# Eval

Hackathon work, Oct 28 (cards HIQ-25 and HIQ-46). Two things live here:

- **The 20-case eval** runs on every change in CI, for free. It checks that no model output reaching a renter
  invents a source, and that the listing reader gets the facts right.
- **The photo test** scores the reader on 20 listings Rafa saves and labels by hand. Its per-field accuracy
  decides which photo fields reach the score.

Stdlib Python 3.12, no install. Run everything from `eval/`.

```bash
python -m hush_eval run                  # mock mode: no model, no key, no cost; exits 1 on a failure
python -m pytest tests                   # the eval's own tests
```

## The 20-case eval

### What it checks

Every case goes through the listing reader, then the verdict writer, and, when the case carries a permit pull,
the permit reader. A **fail** stops CI. A **note** is reported and does not stop it.

| Check | Fails when |
|---|---|
| Reader grounding | A field marked `read` has no evidence. A text quote is not in the listing (whitespace and curly quotes forgiven). Quote offsets do not point at the quote. A cited photo does not exist, or the citation does not say what the photo shows. A floor or side rests only on a sales adjective ("quiet block"). A value is outside its type. `position` disagrees with `side`. |
| Verdict citations | A sentence cites an evidence id that was not sent, ids repeat, there are no sentences, or a sentence gives decibels (no decibels leave the engine). Notes: a sentence with no citation, a number that none of its cited lines contains. |
| Permit adjustments | A source has no cap, or the size is over the cap. The cap comes from `services/adjust` `config.CAPS`, never from the model. Also fails on a cited row that is not in the pull, a direction other than louder or quieter, or a permit reading whose quote is not in that permit's own description. |
| Extraction against gold | Address, floor and side, field by field, against the case's gold labels. Observed fields too, where a case has gold for them. |

Extraction has four outcomes, and *can't tell* is counted apart from wrong:

- **correct**: the reader's value is right, or the listing is silent and the reader said can't tell.
- **wrong**: a value that differs from gold.
- **cant_tell**: the listing says it and the reader abstained.
- **invented**: the listing is silent, or contradicts itself, and the reader gave a value anyway.

The gate on address, floor and side depends on the mode:

- **Mock mode**: no wrong or invented values. A service's own checks may refuse a recorded output; that
  shows as *cant_tell* and a note.
- **Live mode**: the photo test's rule. At least 85% correct where the listing says it, and under 5% wrong.

### Modes and how each service is reached

`hush_eval/adapters.py` is the one place that knows each service's module and call shape. Each comes from that
service's `CONTRACT.md`.

| Service | In mock mode | In live mode |
|---|---|---|
| Listing reader, `services/agent` (HIQ-13) | Its own mock client, driven by the case's recorded model output, so `submit_listing` and `read_photo` check it for real. A stand-in scorer returns the recorded score, so nothing reaches the city's data. | `reader.client.make_client()` with `MODEL_API_KEY`; the hosted scorer |
| Verdict writer, `services/verdict` (HIQ-20) | A scripted OpenAI-SDK client, when its entry point takes `client`. Until its branch lands: fixture replay | its own client with `BASETEN_API_KEY` |
| Permit reader, `services/adjust` (HIQ-18) | Its rules reader (`client=None`), through the same checks | its Muse Spark client |

A service that is not on the branch is reached over HTTP when `HIQ_READER_URL`, `HIQ_VERDICT_URL` or
`HIQ_ADJUST_URL` is set. Otherwise mock mode replays the output recorded in the case file. The first lines of
every run say which way each service was reached.

```bash
python -m hush_eval run --live                         # needs MODEL_API_KEY (and BASETEN_API_KEY for the verdict)
python -m hush_eval run --live --record                # also saves the real outputs into the cases for mock mode
HIQ_EVAL_REPO=/path/to/checkout python -m hush_eval run  # against a service's unmerged branch
python -m hush_eval run --only 06 08 --json report.json --markdown summary.md
```

Live mode prints the per-field accuracy table, then latency, tokens and cost per case. Cost needs the prices
in `prices.json`, which are blank until someone fills them in from the Meta Model API and Baseten price
pages. Until then the cost column says n/a and tokens still print.

### The cases

`cases/<nn>-<what>.json`. Each case has a synthetic listing written for this eval and a real Manhattan address,
checked against GeoSearch and PLUTO on Oct 28. No listing text was copied, and no listing site was read. Each
case holds:

- `gold`: address, unit, floor, side, and observed facts where the text states them;
- `answers`: the three taps;
- `pull`: a synthetic permit pull, on four cases;
- `fixtures`: the recorded outputs, in each service's own vocabulary.

| # | Tests | Address | Floor | Side | Why |
|---|---|---|---|---|---|
| 01 | explicit | 2109 Broadway | 4 | front | Everything stated plainly |
| 02 | silent, demo | 140 Claremont Avenue | can't tell | can't tell | The demo address with a silent listing: expected values and a range |
| 03 | unit number | 50 Murray Street | 12 | can't tell | Only "Apt 12F" gives the floor; the F is a unit letter, not "front" |
| 04 | misleading adjective, permits | 45 Christopher Street | 3 | front | "Quiet block", "peaceful": the living room overlooks the street |
| 05 | misleading adjective, silent | 75 West End Avenue | can't tell | can't tell | Pure sales copy and two exposures |
| 06 | top floor | 32 Gramercy Park South | top (18) | can't tell | The floor is only "PH" |
| 07 | top floor, walk-up | 51 Saint Marks Place | 5 | front | "Top floor of a five-story walk-up"; the address spelled "St. Marks" |
| 08 | top floor | 437 East 12th Street | top (6) | can't tell | "Top floor" with no count |
| 09 | contradiction, permits | 315 East 70th Street | can't tell | can't tell | "3rd floor" in the headline, "sixth-floor" in the body |
| 10 | contradiction | 1 Irving Place | 15 | can't tell | Bedroom "faces the rear", yet "all windows overlook 14th Street" |
| 11 | courtyard | 2211 Broadway | 7 | rear | "Courtyard-facing" is the only side cue |
| 12 | rear | 225 West 10th Street | 2 | rear | A rear unit over the back gardens |
| 13 | corner, permits | 200 Water Street | 22 | front | A corner unit with windows on two streets |
| 14 | walk-up, silent | 326 East 6th Street | can't tell | can't tell | "A few flights up" gives no floor |
| 15 | garden level | 21 West 76th Street | 1 | can't tell | Garden level is the first floor; a floor-through faces both ways |
| 16 | compass only | 1 Fifth Avenue | 11 | can't tell | "South-facing" is not street or rear |
| 17 | high floor, permits | 220 Riverside Boulevard | 38 | can't tell | River views are a view, not a side; the permits call for no adjustment |
| 18 | photos | 49 West 11th Street | 3 | front | The AC unit and the brick are only in the photos (`cases/photos/`, drawn for this eval) |
| 19 | no address | none | 2 | can't tell | A street with no house number: ask, never invent one |
| 20 | misleading adjective, rear | 520 East 5th Street | 4 | rear | "No street noise at all!" is a claim; "faces the interior air shaft" is the fact |

"top (18)" means the right answer is `top` or the building's floor count from PLUTO.

### What the first in-process run found (Oct 28)

Run against the reader and permit-reader branches as pushed on Oct 28, in mock mode, offline: no fails.

- **Floor**: the reader declines four floors the gold says are knowable: "PH" (06), "top floor" (08),
  "garden level" (15), and the unit number "12F" (03). Its rule is that a floor must be a number next to the
  word floor. So floor is 75% correct with no wrong answers, under the 85% rule even with a perfect model.
- **Side**: the reader declines "faces the interior air shaft" as rear (20).
- **Observed facts**: the reader takes view, windows, AC and walls from photos only, so it declines them when
  only the text states them (07, 11 to 14, 16, 17). The photo-cited ones in 18 pass `read_photo`'s check.
- **Permits**: the rules reader gives facade work +1 step (04), a new building +2 (09) and a demolition +2 (13),
  each within the cap of 2 and citing only its own permit. The sign permit gets nothing (17).

These are policy choices in the reader, not bugs. The eval reports them as *can't tell*, which never counts
as wrong.

## The photo test

### Folder layout

```
photo_test/
  template/            what a new listing folder starts as (tracked)
  00/                  a synthetic example: drawn photos, labels, a model output (tracked)
  01/ ... 20/          Rafa's listings (gitignored: never in the public repo)
    listing.txt        the description, pasted as the listing shows it
    photos/            every photo, 01.png, 02.png, ...
    labels.json        Rafa's labels, written by the labeler
    model.json         the reader's result, written by `photo run`
```

`photo_test/.gitignore` keeps everything but `template/` and `00/` out of git. The listings and photos belong
to their owners, and the repo is public.

### Rafa's 45 minutes (HIQ-47)

1. Open `eval/labeler.html` in Chrome by double-clicking it. Click **Open photo_test folder** and pick
   `eval/photo_test`. One minute.
2. For each listing, about 1.5 minutes:
   1. Click **New listing**, then paste the link and the description.
   2. For each photo, right-click it on the listing, choose **Copy Image**, and press ⌘V in the labeler.
   3. Click **Save listing**. That creates the next numbered folder.
3. Label each listing, about 30 seconds. Amber fields are pre-filled from the text; look at the photos, click
   to confirm or correct, or click **Can't tell**. Press **Enter** to save `labels.json` and move to the next.
4. Check: `python -m hush_eval photo check` prints one line per listing and "20 ready".

Safari and Firefox cannot write to a folder. There the labeler reads the folder and saves each label as a
download, `labels-<nn>.json`, and `python -m hush_eval photo collect ~/Downloads` moves the downloads into
place. **New listing** needs Chrome, Edge or Arc; without it, `python -m hush_eval photo new --link URL` makes
the folder.

### What is labeled

| Field | Values, each also `cant_tell` |
|---|---|
| `floor` | an integer, 1 to 120 |
| `side` | `front` (the street side, corners included), `rear` (rear, courtyard or air shaft) |
| `view` | `street`, `courtyard` (courtyard or yards), `open` (river, park, skyline), `wall` (a wall close by) |
| `windows` | `floor_to_ceiling`, `standard` |
| `ac_units` | `yes` (a window or through-wall unit), `no` (central, split, or none) |
| `wall_material` | `brick` (or stone), `concrete`, `drywall` (plaster, drywall or wood), `glass` |

The reader's own vocabulary is richer: side `street` or `corner`, view `rear_yards` or `water`, windows as an
object, AC by kind. `hush_eval/shapes.py` maps each of its values onto these before comparing.

### Scoring, and the threshold rule

```bash
python -m hush_eval photo run      # the reader on every listing (live; needs MODEL_API_KEY), model.json beside labels.json
python -m hush_eval photo score    # per-field accuracy, and which fields reach the score
```

**Proposed rule:** a photo field reaches the score when, on the labeled set, all three hold:

1. **85% correct.** At least 85% of the listings where Rafa could tell get the right value. When the model
   says can't tell, that costs this number.
2. **Under 5% wrong.** Fewer than 5% of all labeled listings get a wrong value, counting a value given where
   Rafa could not tell. On 20 listings that means none: a wrong floor moves the verdict, and a can't tell
   only widens the range.
3. **At least 10 listings where Rafa could tell**, so 2 out of 2 does not pass.

The defaults are `MIN_ACCURACY`, `MAX_WRONG` and `MIN_ANSWERABLE` in `hush_eval/photo.py`. The 20-case eval
uses the same 85% and 5% in live mode.

## CI

`.github/workflows/ci.yml` runs three jobs on every pull request and every push to main, with no secrets:

- `packages/model` tests;
- the tests of every `services/*` folder that has them;
- this eval in mock mode, plus its own tests.

The eval's table goes to the run's summary page and its JSON report to an artifact.

`ci/pytest_offline.py` is a pytest plugin that blocks the internet but leaves loopback open. A test that
reaches for the internet is **skipped**, with the host named in the reason, rather than failed or deleted.
`@pytest.mark.network` skips a test up front, and the summary lists every skipped test.

On Oct 28, none of the 18 model tests on main needed the network, nor the 30 with engine v2. The reader's 65
tests and the permit reader's 38 also pass offline.
