import {S,$,api,esc,image,dialog,closeDialog,toast,pager,categoryButtons} from '../app.js';

const storageKey='duck-daily-sales-draft-v1';
let draft={sold_on:'',note:'',items:[],pending:null},products=[],query='',category='',historyPage=1;
try{const saved=JSON.parse(sessionStorage.getItem(storageKey));if(saved&&Array.isArray(saved.items))draft=saved;}catch{}
const persist=()=>{try{sessionStorage.setItem(storageKey,JSON.stringify(draft));}catch{}};
export const hasSalesDraft=()=>draft.items.length>0;
export function clearSalesDraft(){draft={sold_on:'',note:'',items:[],pending:null};persist();}
const payload=()=>({sold_on:draft.sold_on,note:draft.note,items:draft.items.map(p=>({product_id:p.id,quantity:p.quantity}))});

export async function renderDailySales(seq,isCurrent){
  draft.sold_on ||= S.meta.today;
  const [catalog,history]=await Promise.all([api('/daily-sales/products?'+new URLSearchParams({sold_on:draft.sold_on})),api('/daily-sales?page='+historyPage)]);
  if(!isCurrent())return;
  products=catalog.items;historyPage=history.page;
  $('#main').innerHTML=`<div class="page-heading"><div><p class="eyebrow">菜騎鴨 · 每日結帳</p><h1>每日銷售單</h1><p class="muted">把今天賣出的商品整理成一張單，確認後一次扣庫存。</p></div><span class="sales-stamp">結帳後 · 記一張</span></div>
    <div class="sales-layout"><section class="panel sales-picker"><div class="panel-head"><h2>01 選商品</h2><small>點選加入銷售單</small></div><div class="sales-filters"><input id="sales-search" type="search" aria-label="搜尋銷售商品" placeholder="搜尋品名或品號" value="${esc(query)}">${categoryButtons(products.map(p=>p.category),category,'sales-category')}</div><p class="sales-photo-note">照片供辨識商品，包裝入數可能不同；扣庫存以商品標示的單位為準。</p><div id="sales-products" class="sales-products"></div></section>
    <section class="panel sales-sheet"><div class="panel-head"><h2>02 填賣出數量</h2><span id="sales-count"></span></div><div class="sales-sheet-body"><div class="sales-date"><label>銷售日期<input id="sales-date" type="date" max="${S.meta.today}" value="${esc(draft.sold_on)}" ${draft.pending?'disabled':''}></label><p class="muted">每天一張。<br>補登可選之前的日期。</p></div><div id="sales-lines"></div><label>備註（選填）<textarea id="sales-note" maxlength="500" rows="2" placeholder="例如：晚班結帳彙總" ${draft.pending?'disabled':''}>${esc(draft.note)}</textarea></label><p class="sales-rule">依效期由近到遠扣庫存，已確認可售但效期未知的批次排最後。請填商品的庫存單位；任何一項不足，整張都不扣。</p><p class="error" id="sales-error" role="alert"></p><button id="sales-preview" class="primary">檢查整張單 →</button><p class="draft-note">草稿保存在此分頁，切換頁面或重新整理仍會保留。</p></div></section></div>
    <section class="panel sales-history"><div class="panel-head"><h2>每日紀錄</h2><small>已送出的單可查看明細及沖銷</small></div><div class="sales-history-list">${history.items.map(h=>`<button class="sales-history-row" data-sheet="${h.id}"><span><strong>${esc(h.sold_on)}</strong><small>銷售單 #${h.id} · ${h.item_count} 項商品</small></span><span class="badge ${h.status==='posted'?'normal':''}">${h.status==='posted'?'已扣庫存':'已沖銷'}</span><span>查看 ›</span></button>`).join('')||'<p class="sales-empty">還沒有銷售單。完成今天的結帳後，從上方開始填寫。</p>'}</div>${pager(history,'sales-history-page')}</section>`;
  drawProducts();drawLines();
  $('#sales-search').oninput=e=>{query=e.target.value;drawProducts();};
  document.querySelectorAll('[data-action="sales-category"]').forEach(b=>b.onclick=()=>{
    category=category===b.dataset.category?'':b.dataset.category;
    document.querySelectorAll('[data-action="sales-category"]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.category===category)));
    drawProducts();
  });
  $('#sales-note').oninput=e=>{draft.note=e.target.value;persist();};
  $('#sales-date').onchange=async e=>{
    if(!e.target.value||!e.target.checkValidity()){e.target.value=draft.sold_on;return;}
    const old=draft.sold_on,chosen=e.target.value;e.target.disabled=true;
    try{const data=await api('/daily-sales/products?'+new URLSearchParams({sold_on:chosen}));draft.sold_on=chosen;products=data.items;persist();drawProducts();drawLines();}
    catch(error){e.target.value=old;toast(error.message);}finally{e.target.disabled=false;}
  };
  $('#sales-preview').onclick=preview;
  document.querySelectorAll('[data-sheet]').forEach(b=>b.onclick=()=>showSheet(b.dataset.sheet).catch(e=>toast(e.message)));
  document.querySelectorAll('[data-action="sales-history-page"]').forEach(b=>b.onclick=async()=>{historyPage=Number(b.dataset.page);const {render}=await import('../app.js');await render();});
  if(draft.pending)$('#sales-error').textContent='上次送出結果尚未確認。請按「確認上次送出結果」安全重試，不會重複扣庫存。';
}

function drawProducts(){
  const shown=products.filter(p=>(!category||p.category===category)&&(!query||(p.name+' '+p.code).toLowerCase().includes(query.toLowerCase())));
  $('#sales-products').innerHTML=shown.map(p=>`<button class="sales-product ${draft.items.some(i=>i.id===p.id)?'selected':''}" data-add-sale="${p.id}" ${draft.pending?'disabled':''}>${image(p)}<span><strong>${esc(p.name)}</strong><small>${esc(p.code)} · 可扣 ${esc(p.available)} ${esc(p.unit)}</small></span><span class="sales-add">${draft.items.some(i=>i.id===p.id)?'✓':'＋'}</span></button>`).join('')||'<p class="sales-empty">沒有符合的商品，試試其他名稱或分類。</p>';
  document.querySelectorAll('[data-add-sale]').forEach(b=>b.onclick=()=>{
    const p=products.find(p=>p.id===Number(b.dataset.addSale));
    if(!draft.items.some(i=>i.id===p.id)){
      if(draft.items.length>=200){toast('一張單最多 200 項商品');return;}
      draft.items.push({...p,quantity:'1'});persist();drawProducts();drawLines();
    }
    document.querySelector(`[data-sale-qty="${p.id}"]`)?.focus();
  });
}

function drawLines(){
  $('#sales-count').textContent=draft.items.length+' 項商品';
  $('#sales-lines').innerHTML=draft.items.map(p=>`<div class="sales-line"><div><strong>${esc(p.name)}</strong><small>${esc(p.code)} · 可扣 ${esc(products.find(x=>x.id===p.id)?.available??'待確認')} ${esc(p.unit)}</small></div><label><span class="sales-sr">${esc(p.name)}賣出數量</span><input type="number" min="${['kg','g','斤','公斤','公克','台斤','兩'].includes(p.unit.toLowerCase())?'0.000001':'1'}" max="999999999" step="${['kg','g','斤','公斤','公克','台斤','兩'].includes(p.unit.toLowerCase())?'0.000001':'1'}" data-sale-qty="${p.id}" value="${esc(p.quantity)}" ${draft.pending?'disabled':''}><span>${esc(p.unit)}</span></label><button class="text-button" data-remove-sale="${p.id}" aria-label="移除${esc(p.name)}" ${draft.pending?'disabled':''}>×</button></div>`).join('')||'<div class="sales-empty"><strong>今天賣出了什麼？</strong><p>先從商品清單加入，再填整天合計數量。</p></div>';
  $('#sales-preview').disabled=!draft.items.length;
  $('#sales-preview').textContent=draft.pending?'確認上次送出結果':'檢查整張單 →';
  document.querySelectorAll('[data-sale-qty]').forEach(el=>el.oninput=()=>{draft.items.find(p=>p.id===Number(el.dataset.saleQty)).quantity=el.value;persist();});
  document.querySelectorAll('[data-remove-sale]').forEach(b=>b.onclick=()=>{draft.items=draft.items.filter(p=>p.id!==Number(b.dataset.removeSale));persist();drawProducts();drawLines();});
}

async function preview(){
  if(draft.pending){await submit();return;}
  for(const input of document.querySelectorAll('[data-sale-qty]'))if(!input.value||!input.reportValidity()){input.focus();return;}
  $('#sales-preview').disabled=true;$('#sales-error').textContent='';S.savingSales=true;
  try{
    const body=payload(),plan=await api('/daily-sales/preview',body);
    dialog('確認這張銷售單',`<p class="notice">${esc(plan.sold_on)} · ${plan.items.length} 項商品。確認後立即扣庫存。</p><div class="sales-review">${plan.items.map(p=>`<div><strong>${esc(p.name)}</strong><p>賣出 <b>${esc(p.quantity)} ${esc(p.unit)}</b> · 可扣庫存 ${esc(p.available)} → ${esc(p.remaining)}</p><small>${p.allocations.map(a=>`批次 #${a.batch_id}（${esc(a.expires_on||'效期未知／已確認可售')}）扣 ${esc(a.quantity)}`).join('、')}</small></div>`).join('')}</div><p class="error" id="sales-submit-error" role="alert"></p><div class="form-actions"><button data-action="close">返回修改</button><button id="sales-confirm" class="primary">確認扣庫存</button></div>`,'每日結帳 · 最後確認');
    $('#sales-confirm').onclick=async()=>{draft.pending={...body,revision:plan.revision,request_id:crypto.randomUUID()};persist();await submit();};
  }catch(error){$('#sales-error').textContent=error.message;}
  finally{S.savingSales=false;if($('#sales-preview'))$('#sales-preview').disabled=false;}
}

async function submit(){
  if(S.savingSales)return;
  S.savingSales=true;
  if($('#sales-confirm'))$('#sales-confirm').disabled=true;
  if($('#sales-preview'))$('#sales-preview').disabled=true;
  let result;
  try{result=await api('/daily-sales',draft.pending);}
  catch(error){
    // A network/5xx failure may occur after commit: retain the identical payload for retry.
    if(error.status&&error.status<500){draft.pending=null;persist();}
    closeDialog(true);
    $('#sales-error').textContent=error.message+(draft.pending?'。結果尚未確認，請按下方按鈕安全重試。':'。整張未扣庫存，請修正後重新檢查。');
  }finally{S.savingSales=false;}
  if(result){clearSalesDraft();closeDialog(true);toast(`銷售單 #${result.id} 已完成，${result.items.length} 項商品已扣庫存`);const {refresh}=await import('../app.js');await refresh();await showSheet(result.id);}
  else{drawProducts();drawLines();$('#sales-date').disabled=!!draft.pending;$('#sales-note').disabled=!!draft.pending;}
}

async function showSheet(id){
  const sheet=await api('/daily-sales/'+id);
  dialog(`銷售單 #${sheet.id}`,`<p class="notice">${esc(sheet.sold_on)} · ${sheet.status==='posted'?'已扣庫存':'已沖銷，庫存已加回'}</p><div class="sales-review">${sheet.items.map(p=>`<div><strong>${esc(p.name)}</strong><p>${esc(p.quantity)} ${esc(p.unit)}</p><small>${p.allocations.map(a=>`批次 #${a.batch_id}：${esc(a.before_value)} → ${esc(a.after_value)}`).join('、')}</small></div>`).join('')}</div><p>${esc(sheet.note||'無備註')}</p><p class="muted">建立時間：${esc(sheet.created_at.slice(0,16).replace('T',' '))}</p>${sheet.status==='void'?`<p>沖銷原因：${esc(sheet.void_reason)}</p>`:'<p class="muted">填錯可沖銷整張後重填。已有後續盤點的批次，需從盤點更正。</p><button id="sales-void" class="danger">沖銷整張單並加回庫存</button>'}<p id="sales-void-error" class="error" role="alert"></p>`,'每日銷售紀錄');
  if($('#sales-void')){
    let pendingVoid=null;
    $('#sales-void').onclick=async e=>{
      if(!pendingVoid){const reason=prompt('填寫沖銷原因；整張銷售單的數量會加回庫存。');if(!reason)return;pendingVoid={reason,request_id:crypto.randomUUID()};}
      e.target.disabled=true;S.savingSales=true;
      try{await api('/daily-sales/'+id+'/void',pendingVoid);pendingVoid=null;closeDialog(true);toast('整張已沖銷，庫存已加回');S.savingSales=false;const {refresh}=await import('../app.js');await refresh();await showSheet(id);}
      catch(error){if(error.status&&error.status<500)pendingVoid=null;$('#sales-void-error').textContent=error.message;}
      finally{S.savingSales=false;e.target.disabled=false;}
    };
  }
}
window.addEventListener('beforeunload',e=>{if(hasSalesDraft()){e.preventDefault();e.returnValue='';}});
