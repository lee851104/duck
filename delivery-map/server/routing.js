import { STORE, distanceMeters, validPoint } from '../src/rules.js';
import { createQuota } from './quota.js';

export class RouteError extends Error {
  constructor(code, status = 503) { super(code); this.code = code; this.status = status; }
}
const finiteDistance = value => Number.isFinite(value) && value >= 0;

export function validateDestination(point) {
  // Service area guard only; delivery eligibility ALWAYS uses the road route.
  if (!validPoint(point) || distanceMeters(STORE, point) > 60000) {
    throw new RouteError('invalid-destination', 400);
  }
  return { lat: point.lat, lng: point.lng };
}

async function json(response) {
  if (!response.ok) throw new RouteError('provider-unavailable');
  return response.json();
}

export async function googleRoute(point, env, fetcher) {
  const response = await fetcher('https://routes.googleapis.com/directions/v2:computeRoutes', {
    method: 'POST', headers: { 'Content-Type': 'application/json',
      'X-Goog-Api-Key': env.GOOGLE_ROUTES_API_KEY,
      'X-Goog-FieldMask': 'routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline' },
    body: JSON.stringify({ origin: { location: { latLng: { latitude: STORE.lat, longitude: STORE.lng } } },
      destination: { location: { latLng: { latitude: point.lat, longitude: point.lng } } },
      travelMode: 'DRIVE', routingPreference: 'TRAFFIC_UNAWARE', computeAlternativeRoutes: false,
      polylineQuality: 'OVERVIEW', languageCode: 'zh-TW', units: 'METRIC' }),
    signal: AbortSignal.timeout(7000),
  });
  const route = (await json(response)).routes?.[0];
  const encoded = route?.polyline?.encodedPolyline;
  const duration = typeof route?.duration === 'string' && /^\d+(\.\d+)?s$/.test(route.duration)
    ? Number(route.duration.slice(0, -1)) : NaN;
  if (!finiteDistance(route?.distanceMeters) || !finiteDistance(duration)
      || typeof encoded !== 'string' || !encoded || encoded.length > 6000) throw new RouteError('no-route');

  return { provider: 'google', meters: route.distanceMeters, seconds: duration, encodedPolyline: encoded };
}

export async function osrmRoute(point, env, fetcher) {
  const base = env.OSRM_BASE_URL || 'https://routing.openstreetmap.de/routed-car';
  if (!base.startsWith('https://')) throw new RouteError('provider-unavailable');
  const url = `${base.replace(/\/$/, '')}/route/v1/driving/${STORE.lng},${STORE.lat};${point.lng},${point.lat}`
    + '?overview=full&geometries=geojson&steps=false&alternatives=false&radiuses=100;100';
  const data = await json(await fetcher(url, { signal: AbortSignal.timeout(9000),
    headers: { 'User-Agent': 'DuckDeliveryMap/2.0 (+https://duck-delivery-map.vercel.app/)' } }));
  const route = data.routes?.[0];
  const coords = route?.geometry?.coordinates;
  if (data.code !== 'Ok' || !finiteDistance(route?.distance) || !finiteDistance(route?.duration)
      || route?.geometry?.type !== 'LineString' || !Array.isArray(coords) || coords.length < 2 || coords.length > 20000
      || !coords.every(c => Array.isArray(c) && validPoint({ lng: c[0], lat: c[1] }))
      || !Array.isArray(data.waypoints) || data.waypoints.length !== 2
      || !data.waypoints.every(w => finiteDistance(w.distance) && w.distance <= 100)) throw new RouteError('no-route');
  return { provider: 'osrm', meters: route.distance, seconds: route.duration,
    coordinates: coords.map(([lng, lat]) => [lat, lng]),
    snappedMeters: Math.max(...data.waypoints.map(w => w.distance)) };
}

export function createRouter({ env = process.env, fetcher = fetch, quota = createQuota(env, fetcher),
  now = () => new Date() } = {}) {
  return async function route(destination, { osrmOnly = false } = {}) {
    const point = validateDestination(destination);
    let fallbackReason = 'not-configured';
    if (!osrmOnly && env.GOOGLE_ROUTES_API_KEY) {
      let reserved = false;
      try { reserved = await quota.reserveGoogle(now()); fallbackReason = 'budget-limit'; }
      catch { fallbackReason = 'quota-unavailable'; }
      if (reserved) {
        try { return await googleRoute(point, env, fetcher); }
        catch (error) {
          fallbackReason = 'google-unavailable';
          // Log only fixed codes and format checks; never keys, request URLs or provider bodies.
          console.warn('Google routing unavailable', {
            reason: error instanceof RouteError ? error.code : 'request-failed',
            routesKeyFormatValid: /^AIza[\w-]{35}$/.test(env.GOOGLE_ROUTES_API_KEY),
            routesKeyMasked: /^[•●*]+$/.test(env.GOOGLE_ROUTES_API_KEY),
          });
        }
        // A failed/aborted call might still be billable. NEVER refund or retry it.
      }
    }
    let allowed = false;
    try { allowed = await quota.allowOsrm(); } catch { throw new RouteError('quota-unavailable'); }
    if (!allowed) throw new RouteError('busy', 429);
    try { return { ...await osrmRoute(point, env, fetcher), fallbackReason }; }
    catch (error) { throw error instanceof RouteError ? error : new RouteError('provider-unavailable'); }
  };
}
