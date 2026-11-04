/** The rules reader's floor from the unit number, as the reader service does it. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { extract, floorFromUnit } from '../src/lib/mock/extract.ts';

test('New York unit numbering gives the floor', () => {
  assert.deepEqual(['3E', '#3E', 'Apt 12F', '503', '1203', '2', '14', 'PH', 'B', '0A'].map(floorFromUnit), [3, 3, 12, 5, 12, null, null, null, null, null]);
});

test('a unit gives the floor only when the listing states none', () => {
  const silent = extract('Renovated 1BR at 520 2nd Avenue #3E, New York, NY 10016. $4,100 a month.');
  assert.equal(silent.fields.floor.value, 3);
  assert.equal(silent.fields.floor.derived?.from, 'unit');
  const stated = extract('Renovated 1BR at 520 2nd Avenue #3E, New York, NY 10016, on the fourth floor.');
  assert.equal(stated.fields.floor.value, 4);
  assert.equal(stated.fields.floor.derived, undefined);
});
