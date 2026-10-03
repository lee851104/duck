import {renderDailySales,hasSalesDraft} from './views/daily-sales.js';
import {renderMerchant,renderExports,hasStocktakeDrafts,clearStocktakeDrafts} from './views/merchant.js';
import {productPhoto} from './product-photo.js';
import {operation, productPanel, newProduct} from './views/operations.js';
import {dataManager, importPreview, mappings} from './views/data.js';

export const S={view:location.hash==='#inventory'?'inventory':'daily-sales',inventoryMode:'table',savingCounts:false,page:1,q:'',status:'',category:'',photos:'',catalogSize:24,kind:'',from:'',to:'',productId:'',meta:null,csrf:'',dialogDirty:false,pageSizes:{}};
export const $=s=>document.querySelector(s);
export const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const names={out:'缺貨',low:'低庫存',expiring:'即期',expired:'已過期',uncounted:'未盤點',normal:'正常',unmapped:'待對應',independent:'獨立品項'};
export const kinds={opening:'期初匯入',receive:'進貨',issue:'出貨',count:'盤點',price:'改價',edit:'商品修改',create:'新增商品',reverse:'沖銷',return:'顧客退回',mapping:'商品對應'};
export const badge=status=>`<span class="badge ${esc(status)}">${names[status]||esc(status)}</span>`;
export const money=v=>v===null||v===undefined?'未設定': /^\d+(\.\d+)?$/.test(String(v))?'$'+Number(v).toLocaleString('zh-TW',{maximumFractionDigits:2}):esc(v);
export const image=p=>productPhoto(p.image,p.name,'product-image','/media/');
export const qty=p=>p.quantity===null?'未盤點':`${esc(p.quantity)}<small>${esc(p.unit)}</small>`;

export async function api(path,body,method='POST'){
  const options={headers:{'X-CSRF-Token':S.csrf}};
  if(body!==undefined){options.method=method;options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}
  const response=await fetch('/api'+path,options);
  const data=await response.json();
  if(response.status===401&&path!=='/login'&&path!=='/session'){
    const state=await api('/session');S.csrf=state.csrf;
    if(!state.authenticated)showAuth({...state,login_error:'登入已過期或帳號權限已變更，請重新登入。'});
  }
  if(!response.ok){const e=new Error(data.error?.message||'讀取失敗，請重試');e.fields=data.error?.fields;e.status=response.status;throw e;}
  return data;
}

let toastTimer;
export function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,3500);}
export function dialog(title,html,eyebrow='商品管理'){
  if(S.authenticated===false)return;
  S.dialogDirty=false;$('#dialog-title').textContent=title;$('#dialog-eyebrow').textContent=eyebrow;$('#dialog-body').innerHTML=html;
  if(!$('#dialog').open)$('#dialog').showModal();
  $('#dialog-body').scrollTop=0;
}
export function closeDialog(force=false){if(S.savingSales&&!force)return;if(!force&&S.dialogDirty&&!confirm('尚未儲存，確定離開？'))return;S.dialogDirty=false;$('#dialog').close();}
export function formSubmit(form,callback){
  let busy=false;
  form.addEventListener('submit',async event=>{event.preventDefault();if(busy)return;busy=true;
    const button=form.querySelector('[type=submit]');if(button)button.disabled=true;
    const error=form.querySelector('.error');if(error)error.textContent='';
    try{await callback(new FormData(form));}catch(e){if(error)error.textContent=e.message;else toast(e.message);}
    finally{busy=false;if(button)button.disabled=false;}
  });
}
export function pager(p,action='page'){
  const pages=Math.max(1,Math.ceil(p.total/p.page_size));
  return `<div class="pager"><span>共 ${p.total} 筆</span><div class="pager-controls"><button data-action="${action}" data-page="${p.page-1}" ${p.page<=1?'disabled':''} aria-label="上一頁">‹</button><span>${p.page} / ${pages}</span><button data-action="${action}" data-page="${p.page+1}" ${p.page>=pages?'disabled':''} aria-label="下一頁">›</button></div></div>`;
}
export const empty=(title,text,action='')=>`<div class="empty"><span class="empty-symbol">▧</span><h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;
export function size(view){
  if(view==='dashboard')return 6;
  if(view==='catalog')return S.catalogSize;
  return 10;
}

export async function refreshMeta(){S.meta=await api('/meta');$('#today').textContent=S.meta.today.replaceAll('-',' / ');$('#demo-label').hidden=!S.meta.demo;$('#save-status').textContent=S.meta.backup?.error?'備份未完成，請至資料管理查看':(S.meta.cloud_mode?'資料儲存在雲端':'資料保存在這台電腦');}
export async function navigate(view,filters={}){Object.assign(S,{view,page:1,q:'',status:'',category:'',photos:'',kind:'',from:'',to:'',productId:''},filters);await render();$('#main').scrollTop=0;}
export async function refresh(){await refreshMeta();await render();}
const heading=(title,subtitle,buttons='')=>`<div class="page-heading"><div><p class="eyebrow">菜騎鴨 · 店務管理</p><h1>${title}</h1><p class="muted">${subtitle}</p></div><div class="button-row">${buttons}</div></div>`;

async function dashboard(seq){
  const d=await api(`/dashboard?page=${S.page}&page_size=${size('dashboard')}`);
  if(seq!==generation)return;
  const stat=(label,count,unit,status,color,icon)=>`<button class="stat ${color}" data-action="filter-dashboard" data-status="${status}"><span class="stat-label">${label}</span><span class="stat-icon" aria-hidden="true">${icon}</span><span class="stat-num">${count}</span><span class="stat-unit">${unit}</span></button>`;
  const alerts=d.alerts.items.map(a=>`<div class="alert-row">${badge(a.status)}<div class="item-main"><span class="item-name">${esc(a.name)}</span><p class="item-sub">${esc(a.detail)} · ${a.quantity===null?'數量待確認':esc(a.quantity)+' '+esc(a.unit)}</p></div><button class="row-action" data-action="product" data-id="${a.product_id}">查看 ›</button></div>`).join('');
  const action=(type,label,copy,icon)=>`<button class="quick-action action-${type}" data-action="choose-operation" data-type="${type}"><span class="quick-icon" aria-hidden="true">${icon}</span><span><strong>${label}</strong><small>${copy}</small></span></button>`;
  $('#main').innerHTML=heading('庫存總覽','先看看今天有哪些商品需要留意。','<button data-action="data">資料管理</button>')+
    `<div class="stats">${stat('缺貨商品',d.out_of_stock_products,'項','out','red','−')}${stat('低庫存商品',d.low_stock_products,'項','low','amber','↘')}${stat('即期批次',d.expiring_batches,'批','expiring','amber','◷')}${stat('未盤點商品',d.uncounted_products,'項','uncounted','','▤')}</div>
    <div class="dashboard-body"><section class="panel"><div class="panel-head"><h3>需要處理</h3><small>${d.expired_batches?`${d.expired_batches} 批已過期`:`共 ${d.total_products} 項商品`}</small></div><div class="list-space">${alerts||empty(d.total_products?'目前沒有待處理提醒':'先帶入店裡的商品',d.total_products?'未盤點商品可從上方摘要查看。':'從原始 Excel 預覽資料，再確認匯入。',d.total_products?'':'<button class="primary" data-action="import">匯入原始資料</button>')}</div>${pager(d.alerts)}</section>
    <aside class="panel quick"><h3>日常操作</h3><p>找到商品，幾步完成登記。</p>${action('receive','登記進貨','補貨到店，新增批次','＋')}${action('issue','登記出貨','銷售、報廢或退貨','↗')}${action('count','盤點庫存','確認現場實際數量','✓')}<div class="quick-note">每次庫存變動都會留下紀錄。<br>${d.updated_at?'最後異動 '+esc(d.updated_at.slice(5,16).replace('T',' ')):'尚無庫存異動'}</div></aside></div>`;
}

export function categoryButtons(categories,selected,action='category-filter'){
  const choices=['',...new Set(categories.filter(Boolean))];
  return `<div class="category-filter"><div class="category-filter-heading"><strong>分類</strong><small>亮起表示已選取，再點取消</small></div><div class="category-buttons" role="group" aria-label="商品分類">${choices.map(c=>`<button type="button" data-action="${action}" data-category="${esc(c)}" aria-pressed="${selected===c}"><span class="category-check" aria-hidden="true">✓</span>${esc(c?c.replace(/^[A-Z]/,''):'全部分類')}</button>`).join('')}</div></div>`;
}

function searchToolbar(includeStatus=true){
  return `<div class="toolbar"><div class="search-box"><input id="search" aria-label="搜尋商品" placeholder="搜尋商品名稱或品號" value="${esc(S.q)}"></div>${categoryButtons(S.view==='catalog'?S.meta.catalog_categories:S.meta.categories,S.category)}${includeStatus?`<div class="filters">${[['','全部'],['restock','待補貨'],['expiring','即期'],['uncounted','未盤點']].map(([value,label])=>`<button data-action="filter" data-status="${value}" class="${S.status===value?'selected':''}">${label}</button>`).join('')}</div>`:''}</div>`;
}

async function dailySales(seq){await renderDailySales(seq,()=>seq===generation);}

async function inventory(seq){await renderMerchant(()=>seq===generation);}

let catalogItems=new Map();
async function catalog(seq){
  const p=await api('/catalog?'+new URLSearchParams({q:S.q,category:S.category,photos:S.photos,page:S.page,page_size:size('catalog')}));
  if(seq!==generation)return;
  S.page=p.page;
  catalogItems=new Map(p.items.map(c=>[String(c.id),c]));
  const count=p.photo_counts;
  $('#main').innerHTML=heading('商品價目表','瀏覽所有價目項目；點照片可放大，向下捲動或換頁繼續查看。','<button class="primary" data-action="print">列印價目表</button>')+searchToolbar(false)+
    `<div class="catalog-controls"><div class="photo-filters" role="group" aria-label="商品照片篩選">${[['','全部項目',count.all],['present','有照片',count.present],['missing','尚無照片',count.missing]].map(([value,label,n])=>`<button data-action="photo-filter" data-photos="${value}" aria-pressed="${S.photos===value}">${label}<span>${n}</span></button>`).join('')}</div><label class="page-size-label">每頁<select id="catalog-page-size" aria-label="每頁價目項目數">${[12,24,48].map(n=>`<option value="${n}" ${n===S.catalogSize?'selected':''}>${n} 項</option>`).join('')}</select></label></div>
    <section class="panel catalog-panel"><div class="catalog-grid">${p.items.map(c=>`<article class="catalog-card"><button class="catalog-photo" data-action="catalog-detail" data-id="${esc(c.id)}" aria-label="${c.image?'放大照片':'查看商品'}：${esc(c.name)}">${productPhoto(c.image,c.name,'catalog-card-image','/media/')}${c.image?'<span class="photo-zoom">放大照片</span>':''}</button><div class="catalog-info"><p class="catalog-brand">${esc(c.brand||c.category)}</p><h3>${esc(c.name)}</h3><p class="catalog-spec">${esc(c.specification||c.unit||'規格待確認')}</p><div class="catalog-price-row"><p class="price">${money(c.price)}</p>${badge(c.status)}</div></div><button class="catalog-detail-button" data-action="catalog-detail" data-id="${esc(c.id)}">查看詳情 <span aria-hidden="true">↗</span></button></article>`).join('')||empty('沒有符合的價目項目','試試其他分類、照片篩選或關鍵字。')}</div>${pager(p)}</section>`;
  bindSearch();
  $('#catalog-page-size').onchange=async e=>{S.catalogSize=Number(e.target.value);S.page=1;await render();$('#main').scrollTop=0;};
}

function catalogDetail(id){
  const c=catalogItems.get(String(id));if(!c)return;
  dialog(c.name,`${productPhoto(c.image,c.name,'catalog-preview-image','/media/')}<div class="catalog-preview-meta"><p class="muted">${esc(c.brand||c.category)}</p><p>${esc(c.specification||c.unit||'規格待確認')}</p><div class="catalog-price-row"><strong class="price">${money(c.price)}</strong>${badge(c.status)}</div></div>${!c.linked?`<p class="notice">${c.independent?'這是獨立品項，保留來源規格與價格，不連動庫存。':'這張價目卡尚未連結庫存商品，庫存狀態待確認。'}</p>`:''}<div class="form-actions">${c.product_id?`<button class="primary" data-action="product" data-id="${c.product_id}">查看庫存與批次</button>`:'<button data-action="mapping-catalog">整理商品對應</button>'}<button data-action="close">關閉</button></div>`,'商品價目 · 照片與規格');
}

async function history(seq){
  const p=await api('/history?'+new URLSearchParams({page:S.page,page_size:size('history'),kind:S.kind,from:S.from,to:S.to,product_id:S.productId}));
  if(seq!==generation)return;
  $('#main').innerHTML=heading('異動紀錄','每筆進出貨、盤點與改價，都有跡可查。','')+
    `<div id="export-state" class="export-state">${S.meta.export.pending?(S.meta.export.last_export?'商品資料已變動，需重新匯出發票商品。':'尚未匯出發票商品。'):'發票商品資料與上次匯出一致。'}${S.meta.export.issues.length?' 有 '+S.meta.export.issues.length+' 筆待確認。':''}</div><div class="toolbar"><select id="history-product" aria-label="篩選商品"><option value="">所有商品</option>${S.meta.products.map(p=>`<option value="${p.id}" ${String(p.id)===String(S.productId)?'selected':''}>${esc(p.name)} · ${esc(p.code)}</option>`).join('')}</select><select id="history-kind" aria-label="異動類型"><option value="">所有異動</option>${Object.entries(kinds).map(([k,v])=>`<option value="${k}" ${S.kind===k?'selected':''}>${v}</option>`).join('')}</select><input type="date" id="history-from" aria-label="開始日期" value="${esc(S.from)}"><input type="date" id="history-to" aria-label="結束日期" value="${esc(S.to)}"></div>
    <section class="panel table-panel"><div class="table-wrap"><table class="history-table"><thead><tr><th width="30%">商品</th><th width="15%">操作</th><th width="20%">變更</th><th width="22%">時間／操作人</th><th width="13%">更正</th></tr></thead><tbody>${p.items.map(m=>`<tr><td><span class="item-name">${esc(m.name)}</span><div class="item-sub">${esc(m.reason)}${m.batch_id?' · 批次 #'+m.batch_id:''}</div></td><td>${kinds[m.kind]||esc(m.kind)}</td><td>${['edit','mapping','create'].includes(m.kind)?'資料更新':`${esc(m.before_value??'未知')} → ${esc(m.after_value??'未知')}`}</td><td class="hide-mobile"><small>${esc(m.created_at.slice(5,16).replace('T',' '))} · 店主</small></td><td>${['receive','issue','return'].includes(m.kind)?`<button class="text-button danger" data-action="reverse" data-id="${m.id}">沖銷</button>`:'—'}</td></tr>`).join('')}</tbody></table>${!p.items.length?empty('尚無符合的異動紀錄','完成進貨、出貨或盤點後，紀錄會顯示在這裡。'):''}</div>${pager(p)}</section>`;
  for(const [id,key] of [['history-product','productId'],['history-kind','kind'],['history-from','from'],['history-to','to']])$('#'+id).onchange=async e=>{S[key]=e.target.value;S.page=1;await render();};
}

let generation=0;
export async function render(){
  if(S.savingCounts||S.savingSales)return;
  const seq=++generation;
  $('#main').dataset.view=S.view;
  document.querySelectorAll('[data-nav]').forEach(b=>b.classList.toggle('active',b.dataset.nav===S.view));
  try{
    await ({dashboard,inventory,catalog,history,exports:renderExports,'daily-sales':dailySales}[S.view]||inventory)(seq);
    if(seq!==generation)return;

  }
  catch(e){if(seq===generation)$('#main').innerHTML=empty('暫時無法讀取',e.message,'<button data-action="retry">重新載入</button>');}
}
function bindSearch(){let timer;$('#search').oninput=e=>{const v=e.target.value;clearTimeout(timer);timer=setTimeout(async()=>{S.q=v;S.page=1;await render();const s=$('#search');s?.focus();s?.setSelectionRange(v.length,v.length);},280);};}

async function printCatalog(){
  const first=await api('/catalog?page=1&page_size=10');let rows=[...first.items];
  for(let page=2;page<=Math.ceil(first.total/10);page++)rows.push(...(await api(`/catalog?page=${page}&page_size=10`)).items);
  document.querySelector('.print-page')?.remove();const el=document.createElement('section');el.className='print-page';
  el.innerHTML=`<header class="print-heading"><h1>菜騎鴨｜商品價目表</h1><p>${esc(S.meta.today)}</p></header><div class="print-grid">${rows.map(c=>`<article class="print-card">${productPhoto(c.image,c.name,'print-product-image','/media/','eager')}<h3>${esc(c.brand||'')} ${esc(c.name)}</h3><p>${esc(c.specification||c.unit||'')}</p><p class="price">${c.status==='out'?'缺貨':money(c.price)}</p>${!c.linked?'<small>庫存狀態尚未對應</small>':c.status==='uncounted'?'<small>未盤點</small>':''}</article>`).join('')}</div>`;document.body.append(el);
  await Promise.all([...el.querySelectorAll('img')].map(im=>im.decode().catch(()=>{})));window.print();
}


function showIssues(issues,page=1){
  const pageSize=4,items=issues.slice((page-1)*pageSize,page*pageSize);
  dialog('這些資料需要先確認',`<div class="mini-list">${items.map(text=>`<p class="notice">${esc(text)}</p>`).join('')}</div>${pager({total:issues.length,page,page_size:pageSize},'issue-details-page')}<button data-action="mapping-invoice">查看發票商品對應</button>`,'發票匯出');
  document.querySelectorAll('[data-action="issue-details-page"]').forEach(b=>b.onclick=()=>showIssues(issues,Number(b.dataset.page)));
}

document.addEventListener('click',async event=>{
  if((S.savingCounts||S.savingSales)&&event.target.closest('[data-nav],[data-action]')){event.preventDefault();return;}
  const nav=event.target.closest('[data-nav]');if(nav){if($('#dialog').open){if(S.dialogDirty&&!confirm('尚未儲存，確定離開？'))return;closeDialog(true);}await navigate(nav.dataset.nav);return;}
  const b=event.target.closest('[data-action]');if(!b||b.disabled)return;
  try{switch(b.dataset.action){
    case 'page':S.page=Number(b.dataset.page);await render();$('#main').scrollTop=0;break;
    case 'category-filter':S.category=S.category===b.dataset.category?'':b.dataset.category;S.page=1;await render();break;
    case 'photo-filter':S.photos=b.dataset.photos;S.page=1;await render();break;
    case 'filter':S.status=b.dataset.status;S.page=1;await render();break;
    case 'filter-dashboard':await navigate('inventory',{status:b.dataset.status});break;
    case 'product':await productPanel(Number(b.dataset.id));break;
    case 'operation':await operation(b.dataset.type,Number(b.dataset.id),b.dataset.batch?Number(b.dataset.batch):null);break;
    case 'choose-operation':await operation(b.dataset.type);break;
    case 'new-product':await newProduct();break;
    case 'catalog-detail':catalogDetail(b.dataset.id);break;
    case 'data':await dataManager();break;
    case 'import':await importPreview();break;
    case 'mapping-catalog':await mappings('catalog');break;
    case 'mapping-invoice':await mappings('invoice');break;
    case 'invoice-export':{const result=await api('/invoice-exports',{});location.href=`/api/invoice-exports/${result.export_id}/download`;await refreshMeta();toast('發票商品檔已產生');break;}
    case 'reverse':{const reason=prompt('填寫沖銷原因（原紀錄會保留）');if(reason){await api('/reversals',{movement_id:Number(b.dataset.id),reason,request_id:crypto.randomUUID()});await refresh();toast('已建立沖銷紀錄');}break;}
    case 'print':await printCatalog();break;
    case 'retry':await refresh();break;
    case 'close':closeDialog();break;
  }}catch(e){if(e.fields?.issues)showIssues(e.fields.issues);else toast(e.message);}
});

$('#dialog-close').onclick=()=>closeDialog();$('#dialog').addEventListener('cancel',e=>{e.preventDefault();closeDialog();});
$('#dialog-body').addEventListener('input',()=>S.dialogDirty=true);
$('#settings').onclick=()=>{if(!S.savingCounts&&!S.savingSales)dataManager();};
$('#logout').onclick=async()=>{if(S.savingCounts||S.savingSales)return;if((hasStocktakeDrafts()||hasSalesDraft())&&!confirm('有尚未儲存的盤點或銷售單，確定登出？銷售單草稿會保留在此分頁。'))return;const state=await api('/logout',{});S.csrf=state.csrf;clearStocktakeDrafts();showAuth(state);};
let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(S.meta)render();},180);});

function showAuth(state){S.authenticated=false;S.account=null;if($('#dialog').open)$('#dialog').close();$('#app').hidden=true;$('#auth-screen').hidden=false;const google=state.auth_mode==='google';$('#auth-title').textContent=google?'店家登入':state.setup_required?'建立管理密碼':'登入工作台';$('#auth-copy').textContent=google?'使用已授權的 Google 帳號，開始今天的店務。':state.setup_required?'第一次使用，設定至少 10 個字元的密碼。':'輸入密碼，開始今天的庫存管理。';$('#password').value='';$('#password').minLength=state.setup_required?10:1;$('#password').autocomplete=state.setup_required?'new-password':'current-password';$('#password').required=!google;$('#password').disabled=google;$('#password-auth').hidden=google;$('#google-auth').hidden=!google;$('#google-login').disabled=!state.google_ready;$('#google-auth-help').textContent=state.google_ready?'僅開放已授權的店家帳號。':'Google 登入尚未設定完成，請聯絡店家管理員。';$('#auth-error').textContent=state.login_error||'';
  $('#google-login').onclick=()=>{location.assign('/auth/google/start');};
  $('#auth-form').onsubmit=async e=>{e.preventDefault();if(google)return;const button=e.currentTarget.querySelector('[type="submit"]');button.disabled=true;$('#auth-error').textContent='';try{const result=await api(state.setup_required?'/setup':'/login',{password:$('#password').value});S.csrf=result.csrf;S.account=result.account;await start();}catch(error){$('#auth-error').textContent=error.message;}finally{button.disabled=false;}};
}
async function start(){S.authenticated=true;$('#auth-screen').hidden=true;$('#app').hidden=false;const roles={admin:['管','系統管理員'],owner:['闆','老闆'],staff:['員','員工']};$('.avatar').textContent=S.account?roles[S.account.role][0]:'店';$('.avatar').title=S.account?`${S.account.name||S.account.email} · ${roles[S.account.role][1]}`:'店家';await refresh();}
async function init(){try{const state=await api('/session');S.csrf=state.csrf;S.account=state.account;state.authenticated?await start():showAuth(state);}catch(e){$('#auth-screen').hidden=false;$('#auth-error').textContent=e.message;}}
init();
