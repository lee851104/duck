import { createQuota, billingPeriod } from '../server/quota.js';

const used = Number(process.argv[2]);
if (process.argv.length !== 3 || !Number.isInteger(used) || used < 0) {
  console.error('Usage: npm run budget:init -- <already-used-this-month>');
  process.exitCode = 1;
} else {
  const quota = createQuota(process.env);
  const { month, day } = billingPeriod();
  // An operator must explicitly seed a missing ledger. Never reset an existing
  // ledger: losing the counter must not silently grant another free allowance.
  const result = await quota.command(['EVAL', `
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('HSET', KEYS[1], 'month', ARGV[1], 'used', ARGV[2], 'day', ARGV[3], 'today', 0)
return 1`, '1', quota.ledger, month, String(used), day]);
  console.log(result === 1 ? `Initialized ${month} budget with ${used} already-used slots.`
    : 'Ledger already exists; nothing changed.');
}
