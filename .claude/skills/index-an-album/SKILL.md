---
name: index-an-album
description: How to index a folder of race photos by eye -- read every bib, get the start protocol, recognise the starters whose bib is not readable (bursts, kit, timing, podium results, faces) and write the folder's photo-index.v1.json through the app's command line. Use when asked to index, tag or label an album or a photo folder, or to find participants on photos.
---

# Indexing an album by eye

"Index this folder" means: every photo gets the bibs of every starter on it -- the
ones whose bib is readable and the ones recognised without it -- and the folder gets
a `photo-index.v1.json` the site accepts. The app finds about 70 to 80 percent of
visible bibs with its Large models, fewer with the smaller ones, and almost nobody
without one; a careful pass by eye finds nearly all.
The person asking cares more about missing nobody than about an extra suggestion,
but a wrong *accepted* bib puts a stranger's photo in someone's album: when unsure,
mark the bib probable instead (see below).

## 1. Before starting

1. **Album folder(s).** One photographer's album per folder, photos at its root.
2. **Start protocol.** Ask where it is, after looking next to the album first. The
   sibling apps leave these files (`#`-separated, UTF-8):
   - StartProtocolMaker `data/start.txt`: `bib#Name#Group#...#Team#City#Bike#...`;
   - FinishProtocolGenerator `data/start.txt` (same), `data/gr.html` (results and
     places by category) and `data/abs.html` (overall);
   - WindowsChronometer `data/results.txt`: `bib#day h:m:s.ms#nextLap#`, one line per
     crossing of the timing line.
   A bib, name, gender, category, team, bike model and lap count per starter are all
   clues. Bibs can have letters or leading zeroes; keep them exactly.
3. **Ask whether the person asking raced or worked there.** Organisers and judges
   who also race appear at registration, as the starter, at the timing table and
   presenting awards -- and they will look for themselves first.
4. **Back up the existing index**: copy `ALBUM/photo-index.v1.json` aside. Never
   write into the album except through `app.cli` (step 5).

## 2. Prepare a work folder (outside the album)

```bash
uv run python -m tools.album.prepare ALBUM WORK      # WORK/view/NNN.jpg, WORK/photos.csv
```

`photos.csv` is `n,file,width,height,taken,camera`; `n` numbers the photos in the
indexer's order and is used everywhere below. Labels go to `WORK/labels.txt`, one line
per photo, written as you go -- it is the memory of the work, so save it after every
few photos:

```
# n|visible|identified|note
45|16||plate bent, 1 partly hidden
46||16|plate folded, reads 1C; same rider as 45
120|30|27 @blue-backpack|27 without plate at the edge; far rider with backpack
258||11 9 33 19 3 1|men's awards; order matches the finishing order
280||17?|plate folded; yellow kit and timing fit 17
```

- **visible** -- bibs readable on this photo, at full resolution if needed.
- **identified** -- starters recognised here without a readable bib. `17?` is
  probable: it goes to the review file, not into the index. `@tag` is a person not
  identified yet; give the same tag on every photo and resolve it later.
- **note** -- how it was decided; the reviewer reads it.

## 3. Pass 1: read the bibs on every photo

- Look at `view/NNN.jpg` in order, several per batch. For every rider whose bib is
  small, read it on full-resolution crops; one montage of several crops is cheaper
  than one image each:
  `uv run python -m tools.album.look ALBUM WORK out.jpg 45:0.0,0.55,0.25,0.65 46:...`
  (boxes are fractions of the photo).
- Count as a bib: a plate on the rider or their bike (handlebar, seat post), a number
  on the chest, arm or belt. Never: jersey prints ("68" on a moto jersey), helmet
  stickers, tyre sizes ("700"), banners and flags, car plates, displays, spare plates
  lying on the registration table.
- Check every value against the start protocol. A value that is not a starter's bib
  is a misread or not a bib -- look again.
- Folded or bent plates show part of the number; a brake cable across a plate splits
  it ("1 3" is 13). Read the rest from kit and neighbouring frames.
- The first time a bib is clear, note what goes with it: kit and team, helmet,
  glasses, socks, shoes, gloves, bike brand and colour, backpack, hair, tattoos.
  That table is what pass 2 runs on.

## 4. Pass 2: the starters without a readable bib

Use several cues and write which ones in the note. One cue is a lead, two
independent ones are an identification.

- **Bursts.** Same camera, a few seconds apart (`photos.csv`): the same rider in the
  same place carries the bib of the readable frame.
- **Kit and details.** Distinctive kit identifies on its own; a team kit worn by many
  starters does not -- add helmet, socks, bike, face.
- **Timing.** When the photographer stood at or near the timing line, photo time
  minus crossing time is the same for every rider whose bib is readable (to the
  second on a camera, within seconds on a phone). Then a head-on finish shot with
  no plate in view matches the crossing at that offset. Away from the line riders'
  speeds differ, so do not use it there.
- **Ceremonies.** Results by category say who stands on each podium; a category with
  one starter means that person is alone on the podium; the podium order can match
  the finishing order. People change clothes and take off helmets and glasses here.
- **Faces.** `uv run python -m tools.album.faces index ALBUM WORK`, then
  `uv run python -m tools.album.faces like WORK N X Y` lists faces similar to the
  person at fractions (X, Y) of photo N. SFace's same-person threshold is 0.363;
  every hit still needs a look. People printed on banners match too, sunglasses and
  helmets weaken a race face, and a podium face (no helmet) is the best query.
- **The asker.** Search for them explicitly: registration table, start, timing
  table, podium, group photo.

Spectators, marshals and family are not starters: leave them out unless the start
protocol says otherwise.

## 5. Write the index

```bash
uv run python -m tools.album.labels WORK        # WORK/bibs.csv and WORK/review.csv
uv run python -m app.cli index ALBUM --csv WORK/bibs.csv
uv run python -m app.cli check ALBUM            # "the site would accept it"
```

`bibs.csv` lists visible and identified bibs for every photo, also the empty ones, so
every photo becomes reviewed. The album id and photo ids stay; the revision goes up
by one. Reviewed photos keep their bibs through later automatic runs, which can only
add candidates. The site refuses an index older than the one it already imported:
write over the newest copy. Upload the index with the photos and `_previews/` (the
app makes previews for HEIC and other camera formats and for originals over 20 MB);
then press *Refresh participants' tagging* on the event's photo page.

## 6. Check yourself, then report

- Run the app's recognition on a copy (see the `measure-recognition` skill) and look
  at every value it reads that your labels lack, and every bib you have that it
  never reads. On the first races this found a plate on a parked bike that the eye
  pass had skipped.
- Report: photos, visible photo-bib pairs, starters identified without a bib,
  probable ones left out, where `review.csv` is, and the open doubts.
