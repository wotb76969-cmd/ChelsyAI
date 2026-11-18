const api=window.ChelsyAuth.request;
const output=document.querySelector('#history'),status=document.querySelector('#status');
let records=[];
function draw(){
  const query=document.querySelector('#query').value.toLocaleLowerCase();
  output.replaceChildren();
  for(const row of records.filter(r=>(r.question+' '+r.answer).toLocaleLowerCase().includes(query))){
    const card=document.createElement('article');card.className='form-card';
    for(const value of [row.created,row.question,row.answer]){
      const p=document.createElement('p');p.textContent=value;card.append(p);
    }
    for(const [label,action] of [[row.favorite?'Убрать из избранного':'В избранное',()=>api('/history/'+row.id,{method:'POST',body:{favorite:!row.favorite}})],['Удалить',()=>confirm('Удалить этот диалог и сохранённый текст задания?')&&api('/history/'+row.id,{method:'DELETE'})]]){
      const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=async()=>{try{if(await action())await load();}catch(e){status.textContent=e.message;}};card.append(b);
    }
    output.append(card);
  }
}
async function load(){
  try{records=(await api('/history')).history;draw();status.textContent='Диалогов: '+records.length;}
  catch(e){status.textContent=e.status===401?'Войдите в кабинет.':'История недоступна. '+e.message;}
}
document.querySelector('#refresh').onclick=load;
document.querySelector('#query').oninput=draw;
load();
