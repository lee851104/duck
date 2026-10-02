import {S,$,api,esc,money,qty,pager,empty,toast,render,categoryButtons} from '../app.js';
import {productPhoto} from '../product-photo.js';

const drafts=new Map();
let requestId=null,errorText='',errorBatch=null;
export const hasStocktakeDrafts=()=>drafts.size>0;
export function clearStocktakeDrafts(){drafts.clear();requestId=null;errorText='';errorBatch=null;}
window.addEventListener('beforeunload',event=>{
  if(drafts.size||S.savingCounts){event.preventDefault();event.returnValue='';}
});

function toolbar(){
  return `<div class="toolbar merchant-toolbar"><div class="search-box"><input id="search" type="search" aria-label="搜尋商品" placeholder="找商品名稱或品號" value="${esc(S.q)}"></div>${categoryButtons(S.meta.categories,S.category)}<div class="filters" aria-label="庫存狀態">${[['','全部'],['restock','待補貨'],['uncounted','未盤點'],['expiring','即期']].map(([value,label])=>`<button data-action="filter" data-status="${value}" aria-pressed="${S.status===value}" class="${S.status===value?'selected':''}">${label}</button>`).join('')}</div></div>`;
}

function cards(items){
  return `<div class="merchant-grid">${items.map(p=>`<button class="merchant-card" data-action="product" data-id="${p.id}" aria-label="管理 ${esc(p.name)}">${productPhoto(p.image,p.name,'merchant-photo','/media/')}<span class="merchant-card-info"><strong class="merchant-name">${esc(p.name)}</strong><span class="merchant-price">${money(p.price)}<small> / ${esc(p.unit)}</small></span><span class="merchant-stock">可售 ${qty(p)}</span></span></button>`).join('')}</div>`;
}

function stocktake(items){
  return `<form id="stocktake-form"><div class="stocktake-caption"><strong>看照片找商品，把眼前的實際數量填進來。</strong><p>數量相同就點「數量沒變」；沒有了就點「已售完」。留白不更動，最後一起儲存。</p></div><div class="stocktake-cards">${items.map(p=>`<article class="stocktake-card"><header class="stocktake-product">${productPhoto(p.image,p.name,'stocktake-photo','/media/')}<div><h2>${esc(p.name)}</h2><p>以「${esc(p.unit)}」計數${p.batches.length>1?` · ${p.batches.length} 個效期，分開數`:''}</p></div></header>${p.batches.map((b,index)=>`<section class="count-batch ${errorBatch===b.id?'stocktake-conflict':''}" data-stocktake-row="${b.id}"><div class="count-batch-heading"><strong>${p.batches.length>1?`第 ${index+1} 批 · `:''}${esc(b.expires_on?b.expires_on+' 到期':'效期尚未填寫')}</strong><button type="button" class="count-details" data-action="operation" data-type="count" data-id="${p.id}" data-batch="${b.id}">效期／狀態</button></div>${b.expired?'<p class="count-warning">已過期：仍照實盤點，這批不會計入可售庫存。</p>':!b.saleable?'<p class="count-warning">這批尚未確認可售，盤點只更新數量。</p>':''}<div class="count-book">原本記錄：<strong>${esc(b.quantity??'還沒盤點')}</strong>${b.quantity===null?'':' '+esc(p.unit)}</div>${Number(b.reserved_quantity)>0?`<p class="count-reserved">含替客人保留的 ${esc(b.reserved_quantity)} ${esc(p.unit)}，請一起數。</p>`:''}<label class="count-label" for="count-${b.id}">現在實際有幾${esc(p.unit)}？</label><div class="count-stepper"><button type="button" data-count-command="minus" data-batch-id="${b.id}" aria-label="減少數量">−</button><div class="count-input-wrap"><input id="count-${b.id}" type="number" min="0" step="${['kg','g','斤','公斤','公克','台斤','兩'].includes(p.unit.toLowerCase())?'any':'1'}" inputmode="decimal" aria-label="${esc(p.name)} 批次 ${b.id} 實際數量" data-count-batch="${b.id}" data-original="${esc(b.quantity??'')}" data-unit="${esc(p.unit)}" value="${esc(drafts.get(b.id)?.actual_quantity??'')}" placeholder="填數量"><span>${esc(p.unit)}</span></div><button type="button" data-count-command="plus" data-batch-id="${b.id}" aria-label="增加數量">＋</button></div><div class="count-shortcuts"><button type="button" data-count-command="same" data-batch-id="${b.id}" ${b.quantity===null?'disabled':''}>數量沒變</button><button type="button" data-count-command="zero" data-batch-id="${b.id}">已售完，填 0</button><button type="button" data-count-command="clear" data-batch-id="${b.id}">清除此筆</button></div><p class="count-feedback" aria-live="polite"></p></section>`).join('')}</article>`).join('')}</div><p id="stocktake-error" class="error" role="alert">${esc(errorText)}</p>${errorBatch?`<button type="button" id="reload-conflict" class="action-count">重填發生衝突的這一批</button>`:''}<div class="stocktake-save"><div><strong id="stocktake-summary" aria-live="polite"></strong><small id="stocktake-page-progress"></small></div><div class="button-row"><button type="button" id="reset-stocktake">全部清除</button><button type="submit" class="primary" id="save-stocktake">儲存盤點</button></div></div></form>`;
}

function updateSummary(){
  if(!$('#stocktake-summary'))return;
  const inputs=[...document.querySelectorAll('[data-count-batch]')];
  $('#stocktake-summary').textContent=drafts.size?`已填 ${drafts.size} 筆，尚未儲存`:'還沒填數量';
  $('#stocktake-page-progress').textContent=`本頁 ${inputs.filter(el=>drafts.has(Number(el.dataset.countBatch))).length} / ${inputs.length} 筆已填 · 換頁仍會保留`;
  $('#save-stocktake').textContent=S.savingCounts?'正在儲存…':drafts.size?`儲存這 ${drafts.size} 筆盤點`:'儲存盤點';
  $('#save-stocktake').disabled=!drafts.size||S.savingCounts;
  $('#reset-stocktake').disabled=!drafts.size||S.savingCounts;
  inputs.forEach(input=>{
    const id=Number(input.dataset.countBatch),draft=drafts.get(id),row=input.closest('[data-stocktake-row]');
    const locked=S.savingCounts||(drafts.size>=200&&!draft);
    input.disabled=locked;row.classList.toggle('count-filled',!!draft);
    const current=input.value!==''?Number(input.value):input.dataset.original!==''?Number(input.dataset.original):null;
    row.querySelectorAll('[data-count-command]').forEach(button=>{
      const command=button.dataset.countCommand;
      button.disabled=locked||(command==='same'&&input.dataset.original==='')||(command==='minus'&&(current===null||current<=0))||(command==='clear'&&!draft);
    });
    let message='尚未填寫，不會更動庫存';
    if(draft){
      const value=Number(draft.actual_quantity),original=input.dataset.original;
      if(original==='')message=`已填 ${draft.actual_quantity} ${input.dataset.unit}，待儲存`;
      else {const difference=Number((value-Number(original)).toFixed(6));message=difference===0?'數量相同，已確認':`比原本${difference>0?'多':'少'} ${Math.abs(difference)} ${input.dataset.unit}，待儲存`;}
    }
    row.querySelector('.count-feedback').textContent=message;
  });
  if(drafts.size>=200)$('#stocktake-summary').textContent+=' · 請先儲存';
}

export async function renderMerchant(isCurrent){
  const p=await api('/products?'+new URLSearchParams({q:S.q,status:S.status,category:S.category,page:S.page,page_size:10}));
  if(!isCurrent()||S.savingCounts)return;
  S.page=p.page;
  const table=S.inventoryMode==='table';
  $('#main').innerHTML=`<div class="page-heading merchant-heading"><div><p class="eyebrow">菜騎鴨 · 店務小幫手</p><h1>${table?'盤點庫存':'管商品'}</h1><p class="muted">${table?'照著貨架數，點一下就記好。':'找到商品，點一下就能管理。'}</p></div><button data-action="new-product">＋ 新增商品</button></div><div class="merchant-mode" role="group" aria-label="商品呈現方式"><button data-inventory-mode="cards" aria-pressed="${!table}">商品資料</button><button data-inventory-mode="table" aria-pressed="${table}">盤點庫存</button>${!table&&drafts.size?`<span class="draft-note">${drafts.size} 個批次尚未儲存</span>`:''}</div>${toolbar()}${p.items.length?(table?stocktake(p.items):cards(p.items)):empty('沒有符合的商品','換個篩選條件，或至設定匯入原始 Excel。')}${table&&!p.items.length&&drafts.size?stocktake([]):''}${pager(p)}`;
  document.querySelectorAll('[data-inventory-mode]').forEach(b=>b.onclick=()=>{S.inventoryMode=b.dataset.inventoryMode;render();});
  let timer;
  $('#search').oninput=e=>{const value=e.target.value;clearTimeout(timer);timer=setTimeout(async()=>{if(S.view!=='inventory'||S.savingCounts)return;S.q=value;S.page=1;await render();$('#search')?.focus();},280);};
  if(!$('#stocktake-form'))return;
  const batchMap=new Map(p.items.flatMap(product=>product.batches.map(batch=>[batch.id,{product,batch}])));
  document.querySelectorAll('[data-count-batch]').forEach(input=>input.oninput=()=>{
    const id=Number(input.dataset.countBatch),{product,batch}=batchMap.get(id);
    if(input.value!==''&&!drafts.has(id)&&drafts.size>=200){input.value='';toast('一次最多盤點 200 個批次，請先儲存已填數量。');return;}
    if(input.value==='')drafts.delete(id);
    else drafts.set(id,{batch_id:id,expected_version:drafts.get(id)?.expected_version??batch.version,actual_quantity:input.value,name:product.name});
    requestId=null;
    // A different edited row must not discard the stale batch's recovery target.
    if(errorBatch===id&&input.value===''){errorBatch=null;$('#reload-conflict')?.remove();}
    if(!errorBatch){errorText='';$('#stocktake-error').textContent='';}
    updateSummary();
  });
  document.querySelectorAll('[data-count-command]').forEach(button=>button.onclick=()=>{
    if(S.savingCounts)return;
    const input=$(`[data-count-batch="${button.dataset.batchId}"]`),command=button.dataset.countCommand;
    const current=Number(input.value!==''?input.value:input.dataset.original||0);
    input.value=command==='clear'?'':command==='same'?input.dataset.original:command==='zero'?'0':String(Math.max(0,Number((current+(command==='plus'?1:-1)).toFixed(6))));
    input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  if($('#reload-conflict'))$('#reload-conflict').onclick=async()=>{drafts.delete(errorBatch);requestId=null;errorBatch=null;errorText='';await render();};
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
      if(error.status===409)errorText+=' 請點「重填發生衝突的這一批」，其他已填數量會保留。';
    }finally{S.savingCounts=false;await render();}
  };
  updateSummary();
}

let exportTimer;
export async function renderExports(){
  clearTimeout(exportTimer);
  const state=await api('/excel-sync');
  if(S.view!=='exports')return;
  const busy=state.pending||state.running,last=state.last,ready=last&&!busy&&!state.error;
  $('#main').innerHTML=`<div class="page-heading"><div><p class="eyebrow">菜騎鴨 · 本機 Excel</p><h1>匯出庫存管理表</h1><p class="muted">平常在系統記錄銷售、盤點與改價，Excel 由系統更新。</p></div></div>
    <section class="panel inventory-export-panel"><h2>庫存管理表</h2><p>完整匯出所有商品與批次，包含進價、售價、數量及效期。未知數值保留空白；同商品不同批次分列。</p><button id="download-inventory" class="primary" ${ready?'':'disabled'}>下載庫存管理表 Excel</button><p class="draft-note">下載的是最後同步完成的資料；Excel 內的手動修改不會回寫系統。</p></section>
    <section class="panel inventory-export-panel"><h2>三份 Excel 自動同步</h2><p id="excel-sync-status" role="status">${busy?'正在產生最新 Excel…':state.error?esc(state.error):last?'已同步 · '+esc(last.created_at.slice(0,19).replace('T',' ')):'尚未產生 Excel，請按下方開始同步。'}</p>
    <p class="muted">每次資料儲存成功後，自動產生庫存管理表、商品價目表與發票系統表。價目表保留照片與版型，只有已確認對應的商品會連動售價；獨立品項保留原值。</p>
    ${last?`<p>${last.batch_count} 筆庫存批次 · ${last.invoice_count} 筆發票商品</p><label>最新三份檔案所在資料夾<input id="excel-folder" readonly value="${esc(last.folder)}"></label><p class="draft-note">複製後貼到檔案總管的位址列即可開啟。每次同步產生新的一批，已開啟的舊 Excel 不會自行更新。</p><button id="copy-excel-folder">複製資料夾位置</button>`:''}
    <button id="retry-excel-sync" ${busy?'disabled':''}>${last?'重新同步':'開始同步'}</button></section>`;
  $('#download-inventory').onclick=async()=>{
    const button=$('#download-inventory');button.disabled=true;
    try{
      const response=await fetch('/api/inventory-export/download');
      if(!response.ok){const result=await response.json();throw new Error(result.error?.message||'下載失敗，請重試');}
      const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');
      link.href=url;link.download='庫存管理.xlsx';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(error){toast(error.message);}finally{if(button.isConnected)button.disabled=false;}
  };
  $('#retry-excel-sync').onclick=async()=>{try{await api('/excel-sync',{});await renderExports();}catch(error){toast(error.message);}};
  if($('#copy-excel-folder'))$('#copy-excel-folder').onclick=async()=>{
    try{await navigator.clipboard.writeText(last.folder);toast('已複製資料夾位置');}
    catch{$('#excel-folder').focus();$('#excel-folder').select();toast('請複製選取的資料夾位置');}
  };
  if(busy)exportTimer=setTimeout(()=>{if(S.view==='exports')renderExports().catch(e=>toast(e.message));},1200);
}
