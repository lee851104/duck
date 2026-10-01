const {chromium}=require('C:/Users/咖波/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:390,height:844}});
 await page.goto('http://127.0.0.1:8766');await page.locator('#password').fill('qa-local-testing-only');await page.locator('#auth-form button').click();await page.locator('.stats').waitFor();
 await page.locator('[data-nav="inventory"]').click();await page.locator('[data-action="operation"][data-type="receive"]').first().click();
 await page.evaluate(()=>{
   const sizes=[...document.querySelectorAll('#dialog,#dialog *')].map(el=>[el,parseFloat(getComputedStyle(el).fontSize)]);
   sizes.forEach(([el,size])=>el.style.fontSize=(size*2)+'px');
 });
 await page.locator('[name="quantity"]').fill('1');
 await page.locator('#receive-form button[type="submit"]').scrollIntoViewIfNeeded();await page.locator('#receive-form button[type="submit"]').click();
 await page.locator('#receive-form .error').waitFor();
 await page.locator('[name="expires_on"]').fill('2027-12-31');
 const button=page.locator('#receive-form button[type="submit"]');await button.scrollIntoViewIfNeeded();
 const box=await button.boundingBox();if(box.y<0||box.y+box.height>844)throw Error('Large-font submit button inaccessible');
 await button.click();await page.waitForFunction(()=>!document.querySelector('#dialog').open);
 console.log(JSON.stringify({formTextScale:2,validationAndSubmitUsable:true}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
