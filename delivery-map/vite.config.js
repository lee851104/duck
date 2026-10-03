import { defineConfig, loadEnv } from 'vite';
import { createHandler } from './api/route.js';
import { createRouter } from './server/routing.js';
import { createQuota } from './server/quota.js';

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ''), ...process.env };
  let lastOsrm = 0;
  const configured = env.UPSTASH_REDIS_REST_URL && env.UPSTASH_REDIS_REST_TOKEN;
  // Local, single-process demonstration only. This path never authorizes Google.
  const quota = configured ? createQuota(env) : {
    reserveGoogle: async () => false,
    allowOsrm: async () => {
      if (Date.now() - lastOsrm < 1100) return false;
      lastOsrm = Date.now(); return true;
    },
  };
  const handler = createHandler(createRouter({ env, quota }));
  function middleware(server) {
    server.middlewares.use('/api/route', async (req, res) => {
      res.status = code => { res.statusCode = code; return res; };
      res.json = value => { res.setHeader('Content-Type', 'application/json; charset=utf-8'); res.end(JSON.stringify(value)); };
      let body = '';
      for await (const chunk of req) {
        body += chunk;
        if (body.length > 512) { res.status(400).json({ error: 'invalid-request' }); return; }
      }
      req.body = body;
      await handler(req, res);
    });
  }
  return { plugins: [{ name: 'local-route-api', configureServer: middleware, configurePreviewServer: middleware }] };
});
