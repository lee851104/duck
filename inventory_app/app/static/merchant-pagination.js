export function visiblePages(page,total){
  const start=Math.max(1,Math.min(page-3,total-6));
  return Array.from({length:Math.min(7,total)},(_,i)=>start+i);
}

export function merchantPagination(p){
  const total=Math.max(1,Math.ceil(p.total/p.page_size));
  const pages=visiblePages(p.page,total);
  const button=n=>`<button type="button" data-action="page" data-page="${n}" aria-label="第 ${n} 頁" ${n===p.page?'aria-current="page"':''}>${n}</button>`;
  return `<nav class="merchant-pagination" aria-label="商品分頁"><span class="pagination-summary">共 ${p.total} 項 · 第 ${p.page} / ${total} 頁</span><div class="pagination-controls"><button type="button" class="pagination-step" data-action="page" data-page="${p.page-1}" aria-label="上一頁" ${p.page<=1?'disabled':''}>‹<span>上一頁</span></button><div class="pagination-numbers">${pages[0]>1?button(1)+'<span class="pagination-gap" aria-hidden="true">…</span>':''}${pages.map(button).join('')}${pages.at(-1)<total?'<span class="pagination-gap" aria-hidden="true">…</span>'+button(total):''}</div><button type="button" class="pagination-step" data-action="page" data-page="${p.page+1}" aria-label="下一頁" ${p.page>=total?'disabled':''}><span>下一頁</span>›</button></div><label class="pagination-jump">跳至<select id="merchant-page-jump" aria-label="跳至商品頁碼">${Array.from({length:total},(_,i)=>`<option value="${i+1}" ${i+1===p.page?'selected':''}>第 ${i+1} 頁</option>`).join('')}</select></label></nav>`;
}
