// Fully mocked browser regression: no server or inventory database is accessed.
const {chromium}=require('C:/Users/咖波/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const appRoot=path.resolve(__dirname,'../app');
const simulateFix=process.argv.includes('--simulate-fix');
const simulateOriginal=process.argv.includes('--simulate-original');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
  const page=await browser.newPage();
  let holdGet=false,heldGet,heldPost,sent,resolveGet,resolvePost;
  const getStarted=new Promise(resolve=>resolveGet=resolve);
  const postStarted=new Promise(resolve=>resolvePost=resolve);
  const product={id:1,name:'Review Product',code:'TEST',category:'',price:'12',unit:'包',quantity:'10',batches:[{id:1,quantity:'10',version:1,expires_on:'2027-01-01',saleable:1,reserved_quantity:'0'}]};
  const products={items:[product],total:1,page:1,page_size:10};
  await page.route('**/*',async route=>{
   const u=new URL(route.request().url());
   if(u.pathname==='/api/session')return route.fulfill({json:{authenticated:true,csrf:'test'}});
   if(u.pathname==='/api/meta')return route.fulfill({json:{today:'2026-10-01',categories:[],products:[product],export:{pending:false,issues:[]}}});
   if(u.pathname==='/api/products'){
    if(holdGet){heldGet=route;resolveGet();return;}
    return route.fulfill({json:products});
   }
   if(u.pathname==='/api/counts/bulk'){heldPost=route;sent=route.request().postDataJSON();resolvePost();return;}
   const file=u.pathname==='/'?path.join(appRoot,'templates/index.html'):path.join(appRoot,u.pathname);
   if(fs.existsSync(file)){
    let body=fs.readFileSync(file);
    if(u.pathname==='/static/views/merchant.js'){
     let source=body.toString('utf8');
     if(simulateFix)source=source.replace('if(!isCurrent())return;','if(!isCurrent()||S.savingCounts)return;');
     if(simulateOriginal)source=source.replace('if(!isCurrent()||S.savingCounts)return;','if(!isCurrent())return;');
     body=Buffer.from(source);
    }
    return route.fulfill({body,contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'image/png'});
   }
   return route.abort();
  });
  await page.goto('http://localhost:9876/');
  await page.locator('[data-inventory-mode="table"]').click();
  await page.locator('[data-count-batch]').fill('4');
  holdGet=true;
  await page.evaluate(()=>{window.reviewRenderDone=false;import('/static/app.js').then(m=>m.render()).finally(()=>{window.reviewRenderDone=true;});});
  await getStarted;
  await page.locator('#save-stocktake').click();
  await postStarted;
  await heldGet.fulfill({json:products});
  await page.waitForFunction(()=>window.reviewRenderDone);
  const disabled=await page.locator('[data-count-batch]').isDisabled();
  if(!disabled)await page.locator('[data-count-batch]').fill('9');
  holdGet=false;
  await heldPost.fulfill({json:{results:[{batch_id:1}],movement_ids:[1]}});
  await page.waitForFunction(()=>document.querySelector('[data-count-batch]')?.value==='');
  console.log(JSON.stringify({disabledDuringPost:disabled,sentQuantity:sent.items[0].actual_quantity,finalInput:await page.locator('[data-count-batch]').inputValue()}));
  assert(disabled,'Pending GET re-enabled the form: the subsequent quantity 9 was erased when quantity 4 finished saving.');
  assert.equal(sent.items[0].actual_quantity,'4');
  console.log('PASS: pending products GET cannot re-enable or replace the saving stocktake form.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
