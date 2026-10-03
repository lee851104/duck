// Explicit opt-in integration check. Uses an isolated, expiring test key;
// never touches the production ledger or calls Google/OSRM.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { createQuota, RESERVE_GOOGLE } from '../server/quota.js';

const quota = createQuota(process.env);
const key = `duck-delivery:test:${randomUUID()}`;
const call = (month, day, monthly, daily) => quota.command(['EVAL', RESERVE_GOOGLE, '1', key,
  month, day, String(monthly), String(daily)]);
try {
  assert.equal(await call('2026-10', '2026-10-03', 5, 5), -1, 'missing ledger must fail closed');
  await quota.command(['HSET', key, 'month', '2026-10', 'used', '0']);
  await quota.command(['EXPIRE', key, '300']);
  const results = await Promise.all(Array.from({ length: 20 }, () => call('2026-10', '2026-10-03', 5, 5)));
  assert.equal(results.filter(n => n === 1).length, 5, '20 concurrent requests must grant exactly 5 slots');
  assert.equal(await call('2026-10', '2026-10-04', 5, 5), 0, 'new day must not reset monthly cap');
  assert.equal(await call('2026-11', '2026-11-01', 5, 1), 1, 'new month must reset monthly count');
  assert.equal(await call('2026-11', '2026-11-01', 5, 1), 0, 'daily cap must apply');
  assert.equal(await call('2026-10', '2026-10-31', 5, 5), -1, 'stale month must not reset ledger');
  await quota.command(['HSET', key, 'used', 'corrupt']);
  assert.equal(await call('2026-11', '2026-11-02', 5, 5), -1, 'corrupt ledger must fail closed');
  console.log('Redis atomic budget integration checks passed; Google was not called.');
} finally {
  await quota.command(['DEL', key]);
}
