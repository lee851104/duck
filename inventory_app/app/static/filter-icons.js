// Small, decorative icons shared by the sales and inventory filters.
const shapes={
  all:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  frozen:'<path d="M12 2v20M3.3 7l17.4 10M3.3 17 20.7 7M9 4l3 3 3-3M9 20l3-3 3 3M4 11l1-4 4-1M15 18l4-1 1-4M4 13l1 4 4 1M15 6l4 1 1 4"/>',
  meat:'<path d="M8 4c5-3 13 1 13 7 0 5-5 9-10 9-5 0-8-3-8-7 0-3 3-3 3-5 0-2 0-3 2-4Z"/><path d="M9 8c2-2 6-1 7 2s-1 5-4 5-5-2-4-4"/>',
  seafood:'<path d="M3 12c4-8 11-8 15-2l4-4v12l-4-4c-4 6-11 6-15-2Z"/><path d="M10 6c3 3 3 9 0 12M6.5 11h.01"/>',
  produce:'<path d="M5 20C5 11 10 4 21 3c0 11-6 17-13 17H5ZM3 22 15 10M9 16v-5M9 16h5"/>',
  grocery:'<path d="M6 3h12l-2 5 4 5v7H4v-7l4-5-2-5ZM8 8h8M9 14h6M9 17h6"/>',
  prepared:'<path d="M3 12h18c0 5-4 8-9 8s-9-3-9-8ZM6 22h12M8 3c-3 3 3 3 0 6M13 2c-3 3 3 3 0 6M18 3c-3 3 3 3 0 6"/>',
  drinks:'<path d="M5 7h14l-2 14H7L5 7ZM4 7h16M12 7l2-5h4M6 12h12"/>',
  other:'<path d="m3 7 9-4 9 4v10l-9 4-9-4V7Zm0 0 9 4 9-4M12 11v10M7 5l9 4"/>',
  restock:'<path d="M3 7h13v14H3V7Zm0 5h13M9 7v5M19 2v6M16 5h6"/>',
  uncounted:'<rect x="5" y="4" width="14" height="18" rx="2"/><rect x="9" y="2" width="6" height="4" rx="1"/><path d="M9 11h6M9 16h4"/>',
  expiring:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  unconfirmed:'<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.6 2.6L16 9.5"/>'
};

export function filterIcon(kind){
  return `<svg class="filter-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${shapes[kind]||shapes.other}</svg>`;
}

export function categoryIcon(category){
  if(!category)return filterIcon('all');
  const kind=[[/冷凍|冰品/,'frozen'],[/海鮮|水產|魚|蝦/,'seafood'],[/肉|禽/,'meat'],[/蔬|果/,'produce'],[/南北|雜貨/,'grocery'],[/調理|熟食/,'prepared'],[/飲|零食/,'drinks']].find(([pattern])=>pattern.test(category))?.[1];
  return filterIcon(kind);
}
