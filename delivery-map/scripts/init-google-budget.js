import { createQuota, billingPeriod } from '../server/quota.js';

const used = Number(process.argv[2]);
const kind = process.argv[3] || 'routes';
if (process.argv.length < 3 || process.argv.length > 4 || !['routes', 'dynamic-maps'].includes(kind) || !Number.isInteger(used) || used < 0) {
  console.error('Usage: npm run budget:init -- <already-used-this-month> [routes|dynamic-maps]');
  process.exitCode = 1;
} else {
  const quota = createQuota(process.env);
  const { month, day } = billingPeriod();
  const ledger = kind === 'dynamic-maps' ? quota.mapsLedger : quota.ledger;
  // An operator must explicitly seed a missing ledger. Never reset an existing
  // ledger: losing the counter must not silently grant another free allowance.
  const result = await quota.command(['EVAL', `
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('HSET', KEYS[1], 'month', ARGV[1], 'used', ARGV[2], 'day', ARGV[3], 'today', 0)
return 1`, '1', ledger, month, String(used), day]);
  console.log(result === 1 ? `Initialized ${kind} ${month} budget with ${used} already-used slots.`
    : 'Ledger already exists; nothing changed.');
}
