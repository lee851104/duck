// UI-only fixture: all network requests are intercepted; no live stock is changed.
const {chromium}=require('C:/Users/咖波/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../app');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{for(const width of [1366,390]){
  const page=await browser.newPage({viewport:{width,height:844}}),errors=[];page.on('pageerror',e=>errors.push(e.message));let sent,attempts=0;
  const items=[{id:1,code:'A1',name:'番茄牛肉湯',unit:'包',price:'110',quantity:'8',category:'冷凍',batches:[{id:1,quantity:'8',version:1,expires_on:'2027-01-01',saleable:1,reserved_quantity:'2'},{id:4,quantity:'3',version:1,expires_on:'2027-02-01',saleable:1}]},
   {id:2,code:'A2',name:'雞腿尚未盤點的商品',unit:'包',price:'150',quantity:null,category:'冷凍',batches:[{id:2,quantity:null,version:1,expires_on:null,saleable:0}]},
   {id:3,code:'A3',name:'秤重牛肉',unit:'kg',price:'800',quantity:'1.5',category:'冷凍',batches:[{id:3,quantity:'1.5',version:1,expires_on:'2027-01-01',saleable:1}]}];
  await page.route('**/*',async route=>{const u=new URL(route.request().url());
   if(u.pathname==='/api/session')return route.fulfill({json:{authenticated:true,csrf:'test'}});
   if(u.pathname==='/api/meta')return route.fulfill({json:{today:'2026-10-01',categories:['冷凍'],products:items}});
   if(u.pathname==='/api/products')return route.fulfill({json:{items,total:3,page:1,page_size:10}});
   if(u.pathname==='/api/counts/bulk'){sent=route.request().postDataJSON();if(!attempts++){items[0].batches[0].version=2;items[0].batches[0].quantity='7';return route.fulfill({status:409,json:{error:{message:'庫存已被更新',fields:{batch_id:1}}}});}return route.fulfill({json:{results:sent.items}});}
   const file=u.pathname==='/'?path.join(root,'templates/index.html'):path.join(root,u.pathname);
   if(fs.existsSync(file))return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'image/png'});
   return route.abort();
  });
  await page.goto('http://localhost:9876/');await page.locator('[data-inventory-mode="table"]').click();
  await page.locator('.stocktake-card').first().waitFor({timeout:3000});
  assert.equal(await page.locator('.stocktake-card').count(),3);
  assert.equal(await page.locator('[data-count-batch]').count(),4,'separate expiry batches');
  const row=id=>page.locator(`[data-stocktake-row="${id}"]`),input=id=>page.locator(`[data-count-batch="${id}"]`);
  assert.equal(await input(1).inputValue(),'');
  await row(1).getByRole('button',{name:'數量沒變',exact:true}).click();assert.equal(await input(1).inputValue(),'8');
  await row(1).getByRole('button',{name:'增加數量'}).click();assert.equal(await input(1).inputValue(),'9');
  assert.match(await row(1).locator('.count-feedback').innerText(),/多 1/);
  assert(await row(2).getByRole('button',{name:'數量沒變',exact:true}).isDisabled());
  assert(await row(2).getByRole('button',{name:'減少數量'}).isDisabled());
  await row(2).getByRole('button',{name:'增加數量'}).click();assert.equal(await input(2).inputValue(),'1');
  await row(2).getByRole('button',{name:'已售完，填 0',exact:true}).click();assert.equal(await input(2).inputValue(),'0');
  await row(3).getByRole('button',{name:'增加數量'}).click();assert.equal(await input(3).inputValue(),'2.5');
  await input(3).fill('0.75');
  await row(4).getByRole('button',{name:'數量沒變',exact:true}).click();
  await row(4).getByRole('button',{name:'清除此筆',exact:true}).click();assert.equal(await input(4).inputValue(),'');
  assert.match(await page.locator('#stocktake-summary').innerText(),/3/);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert(await page.locator('#main').evaluate(el=>el.scrollWidth<=el.clientWidth+1),'no sideways scrolling');
  const buttonBox=await row(1).getByRole('button',{name:'增加數量'}).boundingBox();assert(buttonBox.height>=52&&buttonBox.width>=52);
  await page.locator('#main').evaluate(el=>el.scrollTop=0);await page.screenshot({path:`.qa/stocktake-touch-${width}.png`});
  await page.locator('#save-stocktake').click();await page.locator('#reload-conflict').waitFor();
  await input(2).fill('1');await input(2).fill('0');
  await page.locator('#reload-conflict').click();await page.waitForFunction(()=>document.querySelector('[data-count-batch="1"]')?.value==='');
  assert.equal(await input(2).inputValue(),'0','other drafts survive conflict recovery');assert.equal(await input(3).inputValue(),'0.75');
  await row(1).getByRole('button',{name:'數量沒變',exact:true}).click();assert.equal(await input(1).inputValue(),'7');
  await page.locator('#save-stocktake').click();await page.waitForFunction(()=>document.querySelector('#save-stocktake')?.disabled);
  assert.equal(sent.items.find(i=>i.batch_id===1).expected_version,2,'reload uses fresh batch version');
  assert.equal(sent.items.length,3);assert.equal(sent.items.find(i=>i.batch_id===2).actual_quantity,'0');assert.equal(sent.items.find(i=>i.batch_id===3).actual_quantity,'0.75');assert(!sent.items.some(i=>i.batch_id===4));
  assert.deepEqual(errors,[]);await page.close();
 }console.log('PASS: large photo cards, known/unknown/decimal/zero counts, expiry separation, single-row clear, touch target sizes, desktop/mobile layout, explicit bulk save.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
