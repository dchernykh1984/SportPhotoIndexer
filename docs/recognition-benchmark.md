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

## Model sizes

The same photos with each model size the window offers, appearance included, one run
at a time on the ten-core Mac. Medium and Large add Florence-2 base (8-bit or full
precision) to the small models; Florence-2 large is shown for comparison and is not
offered. *Without a bib* counts identified photo-starter pairs with no readable bib
that the index suggests.

| Album | Size | Download | Time | Accepted: found | Accepted: wrong | All: found | All: wrong | Without a bib |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Alatau XCO | Small | 15 MB | 291 s | 62.0% | 29 of 303 (24) | 72.7% | 123 of 460 (109) | 23 of 378 |
| Alatau XCO | Medium | 292 MB | 907 s | 65.7% | 27 of 317 (23) | 72.9% | 62 of 401 (55) | 24 of 378 |
| Alatau XCO | Large | 1103 MB | 1636 s | **68.5%** | 29 of 331 (24) | 76.2% | 70 of 425 (61) | 26 of 378 |
| Alatau XCO | Florence-2 large | 3312 MB | 5153 s | 66.0% | 25 of 316 (20) | 76.9% | 60 of 416 (51) | 24 of 378 |
| UBT TT | Small | 15 MB | 146 s | 48.9% | 25 of 47 (6) | 57.8% | 64 of 91 (28) | 1 of 141 |
| UBT TT | Medium | 292 MB | 435 s | 55.6% | 28 of 53 (9) | 62.2% | 32 of 61 (12) | 1 of 141 |
| UBT TT | Large | 1103 MB | 929 s | **57.8%** | 28 of 54 (9) | 62.2% | 36 of 65 (14) | 1 of 141 |
| UBT TT | Florence-2 large | 3312 MB | 2068 s | 55.6% | 27 of 52 (8) | 60.0% | 32 of 60 (11) | 1 of 141 |

Florence-2 reads plates the small reader misses and rarely reads a logo as a number,
so both larger sizes find more and halve the wrong suggestions. Florence-2 large found
three more pairs than Florence-2 base among all values on Alatau XCO, fewer accepted
ones, and fewer on UBT TT, at three times the time and 5.7 GB of RAM per photo worker:
that is where a bigger model stopped helping. Its 8-bit export (850 MB) scored below
full-precision base on Alatau XCO and level with it on UBT TT, and was dropped too.

## Start protocol

The same runs with each race's start protocol (30 and 25 starters), reusing the saved
reads; only appearance ran again (81 s and 18 s with Large).

| Album | Size | Protocol | Accepted: found | Accepted: wrong | All: found | All: wrong |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Alatau XCO | Small | no | 62.0% | 29 of 303 (24) | 72.7% | 123 of 460 (109) |
| Alatau XCO | Small | yes | 62.0% | 24 of 298 (24) | 72.7% | 109 of 446 (109) |
| Alatau XCO | Large | no | 68.5% | 29 of 331 (24) | 76.2% | 70 of 425 (61) |
| Alatau XCO | Large | yes | 68.5% | 24 of 326 (24) | 76.2% | 61 of 416 (61) |
| UBT TT | Small | no | 48.9% | 25 of 47 (6) | 57.8% | 64 of 91 (28) |
| UBT TT | Small | yes | 48.9% | 6 of 28 (6) | 57.8% | 28 of 55 (28) |
| UBT TT | Large | no | 57.8% | 28 of 54 (9) | 62.2% | 36 of 65 (14) |
| UBT TT | Large | yes | 57.8% | 9 of 35 (9) | 62.2% | 14 of 43 (14) |

The protocol removes exactly the wrong values that match no starter and loses no bib,
since every labelled bib was in it. It cannot remove what the site would show to a
starter, the numbers in brackets: lone digits from stickers and bottles are starters'
bibs too. Keeping weaker reads of starters' bibs (small reader from 0.5, Florence-2
from 0.02) was scored offline and not kept: one to six more pairs for up to thirty
more wrong ones, all of them starters' bibs.

## Faces

The mode *Bib numbers, then rider appearance and faces* with the small models, against
the plain appearance mode (all values, accepted and candidates):

| Album | Mode | All: found | All: wrong | Without a bib |
| --- | --- | ---: | ---: | ---: |
| Alatau XCO | appearance | 72.7% | 123 of 460 (109) | 23 of 378 |
| Alatau XCO | appearance and faces | 73.6% | 118 of 481 (104) | **45 of 378** |
| UBT TT | appearance | 57.8% | 64 of 91 (28) | 1 of 141 |
| UBT TT | appearance and faces | 60.0% | 77 of 105 (41) | 1 of 141 |

Faces double the people found out of view of their bib on Alatau XCO, where most
accepted bibs are right. On UBT TT appearance can only spread its references, and many
of them are lone digits from stickers and bottles, so faces mostly spread those. With
Medium models faces find 8 of 141 there, with 47 wrong values (27 bibs).

Tried and not kept: larger appearance models (CLIP ViT-L/14, DINOv2-L, AuraFace) did
not beat the Youtu ReID and SFace pair; reading every zone twice with a shifted crop
found one more bib for double the time; keeping Florence-2 reads below 0.2 added more
wrong values than bibs.

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
