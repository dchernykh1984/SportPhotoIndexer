# Sport Photo Indexer

Marks which race bibs are on which photo of an album folder, and writes the folder's
`photo-index.v1.json`. Put the folder in Dropbox, share it, and connect it to the
event on [universalbicycle.team](https://universalbicycle.team): riders then find
their photos by bib, and in their own race album.

## How to index an album

1. **One folder per photographer's album**, with the photos at its top level (the
   site opens a photo straight from Dropbox only for files at the root). Use the
   folder as it sits in your Dropbox, synced to this computer.
2. **Open it**: *Open folder...*. The program lists the photos and writes
   `photo-index.v1.json` into the folder at once. Nothing else in the folder is
   changed; photos over 20 MB get a small copy in `_previews/`, because Dropbox
   cannot shrink them for the site.
3. **Type the bibs** you see on each photo, separated by spaces, and press **Enter**:
   the photo is saved and the next one opens. A photo with no readable bib: press
   Enter on an empty field. The list shows what is done and what is "not checked";
   the index is saved after every photo, so you can stop at any time and come back.
4. **Share the folder** in Dropbox: *Share* -> *Anyone with the link can view* ->
   copy the link.
5. **On the site**, on the event's page: *Manage event photos* -> paste the link ->
   *Add and import*. After you index more photos, press *Refresh participants'
   tagging* there.

Bibs keep exactly what you type: `012` stays `012`, letters stay letters. If a photo
file is replaced, the bibs typed for the old file are dropped (they were about
different pixels) and the photo is "not checked" again.

### Bibs from a table

*Import bibs (CSV)...* takes a table with the file name in the first column and the
bibs after it, for example:

```
file;bibs
IMG_20261011_102014.jpg;12 45
IMG_20261011_102015.jpg;7
```

### Command line

```bash
uv run python -m app.cli index /path/to/album            # scan and write the index
uv run python -m app.cli index /path/to/album --csv bibs.csv
uv run python -m app.cli check /path/to/album            # would the site accept it?
```

## Download a ready-made app

Every release ships portable builds, so there is nothing to install and no
Python, uv or git needed. Pick the file for your platform from the
[latest release](https://github.com/dchernykh1984/SportPhotoIndexer/releases/latest):

| Platform | File |
| --- | --- |
| Windows (Intel/AMD) | `SportPhotoIndexer-windows-x64.exe` |
| Windows (ARM) | `SportPhotoIndexer-windows-arm64.exe` |
| macOS (Apple Silicon) | `SportPhotoIndexer-macos-arm64.zip` |
| Linux (Intel/AMD) | `SportPhotoIndexer-linux-x86_64` |
| Linux (ARM64) | `SportPhotoIndexer-linux-aarch64` |

The builds are not code-signed, so every system needs a one-off nudge before the
first launch. Each step below is done once per download, not on every start.

### macOS

Only Apple Silicon (M1 and newer) is supported - there is no Intel build.

Unpack the archive, then clear the quarantine flag that macOS puts on downloaded
files:

```bash
xattr -dr com.apple.quarantine "/path/to/SportPhotoIndexer.app"
```

After that the app opens with a normal double-click. Without it macOS refuses to
start the app, because it is unsigned.

The flag stays cleared. Copying or moving the app on the same Mac keeps it clear,
so there is no need to repeat this for every copy. It only comes back when the app
arrives from outside again: a fresh download, AirDrop, or unpacking a
newly downloaded archive.

Rather not use a terminal? Ctrl-click the app, choose **Open**, then **Open**
again in the dialog. macOS 15 Sequoia dropped that shortcut - there, go to System
Settings -> Privacy & Security, scroll down to the notice about the blocked app
and press **Open Anyway**.

### Windows

Run the `.exe` directly. SmartScreen warns that the publisher is unknown: choose
**More info**, then **Run anyway**.

### Linux

Make the file executable and run it:

```bash
chmod +x SportPhotoIndexer-linux-x86_64
./SportPhotoIndexer-linux-x86_64
```

This is a GUI application, so it needs a graphical session. If it fails to start
with an error about missing Qt libraries, install them:

```bash
sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libxcb-cursor0
```

### Where to keep it

The program reads and writes its files (`data/spi_settings.json`) **next to itself**, so give
it a folder of its own rather than a shared downloads directory. On macOS the
files land next to the `.app` bundle, in the folder that contains it.

It only remembers the last album folder you opened.


## Setup

### 1. Download the project

Install Git if you don't have it:

- **macOS:** `brew install git`
- **Linux (Ubuntu / Debian):** `sudo apt install git`
- **Windows:** download from [git-scm.com](https://git-scm.com/downloads) and run the installer

Then clone the repository:

```bash
git clone https://github.com/dchernykh1984/SportPhotoIndexer.git
cd SportPhotoIndexer
```

All subsequent commands should be run from the `SportPhotoIndexer` folder.

### 2. Install Python 3.14

This project requires **Python 3.14**; `uv` installs a matching interpreter automatically, but you can also install it yourself as shown below.

**macOS**

```bash
brew install python@3.14
```

If you don't have Homebrew yet, install it first from [brew.sh](https://brew.sh).

**Linux (Ubuntu / Debian)**

The system `python3` package is usually not 3.14. Install it via the deadsnakes PPA:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.14 python3.14-venv
```

**Windows**

Download the **Python 3.14** installer from [python.org/downloads](https://www.python.org/downloads/) and run it. On the first screen, check **"Add Python to PATH"** before clicking Install.

Verify the installation in a terminal:

- **macOS / Linux:** `python3.14 --version`
- **Windows:** `py -3.14 --version`

The output should start with `Python 3.14`.

### 3. Install uv

**macOS / Linux**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows**

Open **PowerShell** and run:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal afterwards so `uv` is on your `PATH`.

### 4. Create virtual environment and install dependencies

```bash
uv sync
```

### 5. Set up pre-commit hooks

```bash
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

After that pre-commit hooks will run automatically on every commit.

To run all checks manually across all files:

```bash
uv run pre-commit run --all-files
```

## Running the application

```bash
uv run python -m app.main
```

## Contributing

Before requesting a review, make sure the CI pipeline passes on your pull request. Once the pipeline is green, request a review from [@dchernykh1984](https://github.com/dchernykh1984).
