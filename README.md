# spotify-downloader

Spotify song downloader using API created by [lucida.to](https://lucida.to/) _(Source code can be found [here](https://git.gay/lucida/lucida))_

The script `src/spotify_dl.py` can be run in interactive mode or CLI mode.


## Build the binary

To generate a .exe for this tool, with Python installed, run the following commands:
```shell
git clone https://github.com/MattJaccino/spotify-downloader.git
cd spotify-downloader/
python -m venv ./venv
cd venv/
source ./Scripts/activate
pip install -r requirements.txt
pip install pyinstaller
pyinstaller src/spotify_dl.py --onefile --paths ./venv/Lib/site-packages
```

The directory `dist/` will contain the executable.


## Interactive mode

When run without any arguments, interactive mode is used.  The user is prompted for URLs of songs or playlists.  If a playlist is given, the user has the option to download individual songs from that playlist or all of them as well as the ability to see the songs in the playlist prior to making a decision.  The default download directory is the user's `Downloads/` directory, e.g. `C:\Users\[USER]\Downloads\`.  The user is prompted if they want to change the directory prior to downloading the songs.  Template variables can be used in the path.

## CLI mode

```shell
usage: spotify_dl.py [-h] [-u URLS [URLS ...]] [-f FILENAME] [-d {lucida,spotifydown}] [-t {mp3-320,mp3-256,mp3-128,ogg-320,ogg-256,ogg-128,original}] [-o OUTPUT] [-c] [-p {skip,overwrite,append_number}] [-k CONFIG_FILE] [--retry-failed-downloads RETRY_FAILED_DOWNLOADS] [--cfg-file CFG_FILE] [--debug] [-s]

optional arguments:
  -h, --help            show this help message and exit
  -u URLS [URLS ...], --urls URLS [URLS ...]
                        URL(s) of Sptofy songs or playlists to download. If a playlist is given, append "|[TRACK NUMBERS]" to URL to specify which tracks to download. Example:
                        'https://open.spotify.com/playlist/mYpl4YLi5T|1,4,15-' to download the first, fourth, and fifteenth to the end. If not specified, all tracks are downloaded.
  -f FILENAME, --filename FILENAME, --filename-template FILENAME
                        Specify custom filename template using variables '{title}', '{artist}', and '{track_num}'. Defaults to '{title} - {artist}'.
  -d {lucida,spotifydown}, --downloader {lucida,spotifydown}
                        Specify download server to use. Defaults to 'lucida'.
  -t {mp3-320,mp3-256,mp3-128,ogg-320,ogg-256,ogg-128,original}, --file-type {mp3-320,mp3-256,mp3-128,ogg-320,ogg-256,ogg-128,original}
                        Specify audio file format to download. Must be one of mp3-320, mp3-256, mp3-128, ogg-320, ogg-256, ogg-128, original. Defaults to 'mp3-320'.
  -o OUTPUT, --output OUTPUT
                        Path to directory where tracks should be downloaded to. Defaults to 'C:\Users\mattj\Downloads'
  -c, --create-dir      Create the output directory if it does not exist.
  -p {skip,overwrite,append_number}, --duplicate-download-handling {skip,overwrite,append_number}
                        How to handle if a track already exists at the download location. Defaults to 'skip'.
  -k CONFIG_FILE, --config-file CONFIG_FILE
                        Path to JSON containing download instructions.
  --retry-failed-downloads RETRY_FAILED_DOWNLOADS
                        Number of times to retry failed downloads. Defaults to 0.
  --cfg-file CFG_FILE   Path to .cfg file used for user default settings if not using `$HOME/.spotify_dl.cfg`.
  --debug               Debug mode.
  -s, --skip-duplicate-downloads
                        [To be deprecated] Don't download a song if the file already exists in the output directory. Defaults to True.
```

### Cfg file

Not to be confused with the "config" file below (bad name, I know. I'll change it at some point), The user can define a file named `.spotify_dl.cfg` in their home directory (in Windows, it's `C:\Users\[Your user]\`) to define settings that will always be used by this tool.  The `Settings` section **must** be defined.

Example:

```
[Settings]
default_download_location="C:\Users\me\Desktop\folder"
default_filename_template="{artist} - {title}"
```

See the [sample .spotify_dl.cfg](./dist/.spotify_dl.cfg).

The following values are supported:
* `default_download_location`: Path to directory/folder to download tracks to.
* `default_downloader`: Downloader to use.  Either `lucida` or `spotifydown`.
* `default_file_type`: Audio file type to download.  See CLI output above for options. _(Only applicable when using Lucida)_.
* `default_filename_template`: Filename format template to use when naming downloads.
* `default_retry_downloads_attempts`: Number of attempts to retry downloading tracks that failed to download.
* `duplicate_download_handling`: How to handle downloads for files that already exist.  Options are `skip`, `overwrite`, or `append_number`


### Config file

Example of JSON file used to contain download instructions:

```json
[
  {
    "url": "https://open.spotify.com/playlist/mYpl4YLi5T"
  },
  {
    "url": "https://open.spotify.com/playlist/mYpl4YLi5T2",
    "output_dir": "/path/to/dir/",
    "create_dir": true,
    "filename_template": "{id} - {artist} - {title}"
  },
  {
    "url": "https://open.spotify.com/playlist/mYpl4YLi5T3",
    "skip_duplicate_downloads": true
  }
]
```

The following arguments can be specified in entries within the config JSON:
* `url` (Required)
* `output_dir`
* `downloader`
* `create_dir`
* `skip_duplicate_downloads`
* `duplicate_download_handling`
* `filename_template`
* `file_type`
There types and use match those of the CLI arguments.  

_The arguments `--retry-failed-downloads` and `--cfg-file` are not set in the config JSON.  It should be run when using the respective args when executing the tool, e.g., `spotify_dl --config-file path/to/config.json --retry-failed-downloads 3`_
