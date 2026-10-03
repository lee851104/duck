import test from 'node:test';
import assert from 'node:assert/strict';
import { createGoogleMapView } from '../src/google-map.js';

test('concurrent initialization and provider switching reuse a single billed map instance', async t => {
  const events = { reservations: 0, scripts: 0, maps: 0, routes: 0 };
  const markers = [];
  let projectedPosition;
  const fakeWindow = { google: { maps: {
    Map: class { constructor() { events.maps++; } addListener() {} fitBounds() {} },
    Polyline: class { constructor() { events.routes++; } setMap() {} },
    LatLngBounds: class { extend() {} }, RenderingType: { RASTER: 'RASTER' }, SymbolPath: { CIRCLE: 0 },
    LatLng: class { constructor(lat, lng) { this.lat = lat; this.lng = lng; } },
    OverlayView: class {
      setMap(map) { if (map) { this.onAdd(); this.draw(); } else this.onRemove(); }
      getPanes() { return { overlayLayer: { append: node => markers.push(node) } }; }
      getProjection() { return { fromLatLngToDivPixel: point => { projectedPosition = point; return { x: 100, y: 200 }; } }; }
    },
    geometry: { encoding: { decodePath: () => [{ lat: () => 24, lng: () => 120 }, { lat: () => 24.1, lng: () => 120.1 }] } },
    event: { addListenerOnce: (_, __, fn) => queueMicrotask(fn), trigger() {} },
  } } };
  t.mock.method(globalThis, 'fetch', async () => { events.reservations++; return new Response(JSON.stringify({ browserKey: 'fake' })); });
  const previous = { window: globalThis.window, document: globalThis.document };
  globalThis.window = fakeWindow;
  globalThis.document = { createElement: () => ({ style: {}, setAttribute() {}, remove() { markers.splice(markers.indexOf(this), 1); } }), head: { append() { events.scripts++; queueMicrotask(() => fakeWindow.duckMapsReady()); } } };
  t.after(() => { globalThis.window = previous.window; globalThis.document = previous.document; });
  const view = createGoogleMapView({}, () => {}, () => {});
  await Promise.all([view.ensure(), view.ensure()]);
  assert.equal(markers.length, 1, 'store marker is visible before a route exists');
  assert.equal(projectedPosition.lat, 24.2739442);
  assert.equal(projectedPosition.lng, 120.5453111);
  const storeMarker = markers[0];
  assert.equal(storeMarker.style.left, '100px');
  assert.equal(storeMarker.style.top, '200px');
  view.draw('route'); view.clear(); await view.ensure(); view.draw('route');
  assert.deepEqual(markers, [storeMarker], 'clearing routes and switching providers preserves one store marker');
  assert.deepEqual(events, { reservations: 1, scripts: 1, maps: 1, routes: 2 });
});

test('map budget failure never loads Google SDK and cannot retry on the same page', async t => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; return new Response(JSON.stringify({ error: 'map-budget-limit' }), { status: 429 }); });
  const view = createGoogleMapView({}, () => {}, () => {});
  await assert.rejects(view.ensure(), { message: 'map-budget-limit' });
  await assert.rejects(view.ensure(), { message: 'google-map-unavailable' });
  assert.equal(calls, 1);
});

test('Google auth failure before map construction consumes no second reservation', async t => {
  let calls = 0;
  const previous = { window: globalThis.window, document: globalThis.document };
  globalThis.window = {};
  globalThis.document = { createElement: () => ({}), head: { append() { queueMicrotask(() => window.gm_authFailure()); } } };
  t.after(() => { globalThis.window = previous.window; globalThis.document = previous.document; });
  t.mock.method(globalThis, 'fetch', async () => { calls++; return new Response(JSON.stringify({ browserKey: 'fake' })); });
  const view = createGoogleMapView({}, () => {}, () => {});
  await assert.rejects(view.ensure(), { message: 'google-map-unavailable' });
  await assert.rejects(view.ensure());
  assert.equal(calls, 1);
});
