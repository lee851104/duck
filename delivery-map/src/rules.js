export const STORE = Object.freeze({
  name: '菜騎鴨',
  address: '臺中市清水區中社路 102-21 號',
  lat: 24.2739442,
  lng: 120.5453111,
  mapsUrl: 'https://maps.app.goo.gl/ThLryBDRxGa6YcFg6',
});

export function validPoint(point) {
  return point && Number.isFinite(point.lat) && Number.isFinite(point.lng)
    && Math.abs(point.lat) <= 90 && Math.abs(point.lng) <= 180;
}

// Same spherical Earth radius as Leaflet's circle/distance calculation.
export function distanceMeters(a, b) {
  if (!validPoint(a) || !validPoint(b)) throw new TypeError('Invalid coordinates');
  const radians = value => value * Math.PI / 180;
  const dLat = radians(b.lat - a.lat);
  const dLng = radians(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2
    + Math.cos(radians(a.lat)) * Math.cos(radians(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 6371000 * 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, h))));
}

export function deliveryRule(meters) {
  if (!Number.isFinite(meters) || meters < 0) throw new TypeError('Invalid distance');
  if (meters <= 3000) return { zone: 'near', minimum: 100, fee: 20, eligible: true };
  if (meters <= 5000) return { zone: 'outer', minimum: 300, fee: 20, eligible: true };
  return { zone: 'outside', minimum: null, fee: null, eligible: false };
}

export function crossesBoundary(meters, accuracy = 0) {
  if (!Number.isFinite(accuracy) || accuracy < 0) return true;
  return [3000, 5000].some(boundary => meters - accuracy <= boundary && meters + accuracy > boundary);
}

export function distanceLabel(meters) {
  // Round upward: a point just outside 3 or 5 km must not display as exactly on it.
  return (Math.ceil((meters - 1e-8) / 10) / 100).toFixed(2);
}

export function searchQueries(raw) {
  const query = raw.trim().replace(/^台中/, '臺中');
  // Photon tokenizes Chinese addresses more reliably with administrative separators.
  const normalized = query.replace(/([縣市區鄉鎮里村路街段巷弄])/g, '$1 ').replace(/\s+/g, ' ').trim();
  const streetOnly = normalized.replace(/\s*\d[\d\s之\-]*號.*$/, '').trim();
  return [...new Set([normalized, streetOnly].filter(Boolean))];
}

export function demoPoint(km) {
  return { lat: STORE.lat + km / 6371 * 180 / Math.PI, lng: STORE.lng };
}

export function featureToCandidate(feature) {
  const coordinates = feature?.geometry?.coordinates;
  const p = feature?.properties;
  if (!p || !Array.isArray(coordinates) || p.countrycode?.toUpperCase() !== 'TW') return null;
  const point = { lat: coordinates[1], lng: coordinates[0] };
  if (!validPoint(point)) return null;
  const address = [...new Set([p.city, p.district, p.locality, p.street, p.housenumber].filter(Boolean))].join(' ');
  return { ...point, name: p.name || p.street || address || '搜尋位置', address,
    precise: Boolean(p.housenumber), key: `${p.osm_type}-${p.osm_id}` };
}
