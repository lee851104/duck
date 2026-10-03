import test from 'node:test';
import assert from 'node:assert/strict';
import { STORE, distanceMeters, deliveryRule, crossesBoundary, distanceLabel, demoPoint, featureToCandidate, searchQueries } from '../src/rules.js';

test('3 km and 5 km inclusivity and just-outside cases', () => {
  for (const [meters, expected] of [[0,100],[2999.99,100],[3000,100],[3000.01,300],[4999.99,300],[5000,300],[5000.01,null]]) {
    assert.equal(deliveryRule(meters).minimum, expected);
    assert.equal(deliveryRule(meters).eligible, meters <= 5000);
  }
  assert.equal(deliveryRule(5000.01).fee, null);
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
test('classroom points actually fall into three different zones', () => {
  for (const [km,zone] of [[2,'near'],[4,'outer'],[6,'outside']]) {
    const meters = distanceMeters(STORE,demoPoint(km));
    assert.ok(Math.abs(meters - km*1000) < 1e-6);
    assert.equal(deliveryRule(meters).zone,zone);
  }
});
test('GPS uncertainty crossing either threshold requires confirmation', () => {
  assert.equal(crossesBoundary(2950,100),true);
  assert.equal(crossesBoundary(3050,100),true);
  assert.equal(crossesBoundary(4950,100),true);
  assert.equal(crossesBoundary(5100,150),true);
  assert.equal(crossesBoundary(2000,100),false);
  assert.equal(crossesBoundary(4000,100),false);
  assert.equal(crossesBoundary(6500,100),false);
  assert.equal(crossesBoundary(3000,0),false);
});
test('display does not round an out-of-range point back onto the boundary', () => {
  assert.equal(distanceLabel(3000.01),'3.01');
  assert.equal(distanceLabel(5000.01),'5.01');
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
