const {chromium}=require('C:/Users/咖波/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
const base=process.env.DUCK_TEST_URL||'http://127.0.0.1:8765';
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const context=await browser.newContext({viewport:{width:1366,height:900}});
  const page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const all=await (await context.request.get(base+'/api/shop/catalog?all=1')).json();
  assert.equal(all.items.length,all.total,'all products returned');
  assert.equal(new Set(all.items.map(p=>p.id)).size,all.total,'no duplicate products');
  for(const category of all.categories){
   const rows=all.items.filter(p=>p.category===category);
   let missing=false;
   for(const row of rows){if(!row.image)missing=true;else assert(!missing,'photo must precede missing photo within category');}
  }
  await page.goto(base+'/shop');
  await page.locator('[data-view="products"]:visible').first().click();
  await page.waitForFunction(n=>document.querySelectorAll('.product-card').length===n,all.total);
  assert.deepEqual(await page.locator('.product-card').evaluateAll(cards=>cards.map(c=>Number(c.dataset.productId))),all.items.map(p=>p.id));
  assert.deepEqual(await page.locator('.product-category h2').allTextContents(),all.categories.map(c=>c||'其他商品'));
  assert.equal(await page.locator('.product-card .missing-product-photo').count(),all.items.filter(p=>!p.image).length);
  const placeholder=page.locator('.product-card .missing-product-photo').first();
  if(await placeholder.count()){
   assert((await placeholder.getAttribute('src')).endsWith('/product-no-photo-light.png'));
   await placeholder.evaluate(img=>img.decode());
  }
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:'.qa/product-display-desktop.png'});
  const category=all.categories[1]||all.categories[0];
  if(category){
   await page.locator('[data-action="category"]').filter({hasText:category}).click();
   await page.waitForFunction(n=>document.querySelectorAll('.product-card').length===n,all.items.filter(p=>p.category===category).length);
  }
  await page.locator('[data-action="category"][data-category=""]').click();
  await page.waitForFunction(n=>document.querySelectorAll('.product-card').length===n,all.total);
  await page.locator('#product-search').fill('不存在的商品-test');
  await page.getByRole('heading',{name:'沒有找到商品'}).waitFor();
  await page.locator('#product-search').fill('');
  await page.waitForFunction(n=>document.querySelectorAll('.product-card').length===n,all.total);
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile overflow');
  await page.screenshot({path:'.qa/product-display-mobile.png'});
  // Real image failures also use the shared fallback, without a request loop.
  const photo=page.locator('.product-card img:not(.missing-product-photo)').first();
  if(await photo.count()){
   await photo.evaluate(img=>{img.src='/static/intentionally-missing-product.png';});
   await page.waitForFunction(()=>!document.querySelector('img[src="/static/intentionally-missing-product.png"]'));
  }
  assert.deepEqual(errors,[]);
  console.log(`PASS: ${all.total} products, ${all.categories.length} categories, photo order, placeholders, filters, desktop/mobile and image error fallback.`);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
