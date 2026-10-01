const {chromium}=require('C:/Users/咖波/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{
 const page=await browser.newPage({viewport:{width:1366,height:900}});
 await page.goto('http://127.0.0.1:8768/');await page.locator('#password').fill('merchant-test-only');await page.locator('#auth-form button').click();await page.locator('.merchant-card').first().waitFor();
 await page.route('**/api/products?*',async route=>{
  const n=Number(new URL(route.request().url()).searchParams.get('page')||1);
  const items=Array.from({length:10},(_,i)=>{const id=(n-1)*10+i+1;return {id,code:'T'+id,name:'上限測試'+id,unit:'包',price:'10',category:'A冷凍食品',quantity:'1',batches:[{id,version:1,quantity:'1',reserved_quantity:'0',expires_on:'2027-12-31',saleable:true}]};});
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items,total:210,page:n,page_size:10})});
 });
 await page.locator('[data-inventory-mode="table"]').click();
 for(let n=1;n<=20;n++){
  await page.locator(`[data-count-batch="${(n-1)*10+1}"]`).waitFor();
  await page.locator('[data-count-batch]').evaluateAll(inputs=>inputs.forEach(input=>{input.value='2';input.dispatchEvent(new Event('input',{bubbles:true}));}));
  await page.locator(`[data-action="page"][data-page="${n+1}"]`).click();
 }
 await page.locator('[data-count-batch="201"]').waitFor();
 assert(await page.locator('[data-count-batch="201"]').isDisabled(),'201st draft is blocked without losing the first 200');
 assert((await page.locator('#stocktake-summary').innerText()).includes('200'));
 await page.locator('[data-action="page"][data-page="20"]').click();
 await page.locator('[data-count-batch="191"]').fill('');
 await page.locator('[data-action="page"][data-page="21"]').click();
 await page.locator('[data-count-batch="201"]').waitFor();
 assert(!(await page.locator('[data-count-batch="201"]').isDisabled()),'clearing one draft releases capacity');
 console.log('PASS: 200-draft limit and capacity recovery, with no database writes.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
