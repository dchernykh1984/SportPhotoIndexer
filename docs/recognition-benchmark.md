# Recognition benchmark

Two real albums, every photo labelled by hand: which bibs are readable on it, and which
starters are on it without a readable bib (recognised by kit, bike and finish timing).
The photos and labels stay outside the repository.

| Album | Photos | Bibs | Visible photo-bib pairs | People without a readable bib |
| --- | ---: | --- | ---: | ---: |
| Alatau XCO (mountain bike, phones) | 500 | handlebar plates | 432 | 305 |
| UBT TT (time trial, one camera) | 145 | small seat-post plates, seen side-on | 45 | 102 |

UBT TT is the hard case: plates are side-on and motion-blurred, the finish was shot
head-on (no plate in view), and banners, bottles and helmet stickers carry numbers.

## Results

*Found* is the share of visible pairs the index contains. *Wrong* is the share of
the index's values that belong to nobody on that photo; in brackets, how many of those
wrong values are some starter's bib, so the site would show the photo to that starter.
The rest (car plates, a display's "8888") match no registration. *All* counts accepted
bibs and candidates (uncertain reads and appearance suggestions), as a participant's
registration album shows them.

| Album | Version | Accepted: found | Accepted: wrong | All: found | All: wrong |
| --- | --- | ---: | ---: | ---: | ---: |
| Alatau XCO | 0.3.0 | 41.0% | 14 of 192 (12 bibs) | 58.8% | 155 of 426 (135 bibs) |
| Alatau XCO | people windows | **62.0%** | 29 of 303 (24 bibs) | **72.7%** | **123 of 460 (109 bibs)** |
| UBT TT | 0.3.0 | 48.9% | 9 of 31 (2 bibs) | 57.8% | 88 of 115 (38 bibs) |
| UBT TT | people windows | 48.9% | 25 of 47 (7 bibs) | 57.8% | 64 of 91 (36 bibs) |

Bibs with letters are accepted like digits, so that a race numbered "A12" works without
settings. On UBT TT this accepts 12 lettered values that are not bibs at all (a display's
"B8888", a car plate), which no participant's album shows.

Speed is unchanged: 500 Alatau photos, appearance included, on six workers of a ten-core
Mac took 399 s with 0.3.0 and 399 s and 427 s in two runs with people windows.

## What was wrong before

- The text detector is the OpenCV Zoo PP-OCRv3 export, which takes
  `(BGR - mean) / 255`. It was fed Paddle's `(BGR - mean) / std`, four times larger, and
  either saw no text at all in a frame or text everywhere.
- Even with the right input, it finds plate digits only once they fill about a tenth of
  its 736-pixel input: three times larger than in a native-resolution 768-pixel tile.
  Enlarging the whole photo that much is ten times the work, so the windows are now
  placed around the people the person detector finds.

## What is still missed or wrong

- Missed: plates seen edge-on or folded, motion blur, digits under about ten pixels,
  riders shot head-on with a seat-post plate. People without a readable bib are left to
  the appearance phase.
- Wrong: lone digits in logos and word fragments (they now need a sure read or two
  agreeing windows), part of a plate split by a brake cable ("3" of "30"), numbers and
  codes that really are on a person or near one (helmet sticker, bottle, tyre size,
  a car plate).
