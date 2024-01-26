import os
import re
import requests
import signal
import sys
import traceback
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import sleep

# Want to figure out how to do this without a third party module
import eyed3
from eyed3.id3.frames import ImageFrame

# Suppress warnings about CRC fail for cover art
import logging
logging.getLogger('eyed3.mp3.headers').warning = logging.debug


# Cheeky Ctrl+C handler
signal.signal(signal.SIGINT, lambda sig, frame : print('\n\nInterrupt received. Exiting.\n') or sys.exit(0))

DOWNLOADER_URL = "https://api.spotifydown.com"
# Clean browser heads for API
DOWNLOADER_HEADERS = {
    'Host': 'api.spotifydown.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip',
    'Referer': 'https://spotifydown.com/',
    'Origin': 'https://spotifydown.com',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
    'Sec-GPC': '1',
    'TE': 'trailers'
}

PLAYLIST_INPUT_URL_TRACK_NUMS_RE = re.compile(r'^https?:\/\/open\.spotify\.com\/playlist\/[\w]+(?:\?[\w=%-]*|)\|(?P<track_nums>.*)$')

# In interactive mode, user is prompted upon first duplicate encountered
# Otherwise, set via CLI arg
skip_duplicate_downloads = False
skip_duplicate_downloads_prompted = False


@dataclass(frozen=True, eq=True)
class SpotifySong:
    title: str
    artist: str
    album: str
    id: str
    url = f"https://open.spotify.com/track/{id}"


def _get_track_local_title(title: str, artist: str) -> str:
    return f"{title} - {artist}"


def _call_downloader_api(
    endpoint: str,
    method: str = 'GET',
    headers=DOWNLOADER_HEADERS,
    **kwargs
) -> requests.Response:
    _map = {
        'GET': requests.get,
        'POST': requests.post
    }

    if method not in _map:
        raise ValueError

    try:
        resp = _map[method](DOWNLOADER_URL + endpoint, headers=headers, **kwargs)
    except Exception as exc:
        raise RuntimeError("ERROR: ", exc)

    return resp


def get_track_data(track_id: str):
    resp = _call_downloader_api(f"/download/{track_id}")

    resp_json = resp.json()

    if not resp_json['success']:
        # print("[!] Bad URL. No song found.")
        resp_json = {}

    return resp_json


def get_playlist_data(playlist_id: str):
    metadata_resp = _call_downloader_api(f"/metadata/playlist/{playlist_id}").json()

    # For paginated response
    track_list = []

    tracks_resp = _call_downloader_api(f"/trackList/playlist/{playlist_id}").json()
    
    if not tracks_resp.get('trackList'):
        return {}

    track_list.extend(tracks_resp['trackList'])

    while next_offset := tracks_resp.get('nextOffset'):
        tracks_resp = _call_downloader_api(f"/trackList/playlist/{playlist_id}?offset={next_offset}").json()
        track_list.extend(tracks_resp['trackList'])

    if not metadata_resp['success']:
        return {}

    return {
        **metadata_resp,
        'trackList': [
            SpotifySong(
                title=track['title'],
                artist=track['artists'],
                album=track['album'],
                id=track['id']
            )
            for track in track_list
        ]
    }


def get_spotify_playlist(playlist_id: str, token: str):
    # GET to playlist URL can get first 30 songs only
    # soup.find_all('meta', content=re.compile("https://open.spotify.com/track/\w+"))

    playlist_resp = requests.get(
        f'https://api.spotify.com/v1/playlists/{playlist_id}',
        headers={'Authorization': f"Bearer {token}"}
    )

    playlist = playlist_resp.json()

    tracks_list = [
        SpotifySong(
            title=track['track']['name'],
            artist=', '.join(artist['name'] for artist in track['track']['artists']),
            album=track['track']['album']['name'],
            id=track['track']['id']
        )
        for track in playlist['tracks']['items']
    ]

    return playlist['name'], playlist['owner']['display_name'], tracks_list


def track_num_inp_to_ind(given_inp: str, list_len: int) -> list:
    indexes_or_slices = []
    # Remove whitespace
    no_ws = re.sub('\s', '', given_inp)

    for item in no_ws.split(','):

        if item.isnumeric():
            if int(item) > list_len and int(item) >= 1:
                print(f"Track number {item} does not exist.  Last track is number {list_len}")
                continue
            if int(item) <= 0:  #user inputs 0 or less                                         
                continue
            # Subtract one for indexing
            indexes_or_slices.append(str(int(item) - 1))

        elif '-' in item:
            start, end = item.split('-')
            if not start:
                # '-3' --> :3 since that gets the first three tracks, 0, 1, and 2
                indexes_or_slices.append(f":{end}")
            elif not end:
                indexes_or_slices.append(f"{int(start) - 1}:")
            else:
                indexes_or_slices.append(f"{int(start) - 1}:{end}")

        elif item == '*':
            indexes_or_slices.append(':')

        else:
            print(f'    [!] Invalid input: {item}')

    if not indexes_or_slices:
        print(f"    [!] No valid input received: '{given_inp}'. Try again.")

    return indexes_or_slices


def get_playlist_track_nums_input(playlist_tracks: list) -> list:
    track_numbers_inp = None

    while not track_numbers_inp:
        track_numbers_inp = input('\n'
            "    Enter 'show' to list the playlist tracks, the track numbers to download, or '*' to download all:\n"
            "      Example: '1, 4, 15-' to download the first, fourth, and fifteenth to the end\n"
            "  > "
        )

        if 'show' in track_numbers_inp.lower():
            print(
                '\n    ',
                '\n    '.join(f"{ind + 1:>4}| {track.title} - {track.artist}" for ind, track in enumerate(playlist_tracks)),
                '\n',
                sep=''
            )
            track_numbers_inp = None

    return track_numbers_inp


def process_input_url(url: str, interactive: bool) -> list:
    track_id_title_tuples = []

    if "/track/" in url:
        track_resp_json = get_track_data(track_id=url.split('/')[-1].split('?')[0])

        if not track_resp_json:
            print(f"\t[!] Song not found{f' at {url}' if not interactive else ''}.")
            return []

        track_title = _get_track_local_title(track_resp_json['metadata']['title'], track_resp_json['metadata']['artists'])
        print(f"\t{track_title}")

        track_id_title_tuples.append((track_resp_json['metadata']['id'], track_title))

    elif "/playlist/" in url:
        playlist_id = url.split('/')[-1].split('?')[0].split('|')[0]

        # playlist_name, playlist_creator, playlist_tracks = get_spotify_playlist(playlist_id, token)
        playlist_resp_json = get_playlist_data(playlist_id)

        if not playlist_resp_json:
            print(f"\t[!] Playlist not found{f' at {url}' if not interactive else ''} or it is set to Private.")
            return []

        # print(f"\t{playlist_name} - {playlist_creator} ({len(playlist_tracks)} tracks)")
        print(f"\t{playlist_resp_json['title']} - {playlist_resp_json['artists']} ({len(playlist_resp_json['trackList'])} tracks)")

        playlist_tracks = playlist_resp_json['trackList']

        if interactive:
            track_numbers_inp = get_playlist_track_nums_input(playlist_tracks)

            while not (indexes_or_slices := track_num_inp_to_ind(track_numbers_inp, list_len=len(playlist_tracks))):
                track_numbers_inp = get_playlist_track_nums_input(playlist_tracks)

        else:
            if specified_track_nums := PLAYLIST_INPUT_URL_TRACK_NUMS_RE.match(url):
                track_numbers_inp = specified_track_nums.group('track_nums')
            else:
                # Default to downloading whole playlist
                track_numbers_inp = '*'

            indexes_or_slices = track_num_inp_to_ind(track_numbers_inp, list_len=len(playlist_tracks))

            if not indexes_or_slices:
                raise ValueError(
                    f"Invalid track number indentifer(s) given: '{specified_track_nums}'"
                )

        # Process input given for which tracks to download
        playlist_tracks_to_dl = []
        for index_or_slice in indexes_or_slices:

            if index_or_slice.isnumeric():
                playlist_tracks_to_dl.append(playlist_tracks[int(index_or_slice)])
            else:
                playlist_tracks_to_dl.extend(
                    eval(f"playlist_tracks[{index_or_slice}]")
                )

        for track in sorted(dict.fromkeys(playlist_tracks_to_dl), key=playlist_tracks.index):

            track_title = _get_track_local_title(track.title, track.artist)
            print(f"\t{playlist_tracks.index(track) + 1:>4}| {track_title}")

            track_id_title_tuples.append((track.id, track_title))

    else:
        print(f"\t[!] Invalid URL{f' -- {url}' if not interactive else ''}.")
        return []

    return track_id_title_tuples


def download_track(track_id, track_title, dest_dir: Path, interactive: bool, skip_duplicates: bool):
    # Grab a fresh download link since the one was got may have expired
    resp_json = get_track_data(track_id)

    track_filename = re.sub(r'[<>:"/\|?*]', '_', f"{track_title}.mp3")

    if (dest_dir/track_filename).exists():
        if skip_duplicates:
            print(f"Skipping download for '{track_title}'...")
            return

        if interactive:
            dup_song_inp = input(
                f"The song '{track_title}' was already downloaded to {dest_dir.absolute()}.\n"
                "  Would you like to download it again? [y/N]: "
            )

            if not dup_song_inp or dup_song_inp.lower().startswith('n'):
                print("\nSkipping download.\n")

                global skip_duplicate_downloads_prompted

                if not skip_duplicate_downloads_prompted:
                    dup_all_inp = input(
                        "Would you like to ignore all songs that have already been downloaded? [Y/n]: "
                    )

                    if not dup_all_inp or dup_all_inp.lower().startswith('y'):
                        global skip_duplicate_downloads
                        skip_duplicate_downloads = True
                        print("\Skipping all duplicate downloads.\n")

                    skip_duplicate_downloads_prompted = True

                return

    print(f"Downloading: '{track_title}'...")

    # Clean browser heads for API
    hdrs = {
        #'Host': 'cdn[#].tik.live', # <-- set this below
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip',
        'Referer': 'https://spotifydown.com/',
        'Origin': 'https://spotifydown.com',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-GPC': '1'
    }

    if 'link' not in resp_json or 'metadata' not in resp_json:
        print("\tDownload failed.")
        raise RuntimeError(
            f"Bad response for track '{track_title}' ({track_id}): {resp_json}"
        )

    # For audio
    hdrs['Host'] = resp_json['link'].split('/')[2]
    audio_dl_resp = requests.get(resp_json['link'], headers=hdrs)

    with open(dest_dir/track_filename, 'wb') as track_mp3_fp:
        track_mp3_fp.write(audio_dl_resp.content)

    # For cover art
    if cover_art_url := resp_json['metadata'].get('cover'):
        hdrs['Host'] = cover_art_url.split('/')[2]
        cover_resp = requests.get(cover_art_url,headers=hdrs)

        mp3_file = eyed3.load(dest_dir/track_filename)
        if (mp3_file.tag == None):
            mp3_file.initTag()

        mp3_file.tag.images.set(ImageFrame.FRONT_COVER, cover_resp.content, 'image/jpeg')

        mp3_file.tag.save()

    print("\tDone.")

def main():
    print('', '=' * 48, '||          Spotify Song Downloader           ||', '=' * 48, sep='\n', end='\n\n')

    # # Grab token anyway
    # token_resp = requests.get("https://open.spotify.com/get_access_token")
    # # clientId, accessToken
    # token = token_resp.json()['accessToken']

    tracks_to_dl = []

    # No given args
    if len(sys.argv) == 1:
        # Interactive mode
        interactive = True

        print("Enter URL for Spotify track to download, a playlist to download from, or press [ENTER] with an empty line when done.")

        while url := input("> "):
            track_id_title_tuple_list = process_input_url(url, interactive)

            if not track_id_title_tuple_list:
                continue

            tracks_to_dl.extend(track_id_title_tuple_list)

        debug_mode = False

    else:
        # CLI mode
        interactive = False

        parser = ArgumentParser()

        parser.add_argument(
            '-u',
            '--urls',
            nargs='+',
            required=True,
            help="URL(s) of Sptofy songs or playlists to download.  "
                "If a playlist is given, append \"|[TRACK NUMBERS]\" to URL to specify which tracks to download. "
                "Example: 'https://open.spotify.com/playlist/mYpl4YLi5T|1,4,15-' to download the first, fourth, "
                "and fifteenth to the end. If not specified, all tracks are downloaded."
        )
        parser.add_argument(
            '-o',
            '--output',
            type=Path,
            default=Path.home()/"Downloads",
            help="Path to directory where tracks should be downloaded to"
        )
        parser.add_argument(
            '-c',
            '--create-dir',
            action='store_true',
            help="Create the output directory if it does not exist."
        )
        parser.add_argument(
            '-s',
            '--skip-duplicate-downloads',
            action='store_true',
            default=False,
            help="Don't download a song if the file already exists in the output directory."
        )
        parser.add_argument(
            '--debug',
            action='store_true',
            default=False,
            help="Debug mode."
        )

        args = parser.parse_args()

        output_dir = args.output

        if not output_dir.is_dir():
            if args.create_dir:
                output_dir.mkdir(parents=True)
            else:
                raise ValueError(
                    f"Specified directory '{output_dir}' is not a valid directory."
                )

        for url in args.urls:
            track_id_title_tuple_list = process_input_url(url, interactive)

            if not track_id_title_tuple_list:
                continue

            tracks_to_dl.extend(track_id_title_tuple_list)

        global skip_duplicate_downloads
        skip_duplicate_downloads = args.skip_duplicate_downloads
        
        debug_mode = args.debug

    print(f"\nTracks to download: {len(tracks_to_dl)}\n")

    if interactive:
        output_dir = Path.home()/'Downloads'

        print(f"Downloads will go to {output_dir}.  If you would like to change, enter the location or press [ENTER]")

        if other_dir := input("(New download location?) "):
            output_dir = Path(other_dir)

        while not output_dir.is_dir():
            mkdir_inp = input(f"The directory '{output_dir.absolute()}' does not exist.  Would you like to create it? [y/n]: ")
            if mkdir_inp.lower() == 'y':
                output_dir.mkdir(parents=True)
            else:
                output_dir = Path(input("\nNew download location: "))

    print(f"\nDownloading to '{output_dir.absolute()}'.\n")

    print('-' * 32)

    broken_tracks = []
    for track_id, track_title in list(dict.fromkeys(tracks_to_dl)):
        try:
            download_track(track_id, track_title, output_dir, interactive, skip_duplicate_downloads)
        except Exception as exc:
            broken_tracks.append(track_title)
            if debug_mode:
                with open('.spotify_dl_err.txt', 'a') as debug_fp:
                    debug_fp.write(f"{datetime.now()} | {exc} :: {traceback.format_exc()}\n\n")

    print("\nAll done.")

    if broken_tracks:
        nl = '\n'
        print(
            "\n[!] The following tracks could not be downloaded:\n"
            f"  * {f'{nl}  * '.join(broken_tracks)}\n"
        )

    # Give a chance to see the messages if running via executable
    sleep(1)
    print("\nExiting...\n")
    sleep(3)


if __name__ == '__main__':
    main()
