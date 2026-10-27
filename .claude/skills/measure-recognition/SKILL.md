---
name: measure-recognition
description: How to measure the app's bib and appearance recognition against a hand-labelled album, and what earlier measurements taught. Use before and after any change to app/vision.py, app/recognition.py, OCR or appearance thresholds, or the model catalog, and whenever someone asks how well recognition works.
---

# Measuring recognition

A change to recognition is judged by numbers on real albums, not by eye on a few
photos. You need an album labelled by the `index-an-album` skill: its work folder
with `photos.csv` and `labels.txt`.

## Run

```bash
uv run python -m tools.album.measure ALBUM WORK COPY [MODELS]
```

`COPY` is a new folder outside the album: it gets symbolic links to the photos, and
the app's own scan and recognition (appearance included) run there, exactly as the
window runs them. Nothing is written into the album. Output, for accepted bibs and
for accepted plus candidates: visible bibs found, starters without a bib found,
wrong values (a bib nobody on that photo carries) and how many of those are some
starter's bib -- only those reach a participant's album; a car plate matches nobody.

Compare a change with the base branch on the same machine: run the base in a
`git worktree` with the same `MODELS`, and the branch, each with its own `COPY`
(a second run in the same `COPY` reuses saved OCR, which is how to try new
thresholds quickly). Record both in `docs/recognition-benchmark.md` and the PR.

## What the first measurements taught

Two albums: a mountain-bike race shot on phones (handlebar plates) and a time trial
on one camera (small seat-post plates seen side-on, head-on finish photos, banners).
Check a change on both kinds; one album hides regressions on the other.

- The OpenCV Zoo PP-OCRv3 text detector takes `(BGR - mean) / 255`. Paddle's
  `/ std` saturates it: no text in one frame, text everywhere in the next.
- It finds plate digits only once they are about a tenth of its 736-pixel input,
  hence the enlarged windows around each person. Whole-photo 384-pixel tiles reach
  the same scale at about four times the time.
- The detector is unstable to one-pixel shifts of a window: differences of a few
  values between runs are noise. Do not tune to them.
- Most wrong accepted values are lone digits from logos and word fragments, and
  partial reads of a real plate ("3" of "30"). A minimum text height in pixels drops
  real plates on phone photos.
- Letters must stay acceptable (races number "A12"), even though on these albums
  every lettered read was a car plate or a display.
- PP-OCRv4/v5 detectors, rotating tall crops and wider text boxes did not help.
- Appearance: the person ReID vectors find riders in the race but nobody on the
  podium (no bike, no helmet, other clothes). Faces (YuNet + SFace) find podium
  people, but race faces under helmets and sunglasses make poor references, so a
  face match alone is right only about a third of the time. Printed people on
  banners are detected as people.
- A bib on a seat post or handlebar lies outside the person's box: give the person a
  zone wider than the body when deciding whose bib it is.
- Speed matters: record recognition time with the numbers.
