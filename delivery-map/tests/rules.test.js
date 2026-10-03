import test from 'node:test';
import assert from 'node:assert/strict';
import { STORE, distanceMeters, deliveryRule, distanceLabel, demoPoint, featureToCandidate, searchQueries, navigationUrl } from '../src/rules.js';

test('5 km and 10 km road-distance boundaries include exact thresholds', () => {
  for (const [meters, expected, eligible] of [[0,'near',true],[4999.99,'near',true],[5000,'near',true],
    [5000.01,'outer',null],[10000,'outer',null],[10000.01,'outside',false]]) {
    assert.equal(deliveryRule(meters).zone, expected);
    assert.equal(deliveryRule(meters).eligible, eligible);
  }
});
test('invalid distance cannot produce an eligible result', () => {
  for (const value of [NaN, Infinity, -1, '3000', null]) assert.throws(() => deliveryRule(value));
});
test('Haversine distance: identical point, known equatorial arc, symmetry', () => {
  assert.equal(distanceMeters(STORE, STORE), 0);
  const a = {lat:0,lng:0}, b = {lat:0,lng:1};
  assert.ok(Math.abs(distanceMeters(a,b) - 111194.9266) < .001);
  assert.equal(distanceMeters(a,b), distanceMeters(b,a));
  assert.throws(() => distanceMeters({lat:91,lng:0}, b));
});
test('straight-line helper is only used for service-area guard, never route eligibility', () => {
  for (const km of [2, 7, 12]) {
    const meters = distanceMeters(STORE,demoPoint(km));
    assert.ok(Math.abs(meters - km*1000) < 1e-6);
  }
});
test('navigation always starts at the store and uses the selected destination', () => {
  const url = new URL(navigationUrl({ lat: 24.2, lng: 120.5 }));
  assert.equal(url.searchParams.get('origin'), `${STORE.lat},${STORE.lng}`);
  assert.equal(url.searchParams.get('destination'), '24.2,120.5');
  assert.equal(url.searchParams.get('travelmode'), 'driving');
  assert.throws(() => navigationUrl({ lat: 999, lng: 0 }));
});
test('display does not round an out-of-range point back onto the boundary', () => {
  assert.equal(distanceLabel(3000.01),'3.01');
  assert.equal(distanceLabel(5000.01),'5.01');
  assert.equal(distanceLabel(10000.01),'10.01');
  assert.equal(distanceLabel(5000),'5.00');
  assert.equal(distanceLabel(distanceMeters(STORE,demoPoint(2))),'2.00');
});
test('Chinese street queries preserve the district and clearly fall back from house number', () => {
  assert.deepEqual(searchQueries('台中市清水區中社路102-21號'),['臺中市 清水區 中社路 102-21號','臺中市 清水區 中社路']);
  assert.deepEqual(searchQueries('清水車站'),['清水車站']);
});
test('geocoder validation rejects malformed or non-Taiwan data', () => {
  assert.equal(featureToCandidate({}),null);
  assert.equal(featureToCandidate({properties:{countrycode:'DE'},geometry:{coordinates:[120,24]}}),null);
  assert.equal(featureToCandidate({properties:{countrycode:'TW'},geometry:{coordinates:['120',24]}}),null);
  const candidate = featureToCandidate({properties:{countrycode:'TW',name:'清水車站',city:'臺中市',district:'清水區',osm_type:'W',osm_id:1},geometry:{coordinates:[120.5692101,24.2636915]}});
  assert.equal(candidate.precise,false);
  assert.equal(candidate.lat,24.2636915);
  assert.equal(candidate.address,'臺中市 清水區');
});
