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
   AVIF needs Pillow's native AVIF codec, unavailable on Windows ARM64; an explicit
   error is shown there rather than silently leaving AVIF files out. HEIC/HEIF works
   on Windows ARM64 as well as x64, macOS and Linux.
3. **Recognize automatically**: by default with the *Large* models and the mode that
   reads bibs first, then uses riders with accepted bibs as appearance and face
   references for other photos of this album; its first run downloads 1249 MB. Choose
   *Small models* for a run about six times quicker (160 MB to download in this mode,
   15 MB with *Bib numbers only*), and *Bib numbers only* to skip the second phase.
   Inspect the list's `check:` suggestions.
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

### Which way to index

- **Small models**: a quick first index on any computer (about five minutes for 500
  photos on a ten-core Mac), good enough to publish the album at once.
- **Large models**: the normal way. Several times longer, and it finds the most of
  the three automatic sizes.
- **By eye, or with a coding agent that can look at photos** (Claude Code, Codex):
  the most complete. The `index-an-album` skill in `.claude/skills/` (the same in
  `.agents/skills/`) reads every bib, takes the start protocol, recognises starters
  whose bib is not readable and writes the index through the command line, where
  typed bibs override automatic ones. `measure-recognition` scores the app on an
  album indexed that way.

### Automatic recognition and stopping

Recognition runs on this computer's CPU; photos are not uploaded to a recognition service.
There are no recognition API fees. First use needs internet to download the OCR models
of the chosen size -- **15 MB** small, **292 MB** medium, **1103 MB** large -- plus
**106 MB** for appearance and 39 MB more for faces. Progress names the download;
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

Bibs are read wherever a person carries them -- chest, arm, belt, handlebar or seat
post: the program finds the people in a photo and reads enlarged windows around each of
them and the bike beside them, as well as the whole frame. A number on a banner, flag or
car away from people is still read in the whole frame, so check suggestions.
The reader handles digits and Latin letters, keeping leading zeroes and case. A bib read
with confidence of at least 0.95 is accepted, a single digit from 0.99 (agreeing reads of
one spot combine); other reads from 0.80 up are candidates.
Other bib scripts can be typed or imported from CSV.
The scores are not calibrated race accuracy.
The model size next to the mode is remembered. *Small models* read with PaddleOCR
alone. *Medium* and *Large* read every person's zone and the whole frame again with
Florence-2 base (8-bit or full precision), and keep a small-model read only when it is
sure or Florence-2 read the same value. On the labelled races, Large found 76% of the
visible handlebar plates instead of 73% and 62% of the seat-post plates instead of
58%, with about half as many wrong suggestions, but took 5.6 times as long (27 minutes
for 500 photos on a ten-core Mac); Medium sits between them at about three times.
Florence-2 large (3.3 GB) found about as many as Large and is not offered. Each photo worker
needs about 1 GB of RAM plus the models, so larger sizes run fewer photos at once.

A start protocol is optional: *Start protocol* in the folder bar takes the race's
`start.txt` from StartProtocolMaker (`12#Name#Category#...`) or any table with the bib
in the first column, and is remembered for that album only; *Clear* goes back to any
bib. The status line shows the bibs it found, so a wrong column stands out. Read
numbers that are not in it are kept as rejected, so banners, car plates and displays
are no longer suggested and do not seed appearance; a read that differs only in
leading zeroes or case ("012" for "12") is saved as the protocol spells it, because the
site matches bibs exactly. Clearing or changing the
protocol brings them back on the next run without reading the photos again, on photos
nobody has checked yet: a checked photo keeps what the person typed. It cannot
tell a starter's number on a sticker or a bottle from a bib, and it rejects the bib of
a rider who is missing from the file, so use the final protocol. On the labelled races
it found as many bibs and cut the wrong values from 36 to 14 (seat-post plates, Large)
and from 70 to 61 (handlebar plates).

The appearance phase uses whole-person crops (kit, helmet and build, plus bike pixels
inside the crop). It searches **only this album**: put one
event in a folder. It needs unambiguous accepted bib references; overlapping riders
seed nothing. A team/relay bib can keep references of several different riders.
Appearance matches with cosine similarity at least 0.80 are always **candidates**.
The mode *Bib numbers, then rider appearance and faces* also compares faces (39 MB
more): it looks for a clear face in the top of each person and suggests a bib when face
and body agree on it (face 0.30 and body 0.60), or when the body alone matches from 0.80
and leads every other bib by 0.05. Faces find people out of race kit, at the awards
too. On the first labelled race it doubled the people found without a readable bib (23
to 45 of 378) with fewer wrong suggestions; on the second, where few references are
right, it added wrong suggestions (64 to 77). Face vectors, like body vectors, last one
run.
Similar kit and riding poses can produce wrong suggestions. On two hand-labelled races
([recognition benchmark](docs/recognition-benchmark.md)) the small models found 62-73%
of visible handlebar plates and about half of side-on seat-post plates. About one accepted value in
ten was wrong on the first race and half on the second, most of those there matching no
starter (a car plate, a display), so review suggestions before relying on them. Cross-album appearance search is not implemented.

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

It remembers the last album folder you opened, the model size and each album's start
protocol.


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
