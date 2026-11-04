/**
 * Three sample listings for the demo, written for this site (no listing site was scraped). Real buildings,
 * invented apartments. Each one shows a different case: a floor with no side, a capped verdict, and a
 * listing silent on both.
 */
export interface SampleListing {
  id: string;
  title: string;
  shows: string;
  text: string;
}

export const SAMPLES: SampleListing[] = [
  {
    id: 'claremont',
    title: 'Morningside, 4th floor',
    shows: 'Floor given, side not: a range',
    text: `Prewar one-bedroom, Apt 4C
140 Claremont Avenue, New York, NY 10027
$3,150/month · 1 bed · 1 bath

Bright and quiet one-bedroom on the fourth floor of an elevator building. Original hardwood floors, exposed brick wall in the living room, renovated kitchen with dishwasher. Two oversized windows in the bedroom. Laundry in the basement, live-in super. Steps to Riverside Park and the 1 train.

Available December 1. Cats case by case.`,
  },
  {
    id: 'w47',
    title: "Hell's Kitchen, 3rd floor front",
    shows: 'Floor and side given: one answer',
    text: `Two-bedroom walk-up #3F
310 West 47th Street, New York, NY 10036
$4,200/month · 2 beds · 1 bath

Sunny third-floor two-bedroom facing 47th Street, in the heart of the Theater District. Through-wall air conditioner in each bedroom. Windows look out on West 47th Street. Restaurants and bars on the block, Times Square five minutes away.

No fee. Guarantors welcome.`,
  },
  {
    id: 'bedford',
    title: 'Williamsburg, floor not given',
    shows: 'Silent on floor and side: expected values',
    text: `Railroad one-bedroom on Bedford
158 Bedford Avenue, Brooklyn, NY 11249
$3,400/month · 1 bed · 1 bath

Charming and peaceful railroad one-bedroom in a classic walk-up. Renovated bathroom, gas stove, new hardwood floors. Window AC units provided. Blocks from McCarren Park and the L train at Bedford Avenue.`,
  },
];
