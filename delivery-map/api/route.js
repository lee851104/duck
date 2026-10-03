import { createRouter, RouteError } from '../server/routing.js';

export function createHandler(router = createRouter()) {
  return async function handler(req, res) {
    res.setHeader('Cache-Control', 'private, no-store');
    res.setHeader('Vercel-CDN-Cache-Control', 'no-store');
    if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); return res.status(405).json({ error: 'method-not-allowed' }); }
    const type = req.headers['content-type'] || '';
    if (!type.startsWith('application/json')) return res.status(415).json({ error: 'invalid-request' });
    if (req.headers['sec-fetch-site'] === 'cross-site') return res.status(403).json({ error: 'invalid-request' });
    try {
      const raw = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
      if (!raw || raw.length > 512) return res.status(400).json({ error: 'invalid-request' });
      const body = JSON.parse(raw);
      if (body === null || typeof body !== 'object' || Array.isArray(body)
          || Object.keys(body).some(key => !['lat', 'lng', 'osrmOnly'].includes(key))
          || (body.osrmOnly !== undefined && typeof body.osrmOnly !== 'boolean')) {
        return res.status(400).json({ error: 'invalid-request' });
      }
      return res.status(200).json(await router(body, { osrmOnly: body.osrmOnly === true }));
    } catch (error) {
      if (error instanceof SyntaxError) return res.status(400).json({ error: 'invalid-request' });
      if (error instanceof RouteError) {
        if (error.status === 429) res.setHeader('Retry-After', '2');
        return res.status(error.status).json({ error: error.code });
      }
      return res.status(503).json({ error: 'provider-unavailable' });
    }
  };
}
export default createHandler();
