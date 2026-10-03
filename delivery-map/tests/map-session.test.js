import test from 'node:test';
import assert from 'node:assert/strict';
import { createMapHandler } from '../api/map-session.js';
import { createQuota } from '../server/quota.js';

const browserKey = 'AIza' + 'x'.repeat(35); // fake, format-only test value
const env = { GOOGLE_MAPS_BROWSER_API_KEY: browserKey, GOOGLE_ROUTES_API_KEY: 'server-secret' };
const request = { method: 'POST', headers: { 'content-type': 'application/json' }, body: {} };
function recorder() {
  return { headers: {}, code: 200, setHeader(k, v) { this.headers[k] = v; },
    status(n) { this.code = n; return this; }, json(body) { this.body = body; return this; } };
}
test('map initialization reserves its own slot and returns only the website-restricted key', async () => {
  let reservations = 0;
  const handler = createMapHandler({ env, quota: { reserveGoogleMap: async () => { reservations++; return true; } } });
  const res = recorder(); await handler(request, res);
  assert.equal(res.code, 200); assert.equal(reservations, 1);
  assert.deepEqual(res.body, { browserKey });
  assert.equal(res.headers['Cache-Control'], 'private, no-store');
  assert.equal(res.headers['Vercel-CDN-Cache-Control'], 'no-store');
});
test('map exhaustion and counter outage never release a key', async () => {
  for (const [reserveGoogleMap, code, error] of [
    [async () => false, 429, 'map-budget-limit'],
    [async () => { throw new Error('secret'); }, 503, 'quota-unavailable'],
  ]) {
    const res = recorder(); await createMapHandler({ env, quota: { reserveGoogleMap } })(request, res);
    assert.equal(res.code, code); assert.deepEqual(res.body, { error });
  }
});
test('missing or masked browser keys do not consume budget', async () => {
  for (const key of [undefined, '••••••••', 'duck-maps-browser']) {
    const res = recorder(); await createMapHandler({ env: { GOOGLE_MAPS_BROWSER_API_KEY: key },
      quota: { reserveGoogleMap: async () => assert.fail('reservation') } })(request, res);
    assert.equal(res.code, 503);
  }
});
test('invalid map requests are rejected before budget or key access', async () => {
  const handler = createMapHandler({ env, quota: { reserveGoogleMap: async () => assert.fail('reservation') } });
  for (const [req, code] of [
    [{ ...request, method: 'GET' }, 405],
    [{ ...request, headers: {} }, 415],
    [{ ...request, headers: { ...request.headers, 'sec-fetch-site': 'cross-site' } }, 403],
    [{ ...request, body: { reset: true } }, 400],
    [{ ...request, body: [] }, 400],
    [{ ...request, body: null }, 400],
    [{ ...request, body: ' '.repeat(65) }, 400],
    [{ ...request, body: '{' }, 400],
  ]) { const res = recorder(); await handler(req, res); assert.equal(res.code, code); }
});
test('map ledger and limits are separate from Routes; missing ledger fails closed', async () => {
  const calls = [];
  const quota = createQuota({ UPSTASH_REDIS_REST_URL: 'https://example.test', UPSTASH_REDIS_REST_TOKEN: 'test',
    GOOGLE_MONTHLY_LIMIT: '20', GOOGLE_DAILY_LIMIT: '10', GOOGLE_MAPS_MONTHLY_LIMIT: '100000', GOOGLE_MAPS_DAILY_LIMIT: '250' },
  async (_, init) => { calls.push(JSON.parse(init.body)); return new Response(JSON.stringify({ result: -1 })); });
  assert.equal(await quota.reserveGoogleMap(), false);
  assert.equal(calls[0][3], 'duck-delivery:v1:dynamic-maps');
  assert.deepEqual(calls[0].slice(-2), ['0', '250']);
  await quota.reserveGoogle();
  assert.equal(calls[1][3], 'duck-delivery:v1:google');
  assert.deepEqual(calls[1].slice(-2), ['20', '10']);
});
