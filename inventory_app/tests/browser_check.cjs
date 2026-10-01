const {chromium}=require('C:/Users/咖波/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs');const path=require('path');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1366,height:768}});
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const out=path.resolve(__dirname,'../.qa/screenshots');fs.mkdirSync(out,{recursive:true});
 await page.goto('http://127.0.0.1:8766');
 await page.locator('#password').fill('qa-local-testing-only');await page.locator('#auth-form button').click();
 await page.locator('.stats').waitFor();
 const findings=[];
 for(const viewport of [{width:1366,height:768},{width:390,height:844}]){
  await page.setViewportSize(viewport);
  for(const view of ['dashboard','inventory','catalog','history']){
   await page.locator(`[data-nav="${view}"]`).click();
   await page.waitForFunction(v=>document.querySelector(`[data-nav="${v}"]`).classList.contains('active'),view);
   await page.waitForTimeout(450);
   const dimensions=await page.evaluate(()=>{
    const root=document.documentElement;
    const area=document.querySelector('.table-wrap,.list-space,.catalog-grid');
    const children=area?[...area.querySelectorAll('tbody tr,.alert-row,.catalog-card')]:[];
    const bound=area?.getBoundingClientRect();
    return {width:innerWidth,height:innerHeight,scrollWidth:root.scrollWidth,scrollHeight:root.scrollHeight,
      contentClipped:children.some(el=>el.getBoundingClientRect().bottom>(bound?.bottom||0)+1),rows:children.length};
   });
   findings.push({view,...dimensions});
   await page.screenshot({path:path.join(out,`${viewport.width}-${view}.png`)});
  }
 }
 // Follow the real visible receipt/count/issue flow on the first matching product.
 await page.setViewportSize({width:1366,height:768});
 await page.locator('[data-nav="inventory"]').click();await page.locator('[data-action="operation"][data-type="receive"]').first().click();
 await page.locator('[name="quantity"]').fill('3');await page.locator('[name="expires_on"]').fill('2027-12-31');
 await page.locator('#receive-form button[type="submit"]').click();await page.waitForFunction(()=>!document.querySelector('#dialog').open);
 await page.locator('[data-action="operation"][data-type="count"]').first().click();
 await page.locator('[name="actual_quantity"]').fill('2');await page.locator('[name="expires_on"]').fill('2027-01-01');
 await page.locator('[name="saleable_confirmed"]').check();await page.locator('#count-form button[type="submit"]').click();
 await page.waitForFunction(()=>!document.querySelector('#dialog').open);
 await page.locator('[data-action="operation"][data-type="issue"]').first().click();
 await page.locator('[name="total"]').fill('1');await page.locator('#suggest').click();await page.locator('#issue-form button[type="submit"]').click();
 await page.waitForFunction(()=>!document.querySelector('#dialog').open);
 const result={findings,errors,operations:'receipt/count/issue completed'};
 fs.writeFileSync(path.resolve(__dirname,'../.qa/browser-results.json'),JSON.stringify(result,null,2));
 console.log(JSON.stringify(result));await browser.close();
 if(errors.length||findings.some(f=>f.scrollWidth>f.width||f.scrollHeight>f.height||f.contentClipped))process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
