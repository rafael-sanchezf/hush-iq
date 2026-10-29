/**
 * Every factor that decides how loud an apartment is, and where each one stands. Built from the score map
 * (2026-10-28) and packages/model/ENGINE_V2.md; where they differ, ENGINE_V2.md is newer and wins. Rule tags
 * like [V3] point at ENGINE_V2.md. Decibel figures below are the model's internal estimates inside one source;
 * they order apartments for that source and never reach a renter.
 */

/** Flip when /v2/score is deployed: every "v2" factor then reads Live. */
export const ENGINE_V2_LIVE = false;

export type Status = 'live' | 'v2' | 'next' | 'partial' | 'tbd' | 'removed';
export type Basis = 'Data' | 'Physics' | 'Judgment';

export interface Factor {
  name: string;
  status: Status;
  basis?: Basis[];
  /** Which way the sound comes in, for the apartment lane. */
  path?: 'Outdoor' | 'Neighbors' | 'Both' | 'Inside';
  line: string;
  data?: string;
  rule?: string[];
  gap?: string;
  meta?: string;
}

export interface Lane {
  id: string;
  k: string;
  title: string;
  intro: string;
  ordered?: boolean;
  factors: Factor[];
}

export const STATUS_WORDS: Record<Status, string> = {
  live: 'Live',
  v2: ENGINE_V2_LIVE ? 'Live' : 'Engine v2',
  next: 'Next',
  partial: 'Partial',
  tbd: 'TBD',
  removed: 'Removed',
};

export const STATUS_HELP: Record<Status, string> = {
  live: 'in the hosted model today',
  v2: ENGINE_V2_LIVE ? 'in the hosted model today' : 'built in engine v2, live when /v2/score deploys',
  next: 'planned for the hackathon build',
  partial: 'part of it is live',
  tbd: 'waits, with the reason',
  removed: 'taken out, with the reason',
};

export const LANES: Lane[] = [
  {
    id: 'around',
    k: '1 · Around you',
    title: 'Sources of noise',
    intro:
      'Everything outside your walls that makes sound, plus the one big source inside the building: your neighbors. The model estimates each source at your window from public data, then ranks it against the same source across Manhattan.',
    factors: [
      {
        name: 'Street traffic', status: 'live', basis: ['Judgment', 'Physics'],
        line: 'Road type, lanes, speed and distance, plus vehicle complaints nearby.',
        data: 'NYC Street Centerline (road type, travel lanes, speed limit, one or two way, bus or truck route); 311 vehicle-noise complaints.',
        rule: [
          'Every road within 60 m. Loudness at 10 m: one-lane 56 dB, two-lane 60, arterial (3+ lanes) 66, bridge 68, ramp 70, highway 75.',
          '+2 dB on a bus or truck route, +1 per 5 mph over 25, +1 if two-way.',
          'Fades 3 dB each time the distance doubles (a road is a line of sound).',
          'Loudest segment per street name; streets added as sound energy.',
          '311 vehicle complaints within 100 m, last 24 months: +3 dB at 4 a year in a time slot, +3 more per doubling, at most +10.',
          'Night 5 dB quieter than day, early morning 2 dB quieter.',
        ],
        gap: 'No real traffic counts. The road type stands in for the traffic on it.',
      },
      {
        name: 'Elevated and surface subway', status: 'live', basis: ['Judgment'],
        line: 'Elevated, at-grade or open-cut stations within 350 m stand in for the track.',
        data: 'MTA subway stations (structure type).',
        rule: ['72 dB at 30 m from an elevated station, fading 4 dB per doubling of distance.', 'Counted within 350 m.'],
        gap: 'Uses stations, not the track itself, so a home beside the track between stations is under-counted.',
      },
      { name: 'Underground subway rumble', status: 'tbd', line: 'Vibration felt through the building from lines below.', gap: 'No public data on vibration by building. Track depth and distance would be the start.' },
      {
        name: 'Commuter and freight rail', status: 'tbd', line: 'LIRR, Metro-North, NJ Transit, Amtrak, freight.',
        data: 'Available: OpenStreetMap rail lines; the federal transportation noise map has a rail layer for the whole US.',
        gap: 'Not wired. Matters little in Manhattan, a lot in Queens and outside New York.',
      },
      {
        name: 'Planes and helicopters', status: 'tbd', line: 'Flight paths into LaGuardia, JFK and Newark; tour and commuter helicopters.',
        data: 'Available: the federal transportation noise map’s aviation layer; 311 helicopter complaints; heliport locations.',
        gap: 'Not wired yet.',
      },
      {
        name: 'Bars, clubs and restaurants', status: 'live', basis: ['Judgment', 'Physics'],
        line: 'Liquor licenses nearby plus party and music complaints.',
        meta: 'Could read each venue’s public page for closing hours, only with a real source to cite.',
        data: 'NYS liquor licenses (current, active); 311 party, music and loud-talking complaints.',
        rule: [
          'Licensed venues within 150 m. Loudness at 10 m: club or bar 66 dB, hotel, caterer, brewery or theatre 62, restaurant 58.',
          'Fades 6 dB per doubling of distance (a venue is a point of sound). All venues together capped at 75 dB.',
          'Liquor and grocery stores ignored.',
          'Party complaints within 150 m: +3 dB at 3 a year in a time slot, +3 per doubling, at most +12.',
          'Day and early morning 8 dB quieter than night.',
        ],
        gap: 'Closing hours are not known. A restaurant open to 4 am and a club open to 2 am start at the same level.',
      },
      {
        name: 'Street life and crowds', status: 'partial', basis: ['Judgment'],
        line: 'Party and loud-talking complaints are live; foot traffic, schools, parks and vendors are not.',
        data: 'Live: 311 party and loud-talking complaints (counted under nightlife). Available: 311 park-noise complaints; schools are in the NYC Facilities Database already pulled.',
        gap: 'Foot traffic has no public count. Schools, playgrounds, parks, street vendors and ice cream trucks are not wired.',
      },
      {
        name: 'Sirens', status: 'live', basis: ['Judgment'],
        line: 'Hospitals, firehouses and police stations within 600 m.',
        data: 'NYC Facilities Database.',
        rule: [
          'Loudness at 50 m: hospital or ER 64 dB, firehouse or ambulance station 62, police station 56.',
          'Fades 4 dB per doubling of distance (the vehicle leaves along the street). Capped at 70 dB; nothing nearby is 35.',
          'Night 3 dB quieter, early morning 2 dB quieter.',
        ],
        gap: 'How often sirens run is not public. Modelled from where vehicles start, not how often they leave. Dispatch records could map the routes they take.',
      },
      {
        name: 'Neighbors', status: 'live', basis: ['Data', 'Judgment'],
        line: 'Residential noise complaints at your building, against the borough rate.',
        data: '311 residential noise complaints at this exact tax lot; PLUTO (apartments, year built, building class).',
        rule: [
          'Complaints per apartment per year, blended with the borough rate (20 apartment-years of borough weight).',
          'Borough rates per 100 apartments a year: Manhattan 7.3, Brooklyn 10.8, Queens 9.4, Bronx 28.4, Staten Island 6.6.',
          'Turned into a level only to order buildings; with ranks, only the order matters.',
        ],
        gap: 'Complaints measure who complains, not how loud it is. Some neighborhoods file far more than others for the same noise.',
      },
      {
        name: 'Construction', status: 'live', basis: ['Judgment'],
        line: 'Active loud-work permits on the block and construction complaints nearby. Temporary.',
        meta: 'Permit reader: the permit’s own description (“Demolition of 3 story building”) says how big and how long.',
        data: 'DOB NOW approved permits (same tax block, not expired, last 18 months); 311 construction-noise complaints within 100 m.',
        rule: [
          '40 dB, +4 per doubling of (1 + complaints a year), +3 per doubling of (1 + active permits), at most +25. Nothing nearby is 35.',
          'Night 15 dB quieter (crews stop), early morning 3 dB quieter.',
        ],
        gap: 'A facade repair and a new tower count the same today. Shown as temporary.',
      },
      {
        name: 'Garbage trucks and deliveries', status: 'tbd', line: 'The 4 am garbage truck renters name first.',
        data: 'Available: DSNY collection schedules by district; NYC truck routes.',
        gap: 'Not wired. The clearest known gap from the renter interviews.',
      },
      { name: 'Roommates', status: 'tbd', line: 'Only with two or more bedrooms: the people you live with.', gap: 'Depends on the people and on the walls inside the apartment. Likely dropped for lack of data.' },
      {
        name: 'Building machinery', status: 'tbd', line: 'Rooftop air handling, generators, boilers, elevators.',
        data: 'Available: 311 has ventilation-equipment complaints.', gap: 'No data on which building has which equipment.',
      },
    ],
  },
  {
    id: 'apartment',
    k: '2 · This apartment',
    title: 'What lets it in or keeps it out',
    intro:
      'The half the city’s data cannot see, and where reading the listing matters most. The same street sounds different on the fourth floor at the back than on the second floor at the front. Outdoor noise comes in through the facade, mostly the windows; neighbor noise comes through walls, floors and ceilings.',
    factors: [
      {
        name: 'How high you are', status: 'live', basis: ['Judgment'], path: 'Outdoor',
        line: 'From the listing only, never asked. Each floor above the first takes 1 dB off outdoor noise, at most 8.',
        meta: 'The listing reader takes it from a line that states it next to the word floor. A unit number like 3F is not a floor.',
        rule: [
          '-1 dB per floor above the first, at most -8, on street, trains, nightlife, sirens and construction.',
          'Listing silent: the building’s middle residential floor (counting from floor 2 when the ground floor is commercial) [V7].',
          'Either floor or side missing adds a range: the lowest residential floor on the street side to the top floor at the rear [V7].',
        ],
        gap: 'One straight rule for every building. Street canyons can make some middle floors louder than this says.',
      },
      {
        name: 'Street side or inside the block', status: 'live', basis: ['Judgment'], path: 'Outdoor',
        line: 'From the listing only. Rear or courtyard units take 8 dB off outdoor noise: the biggest single swing.',
        meta: 'The listing reader: “faces the garden”, “courtyard”, and what the window photos look out on.',
        rule: ['Rear or courtyard -8 dB, street side 0.', 'Listing silent: scored as unknown (-2 dB, close to halfway in sound energy), with the range [V7].'],
        gap: 'Never asked: most people are browsing listings, not touring, and cannot know.',
      },
      {
        name: 'Windows', status: 'tbd', path: 'Outdoor',
        line: 'Open or closed, single or double glazed, fixed floor-to-ceiling glass or windows that open.',
        meta: 'The reader looks for floor-to-ceiling glass and whether windows open. Shown as “what the model saw”, not scored.',
        rule: ['Typical figures in the acoustics literature, to verify: a window open for air cuts roughly 10 to 15 dB; a closed one 25 dB or more.'],
        gap: 'Probably the biggest apartment factor for outdoor noise, and none of it is modelled. A one-tap question (do you sleep with a window open?) could carry most of it.',
      },
      {
        name: 'Exterior walls and building age', status: 'partial', basis: ['Data', 'Judgment'], path: 'Both',
        line: 'Age and type are live for neighbor noise; their effect on outdoor noise is not.',
        data: 'PLUTO year built and building class.',
        rule: ['On neighbor noise: pre-war walk-up +4 dB (wood joists, plaster), pre-war elevator building +1, built 1940 to 1999 +1, any walk-up +1.'],
        gap: 'Thick pre-war masonry likely blocks more street noise than a glass tower, but there is no rule for it yet.',
      },
      {
        name: 'Top floor, ground floor, over a shop', status: 'live', basis: ['Judgment'], path: 'Neighbors',
        line: 'Nobody above you, a lobby beside you, or a bar below you.',
        rule: ['Top floor -3 dB on neighbor noise.', 'First floor +2 dB (lobby, buzzer, front door).', 'Floors 1 and 2 in a building with a shop or restaurant +5 dB on nightlife; the second floor over it +2 on neighbors.'],
      },
      {
        name: 'How many neighbors you share walls with', status: 'next', basis: ['Data'], path: 'Neighbors',
        line: 'Apartments per floor as a first proxy; the floor plan for the exact count.', meta: 'The listing reader on the floor plan image.',
        data: 'PLUTO: apartments divided by floors, available for every building today.', gap: 'Exact shared walls need the floor plan, which only some listings carry.',
      },
      {
        name: 'Wall material and thickness', status: 'tbd', path: 'Neighbors',
        line: 'Drywall, plaster, brick or concrete; a concrete slab or wood joists.',
        meta: 'Listing photos: exposed brick is easy to see; drywall against plaster is hard to tell. Shown as “what the model saw”.',
        gap: 'No public data on wall material. Building age and class are the only prior today.',
      },
      {
        name: 'Wall to the hallway', status: 'tbd', path: 'Neighbors', line: 'Hallway chatter, the elevator, deliveries at the next door.',
        meta: 'Photos of the entry door and hallway, where the listing has them.', data: 'Apartments per floor (PLUTO) says how busy the hallway is.',
        gap: 'Nothing says how well the wall and door block it. Likely a small effect.',
      },
      {
        name: 'Doorman or open building', status: 'tbd', path: 'Neighbors', line: 'Whether deliveries and visitors come up to your door or stop at the lobby.',
        meta: 'The listing reader on the amenities list (doorman, virtual doorman, package room).', gap: 'Listings usually say it. The effect size is a guess; it waits for evidence.',
      },
      {
        name: 'Walls inside the apartment', status: 'tbd', path: 'Inside', line: 'Roommates. Only matters with two or more bedrooms.',
        meta: 'Listing photos and floor plan: wall material, bedrooms side by side.', gap: 'The hardest one to estimate. Likely dropped unless photos can tell wall material.',
      },
      { name: 'Where the bedroom sits', status: 'tbd', path: 'Both', line: 'A bedroom on the street side of a rear unit, or at the back of a front one.', meta: 'Floor plan image.', gap: 'Needs the floor plan. Matters most for light sleepers in large apartments.' },
      { name: 'Corner unit', status: 'tbd', path: 'Outdoor', line: 'Exposed to two streets instead of one.', data: 'Available: NYC building footprints.', gap: 'The reader reads “corner unit” from the text; it scores as street side until a rule for two streets exists.' },
      { name: 'Window air conditioners', status: 'tbd', path: 'Outdoor', line: 'Through-wall sleeves and window units leak street noise and add their own.', meta: 'Listing photos. Shown as “what the model saw”.', gap: 'No data outside listing photos.' },
    ],
  },
  {
    id: 'you',
    k: '3 · You',
    title: 'Who is listening',
    intro:
      'The questions ask only what a listing cannot tell: when you sleep and what gets to you. People use this while browsing, before any tour, so facts about the apartment come from the listing or become expected values. Three taps, so people finish.',
    factors: [
      {
        name: 'What gets to you', status: 'v2', basis: ['Data', 'Judgment'],
        line: 'Tick the sources that get to you. Each tick counts three times as much [V3].',
        rule: [
          'Starting weights: street 32, sirens 20, neighbors 20, nightlife 15, construction 13, from New York City health department noise surveys (Epi Data Briefs 45 and 105), the mean of three readings, rounded.',
          '311 complaint shares are not used: the surveys show they over-count neighbors and under-count traffic.',
          'A ticked source counts three times; the weights are then rescaled. Tick traffic and street noise goes from 32% to 58.5% of the verdict.',
        ],
        gap: 'The starting weights should be checked against what renters say they hear.',
      },
      {
        name: 'When do you sleep?', status: 'v2', basis: ['Judgment'],
        line: 'Any hours, from and until. An hour you sleep counts most [V2].',
        rule: [
          'An hour asleep weighs 3, an hour awake 1. A slot’s weight is the sum of its hours.',
          'Asleep 11 pm to 7 am gives night 48%, early morning 18%, day 35%. A night owl’s 5 am counts; their 11 pm barely does.',
        ],
        gap: 'The model’s levels are still in three slots (night 10 pm to 5 am, early 5 to 8 am, day 8 am to 10 pm), so each hour takes its slot’s level. Complaints carry timestamps; traffic, sirens and construction need hourly assumptions.',
      },
      { name: 'Does daytime noise bother you?', status: 'v2', basis: ['Judgment'], line: 'Yes or no. Sets how much the day counts [V2].', rule: ['No: an awake hour weighs 0.5 instead of 1.', 'Replaces the work-from-home question, which only covered one reason to be home.'] },
      { name: 'Floor and side', status: 'removed', line: 'Not asked. Someone browsing has not toured the apartment and cannot know. Read from the listing; if it is silent, the expected value and a range.', meta: 'The listing reader.' },
      { name: 'Do you sleep with a window open?', status: 'tbd', line: 'One tap that would carry most of the window factor.', gap: 'Worth adding once the window rule exists.' },
      { name: 'Light, normal or heavy sleeper', status: 'removed', line: 'Taken out. It set the night weight but told us little; the sleep-hours question does its job better.' },
    ],
  },
  {
    id: 'engine',
    k: '4 · How it adds up',
    title: 'From sources to a verdict',
    ordered: true,
    intro:
      'The steps, in order. The hosted model adds the sources as sound energy. Engine v2 never adds sources: each one is ranked against the same source across Manhattan, and the ranks are averaged with your weights.',
    factors: [
      { name: 'Level at your window, per source', status: 'live', basis: ['Judgment', 'Physics'], line: 'Each source as an estimated level at the window, per time slot, after floor and side [V1]. Internal only.' },
      {
        name: 'Fill what the listing does not say', status: 'v2', basis: ['Judgment'],
        line: 'No floor or side in the listing: the expected value, and the range [V7].',
        rule: ['No floor: the building’s middle residential floor.', 'No side: unknown.', 'Either missing: the verdict also comes for the loudest case (lowest residential floor, street side) and the quietest (top floor, rear).'],
      },
      { name: 'Time of day', status: 'v2', basis: ['Judgment'], line: 'Each source’s slot levels averaged with your hours’ weights [V2].' },
      {
        name: 'Compare each source to the city', status: 'v2', basis: ['Data'],
        line: 'Each source becomes “quieter than X% of Manhattan apartments” [V4].',
        rule: ['Ranked against the 300-building Manhattan sample, every sample building at a typical apartment: the middle residential floor, side unknown.', 'A fixed Manhattan, so a higher floor at the rear always moves the verdict the right way.'],
        gap: 'Removes the guesswork of adding a neighbor “66” to a street “66”: a rank only cares which apartment is louder for that source.',
      },
      { name: 'Weight by what gets to you', status: 'v2', basis: ['Data', 'Judgment'], line: 'Health-department starting weights; each ticked source counts three times [V3].' },
      {
        name: 'Rank again and give the verdict', status: 'v2', basis: ['Data'],
        line: 'The weighted average of the five ranks, re-ranked against the same average for every sample building, in fifths [V5].',
        rule: ['Very loud, Loud, Typical, Quiet, Very quiet: one fifth of Manhattan each.'],
        meta: 'The verdict writer explains it in a paragraph and may cite only the evidence lines it was sent.',
      },
      {
        name: 'Dealbreaker check', status: 'v2', basis: ['Judgment'],
        line: 'One terrible source cannot be outvoted [V6].',
        rule: ['Any source in Manhattan’s loudest 5% caps the verdict at Loud.', 'A source you ticked in the loudest 10% caps it at Typical.', 'Each cap comes back with the source that set it, and whether it changed the verdict.'],
      },
      {
        name: 'The comparison set', status: 'partial', basis: ['Data'],
        line: '300 Manhattan buildings, drawn by residential units, standing for about 958,000 apartments.',
        rule: ['Sampled by community district, seed fixed, weighted so a 400-unit tower counts 400 times a brownstone apartment.'],
        gap: 'Five boroughs next (about four times the data pulls). Other US cities after: the federal noise map and OpenStreetMap cover sources everywhere; neighbor complaints exist only where a city publishes 311 data.',
        meta: 'A city mapper could read each city’s complaint categories onto these sources.',
      },
    ],
  },
];

/** Engine v2's rules, V1 to V8, in plain words (packages/model/ENGINE_V2.md). */
export const RULES: { k: string; title: string; body: string[] }[] = [
  { k: 'V1', title: 'Five sources', body: ['Street, nightlife, neighbors, sirens and construction, each estimated per time slot from the frozen model, after the floor and the side.'] },
  { k: 'V2', title: 'Your hours', body: ['An hour you are asleep weighs 3, an hour awake 1, or 0.5 if daytime noise does not bother you. Each source’s night, early and day levels are averaged with those weights.'] },
  { k: 'V3', title: 'Weights', body: ['Street 32, sirens 20, neighbors 20, nightlife 15, construction 13, from New York City health department noise surveys. A source you tick counts three times; the weights are then rescaled.'] },
  { k: 'V4', title: 'Ranks', body: ['Each source is ranked against the same source in 300 Manhattan buildings, each at a typical apartment. The rank reads “quieter than X% of Manhattan apartments”.'] },
  { k: 'V5', title: 'The verdict', body: ['The weighted average of the five ranks, ranked again against the same average for every sample building, in fifths: Very loud, Loud, Typical, Quiet, Very quiet.'] },
  { k: 'V6', title: 'Caps', body: ['Any source in Manhattan’s loudest 5% caps the verdict at Loud. A source you ticked in the loudest 10% caps it at Typical. Each cap is shown with the source that set it.'] },
  { k: 'V7', title: 'A silent listing', body: ['No floor: the middle residential floor. No side: unknown. Either missing adds a range, from the lowest residential floor on the street side to the top floor at the rear.'] },
  { k: 'V8', title: 'No decibels leave the engine', body: ['Every number it returns is a rank, a weight, a floor or a count. Decibel-shaped estimates live only inside each source, where road size against distance is physics, and they only order apartments for that source.'] },
];
