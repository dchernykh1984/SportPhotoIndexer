# Sport Photo Indexer

Marks which race bibs are on which photo of an album folder, and writes the folder's
`photo-index.v1.json`. Put the folder in Dropbox, share it, and connect it to the
event on [universalbicycle.team](https://universalbicycle.team): riders then find
their photos by bib, and in their own race album.

## How to index an album

1. **One folder per photographer's album**, with the photos at its top level (the
   site opens a photo straight from Dropbox only for files at the root). Use the
   folder as it sits in your Dropbox, synced to this computer.
2. **Open it**: *Open folder...*. JPEG, PNG, WebP, HEIC/HEIF (including HIF), TIFF,
   BMP, GIF and AVIF are supported. The program lists the photos and writes
   `photo-index.v1.json` into the folder at once. Nothing else in the folder is
   changed; photos over 20 MB get a small copy in `_previews/`, because Dropbox
   cannot shrink them for the site. HEIC/HEIF, TIFF, BMP, GIF and AVIF always get a
   separate JPEG preview for the app and site. Originals keep their format and bytes.
   A multi-image file contributes its primary image (HEIF) or first frame/page.
3. **Recognize automatically**: the default mode reads bibs first, then uses riders with
   accepted bibs as appearance references for other photos of this album. Choose *Bib
   numbers only* to skip the second phase. Inspect the list's `check:` suggestions.
   Type the accepted bibs and press **Enter** to confirm/correct a photo and move on;
   Enter with an empty field explicitly accepts no bibs. Manual entry and CSV also
   work without downloading any models.
4. **Share the folder** in Dropbox: *Share* -> *Anyone with the link can view* ->
   copy the link.
5. **On the site**, on the event's page: *Manage event photos* -> paste the link ->
   *Add and import*. After you index more photos, press *Refresh participants'
   tagging* there.

Bibs keep exactly what you type: `012` stays `012`, letters stay letters. If a photo
file is replaced, old observations no longer apply: manual decisions are archived in
`manual_history`, automatic results are cleared and the photo is "not checked" again.

### Automatic recognition and stopping

Recognition runs on this computer's CPU; photos are not uploaded to a recognition service.
There are no recognition API fees. First use needs internet to download up to **11 MB**
of OCR models, or **121 MB** including appearance models. Progress names the download;
verified models stay in `data/models` next to the portable app and work offline afterwards.
Give that folder enough writable disk space. [Models and licenses](MODEL_NOTICES.md)
list the pinned sources and hashes; failed downloads can be retried.

Photos are processed in parallel automatically. The worker count is bounded by physical
CPU cores, the CPUs available to this process, the album size and available RAM. Models
share that CPU budget instead of starting a full set of threads for every photo. The
preparation status shows the chosen photo-worker count. No configuration is required.
The index is still written by one coordinator; parallel workers only read the originals.
See [CPU policy and measurements](docs/parallel-recognition.md). Sustained full CPU load
can still trigger hardware thermal throttling; limiting workers prevents oversubscription,
not heat itself.

The current reader handles digits and Latin letters, keeping leading zeroes and case.
Other bib scripts can be typed or imported from CSV. An OCR confidence of at least 0.98
is accepted; 0.60-0.98 is a candidate. The scores are not calibrated race accuracy.
The appearance phase uses whole-person crops (kit, helmet and build, plus bike pixels
inside the crop), without face recognition. It searches **only this album**: put one
event in a folder. It needs unambiguous accepted bib references; overlapping riders
seed nothing. A team/relay bib can keep references of several different riders.
Appearance matches with cosine similarity at least 0.80 are always **candidates**.
Similar kit and riding poses can produce wrong suggestions. A real-race pilot exposed small-number and aspect-ratio failures, now guarded by regression
tests. OCR reads overlapping 768-pixel tiles on large photos instead of shrinking away the
bibs. A complete manually labelled precision/recall benchmark is still pending; review
suggestions before relying on them. Cross-album appearance search is not implemented.

**Stop** terminates the read-only photo workers and keeps every already-saved photo.
Photos can finish out of order; the progress count measures returned photos. Start again to resume OCR without repeating
unchanged completed OCR. Appearance is recomputed after restart; its vectors live only
in a private temporary database outside the album and are deleted on exit. Changing the
model version invalidates OCR checkpoints. If a file changed, rescan before restarting.
A competing index edit stops the worker rather than overwriting the other editor.

Manual accepted/rejected values and even an explicitly empty accepted set survive
automatic reruns. New automatic results cannot enlarge a manually accepted set;
new suggestions remain candidates. To accept a suggestion, include its bib in the
field and press Enter. Leaving a previously suggested bib out records a manual rejection.
Processing errors are shown explicitly; the last valid saved index remains usable.
If an unchanged photo leaves the folder and comes back, indexes written by this version
restore its manual acceptance/rejection and review history. Older tombstones kept only
the photo ID, so annotations that were never saved there cannot be reconstructed.

### Limits

- One album: at most 5000 photos, 20 bibs on a photo, and an index file of at most 5 MB
  (the site's own limits; the program refuses to write an index the site would refuse).
- Only photos at the top of the folder are indexed; subfolders are not read.
- Dropbox makes no thumbnail of a photo over 20 MB, so the program puts a small preview
  of such photos into `_previews/`.
- Dropbox limits the traffic of shared links: 1 TB a day on paid plans, 20 GB on Basic.
  Over it, all the owner's shared links pause for a day.
- Do not index one folder from two computers at once: the second one is told the index
  changed and has to reopen the folder.

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
