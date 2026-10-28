# Noise Score: build spec

Written 2026-10-21 night. One SwiftUI app, two deliverables:

1. **UI/UX Assignment 4, "Live API Data"** (ENGI E4502, 20 pts, due Thu 2026-10-22 11:59 PM ET, pushed to
   GitLab `ENG4502/assignment_4` on branch `ras2369`). Canvas text: select any live API endpoint; download
   live data and display it as a List with a separate detail view, or on a Map; ensure the app works in a
   "no network" condition; no weather apps. Said in class: spend time on the design, it is a UI/UX class.
2. **The HCD team project's prototype** (IEME E4201, Pitch & Prototype due Tue 2026-10-27): the Personal
   Noise Score. The Python prototype at `~/code/noise-score` is the reference model. This app is the
   renter-facing client: three questions, then a score for one apartment by hour with the evidence shown.

The live API is NYC Open Data (Socrata), no key: 311 noise complaints for the map and list, plus the six
other public datasets the score needs. Everything is computed on the phone; there is no backend.

## Repo layout and ownership

```
NoiseScore.xcodeproj            app project (file-system synchronized group: drop Swift files in NoiseScore/ and they build)
NoiseScore/                     the app: screens, theme, store, assets         -> UI agent
Packages/NoiseKit/              the library: rows, model, data, cache, no UI    -> KIT agent
  Sources/NoiseKit/Rows.swift       CONTRACT, fixed: upstream row types, Inputs, GeoAddress
  Sources/NoiseKit/Contracts.swift  CONTRACT, fixed: Unit, Profile, Window, Bother, Ingredient, ScoreResult, NoiseDataSource, Pulled, NoiseError
  Sources/NoiseKit/Resources/       broadway.inputs.json, broadway.recent.json (bundled sample for previews and the no-cache offline fallback)
  Tests/NoiseKitTests/Fixtures/     <slug>.inputs.json + <slug>.expected.json from the Python model, 4 addresses
SPEC.md                         this file
README.md                       written last (submission README)
```

The two CONTRACT files are the interface between agents. Do not change an existing public signature;
additive changes (new types, new members with defaults, extensions) are fine. If something in a contract
is wrong, fix it minimally and note it in your final report.

Build commands:

```bash
cd Packages/NoiseKit && swift build && swift test
xcodebuild -project NoiseScore.xcodeproj -scheme NoiseScore -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/noisescore-dd build
```

Xcode 27.1, iOS 18 deployment target, Swift 5 language mode (set in Package.swift; the app target is SWIFT_VERSION 5.0).

## KIT agent: `Packages/NoiseKit`

Port `~/code/noise-score/noise_score/{config,geo,model,sources,cache}.py` to Swift, one file each:

- **Config.swift**: every constant from `config.py`, same names in camelCase inside `enum Config`, each with
  the `[M*]`/`[T*]` tag in a comment, plus the M11 sirens constants below.
- **Geo.swift**: `haversineM`, `pointToSegmentM`, `pointToMultilineM` over `GeoJSON`. Same equirectangular
  projection as geo.py so distances match.
- **Model.swift**: `public enum Scorer { public static func score(_ inputs: Inputs, unit: Unit, profile: Profile?, options: ScoreOptions = ScoreOptions()) -> ScoreResult }`
  with `public struct ScoreOptions { public var sirens = true; public init(sirens: Bool = true) }`.
  Replicate model.py function by function: street, nightlife, building, sirens (new), construction, combine,
  streetOnly, score. **Evidence strings must match the Python text exactly** (they are what the renter
  reads and what the tests can diff). Ingredient order: street, nightlife, building, sirens, construction.
  `windowOf(hour)`, `logBump`, `energySum`, `toScore` as in Python. Python's `_hour` parses
  `created_date[:19]` with `fromisoformat`; do the same (the string is local time, no zone).
  Python's `today` for permit expiry is `inputs.as_of`; use that, never `Date()`, so fixtures replay.
- **Sources.swift**: `public struct LiveDataSource: NoiseDataSource` with the exact endpoints and `$select` /
  `$where` strings of sources.py (datasets erm2-nwe9, 64uk-42ks, inkn-q76z, rbx6-tga4, 9s3h-dpkz on
  data.ny.gov, 39hk-dx4f on data.ny.gov, GeoSearch v2). User-Agent `noise-score-ios/0.1 (Columbia ENGI E4502 and IEME E4201; ras2369@columbia.edu)`.
  Timeout 30 s, two retries on transient failure. `URLError.notConnectedToInternet`, `.networkConnectionLost`,
  `.cannotFindHost`, `.cannotConnectToHost`, `.timedOut` map to `NoiseError.offline`.
  `suggest(_:)`: GeoSearch `/v2/autocomplete?text=&size=5` if it answers, else `/v2/search?text=&size=5`.
  `pullAll` runs the pulls concurrently (async let / task group), then writes the cache. `recentComplaints`
  selects `unique_key,created_date,closed_date,complaint_type,descriptor,incident_address,status,resolution_description,latitude,longitude,location_type,bbl`
  with `starts_with(complaint_type,'Noise') AND created_date > '<now - days>' AND within_circle(location,lat,lng,radiusM)`,
  `$order=created_date DESC`, `$limit=500`.
  Facilities (M11): FacDB `67g2-p84d`, `$select=facname,factype,address,latitude,longitude`,
  `$where=factype in('HOSPITAL','ACUTE CARE HOSPITAL','FIREHOUSE','AMBULANCE STATION','POLICE STATION')`, `$limit=2000`,
  pulled citywide (about 400 rows; `within_circle` on this dataset's `the_geom` returns nothing), cached 30
  days, filtered to `RADIUS_SIRENS_M` in code. Rows with no coordinates are dropped. Kind: HOSPITAL and ACUTE CARE
  HOSPITAL are `.hospital`; FIREHOUSE and AMBULANCE STATION are `.fire`; POLICE STATION is `.police`.
  `Inputs.sources` gets an eighth entry `{"NYC Facilities Database (hospitals, firehouses, police)", "https://data.cityofnewyork.us/resource/67g2-p84d.json"}`.
- **Cache.swift**: JSON files under `Application Support/NoiseScore/cache/`, keyed by a hash of the request,
  each with `fetchedAt`. TTL 7 days for pulls (T4), 15 minutes for recent complaints, 30 days for
  facilities. When the network fails and `allowCache` is true, return the cached value whatever its age
  with `fromCache = true`. `cached(address:)` never touches the network.
- **FixtureDataSource.swift**: `public struct FixtureDataSource: NoiseDataSource` replaying
  `Resources/broadway.inputs.json` and `broadway.recent.json` (Bundle.module), for previews and for the
  no-network, no-cache case. `suggest` returns the one bundled address for any text.

### M11, the sirens ingredient (new in both models)

Point sources: hospitals (ambulance bays, ER), firehouses and ambulance stations, police stations.

| Constant | Value | Note |
|---|---|---|
| `RADIUS_SIRENS_M` | 600 | about four avenue blocks |
| `SIRENS_BASE_DB` | hospital 64, fire 62, police 56 | at the reference distance |
| `SIRENS_REF_DISTANCE_M` | 50 | |
| `SIRENS_DB_PER_DOUBLING` | 4.0 | between a point and a line source: sirens move along streets |
| `SIRENS_SUM_CAP_DB` | 70 | |
| `SIRENS_NONE_DB` | 35 | no facility within the radius |
| `SIRENS_WINDOW_OFFSET` | night -3, early -2, day 0 | |

Level per facility: `base[kind] - DB_PER_DOUBLING * log2(max(d, REF) / REF)`. Energy-sum them, cap at
`SIRENS_SUM_CAP_DB`, add the window offset, then `floorAttenuation(unit) + POSITION_DB[position]` (an
outdoor source). `BOTHER_TO_INGREDIENT["sirens"] = "sirens"` adds `BOTHER_DB` like any other bother.
`street_only` is unchanged (HowLoud ignores sirens; keeping it comparable).
Evidence, in this order: `"{n} emergency facilities within 600 m: {k} hospital(s), {k} firehouse(s), {k} police station(s)"`
(omit zero kinds; singular/plural as in nightlife), then up to three nearest as
`"{facname} ({hospital|firehouse|police station}), {address}, {d} m"`. None: `"no hospital, firehouse or police station within 600 m"`.
Ingredient: `name "sirens"`, `label "Sirens"`, `temporary false`. With `options.sirens == false` the ingredient is omitted entirely.

### Tests (`Tests/NoiseKitTests`)

For each fixture slug (bedford, second-ave, claremont, broadway): decode `<slug>.inputs.json` into `Inputs`
and `<slug>.expected.json` (keys `unit`, `profile`, `result`), run `Scorer.score(inputs, unit:, profile:, options: ScoreOptions(sirens: false))`
(the fixtures predate M11) and assert: `score`, `streetOnlyScore`, each `byTime` within 1 point; each
ingredient's `levels` within 0.15 dB and `rawLevel` within 0.15; evidence line counts equal and the
first evidence line of each ingredient equal as text. Add unit tests for `windowOf`, `energySum`,
`logBump`, `GeoJSON` decoding, the lenient string decoding, the cache round trip, and a sirens test with
hand-made facilities (one hospital at 100 m: level 64 - 4 = 60 before offsets). `swift test` must pass.

## UI agent: `NoiseScore/`

Code against `NoiseKit` only through the contract types and `NoiseDataSource`. Until the KIT agent lands,
build against `FixtureDataSource` stubs of your own if needed, then delete them. Target: iPhone first, iPad
must not break. iOS 18 APIs are fine (`Map` with `Annotation`, `@Observable`, `NavigationStack`).

### The signature

Same visual signature as the HW2 app (`~/code/ENG4502_assignment_2/Assignment2/Theme.swift`): corner radius 22,
gutter 20, rounded bold numerals, greyscale first, **one accent colour per screen spent on one thing**
(the instructor takes a point off for colour overuse). Images and spacing carry the hierarchy. Dynamic
Type must work; every tappable thing has an accessibility label. No third-party packages.

Accent rule per screen: Score screen, the score ring. Nearby screen, the pins that match what bothers
the renter (the others are grey). Detail screens, the status pill or the number. Survey, the selected
option. That is the design story: the same data, recoloured by the renter's answers.

### Screens

1. **Welcome and survey** (first launch, and from the Score toolbar as "Edit answers"). Three steps with a
   progress line, one question per step, large tap targets, Continue at the bottom:
   - "How do you sleep?" light / normal / heavy sleeper, one sentence under each.
   - "What gets to you?" multi-select chips: Neighbors, Nightlife and people, Traffic, Sirens, Construction.
     Plus a toggle "I work from home most days".
   - "Your place": address field with live suggestions (GeoSearch), a "Use Columbia" shortcut that fills
     2900 Broadway, a "Use my location" button (CoreLocation when-in-use, reverse-geocode through `suggest`
     with "lat,lng" is not supported, so use `CLGeocoder` for the label and GeoSearch for the match);
     floor stepper 1 to 60 with "not sure"; faces: Street / Courtyard or back / Not sure.
   Answers persist in `UserDefaults` as JSON (`Profile`, `Unit`, `GeoAddress`).
2. **Score** (home tab). Big number in a ring (accent), "higher is quieter" caption, the line
   "A street-only map would say {streetOnlyScore}" with a one-line why. Three bars: Night, Early, Day with
   hours. Then the ingredient rows: label, a bar for the night score (the worst window if you prefer, say
   which), a "weighted up" tag when `weightedUp`, a "temporary" tag for construction. Tap a row for the
   **Ingredient detail**: per-window scores, the evidence lines as a checklist the renter can verify, the
   position adjustment in words ("floor 4 at the front: -3 dB"). Footer: address, "Data pulled {relative}"
   or "From {date}, offline", sources list, caveats.
3. **Nearby** tab: a segmented control Map | List over the same `recentComplaints` (500 m, 30 days).
   - Map: `Map` centred on the address with a subtle 500 m circle, one marker per complaint. Markers that
     match a chosen bother are accent, the rest grey; SF Symbols per category (`person.2` residential,
     `car` vehicle, `music.note` music/party, `storefront` commercial, `hammer` construction,
     `speaker.wave.2` other). Selecting a marker shows a bottom card (descriptor, address, relative time,
     status); tapping the card opens the detail. A summary strip on top: "{n} noise complaints in 30 days,
     mostly {top descriptor}".
   - List: rows sorted by distance, same symbol, descriptor, address, relative time, distance; status as a
     small pill. `NavigationLink` to the detail.
   - **Complaint detail**: descriptor as title, type and location type, address, created and closed times,
     status pill, the resolution text in a quote block, a small map snippet with the one pin, distance from
     the address, and the 311 key in the footer. This is the "separate detail view" the assignment asks for.
4. **Offline and errors**: an `NWPathMonitor` in the store sets `isOffline`. A banner under the navigation
   title: "Offline. Showing data from {date}." with Retry. If offline with nothing cached, the store falls
   back to `FixtureDataSource` and the banner says "Offline. Showing a saved sample for 2900 Broadway."
   Any other error: a readable message with Retry, never a crash, never an empty white screen.
   Test it: Simulator > Features > Network Link Conditioner is not available; instead toggle Wi-Fi off on
   the Mac, or use `xcrun simctl` is not enough; document how you tested in your report.
5. **Store**: `@MainActor @Observable final class NoiseStore` holding address, unit, profile, `pulled`,
   `result`, `recent`, `phase` (idle, loading, ready, failed(String)), `isOffline`. `refresh()` pulls both
   (`pullAll` and `recentComplaints`) concurrently, scores, and persists. `rescore()` re-runs the model when
   answers change without a network call. Inject the data source so previews use `FixtureDataSource`.
6. **App icon**: a 1024 px PNG in `Assets.xcassets/AppIcon.appiconset` (generate it with a small Swift
   script using CoreGraphics on macOS: dark rounded square, a white sound-wave glyph, the accent as one
   dot). Display name is already "Noise Score".

Previews for every screen using `FixtureDataSource`. The app must build warning-free with the xcodebuild
command above and run on the iPhone 17 Pro simulator; take screenshots of the four main screens with
`xcrun simctl io booted screenshot` into `screenshots/` (survey, score, map, detail).

## Python agent: `~/code/noise-score`

Add M11 to the Python prototype so both models agree:

- `config.py`: the sirens constants above, `BOTHER_TO_INGREDIENT["sirens"] = "sirens"`, `RADIUS_SIRENS_M`.
- `sources.py`: `facilities(lat, lng, radius_m, fresh)` pulling FacDB citywide as above (cache key without
  lat/lng so the citywide pull is shared), filtered by haversine in Python, returning the normalised rows
  `{"name", "kind", "address", "latitude", "longitude"}` with the kind mapping above; `pull_all` adds
  `"facilities"` and the eighth source.
- `model.py`: `sirens(inputs, unit)` between building and construction, evidence text exactly as above;
  `score()` includes it; `street_only` unchanged; the docstring's pipeline list and the `combine` call
  updated. `cli.py` and `api.py` accept `sirens` in `--bothers` / `bothers`.
- `DECISIONS.md`: an M11 entry in the same voice as M1 to M10, default taken, with the one decision
  (whether police stations belong, since precinct houses are quiet by day; default in). `README.md`: the
  Data table row, the ingredient list, the bothers list.
- `tests/test_model.py`: a sirens test with a hand-made facility list; `uv run pytest` (or `.venv/bin/pytest`) passes.
- Re-score the three deck addresses and print the before/after table (score, by_time) in your report.
  Commit on `main` with message `M11: sirens ingredient (hospitals, firehouses, police) from the NYC Facilities Database`. Do not push.

## Orchestrator (after the agents)

Regenerate the four fixtures with the Python model including sirens, switch the Swift comparison test to
`ScoreOptions(sirens: true)`, run `swift test`, build, run on the simulator, write README.md (purpose, the
API, the screens, how offline works, files, AI acknowledgement in the HW2 wording), commit, push `ras2369`.
