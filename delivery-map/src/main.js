import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './style.css';
import './workspace.css';
import { STORE, deliveryRule, distanceLabel, featureToCandidate, searchQueries, navigationUrl } from './rules.js';

const $ = id => document.getElementById(id);
const result = $('result');
const emptyResult = result.innerHTML;
const cache = new Map();
let generation = 0;
let abortSearch;
let lastRequest = 0;
let selected;
let pendingPoint;
let locationMarker;
let connector;
let accuracyCircle;
let suggestionTimer;
let composing = false;
let abortRoute;
let routeGeneration = 0;
const routePadding = { paddingTopLeft: [32, 100], paddingBottomRight: [32, 40], maxZoom: 16 };

const map = L.map('map', { scrollWheelZoom: true, zoomControl: false, doubleClickZoom: false, zoomSnap: 0.25, zoomDelta: 0.5 }).setView([STORE.lat, STORE.lng], 12);
L.control.zoom({ position: 'topright', zoomInTitle: '放大地圖', zoomOutTitle: '縮小地圖' }).addTo(map);
const streetTiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
});
const photoTiles = L.tileLayer('https://wmts.nlsc.gov.tw/wmts/PHOTO2/default/GoogleMapsCompatible/{z}/{y}/{x}', {
  maxZoom: 19,
  attribution: '<a href="https://maps.nlsc.gov.tw/S09SOA/" target="_blank" rel="noopener noreferrer">正射影像 © 內政部國土測繪中心</a>',
});
let activeTiles = streetTiles;
let tileTimer;
for (const layer of [streetTiles, photoTiles]) {
  let failed = false;
  layer.on('loading', () => {
    failed = false;
    if (layer !== activeTiles) return;
    clearTimeout(tileTimer);
    tileTimer = setTimeout(() => {
      if (layer === activeTiles) $('map-error').hidden = false;
    }, 12000);
  });
  layer.on('tileerror', () => {
    failed = true;
    if (layer === activeTiles) $('map-error').hidden = false;
  });
  layer.on('load', () => {
    if (layer !== activeTiles) return;
    clearTimeout(tileTimer);
    $('map-error').hidden = !failed;
  });
}
streetTiles.addTo(map);

document.querySelectorAll('[name="basemap"]').forEach(input => input.addEventListener('change', () => {
  if (!input.checked) return;
  const photo = input.value === 'photo';
  const next = photo ? photoTiles : streetTiles;
  if (activeTiles === next) return;
  clearTimeout(tileTimer);
  map.removeLayer(activeTiles);
  activeTiles = next;
  $('map-error').hidden = true;
  $('map-error').textContent = photo
    ? '部分正射影像無法載入，請切回街道圖或稍後再試。'
    : '底圖暫時無法載入，請檢查網路。距離計算仍可使用。';
  next.addTo(map);
  connector?.setStyle({ color: photo ? '#ffffff' : '#244f3d' });
}));
const shopIcon = L.divIcon({ className: 'shop-pin', html: '<img src="/favicon.svg" alt="" /><span>菜騎鴨</span>', iconSize: [48, 66], iconAnchor: [24, 36] });
L.marker([STORE.lat, STORE.lng], { icon: shopIcon, title: '菜騎鴨：外送起點', alt: '菜騎鴨店家位置' }).addTo(map);

function overview() { map.setView([STORE.lat, STORE.lng], 13, { animate: false }); }
overview();
new ResizeObserver(() => {
  map.invalidateSize();
  if (connector && selected && !$('map').hidden) {
    map.fitBounds(connector.getBounds().extend([STORE.lat, STORE.lng]).extend([selected.lat, selected.lng]), { ...routePadding, animate: false });
  } else if (!selected && !pendingPoint) overview();
}).observe($('map'));

function cancelPending() {
  generation++;
  clearTimeout(suggestionTimer);
  abortSearch?.abort();
  abortSearch = undefined;
  $('search-button').disabled = false;
  $('locate-button').disabled = false;
  $('locate-button').querySelector('span').textContent = '使用目前位置';
  $('suggestions-panel').hidden = true;
  $('address').setAttribute('aria-expanded', 'false');
  $('candidates').replaceChildren();
  $('search-status').textContent = '';
  pendingPoint = null;
  return generation;
}

function clearMarkers() {
  [locationMarker, connector, accuracyCircle].forEach(layer => { if (layer) map.removeLayer(layer); });
  locationMarker = connector = accuracyCircle = undefined;
}

function cancelRoute() {
  routeGeneration++;
  abortRoute?.abort();
  abortRoute = undefined;
  result.removeAttribute('aria-busy');
}

function showSelectionMap() {
  $('google-route').hidden = true;
  $('google-route-image').removeAttribute('src');
  $('map').hidden = false;
  document.querySelector('.basemap-switch').hidden = false;
  $('route-provider').textContent = '選擇收貨位置';
  map.invalidateSize();
}

function mark(point, { accuracy = 0, fit = true } = {}) {
  clearMarkers();
  locationMarker = L.marker([point.lat, point.lng], {
    icon: L.divIcon({ className: 'destination-pin', html: '<span></span>', iconSize: [26, 26], iconAnchor: [13, 13] }),
    title: '你選擇的位置', alt: '你選擇的位置',
  }).addTo(map);
  if (accuracy > 0) accuracyCircle = L.circle([point.lat, point.lng], { radius: accuracy, weight: 1, color: '#527998', fillOpacity: .08, interactive: false }).addTo(map);
  if (fit) {
    const bounds = L.latLngBounds([[STORE.lat, STORE.lng], [point.lat, point.lng]]);
    map.fitBounds(bounds, { padding: [18, 18], maxZoom: 15 });
  }
}

async function showResult(point, options = {}) {
  cancelPending();
  cancelRoute();
  showSelectionMap();
  selected = point;
  mark(point, options);
  document.querySelector('.map-hint').hidden = true;
  // GPS error cannot be added/subtracted from a road-route distance reliably.
  // Ask for an explicit pin confirmation instead of inventing an error margin.
  if (options.accuracy > 100) {
    result.dataset.state = 'confirm';
    result.innerHTML = `<div><h3>請確認收貨位置</h3><p class="confirm-note">定位誤差約 ${Math.ceil(options.accuracy)} 公尺，請點地圖修正，或確認目前圓點。</p></div><button id="confirm-location" class="confirm-button" type="button">位置正確，查路線</button>`;
    $('confirm-location').addEventListener('click', () => showResult(point));
    return;
  }
  const token = routeGeneration;
  const controller = new AbortController(); abortRoute = controller;
  const timeout = setTimeout(() => controller.abort(), 30000);
  result.dataset.state = 'loading'; result.setAttribute('aria-busy', 'true');
  result.innerHTML = '<div class="result-summary"><h3>正在查詢道路路線…</h3></div><p class="result-description">從菜騎鴨出發，計算汽車行駛距離。</p>';
  try {
    const response = await fetch('/api/route', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lat: point.lat, lng: point.lng, osrmOnly: options.osrmOnly === true }), signal: controller.signal });
    const route = await response.json();
    if (!response.ok) throw new Error(route.error || 'provider-unavailable');
    if (token !== routeGeneration) return;
    const rule = deliveryRule(route.meters);
    if (route.provider === 'google') {
      // Google content is shown only on its own map, never over Leaflet/OSM.
      if (typeof route.mapImage !== 'string' || !route.mapImage.startsWith('data:image/png;base64,')) throw new Error('provider-unavailable');
      $('google-route-image').src = route.mapImage;
      $('google-route').hidden = false;
      $('map').hidden = true;
      document.querySelector('.basemap-switch').hidden = true;
      $('map-error').hidden = true;
      $('route-provider').textContent = 'Google Maps · 汽車路線';
    } else if (route.provider === 'osrm') {
      if (!Array.isArray(route.coordinates) || route.coordinates.length < 2) throw new Error('provider-unavailable');
      connector = L.polyline(route.coordinates, { color: activeTiles === photoTiles ? '#ffffff' : '#244f3d',
        weight: 5, opacity: .9, interactive: false }).addTo(map);
      map.fitBounds(connector.getBounds().extend([STORE.lat, STORE.lng]).extend([point.lat, point.lng]), routePadding);
      $('route-provider').textContent = 'OpenStreetMap / OSRM · 汽車路線';
    } else throw new Error('provider-unavailable');
    const titles = { near: '可以外送', outer: '請先確認人手', outside: '無法配送' };
    const descriptions = { near: '5 公里內，外送低消 <strong>300 元</strong>。',
      outer: '超過 5 至 10 公里，請先向店家確認人手狀況。', outside: '超過 10 公里，因人手不足無法配送；歡迎來店自取。' };
    result.dataset.state = rule.zone;
    result.innerHTML = `<div class="result-summary"><h3>${titles[rule.zone]}</h3><span class="result-distance">道路 ${distanceLabel(route.meters)} 公里</span></div><p class="result-description">${descriptions[rule.zone]}</p><div class="route-detail"><span class="route-source"></span><a class="navigation-link" target="_blank" rel="noopener noreferrer">Google 導航 ↗</a></div>`;
    result.querySelector('.route-source').textContent = route.provider === 'google' ? 'Google Maps · 店家 → 收貨位置'
      : 'OpenStreetMap / OSRM 備援路線，可能與 Google 導航不同';
    result.querySelector('.navigation-link').href = navigationUrl(point);
    if (options.accuracy || route.snappedMeters > 30) {
      const note = document.createElement('p'); note.className = 'accuracy-note';
      note.textContent = '路線以附近可通行道路為終點，請確認收貨入口；巷弄與定位誤差可能影響結果。';
      result.append(note);
    }
  } catch (error) {
    if (token !== routeGeneration) return;
    showSelectionMap();
    result.dataset.state = 'uncertain';
    const messages = { busy: '查詢較頻繁，請稍候 2 秒再試。', 'invalid-destination': '此位置超出本站查詢區域，請用 Google 導航確認。',
      'no-route': '找不到可通行路線，請選擇附近的收貨入口。' };
    result.innerHTML = '<div class="result-summary"><h3>暫時無法判定</h3></div><p class="result-description"></p><div class="route-detail"><button id="retry-route" type="button">重新查詢</button><a class="navigation-link" target="_blank" rel="noopener noreferrer">開啟 Google 導航 ↗</a></div>';
    result.querySelector('.result-description').textContent = messages[error.message] || '道路查詢暫時無法使用，請用 Google 導航查看距離並向店家確認。';
    result.querySelector('.navigation-link').href = navigationUrl(point);
    $('retry-route').addEventListener('click', () => showResult(point, options));
  } finally {
    clearTimeout(timeout);
    if (token === routeGeneration) result.removeAttribute('aria-busy');
  }
}

$('adjust-location').addEventListener('click', () => {
  cancelRoute(); showSelectionMap();
  result.dataset.state = 'empty'; result.innerHTML = emptyResult;
  document.querySelector('.map-hint').hidden = false;
});
$('google-route-image').addEventListener('error', () => {
  if (selected && !$('google-route').hidden) showResult(selected, { osrmOnly: true });
});

map.on('click', event => showResult(event.latlng, { fit: false }));
$('map').addEventListener('keydown', event => {
  if (event.key === 'Enter' && event.target === $('map')) {
    event.preventDefault(); showResult(map.getCenter(), { fit: false });
  }
});
$('reset-map').addEventListener('click', () => {
  cancelPending(); cancelRoute(); showSelectionMap(); clearMarkers(); selected = null;
  $('address').value = '';
  result.dataset.state = 'empty'; result.innerHTML = emptyResult;
  document.querySelector('.map-hint').hidden = false;
  overview();
});

function chooseCandidate(candidate) {
  cancelPending();
  cancelRoute(); showSelectionMap();
  $('address').value = candidate.name;
  selected = null; pendingPoint = candidate;
  mark(candidate);
  map.setView([candidate.lat, candidate.lng], candidate.precise ? 17 : 16);
  document.querySelector('.map-hint').hidden = true;
  result.dataset.state = 'confirm';
  result.innerHTML = '<div class="confirmation-copy"><h3>確認收貨位置</h3><p class="candidate-name"></p><p class="confirm-note">請確認地圖圓點；不準確可直接點地圖修正。</p></div><button id="confirm-location" class="confirm-button" type="button">位置正確，查詢</button>';
  result.querySelector('.candidate-name').textContent = candidate.name + (candidate.address ? ' · ' + candidate.address : '');
  $('confirm-location').addEventListener('click', () => showResult(candidate, { label: candidate.name + (candidate.address ? ` · ${candidate.address}` : '') }));
}

async function searchProvider(query, signal) {
  if (cache.has(query)) return cache.get(query);
  const delay = Math.max(0, 1200 - (Date.now() - lastRequest));
  if (delay) await new Promise(resolve => setTimeout(resolve, delay));
  signal.throwIfAborted(); lastRequest = Date.now();
  const params = new URLSearchParams({ q: query, lat: String(STORE.lat), lon: String(STORE.lng), limit: '6', bbox: '119.3,21.8,122.1,25.5' });
  const response = await fetch(`https://photon.komoot.io/api/?${params}`, { signal });
  if (!response.ok) throw new Error(response.status === 429 ? 'busy' : 'network');
  const data = await response.json();
  if (!Array.isArray(data.features)) throw new Error('network');
  const seen = new Set();
  const candidates = data.features.map(featureToCandidate).filter(candidate => {
    if (!candidate) return false;
    const key = `${candidate.name}|${candidate.address}|${candidate.lat.toFixed(4)}|${candidate.lng.toFixed(4)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  if (cache.size >= 30) cache.delete(cache.keys().next().value);
  cache.set(query, candidates);
  return candidates;
}

function queueSuggestions() {
  cancelPending();
  cancelRoute(); showSelectionMap();
  if (result.dataset.state !== 'empty') {
    result.dataset.state = 'empty'; result.innerHTML = emptyResult;
    selected = null;
    clearMarkers();
    document.querySelector('.map-hint').hidden = false;
  }
  if (!composing && $('address').value.trim().length >= 2) {
    suggestionTimer = setTimeout(() => runSearch({ automatic: true }), 700);
  }
}
$('address').addEventListener('input', queueSuggestions);
$('address').addEventListener('compositionstart', () => { composing = true; cancelPending(); });
$('address').addEventListener('compositionend', () => { composing = false; queueSuggestions(); });
$('search-form').addEventListener('submit', event => {
  event.preventDefault();
  if (!composing) runSearch();
});
async function runSearch({ automatic = false } = {}) {
  const query = $('address').value.trim();
  if (query.length < 2) { $('search-status').textContent = '請輸入至少兩個字，例如道路名稱或附近地標。'; return; }
  const token = cancelPending();
  const controller = new AbortController(); abortSearch = controller;
  const timeout = setTimeout(() => controller.abort('timeout'), 18000);
  $('search-button').disabled = true;
  $('search-status').textContent = '正在尋找位置…';
  try {
    const queries = searchQueries(query);
    let candidates = await searchProvider(queries[0], controller.signal);
    let approximate = false;
    if (!candidates.length && queries[1] && !automatic) {
      if (token !== generation) return;
      $('search-status').textContent = '沒有找到完整門牌，正在尋找同一道路；稍後請在地圖確認位置。';
      candidates = await searchProvider(queries[1], controller.signal);
      approximate = true;
    }
    if (token !== generation) return;
    if (!candidates.length) {
      $('search-status').textContent = '找不到這個地址。請改用道路名稱（例如「中社路」）、附近地標，或直接在地圖選點。';
      return;
    }
    $('search-status').textContent = approximate ? '僅找到附近道路，並非完整門牌。請在地圖確認位置。' : `找到 ${candidates.length} 個相近位置，請從建議清單選擇。`;
    const list = $('candidates');
    $('suggestions-panel').hidden = false;
    $('address').setAttribute('aria-expanded', 'true');
    for (const candidate of candidates) {
      const li = document.createElement('li'); const button = document.createElement('button'); button.type = 'button';
      const name = document.createElement('strong'); name.textContent = candidate.name;
      const address = document.createElement('span'); address.textContent = candidate.address;
      const distance = document.createElement('small'); distance.textContent = '確認收貨入口後，查詢道路距離';
      button.append(name, address, distance); button.addEventListener('click', () => {
        chooseCandidate(candidate);
        $('confirm-location').focus({ preventScroll: true });
      }); li.append(button); list.append(li);
    }
  } catch (error) {
    if (token !== generation) return;
    $('search-status').textContent = error.message === 'busy' ? '地址查詢目前較忙，請稍後再試，或直接在地圖選點。' : '地址查詢暫時無法連線。你仍可使用定位，或直接在地圖選點。';
  } finally {
    clearTimeout(timeout);
    if (token === generation) $('search-button').disabled = false;
  }
}

$('dismiss-suggestions').addEventListener('click', () => { cancelPending(); $('address').focus(); });
$('address').addEventListener('keydown', event => {
  if (event.isComposing || composing) return;
  if (event.key === 'ArrowDown' && !$('suggestions-panel').hidden) {
    event.preventDefault(); $('candidates').querySelector('button')?.focus();
  }
  if (event.key === 'Escape') cancelPending();
});
$('candidates').addEventListener('keydown', event => {
  const buttons = [...$('candidates').querySelectorAll('button')];
  const index = buttons.indexOf(document.activeElement);
  if (event.key === 'ArrowDown') { event.preventDefault(); buttons[Math.min(index + 1, buttons.length - 1)]?.focus(); }
  if (event.key === 'ArrowUp') { event.preventDefault(); (index <= 0 ? $('address') : buttons[index - 1]).focus(); }
  if (event.key === 'Escape') { cancelPending(); $('address').focus(); }
});
document.addEventListener('pointerdown', event => {
  if (!event.target.closest('#search-form') && !$('suggestions-panel').hidden) cancelPending();
});

const rulesDialog = $('rules-dialog');
document.querySelectorAll('[data-open-rules]').forEach(button => button.addEventListener('click', () => {
  cancelPending(); rulesDialog.showModal();
}));
$('close-rules').addEventListener('click', () => rulesDialog.close());
rulesDialog.addEventListener('click', event => {
  if (event.target === rulesDialog) {
    const rect = rulesDialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) rulesDialog.close();
  }
});

$('locate-button').addEventListener('click', () => {
  const token = cancelPending();
  cancelRoute(); showSelectionMap(); clearMarkers();
  result.dataset.state = 'empty'; result.innerHTML = emptyResult;
  if (!navigator.geolocation) { $('search-status').textContent = '此瀏覽器不支援定位，請輸入地址或在地圖選點。'; return; }
  $('locate-button').disabled = true;
  $('locate-button').querySelector('span').textContent = '正在取得位置…';
  $('search-status').textContent = '請允許瀏覽器使用位置；座標會傳送至路線服務以計算道路距離。';
  navigator.geolocation.getCurrentPosition(position => {
    if (token !== generation) return;
    $('address').value = '';
    showResult({ lat: position.coords.latitude, lng: position.coords.longitude }, { accuracy: position.coords.accuracy, label: '目前定位位置' });
  }, error => {
    if (token !== generation) return;
    cancelPending();
    $('search-status').textContent = error.code === 1 ? '未取得定位權限。你可以輸入地址，或直接在地圖選點。' : error.code === 3 ? '定位等候逾時，請重試，或直接在地圖選點。' : '目前無法取得位置。請開啟裝置定位，或輸入地址查詢。';
  }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 });
});
