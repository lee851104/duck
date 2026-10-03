// 每日銷售單草稿的日期：空白草稿跨日自動換成今天；有品項的草稿可能是前一天還沒送出的銷售，保留原日期由畫面提醒。
export function draftSoldOn(draft,today){
  if(!draft.sold_on)return today;
  if(!draft.pending&&!draft.items.length&&draft.dated_on!==today)return today;
  return draft.sold_on;
}
