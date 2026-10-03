import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './style.css';
import './workspace.css';
import { STORE, distanceMeters, deliveryRule, crossesBoundary, distanceLabel, featureToCandidate, searchQueries } from './rules.js';

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

const outer = L.circle([STORE.lat, STORE.lng], { radius: 5000, color: '#b38a39', weight: 2, dashArray: '6 7', fillColor: '#e7c77e', fillOpacity: .12 }).addTo(map);
const inner = L.circle([STORE.lat, STORE.lng], { radius: 3000, color: '#416d52', weight: 2, fillColor: '#678d63', fillOpacity: .18 }).addTo(map);
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
  inner.setStyle({ color: photo ? '#bce595' : '#416d52', fillOpacity: photo ? .06 : .18 });
  outer.setStyle({ color: photo ? '#ffcf68' : '#b38a39', fillOpacity: photo ? .04 : .12 });
  connector?.setStyle({ color: photo ? '#ffffff' : '#244f3d' });
}));
const shopIcon = L.divIcon({ className: 'shop-pin', html: '<img src="/favicon.svg" alt="" /><span>菜騎鴨</span>', iconSize: [48, 66], iconAnchor: [24, 36] });
L.marker([STORE.lat, STORE.lng], { icon: shopIcon, title: '菜騎鴨：外送起點', alt: '菜騎鴨店家位置' }).addTo(map);

function overview() { map.fitBounds(outer.getBounds(), { padding: [14, 14], animate: false }); }
overview();
new ResizeObserver(() => { map.invalidateSize(); if (!selected && !pendingPoint) overview(); }).observe($('map'));

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

function mark(point, { accuracy = 0, fit = true } = {}) {
  clearMarkers();
  locationMarker = L.marker([point.lat, point.lng], {
    icon: L.divIcon({ className: 'destination-pin', html: '<span></span>', iconSize: [26, 26], iconAnchor: [13, 13] }),
    title: '你選擇的位置', alt: '你選擇的位置',
  }).addTo(map);
  connector = L.polyline([[STORE.lat, STORE.lng], [point.lat, point.lng]], { color: activeTiles === photoTiles ? '#ffffff' : '#244f3d', weight: 2, dashArray: '4 6', interactive: false }).addTo(map);
  if (accuracy > 0) accuracyCircle = L.circle([point.lat, point.lng], { radius: accuracy, weight: 1, color: '#527998', fillOpacity: .08, interactive: false }).addTo(map);
  if (fit) {
    const bounds = outer.getBounds().extend([point.lat, point.lng]);
    map.fitBounds(bounds, { padding: [18, 18], maxZoom: 15 });
  }
}

function showResult(point, options = {}) {
  cancelPending();
  selected = point;
  const meters = distanceMeters(STORE, point);
  const rule = deliveryRule(meters);
  const uncertain = crossesBoundary(meters, options.accuracy || 0);
  const state = uncertain ? 'uncertain' : rule.zone;
  mark(point, options);
  result.dataset.state = state;
  const titles = { near: '可以外送', outer: '可以外送', outside: '超出外送範圍', uncertain: '請確認位置' };
  const body = uncertain
    ? '定位誤差跨過範圍界線，請點地圖選擇實際位置。'
    : rule.eligible ? `滿 <strong>${rule.minimum} 元</strong>免運，未滿加收 20 元／趟`
      : '超過 5 公里，歡迎來店自取。';
  result.innerHTML = `<div class="result-summary"><h3>${titles[state]}</h3><span class="result-distance">${distanceLabel(meters)} 公里</span></div><p class="result-description">${body}</p>${rule.eligible && !uncertain ? '<p class="result-detail">團購不計低消 · 訂購時間請見外送須知</p>' : ''}${options.accuracy ? '<p class="accuracy-note"></p>' : ''}`;
  if (options.accuracy) result.querySelector('.accuracy-note').textContent = `定位精度約 ±${Math.ceil(options.accuracy)} 公尺`;
  document.querySelector('.map-hint').hidden = true;
}

map.on('click', event => showResult(event.latlng, { fit: false }));
$('map').addEventListener('keydown', event => {
  if (event.key === 'Enter' && event.target === $('map')) {
    event.preventDefault(); showResult(map.getCenter(), { fit: false });
  }
});
$('reset-map').addEventListener('click', () => {
  cancelPending(); clearMarkers(); selected = null;
  $('address').value = '';
  result.dataset.state = 'empty'; result.innerHTML = emptyResult;
  document.querySelector('.map-hint').hidden = false;
  overview();
});

function chooseCandidate(candidate) {
  cancelPending();
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
      const distance = document.createElement('small'); distance.textContent = `距店家約 ${distanceLabel(distanceMeters(STORE, candidate))} 公里 · 請確認實際位置`;
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
  if (!navigator.geolocation) { $('search-status').textContent = '此瀏覽器不支援定位，請輸入地址或在地圖選點。'; return; }
  $('locate-button').disabled = true;
  $('locate-button').querySelector('span').textContent = '正在取得位置…';
  $('search-status').textContent = '請允許瀏覽器使用位置；不會將定位座標送往地址搜尋服務。';
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
