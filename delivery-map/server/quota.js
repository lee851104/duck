// Atomic reservations shared by every Vercel instance. Never use a browser or
// process-local counter to authorize a billable Google request.
export const RESERVE_GOOGLE = `
if redis.call('EXISTS', KEYS[1]) == 0 then return -1 end
local month = redis.call('HGET', KEYS[1], 'month')
local used = tonumber(redis.call('HGET', KEYS[1], 'used'))
if not month or not used or used < 0 or used ~= math.floor(used) then return -1 end
if month > ARGV[1] then return -1 end
if month < ARGV[1] then
  redis.call('HSET', KEYS[1], 'month', ARGV[1], 'used', 0)
  used = 0
end
local day = redis.call('HGET', KEYS[1], 'day')
local today = tonumber(redis.call('HGET', KEYS[1], 'today')) or 0
if today < 0 or today ~= math.floor(today) then return -1 end
if day ~= ARGV[2] then today = 0 end
if used >= tonumber(ARGV[3]) or today >= tonumber(ARGV[4]) then return 0 end
redis.call('HSET', KEYS[1], 'used', used + 1, 'day', ARGV[2], 'today', today + 1)
return 1
`;

export function billingPeriod(now = new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now).map(p => [p.type, p.value]));
  return { month: `${parts.year}-${parts.month}`, day: `${parts.year}-${parts.month}-${parts.day}` };
}

export function limit(value, fallback, maximum) {
  if (value === undefined || value === '') return fallback;
  const n = Number(value);
  return Number.isInteger(n) && n >= 0 && n <= maximum ? n : 0;
}

export function createQuota(env, fetcher = fetch) {
  const url = env.UPSTASH_REDIS_REST_URL;
  const token = env.UPSTASH_REDIS_REST_TOKEN;
  const prefix = 'duck-delivery:v1'; // Stable across deploys and preview/production.
  async function command(args) {
    if (!url || !token || !url.startsWith('https://')) throw new Error('quota-unavailable');
    const response = await fetcher(url, { method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(args), signal: AbortSignal.timeout(3000) });
    if (!response.ok) throw new Error('quota-unavailable');
    const data = await response.json();
    if (data.error) throw new Error('quota-unavailable');
    return data.result;
  }
  return {
    command,
    ledger: `${prefix}:google`,
    async reserveGoogle(now) {
      const { month, day } = billingPeriod(now);
      const result = await command(['EVAL', RESERVE_GOOGLE, '1', `${prefix}:google`, month, day,
        String(limit(env.GOOGLE_MONTHLY_LIMIT, 9000, 9000)),
        String(limit(env.GOOGLE_DAILY_LIMIT, 250, 250))]);
      return result === 1;
    },
    async allowOsrm() {
      return await command(['SET', `${prefix}:osrm-lock`, '1', 'NX', 'PX', '1100']) === 'OK';
    },
  };
}
