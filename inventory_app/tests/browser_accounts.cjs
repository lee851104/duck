// Isolated UI fixture: all requests intercepted; no real account or inventory changes.
const {chromium}=require('C:/Users/咖波/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../app'),output=path.resolve(__dirname,'../.qa');
fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 try{for(const width of [1366,390]){
  const page=await browser.newPage({viewport:{width,height:844}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  let state={authenticated:false,csrf:'test',auth_mode:'google',google_ready:true,setup_required:false},googleStart=false,expired=false;
  const accounts=[{id:1,email:'admin@gmail.com',name:'管理員',role:'admin',active:1,last_login:'2026-10-02T10:00:00'}];
  await page.route('**/*',async route=>{
   const u=new URL(route.request().url()),method=route.request().method();
   if(u.pathname==='/api/session')return route.fulfill({json:state});
   if(u.pathname==='/auth/google/start'){googleStart=true;return route.fulfill({contentType:'text/html',body:'<p>Google redirect fixture</p>'});}
   if(u.pathname==='/api/meta')return route.fulfill({json:{today:'2026-10-02',categories:[],products:[]}});
   if(u.pathname==='/api/products')return route.fulfill({json:{items:[],total:0,page:1,page_size:10}});
   if(u.pathname==='/api/accounts'&&method==='GET')return expired?route.fulfill({status:401,json:{error:{message:'請先登入'}}}):route.fulfill({json:{items:accounts}});
   if(u.pathname==='/api/accounts'&&method==='POST'){
    assert.equal(route.request().headers()['x-csrf-token'],'test');
    const body=route.request().postDataJSON(),id=accounts.length+1;
    accounts.push({id,email:body.email,name:'',role:body.role,active:1,last_login:null});
    return route.fulfill({status:201,json:{id}});
   }
   if(u.pathname==='/api/accounts/2'){accounts[1].active=+route.request().postDataJSON().active;return route.fulfill({json:{ok:true}});}
   if(u.pathname==='/api/login'){assert.equal(route.request().postDataJSON().password,'test-password');state.authenticated=true;return route.fulfill({json:state});}
   const file=u.pathname==='/'?path.join(root,'templates/index.html'):path.join(root,u.pathname);
   if(fs.existsSync(file))return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'image/png'});
   return route.abort();
  });
  await page.goto('http://localhost:9876/');await page.locator('#google-login').waitFor();
  assert.equal(await page.locator('#password').isVisible(),false);
  assert.equal(await page.locator('.customer-entry').getAttribute('href'),'/shop');
  assert.ok((await page.locator('#google-login').boundingBox()).height>=48);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(output,`google-login-${width}.png`),fullPage:true});
  await page.locator('#google-login').click();await page.waitForURL('**/auth/google/start');assert.ok(googleStart);
  state.google_ready=false;await page.goto('http://localhost:9876/');await page.locator('#google-login').waitFor();assert.ok(await page.locator('#google-login').isDisabled());
  state={...state,authenticated:true,google_ready:true,account:accounts[0]};await page.reload();await page.locator('#settings').click();await page.locator('#manage-accounts').click();
  await page.locator('#add-account input').fill('staff@gmail.com');await page.getByRole('button',{name:'新增可登入帳號'}).click();
  await page.getByRole('button',{name:'停用帳號',exact:true}).waitFor();
  assert.equal(await page.locator('.account-row').count(),2);
  await page.getByRole('button',{name:'停用帳號',exact:true}).click();await page.getByRole('button',{name:'重新啟用'}).waitFor();assert.equal(accounts[1].active,0);
  await page.getByRole('button',{name:'重新啟用'}).click();await page.getByRole('button',{name:'停用帳號',exact:true}).waitFor();assert.equal(accounts[1].active,1);
  await page.locator('#add-account input').fill('store-owner@gmail.com');await page.locator('#add-account select').selectOption('owner');await page.getByRole('button',{name:'新增可登入帳號'}).click();await page.locator('[data-account="3"]').waitFor();assert.equal(accounts[2].role,'owner');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.ok(await page.locator('#dialog').evaluate(el=>el.scrollWidth<=el.clientWidth));
  await page.screenshot({path:path.join(output,`accounts-${width}.png`),fullPage:true});
  state.account=accounts[2];await page.reload();await page.locator('#settings').click();await page.locator('#manage-accounts').click();await page.locator('#add-account').waitFor();assert.equal(await page.locator('#add-account select').count(),0);assert.equal(await page.locator('[data-account="3"]').count(),0);assert.equal(await page.locator('[data-account="1"]').count(),0);
  await page.locator('#dialog-close').click();await page.locator('#settings').click();expired=true;state.authenticated=false;await page.locator('#manage-accounts').click();await page.locator('#google-login').waitFor();assert.equal(await page.locator('#dialog').isVisible(),false);assert.match(await page.locator('#auth-error').innerText(),/過期/);expired=false;state.authenticated=true;
  state.account=accounts[1];await page.reload();await page.locator('#settings').click();await page.locator('#begin-import').waitFor();assert.equal(await page.locator('#manage-accounts').count(),0);
  state={authenticated:false,csrf:'test',auth_mode:'password',setup_required:false};await page.reload();await page.locator('#password').fill('test-password');await page.getByRole('button',{name:'進入工作台'}).click();await page.locator('#app').waitFor();
  assert.deepEqual(errors,[]);await page.close();
 }console.log('PASS Google login, missing configuration, guest entry, admin/owner/staff controls, expiry recovery and mobile layout');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
