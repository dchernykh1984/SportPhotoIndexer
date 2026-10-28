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
uv run python -m tools.album.measure ALBUM WORK COPY [MODELS] [SIZE] [faces]
```

`SIZE` is a model size from `app.model_cache.SIZES` (`small` by default); `faces`
runs the appearance mode that compares faces too.

`COPY` is a new folder outside the album: it gets symbolic links to the photos, and
the app's own scan and recognition (appearance included) run there, exactly as the
window runs them. Nothing is written into the album. Output, for accepted bibs and
for accepted plus candidates: visible bibs found, starters without a bib found,
wrong values (a bib nobody on that photo carries) and how many of those are some
starter's bib -- only those reach a participant's album; a car plate matches nobody.

Compare a change with the base branch on the same machine: run the base in a
`git worktree` with the same `MODELS`, and the branch, each with its own `COPY`
(a second run in the same `COPY` reuses saved OCR read with the same size, which is
how to try new thresholds or appearance rules quickly: copy a measured `COPY`
first). Record both in `docs/recognition-benchmark.md` and the PR.

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
- A bib on a seat post or handlebar lies outside the person's box: read it in a zone
  wider than the body. As appearance references, though, bibs inside the body box
  gave fewer wrong suggestions than bibs in that zone, where riders overlap.
- Speed matters: record recognition time with the numbers.

## What the larger models taught

- Florence-2 (OCR with regions) reads plates the small reader misses and misreads
  far less, but its lowest token probability is on another scale: its 0.2, 0.5 and
  0.9 behave like the small reader's 0.80, 0.95 and 0.99. Keep the small reader's
  unsure reads only when Florence read the same value.
- Its greedy decoding changes with a one-pixel shift of the crop ("11" at 0.48 in
  one crop, nothing in the next). Measure with exactly the crops the app reads;
  reading every zone twice gained almost nothing for double the time.
- int8 costs about three points of found bibs against fp32 of the same model.
- Florence-2 large (fp32, 3.3 GB) found about as many as base fp32 end to end, at three
  times the time and 5.7 GB per worker: that was the plateau. An offline score of
  torch Florence-2 large promised more than its ONNX export delivered in the app, so
  decide on a size only from `tools.album.measure`.
- Bigger appearance models (CLIP-L/14, DINOv2-L, AuraFace) did not beat the small
  ReID and SFace pair. What helped was a face and the body agreeing on one bib.
- Appearance can only spread the references OCR gives it: where many accepted
  bibs are wrong (lone digits from stickers on the time trial), faces spread those
  too. Check that album separately before tuning appearance on the other.
