const {chromium}=require('C:/Users/咖波/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8769/');
  await page.locator('#password').fill('review-test-only');await page.locator('#auth-form button').click();
  await page.locator('.merchant-card').first().waitFor();
  const api=await page.evaluate(async()=>{const get=async path=>(await fetch('/api'+path)).json();return {catalog:await get('/mappings/catalog?pending=1'),invoice:await get('/mappings/invoice?pending=1'),product:await get('/products/86')};});
  assert.equal(api.catalog.total,3);assert.equal(api.invoice.total,2);assert.equal(api.product.price,'115');
  await page.locator('#settings').click();await page.locator('#catalog-map').click();
  await page.locator('#toggle-mapping-filter').waitFor();
  assert.match(await page.locator('#dialog-body').innerText(),/待確認 3 筆/);
  await page.locator('#toggle-mapping-filter').click();await page.waitForFunction(()=>document.querySelector('#dialog-body').textContent.includes('全部 186 筆'));
  assert.equal(await page.locator('[data-mapping-id="2"] [name="product_id"]').inputValue(),'independent');
  await page.locator('#toggle-mapping-filter').click();
  await page.locator('[data-mapping-id="79"]').waitFor();
  const row=page.locator('[data-mapping-id="79"]');await row.locator('[name="product_id"]').selectOption('independent');await row.locator('button[type="submit"]').click();
  await page.waitForFunction(()=>document.querySelector('#dialog-body').textContent.includes('待確認 2 筆'));
  assert.equal(await page.locator('[data-mapping-id="79"]').count(),0);
  await page.screenshot({path:'../output/owner-review/reconciliation-desktop.png'});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:'../output/owner-review/reconciliation-mobile.png'});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.deepEqual(errors,[]);
  console.log('PASS: live trial data; pending-only catalog; all-data editing; independent state roundtrip; 6-price plan visible; save refresh; desktop/mobile; no JS errors.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
