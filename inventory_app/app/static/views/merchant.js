import {S,$,api,esc,money,qty,pager,empty,toast,render} from '../app.js';
import {productPhoto} from '../product-photo.js';

const drafts=new Map();
let requestId=null,errorText='',errorBatch=null;
export const hasStocktakeDrafts=()=>drafts.size>0;
export function clearStocktakeDrafts(){drafts.clear();requestId=null;errorText='';errorBatch=null;}
window.addEventListener('beforeunload',event=>{
  if(drafts.size||S.savingCounts){event.preventDefault();event.returnValue='';}
});

function toolbar(){
  return `<div class="toolbar merchant-toolbar"><div class="search-box"><input id="search" type="search" aria-label="搜尋商品" placeholder="找商品名稱或品號" value="${esc(S.q)}"></div><select id="category" aria-label="商品分類"><option value="">所有分類</option>${S.meta.categories.map(c=>`<option value="${esc(c)}" ${c===S.category?'selected':''}>${esc(c.replace(/^[A-Z]/,''))}</option>`).join('')}</select><div class="filters" aria-label="庫存狀態">${[['','全部'],['restock','待補貨'],['uncounted','未盤點'],['expiring','即期']].map(([value,label])=>`<button data-action="filter" data-status="${value}" aria-pressed="${S.status===value}" class="${S.status===value?'selected':''}">${label}</button>`).join('')}</div></div>`;
}

function cards(items){
  return `<div class="merchant-grid">${items.map(p=>`<button class="merchant-card" data-action="product" data-id="${p.id}" aria-label="管理 ${esc(p.name)}">${productPhoto(p.image,p.name,'merchant-photo','/media/')}<span class="merchant-card-info"><strong class="merchant-name">${esc(p.name)}</strong><span class="merchant-price">${money(p.price)}<small> / ${esc(p.unit)}</small></span><span class="merchant-stock">可售 ${qty(p)}</span></span></button>`).join('')}</div>`;
}

function stocktake(items){
  const rows=items.flatMap(p=>p.batches.map(b=>({p,b})));
  return `<form id="stocktake-form"><div class="stocktake-caption"><p>按批次填入現場實際數量；留白不更動，0 表示沒有庫存。帳面數量包含訂單預留。</p><p class="muted">這裡只調整數量；效期與可售狀態可點「調整批次」修改。</p></div><div class="stocktake-scroll"><table class="stocktake-table"><thead><tr><th>商品</th><th>批次／效期</th><th>帳面數量</th><th>實際數量</th></tr></thead><tbody>${rows.map(({p,b})=>`<tr class="${errorBatch===b.id?'stocktake-conflict':''}" data-stocktake-row="${b.id}"><td><strong>${esc(p.name)}</strong><small>${esc(p.code)} · ${esc(p.unit)}</small></td><td><span>#${b.id} · ${esc(b.expires_on||'效期未知')}</span><small>${b.expired?'已過期':b.saleable?'可售批次':'待確認可售'}</small><button type="button" class="text-button" data-action="operation" data-type="count" data-id="${p.id}" data-batch="${b.id}">調整批次</button></td><td><strong>${esc(b.quantity??'未盤點')}</strong> ${esc(p.unit)}${Number(b.reserved_quantity)>0?`<small>含預留 ${esc(b.reserved_quantity)} ${esc(p.unit)}</small>`:''}</td><td><input type="number" min="0" step="${['kg','g','斤','公斤','公克','台斤','兩'].includes(p.unit.toLowerCase())?'any':'1'}" inputmode="decimal" aria-label="${esc(p.name)} 批次 ${b.id} 實際數量" data-count-batch="${b.id}" value="${esc(drafts.get(b.id)?.actual_quantity??'')}" placeholder="尚未填寫"></td></tr>`).join('')}</tbody></table></div><div class="stocktake-save"><span id="stocktake-summary" aria-live="polite"></span><div class="button-row"><button type="button" id="reset-stocktake">清除已填數量</button><button type="submit" class="primary" id="save-stocktake">儲存盤點</button></div></div><p id="stocktake-error" class="error" role="alert">${esc(errorText)}</p></form>`;
}

function updateSummary(){
  if(!$('#stocktake-summary'))return;
  $('#stocktake-summary').textContent=drafts.size?`已填 ${drafts.size} 個批次（包含其他頁）`:'填入數量後，一次儲存';
  $('#save-stocktake').disabled=!drafts.size||S.savingCounts;
  $('#reset-stocktake').disabled=!drafts.size||S.savingCounts;
  document.querySelectorAll('[data-count-batch]').forEach(input=>{
    input.disabled=S.savingCounts||(drafts.size>=200&&!drafts.has(Number(input.dataset.countBatch)));
  });
  if(drafts.size>=200)$('#stocktake-summary').textContent+=' · 已達 200 批次上限，請先儲存';
}

export async function renderMerchant(isCurrent){
  const p=await api('/products?'+new URLSearchParams({q:S.q,status:S.status,category:S.category,page:S.page,page_size:10}));
  if(!isCurrent()||S.savingCounts)return;
  S.page=p.page;
  const table=S.inventoryMode==='table';
  $('#main').innerHTML=`<div class="page-heading merchant-heading"><div><p class="eyebrow">菜騎鴨 · 店務小幫手</p><h1>管商品</h1><p class="muted">${table?'像填表一樣，一次完成盤點。':'找到商品，點一下就能管理。'}</p></div><button data-action="new-product">＋ 新增商品</button></div><div class="merchant-mode" role="group" aria-label="商品呈現方式"><button data-inventory-mode="cards" aria-pressed="${!table}">商品卡片</button><button data-inventory-mode="table" aria-pressed="${table}">集中盤點</button>${!table&&drafts.size?`<span class="draft-note">${drafts.size} 個批次尚未儲存</span>`:''}</div>${toolbar()}${p.items.length?(table?stocktake(p.items):cards(p.items)):empty('沒有符合的商品','換個篩選條件，或至設定匯入原始 Excel。')}${table&&!p.items.length&&drafts.size?stocktake([]):''}${pager(p)}`;
  document.querySelectorAll('[data-inventory-mode]').forEach(b=>b.onclick=()=>{S.inventoryMode=b.dataset.inventoryMode;render();});
  let timer;
  $('#search').oninput=e=>{const value=e.target.value;clearTimeout(timer);timer=setTimeout(async()=>{if(S.view!=='inventory'||S.savingCounts)return;S.q=value;S.page=1;await render();$('#search')?.focus();},280);};
  $('#category').onchange=e=>{S.category=e.target.value;S.page=1;render();};
  if(!$('#stocktake-form'))return;
  const batchMap=new Map(p.items.flatMap(product=>product.batches.map(batch=>[batch.id,{product,batch}])));
  document.querySelectorAll('[data-count-batch]').forEach(input=>input.oninput=()=>{
    const id=Number(input.dataset.countBatch),{product,batch}=batchMap.get(id);
    if(input.value!==''&&!drafts.has(id)&&drafts.size>=200){input.value='';toast('一次最多盤點 200 個批次，請先儲存已填數量。');return;}
    if(input.value==='')drafts.delete(id);
    else drafts.set(id,{batch_id:id,expected_version:drafts.get(id)?.expected_version??batch.version,actual_quantity:input.value,name:product.name});
    requestId=null;errorText='';errorBatch=null;$('#stocktake-error').textContent='';updateSummary();
  });
  $('#reset-stocktake').onclick=async()=>{if(confirm('清除所有頁面已填但尚未儲存的盤點數量？')){clearStocktakeDrafts();await render();}};
  $('#stocktake-form').onsubmit=async e=>{
    e.preventDefault();if(S.savingCounts||!drafts.size)return;
    S.savingCounts=true;requestId||=crypto.randomUUID();updateSummary();
    document.querySelectorAll('#main button,#main input,#main select').forEach(el=>el.disabled=true);
    try{
      const items=[...drafts.values()].map(({name,...row})=>row);
      await api('/counts/bulk',{items,request_id:requestId});
      clearStocktakeDrafts();toast(`已儲存 ${items.length} 個批次的盤點`);
    }catch(error){
      errorBatch=error.fields?.batch_id;
      const name=drafts.get(errorBatch)?.name;
      errorText=(name?`${name}（批次 #${errorBatch}）：`:'')+error.message+'。尚未確認儲存成功，已填內容仍保留。';
      if(error.status===409)errorText+=' 請清除已填數量後重新讀取盤點表。';
    }finally{S.savingCounts=false;await render();}
  };
  updateSummary();
}

export async function renderExports(){
  $('#main').innerHTML=`<div class="page-heading"><div><p class="eyebrow">需要時，再匯出</p><h1>匯出資料</h1></div></div><div class="export-options"><section><h2>商品價目表</h2><p>預覽商品照片與售價，列印或另存 PDF。</p><button data-nav="catalog" class="primary">預覽價目表</button></section><section><h2>發票商品檔</h2><p>檢查商品對應與價格，匯出平台需要的七欄 Excel。</p><button data-action="invoice-export" class="primary">檢查並匯出</button></section></div>`;
}
