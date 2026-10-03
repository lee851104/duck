import { STORE } from './rules.js';

// One instance and one reservation per page. No storage or billing credential
// persistence. A failed initialization stays failed until the page is reloaded.
export function createGoogleMapView(element, onPick, onFailure) {
  let pending;
  let map;
  let line;
  let failed = false;
  let rejectReady;
  let ready = false;

  function fail() {
    failed = true;
    rejectReady?.(new Error('google-map-unavailable'));
    if (ready) onFailure();
  }

  async function initialize() {
    const response = await fetch('/api/map-session', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      signal: AbortSignal.timeout(5000),
    });
    const config = await response.json();
    if (!response.ok) throw new Error(config.error || 'google-map-unavailable');
    if (typeof config.browserKey !== 'string') throw new Error('google-map-unavailable');

    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => { failed = true; reject(new Error('google-map-unavailable')); }, 12000);
      const stop = error => { clearTimeout(timer); reject(error); };
      rejectReady = stop;
      window.gm_authFailure = fail;
      window.duckMapsReady = () => { clearTimeout(timer); resolve(); };
      const script = document.createElement('script');
      const params = new URLSearchParams({ key: config.browserKey, v: 'quarterly', loading: 'async',
        callback: 'duckMapsReady', libraries: 'geometry', language: 'zh-TW', region: 'TW' });
      script.src = `https://maps.googleapis.com/maps/api/js?${params}`;
      script.async = true;
      script.onerror = () => { failed = true; stop(new Error('google-map-unavailable')); };
      document.head.append(script);
    });
    if (failed) throw new Error('google-map-unavailable');
    const maps = window.google.maps;
    map = new maps.Map(element, {
      center: { lat: STORE.lat, lng: STORE.lng }, zoom: 13,
      renderingType: maps.RenderingType.RASTER,
      gestureHandling: 'greedy', zoomControl: true, fullscreenControl: true,
      streetViewControl: false, mapTypeControl: false, clickableIcons: false,
    });
    // Keep the shop independent of the route: clearing or replacing a route
    // must never remove its origin marker. OverlayView needs no extra Map ID.
    class StoreMarker extends maps.OverlayView {
      onAdd() {
        this.element = document.createElement('div');
        this.element.className = 'shop-pin google-shop-pin';
        this.element.setAttribute('role', 'img');
        this.element.setAttribute('aria-label', '菜騎鴨店家位置：外送起點');
        this.element.innerHTML = '<img src="/favicon.svg" alt="" /><span>菜騎鴨</span>';
        this.getPanes().overlayLayer.append(this.element);
      }
      draw() {
        const point = this.getProjection().fromLatLngToDivPixel(new maps.LatLng(STORE.lat, STORE.lng));
        if (!point) return;
        this.element.style.left = `${point.x}px`;
        this.element.style.top = `${point.y}px`;
      }
      onRemove() { this.element.remove(); }
    }
    new StoreMarker().setMap(map);
    map.addListener('click', event => { if (event.latLng && !failed) onPick(event.latLng.toJSON()); });
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => { failed = true; reject(new Error('google-map-unavailable')); }, 12000);
      rejectReady = error => { clearTimeout(timer); reject(error); };
      maps.event.addListenerOnce(map, 'tilesloaded', () => { clearTimeout(timer); resolve(); });
    });
    if (failed) throw new Error('google-map-unavailable');
    ready = true;
    rejectReady = undefined;
  }

  return {
    async ensure() {
      if (failed) throw new Error('google-map-unavailable');
      if (!pending) pending = initialize().catch(error => { failed = true; throw error; });
      return pending;
    },
    draw(encodedPolyline) {
      if (failed || !ready || typeof encodedPolyline !== 'string') throw new Error('google-map-unavailable');
      const maps = window.google.maps;
      const path = maps.geometry.encoding.decodePath(encodedPolyline);
      if (path.length < 2 || path.some(p => !Number.isFinite(p.lat()) || !Number.isFinite(p.lng()))) throw new Error('google-map-unavailable');
      line?.setMap(null);
      line = new maps.Polyline({ map, path, strokeColor: '#244f3d', strokeWeight: 5,
        icons: [
          { icon: { path: maps.SymbolPath.CIRCLE, scale: 8, fillColor: '#244f3d', fillOpacity: 1, strokeColor: '#fff', strokeWeight: 3 }, offset: '0%' },
          { icon: { path: maps.SymbolPath.CIRCLE, scale: 8, fillColor: '#b76e35', fillOpacity: 1, strokeColor: '#fff', strokeWeight: 3 }, offset: '100%' },
        ] });
      const bounds = new maps.LatLngBounds();
      path.forEach(p => bounds.extend(p));
      bounds.extend({ lat: STORE.lat, lng: STORE.lng });
      maps.event.trigger(map, 'resize');
      map.fitBounds(bounds, 50);
    },
    clear() { line?.setMap(null); line = undefined; },
  };
}
