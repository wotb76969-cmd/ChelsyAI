(() => {
  for (const key of ['chelsy_access','chelsy_refresh']) sessionStorage.removeItem(key);
  let renewal;
  async function request(path,{method='GET',body,raw=false}={},retry=true) {
    const response=await fetch('/api/v3'+path,{
      method,credentials:'same-origin',redirect:'error',cache:'no-store',
      headers:{'X-Chelsy-Request':'cabinet',...(body===undefined?{}:{'Content-Type':'application/json'})},
      body:body===undefined?undefined:JSON.stringify(body)
    });
    if (response.status===401 && retry && !path.startsWith('/auth/')) {
      const rotate=async()=>{
        const check=await fetch('/api/v3/me',{cache:'no-store',credentials:'same-origin'});
        if (!check.ok) await request('/auth/refresh',{method:'POST',body:{}},false);
      };
      renewal??=(navigator.locks?navigator.locks.request('chelsy-session',rotate):rotate()).finally(()=>{renewal=null;});
      await renewal;
      return request(path,{method,body,raw},false);
    }
    if (!response.ok) {
      const data=await response.json().catch(()=>({}));
      const error=new Error(data.message||data.error||('HTTP '+response.status));
      error.status=response.status;
      throw error;
    }
    return raw?response:response.json();
  }
  window.ChelsyAuth={request};
  document.addEventListener('DOMContentLoaded',()=>{
    const form=document.querySelector('#login-form');
    if(form) form.addEventListener('submit',async e=>{
      e.preventDefault();
      const button=form.querySelector('[type=submit]'),status=document.querySelector('#login-status');
      button.disabled=true;
      status.hidden=false;
      status.textContent='Проверяем данные…';
      try {
        await request('/auth/login',{method:'POST',body:{email:form.email.value.trim(),password:form.password.value,device_label:'Кабинет'}});
        form.password.value='';
        location.assign('account.html');
      } catch(err) {status.textContent=err.message;}
      finally {button.disabled=false;}
    });
    if(!form) request('/me').then(()=>document.querySelectorAll('a.header-login').forEach(a=>{a.href='account.html';a.textContent='Кабинет';})).catch(()=>{});
  });
})();
