import { createQuota } from '../server/quota.js';

// This is a PUBLIC, website-restricted Maps JS key, never the Routes server key.
// A reservation controls our app's map creation; it cannot hide a browser key
// or replace Google Cloud restrictions/quotas against out-of-band key usage.
export function createMapHandler({ env = process.env, quota = createQuota(env), now = () => new Date() } = {}) {
  return async function handler(req, res) {
    res.setHeader('Cache-Control', 'private, no-store');
    res.setHeader('Vercel-CDN-Cache-Control', 'no-store');
    if (req.method !== 'POST') {
      res.setHeader('Allow', 'POST'); return res.status(405).json({ error: 'method-not-allowed' });
    }
    if (req.headers['sec-fetch-site'] === 'cross-site') return res.status(403).json({ error: 'invalid-request' });
    if (!req.headers['content-type']?.startsWith('application/json')) return res.status(415).json({ error: 'invalid-request' });
    try {
      const raw = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
      if (!raw || raw.length > 64) return res.status(400).json({ error: 'invalid-request' });
      const body = JSON.parse(raw);
      if (!body || Array.isArray(body) || typeof body !== 'object' || Object.keys(body).length) return res.status(400).json({ error: 'invalid-request' });
    } catch { return res.status(400).json({ error: 'invalid-request' }); }
    if (!/^AIza[\w-]{35}$/.test(env.GOOGLE_MAPS_BROWSER_API_KEY || '')) return res.status(503).json({ error: 'maps-not-configured' });
    try {
      if (!await quota.reserveGoogleMap(now())) return res.status(429).json({ error: 'map-budget-limit' });
      return res.status(200).json({ browserKey: env.GOOGLE_MAPS_BROWSER_API_KEY });
    } catch { return res.status(503).json({ error: 'quota-unavailable' }); }
  };
}
export default createMapHandler();
