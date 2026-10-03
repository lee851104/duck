import {S,$,api,esc,dialog,closeDialog,toast,pager,money,formSubmit} from '../app.js';

const importStates={baseline:'已記住位置',empty:'沒有客人留言',pending:'等待轉換',converting:'轉換中',done:'已轉成訂單',failed:'轉換失敗'};
const statusNames={open:'待處理',done:'已完成',dismissed:'不是訂單'};
const ranges=[['all','全部'],['today','今天'],['yesterday','昨天']];
// 排序（新到舊／舊到新）記在這台電腦，下次打開照舊。
const sortKey='duck-line-sort';
const savedSort=()=>{try{return localStorage.getItem(sortKey)==='old'?'old':'new';}catch{return 'new';}};
let filter={status:'open',range:'all',from:'',to:'',page:1,sort:savedSort()},busy=false,notice=null;
// 目前選到的訂單：重新整理後先找同一筆，找不到（例如剛標完成）就選同位置的下一筆。
let pick={id:null,index:0},current=null;

const shortDate=d=>d?d.slice(5).replace('-','/'):'';
const stamp=iso=>iso?`${shortDate(iso.slice(0,10))} ${iso.slice(11,16)}`:'';
const quantity=i=>i.quantity===null?'<span class="line-unknown">?</span>':esc(i.quantity);
const day=offset=>{const d=new Date(S.meta.today+'T00:00:00Z');d.setUTCDate(d.getUTCDate()+offset);return d.toISOString().slice(0,10);};
const pages=d=>Math.max(1,Math.ceil(d.total/d.page_size));
const weekday=d=>'日一二三四五六'[new Date(d+'T00:00:00Z').getUTCDay()];
const dayTag=d=>d===day(0)?'今天':d===day(-1)?'昨天':'';
async function rerender(){const {render}=await import('../app.js');await render();}

// 時間範圍同時決定清單、商品合計和匯出的 Excel。
function period(){
  if(filter.range==='today')return {from:day(0)+'T00:00',to:day(0)+'T23:59'};
  if(filter.range==='yesterday')return {from:day(-1)+'T00:00',to:day(-1)+'T23:59'};
  if(filter.range==='custom')return {from:filter.from,to:filter.to};
  return {};
}
function rangeLabel(){
  if(filter.range==='today')return `今天 ${shortDate(day(0))}`;
  if(filter.range==='yesterday')return `昨天 ${shortDate(day(-1))}`;
  if(filter.range==='custom')return `${shortDate(filter.from.slice(0,10))} ${filter.from.slice(11)} ～ ${shortDate(filter.to.slice(0,10))} ${filter.to.slice(11)}`;
  return '全部時間';
}

async function upload(file,start){
  const form=new FormData();form.append('file',file);if(start)form.append('start',start);
  const response=await fetch('/api/line-orders/import',{method:'POST',headers:{'X-CSRF-Token':S.csrf},body:form});
  const data=await response.json().catch(()=>({}));
  if(!response.ok){const e=new Error(data.error?.message||'匯入失敗，請重試');e.code=data.error?.code;e.fields=data.error?.fields||{};e.status=response.status;throw e;}
  return data;
}

// 匯入中把標題下那行小字換成進度，不另外多佔一行。
function setBusy(on,text){
  const progress=$('#line-progress'),meta=$('#line-meta');
  if(progress){progress.hidden=!on;progress.textContent=text||'';}
  if(meta)meta.hidden=on;
  document.querySelectorAll('#line-pick,#line-file,#line-pick-empty').forEach(el=>el.disabled=on);
}

async function importFile(file,start=''){
  if(busy)return;
  if(!/\.txt$/i.test(file.name)){toast('請選擇 LINE「儲存聊天」匯出的 .txt 檔');return;}
  busy=true;notice=null;
  setBusy(true,`正在匯入「${file.name}」，交給 AI 轉成訂單，約需 10–60 秒…`);
  try{
    const r=await upload(file,start);
    if(!r.import_id)notice={kind:'info',text:`沒有新留言（最後一則 ${shortDate(r.last_on)} ${r.last_at}）`};
    else if(r.status==='baseline')notice={kind:'info',text:`已記住位置（最後一則 ${shortDate(r.last_on)} ${r.last_at}），之後只會加入新留言`};
    else if(r.convert_error)notice={kind:'error',text:`新留言 ${r.new_messages} 則已保存，但還沒轉成訂單：${r.convert_error}`};
    else notice={kind:'ok',text:r.orders_created?`✓ 新增 ${r.orders_created} 筆訂單，標有「新」`:`新留言 ${r.new_messages} 則，沒有新的訂單`};
    filter={...filter,status:'open',range:'all',page:1};pick={id:null,index:0};
  }catch(e){
    if(e.code==='line_first_import'||e.code==='line_position_lost'){
      setBusy(false);busy=false;askStart(file,e);return;
    }
    notice={kind:'error',text:e.message};
  }finally{busy=false;}
  await rerender();
}

function askStart(file,error){
  const f=error.fields,lost=error.code==='line_position_lost';
  const previous=lost?`${f.previous_on}T${f.previous_at}`:`${f.last_on}T00:00`;
  dialog(lost?'找不到上次匯入的位置':`第一次匯入「${f.chat}」`,`<p class="notice">${esc(error.message)}</p>
    <p class="line-dialog-copy">這份聊天紀錄共 ${Number(f.message_count).toLocaleString('zh-TW')} 則，最後一則是 ${esc(shortDate(f.last_on))} ${esc(f.last_at)}。</p>
    <fieldset class="line-start"><legend>從什麼時候開始接單？</legend>
      ${lost?'':`<label><input type="radio" name="line-start" value="day" checked>從 ${esc(shortDate(f.last_on))} 00:00 開始（最後一天的留言）</label>`}
      <label><input type="radio" name="line-start" value="custom" ${lost?'checked':''}>從指定時間開始<input id="line-since" type="datetime-local" value="${esc(previous)}"></label>
      <label><input type="radio" name="line-start" value="baseline">先不轉換，只記住目前位置</label>
    </fieldset>
    <p class="muted">${lost?'已經匯入過的留言會自動略過，不會重複建立訂單。':'之後每次匯入，只會加入這次之後的新留言。'}</p>
    <p id="line-start-error" class="error" role="alert"></p>
    <div class="form-actions"><button data-action="close">取消</button><button id="line-start-go" class="primary">開始匯入</button></div>`,'LINE 接單 · 設定開始時間');
  $('#line-since').onfocus=()=>{document.querySelector('[name="line-start"][value="custom"]').checked=true;};
  $('#line-start-go').onclick=()=>{
    const choice=document.querySelector('[name="line-start"]:checked').value;
    const start=choice==='baseline'?'baseline':choice==='day'?`${f.last_on}T00:00`:$('#line-since').value;
    if(!start){$('#line-start-error').textContent='請選擇開始時間';return;}
    closeDialog(true);importFile(file,start);
  };
}

// 一個品項一行：數量｜客人要的品項（處理方式、備註）｜單價。對到店內商品時，下一行小字列出商品與庫存。
function item(i){
  // 有對到店內商品就用店內售價和店內單位，否則用菜單上的單價。
  const p=i.product,[price,per]=p?.price?[p.price,p.unit]:[i.unit_price,i.unit];
  const stock=p?`<small class="line-stock">店內商品：${esc(p.name)}（${esc(p.code)}）· 庫存 ${p.quantity===null?'未盤點':esc(p.quantity)+' '+esc(p.unit)}</small>`:'';
  return `<li class="${p?'linked':''}"><span class="line-qty">${quantity(i)}<small>${esc(i.unit)}</small></span><span class="line-item"><strong>${esc(i.name)}</strong>${i.processing?`<em>${esc(i.processing)}</em>`:''}${i.note?`<span class="line-item-note">${esc(i.note)}</span>`:''}${stock}</span><span class="line-price">${price?money(price)+(per?'／'+esc(per):''):''}</span></li>`;
}

// 原文照 LINE 的樣子顯示：時間另列，保留換行，連續空行縮成一行。
function bubble(m){
  const [first,...rest]=m.raw.split('\n');
  const text=[first.replace(/^\d{2}:\d{2} /,''),...rest].join('\n').replace(/\n{3,}/g,'\n\n');
  return `<div class="line-bubble"><time>${shortDate(m.sent_on)} ${esc(m.sent_at)}</time><p>${esc(text)}</p></div>`;
}

function tags(o){
  const fresh=o.is_new&&o.status==='open';
  return `${fresh?'<span class="line-new">新</span>':''}${o.action!=='新訂單'?`<span class="badge warning">${esc(o.action)}</span>`:''}${o.needs_review?'<span class="badge out">需確認</span>':''}${o.sale_id?`<span class="badge normal" title="已帶入每日銷售單 #${o.sale_id}">已扣庫存</span>`:''}`;
}

// 中間：一次只看一筆，左右對照「客人原文」和「AI 整理的訂單」，按鈕固定在底部。
function detail(o){
  if(!o){
    const first=!current.total&&filter.status==='open'&&filter.range==='all';
    return `<div class="line-detail-empty">${first?`<span class="line-drop-icon" aria-hidden="true">⇪</span><strong>把 LINE 聊天檔拖到這裡</strong><p>檔名像「[LINE]菜騎鴨-….txt」，AI 會把新留言整理成訂單。</p><button id="line-pick-empty" class="primary">選擇檔案</button>`
      :`<strong>${filter.status==='open'?'沒有待處理的訂單':'這裡沒有訂單'}</strong><p>${filter.range!=='all'?'換個時間看看，或按「全部」。':{open:'匯入新的 LINE 聊天檔，新訂單就會出現在左邊。',done:'按「✓ 已完成」的訂單會放在這裡。',dismissed:'按「不是訂單」的留言會放在這裡。'}[filter.status]}</p>`}</div>`;
  }
  const at=current.items.indexOf(o),position=(current.page-1)*current.page_size+at+1;
  const meta=[['載具',o.carrier],['付款',o.payment],['備註',o.note]].filter(([,v])=>v).map(([k,v])=>`<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join('');
  const version=`data-id="${o.id}" data-version="${o.version}"`;
  const actions=o.status==='open'
    ?`<button class="primary line-done" data-line-status="done" ${version}>✓ 已完成</button><button data-line-status="dismissed" ${version}>不是訂單</button>`
    :o.sale_id?`<button class="line-done" disabled title="要修改請先到每日銷售單沖銷那張單">已扣庫存 · 每日銷售單 #${o.sale_id}</button>`
    :`<button class="primary line-done" data-line-status="open" ${version}>${o.status==='done'?'改回待處理':'改回訂單'}</button>${o.status==='done'?'<span class="line-hint">還沒扣庫存：到「每日銷售單」按「從 LINE 接單帶入」</span>':''}`;
  return `<article class="line-order ${o.status}${o.needs_review?' review':''}${o.is_new&&o.status==='open'?' fresh':''}" aria-label="${esc(o.location||'訂單')}">
    <header><span class="line-when">${shortDate(o.sent_on)} <strong>${esc(o.sent_at)}</strong></span><div class="line-who"><strong>${esc(o.location||'（沒寫地點）')}</strong><small>${esc(o.customer)}</small></div><div class="line-tags">${tags(o)}${o.sale_id?'':'<button class="line-edit" data-line-edit title="修改地點、品項、數量等">✎ 編輯</button>'}</div></header>
    ${o.needs_review?`<p class="line-review"><span>需確認：${esc(o.review_reason||'請核對原始留言')}</span>${o.sale_id?'':'<button class="line-edit" data-line-edit>✎ 編輯修正</button>'}</p>`:''}
    <div class="line-compare">
      <section class="line-raw" aria-label="客人在 LINE 的原文"><h3 class="line-col-title">客人原文<small>LINE</small></h3>
        <div class="line-scroll">${o.source.map(bubble).join('')||'<p class="line-empty-items">找不到原始留言</p>'}</div></section>
      <section class="line-parsed" aria-label="AI 整理後的訂單"><h3 class="line-col-title">${o.edited_at?`訂單內容<small class="line-edited">已手動修改 ${stamp(o.edited_at)}</small><small>${o.items.length} 項</small>`:`AI 整理的訂單<small>${o.items.length} 項</small>`}</h3>
        <div class="line-scroll"><ul class="line-items">${o.items.map(item).join('')||'<li class="line-empty-items">沒有辨識出品項，請看左邊原文</li>'}</ul>
        ${meta?`<dl class="line-meta">${meta}</dl>`:''}</div></section>
    </div>
    <footer class="line-actions">${actions}<span class="line-step" title="鍵盤 ↑ ↓ 也可以切換"><button data-line-step="-1" aria-label="上一筆" ${position<=1?'disabled':''}>‹</button><span>${position} / ${current.total}</span><button data-line-step="1" aria-label="下一筆" ${position>=current.total?'disabled':''}>›</button></span></footer>
  </article>`;
}

// 清單每筆兩行：地點＋標記＋客人／要的品項。
function row(o,active){
  const names=o.items.map(i=>i.name);
  const preview=names.slice(0,3).join('、')+(names.length>3?` 等 ${names.length} 項`:'');
  return `<button class="line-row${o.is_new&&o.status==='open'?' fresh':''}${o.needs_review?' review':''}" data-line-pick="${o.id}" aria-current="${active}">
    <span class="line-row-time">${shortDate(o.sent_on)}<strong>${esc(o.sent_at)}</strong></span>
    <span class="line-row-main"><span class="line-row-top"><strong>${esc(o.location||'（沒寫地點）')}</strong>${tags(o)}<small>${esc(o.customer)}</small></span><span class="line-row-items">${esc(preview)||'沒有辨識出品項'}</span></span></button>`;
}

// 左邊清單：待處理時，這次匯入新增的在最上面，之前還沒處理的在下面。
// 左邊清單：依留言時間排（新到舊或舊到新），每天一個標題，捲動時標題停在上方。
function orderList(data,chosen){
  if(!data.items.length)return `<p class="line-list-empty">${filter.status==='open'?'沒有待處理的訂單':'這裡沒有訂單'}</p>`;
  const perDay={};
  for(const o of data.items)perDay[o.sent_on]=(perDay[o.sent_on]||0)+1;
  let html='',section=null;
  for(const o of data.items){
    if(o.sent_on!==section){
      section=o.sent_on;const tag=dayTag(section);
      html+=`<h2 class="line-group${tag==='今天'?' today':''}"><strong>${esc(shortDate(section))} 週${weekday(section)}</strong>${tag?`<em>${tag}</em>`:''}<span>${perDay[section]} 筆</span></h2>`;
    }
    html+=row(o,o===chosen);
  }
  return html;
}

function summaryList(data){
  if(data.summary===null)return '<p class="line-side-empty">選「今天」或其他時間，這裡就會加總。</p>';
  const rows=data.summary.map(g=>`<li><span>${esc(g.name)}${g.product_id?'<small>店內商品</small>':''}</span><strong>${g.total!=='0'||!g.unknown?esc(g.total)+' '+esc(g.unit):''}${g.unknown?`<small>${g.unknown} 筆沒寫數量</small>`:''}${g.review?`<small>${g.review} 筆需確認</small>`:''}</strong><small>${g.orders} 筆</small></li>`).join('');
  return rows?`<ul class="line-summary">${rows}</ul>`:'<p class="line-side-empty">沒有可加總的品項</p>';
}
const summaryInfo=()=>`${statusNames[filter.status]} · ${esc(rangeLabel())}`;

const messageList=(title,items)=>items.length?`<h3>${title}</h3><ul class="line-messages">${items.map(m=>`<li><time>${shortDate(m.sent_on)} ${esc(m.sent_at)}</time>${esc(m.raw.split('\n')[0].replace(/^\d{2}:\d{2} /,''))}</li>`).join('')}</ul>`:'';

// 標題下一行小字：剛匯入的結果，或最近一次匯入；再加上匯入紀錄、說明。
function metaLine(data){
  const latest=data.latest,ai=data.ai;
  const extra=latest?[[latest.not_orders.length,'則留言沒轉成訂單'],[latest.images.length,'張圖片'],[latest.recalls.length,'則收回']].filter(([n])=>n).map(([n,t])=>n+' '+t).join('、'):'';
  const status=notice&&notice.kind!=='error'?`<span class="line-result ${notice.kind}" role="status">${esc(notice.text)}<button class="line-notice-close" aria-label="關閉提示">×</button></span>`
    :latest?`<span>最近匯入 ${stamp(latest.created_at)}${filter.status!=='open'?'':data.new_count?`，<b class="line-new-count">新增 ${data.new_count} 筆</b>（標「新」）`:'，沒有新訂單'}</span>`:'<span>還沒有匯入過</span>';
  return `<div id="line-meta" class="line-meta-line">${status}${extra?`<button class="text-button line-link attention" data-line-import="${latest.id}">${extra} ›</button>`:''}${data.imports.length?'<button id="line-history" class="text-button line-link">匯入紀錄</button>':''}
      <details class="line-help"><summary>說明</summary><div class="line-help-pop">
        <p><strong>怎麼從 LINE 存聊天？</strong>電腦版 LINE 打開「菜騎鴨」群組 → 右上角選單（≡ 或 ⋮）→「儲存聊天」→ 存成文字檔。每次存同一個位置、覆蓋舊檔就好。</p>
        <p>也可以直接把 .txt 檔拖到這個畫面任何地方。鍵盤 ↑ ↓ 可以切換訂單。</p>
        <p class="line-help-ai">${ai.configured?'<span class="badge normal">OpenAI 已連接</span>':'<span class="badge warning">尚未連接 OpenAI</span>'}<button id="line-check-key" class="text-button line-link">測試連線</button></p></div></details></div>
    <p id="line-progress" class="line-progress" role="status" hidden></p>`;
}

// 需要老闆處理的狀況才出現橫條：沒接上 AI、上次轉換失敗、匯入出錯。
function alerts(data){
  const ai=data.ai,latest=data.latest;let html='';
  if(!ai.configured)html+=`<div class="line-alert warn"><strong>尚未連接 OpenAI</strong><span>${ai.cloud?`請在 ${esc(ai.key_location)} 設定金鑰。`:`用記事本把金鑰存成：<code>${esc(ai.key_location)}</code>`}</span></div>`;
  if(latest&&['pending','failed'].includes(latest.status))html+=`<div class="line-alert error"><span>上次匯入的新留言還沒轉成訂單。</span><button id="line-retry" data-id="${latest.id}" class="primary">重新轉換</button></div>`;
  if(notice?.kind==='error')html+=`<div class="line-alert error" role="alert"><span>${esc(notice.text)}</span><button class="line-notice-close" aria-label="關閉提示">×</button></div>`;
  return html;
}

// 標題列右邊：時間範圍（套用到清單、合計、匯出）、商品合計、匯出、匯入。自訂時間用小視窗，不多佔一行。
function topTools(data){
  const c=data.counts,total=c.open+c.done,custom=filter.range==='custom';
  const from=filter.from||day(0)+'T00:00',to=filter.to||day(0)+'T23:59';
  return `<div class="line-tools">
    <div class="line-range-wrap"><div class="line-ranges" role="group" aria-label="時間">${ranges.map(([r,l])=>`<button data-line-range="${r}" aria-pressed="${filter.range===r}">${l}</button>`).join('')}<button id="line-custom-open" aria-pressed="${custom}" aria-expanded="false">${custom?esc(rangeLabel()):'自訂'}</button></div>
      <div id="line-custom" class="line-custom" hidden><label>開始<input id="line-from" type="datetime-local" value="${esc(from)}"></label><label>結束<input id="line-to" type="datetime-local" value="${esc(to)}"></label><div class="line-custom-actions"><button id="line-custom-cancel">取消</button><button id="line-apply" class="primary">套用</button></div></div></div>
    <button id="line-summary" class="line-summary-button">商品合計</button>
    <button id="line-export" class="line-export" ${total?'':'disabled'} title="${total?`匯出${esc(rangeLabel())}的 ${total} 筆訂單：商品數量合計、每筆訂單和 LINE 原文`:'這段時間沒有訂單可以匯出'}">⬇ 匯出 Excel</button>
    <button id="line-pick" class="primary line-pick"><span aria-hidden="true">⇪</span>匯入<span class="line-pick-extra"> LINE </span>聊天檔</button><input id="line-file" type="file" accept=".txt,text/plain" hidden>
  </div>`;
}

export async function renderLineOrders(seq,isCurrent){
  const data=await api('/line-orders?'+new URLSearchParams({status:filter.status,page:filter.page,sort:filter.sort,...period()}));
  if(!isCurrent())return;
  filter.page=data.page;current=data;
  const chosen=data.items.find(o=>o.id===pick.id)||data.items[Math.min(pick.index,data.items.length-1)]||null;
  pick={id:chosen?.id??null,index:Math.max(0,data.items.indexOf(chosen))};
  const c=data.counts;
  $('#main').innerHTML=`<div class="line-page">
    <div class="line-heading"><div class="line-title"><h1>LINE 接單</h1>${metaLine(data)}</div>${topTools(data)}</div>
    ${alerts(data)}
    <div class="line-work">
      <nav class="panel line-list" aria-label="訂單清單">
        <div class="line-tabs" role="group" aria-label="訂單狀態">${Object.entries(statusNames).map(([s,l])=>`<button data-line-tab="${s}" aria-pressed="${filter.status===s}">${l}<span>${c[s]}</span></button>`).join('')}</div>
        <div class="line-list-head"><span>依留言時間</span><div class="line-sort" role="group" aria-label="排序">${[['new','新到舊'],['old','舊到新']].map(([v,l])=>`<button data-line-sort="${v}" aria-pressed="${filter.sort===v}">${l}</button>`).join('')}</div></div>
        <div class="line-list-scroll">${orderList(data,chosen)}</div>${data.total>data.page_size?pager(data,'line-page'):''}</nav>
      <section id="line-detail" class="line-detail" aria-live="polite">${detail(chosen)}</section>
      <aside class="panel line-summary-col" aria-label="商品數量合計"><div class="panel-head"><h2>商品合計</h2><small>${summaryInfo()}</small></div><div class="line-summary-scroll">${summaryList(data)}</div></aside>
    </div>
    <div id="line-dropzone" class="line-dropzone" hidden><div><span aria-hidden="true">⇪</span><strong>放開滑鼠，匯入 LINE 聊天檔</strong></div></div>
  </div>`;
  bind();
  document.querySelector('[data-line-pick][aria-current="true"]')?.scrollIntoView({block:'nearest'});
}

function select(o){
  pick={id:o.id,index:current.items.indexOf(o)};
  document.querySelectorAll('[data-line-pick]').forEach(b=>b.setAttribute('aria-current',String(Number(b.dataset.linePick)===o.id)));
  $('#line-detail').innerHTML=detail(o);
  bindDetail();
  document.querySelector(`[data-line-pick="${o.id}"]`)?.scrollIntoView({block:'nearest'});
  // 手機上清單在上、明細在下，點了就捲到明細。
  if(matchMedia('(max-width:900px)').matches)$('#line-detail').scrollIntoView({block:'start',behavior:'smooth'});
}

async function step(delta){
  if(!current?.items.length)return;
  const next=pick.index+delta;
  if(next>=0&&next<current.items.length){select(current.items[next]);return;}
  const page=current.page+delta;
  if(page<1||page>pages(current))return;
  filter.page=page;pick={id:null,index:delta>0?0:current.page_size};await rerender();
}

function customPanel(open){
  const panel=$('#line-custom');if(!panel)return;
  panel.hidden=!open;$('#line-custom-open').setAttribute('aria-expanded',String(open));
  if(open)$('#line-from').focus();
}

function bind(){
  const pickFile=()=>$('#line-file').click();
  $('#line-pick').onclick=pickFile;
  if($('#line-pick-empty'))$('#line-pick-empty').onclick=pickFile;
  $('#line-file').onchange=e=>{const file=e.target.files[0];e.target.value='';if(file)importFile(file);};
  document.querySelectorAll('[data-line-range]').forEach(b=>b.onclick=async()=>{filter={...filter,range:b.dataset.lineRange,page:1};pick={id:null,index:0};notice=null;await rerender();});
  $('#line-custom-open').onclick=()=>customPanel($('#line-custom').hidden);
  $('#line-custom-cancel').onclick=()=>customPanel(false);
  $('#line-apply').onclick=async()=>{
    const from=$('#line-from').value,to=$('#line-to').value;
    if(!from||!to||from>to){toast('請選開始和結束時間，結束要晚於開始');return;}
    filter={...filter,range:'custom',from,to,page:1};pick={id:null,index:0};notice=null;await rerender();
  };
  $('#line-export').onclick=e=>exportExcel(e.currentTarget);
  $('#line-summary').onclick=showSummary;
  document.querySelectorAll('[data-line-sort]').forEach(b=>b.onclick=async()=>{
    if(filter.sort===b.dataset.lineSort)return;
    filter={...filter,sort:b.dataset.lineSort,page:1};
    try{localStorage.setItem(sortKey,filter.sort);}catch{}
    await rerender();
  });
  document.querySelectorAll('[data-line-tab]').forEach(b=>b.onclick=async()=>{filter={...filter,status:b.dataset.lineTab,page:1};pick={id:null,index:0};notice=null;await rerender();});
  document.querySelectorAll('[data-action="line-page"]').forEach(b=>b.onclick=async()=>{filter.page=Number(b.dataset.page);pick={id:null,index:0};await rerender();});
  document.querySelectorAll('[data-line-pick]').forEach(b=>b.onclick=()=>{const o=current.items.find(x=>x.id===Number(b.dataset.linePick));if(o)select(o);});
  document.querySelectorAll('[data-line-import]').forEach(b=>b.onclick=()=>showImport(b.dataset.lineImport).catch(e=>toast(e.message)));
  if($('#line-history'))$('#line-history').onclick=showHistory;
  $('#line-check-key').onclick=async e=>{e.target.disabled=true;try{await api('/line-orders/check-key',{});toast('OpenAI 連線成功');}catch(error){toast(error.message);}finally{e.target.disabled=false;}};
  if($('#line-retry'))$('#line-retry').onclick=e=>retry(e.target.dataset.id,e.target);
  document.querySelectorAll('.line-notice-close').forEach(b=>b.onclick=async()=>{notice=null;await rerender();});
  bindDetail();
}

function bindDetail(){
  document.querySelectorAll('[data-line-step]').forEach(b=>b.onclick=()=>step(Number(b.dataset.lineStep)));
  document.querySelectorAll('[data-line-edit]').forEach(b=>b.onclick=()=>{const o=current.items.find(x=>x.id===pick.id);if(o)editOrder(o).catch(e=>toast(e.message));});
  document.querySelectorAll('[data-line-status]').forEach(b=>b.onclick=async()=>{
    b.disabled=true;
    try{await api('/line-orders/'+b.dataset.id,{status:b.dataset.lineStatus,version:Number(b.dataset.version)},'PATCH');
      toast({done:'已標記完成',dismissed:'已移到「不是訂單」',open:'已改回待處理'}[b.dataset.lineStatus]);
      pick={id:null,index:pick.index};await rerender();}
    catch(e){toast(e.message);if(e.status===409)await rerender();else b.disabled=false;}
  });
}

// 修改訂單：左邊固定顯示 LINE 原文，右邊改地點、客人、類型、每個品項和載具付款備註；整筆一起儲存。
const actionNames=['新訂單','追加','修改','取消'];
let productCache=null;
async function editOrder(o){
  productCache??=(await api('/line-orders/products')).items;
  const groups={};
  for(const p of productCache)(groups[p.category||'其他']??=[]).push(p);
  const options=selected=>'<option value="">（不對應店內商品）</option>'+Object.entries(groups).map(([c,list])=>`<optgroup label="${esc(c)}">${list.map(p=>`<option value="${p.id}" ${p.id===selected?'selected':''}>${esc(p.name)}（${esc(p.code)}）· ${esc(p.unit)}</option>`).join('')}</optgroup>`).join('');
  const blank={name:'',quantity:'',unit:'',processing:'',note:'',product_id:null,unit_price:null};
  const items=o.items.map(i=>({name:i.name,quantity:i.quantity??'',unit:i.unit,processing:i.processing,note:i.note,product_id:i.product_id??null,unit_price:i.unit_price??null}));
  const itemHtml=(i,k)=>`<div class="le-item" data-le-item="${k}">
      <div class="le-item-main"><input data-le-field="quantity" type="number" min="0" step="any" inputmode="decimal" placeholder="?" aria-label="第 ${k+1} 項數量（空白＝沒寫）" value="${esc(i.quantity)}"><input data-le-field="unit" maxlength="20" placeholder="單位" aria-label="第 ${k+1} 項單位" value="${esc(i.unit)}"><input data-le-field="name" maxlength="100" placeholder="品名" aria-label="第 ${k+1} 項品名" value="${esc(i.name)}"><button type="button" class="text-button le-remove" data-le-remove="${k}" aria-label="刪除第 ${k+1} 項">×</button></div>
      <div class="le-item-more"><label><span>處理</span><input data-le-field="processing" maxlength="100" placeholder="切、去皮…" value="${esc(i.processing)}"></label><label><span>備註</span><input data-le-field="note" maxlength="200" value="${esc(i.note)}"></label><label><span>店內</span><select data-le-field="product_id" aria-label="第 ${k+1} 項對應的店內商品">${options(i.product_id)}</select></label></div></div>`;
  const drawItems=()=>{$('#le-items').innerHTML=items.map(itemHtml).join('')||'<p class="le-empty">沒有品項（例如取消單）。需要的話按「＋ 加一項」。</p>';};
  const field=(id,label,value,limit)=>`<label>${label}<input id="${id}" maxlength="${limit}" value="${esc(value)}"></label>`;
  dialog(`修改訂單 · ${o.location||o.customer||'LINE 訂單'}`,`${o.needs_review?`<p class="notice">AI 標記需確認：${esc(o.review_reason||'請核對原始留言')}</p>`:''}
    <div class="le-layout"><section class="le-raw" aria-label="客人在 LINE 的原文"><h3>客人原文 <small>LINE</small></h3>${o.source.map(bubble).join('')||'<p class="line-empty-items">找不到原始留言</p>'}</section>
      <form id="le-form" class="le-form" novalidate>
        <div class="le-fields">${field('le-location','地點',o.location,100)}${field('le-customer','客人',o.customer,100)}<label>類型<select id="le-action">${actionNames.map(a=>`<option ${a===o.action?'selected':''}>${a}</option>`).join('')}</select></label></div>
        <h3>品項 <small>數量空白＝客人沒寫數量</small></h3><div class="le-head" aria-hidden="true"><span>數量</span><span>單位</span><span>品名</span></div>
        <div id="le-items" class="le-items"></div><button type="button" id="le-add" class="text-button le-add">＋ 加一項</button>
        <div class="le-fields">${field('le-carrier','載具',o.carrier,100)}${field('le-payment','付款',o.payment,100)}${field('le-note','備註',o.note,500)}</div>
        <label class="le-check"><input id="le-review" type="checkbox">還要再確認（保留「需確認」）</label>
        <label id="le-reason-wrap" class="le-reason" hidden>需確認原因<input id="le-reason" maxlength="200" value="${esc(o.review_reason)}"></label>
        <p class="error" role="alert"></p>
        <div class="form-actions"><button type="button" data-action="close">取消</button><button type="submit" class="primary">儲存修改</button></div>
      </form></div>`,'LINE 接單 · 修改訂單');
  const box=$('#dialog');box.classList.add('le-dialog');box.addEventListener('close',()=>box.classList.remove('le-dialog'),{once:true});
  drawItems();
  const sync=e=>{
    const row=e.target.closest('[data-le-item]'),name=e.target.dataset.leField;if(!row||!name)return;
    const i=items[Number(row.dataset.leItem)];S.dialogDirty=true;
    if(name!=='product_id'){i[name]=e.target.value;return;}
    i.product_id=e.target.value?Number(e.target.value):null;
    // 選了店內商品，品名或單位空白就幫忙帶入。
    const p=productCache.find(x=>x.id===i.product_id);
    for(const key of ['name','unit'])if(p&&!i[key].trim()){i[key]=p[key];row.querySelector(`[data-le-field="${key}"]`).value=p[key];}
  };
  $('#le-items').addEventListener('input',sync);$('#le-items').addEventListener('change',sync);
  $('#le-items').addEventListener('click',e=>{const b=e.target.closest('[data-le-remove]');if(!b)return;items.splice(Number(b.dataset.leRemove),1);S.dialogDirty=true;drawItems();});
  $('#le-add').onclick=()=>{items.push({...blank});S.dialogDirty=true;drawItems();document.querySelector(`[data-le-item="${items.length-1}"] [data-le-field="name"]`)?.focus();};
  $('#le-form').addEventListener('input',()=>{S.dialogDirty=true;});
  $('#le-review').onchange=e=>{$('#le-reason-wrap').hidden=!e.target.checked;};
  formSubmit($('#le-form'),async()=>{
    if(items.some(i=>!i.name.trim()))throw new Error('品名不能空白；不要的品項按 × 刪除');
    const body={version:o.version,action:$('#le-action').value,needs_review:$('#le-review').checked,review_reason:$('#le-reason').value,
      location:$('#le-location').value,customer:$('#le-customer').value,carrier:$('#le-carrier').value,payment:$('#le-payment').value,note:$('#le-note').value,
      items:items.map(i=>({...i,quantity:String(i.quantity).trim()||null}))};
    try{await api('/line-orders/'+o.id,body,'PUT');}
    catch(e){if(e.status!==409)throw e;closeDialog(true);toast(e.message);await rerender();return;}
    closeDialog(true);toast('已更新訂單');pick={id:o.id,index:pick.index};await rerender();
  });
}

// 寬螢幕右邊直接有合計欄；較窄的螢幕按「商品合計」用視窗看。
function showSummary(){
  dialog('商品數量合計',`<p class="notice">${summaryInfo()}</p>${summaryList(current)}<div class="form-actions"><button data-action="close">關閉</button></div>`,'LINE 接單');
}

function showHistory(){
  dialog('匯入紀錄',`<div class="line-history">${current.imports.map(i=>`<button class="line-history-row" data-line-import="${i.id}"><span><strong>${stamp(i.created_at)}</strong><small>新留言 ${i.new_messages} 則 · 訂單 ${i.order_count} 筆</small></span><span class="badge ${i.status==='failed'?'out':i.status==='pending'?'warning':'normal'}">${importStates[i.status]}</span></button>`).join('')}</div>
    <div class="form-actions"><button data-action="close">關閉</button></div>`,`LINE 接單 · 最近 ${current.imports.length} 次`);
  document.querySelectorAll('#dialog [data-line-import]').forEach(b=>b.onclick=()=>showImport(b.dataset.lineImport).catch(e=>toast(e.message)));
}

async function exportExcel(button){
  button.disabled=true;const label=button.textContent;button.textContent='正在產生 Excel…';
  try{
    const response=await fetch('/api/line-orders/export?'+new URLSearchParams(period()));
    if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error?.message||'匯出失敗，請重試');}
    const header=response.headers.get('Content-Disposition')||'',match=header.match(/filename\*=UTF-8''([^;]+)/i);
    const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');
    a.href=url;a.download=match?decodeURIComponent(match[1]):'LINE訂單.xlsx';document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),5000);toast('Excel 已下載');
  }catch(e){toast(e.message);}finally{button.disabled=false;button.textContent=label;}
}

async function retry(id,button){
  if(busy)return;
  busy=true;if(button)button.disabled=true;
  setBusy(true,'AI 轉換中，約需 10–60 秒…');
  try{const r=await api(`/line-orders/imports/${id}/convert`,{});notice={kind:'ok',text:`✓ 已轉出 ${r.orders_created} 筆訂單`};pick={id:null,index:0};closeDialog(true);}
  catch(e){notice={kind:'error',text:e.message};closeDialog(true);}
  finally{busy=false;}
  await rerender();
}

async function showImport(id){
  const d=await api('/line-orders/imports/'+id);
  dialog(`匯入紀錄 #${d.id}`,`<p class="notice">${stamp(d.created_at)} · ${esc(d.filename)}</p>
    <dl class="line-facts"><div><dt>狀態</dt><dd>${importStates[d.status]}</dd></div><div><dt>新留言</dt><dd>${d.new_messages} 則（客人文字 ${d.customer_messages} 則、店家 ${d.staff_messages} 則）</dd></div><div><dt>轉出訂單</dt><dd>${d.orders} 筆</dd></div></dl>
    ${d.error?`<p class="error">${esc(d.error)}</p>`:''}
    <div class="line-others-body">${messageList('沒被判定為訂單的客人留言',d.not_orders)}${messageList('客人傳的圖片（請到 LINE 查看）',d.images)}${messageList('收回的訊息',d.recalls)}</div>
    <div class="form-actions">${['pending','failed'].includes(d.status)?`<button id="line-dialog-retry" class="primary">重新轉換</button>`:''}<button data-action="close">關閉</button></div>`,'LINE 接單');
  if($('#line-dialog-retry'))$('#line-dialog-retry').onclick=e=>retry(d.id,e.target);
}

// 在這一頁時，檔案拖到畫面任何地方都匯入，避免瀏覽器直接打開文字檔；拖曳中蓋一層提示。
const dragging=e=>S.view==='line-orders'&&e.dataTransfer?.types?.includes('Files');
let dragDepth=0;
const dropzone=show=>{const z=$('#line-dropzone');if(z)z.hidden=!show;};
window.addEventListener('dragenter',e=>{if(!dragging(e))return;dragDepth++;dropzone(true);});
window.addEventListener('dragleave',e=>{if(!dragging(e))return;dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)dropzone(false);});
window.addEventListener('dragover',e=>{if(dragging(e))e.preventDefault();});
window.addEventListener('drop',e=>{dragDepth=0;dropzone(false);if(S.view!=='line-orders'||!e.dataTransfer?.files?.length)return;e.preventDefault();importFile(e.dataTransfer.files[0]);});

// 點自訂時間小視窗以外的地方就關掉。
document.addEventListener('click',e=>{if(S.view==='line-orders'&&!e.target.closest?.('.line-range-wrap'))customPanel(false);});

// ↑ ↓（或 K J）切換訂單；Esc 關掉自訂時間；正在打字或開著對話框時不搶按鍵。
document.addEventListener('keydown',e=>{
  if(S.view!=='line-orders'||$('#dialog').open||e.altKey||e.ctrlKey||e.metaKey)return;
  if(e.key==='Escape'){customPanel(false);return;}
  if(e.target.closest?.('input,textarea,select,[contenteditable]'))return;
  const delta={ArrowDown:1,j:1,ArrowUp:-1,k:-1}[e.key];
  if(!delta)return;
  e.preventDefault();step(delta);
});
