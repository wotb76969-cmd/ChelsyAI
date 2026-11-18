document.addEventListener('DOMContentLoaded',()=>{
  const api=window.ChelsyAuth.request;
  const el=id=>document.getElementById(id);
  const status=el('account-status');
  const show=msg=>{status.hidden=false;status.textContent=msg;};
  const node=(tag,value)=>{const n=document.createElement(tag);n.textContent=value;return n;};
  async function action(fn,button){
    if(button)button.disabled=true;
    try{return await fn();}catch(err){show(err.message);return null;}finally{if(button)button.disabled=false;}
  }
  function button(box,label,run){
    const b=node('button',label);b.type='button';b.className='btn btn-small';b.onclick=()=>action(run,b);box.append(b);
  }
  function bindForm(id,fn){
    const f=el(id);if(!f)return;
    f.onsubmit=e=>{e.preventDefault();action(()=>fn(f),f.querySelector('[type=submit]'));};
  }
  function download(blob,name){
    const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),2000);
  }
  async function overview(){
    const d=await api('/cabinet/overview');
    el('cabinet-overview').textContent='Host '+d.host.version+' · '+d.host.runtime+' · Активных задач: '+d.tasks_active+' · Файлов: '+d.files_count+' · '+d.files_bytes+' байт из '+d.quota_mb_limit+' МБ';
  }
  async function files(){
    const {artifacts}=await api('/artifacts'),box=el('files-list');
    box.replaceChildren();
    if(!artifacts.length)box.textContent='Файлов пока нет.';
    for(const a of artifacts){
      const row=node('article','');row.append(node('h3',a.title),node('p',a.format.toUpperCase()+' · '+a.size_bytes+' байт · v'+a.version+' · '+a.created));
      const path='/artifacts/'+a.id;
      button(row,'Просмотр',async()=>{const p=(await api(path)).artifact.preview;el('preview').textContent=JSON.stringify(p,null,2);});
      button(row,'Скачать',async()=>download(await (await api(path+'/download',{raw:true})).blob(),a.filename));
      button(row,'Создать ещё раз',async()=>{await api('/tasks/'+a.task_id+'/repeat',{method:'POST',body:{idempotency_key:crypto.randomUUID()}});await files();});
      button(row,'Удалить',async()=>{if(confirm('Удалить этот файл с Host?')){await api(path,{method:'DELETE'});el('preview').textContent='';await files();}});
      box.append(row);
    }
  }
  async function tasks(){
    const list=(await api('/tasks')).tasks,box=el('tasks-list');box.replaceChildren();
    if(!list.length)box.textContent='Очередь пуста.';
    for(const t of list){
      const row=node('p',t.kind+' · '+t.status+' · '+Math.round(t.progress*100)+'% '+(t.error||'')+' ');
      if(['queued','running'].includes(t.status))button(row,'Отменить',async()=>{await api('/tasks/'+t.id+'/cancel',{method:'POST',body:{}});await tasks();});
      if(['failed','cancelled'].includes(t.status))button(row,'Повторить',async()=>{await api('/tasks/'+t.id+'/repeat',{method:'POST',body:{idempotency_key:crypto.randomUUID()}});await tasks();});
      box.append(row);
    }
  }
  async function facts(){
    const data=await api('/memory'),box=el('facts-list');box.replaceChildren();
    if(!data.facts.length)box.textContent='Сохранённых фактов пока нет.';
    for(const f of data.facts){const row=node('p',f.text+' ');button(row,'Удалить',async()=>{if(confirm('Удалить этот факт?')){await api('/memory/'+f.id,{method:'DELETE'});await facts();}});box.append(row);}
  }
  bindForm('fact-form',async f=>{await api('/memory',{method:'POST',body:{text:f.elements.text.value}});f.reset();await facts();show('Факт сохранён.');});
  async function sessions(){
    const list=(await api('/me/sessions')).sessions,box=el('sessions-list');box.replaceChildren();
    for(const s of list){const p=node('p',(s.device_label||'Устройство')+' · '+s.last_seen+' · '+(s.revoked?'Отозвана':'Действует')+' ');
      if(!s.revoked)button(p,'Завершить',async()=>{if(confirm('Закрыть эту сессию?')){await api('/me/sessions/'+s.id,{method:'DELETE'});await sessions();}});box.append(p);}
  }
  function panel(id){
    document.querySelectorAll('.cabinet-panel').forEach(p=>{p.hidden=p.id!=='panel-'+id;p.classList.toggle('is-active',!p.hidden);});
    document.querySelectorAll('[data-panel]').forEach(b=>b.classList.toggle('is-active',b.dataset.panel===id));
    const f={overview,security:sessions,files,tasks,memory:facts}[id];if(f)action(f);
  }
  document.querySelectorAll('[data-panel]').forEach(b=>b.onclick=()=>panel(b.dataset.panel));
  bindForm('profile-form',async f=>{
    await api('/me',{method:'POST',body:Object.fromEntries(new FormData(f).entries())});
    el('account-name').textContent=f.elements.display_name.value;show('Профиль сохранён.');
  });
  bindForm('avatar-form',async f=>{
    const file=f.elements.photo.files[0];if(!file||file.size>1000000)throw Error('Выберите изображение до 1 МБ.');
    const reader=new FileReader();const data=await new Promise((resolve,reject)=>{reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
    await api('/me/avatar',{method:'POST',body:{image:data.split(',')[1]}});el('avatar').src='/api/v3/me/avatar?t='+Date.now();el('avatar').hidden=false;show('Аватар сохранён.');
  });
  bindForm('password-form',async f=>{await api('/me/password',{method:'POST',body:Object.fromEntries(new FormData(f))});location.assign('login.html');});
  bindForm('email-form',async f=>{const r=await api('/me/email',{method:'POST',body:Object.fromEntries(new FormData(f))});if(r.changed)location.assign('login.html');else show('Введите код, отправленный на новый адрес.');});
  let requestId=null;
  const prompt=el('mind-form').elements.message;
  prompt.oninput=()=>{requestId=null;};
  bindForm('mind-form',async f=>{
    requestId??=crypto.randomUUID();show('Host обрабатывает задачу…');
    const data=await api('/mind/run',{method:'POST',body:{message:prompt.value,idempotency_key:requestId}});
    el('mind-answer').textContent=data.answer||data.meta.status;requestId=null;show(data.artifact_id?'Документ доступен в разделе «Мои файлы».':'Статус: '+data.meta.status);await tasks();
  });
  bindForm('delete-request',async f=>{if(confirm('Зарегистрировать запрос удаления аккаунта и личных данных?')){await api('/me/deletion',{method:'POST',body:{password:f.elements.password.value}});f.reset();show('Запрос принят.');}});
  el('export').onclick=()=>action(async()=>download(new Blob([JSON.stringify(await api('/export'),null,2)],{type:'application/json'}),'chelsy-export.json'));
  el('revoke-other-sessions').onclick=()=>action(async()=>{if(confirm('Завершить все другие сессии?')){await api('/me/sessions',{method:'DELETE'});await sessions();}});
  el('memory-enabled').onchange=e=>action(async()=>{try{await api('/me',{method:'POST',body:{memory_enabled:e.target.checked}});}catch(err){e.target.checked=!e.target.checked;throw err;}});
  el('refresh-tasks').onclick=()=>action(tasks);
  el('signout-button').onclick=()=>action(async()=>{await api('/auth/logout',{method:'POST',body:{}});location.assign('login.html');});
  (async()=>{
    try{
      const {user}=await api('/me');
      el('account-content').hidden=false;
      for(const [id,v] of Object.entries({'account-name':user.display_name,'account-email':user.email,'account-plan':'Квота Host','account-verified':user.email_verified?'Да':'Нет'}))el(id).textContent=v;
      const f=el('profile-form');for(const k of ['display_name','locale','timezone'])f.elements[k].value=user[k];
      el('memory-enabled').checked=user.memory_enabled;
      if(user.has_avatar){el('avatar').src='/api/v3/me/avatar';el('avatar').hidden=false;}
      if(user.must_change_password){panel('security');show('Измените первоначальный пароль для доступа к кабинету.');}else{show('');await overview();}
    }catch(e){if(e.status===401)location.assign('login.html');else show('Не удалось открыть кабинет. '+e.message);}
  })();
});
