import {S,$,api,esc,badge,money,qty,image,dialog,formSubmit,closeDialog,refresh,toast,pager,kinds} from '../app.js';

const field=(label,name,value='',type='text',extra='')=>`<label>${label}<input name="${name}" type="${type}" value="${esc(value??'')}" ${extra}></label>`;
const checks=(name,label,checked=false)=>`<label class="check-label"><input type="checkbox" name="${name}" ${checked?'checked':''}>${label}</label>`;
const buttons=(text='儲存',tone='primary')=>`<p class="error" role="alert"></p><div class="form-actions"><button type="button" data-action="close">取消</button><button class="${tone}" type="submit">${text}</button></div>`;
const options=(selected)=>S.meta.products.map(p=>`<option value="${p.id}" ${p.id===selected?'selected':''}>${esc(p.name)} · ${esc(p.code)}</option>`).join('');

export async function productPanel(id,tab='basic',page=1){
  const p=await api('/products/'+id);
  const tabs=`<div class="filters">${[['basic','基本資料'],['batches','批次庫存'],['history','異動紀錄']].map(([k,t])=>`<button type="button" data-detail-tab="${k}" class="${tab===k?'selected':''}">${t}</button>`).join('')}</div>`;
  let content='';
  if(tab==='basic')content=`<div class="detail-top">${image(p)}<div><small>可售庫存</small><div class="detail-number">${qty(p)}</div>${badge(p.status)}${Number(p.reserved_quantity)>0?`<small>已扣除訂單預留 ${esc(p.reserved_quantity)} ${esc(p.unit)}</small>`:''}</div></div>
    <dl class="details-grid"><div><dt>品號</dt><dd>${esc(p.code)}</dd></div><div><dt>售價</dt><dd>${money(p.price)}</dd></div><div><dt>分類</dt><dd>${esc(p.category||'未設定')}</dd></div><div><dt>供應商</dt><dd>${esc(p.supplier||'未設定')}</dd></div><div><dt>最低庫存</dt><dd>${esc(p.minimum??'未設定')} ${esc(p.unit)}</dd></div><div><dt>最近效期</dt><dd>${p.nearest_expiry||'無已知可售效期'}</dd></div></dl>
    ${p.uncounted?'<p class="notice">有批次尚未盤點，總庫存目前不完整。</p>':''}
    ${p.status==='unconfirmed'?`<p class="notice">已盤點 ${esc(p.unconfirmed_quantity)} ${esc(p.unit)}，但還沒確認可售，每日銷售單扣不到。請在「盤點庫存」勾選「確認可售」，或在批次的「盤點」確認。</p>`:''}
    <div class="button-row"><button id="edit-product">修改資料／售價</button><button id="return-product">顧客退回</button></div>`;
  else if(tab==='batches'){
    const data=await api(`/products/${id}/batches?page=${page}&page_size=3`);
    content=`<div class="mini-list">${data.items.map(b=>`<div class="batch-row"><div class="item-main"><h3>批次 #${b.id} · ${b.quantity===null?'未盤點':esc(b.quantity)+' '+esc(p.unit)}</h3><p class="item-sub">預留 ${b.reserved_quantity||0} ${esc(p.unit)} · 效期 ${b.expires_on||'未知'} · 進價 ${money(b.cost)}</p><p class="item-sub">${b.expired?'已過期':b.saleable?'可售':'待確認可售'} · 進貨 ${b.received_on||'日期未知'}</p></div><button class="batch-count action-count" data-batch="${b.id}">盤點</button></div>`).join('')}</div>${pager(data,'detail-page')}`;
  }else{
    const data=await api(`/history?product_id=${id}&page=${page}&page_size=4`);
    content=`<div class="mini-list">${data.items.map(m=>`<div class="batch-row"><div><h3>${kinds[m.kind]||esc(m.kind)} · ${esc(m.reason)}</h3><p class="item-sub">${esc(m.created_at.slice(0,16).replace('T',' '))}</p><p class="item-sub">${['edit','create','mapping'].includes(m.kind)?'商品資料已更新':esc(m.before_value??'未知')+' → '+esc(m.after_value??'未知')}</p></div></div>`).join('')||'<p class="muted">尚無紀錄</p>'}</div>${pager(data,'detail-page')}`;
  }
  dialog(p.name,`<div class="product-primary-actions"><button class="action-receive" data-action="operation" data-type="receive" data-id="${p.id}">進貨</button><button class="action-issue" data-action="operation" data-type="issue" data-id="${p.id}">店內賣出</button><button class="action-count" data-action="operation" data-type="count" data-id="${p.id}">盤點</button></div>`+tabs+content,'商品 · '+p.code);
  document.querySelectorAll('[data-detail-tab]').forEach(b=>b.onclick=()=>productPanel(id,b.dataset.detailTab));
  document.querySelectorAll('[data-action="detail-page"]').forEach(b=>b.onclick=()=>productPanel(id,tab,Number(b.dataset.page)));
  document.querySelectorAll('.batch-count').forEach(b=>b.onclick=()=>operation('count',id,Number(b.dataset.batch)));
  if($('#edit-product'))$('#edit-product').onclick=()=>newProduct(p);
  if($('#return-product'))$('#return-product').onclick=()=>operation('return',id);
}

export async function newProduct(p=null){
  const title=p?'修改商品':'新增商品';
  dialog(title,`<form id="product-form"><div class="form-grid">${field('品號','code',p?.code||'','text','required maxlength="60"')}${field('品名','name',p?.name||'','text','required maxlength="200"')}${field('基本單位','unit',p?.unit||'包','text',p?'readonly':'required')}${field('售價','price',p?.price,'number','min="0" step="0.01"')}${field('分類','category',p?.category)}${field('供應商','supplier',p?.supplier)}${field('最低庫存','minimum',p?.minimum,'number','min="0" step="any"')}${field('規格','specification',p?.specification)}<label class="full">包裝換算（選填，例如：箱=24）<input name="conversions" value="${esc(Object.entries(p?.conversions||{}).map(([k,v])=>k+'='+v).join(', '))}" placeholder="箱=24, 手=6"></label></div>${buttons(p?'儲存變更':'新增商品')}</form>`);
  formSubmit($('#product-form'),async f=>{const body=Object.fromEntries(f);body.price=body.price||null;body.minimum=body.minimum||null;
    body.conversions={};if(f.get('conversions').trim())for(const pair of f.get('conversions').split(/[,，]/)){const [k,v]=pair.split('=');if(!k?.trim()||!v?.trim())throw new Error('換算請使用「箱=24」格式');body.conversions[k.trim()]=v.trim();}
    if(p)body.expected_version=p.version;
    await api(p?'/products/'+p.id:'/products',body,p?'PATCH':'POST');closeDialog(true);await refresh();toast(p?'商品資料已更新':'已新增商品：請到「盤點庫存」填數量，並勾選「確認可售」');});
}

export async function operation(type,id=null,batchId=null){
  if(!id){
    if(!S.meta.products.length){toast('請先新增商品或匯入原始資料');return;}
    dialog({receive:'登記進貨',issue:'登記出貨',count:'開始盤點',return:'顧客退回'}[type],`<form id="choose-product"><label>先選擇商品<select name="product">${options()}</select></label>${buttons('下一步')}</form>`);
    formSubmit($('#choose-product'),async f=>operation(type,Number(f.get('product'))));return;
  }
  const p=await api('/products/'+id);
  if(type==='issue')return issueForm(p);
  if(type==='count')return countForm(p,batchId);
  dialog(type==='return'?'顧客退回':'登記進貨',`<form id="receive-form"><p class="muted">${esc(p.name)}</p><div class="form-grid">
    ${field('數量','quantity','','number','min="0.000001" step="any" required')}
    <label>入庫單位<select name="package"><option value="1">${esc(p.unit)}</option>${Object.entries(p.conversions).map(([k,v])=>`<option value="${esc(v)}">${esc(k)}（${esc(v)} ${esc(p.unit)}）</option>`).join('')}</select></label>
    ${field('每 '+esc(p.unit)+' 進價','cost',p.batches.findLast(b=>b.cost!==null)?.cost,'number','min="0" step="any"')}${field('進貨日期','received_on',S.meta.today,'date','required')}
    <label class="full">有效期限<input type="date" name="expires_on"></label>
    <div class="full">${checks('unknown_expiry','效期未知')}${type==='return'?'<p class="notice">退回商品先列為不可售，確認狀況後可從盤點重新設定。</p>':checks('saleable_confirmed','效期未知，但已確認這批可售')}</div></div>${buttons('確認入庫')}</form>`);
  formSubmit($('#receive-form'),async f=>{const body=Object.fromEntries(f);body.product_id=id;body.request_id=$('#receive-form').dataset.requestId||crypto.randomUUID();$('#receive-form').dataset.requestId=body.request_id;
    body.quantity=Number((Number(body.quantity)*Number(f.get('package'))).toFixed(6)).toString();body.unknown_expiry=f.has('unknown_expiry');body.saleable_confirmed=f.has('saleable_confirmed');body.cost=body.cost||null;body.expires_on=body.expires_on||null;
    await api(type==='return'?'/returns':'/receipts',body);closeDialog(true);await refresh();toast('入庫紀錄已儲存');});
}

function countForm(p,batchId){
  let b=p.batches.find(x=>x.id===batchId)||p.batches[0];
  if(!b){toast('沒有可盤點批次，請先進貨');return;}
  dialog('盤點庫存',`<form id="count-form"><p class="muted">${esc(p.name)}</p><div class="form-grid"><label class="full">盤點批次<select id="count-batch">${p.batches.map(x=>`<option value="${x.id}" ${x.id===b.id?'selected':''}>批次 #${x.id} · ${x.expires_on||'效期未知'} · ${x.quantity??'未盤點'} ${esc(p.unit)}</option>`).join('')}</select></label><p class="notice full">帳面數量：${b.quantity??'未知'} ${esc(p.unit)}。請填入現場實際數量。</p>${field('實際數量（'+esc(p.unit)+'）','actual_quantity',b.quantity,'number','min="0" step="any" required')}${field('有效期限','expires_on',b.expires_on,'date')}<div class="full">${checks('saleable_confirmed','已確認此批可售（過期仍不可銷售）',!!b.saleable)}</div></div>${buttons('確認盤點','action-count')}</form>`);
  $('#count-batch').onchange=e=>countForm(p,Number(e.target.value));
  const requestId=crypto.randomUUID();
  formSubmit($('#count-form'),async f=>{await api('/counts',{batch_id:b.id,actual_quantity:f.get('actual_quantity'),expected_version:b.version,
    request_id:requestId,expires_on:f.get('expires_on')||null,saleable_confirmed:f.has('saleable_confirmed')});closeDialog(true);await refresh();toast('盤點已儲存');});
}

function issueForm(p){
  const draft={},key=crypto.randomUUID();let page=1,reason='銷售',total='';
  const bs=p.batches.filter(b=>b.quantity===null||Number(b.quantity)>0);
  if(!bs.length){toast('目前沒有可出貨的庫存');return;}
  function draw(){
    const items=bs.slice((page-1)*3,page*3);
    dialog('登記出貨',`<form id="issue-form"><p class="muted">${esc(p.name)}</p><div class="form-grid"><label>出貨原因<select id="issue-reason">${['銷售','報廢','退供應商'].map(r=>`<option ${r===reason?'selected':''}>${r}</option>`).join('')}</select></label>${field('預計出貨（'+esc(p.unit)+'）','total',total,'number','min="0" step="any"')}</div><div class="button-row"><button type="button" id="suggest">依效期分配</button><small>可自行調整各批數量</small></div>
      <div class="mini-list">${items.map(b=>`<label class="batch-row"><span class="item-main"><span class="item-name">批次 #${b.id} · ${b.expires_on||'效期未知'}</span><span class="item-sub">帳面 ${b.quantity??'未知'} ${esc(p.unit)} · 預留 ${b.reserved_quantity||0}${b.expired?' · 已過期':!b.saleable?' · 待確認可售':''}</span></span><input aria-label="批次 ${b.id} 出貨數量" data-allocation="${b.id}" type="number" min="0" step="any" value="${esc(draft[b.id]||'')}" ${b.quantity===null?'disabled':''}></label>`).join('')}</div>${pager({items,total:bs.length,page,page_size:3},'issue-page')}${buttons('確認出貨',reason==='報廢'?'danger':'action-issue')}</form>`);
    const persist=()=>{for(const el of document.querySelectorAll('[data-allocation]'))draft[el.dataset.allocation]=el.value;reason=$('#issue-reason').value;total=$('#issue-form [name=total]').value;};
    document.querySelectorAll('[data-action="issue-page"]').forEach(el=>el.onclick=()=>{persist();page=Number(el.dataset.page);draw();});
    $('#issue-reason').onchange=()=>{persist();$('#issue-form [type=submit]').className=reason==='報廢'?'danger':'action-issue';};
    $('#suggest').onclick=()=>{persist();let left=Number(total);if(!Number.isFinite(left)||left<=0){toast('請先填預計出貨數量');return;}
      Object.keys(draft).forEach(k=>delete draft[k]);
      for(const b of bs){if(b.quantity===null||(reason==='銷售'&&(!b.saleable||b.expired||!b.expires_on)))continue;const n=Math.min(left,Math.max(0,Number(b.quantity)-Number(b.reserved_quantity||0)));if(n>0)draft[b.id]=String(Number(n.toFixed(6)));left-=n;}
      draw();if(left>0)toast('可自動分配的庫存不足，請檢查數量與批次');};
    formSubmit($('#issue-form'),async()=>{persist();const allocations=bs.filter(b=>Number(draft[b.id])>0).map(b=>({batch_id:b.id,quantity:draft[b.id],expected_version:b.version}));
      await api('/issues',{product_id:p.id,reason,allocations,expected_total:total||null,request_id:key});closeDialog(true);await refresh();toast('出貨紀錄已儲存');});
  }draw();
}
