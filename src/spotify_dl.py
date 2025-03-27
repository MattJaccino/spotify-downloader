import json
import os
import re
import signal
import sys
import traceback
from argparse import ArgumentParser
from base64 import b64decode
from configparser import ConfigParser
from datetime import datetime
from pathlib import Path
from time import sleep

# Want to figure out how to do this without a third party module
import requests
from mutagen import File as AudioFile


# Cheeky Ctrl+C handler
signal.signal(signal.SIGINT, lambda sig, frame : print('\n\nInterrupt received. Exiting.\n') or sys.exit(0))

### Cfg file constants
CFG_SECTION_HEADER = "Settings"
CFG_DEFAULT_FILENAME_TEMPLATE_OPTION = "default_filename_template"
CFG_DEFAULT_DOWNLOADER_OPTION = "default_downloader"
CFG_DEFAULT_FILE_TYPE_OPTION = "default_file_type"
CFG_DEFAULT_DOWNLOAD_LOCATION_OPTION = "default_download_location"
CFG_DEFAULT_NUM_RETRY_ATTEMPTS_OPTION = "default_retry_downloads_attempts"
CFG_DEFAULT_DUPLICATE_DOWNLOAD_HANDLING = "duplicate_download_handling"

OUTPUT_DIR_DEFAULT = str(Path.home()/"Downloads")

### DOWNLOADER CONSTANTS ###

# ## Spotifydown constants
# DOWNLOADER_SPOTIFYDOWN = "spotifydown"
# DOWNLOADER_SPOTIFYDOWN_URL = "https://spotifydown.com"
# DOWNLOADER_SPOTIFYDOWN_API_URL = "https://api.spotifydown.com"
# # Clean browser heads for API
# DOWNLOADER_SPOTIFYDOWN_HEADERS = {
#     'Host': 'api.spotifydown.com',
#     'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
#     'Accept': '*/*',
#     'Accept-Language': 'en-US,en;q=0.5',
#     'Accept-Encoding': 'gzip',
#     'Referer': 'https://spotifydown.com/',
#     'Origin': 'https://spotifydown.com',
#     'DNT': '1',
#     'Connection': 'keep-alive',
#     'Sec-Fetch-Dest': 'empty',
#     'Sec-Fetch-Mode': 'cors',
#     'Sec-Fetch-Site': 'same-site',
#     'Sec-GPC': '1',
#     'TE': 'trailers'
# }

# ## Lucida constants
# DOWNLOADER_LUCIDA = "lucida"
# DOWNLOADER_LUCIDA_URL = "https://lucida.su"
# # Can't support formats that aren't available in mutagen
# DOWNLOADER_LUCIDA_FILE_FORMATS = [
#     'original',
#     'mp3-320', 'mp3-256', 'mp3-128',
#     'ogg-vorbis-320', 'ogg-vorbis-256', 'ogg-vorbis-128',
#     'ogg-opus-320', 'ogg-opus-256', 'ogg-opus-128', 'ogg-opus-96', 'ogg-opus-64',
#     #'opus-320', 'opus-256', 'opus-128', 'opus-96', 'opus-64',
#     'flac-16',
#     'm4a-aac-320', 'm4a-aac-256', 'm4a-aac-192', 'm4a-aac-128',
#     #'bitcrush'
# ]
# DOWNLOADER_LUCIDA_FILE_FORMAT_DEFAULT = "mp3-320"
# DOWNLOADER_LUCIDA_HEADERS = {
#     'Host': 'lucida.su',
#     'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
#     'Accept': '*/*',
#     'Accept-Language': 'en-US,en;q=0.5',
#     'Accept-Encoding': 'gzip',
#     'Referer': 'https://spotifydown.com/',
#     'DNT': '1',
#     'Connection': 'keep-alive',
#     'Sec-Fetch-Dest': 'document',
#     'Sec-Fetch-Mode': 'navigate',
#     'Sec-Fetch-Site': 'same-origin',
#     'Sec-GPC': '1'
# }

## SpotifyMate constants
DOWNLOADER_SPOTIFYMATE = "spotifymate"
DOWNLOADER_SPOTIFYMATE_URL = "https://spotifymate.com"
DOWNLOADER_SPOTIFYMATE_HEADERS = {
    "Host": "spotifymate.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip",
    "Referer": "https://spotifymate.com/en",
    "Origin": "https://spotifymate.com",
    "DNT": "1",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Connection": "keep-alive",
    "Alt-Used": "spotifymate.com",
    "Sec-GPC": "1",
    "Priority": "u=0"
}

DOWNLOADER_OPTIONS = [DOWNLOADER_SPOTIFYMATE] # [DOWNLOADER_LUCIDA, DOWNLOADER_SPOTIFYDOWN, DOWNLOADER_SPOTIFYMATE]
DOWNLOADER_DEFAULT = DOWNLOADER_SPOTIFYMATE # DOWNLOADER_LUCIDA

MULTI_TRACK_INPUT_URL_TRACK_NUMS_RE = re.compile(r'^https?:\/\/open\.spotify\.com\/(album|playlist)\/[\w]+(?:\?[\w=%-]*|)\|(?P<track_nums>.*)$')

FILENAME_TEMPLATE_VARS = ["title", "artist", "album", "track_num"]
FILENAME_TEMPLATE_DEFAULT = r"{title} - {artist}"

# In interactive mode, user is prompted upon first duplicate encountered
# Otherwise, set via CLI arg
DUPLICATE_DOWNLOAD_CHOICES = ["skip", "overwrite", "append_number"]
DUPLICATE_DOWNLOAD_CHOICE_DEFAULT = "skip"
duplicate_downloads_action = DUPLICATE_DOWNLOAD_CHOICE_DEFAULT
duplicate_downloads_prompted = False


##### Spotify stuff #####

def _get_spotify_token() -> str:
    token_resp = requests.post(
        url="https://accounts.spotify.com/api/token?grant_type=client_credentials&client_id="
            f"{os.getenv('SPOTIFY_CLIENT_ID', input('Enter Spotify client ID: '))}"
            f"&client_secret={os.getenv('SPOTIFY_CLIENT_SECRET', input("Enter Spotify client secret: "))}", #"https://open.spotify.com/get_access_token",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0", "Content-Type": "application/x-www-form-urlencoded"}
    )
    return token_resp.json()['access_token']


class SpotifySong:
    def __init__(
        self,
        title: str,
        artist: str,
        album: str,
        id: str,
        track_number: str = "0",
        cover_art_url: str = "",
        release_date: str = ""
    ):
        self.title = title
        self.artist = artist
        self.album = album
        self.track_number = str(track_number)
        self.id = id
        self.cover_art_url = cover_art_url
        self.release_date = release_date
        self.url = f"https://open.spotify.com/track/{self.id}"

    def __eq__(self, other):
        return self.url == other.url

    def __hash__(self):
        return hash(self.url)


class SpotifyAlbum:
    def __init__(
        self,
        title: str,
        artist: str,
        tracks: list,
        id: str,
        cover_art_url: str,
        release_date: str
    ):
        self.title = title
        self.artist = artist
        self.tracks = tracks
        self.id = id
        self.cover_art_url = cover_art_url
        self.release_date = release_date
        self.url = f"https://open.spotify.com/album/{self.id}"

    def __eq__(self, other):
        return self.url == other.url


class SpotifyPlaylist:
    def __init__(
        self,
        name: str,
        owner: str,
        tracks: list,
        id: str,
        cover_art_url: str
    ):
        self.name = name
        self.owner = owner
        self.tracks = tracks
        self.id = id
        self.cover_art_url = cover_art_url
        self.url = f"https://open.spotify.com/playlist/{self.id}"

    def __eq__(self, other):
        return self.url == other.url


def get_spotify_track(track_id: str, token: str) -> SpotifySong:
    # GET to playlist URL can get first 30 songs only
    # soup.find_all('meta', content=re.compile("https://open.spotify.com/track/\w+"))

    track_resp = requests.get(
        f'https://api.spotify.com/v1/tracks/{track_id}',
        headers={'Authorization': f"Bearer {token}"}
    )

    track = track_resp.json()

    return SpotifySong(
        title=track['name'],
        artist=', '.join(artist['name'] for artist in track['artists']),
        album=track['album']['name'],
        id=track['id'],
        track_number=track['track_number'],
        cover_art_url=track['album']['images'][0]['url'] if len(track['album'].get('images', [])) else None,
        release_date=track['album']['release_date']
    )


def get_spotify_album(album_id: str, token: str) -> SpotifyAlbum:
    # GET to playlist URL can get first 30 songs only
    # soup.find_all('meta', content=re.compile("https://open.spotify.com/track/\w+"))

    album_resp = requests.get(
        f'https://api.spotify.com/v1/albums/{album_id}',
        headers={'Authorization': f"Bearer {token}"}
    )

    album = album_resp.json()

    # Same for all tracks
    cover_art_url = album['images'][0]['url'] if len(album.get('images', [])) else None
    release_date = album['release_date']

    tracks_list = [
        SpotifySong(
            title=track['name'],
            artist=', '.join(artist['name'] for artist in track['artists']),
            album=album['name'],
            id=track['id'],
            track_number=track['track_number'],
            cover_art_url=cover_art_url,
            release_date=release_date
        )
        for track in album['tracks']['items']
        if track
    ]

    return SpotifyAlbum(
        title=album['name'],
        artist=', '.join(artist['name'] for artist in album['artists']),
        tracks=tracks_list,
        id=album['id'],
        cover_art_url=cover_art_url,
        release_date=release_date
    )


def get_spotify_playlist(playlist_id: str, token: str) -> SpotifyPlaylist:
    # GET to playlist URL can get first 30 songs only
    # soup.find_all('meta', content=re.compile("https://open.spotify.com/track/\w+"))

    playlist_resp = requests.get(
        f'https://api.spotify.com/v1/playlists/{playlist_id}',
        headers={'Authorization': f"Bearer {token}"}
    )

    playlist = playlist_resp.json()
    playlist_tracks = playlist.get('tracks', [])

    tracks_list = [
        SpotifySong(
            title=track_data['track']['name'],
            artist=', '.join(artist['name'] for artist in track_data['track']['artists']),
            album=track_data['track']['album']['name'],
            id=track_data['track']['id'],
            track_number=track_data['track']['track_number'],
            cover_art_url=track_data['track']['album']['images'][0]['url'] if len(track_data['track']['album'].get('images', [])) else None,
            release_date=track_data['track']['album']['release_date']
        )
        for track_data in playlist_tracks['items']
        if track_data['track']
    ]

    while next_chunk_url := playlist_tracks.get('next'):
        playlist_resp = requests.get(
            next_chunk_url,
            headers={'Authorization': f"Bearer {token}"}
        )

        playlist_tracks = playlist_resp.json()

        tracks_list.extend(
            SpotifySong(
                title=track_data['track']['name'],
                artist=', '.join(artist['name'] for artist in track_data['track']['artists']),
                album=track_data['track']['album']['name'],
                id=track_data['track']['id'],
                track_number=track_data['track']['track_number'],
                cover_art_url=track_data['track']['album']['images'][0]['url'] if len(track_data['track']['album'].get('images', [])) else None,
                release_date=track_data['track']['album']['release_date']
            )
            for track_data in playlist_tracks['items']
            if track_data['track']
        )

    return SpotifyPlaylist(
        name=playlist['name'],
        owner=playlist['owner']['display_name'],
        tracks=tracks_list,
        id=playlist_id,
        cover_art_url=playlist['images'][0]['url'] if len(playlist.get('images', [])) else None
    )

###################

def _validate_filename_template(given_str: str, required: bool = True):
    if not any(var in given_str for var in FILENAME_TEMPLATE_VARS) \
            and required:
        raise ValueError(
            "Filename should contain at least one of the following to "
            "prevent files from being overwritten: "
            f"{', '.join('{' + var + '}' for var in FILENAME_TEMPLATE_VARS)}"
        )
    for detected_var in re.findall(r"{(\w+)}", given_str):
        if detected_var not in FILENAME_TEMPLATE_VARS:
            raise ValueError(
                "Variable in filename template of not one of "
                f"{', '.join(map(repr, FILENAME_TEMPLATE_VARS))}. Found: '{detected_var}'"
            )


def validate_config_file(config_file: Path) -> list:
    allowed_args = {
        'url': (str, None),
        'output_dir': (str, None),
        'create_dir': (bool, None),
        'skip_duplicate_downloads': (bool, None),
        'duplicate_download_handling': (str, DUPLICATE_DOWNLOAD_CHOICES),
        'filename_template': (str, None),
        # 'file_type': (str, DOWNLOADER_LUCIDA_FILE_FORMATS)
    }

    with open(config_file) as config_fp:
        loaded_config = json.load(config_fp)

    if not isinstance(loaded_config, list):
        raise RuntimeError("Config file must be a list")

    for e_idx, entry in enumerate(loaded_config, start=1):
        for key in entry:
            if key not in allowed_args:
                raise ValueError(
                    f"Key '{key}' in entry {e_idx} is not valid.  "
                    f"Allowed keys are: {', '.join(allowed_args.keys())}"
                )
            elif not isinstance(entry[key], allowed_args[key][0]):
                raise ValueError(
                    f"Key '{key}' in entry {e_idx} is the wrong type.  "
                    f"Argument for '{key}' must be of type '{allowed_args[key]}'"
                )

            # specific validation
            elif (allowed_values := allowed_args[key][1]) \
                    and entry[key] not in allowed_values:
                raise ValueError(
                    f"Value for key '{key}' in entry {e_idx} is "
                    f"not one of {' ,'.join(allowed_values)}"
                )

    return loaded_config


def parse_cfg(cfg_path: Path) -> ConfigParser:
    parser = ConfigParser()

    # just in case
    if not isinstance(cfg_path, Path):
        cfg_path = Path(str(cfg_path))

    if not cfg_path.is_file():
        return parser

    try:
        parser.read(cfg_path)
    except Exception as exc:
        print(
            f"[!] Cfg file at {cfg_path.absolute()} received a parsing error: {exc}"
        )
        sys.exit(1)

    # validate

    if CFG_SECTION_HEADER not in parser:
        print(
            f"[!] Cfg file at {cfg_path.absolute()} does not contain section '{CFG_SECTION_HEADER}'."
        )
        sys.exit(1)

    if default_filename_template := parser.get(CFG_SECTION_HEADER, CFG_DEFAULT_FILENAME_TEMPLATE_OPTION, fallback=None):
        try:
            _validate_filename_template(default_filename_template)
        except Exception as exc:
            print(
                f"[!] Cfg file at {cfg_path.absolute()} has an invalid value for "
                f"'{CFG_DEFAULT_FILENAME_TEMPLATE_OPTION}': {exc}."
            )
            sys.exit(1)

    if (default_downloader := parser.get(CFG_SECTION_HEADER, CFG_DEFAULT_DOWNLOADER_OPTION, fallback=None)) \
            and (default_downloader_lower := default_downloader.lower()) not in DOWNLOADER_OPTIONS:
        print(
            f"[!] Cfg file at {cfg_path.absolute()} has an invalid value for "
            f"'{CFG_DEFAULT_DOWNLOADER_OPTION}': '{default_downloader_lower}' "
            f"is not one of {', '.join(DOWNLOADER_OPTIONS)}."
        )
        sys.exit(1)

    # if (default_file_type := parser.get(CFG_SECTION_HEADER, CFG_DEFAULT_FILE_TYPE_OPTION, fallback=None)) \
    #         and (file_type_lower := default_file_type.lower()) not in DOWNLOADER_LUCIDA_FILE_FORMATS:
    #     print(
    #         f"[!] Cfg file at {cfg_path.absolute()} has an invalid value for "
    #         f"'{CFG_DEFAULT_FILE_TYPE_OPTION}': '{file_type_lower}' "
    #         f"is not one of {', '.join(DOWNLOADER_LUCIDA_FILE_FORMATS)}"
    #     )
    #     sys.exit(1)

    # if (default_download_location := parser.get(CFG_SECTION_HEADER, CFG_DEFAULT_DOWNLOAD_LOCATION_OPTION, fallback=None)) \
    #         and not Path(default_download_location).is_dir():
    #     print(
    #         f"[!] Cfg file at {cfg_path.absolute()} has an invalid value for "
    #         f"'{CFG_DEFAULT_DOWNLOAD_LOCATION_OPTION}': '{default_download_location}' "
    #         f"was not found."
    #     )
    #     sys.exit(1)

    if (default_num_retries := parser.get(CFG_SECTION_HEADER, CFG_DEFAULT_NUM_RETRY_ATTEMPTS_OPTION, fallback=None)) \
            and not str(default_num_retries).isnumeric():
        print(
            f"[!] Cfg file at {cfg_path.absolute()} has an invalid value for "
            f"'{CFG_DEFAULT_NUM_RETRY_ATTEMPTS_OPTION}': '{default_num_retries}' "
            f"is not an integer."
        )
        sys.exit(1)

    if (dup_dl_handling := parser.get(CFG_SECTION_HEADER, CFG_DEFAULT_DUPLICATE_DOWNLOAD_HANDLING, fallback=None)) \
            and not dup_dl_handling in (allowed_vals := DUPLICATE_DOWNLOAD_CHOICES):
        print(
            f"[!] Cfg file at {cfg_path.absolute()} has an invalid value for "
            f"'{CFG_DEFAULT_DUPLICATE_DOWNLOAD_HANDLING}': '{dup_dl_handling}' "
            f"is not one of {', '.join(allowed_vals)}."
        )
        sys.exit(1)

    print(f"[-] Using user's .cfg file at {cfg_path.absolute()}.\n")

    return parser


def get_filename_template_from_user(spotify_dl_cfg: ConfigParser) -> str:
    default_filename_template = spotify_dl_cfg.get(CFG_SECTION_HEADER, CFG_DEFAULT_FILENAME_TEMPLATE_OPTION, fallback=FILENAME_TEMPLATE_DEFAULT)

    print(
        "\nIf you would like to use a different naming pattern for the file, enter it now.\n"
        f"Variables allowed: {', '.join(FILENAME_TEMPLATE_VARS)}.  "
        r"Must be contained in curly braces {}"
        f"\n\nDefault: \"{default_filename_template}\"\n\n"
    )

    # loop until we get something we can use
    while 1:
        filename_resp = input(
            "Filename or press [ENTER] to use default: "
        )

        if not filename_resp:
            return default_filename_template

        try:
            _validate_filename_template(filename_resp)
        except ValueError as exc:
            print(f"'{filename_resp}' is invalid - {exc}")
        else:
            return filename_resp


def get_downloader_from_user(spotify_dl_cfg: ConfigParser) -> str:
    default_downloader = spotify_dl_cfg.get(CFG_SECTION_HEADER, CFG_DEFAULT_DOWNLOADER_OPTION, fallback=DOWNLOADER_DEFAULT)

    print(
        "\nIf you would like to use a different download source, enter it now.\n"
        f"Server options: {', '.join(DOWNLOADER_OPTIONS)}."
        f"\n\nDefault: \"{default_downloader}\"\n\n"
    )

    # loop until we get something we can use
    while 1:
        downloader_resp = input(
            f"Select {' or '.join(map(repr, DOWNLOADER_OPTIONS))} or press [ENTER] to use default: "
        )

        if not downloader_resp:
            return default_downloader

        if (downloader_resp_lower := downloader_resp.lower()) not in DOWNLOADER_OPTIONS:
            print(f"'{downloader_resp_lower}' is not one of {', '.join(DOWNLOADER_OPTIONS)}")
        else:
            return downloader_resp_lower


# def get_file_type_from_user(spotify_dl_cfg: ConfigParser) -> str:
#     default_file_type = spotify_dl_cfg.get(CFG_SECTION_HEADER, CFG_DEFAULT_FILE_TYPE_OPTION, fallback=DOWNLOADER_LUCIDA_FILE_FORMAT_DEFAULT)

#     print(
#         "\nIf you would like to download using a different audio format, enter it now.\n"
#         f"Formats allowed: {', '.join(DOWNLOADER_LUCIDA_FILE_FORMATS)}.\n\n"
#         f"Default: \"{default_file_type}\"\n\n"
#     )

#     # loop until we get something we can use
#     while 1:
#         file_type_resp = input(
#             "File format or press [ENTER] to use default: "
#         )

#         if not file_type_resp:
#             return default_file_type

#         if (file_type_lower := file_type_resp.lower()) not in DOWNLOADER_LUCIDA_FILE_FORMATS:
#             print(f"'{file_type_lower}' is not one of {', '.join(DOWNLOADER_LUCIDA_FILE_FORMATS)}")
#         else:
#             return file_type_lower


def assemble_str_from_template(
    track: SpotifySong,
    template: str,
    required: bool = True
) -> str:
    if not template:
        template = FILENAME_TEMPLATE_DEFAULT
    else:
        _validate_filename_template(template, required)

    template = template \
        .replace(r"{track_num}", track.track_number) \
        .replace(r"{title}", track.title) \
        .replace(r"{album}", track.album) \
        .replace(r"{artist}", track.artist)

    return template


def set_output_dir(
    interactive: bool,
    spotify_dl_cfg: ConfigParser,
    output_dir: str,
    track: SpotifySong = None,
    create_dir: bool = False,
    prompt_for_new_location: bool = True,
    check_dir_exists: bool = True
) -> Path:
    default_output_dir = spotify_dl_cfg.get(CFG_SECTION_HEADER, CFG_DEFAULT_DOWNLOAD_LOCATION_OPTION, fallback=output_dir)

    # specified output dir takes precedence if it's not the default
    if output_dir != OUTPUT_DIR_DEFAULT:
        default_output_dir = output_dir

    if interactive:
        if track:
            output_dir = Path(assemble_str_from_template(track, str(default_output_dir), required=False))
        else:
            output_dir = Path(default_output_dir)

        if prompt_for_new_location:
            print(f"Downloads will go to {output_dir}.  If you would like to change, enter the location or press [ENTER]")

            if other_dir := input("(New download location?) "):
                output_dir = Path(other_dir)

        if check_dir_exists:
            while not output_dir.is_dir():
                mkdir_inp = input(f"The directory '{output_dir.absolute()}' does not exist.  Would you like to create it? [y/n]: ")
                if mkdir_inp.lower() == 'y':
                    output_dir.mkdir(parents=True)
                else:
                    output_dir = Path(input("\nNew download location: "))

    else:
        if track:
            output_dir = Path(assemble_str_from_template(track, str(output_dir), required=False))
        else:
            output_dir = Path(default_output_dir)

        if check_dir_exists and not output_dir.is_dir():
            if create_dir:
                output_dir.mkdir(parents=True)
            else:
                raise ValueError(
                    f"Specified directory '{output_dir}' is not a valid directory."
                )

    return output_dir


# def _download_track_spotifydown(track: SpotifySong) -> requests.Response:
#     session = requests.Session()

#     session.send(
#         requests.Request(
#             method="GET",
#             url=DOWNLOADER_SPOTIFYDOWN_URL,
#             headers={
#                 "Host": "spotifydown.com",
#                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
#                 "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
#                 "Accept-Language": "en-US,en;q=0.5",
#                 "Accept-Encoding": "gzip",
#                 "DNT": "1",
#                 "Alt-Used": "spotifydown.com",
#                 "Connection": "keep-alive",
#                 "Referer": "https://spotifydown.com/",
#                 "Upgrade-Insecure-Requests": "1",
#                 "Sec-Fetch-Dest": "document",
#                 "Sec-Fetch-Mode": "navigate",
#                 "Sec-Fetch-Site": "same-origin",
#                 "Sec-Fetch-User": "?1",
#                 "Sec-GPC": "1",
#                 "Priority": "u=0, i",
#                 "TE": "trailers"
#             }
#         ).prepare()
#     )

#     try:
#         resp = requests.get(f"{DOWNLOADER_SPOTIFYDOWN_API_URL}/download/{track.id}", headers=DOWNLOADER_SPOTIFYDOWN_HEADERS)
#     except Exception as exc:
#         raise RuntimeError("ERROR: ", exc)

#     resp_json = resp.json()

#     if not resp_json['success']:
#         raise RuntimeError(f"Error: {resp.status_code} - {resp_json}")

#     # Clean browser heads for API
#     hdrs = {
#         #'Host': 'cdn[#].tik.live', # <-- set this below
#         'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
#         'Accept': '*/*',
#         'Accept-Language': 'en-US,en;q=0.5',
#         'Accept-Encoding': 'gzip',
#         'Referer': 'https://spotifydown.com/',
#         'Origin': 'https://spotifydown.com',
#         'DNT': '1',
#         'Connection': 'keep-alive',
#         'Sec-Fetch-Dest': 'empty',
#         'Sec-Fetch-Mode': 'cors',
#         'Sec-Fetch-Site': 'cross-site',
#         'Sec-GPC': '1'
#     }

#     if 'link' not in resp_json or 'metadata' not in resp_json:
#         raise RuntimeError(
#             f"Bad metadata response for track '{track.artist} - {track.title}': {resp_json}"
#         )

#     hdrs['Host'] = resp_json['link'].split('/')[2]
#     return requests.get(resp_json['link'], headers=hdrs)


# def _download_track_lucida(track_url: str, file_format=DOWNLOADER_LUCIDA_FILE_FORMAT_DEFAULT) -> requests.Response:
#     # Per lemonbar, send max 10 reqs / min, and we already sleep for 1 below.
#     file_format = file_format.lower()

#     if file_format not in DOWNLOADER_LUCIDA_FILE_FORMATS:
#         raise ValueError(f"File format '{file_format}' is not one of {', '.join(DOWNLOADER_LUCIDA_FILE_FORMATS)}")

#     # Grab token from response from Lucida server
#     metadata_req = requests.get(
#         url=f"https://lucida.su/?url={track_url}&country=auto",
#         headers={
#             'Host': "lucida.su",
#             'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
#             'Accept': "text/html",#,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,image/svg+xml,*/*;q=0.8",
#             'Accept-Language': "en-US,en;q=0.5",
#             'Accept-Encoding': "gzip",#, deflate, br, zstd",
#             'Referer': "https://lucida.su/",
#             'DNT': "1",
#             'Connection': "keep-alive",
#             #'Cookie': "cf_clearance=SyaHxXD5M7mLGW9vlS.ljeBiNBa3LMeyZK9AtBrtkT8-1729096731-1.2.1.1-uPEurBb9v0qWI3ifgmnVR7WCRHGqZbDpXpPkdTIEO_qilE9ymDegpxxWYEs.waLo4WKsVany3LOufnDbSi9XyMhLhFWJm4.b3i12MBufpazy0I_AWnBsxBmrxy3EkZjwknlH3xNrR6WZX_JOGCZQJSjO_ooadSuz1VOMWzDZiDdJG52EXvEAgyftXPgBaHb7FS578mMRP9FASKesfre7amhF9wIvq1Upxgk9lIH_O2DMRbNjk1q4d32wawHiFc_DMXUx76_Cw05ZRCjijMujIeaxMcQ1YzhuEjN4yRGc4X7PrJkd2NBxt1T5Jy6_U1yEixuQGoGzVNf8KW5bTyeNUJ0omMczVqr80_uyW.bmw_E",
#             'Upgrade-Insecure-Requests': "1",
#             'Sec-Fetch-Dest': "document",
#             'Sec-Fetch-Mode': "navigate",
#             'Sec-Fetch-Site': "same-origin",
#             'Sec-Fetch-User': "?1",
#             'Sec-GPC': "1",
#             'Priority': "u=0, i"
#         },
#         allow_redirects=True,
#     )

#     metadata_req_content_str = metadata_req.content.decode('utf-8', errors='ignore')

#     token = re.search(r"token:\s?\"([\w-]+)\",\s?tokenExpiry:\s?(\d+)", metadata_req_content_str)

#     if not token:
#         with open('err.html', 'wb') as f:
#             f.write(metadata_req.content)
#         raise RuntimeError("Unable to locate token for Lucida", metadata_req.status_code, metadata_req_content_str)

#     dl_target_req = requests.post(
#         url="https://lucida.su/api/load?url=%2Fapi%2Ffetch%2Fstream%2Fv2",
#         json={
#             "url": track_url,
#             "metadata": True,
#             "private": True,
#             "handoff": True,
#             "account": {"type": "country", "id": "auto"},
#             "upload": {"enabled": False, "service": "pixeldrain"},
#             # downscale args: mp3-320, mp3-256, mp3-128, ogg-320, ogg-256, ogg-128, ...
#             "downscale": file_format,
#             "token": {
#                 # double b64-decoded str
#                 "primary": b64decode(b64decode(token.group(1).encode())).decode(),
#                 "expiry": token.group(2)
#             }
#         },
#         headers={
#             "Referer": metadata_req.url,
#             "Origin": "https://lucida.su"
#         }
#     )

#     if not dl_target_req.ok:
#         raise RuntimeError(f"Bad dl target response: [{dl_target_req.status_code}] {dl_target_req.content.decode()}")

#     dl_target_req_json = dl_target_req.json()

#     if not dl_target_req_json.get('success'):
#         raise RuntimeError(f"Bad dl target JSON response: [{dl_target_req.status_code}] {dl_target_req.content.decode()}")

#     resp = requests.get(
#         f"https://lucida.su/api/load?url=%2Fapi%2Ffetch%2Frequest%2F{dl_target_req_json['handoff']}&force={dl_target_req_json['name']}",
#         allow_redirects=False
#     )

#     if not resp.ok:
#         raise RuntimeError(f"Bad response from API load: [{resp.status_code}] {resp.content.decode()}")

#     sleep(1)

#     try:
#         resp = requests.get(resp.url)
#         while resp.json()['status'] != "completed": #in ["ripping", "metadata", "downscale"]:
#             sleep(1)
#             resp = requests.get(resp.url)
#     except Exception as exc:
#         raise RuntimeError(f"Unexpected error during download: {exc} -- [{resp.status_code}] {resp.content.decode()}")

#     return requests.get(
#         f"https://{dl_target_req_json['name']}.lucida.su/api/fetch/request/{dl_target_req_json['handoff']}/download"
#     )

def _download_track_spotifymate(track_url: str) -> requests.Response:
    session = requests.Session()
    page_resp = session.send(requests.Request('GET',"https://spotifymate.com/en").prepare())

    token_re=re.compile(r"Paste URL from Spotify.*\s*<input name=\"([\w_-]+)\" type=\"hidden\" value=\"(\w+)\" />")

    token=token_re.search(page_resp.content.decode())

    if not token:
        raise RuntimeError("Token not found in response for Spotifymate title page.")

    track_search_req = requests.Request(
        method='POST',
        url="https://spotifymate.com/action",
        files={
            'url':(None, track_url),
            token.group(1): (None, token.group(2))
        },
        headers=DOWNLOADER_SPOTIFYMATE_HEADERS,
        cookies=page_resp.cookies
    )

    r2 = session.send(track_search_req.prepare())

    dl_re = re.compile(r"href=\"([\w\?:/.=]+)\".*Download Mp3")

    dl_url = dl_re.search(r2.content.decode())

    if not dl_url:
        raise RuntimeError("Download URL not found in response.")


    return session.send(
        requests.Request(
            method='GET',
            url=dl_url.group(1),
            headers=DOWNLOADER_SPOTIFYMATE_HEADERS
        ).prepare()
    )

def get_tracks_to_download(
    interactive: bool,
    filename_template: str,
    spotify_token: str,
    cli_arg_urls: list = None
) -> list:
    tracks_to_dl = []

    if interactive:
        print("Enter URL for Spotify track to download, a playlist to download from, or press [ENTER] with an empty line when done.")

        while url := input("> "):
            track_obj_title_tuple_list = process_input_url(url, filename_template, interactive, spotify_token)

            if not track_obj_title_tuple_list:
                continue

            tracks_to_dl.extend(track_obj_title_tuple_list)

    else:
        for url in cli_arg_urls:
            track_obj_title_tuple_list = process_input_url(url, filename_template, interactive, spotify_token)

            if not track_obj_title_tuple_list:
                continue

            tracks_to_dl.extend(track_obj_title_tuple_list)

    return tracks_to_dl


def track_num_inp_to_ind(given_inp: str, list_len: int) -> list:
    indexes_or_slices = []
    # Remove whitespace
    no_ws = re.sub(r'\s', '', given_inp)

    for item in no_ws.split(','):

        if item.isnumeric(): # ensure the user inputs a valid number in the playlist range
            if not 1 <= int(item) <= list_len:
                print(f"Track number {item} does not exist.  Valid numbers are 1 - {list_len}")
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


def get_track_nums_input(tracks: list, entity_type: str) -> list:
    track_numbers_inp = None

    while not track_numbers_inp:
        track_numbers_inp = input('\n'
            f"    Enter 'show' to list the {entity_type} tracks, the track numbers to download, or '*' to download all:\n"
            "      Example: '1, 4, 15-' to download the first, fourth, and fifteenth to the end\n"
            "  > "
        )

        if 'show' in track_numbers_inp.lower():
            print(
                '\n    ',
                '\n    '.join(f"{ind + 1:>4}| {track.title} - {track.artist}" for ind, track in enumerate(tracks)),
                '\n',
                sep=''
            )
            track_numbers_inp = None

    return track_numbers_inp


def process_input_url(url: str, filename_template: str, interactive: bool, spotify_token: str) -> list:
    track_obj_title_tuples = []

    if "/track/" in url:
        track_obj = get_spotify_track(track_id=url.split('/')[-1].split('?')[0], token=spotify_token)

        if not track_obj:
            print(f"\t[!] Song not found{f' at {url}' if not interactive else ''}.")
            return []

        out_file_title = assemble_str_from_template(
            track=track_obj,
            template=filename_template
        )

        print(f"\t{out_file_title}")

        track_obj_title_tuples.append((track_obj, out_file_title))

    elif "/playlist/" in url or "/album/" in url:
        entity_id = url.split('/')[-1].split('?')[0].split('|')[0]

        if "/playlist/" in url:
            entity_type = "playlist"
            multi_track_obj = get_spotify_playlist(playlist_id=entity_id, token=spotify_token)
        else:
            entity_type = "album"
            multi_track_obj = get_spotify_album(album_id=entity_id, token=spotify_token)

        if not multi_track_obj:
            print(
                f"\t[!] {entity_type.capitalize()} not found{f' at {url}' if not interactive else ''}"
                f"{' or it is set to Private' if entity_type == 'playlist' else ''}."
            )
            return []

        if isinstance(multi_track_obj, SpotifyAlbum):
            print(f"\t{multi_track_obj.title} - {multi_track_obj.artist} ({len(multi_track_obj.tracks)} tracks)")
        else:
            print(f"\t{multi_track_obj.name} - {multi_track_obj.owner} ({len(multi_track_obj.tracks)} tracks)")

        album_or_playlist_tracks = multi_track_obj.tracks

        if interactive:
            track_numbers_inp = get_track_nums_input(album_or_playlist_tracks, entity_type)

            while not (indexes_or_slices := track_num_inp_to_ind(track_numbers_inp, list_len=len(album_or_playlist_tracks))):
                track_numbers_inp = get_track_nums_input(album_or_playlist_tracks, entity_type)

        else:
            if specified_track_nums := MULTI_TRACK_INPUT_URL_TRACK_NUMS_RE.match(url):
                track_numbers_inp = specified_track_nums.group('track_nums')
            else:
                # Default to downloading whole playlist/album
                track_numbers_inp = '*'

            indexes_or_slices = track_num_inp_to_ind(track_numbers_inp, list_len=len(album_or_playlist_tracks))

            if not indexes_or_slices:
                raise ValueError(
                    f"Invalid track number indentifer(s) given: '{specified_track_nums}'"
                )

        # Process input given for which tracks to download
        tracks_to_dl = []
        for index_or_slice in indexes_or_slices:

            if index_or_slice.isnumeric():
                tracks_to_dl.append(album_or_playlist_tracks[int(index_or_slice)])
            else:
                tracks_to_dl.extend(
                    eval(f"album_or_playlist_tracks[{index_or_slice}]")
                )

        for track in sorted(tracks_to_dl, key=album_or_playlist_tracks.index):

            # pad with 0s based on length of str of number of tracks in album/playlist
            track_num = str(album_or_playlist_tracks.index(track) + 1).zfill(len(str(len(album_or_playlist_tracks))))

            track.track_number = track_num

            out_file_title = assemble_str_from_template(
                track=track,
                template=filename_template
            )

            print(f"\t{album_or_playlist_tracks.index(track) + 1:>4}| {out_file_title}")

            track_obj_title_tuples.append((track, out_file_title))

    else:
        print(f"\t[!] Invalid URL{f' -- {url}' if not interactive else ''}.")
        return []

    return track_obj_title_tuples


def download_track(
    track: SpotifySong,
    spotify_dl_cfg: ConfigParser,
    out_file_title: str,
    output_dir: str,
    create_dir: bool,
    downloader: str = DOWNLOADER_DEFAULT,
    # file_type: str = DOWNLOADER_LUCIDA_FILE_FORMAT_DEFAULT,
    interactive: bool = False,
    duplicate_download_handling: str = DUPLICATE_DOWNLOAD_CHOICE_DEFAULT,
    skip_duplicates: bool = False
):
    # if downloader == DOWNLOADER_LUCIDA:
    #     # This might come back to bite me in the ass. need to infer file type
    #     file_ext = file_type.split('-')[0] if file_type != 'original' else "ogg"
    # else:
    file_ext = "mp3"

    track_filename = re.sub(r'[<>:"/\|\\?*]', '_', f"{out_file_title}.{file_ext}")

    global duplicate_downloads_action
    global duplicate_downloads_prompted

    dest_dir = set_output_dir(
        interactive=interactive,
        track=track,
        spotify_dl_cfg=spotify_dl_cfg,
        output_dir=output_dir,
        create_dir=create_dir,
        prompt_for_new_location=False,
        check_dir_exists=True
    )

    if (dest_dir/track_filename).exists():
        # Use user's defined handling if there is one
        if dup_dl_handling := spotify_dl_cfg.get(CFG_SECTION_HEADER, CFG_DEFAULT_DUPLICATE_DOWNLOAD_HANDLING, fallback=None):

            print("Using action defined in .cfg...")

            duplicate_downloads_action = dup_dl_handling

            # don't prompt the user
            duplicate_downloads_prompted = True

        if (duplicate_download_handling == "skip") \
                or skip_duplicates \
                or (duplicate_downloads_action == "skip"):
            print(f"Skipping download for '{out_file_title}'...")
            return

        if interactive and not duplicate_downloads_prompted:
            dup_song_inp = input(
                f"The song '{out_file_title}' was already downloaded to {dest_dir.absolute()}.\n"
                "  Would you like to download it again? [y/N]: "
            )

            if skip_this_dl := (not dup_song_inp or dup_song_inp.lower().startswith('n')):
                print("\nSkipping download.\n")
                # Prompt user if we haven't yet before skipping this one

            if not duplicate_downloads_prompted:
                dup_all_inp = input(
                    "  Would you like to re-download songs that have already been downloaded? [y/N]: "
                )

                if not dup_all_inp or dup_all_inp.lower().startswith('n'):
                    duplicate_downloads_action = "skip"
                    print("\nSkipping duplicate downloads.\n")
                elif dup_all_inp.lower().startswith('y'):
                    dup_append_inp = input(
                        "  Would you like to append a number to filenames for songs that have already been downloaded? [y/N]: "
                    )
                    if not dup_append_inp or dup_append_inp.lower().startswith('n'):
                        duplicate_downloads_action = "overwrite"
                        print("\nRe-downloading all tracks.\n")
                    else:
                        duplicate_downloads_action = "append_number"
                        print("\nRe-downloading all tracks but not overwriting.\n")

                duplicate_downloads_prompted = True

            if skip_this_dl:
                return

        if duplicate_downloads_action == "append_number":
            num = 0
            while (dest_dir/track_filename).exists():
                num += 1
                track_filename = re.sub(r'[<>:"/\|\\?*]', '_', f"{out_file_title} ({num}).{file_ext}")

    print(f"Downloading: '{out_file_title}'...")

    if downloader == DOWNLOADER_SPOTIFYMATE:
        audio_dl_resp = _download_track_spotifymate(track_url=track.url)

    # elif downloader == DOWNLOADER_LUCIDA:
    #     audio_dl_resp = _download_track_lucida(track_url=track.url, file_format=file_type)

    # elif downloader == DOWNLOADER_SPOTIFYDOWN:
    #     audio_dl_resp = _download_track_spotifydown(track=track)

    else:
        raise ValueError(f"Unrecognized downloader: '{downloader}'")

    # Lucida returns HTML when it has a problem
    if not audio_dl_resp.ok \
            or audio_dl_resp.content.startswith(b"<!doctype html>"):
        raise RuntimeError(
            f"Bad download response for track '{out_file_title}': [{audio_dl_resp.status_code}] {audio_dl_resp.content}"
        )

    with open(dest_dir/track_filename, 'wb') as track_audio_fp:
        track_audio_fp.write(audio_dl_resp.content)

    audio_file = AudioFile(dest_dir/track_filename)

    if not audio_file:
        print("\tUnable to parse metadata of track file! Fields like 'title' may be empty.")

    else:
        if audio_file.tags:
            # Remove comments
            for key in ['comment', 'COMM', 'COMM::\x00\x00\x00']:
                try:
                    del audio_file.tags[key]
                except KeyError:
                    pass

        else:
            # No idea if this will work, hopefully it won't have to
            audio_file.tags['title'] = [track.title]
            audio_file.tags['artist'] = track.artist.split(', ')
            audio_file.tags['album'] = [track.album]

            # For cover art
            if track.cover_art_url:
                cover_resp = requests.get(track.cover_art_url)
                audio_file.tags['metadata_block_picture'] = cover_resp.content

            if track.release_date:
                audio_file.tags['release_date'] = [track.release_date]

            if track.track_number:
                audio_file.tags['tracknumber'] = [track.track_number]

        audio_file.save()

    # prevent API throttling
    sleep(0.5)

    print("\tDone.")


def download_all_tracks(
    tracks_to_dl: list,
    interactive: bool,
    duplicate_download_handling: str,
    skip_duplicate_downloads: bool,
    spotify_dl_cfg: ConfigParser,
    output_dir: str = OUTPUT_DIR_DEFAULT,
    create_dir: bool = False,
    downloader: str = DOWNLOADER_DEFAULT,
    # file_type: str = DOWNLOADER_LUCIDA_FILE_FORMAT_DEFAULT,
    debug_mode: bool = False
) -> list:
    downloader = spotify_dl_cfg.get(CFG_SECTION_HEADER, CFG_DEFAULT_DOWNLOADER_OPTION, fallback=downloader)

    output_dir = set_output_dir(
        interactive=interactive,
        track=None,
        spotify_dl_cfg=spotify_dl_cfg,
        output_dir=output_dir,
        create_dir=create_dir,
        prompt_for_new_location=True,
        check_dir_exists=False
    )

    print(f"\nDownloading to '{Path(output_dir).absolute()}' using {downloader.capitalize()}.\n")

    print('-' * 32)

    tracks = list(dict.fromkeys(tracks_to_dl))
    broken_tracks = []

    for idx, (track_obj, out_file_title) in enumerate(tracks, start=1):

        print(f"[{idx:>3}/{len(tracks):>3}]", end=' ')

        try:
            download_track(
                track=track_obj,
                spotify_dl_cfg=spotify_dl_cfg,
                out_file_title=out_file_title,
                output_dir=output_dir,
                create_dir=create_dir,
                downloader=downloader,
                # file_type=file_type,
                interactive=interactive,
                duplicate_download_handling=duplicate_download_handling,
                skip_duplicates=skip_duplicate_downloads
            )

        except Exception as exc:
            print("\tDownload failed!")
            
            print("!!!",exc)

            broken_tracks.append((track_obj, out_file_title, output_dir, create_dir, idx))

            if debug_mode:
                with open('.spotify_dl_err.txt', 'a') as debug_fp:
                    debug_fp.write(
                        f"{datetime.now()} | {exc}"
                        f":: {traceback.format_exc()}\n\n"
                    )

    print("\nAll done.\n")
    if broken_tracks:
        print(
            f"[!] {len(broken_tracks)} track{'s' if len(broken_tracks) != 1 else ''} failed "
            "to download. Before exiting, there will be a chance to retry downloading these.\n"
        )

    return broken_tracks


def spotify_downloader(
    interactive: bool,
    spotify_token: str,
    spotify_dl_cfg: ConfigParser,
    downloader: str = DOWNLOADER_DEFAULT,
    urls: list = None,
    output_dir: str = OUTPUT_DIR_DEFAULT,
    create_dir: bool = None,
    duplicate_download_handling: str = DUPLICATE_DOWNLOAD_CHOICE_DEFAULT,
    skip_duplicate_downloads: bool = None,
    debug_mode: bool = None,
    filename_template: str = FILENAME_TEMPLATE_DEFAULT,
    # file_type: str = DOWNLOADER_LUCIDA_FILE_FORMAT_DEFAULT
):
    loop_prompt = True

    broken_tracks = []
    while loop_prompt and (tracks_to_dl := get_tracks_to_download(
            interactive=interactive,
            spotify_token=spotify_token,
            filename_template=filename_template,cli_arg_urls=urls)):

        print(f"\nTracks to download: {len(tracks_to_dl)}\n")

        broken_tracks.extend(
            download_all_tracks(
                tracks_to_dl=tracks_to_dl,
                interactive=interactive,
                spotify_dl_cfg=spotify_dl_cfg,
                downloader=downloader,
                output_dir=output_dir,
                create_dir=create_dir,
                duplicate_download_handling=duplicate_download_handling,
                skip_duplicate_downloads=skip_duplicate_downloads,
                # file_type=file_type,
                debug_mode=debug_mode
            )
        )
        if not interactive:
            loop_prompt = False

    return broken_tracks


def parse_args():
    parser = ArgumentParser()

    parser.add_argument(
        '-u',
        '--urls',
        nargs='+',
        help="URL(s) of Sptofy songs or playlists to download.  "
            "If a playlist is given, append \"|[TRACK NUMBERS]\" to URL to specify which tracks to download. "
            "Example: 'https://open.spotify.com/playlist/mYpl4YLi5T|1,4,15-' to download the first, fourth, "
            "and fifteenth to the end. If not specified, all tracks are downloaded."
    )
    parser.add_argument(
        '-f',
        '--filename',
        '--filename-template',
        type=str,
        default=FILENAME_TEMPLATE_DEFAULT,
        help=r"Specify custom filename template using variables '{title}', '{artist}', and '{track_num}'. "
            f"Defaults to '{FILENAME_TEMPLATE_DEFAULT}'."
    )
    parser.add_argument(
        '-d',
        '--downloader',
        type=str,
        choices=DOWNLOADER_OPTIONS,
        default=DOWNLOADER_DEFAULT,
        help=f"Specify download server to use. Defaults to '{DOWNLOADER_DEFAULT}'."
    )
    # parser.add_argument(
    #     '-t',
    #     '--file-type',
    #     type=str,
    #     choices=DOWNLOADER_LUCIDA_FILE_FORMATS,
    #     default=DOWNLOADER_LUCIDA_FILE_FORMAT_DEFAULT,
    #     help=f"Specify audio file format to download.  Must be one of {', '.join(DOWNLOADER_LUCIDA_FILE_FORMATS)}. "
    #         f"Defaults to '{DOWNLOADER_LUCIDA_FILE_FORMAT_DEFAULT}'."
    # )
    parser.add_argument(
        '-o',
        '--output',
        type=str,
        default=OUTPUT_DIR_DEFAULT,
        help=f"Path to directory where tracks should be downloaded to.  Defaults to '{OUTPUT_DIR_DEFAULT}'"
    )
    parser.add_argument(
        '-c',
        '--create-dir',
        action='store_true',
        help="Create the output directory if it does not exist."
    )
    parser.add_argument(
        '-p',
        '--duplicate-download-handling',
        choices=DUPLICATE_DOWNLOAD_CHOICES,
        default=DUPLICATE_DOWNLOAD_CHOICE_DEFAULT,
        help="How to handle if a track already exists at the download location. "
            f"Defaults to '{DUPLICATE_DOWNLOAD_CHOICE_DEFAULT}'."
    )
    parser.add_argument(
        '-k',
        '--config-file',
        type=Path,
        help="Path to JSON containing download instructions."
    )
    parser.add_argument(
        '--retry-failed-downloads',
        type=int,
        default=0,
        help="Number of times to retry failed downloads. Defaults to 0."
    )
    parser.add_argument(
        '--cfg-file',
        type=Path,
        help="Path to .cfg file used for user default settings if not using `$HOME/.spotify_dl.cfg`."
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        default=False,
        help="Debug mode."
    )
    # for backwards compatibility
    parser.add_argument(
        '-s',
        '--skip-duplicate-downloads',
        action='store_true',
        default=True,
        help="[To be deprecated] Don't download a song if the file already exists in the output directory. Defaults to True."
    )

    return parser.parse_args()


def main():
    print('', '=' * 48, '||          Spotify Song Downloader v0.2.1           ||', '=' * 48, sep='\n', end='\n\n')

    token = _get_spotify_token()

    spotify_dl_cfg = parse_cfg(Path.home()/".spotify_dl.cfg")

    # No given args
    if len(sys.argv) == 1:
        # Interactive mode
        interactive = True

        downloader = get_downloader_from_user(spotify_dl_cfg)

        filename_template = get_filename_template_from_user(spotify_dl_cfg)

        # if downloader == DOWNLOADER_LUCIDA:
        #     out_file_type = get_file_type_from_user(spotify_dl_cfg)
        # else:
        out_file_type = "mp3"

        broken_tracks = spotify_downloader(
            interactive=interactive,
            spotify_token=token,
            spotify_dl_cfg=spotify_dl_cfg,
            downloader=downloader,
            output_dir=OUTPUT_DIR_DEFAULT,
            urls=None,
            create_dir=None,
            debug_mode=None,
            filename_template=filename_template,
            file_type=out_file_type
        )

    else:
        # CLI mode
        interactive = False

        args = parse_args()

        if args.cfg_file:
            spotify_dl_cfg = parse_cfg(args.cfg_file)

        out_file_type = args.file_type
        downloader = args.downloader

        if not (config_file := args.config_file):

            if not (urls := args.urls):
                raise ValueError(
                    "The '-u'/'--urls' argument must be "
                    "supplied if not using a config file"
                )

            broken_tracks = spotify_downloader(
                interactive=interactive,
                spotify_token=token,
                spotify_dl_cfg=spotify_dl_cfg,
                downloader=downloader,
                output_dir=args.output,
                urls=urls,
                create_dir=args.create_dir,
                duplicate_download_handling=args.duplicate_download_handling,
                skip_duplicate_downloads=args.skip_duplicate_downloads,
                debug_mode=args.debug,
                filename_template=args.filename
            )

        else:
            loaded_config = validate_config_file(config_file)

            broken_tracks = []

            for entry in loaded_config:
                broken_tracks.extend(
                    spotify_downloader(
                        interactive=interactive,
                        spotify_token=token,
                        spotify_dl_cfg=spotify_dl_cfg,
                        output_dir=entry['output_dir'] if 'output_dir' in entry else OUTPUT_DIR_DEFAULT,
                        downloader=downloader or entry.get('downloader', DOWNLOADER_DEFAULT),
                        urls=[entry['url']],
                        create_dir=entry.get('create_dir'),
                        duplicate_download_handling=entry.get('duplicate_download_handling', DUPLICATE_DOWNLOAD_CHOICE_DEFAULT),
                        skip_duplicate_downloads=entry.get('skip_duplicate_downloads', False),
                        debug_mode=args.debug,
                        filename_template=entry.get('filename_template'),
                        # file_type=entry.get('file_type', DOWNLOADER_LUCIDA_FILE_FORMAT_DEFAULT)
                    )
                )

    if broken_tracks:
        nl = '\n'
        print(
            "\n[!] The following tracks could not be downloaded:\n"
            f"  * {f'{nl}  * '.join(out_file_title for _, out_file_title, *_ in broken_tracks)}\n"
        )

        num_retries_cfg = int(spotify_dl_cfg.get(CFG_SECTION_HEADER, CFG_DEFAULT_NUM_RETRY_ATTEMPTS_OPTION, fallback=0))

        if not interactive:
            num_retries = args.retry_failed_downloads or num_retries_cfg
        else:
            resp = input("Would you like to retry downloading these tracks? [y/N]\n")
            if resp.lower() == 'y':
                while 1:
                    try:
                        num_retries = num_retries_cfg or int(input("How many attempts?\n"))
                        break
                    except Exception:
                        print("Invalid response. Please enter a number.\n")
            else:
                print("Not attempting to download.")
                num_retries = 0

        if num_retries:
            print("Re-attempting to download tracks")
            for i in range(num_retries):

                if not broken_tracks:
                    break

                print(f"\nAttempt {i + 1} of {num_retries}")
                for track, out_file_title, output_dir, create_dir, idx in broken_tracks.copy():

                    try:
                        download_track(
                            track=track,
                            spotify_dl_cfg=spotify_dl_cfg,
                            out_file_title=out_file_title,
                            output_dir=output_dir,
                            create_dir=create_dir,
                            downloader=downloader,
                            file_type=out_file_type
                        )

                    except Exception as exc:
                        print("\tDownload failed!")

                    else:
                        broken_tracks.remove((track, out_file_title, output_dir, create_dir, idx))
                sleep(1)

        if interactive:
            input("\nPress [ENTER] to exit.\n")

    # Give a chance to see the messages if running via executable
    sleep(1)
    print("\nExiting...\n")
    sleep(3)


if __name__ == '__main__':
    main()
