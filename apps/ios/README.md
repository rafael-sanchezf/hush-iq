# Assignment 4, Live API Data: Noise Score

Rafael Sanchez. The iOS client of Hush IQ; built as a course project in fall 2026, prior to the hackathon.

A SwiftUI app that answers one question for someone renting in New York: how loud will this apartment
be for me? It asks three things (how you sleep, what gets to you, which floor and side you live on),
pulls live public data for the address, and says in words how loud it is for you compared with the
rest of Manhattan, by time of day, with the decibels and the evidence behind it. The Nearby tab is the live-data view: every noise
complaint made to 311 within 500 m in the last 30 days, on a map or in a list, each opening a detail
page with what 311 did about it.

The idea comes from my Human-Centered Design team project (Personal Noise Score): a street-noise map
scores a point once for everyone; this scores one apartment, for one renter, by hour. The app is the
renter-facing prototype of that project; the scoring model is my own and the code here is a port of
its Python version.

## The API

NYC Open Data, through its Socrata endpoints. No key, no credit card. Eight datasets, the first is the
one on the map:

| What | Dataset | Used for |
|---|---|---|
| NYC 311 Service Requests | `data.cityofnewyork.us/resource/erm2-nwe9.json` | every `Noise*` complaint: the map and list (30 days, 500 m, with status and resolution) and the model (24 months, 150 m, by hour) |
| NYC PLUTO | `64uk-42ks` | year built, floors, units, building class |
| NYC Street Centerline | `inkn-q76z` | road class, lanes, posted speed |
| DOB NOW approved permits | `rbx6-tga4` | unexpired loud-work permits on the block |
| NYS Liquor Authority | `data.ny.gov/resource/9s3h-dpkz.json` | bars, clubs and restaurants within 150 m |
| MTA subway stations | `data.ny.gov/resource/39hk-dx4f.json` | elevated structures within 350 m |
| NYC Facilities Database | `67g2-p84d` | hospitals, firehouses and police stations within 600 m |
| NYC GeoSearch | `geosearch.planninglabs.nyc/v2` | address to coordinates and tax lot |

A typical 311 query the app sends:

```
$select=unique_key,created_date,closed_date,complaint_type,descriptor,incident_address,status,resolution_description,latitude,longitude,location_type,bbl
$where=starts_with(complaint_type,'Noise') AND created_date > '2026-09-22T00:00:00' AND within_circle(location,40.8062,-73.9647,500)
$order=created_date DESC
```

## The screens

1. **Welcome** (first launch, and "Edit answers" later). Three steps: how you sleep; what gets to you
   (neighbors, nightlife and people, traffic, sirens, construction) and whether you work from home; your
   place, with live address suggestions, a "Use Columbia" shortcut, "Use my location", the floor and
   whether the unit faces the street or the courtyard.
2. **Score.** A verdict in words, not a number: "Typical for Manhattan", on a five-step meter from
   Very loud to Very quiet, with one line saying who it is for ("For a light sleeper bothered by
   nightlife, traffic and sirens") and the exact rank ("Quieter than 53% of Manhattan apartments").
   Below it, "When it's loud" gives the same verdict for night, early morning and day with the
   estimated decibels beside each, and "What you'll hear" lists the sources in plain words (the street
   by name, the bars within a block, the nearest firehouse) with the fact a renter can check at a
   viewing. "How it's worked out" shows the percentile, each time slot's decibels against the
   Manhattan typical and middle half, and a guide to reading decibels. Tap a source for its decibels
   by time of day and the evidence lines.
3. **Nearby.** Map or list of the live 311 noise complaints around the address. Pins that match what
   bothers you are blue, the rest grey, so the same data reads differently for a light sleeper who hates
   parties and for someone who only minds trucks. One pin per address: 311 logs repeat calls about
   the same building at the same point, so the pin carries a count and tapping it lists that building's
   complaints. Tap a pin or a row for the **detail**: what was reported, where, when, whether it is
   closed, and the resolution text from the city.

Design: the signature from my Assignment 2 (one corner radius, one gutter, rounded numerals, greyscale
first). Colour is spent once per screen: the ring, the matching pins, the status pill, the selected
answer. Dynamic Type works at the accessibility sizes.

## No network

The app never needs the network to open. Every pull is cached on disk; if a fetch fails, the last cached
data is shown with an "Offline. Showing data from ..." banner and a Retry button. If there is no cache
either (first launch with no connection), a saved sample for 2900 Broadway ships inside the app and the
banner says so. Network loss and server errors are both caught and shown in words; nothing crashes.
Tested by turning the Mac's Wi-Fi off, and repeatable with the launch argument `-NoiseScoreSimulateOffline YES`,
which makes every request fail the way iOS does with no signal (`screenshots/offline-cached.png` with a
cache, `screenshots/offline-sample.png` on a fresh install).

## How the score is made

Each ingredient becomes a pseudo-decibel exposure per time window: street from road class, lanes, speed
and distance plus elevated subway and vehicle complaints; nightlife from licensed venues as point
sources plus party complaints by hour; building from residential complaints per unit per year against
the borough rate, plus construction era; sirens from hospitals, firehouses and police stations by
distance; construction from complaints and unexpired permits. Floors above the first attenuate the
outdoor sources, courtyard units more. The renter's answers add decibels to the ingredients they named
and weight the windows. Ingredients combine by energy sum, so one loud source dominates, as in a
bedroom. The time slots' levels are what the screen shows as decibels: estimated at your window, the same for
anyone in that apartment. Your answers never change those numbers. They change the verdict.

The verdict is relative, because a decibel number alone does not tell a renter whether it is good. The
app ships a Manhattan baseline: 300 apartments drawn across Manhattan's community districts, weighted
by size, each scored with the same model. On the phone, every sample is re-scored for your floor, side
and answers, and your apartment is ranked among them. Each step of the meter is one fifth of
Manhattan. No network is needed for the rank. Every constant is in
`Packages/NoiseKit/Sources/NoiseKit/Config.swift` with a tag to the decision behind it.

## Files

- `NoiseScore/` the app: `SurveyView`, `ScoreView`, `IngredientDetailView`, `NearbyView`,
  `ComplaintDetailView`, `NoiseStore` (state, offline fallback, persistence), `Theme`, `LocationFinder`.
- `Packages/NoiseKit/` the library, no UI: `Rows` (the Socrata row types), `Sources` (the eight pulls),
  `Cache`, `Model` (the score), `Config`, `FixtureDataSource` (the bundled sample).
  `swift test` runs 28 tests, including a comparison of the Swift model against the Python model's output
  for four addresses.
- `screenshots/` the screens on an iPhone 17 Pro.
- `SPEC.md` the build spec.

Built with Xcode 27.1 and SwiftUI, deployment target iOS 18, iPhone and iPad. No third-party packages.

## AI acknowledgement

This assignment was done with the assistance of AI, in line with the course policy. The idea, the
choice of data, the three questions, the scoring model and its weights, the design decisions and all
of the written prose were composed by me, Rafael Sanchez. I orchestrated the work and AI assisted in
the coding, so a good part of the Swift code was AI generated under my direction and I reviewed and
tested it on the simulator.
