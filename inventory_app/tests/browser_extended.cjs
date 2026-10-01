const {chromium}=require('C:/Users/咖波/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:390,height:844}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8766');await page.locator('#password').fill('qa-local-testing-only');await page.locator('#auth-form button').click();await page.locator('.stats').waitFor();
 await page.getByRole('button',{name:'資料管理',exact:true}).first().click();await page.locator('#begin-import').click();
 await page.locator('#import-form').waitFor({timeout:60000});
 const importText=await page.locator('#dialog-body').innerText();
 if(!importText.includes('176')||!importText.includes('186')||!importText.includes('96'))throw Error('Raw preview counts do not match');
 const conflictFields=await page.locator('[data-code]').count();if(!conflictFields)throw Error('Code conflicts not surfaced');
 const importFits=await page.locator('#dialog-body').evaluate(el=>el.scrollHeight<=el.clientHeight+1);
 if(!importFits)throw Error('Import dialog requires a long scroll on mobile');
 await page.screenshot({path:path.resolve(__dirname,'../.qa/screenshots/390-import.png')});await page.locator('#dialog-close').click();
 // Native input validation and keyboard focus must remain inside the usable dialog.
 await page.locator('[data-nav="inventory"]').click();await page.locator('[data-action="operation"][data-type="receive"]').first().click();
 await page.locator('[name="quantity"]').fill('2');
 await page.locator('#receive-form button[type="submit"]').click();
 await page.locator('#receive-form .error').waitFor();
 if(await page.locator('[name="quantity"]').inputValue()!=='2')throw Error('Failed save lost input');
 await page.locator('[name="expires_on"]').fill('2027-12-31');
 await page.setViewportSize({width:390,height:450});
 await page.locator('#receive-form button[type="submit"]').scrollIntoViewIfNeeded();
 await page.screenshot({path:path.resolve(__dirname,'../.qa/screenshots/390-keyboard.png')});
 await page.locator('#receive-form button[type="submit"]').click();await page.waitForFunction(()=>!document.querySelector('#dialog').open);
 // Request failure must not show a healthy empty inventory.
 await page.setViewportSize({width:1366,height:768});
 await page.route('**/api/dashboard?*',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'暫時無法讀取'}})}));
 await page.locator('[data-nav="dashboard"]').click();await page.locator('[data-action="retry"]').waitFor();
 if(await page.locator('.stat-num').count())throw Error('Failed dashboard shows counts');
 await page.unroute('**/api/dashboard?*');await page.locator('[data-action="retry"]').click();await page.locator('.stats').waitFor();
 await page.route('**/api/backups',r=>r.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:{message:'備份未完成'}})}));
 await page.getByRole('button',{name:'資料管理',exact:true}).first().click();await page.locator('#backup-now').click();await page.waitForTimeout(250);
 if(await page.locator('#backup-now').isDisabled())throw Error('Backup failure leaves retry button disabled');
 const result={rawPreview:{rows:176,cards:186,invoice:96,visibleConflicts:conflictFields},failedSaveRetainsInput:true,shortViewportFormUsable:true,loadFailureShowsRetry:true,errors};
 fs.writeFileSync(path.resolve(__dirname,'../.qa/extended-results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));await browser.close();if(errors.length)process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
