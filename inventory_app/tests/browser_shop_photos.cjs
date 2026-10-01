const {chromium}=require('C:/Users/咖波/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8765/shop');await page.locator('.recipe-card').nth(2).waitFor();
  const counts=await page.evaluate(async()=>{
   let total=0,photos=0;
   for(let p=1;p<=8;p++){
    const data=await (await fetch('/api/shop/catalog?page='+p)).json();
    if(p>Math.ceil(data.total/data.page_size))break;
    for(const i of data.items){total++;if(i.image){const img=new Image();img.src='/shop/media/'+i.image;await img.decode();photos++;}}
   }return {total,photos};
  });assert.deepEqual(counts,{total:173,photos:113});
  for(const width of [1366,390]){
   await page.setViewportSize({width,height:900});
   for(const [dish,count] of [['番茄牛肉烏龍麵',2],['照燒雞腿',2],['玉米貢丸湯',3]]){
    await page.locator('.recipe-card').filter({hasText:dish}).locator('button').click();
    assert.equal(await page.locator('.ingredient-photo').count(),count);
    await page.locator('.ingredient-photo').evaluateAll(imgs=>Promise.all(imgs.map(i=>i.decode())));
    assert(await page.locator('#modal-content').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
    if(dish==='玉米貢丸湯')await page.screenshot({path:`.qa/ingredient-photos-${width}.png`});
    await page.keyboard.press('Escape');
   }
  }
  await page.setViewportSize({width:1366,height:900});await page.locator('[data-view="products"]:visible').first().click();await page.locator('#product-search').fill('桂冠');
  await page.waitForFunction(()=>[...document.querySelectorAll('.product-card h3')].every(h=>h.textContent.includes('桂冠')));
  await page.locator('.product-photo').evaluateAll(imgs=>Promise.all(imgs.map(i=>i.decode())));
  await page.screenshot({path:'.qa/shop-linked-photos.png',fullPage:true});assert.deepEqual(errors,[]);
  console.log('PASS: 113/173 product photos decode; recipe ingredient photos 2/2/3; desktop/mobile dialogs fit; no JS errors; read-only production verification.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
