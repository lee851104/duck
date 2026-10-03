import test from 'node:test';
import assert from 'node:assert/strict';
import { createRouter, validateDestination } from '../server/routing.js';
import { createQuota, billingPeriod, limit } from '../server/quota.js';
import { createHandler } from '../api/route.js';

const point = { lat: 24.2636915, lng: 120.5692101 };
const env = { GOOGLE_ROUTES_API_KEY: 'test-routes', GOOGLE_STATIC_MAPS_API_KEY: 'test-static' };
const quota = { reserveGoogle: async () => true, allowOsrm: async () => true };
const google = { routes: [{ distanceMeters: 5200, duration: '600s', polyline: { encodedPolyline: 'test-polyline' } }] };
const osrm = { code: 'Ok', routes: [{ distance: 6800, duration: 700,
  geometry: { type: 'LineString', coordinates: [[120.545, 24.274], [120.56, 24.27], [point.lng, point.lat]] } }],
  waypoints: [{ distance: 3 }, { distance: 9 }] };
const asJson = value => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });
test('Google route reserves before one Essentials call; no static map or server key returned', async () => {
  const events = [];
  const route = createRouter({ env, quota: { ...quota, reserveGoogle: async () => { events.push('reserve'); return true; } },
    fetcher: async (url, init) => {
      assert.ok(url.includes('computeRoutes')); events.push('routes');
      const body = JSON.parse(init.body);
      assert.equal(body.travelMode, 'DRIVE'); assert.equal(body.routingPreference, 'TRAFFIC_UNAWARE');
      assert.equal(body.computeAlternativeRoutes, false);
      assert.equal(init.headers['X-Goog-Api-Key'], env.GOOGLE_ROUTES_API_KEY);
      return asJson(google);
    } });
  const result = await route(point);
  assert.deepEqual(events, ['reserve', 'routes']);
  assert.equal(result.provider, 'google'); assert.equal(result.meters, 5200);
  assert.equal(result.encodedPolyline, 'test-polyline');
  assert.equal(result.mapImage, undefined);
  assert.ok(!JSON.stringify(result).includes('test-routes'));
  assert.ok(!JSON.stringify(result).includes('test-static'));
});

for (const [name, reserve] of [['budget exhausted', async () => false],
  ['counter unavailable', async () => { throw new Error('offline'); }]]) {
  test(`${name} never calls Google and selects OSRM`, async () => {
    let requests = 0;
    const route = createRouter({ env, quota: { ...quota, reserveGoogle: reserve }, fetcher: async url => {
      requests++; assert.ok(url.startsWith('https://routing.openstreetmap.de/'));
      assert.ok(url.includes('radiuses=100;100')); return asJson(osrm);
    } });
    const result = await route(point);
    assert.equal(result.provider, 'osrm'); assert.equal(result.meters, 6800);
    assert.deepEqual(result.coordinates[0], [24.274, 120.545]);
    assert.equal(requests, 1);
  });
}

test('no key skips Google and its budget entirely', async () => {
  const route = createRouter({ env: {}, quota: { ...quota, reserveGoogle: async () => assert.fail('no key') },
    fetcher: async () => asJson(osrm) });
  assert.equal((await route(point)).provider, 'osrm');
});

for (const status of [403, 429, 500]) {
  test(`Google HTTP ${status} falls back once with no refunds or retries`, async () => {
    let reserved = 0; let googleCalls = 0;
    const route = createRouter({ env, quota: { ...quota, reserveGoogle: async () => { reserved++; return true; } },
      fetcher: async url => {
        if (url.includes('googleapis')) { googleCalls++; return new Response('', { status }); }
        return asJson(osrm);
      } });
    assert.equal((await route(point)).provider, 'osrm');
    assert.equal(reserved, 1); assert.equal(googleCalls, 1);
  });
}

test('invalid Google geometry falls back to an independent OSRM route', async () => {
  const route = createRouter({ env, quota, fetcher: async url => url.includes('computeRoutes')
    ? asJson({ routes: [{ ...google.routes[0], polyline: {} }] }) : asJson(osrm) });
  const result = await route(point);
  assert.equal(result.provider, 'osrm'); assert.equal(result.meters, 6800);
  assert.equal(result.encodedPolyline, undefined);
});

test('invalid, too-far and malformed destinations consume no quota or provider calls', async () => {
  const route = createRouter({ env, quota: { reserveGoogle: async () => assert.fail('quota'), allowOsrm: async () => assert.fail('quota') },
    fetcher: async () => assert.fail('network') });
  for (const p of [null, {}, { lat: '24', lng: 120 }, { lat: 90, lng: 120 }, { lat: NaN, lng: 120 }]) {
    await assert.rejects(route(p), { code: 'invalid-destination', status: 400 });
  }
  assert.deepEqual(validateDestination(point), point);
});

test('OSRM rate limit rejects without an upstream request', async () => {
  const route = createRouter({ env: {}, quota: { ...quota, allowOsrm: async () => false }, fetcher: async () => assert.fail('network') });
  await assert.rejects(route(point), { code: 'busy', status: 429 });
});

test('OSRM quota outage fails closed rather than overloading the public server', async () => {
  const route = createRouter({ env: {}, quota: { ...quota, allowOsrm: async () => { throw new Error(); } }, fetcher: async () => assert.fail('network') });
  await assert.rejects(route(point), { code: 'quota-unavailable' });
});

for (const [name, data] of [['no route', { code: 'NoRoute' }], ['empty geometry', { ...osrm,
  routes: [{ ...osrm.routes[0], geometry: { type: 'LineString', coordinates: [] } }] }],
['remote snapped road', { ...osrm, waypoints: [{ distance: 0 }, { distance: 900 }] }],
['negative distance', { ...osrm, routes: [{ ...osrm.routes[0], distance: -1 }] }]]) {
  test(`OSRM ${name} never produces delivery eligibility`, async () => {
    const route = createRouter({ env: {}, quota, fetcher: async () => asJson(data) });
    await assert.rejects(route(point), { code: 'no-route' });
  });
}

test('both providers fail without falling back to a straight line', async () => {
  const route = createRouter({ env, quota, fetcher: async () => { throw new Error('offline'); } });
  await assert.rejects(route(point), { code: 'provider-unavailable' });
});

test('explicit OSRM fallback cannot reserve another Google slot', async () => {
  const route = createRouter({ env, quota: { ...quota, reserveGoogle: async () => assert.fail('Google') }, fetcher: async () => asJson(osrm) });
  assert.equal((await route(point, { osrmOnly: true })).provider, 'osrm');
});

test('budget counter uses one atomic EVAL, fixed ledger and capped limits', async () => {
  const q = createQuota({ UPSTASH_REDIS_REST_URL: 'https://example.test', UPSTASH_REDIS_REST_TOKEN: 'test',
    GOOGLE_MONTHLY_LIMIT: '100000', GOOGLE_DAILY_LIMIT: '999' }, async (_, init) => {
    const args = JSON.parse(init.body);
    assert.equal(args[0], 'EVAL'); assert.equal(args[3], 'duck-delivery:v1:google');
    assert.deepEqual(args.slice(-2), ['0', '0']); return asJson({ result: 0 });
  });
  assert.equal(await q.reserveGoogle(new Date('2026-10-03T12:00:00Z')), false);
});

test('missing or corrupt ledger result cannot authorize Google', async () => {
  for (const result of [-1, null, undefined, '1', 0]) {
    const q = createQuota({ UPSTASH_REDIS_REST_URL: 'https://example.test', UPSTASH_REDIS_REST_TOKEN: 'test' },
      async () => asJson({ result }));
    assert.equal(await q.reserveGoogle(), false);
  }
  await assert.rejects(createQuota({}).reserveGoogle());
});

test('calendar follows Pacific time and invalid limit values disable paid calls', () => {
  assert.equal(billingPeriod(new Date('2026-11-01T06:59:59Z')).month, '2026-10');
  assert.equal(billingPeriod(new Date('2026-11-01T07:00:00Z')).month, '2026-11');
  assert.equal(limit(undefined, 9000, 9000), 9000);
  for (const value of ['no', '-1', '9001', '1.5']) assert.equal(limit(value, 9000, 9000), 0);
});

function responseRecorder() {
  return { headers: {}, code: 200, setHeader(k, v) { this.headers[k] = v; },
    status(code) { this.code = code; return this; }, json(value) { this.body = value; return this; } };
}

test('HTTP endpoint rejects methods, cross-site and invalid/oversized JSON before routing', async () => {
  const handler = createHandler(async () => assert.fail('upstream'));
  for (const [method, headers, body, status] of [
    ['GET', {}, '', 405], ['POST', {}, '{}', 415],
    ['POST', { 'content-type': 'application/json', 'sec-fetch-site': 'cross-site' }, '{}', 403],
    ['POST', { 'content-type': 'application/json' }, '{', 400],
    ['POST', { 'content-type': 'application/json' }, ' '.repeat(600), 400],
    ['POST', { 'content-type': 'application/json' }, JSON.stringify({ ...point, origin: 'override' }), 400],
  ]) {
    const res = responseRecorder(); await handler({ method, headers, body }, res);
    assert.equal(res.code, status); assert.equal(res.headers['Cache-Control'], 'private, no-store');
  }
});

test('HTTP endpoint returns no secrets on unexpected error', async () => {
  const handler = createHandler(async () => { throw new Error('secret'); });
  const res = responseRecorder();
  await handler({ method: 'POST', headers: { 'content-type': 'application/json' }, body: point }, res);
  assert.equal(res.code, 503); assert.deepEqual(res.body, { error: 'provider-unavailable' });
});
