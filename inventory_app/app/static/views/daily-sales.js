import {S,$,api,esc,image,dialog,closeDialog,toast,pager,categoryButtons} from '../app.js';
import {draftSoldOn} from '../sales-date.js';

const storageKey='duck-daily-sales-draft-v1';
let draft={sold_on:'',note:'',items:[],line_orders:[],excel_imports:[],pending:null},products=[],query='',category='',historyPage=1;
try{const saved=JSON.parse(sessionStorage.getItem(storageKey));if(saved&&Array.isArray(saved.items))draft={line_orders:[],excel_imports:[],...saved};}catch{}
const persist=()=>{try{sessionStorage.setItem(storageKey,JSON.stringify(draft));}catch{}};
export const hasSalesDraft=()=>draft.items.length>0;
export function clearSalesDraft(){draft={sold_on:'',note:'',items:[],line_orders:[],excel_imports:[],pending:null};persist();}
const payload=()=>({sold_on:draft.sold_on,note:draft.note,items:draft.items.map(p=>({product_id:p.id,quantity:p.quantity})),line_orders:draft.line_orders});
const decimalUnit=unit=>['kg','g','斤','公斤','公克','台斤','兩'].includes(String(unit).toLowerCase());
const step=unit=>decimalUnit(unit)?'0.000001':'1';
// 數量用字串加減到小數 6 位，避免 0.1+0.2 這種浮點誤差。
const scaled=v=>Math.round(Number(v||0)*1e6);
const qtyText=n=>(n/1e6).toFixed(6).replace(/\.?0+$/,'')||'0';
const addQty=(a,b)=>qtyText(scaled(a)+scaled(b));

function syncDate(){
  const next=draftSoldOn(draft,S.meta.today);
  if(next!==draft.sold_on){draft.sold_on=next;draft.dated_on=S.meta.today;persist();}
}
const productsFor=day=>api('/daily-sales/products?'+new URLSearchParams({sold_on:day}));

export async function renderDailySales(seq,isCurrent){
  syncDate();
  let [catalog,history]=await Promise.all([productsFor(draft.sold_on),api('/daily-sales?page='+historyPage)]);
  if(!isCurrent())return;
  // 分頁開著過夜時，畫面上的「今天」會停在前一天；以伺服器的日期為準。
  if(catalog.today&&catalog.today!==S.meta.today){
    S.meta.today=catalog.today;$('#today').textContent=S.meta.today.replaceAll('-',' / ');
    const before=draft.sold_on;syncDate();
    if(draft.sold_on!==before){catalog=await productsFor(draft.sold_on);if(!isCurrent())return;}
  }
  products=catalog.items;historyPage=history.page;
  $('#main').innerHTML=`<div class="page-heading"><div><h1>每日銷售單</h1><p class="muted">把今天賣出的商品整理成一張單，確認後一次扣庫存。</p></div><span class="sales-stamp">先核對，再扣庫存</span></div>
    <div class="sales-layout"><section class="panel sales-picker"><div class="panel-head"><h2>01 選商品</h2><small>點選加入銷售單</small></div><div class="sales-filters"><input id="sales-search" type="search" aria-label="搜尋銷售商品" placeholder="搜尋品名或品號" value="${esc(query)}">${categoryButtons(products.map(p=>p.category),category,'sales-category')}</div><p class="sales-photo-note">照片供辨識商品，包裝入數可能不同；扣庫存以商品標示的單位為準。</p><div id="sales-products" class="sales-products"></div></section>
    <section class="panel sales-sheet"><div class="panel-head"><h2>02 填賣出數量</h2><span id="sales-count"></span></div><div class="sales-sheet-body"><div id="ls-strip" class="ls-strip"></div><div class="sales-date"><label>銷售日期<input id="sales-date" type="date" max="${S.meta.today}" value="${esc(draft.sold_on)}" ${draft.pending?'disabled':''}></label><p id="sales-date-note"></p></div><div id="sales-lines"></div><label>備註（選填）<textarea id="sales-note" maxlength="500" rows="2" placeholder="例如：晚班結帳彙總" ${draft.pending?'disabled':''}>${esc(draft.note)}</textarea></label><p class="sales-rule">依效期由近到遠扣庫存，已確認可售但效期未知的批次排最後。請填商品的庫存單位；任何一項不足，整張都不扣。</p><p class="error" id="sales-error" role="alert"></p><div class="sales-submit-actions"><button id="sales-export">匯出 Excel</button><button id="sales-preview" class="primary">檢查整張單 →</button></div><p class="draft-note">草稿保存在此分頁，切換頁面或重新整理仍會保留。</p></div></section></div>
    <section class="panel sales-history"><div class="panel-head"><h2>每日紀錄</h2><small>已送出的單可查看明細及沖銷</small></div><div class="sales-history-list">${history.items.map(h=>`<button class="sales-history-row" data-sheet="${h.id}"><span><strong>${esc(h.sold_on)}</strong><small>銷售單 #${h.id} · ${h.item_count} 項商品</small></span><span class="badge ${h.status==='posted'?'normal':''}">${h.status==='posted'?'已扣庫存':'已沖銷'}</span><span>查看 ›</span></button>`).join('')||'<p class="sales-empty">還沒有銷售單。完成今天的結帳後，從上方開始填寫。</p>'}</div>${pager(history,'sales-history-page')}</section>`;
  drawProducts();drawLines();drawDateNote();
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
    try{const data=await productsFor(chosen);draft.sold_on=chosen;draft.dated_on=S.meta.today;products=data.items;persist();drawProducts();drawLines();drawDateNote();}
    catch(error){e.target.value=old;toast(error.message);}finally{e.target.disabled=false;}
  };
  $('#sales-preview').onclick=preview;
  $('#sales-export').onclick=exportDraft;
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

function drawDateNote(){
  const note=$('#sales-date-note');if(!note)return;
  const past=draft.sold_on!==S.meta.today;
  note.className=past?'sales-date-warn':'muted';
  note.textContent=past?`銷售日期是 ${draft.sold_on}，不是今天。如果是今天賣出的，請改成今天。`:'可選過去日期補登';
}

function drawLines(){
  $('#sales-count').textContent=draft.items.length+' 項商品';
  $('#sales-lines').innerHTML=draft.items.map(p=>`<div class="sales-line"><div><strong>${esc(p.name)}</strong><small>${esc(p.code)} · 可扣 ${esc(products.find(x=>x.id===p.id)?.available??'待確認')} ${esc(p.unit)}</small>${p.line_qty?`<small class="ls-from-line">含匯入 ${esc(p.line_qty)} ${esc(p.unit)}</small>`:''}</div><label><span class="sales-sr">${esc(p.name)}賣出數量</span><input type="number" min="${decimalUnit(p.unit)?'0.000001':'1'}" max="999999999" step="${step(p.unit)}" data-sale-qty="${p.id}" value="${esc(p.quantity)}" ${draft.pending?'disabled':''}><span>${esc(p.unit)}</span></label><button class="text-button" data-remove-sale="${p.id}" aria-label="移除${esc(p.name)}" ${draft.pending?'disabled':''}>×</button></div>`).join('')||'<div class="sales-empty"><strong>今天賣出了什麼？</strong><p>先從商品清單加入，再填整天合計數量。</p></div>';
  $('#sales-preview').disabled=!draft.items.length;
  $('#sales-export').disabled=!draft.items.length||!!draft.pending||exporting;
  $('#sales-preview').textContent=draft.pending?'確認上次送出結果':'檢查整張單 →';
  document.querySelectorAll('[data-sale-qty]').forEach(el=>el.oninput=()=>{draft.items.find(p=>p.id===Number(el.dataset.saleQty)).quantity=el.value;persist();});
  document.querySelectorAll('[data-remove-sale]').forEach(b=>b.onclick=()=>{draft.items=draft.items.filter(p=>p.id!==Number(b.dataset.removeSale));persist();drawProducts();drawLines();});
  drawLineStrip();
}

// Excel previews stay local to this draft until the user confirms the sale.
function drawLineStrip(){
  const strip=$('#ls-strip');if(!strip)return;
  const taken=draft.excel_imports.length,off=draft.pending?'disabled':'';
  strip.innerHTML=`<div class="ls-strip-text"><strong>Excel 匯入</strong><span>${taken?`已帶入 ${taken} 份檔案`:'品號或商品＋數量，可另填單位'}</span></div>
    <div class="ls-strip-tools">${taken||draft.line_orders.length?`<button id="ls-undo" class="text-button" ${off}>取消帶入</button>`:''}<button id="ls-excel" class="text-button ls-excel" ${off}>上傳 Excel</button><input id="ls-file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden></div>`;
  $('#ls-excel').onclick=()=>$('#ls-file').click();
  $('#ls-file').onchange=e=>{const file=e.target.files[0];e.target.value='';if(file)uploadExcel(file);};
  if($('#ls-undo'))$('#ls-undo').onclick=undoLine;
}

async function uploadExcel(file){
  if(!/\.xlsx$/i.test(file.name)){toast('請選擇 .xlsx 格式的銷售明細');return;}
  const form=new FormData();form.append('file',file);form.append('sold_on',draft.sold_on);
  $('#ls-excel').disabled=true;
  try{
    const response=await fetch('/api/daily-sales/excel',{method:'POST',headers:{'X-CSRF-Token':S.csrf},body:form});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.error?.message||'讀取 Excel 失敗，請重試');
    reviewLine(data);
  }catch(e){toast(e.message);}finally{if($('#ls-excel'))$('#ls-excel').disabled=!!draft.pending;}
}

function undoLine(){
  if(!confirm('從草稿移除帶入的數量，保留另外手填的數量；不會更動庫存。確定？'))return;
  draft.items=draft.items.flatMap(p=>{
    if(!p.line_qty)return [p];
    const left=scaled(p.quantity)-scaled(p.line_qty);
    const {line_qty,...rest}=p;
    return left>0?[{...rest,quantity:qtyText(left)}]:[];
  });
  draft.line_orders=[];draft.excel_imports=[];persist();
  import('../app.js').then(m=>m.render());
}

const productOptions=selected=>{
  const groups={};
  for(const p of products)(groups[p.category||'其他']??=[]).push(p);
  return `<option value="">店內沒有，不扣庫存</option>`+Object.entries(groups).map(([c,list])=>`<optgroup label="${esc(c)}">${list.map(p=>`<option value="${p.id}" ${p.id===selected?'selected':''}>${esc(p.name)}（${esc(p.code)}）可扣 ${esc(p.available)} ${esc(p.unit)}</option>`).join('')}</optgroup>`).join('');
};

// 逐筆核對：每個品項要勾「✓」才會扣庫存；店內沒有的品項（生鮮等）預設不扣，也可以手動選商品。
function reviewLine(data){
  const orders=data.orders.filter(o=>!draft.excel_imports.includes(o.id));
  const already=data.orders.length-orders.length;
  const rows=[];
  for(const o of orders)o.items.forEach((item,index)=>rows.push({order:o.id,item,product:item.product?.id??null,qty:item.quantity??'',checked:false,picking:false}));
  const dropped=new Set();
  const skipped=data.skipped||[];
  if(!orders.length&&!skipped.length){toast(already?'這份 Excel 已經帶入這張單了':'沒有可帶入的銷售明細');return;}
  const productOf=r=>products.find(p=>p.id===r.product);
  const warn=r=>{
    const p=productOf(r),w=[];
    if(r.item.warning)w.push(r.item.warning);
    if(!p)return w;
    if(!r.qty||scaled(r.qty)<=0)w.push('請填數量');
    if(r.item.unit&&r.item.unit!==p.unit)w.push(`客人寫「${r.item.unit}」，庫存單位是「${p.unit}」，請換算後填數量`);
    if(r.qty&&scaled(r.qty)>scaled(p.available))w.push(`可扣庫存只有 ${p.available} ${p.unit}`);
    // 帶入是加總：草稿已有的商品再帶入會變多，例如把匯出的草稿再上傳。
    const line=draft.items.find(i=>i.id===p.id);
    if(line)w.push(`這張單已有 ${line.quantity} ${p.unit}，勾選後會加在一起`);
    return w;
  };
  const rowHtml=(r,k)=>{
    const p=productOf(r),i=r.item,w=warn(r);
    const said=`<strong>${esc(i.name)}</strong><span class="ls-said-qty">${i.quantity===null?'<b class="line-unknown">?</b>':esc(i.quantity)} ${esc(i.unit)}</span>${i.processing?`<em>${esc(i.processing)}</em>`:''}${i.note?`<small>${esc(i.note)}</small>`:''}`;
    const target=p||r.picking?`<select data-ls-product="${k}" aria-label="${esc(i.name)} 對應的店內商品">${productOptions(r.product)}</select>
        <label class="ls-qty"><span class="sales-sr">${esc(i.name)} 扣庫存數量</span><input type="number" data-ls-qty="${k}" min="0" step="${p?step(p.unit):'1'}" value="${esc(r.qty)}" ${p?'':'disabled'}><span>${p?esc(p.unit):''}</span></label>`
      :`<span class="ls-none">店內沒有，不扣庫存</span><button class="text-button ls-pick" data-ls-pick="${k}">選商品</button>`;
    return `<div class="ls-row${p?'':' muted'}${r.checked?' checked':''}" data-ls-row="${k}">
      <label class="ls-check"><input type="checkbox" data-ls-check="${k}" ${r.checked?'checked':''} ${p?'':'disabled'}><span class="sales-sr">確認扣 ${esc(i.name)}</span></label>
      <div class="ls-said">${said}</div><span class="ls-arrow" aria-hidden="true">→</span><div class="ls-target">${target}</div>
      ${w.length?`<p class="ls-warn">${w.map(esc).join('；')}</p>`:''}</div>`;
  };
  const orderHtml=o=>{
    const keys=rows.map((r,k)=>[r,k]).filter(([r])=>r.order===o.id);
    return `<section class="ls-order${dropped.has(o.id)?' dropped':''}" data-ls-order="${o.id}">
      <header><span class="ls-when">${esc(o.sent_on.slice(5).replace('-','/'))} <b>${esc(o.sent_at)}</b></span><strong>${esc(o.location||'（沒寫地點）')}</strong><small>${esc(o.customer)}</small>${o.action!=='新訂單'?`<span class="badge warning">${esc(o.action)}</span>`:''}${o.needs_review?'<span class="badge out">需確認</span>':''}
        <span class="ls-order-tools">${dropped.has(o.id)?`<button class="text-button" data-ls-keep="${o.id}">改回帶入</button>`:`${keys.some(([r])=>productOf(r))?`<button class="text-button" data-ls-all="${o.id}">勾選沒有提醒的品項</button>`:''}<button class="text-button" data-ls-drop="${o.id}">這筆先不帶入</button>`}</span></header>
      ${dropped.has(o.id)?'<p class="ls-note">這筆先不帶入，之後還可以再帶入。</p>':`
      ${o.needs_review?`<p class="ls-note warn">需確認：${esc(o.review_reason||'請核對原始留言')}</p>`:''}
      ${o.action==='修改'?'<p class="ls-note warn">這是修改單：請確認不要和原本那筆訂單重複扣。</p>':''}
      ${o.action==='取消'?'<p class="ls-note">取消單不扣庫存，帶入只是標記已處理。</p>':''}
      ${o.source.length?`<details class="ls-source"><summary>看來源明細</summary>${o.source.map(s=>`<p>${esc(s)}</p>`).join('')}</details>`:''}
      <div class="ls-rows">${keys.map(([r,k])=>rowHtml(r,k)).join('')||'<p class="ls-note">沒有品項</p>'}</div>`}</section>`;
  };
  const draw=()=>{
    const live=rows.filter(r=>!dropped.has(r.order)),deduct=live.filter(r=>productOf(r)),checked=deduct.filter(r=>r.checked);
    $('#ls-list').innerHTML=orders.map(orderHtml).join('')||'<p class="ls-note">沒有可以帶入的明細。</p>';
    $('#ls-total').innerHTML=`帶入 <b>${orders.length-dropped.size}</b> 份檔案 · 已勾 <b>${checked.length}</b>／${deduct.length} 項要扣庫存的品項`;
    $('#ls-apply').disabled=orders.length===dropped.size;
    bindRows();
  };
  const bindRows=()=>{
    document.querySelectorAll('[data-ls-check]').forEach(el=>el.onchange=()=>{
      const r=rows[el.dataset.lsCheck];S.dialogDirty=true;
      if(el.checked&&(!r.qty||scaled(r.qty)<=0)){el.checked=false;toast('請先填扣庫存的數量');document.querySelector(`[data-ls-qty="${el.dataset.lsCheck}"]`)?.focus();return;}
      r.checked=el.checked;draw();
    });
    document.querySelectorAll('[data-ls-product]').forEach(el=>el.onchange=()=>{
      const r=rows[el.dataset.lsProduct];S.dialogDirty=true;
      r.product=el.value?Number(el.value):null;r.checked=false;r.picking=!r.product?false:r.picking;draw();
      document.querySelector(`[data-ls-qty="${el.dataset.lsProduct}"]`)?.focus();
    });
    document.querySelectorAll('[data-ls-qty]').forEach(el=>{
      el.oninput=()=>{const r=rows[el.dataset.lsQty];r.qty=el.value;S.dialogDirty=true;if(r.checked&&(!r.qty||scaled(r.qty)<=0))r.checked=false;};
      el.onchange=()=>{const k=el.dataset.lsQty;draw();document.querySelector(`[data-ls-qty="${k}"]`)?.focus();};
    });
    document.querySelectorAll('[data-ls-pick]').forEach(b=>b.onclick=()=>{const k=b.dataset.lsPick;rows[k].picking=true;draw();document.querySelector(`[data-ls-product="${k}"]`)?.focus();});
    document.querySelectorAll('[data-ls-all]').forEach(b=>b.onclick=()=>{
      const id=b.dataset.lsAll,mine=rows.filter(r=>r.order===id&&productOf(r));S.dialogDirty=true;
      // 有提醒的品項（取消、重複、單位不同…）不一鍵勾選，要逐項看過再勾。
      mine.filter(r=>r.qty&&scaled(r.qty)>0&&!warn(r).length).forEach(r=>r.checked=true);draw();
      const left=mine.filter(r=>!r.checked).length;
      if(left)toast(`還有 ${left} 項有提醒或缺數量，請逐項確認後再勾選`);
    });
    document.querySelectorAll('[data-ls-drop]').forEach(b=>b.onclick=()=>{dropped.add(b.dataset.lsDrop);S.dialogDirty=true;draw();});
    document.querySelectorAll('[data-ls-keep]').forEach(b=>b.onclick=()=>{dropped.delete(b.dataset.lsKeep);draw();});
  };
  const kinds={open:'還沒按「已完成」',dismissed:'標成不是訂單',linked:'已扣過庫存',missing:'系統裡找不到',row:'列看不懂',cancel:'取消單'};
  const counts=Object.entries(skipped.reduce((c,x)=>({...c,[x.kind]:(c[x.kind]||0)+1}),{})).map(([k,n])=>`${n} 筆${kinds[k]||'其他'}`).join('、');
  const skippedHtml=skipped.length?`<details class="ls-skipped"><summary>略過 ${skipped.length} 筆：${esc(counts)}（看明細）</summary><ul>${skipped.map(s=>`<li><strong>${esc(s.label)}</strong>${esc(s.reason)}</li>`).join('')}</ul></details>`:'';
  dialog('核對 Excel 銷售明細',`<p class="notice">${esc(data.source)} · ${orders.length?`${orders.length} 份檔案。逐項核對：勾「✓」的品項才會加進這張銷售單；店內沒有的品項不扣庫存。`:'沒有可以帶入的品項，略過的原因列在下方。'}${already?`（另有 ${already} 筆已經帶入這張單）`:''}</p>
    ${skippedHtml}<div id="ls-list" class="ls-list"></div>
    <div class="ls-foot"><p id="ls-total"></p><div class="form-actions"><button data-action="close">取消</button><button id="ls-apply" class="primary">加入銷售單</button></div></div>`,'每日銷售單 · Excel 匯入');
  const box=$('#dialog');box.classList.add('ls-dialog');box.addEventListener('close',()=>box.classList.remove('ls-dialog'),{once:true});
  draw();
  $('#ls-apply').onclick=()=>{
    const live=rows.filter(r=>!dropped.has(r.order)),picked=live.filter(r=>productOf(r)&&r.checked),missed=live.filter(r=>productOf(r)&&!r.checked);
    if(!picked.length){toast('請至少勾選一項要帶入的商品');return;}
    if(picked.some(r=>!r.qty||scaled(r.qty)<=0)){toast('勾選的品項要填數量');return;}
    if(missed.length&&!confirm(`還有 ${missed.length} 項店內商品沒勾，這些不會扣庫存；確定只帶入已勾選的品項？`))return;
    const totals=new Map();
    for(const r of picked)totals.set(r.product,addQty(totals.get(r.product),r.qty));
    const added=[...totals.keys()].filter(id=>!draft.items.some(i=>i.id===id)).length;
    if(draft.items.length+added>200){toast('一張單最多 200 項商品');return;}
    for(const [id,qty] of totals){
      const line=draft.items.find(i=>i.id===id);
      if(line){line.quantity=addQty(line.quantity,qty);line.line_qty=addQty(line.line_qty,qty);}
      else draft.items.push({...products.find(p=>p.id===id),quantity:qty,line_qty:qty});
    }
    const ids=orders.filter(o=>!dropped.has(o.id)).map(o=>o.id);
    draft.excel_imports=[...draft.excel_imports,...ids];
    persist();closeDialog(true);drawProducts();drawLines();
    toast(`已帶入 ${ids.length} 份 Excel，加到 ${totals.size} 項商品。核對後按「檢查整張單」`);
  };
}

let exporting=false;
async function downloadExcel(path,body,filename){
  const response=await fetch('/api'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':S.csrf},body:JSON.stringify(body)});
  if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error?.message||'匯出失敗，請重試');}
  const url=URL.createObjectURL(await response.blob());
  const link=document.createElement('a');link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),60000);
}
async function exportDraft(){
  if(exporting||draft.pending)return;
  for(const input of document.querySelectorAll('[data-sale-qty]'))if(!input.value||!input.reportValidity()){input.focus();return;}
  const body=payload(),button=$('#sales-export');exporting=true;button.disabled=true;
  try{await downloadExcel('/daily-sales/export',body,`每日銷售_${body.sold_on}_草稿.xlsx`);toast('已匯出 Excel 草稿，庫存尚未扣除');}
  catch(error){toast(error.message);}
  finally{exporting=false;if($('#sales-export'))$('#sales-export').disabled=!draft.items.length||!!draft.pending;}
}

async function preview(){
  if(draft.pending){await submit();return;}
  for(const input of document.querySelectorAll('[data-sale-qty]'))if(!input.value||!input.reportValidity()){input.focus();return;}
  $('#sales-preview').disabled=true;$('#sales-error').textContent='';S.savingSales=true;
  try{
    const body=payload(),plan=await api('/daily-sales/preview',body);
    const warnings=plan.warnings||[];
    const warningHtml=warnings.length?`<div class="notice sales-warnings" role="alert"><strong>送出前請確認 ${warnings.length} 項提醒</strong><ul>${warnings.map(w=>`<li>${esc(w.message)}</li>`).join('')}</ul><label class="check-label"><input type="checkbox" id="sales-warnings-ok">我已看過以上提醒，數量正確，要扣庫存</label></div>`:'';
    dialog('確認這張銷售單',`<p class="notice">${esc(plan.sold_on)}${plan.sold_on!==S.meta.today?' <b>（補登，不是今天）</b>':''} · ${plan.items.length} 項商品。確認後立即扣庫存。${plan.line_orders.length?`<br>含 LINE 訂單 ${plan.line_orders.length} 筆，送出後標成已扣庫存，不會再被帶入。`:''}</p>${warningHtml}<div class="sales-review">${plan.items.map(p=>`<div><strong>${esc(p.name)}</strong><p>賣出 <b>${esc(p.quantity)} ${esc(p.unit)}</b> · 可扣庫存 ${esc(p.available)} → ${esc(p.remaining)}</p><small>${p.allocations.map(a=>`批次 #${a.batch_id}（${esc(a.expires_on||'效期未知／已確認可售')}${a.later?'，之後進貨':''}）扣 ${esc(a.quantity)}`).join('、')}</small></div>`).join('')}</div><p class="error" id="sales-submit-error" role="alert"></p><div class="form-actions"><button data-action="close">返回修改</button><button id="sales-confirm" class="primary" ${warnings.length?'disabled':''}>確認扣庫存</button></div>`,'每日結帳 · 最後確認');
    // 有提醒時要先勾選確認；勾選本身不算未儲存的修改。
    if(warnings.length)$('#sales-warnings-ok').onchange=e=>{S.dialogDirty=false;$('#sales-confirm').disabled=!e.target.checked;};
    $('#sales-confirm').onclick=async()=>{draft.pending={...body,revision:plan.revision,request_id:crypto.randomUUID(),...(warnings.length?{confirm_warnings:true}:{})};persist();await submit();};
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
  const line=sheet.line_orders.length?`<p class="muted">含 LINE 訂單 ${sheet.line_orders.length} 筆：${sheet.line_orders.map(o=>esc(o.location||o.customer)).join('、')}${sheet.status==='void'?'（已沖銷，可重新帶入）':''}</p>`:'';
  dialog(`銷售單 #${sheet.id}`,`<div class="sales-detail-tools"><p class="notice">${esc(sheet.sold_on)} · ${sheet.status==='posted'?'已扣庫存':'已沖銷，庫存已加回'}</p><button id="sales-export-sheet">匯出 Excel</button></div><div class="sales-review">${sheet.items.map(p=>`<div><strong>${esc(p.name)}</strong><p>${esc(p.quantity)} ${esc(p.unit)}</p><small>${p.allocations.map(a=>`批次 #${a.batch_id}：${esc(a.before_value)} → ${esc(a.after_value)}`).join('、')}</small></div>`).join('')}</div>${line}<p>${esc(sheet.note||'無備註')}</p><p class="muted">建立時間：${esc(sheet.created_at.slice(0,16).replace('T',' '))}</p>${sheet.status==='void'?`<p>沖銷原因：${esc(sheet.void_reason)}</p>`:`<p class="muted">填錯可沖銷整張後重填。已有後續盤點的批次，需從盤點更正。${sheet.line_orders.length?'沖銷後，這張單帶入的 LINE 訂單可以重新帶入。':''}</p><button id="sales-void" class="danger">沖銷整張單並加回庫存</button>`}<p id="sales-void-error" class="error" role="alert"></p>`,'每日銷售紀錄');
  $('#sales-export-sheet').onclick=async e=>{
    const button=e.currentTarget;button.disabled=true;
    try{await downloadExcel(`/daily-sales/${sheet.id}/excel`,undefined,`每日銷售_${sheet.sold_on}_${sheet.id}_${sheet.status==='posted'?'已扣庫存':'已沖銷'}.xlsx`);}
    catch(error){toast(error.message);}finally{button.disabled=false;}
  };
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
