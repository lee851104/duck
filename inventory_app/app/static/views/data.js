import {S,$,api,esc,dialog,formSubmit,closeDialog,refresh,toast,pager,money} from '../app.js';

export async function dataManager(){
  dialog('設定',`<div class="mini-list"><button id="begin-import">匯入原始 Excel</button><button id="catalog-map">確認價目表商品對應</button><button id="invoice-map">確認發票商品對應</button><button id="backup-now">立即備份</button><button data-nav="history">完整操作紀錄</button><button data-nav="dashboard">庫存總覽</button></div><p class="muted">${S.meta.backup?.error?esc(S.meta.backup.error):S.meta.backup?'上次備份：'+esc(S.meta.backup.created_at.slice(0,16).replace('T',' ')):'尚無備份紀錄'}<br>電腦開啟且系統運行時，每天自動備份一次。</p>`,'店務設定');
  $('#begin-import').onclick=()=>importPreview();$('#catalog-map').onclick=()=>mappings('catalog');$('#invoice-map').onclick=()=>mappings('invoice');
  $('#backup-now').onclick=async e=>{const button=e.currentTarget;button.disabled=true;try{await api('/backups',{});await refresh();toast('備份完成');closeDialog(true);}catch(error){toast(error.message);}finally{button.disabled=false;}};
}

export async function importPreview(){
  dialog('讀取原始資料','<p class="muted">正在整理庫存、價目表與發票商品，第一次會需要較多時間。</p>','匯入資料');
  try{
    const p=await api('/imports/preview',{});const codes={},prices={};let page=1,tab='issues';
    const pageSize=innerWidth<=700?1:2;
    const issues=p.issues;
    let acknowledged=false;
    const sources=[...new Set(issues.map(i=>i.source))];
    const collisions=p.rows.filter(r=>sources.includes(r.source));
    const criticalSources=new Set(issues.filter(i=>['code_collision','price_conflict','invalid_number','invalid_date','formula_cache_missing'].includes(i.kind)).map(i=>i.source));
    collisions.sort((a,b)=>Number(criticalSources.has(b.source))-Number(criticalSources.has(a.source)));
    const notes=source=>issues.filter(i=>i.source===source).map(i=>esc(i.message)+(i.original_value!==null&&i.original_value!==undefined?'（原值：'+esc(i.original_value)+'）':'')).join('；');
    const summary=`${issues.filter(i=>i.kind==='unknown_stock').length} 筆未盤點，${issues.filter(i=>i.kind==='missing_price').length} 筆缺售價。`;
    function draw(){
      const rows=tab==='issues'?collisions:p.rows;
      const items=rows.slice((page-1)*pageSize,page*pageSize);
      dialog('確認原始資料',`<div class="import-counts"><span><strong>${p.rows.length}</strong>庫存列</span><span><strong>${p.price_cards.length}</strong>圖卡</span><span><strong>${p.invoice_items.length}</strong>發票項目</span></div><p class="notice">${summary} 不同商品需使用不同品號；其餘未知值保留，請確認後匯入。</p><div class="filters"><button id="issue-tab" class="${tab==='issues'?'selected':''}">需確認 ${collisions.length} 筆</button><button id="rows-tab" class="${tab==='rows'?'selected':''}">全部庫存</button></div><form id="import-form"><div class="mini-list">${items.map(r=>`<div class="mapping-row"><span class="item-name">${esc(r.name)} <small>· ${esc(r.unit)}</small></span><div class="mapping-line"><label>品號<input data-code="${esc(r.source)}" value="${esc(codes[r.source]??r.code)}" required></label><label>售價<input data-price="${esc(r.source)}" type="number" min="0" step="any" value="${esc(prices[r.source]??r.price??'')}"></label></div><small>${r.quantity===null?'未盤點':esc(r.quantity)+' '+esc(r.unit)} · ${esc(r.source.split('/').slice(-2).join(' 第 '))} 列</small>${notes(r.source)?`<p class="import-issue">${notes(r.source)}</p>`:''}</div>`).join('')||'<p class="muted">沒有待確認的資料問題。</p>'}</div>${pager({total:rows.length,page,page_size:pageSize},'import-page')}<label class="check-label"><input type="checkbox" name="acknowledge_issues" ${acknowledged?'checked':''} required>確認未設定的數量、價格或日期保留為未知</label><p class="error" role="alert"></p><div class="form-actions"><button type="button" data-action="close">取消</button><button class="primary" type="submit">確認匯入</button></div></form>`,'首次匯入');
      const persist=()=>{acknowledged=$('[name="acknowledge_issues"]').checked;document.querySelectorAll('[data-code]').forEach(e=>codes[e.dataset.code]=e.value);document.querySelectorAll('[data-price]').forEach(e=>prices[e.dataset.price]=e.value||null);};
      document.querySelectorAll('[data-action="import-page"]').forEach(b=>b.onclick=()=>{persist();page=Number(b.dataset.page);draw();});
      $('#issue-tab').onclick=()=>{persist();tab='issues';page=1;draw();};$('#rows-tab').onclick=()=>{persist();tab='rows';page=1;draw();};
      formSubmit($('#import-form'),async()=>{persist();const result=await api('/imports/'+p.import_id+'/commit',{codes,prices,acknowledge_issues:acknowledged});closeDialog(true);await refresh();toast(`已匯入 ${result.products} 項商品`);});
    }draw();
  }catch(e){dialog('匯入資料','<p class="error">'+esc(e.message)+'</p>');}
}

export async function mappings(kind,page=1,pending=true){
  const p=await api(`/mappings/${kind}?page=${page}&page_size=2&pending=${pending?1:0}`);
  const title=kind==='catalog'?'價目表商品對應':'發票商品對應';
  dialog(title,`<div class="button-row"><button id="toggle-mapping-filter">${pending?'查看全部／修改已整理資料':'只看待確認'}</button><small>${pending?'待確認':'全部'} ${p.total} 筆</small></div><p class="muted">${kind==='catalog'?'相同規格可使用庫存售價；不同容量、整箱或其他品項可選獨立品項，保留原價且不連動庫存。':'確認每筆發票項目。蔬菜價格系列等項目可保留固定資料。'}</p><div class="mini-list">${p.items.map(r=>`<form class="mapping-row" data-mapping-id="${r.id}"><span class="item-name">${esc(r.brand||'')} ${esc(r.name)}</span><small>${esc(r.specification||r.unit||'')} · ${money(r.original_price??r.price)} · ${esc(r.source)}</small><select name="product_id" aria-label="${esc(r.name)} 對應商品"><option value="">${kind==='invoice'?'未對應／固定商品':'尚未對應'}</option>${kind==='catalog'?`<option value="independent" ${r.independent?'selected':''}>獨立品項（不連動庫存）</option>`:''}${S.meta.products.map(x=>`<option value="${x.id}" ${x.id===r.product_id?'selected':''}>${esc(x.name)} · ${esc(x.code)} · ${esc(x.unit)}</option>`).join('')}</select><div class="mapping-line">${kind==='catalog'?`<select name="pricing_mode" aria-label="價格連動方式"><option value="fixed" ${r.pricing_mode==='fixed'?'selected':''}>保留原價，只連動庫存</option><option value="product" ${r.pricing_mode==='product'?'selected':''}>使用商品售價（須相同規格）</option></select>`:`<label class="check-label"><input name="fixed" type="checkbox" ${r.fixed?'checked':''}>確認為固定發票項目</label>`}<button type="submit">儲存</button></div><p class="error" role="alert"></p></form>`).join('')||`<p class="muted">${pending?'沒有待確認的對應，可切換全部資料查看或修改。':'請先匯入原始資料。'}</p>`}</div>${pager(p,'mapping-page')}`,'商品資料對應');
  document.querySelectorAll('[data-action="mapping-page"]').forEach(b=>b.onclick=()=>mappings(kind,Number(b.dataset.page),pending));
  document.querySelectorAll('[data-mapping-id]').forEach(form=>formSubmit(form,async f=>{await api(`/mappings/${kind}/${form.dataset.mappingId}`,{product_id:f.get('product_id')&&f.get('product_id')!=='independent'?Number(f.get('product_id')):null,independent:f.get('product_id')==='independent',pricing_mode:f.get('product_id')==='independent'?'fixed':f.get('pricing_mode'),fixed:f.has('fixed')});S.dialogDirty=false;await refresh();await mappings(kind,page,pending);toast('對應已儲存');}));
  $('#toggle-mapping-filter').onclick=()=>mappings(kind,1,!pending);
  if(kind==='invoice'){
    const button=document.createElement('button');button.textContent='新增發票商品';button.onclick=()=>newInvoiceItem();$('#dialog-body').prepend(button);
  }
}

function newInvoiceItem(){
  if(!S.meta.products.length){toast('請先新增商品');return;}
  dialog('新增發票商品',`<form id="invoice-item-form"><div class="form-grid"><label class="full">商品<select name="product_id">${S.meta.products.map(p=>`<option value="${p.id}">${esc(p.name)} · ${esc(p.code)}</option>`).join('')}</select></label><label>發票平台分類編號<input name="category" inputmode="numeric" pattern="[0-9]+" required placeholder="例如 1734"></label><label>是否含稅<select name="tax"><option value="1">1 · 含稅</option><option value="0">0 · 未含稅</option></select></label></div><p class="muted">分類編號請依發票平台設定填寫。售價與單位會使用商品資料。</p><p class="error" role="alert"></p><div class="form-actions"><button type="button" data-action="close">取消</button><button class="primary" type="submit">加入清單</button></div></form>`,'發票商品');
  const requestId=crypto.randomUUID();
  formSubmit($('#invoice-item-form'),async f=>{await api('/invoice-items',{product_id:Number(f.get('product_id')),category:f.get('category'),tax:Number(f.get('tax')),request_id:requestId});await refresh();await mappings('invoice');toast('已加入發票商品清單');});
}
