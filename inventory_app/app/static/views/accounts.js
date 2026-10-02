import {S,$,api,esc,dialog,formSubmit,toast} from '../app.js';

export async function accountManager(){
  const systemAdmin=S.account?.role==='admin',roleNames={admin:'系統管理員',owner:'老闆',staff:'員工'};
  const canManage=a=>a.role==='staff'||(systemAdmin&&a.role==='owner');
  dialog('登入帳號','<p class="muted">正在讀取帳號…</p>','帳號管理');
  try{
    const data=await api('/accounts');
    dialog('登入帳號',`<p class="muted">目前登入：${esc(S.account?.email)}（${roleNames[S.account?.role]}）。${systemAdmin?'可新增老闆與員工，管理帳號的登入權限。':'可新增及管理員工帳號。'}</p><form id="add-account" class="account-add"><label>要授權的 Google Email<input name="email" type="email" autocomplete="off" placeholder="例如 name@gmail.com" maxlength="254" required></label>${systemAdmin?'<label>帳號角色<select name="role"><option value="staff">員工 · 商品、盤點與訂單</option><option value="owner">老闆 · 店務與員工帳號管理</option></select></label>':'<p class="muted">新增角色：員工，可管理商品、盤點及處理訂單。</p>'}<button class="primary" type="submit">新增可登入帳號</button><p class="error" role="alert"></p></form><p class="muted">新增後即可用指定帳號登入，不會寄送邀請信。請使用 Gmail 或 Google Workspace 帳號。</p><div class="account-list">${data.items.map(a=>`<article class="account-row"><div><strong>${esc(a.name||'尚未登入')}</strong><p class="account-email">${esc(a.email)}</p><small>${roleNames[a.role]} · ${a.active?'可登入':'已停用'}${a.last_login?' · 上次登入 '+esc(a.last_login.slice(0,16).replace('T',' ')):''}</small></div>${canManage(a)?`<button class="${a.active?'danger':'primary'}" data-account="${a.id}" data-active="${!a.active}">${a.active?'停用帳號':'重新啟用'}</button>`:`<span class="badge normal">${roleNames[a.role]}</span>`}</article>`).join('')}</div><p class="muted">停用後，該帳號已登入的裝置也會失去後台權限。操作紀錄仍會保留。</p>`,'帳號管理');
    formSubmit($('#add-account'),async form=>{await api('/accounts',{email:form.get('email'),role:form.get('role')||'staff'});S.dialogDirty=false;await accountManager();toast('帳號已新增，可使用 Google 登入');});
    document.querySelectorAll('[data-account]').forEach(button=>button.onclick=async()=>{
      const active=button.dataset.active==='true';
      if(!active&&!confirm('確定停用這個帳號？已登入的裝置也會失去權限。'))return;
      button.disabled=true;
      try{await api('/accounts/'+button.dataset.account,{active});await accountManager();toast(active?'帳號已啟用':'帳號已停用');}
      catch(error){toast(error.message);button.disabled=false;}
    });
  }catch(error){dialog('登入帳號',`<p class="error" role="alert">${esc(error.message)}</p>`,'帳號管理');}
}
