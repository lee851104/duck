const {chromium}=require('C:/Users/咖波/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try {
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8767');
  await page.locator('#password').fill('qa-local-testing-only');await page.locator('#auth-form button').click();
  await page.locator('.stats').waitFor();
  for(const viewport of [{width:1366,height:768},{width:390,height:844},{width:768,height:700}]){
   await page.setViewportSize(viewport);await page.locator('[data-nav="catalog"]').click();
   await page.locator('#catalog-page-size').waitFor();
   await page.locator('#catalog-page-size').selectOption('24');
   await page.waitForFunction(()=>document.querySelectorAll('.catalog-card').length===24);
   assert.equal(await page.locator('.catalog-card').count(),24);
   const first=await page.locator('.catalog-card h3').first().textContent();
   await page.locator('.catalog-photo').first().click();
   await page.locator('.catalog-preview-image').waitFor();
   assert.equal(await page.locator('#dialog-title').textContent(),first);
   assert.ok(await page.locator('.catalog-preview-image').evaluate(im=>im.complete&&im.naturalWidth>0));
   await page.keyboard.press('Escape');
   await page.locator('[data-action="photo-filter"][data-photos="missing"]').click();
   await page.waitForFunction(()=>document.querySelector('[data-photos="missing"][aria-pressed="true"]'));
   assert.equal(await page.locator('.catalog-photo img').count(),0);
   await page.locator('[data-action="photo-filter"][data-photos="present"]').click();
   await page.waitForFunction(()=>document.querySelector('[data-photos="present"][aria-pressed="true"]'));
   assert.equal(await page.locator('.photo-empty').count(),0);
   await page.locator('.catalog-panel > .pager button').last().click();
   await page.waitForFunction(()=>document.querySelector('.catalog-panel > .pager')?.textContent.includes('2 /'));
   assert.equal(await page.locator('.catalog-panel > .pager button').first().isEnabled(),true);
   await page.locator('#catalog-page-size').selectOption('48');
   await page.waitForFunction(()=>document.querySelectorAll('.catalog-card').length===48);
   assert.ok(await page.locator('#main').evaluate(el=>el.scrollHeight>el.clientHeight));
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:path.resolve(__dirname,`../.qa/screenshots/gallery-${viewport.width}.png`)});
   for(const view of ['dashboard','inventory','history']){
    await page.locator(`[data-nav="${view}"]`).click();await page.waitForTimeout(250);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),view+' has horizontal overflow');
   }
   await page.locator('[data-nav="inventory"]').click();
   await page.locator('.tiny-actions').first().waitFor();
   const actions=page.locator('.tiny-actions').first();
   for(const name of ['登記進貨','登記出貨','盤點庫存'])assert.equal(await actions.getByRole('button',{name,exact:true}).count(),1);
  }
  assert.deepEqual(errors,[]);console.log('Gallery desktop/mobile/tablet: paging, filters, photo preview, scrolling, named actions PASS');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
