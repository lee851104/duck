// Run against an isolated, seeded QA server; never use the store's live database.
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('dialog',dialog=>dialog.type()==='prompt'?dialog.accept('驗收沖銷'):dialog.accept());
  const base='http://127.0.0.1:8770';
  fs.mkdirSync('.qa',{recursive:true});
  await page.goto(base+'/#daily-sales');
  await page.locator('#password').fill('daily-sales-qa-only');
  await page.locator('#auth-form button').click();
  await page.locator('[data-add-sale="1"]').click();
  await page.locator('[data-sale-qty="1"]').fill('5');
  await page.locator('[data-add-sale="2"]').click();
  await page.locator('[data-sale-qty="2"]').fill('1.25');
  await page.locator('#sales-note').fill('每日結帳驗收');
  await page.locator('#sales-search').fill('玉米');
  assert.equal(await page.locator('[data-add-sale]').count(),1);
  await page.locator('#sales-search').fill('');
  await page.locator('[data-nav="inventory"]').click();
  await page.locator('[data-nav="daily-sales"]').click();
  assert.equal(await page.locator('[data-sale-qty="1"]').inputValue(),'5');
  await page.reload();
  await page.locator('[data-sale-qty="1"]').waitFor();
  assert.equal(await page.locator('[data-sale-qty="2"]').inputValue(),'1.25');
  await page.screenshot({path:'.qa/daily-sales-desktop.png',fullPage:true});
  for(const width of [390,320]){
   await page.setViewportSize({width,height:844});
   await page.waitForTimeout(350);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'viewport overflow '+width);
   assert(await page.evaluate(()=>document.querySelector('#main').scrollWidth<=document.querySelector('#main').clientWidth),'main overflow '+width);
  }
  await page.setViewportSize({width:390,height:844});
  await page.waitForTimeout(350);
  await page.locator('#sales-preview').scrollIntoViewIfNeeded();
  await page.screenshot({path:'.qa/daily-sales-mobile.png'});
  await page.locator('[data-sale-qty="2"]').fill('11');
  await page.locator('#sales-preview').click();
  await page.waitForFunction(()=>document.querySelector('#sales-error').textContent.includes('只有'));
  await page.locator('[data-sale-qty="2"]').fill('1.25');
  await page.locator('#sales-preview').click();
  await page.locator('#sales-confirm').waitFor();
  assert((await page.locator('.sales-review').innerText()).includes('批次 #1'));
  await page.screenshot({path:'.qa/daily-sales-preview.png'});
  // Server commits, then response disappears. Retrying must use the same request ID.
  await page.route('**/api/daily-sales',async route=>{
   if(route.request().method()==='POST'){await route.fetch();await route.abort('failed');}
   else await route.continue();
  },{times:1});
  await page.locator('#sales-confirm').click();
  await page.waitForFunction(()=>document.querySelector('#sales-preview')?.textContent.includes('確認上次'));
  assert(await page.locator('[data-sale-qty="1"]').isDisabled());
  await page.reload();
  await page.locator('#sales-preview').click();
  await page.locator('#sales-void').waitFor();
  const sheets=await (await context.request.get(base+'/api/daily-sales')).json();
  assert.equal(sheets.total,1);
  const stock=await (await context.request.get(base+'/api/products/1')).json();
  assert.equal(stock.quantity,'5');
  const csrf=(await (await context.request.get(base+'/api/session')).json()).csrf;
  assert.equal((await context.request.post(base+'/api/shop/orders',{data:{},headers:{'X-CSRF-Token':csrf}})).status(),410);
  await page.locator('#sales-void').click();
  await page.waitForFunction(()=>document.querySelector('#dialog-body')?.textContent.includes('已沖銷，庫存已加回'));
  const restored=await (await context.request.get(base+'/api/products/1')).json();
  assert.equal(restored.quantity,'10');
  await page.locator('#dialog-close').click();
  await page.setViewportSize({width:1440,height:1000});
  await page.waitForTimeout(350);
  await page.screenshot({path:'.qa/daily-sales-history.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: draft navigation/reload, search, 320/390px layout, insufficient stock, preview, lost-response replay after reload, exactly-once deduction, full reversal, customer ordering disabled.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
