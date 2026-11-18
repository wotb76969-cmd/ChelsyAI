"""Local runtimes. Optional PEFT inference never fetches weights while serving."""
import json
import os
from functools import lru_cache
from pathlib import Path

class ModelUnavailable(RuntimeError):
    pass

class Incomplete(ValueError):
    pass

@lru_cache(maxsize=1)
def load_language_model(base, adapter):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    torch.set_num_threads(2)
    tokenizer=AutoTokenizer.from_pretrained(base,local_files_only=True)
    model=AutoModelForCausalLM.from_pretrained(base,local_files_only=True,torch_dtype=torch.float32)
    if adapter:
        model=PeftModel.from_pretrained(model,adapter,local_files_only=True)
    if os.environ.get('CHELSY_CPU_INT8')=='1':
        if adapter: model=model.merge_and_unload()
        model=torch.ao.quantization.quantize_dynamic(model,{torch.nn.Linear},dtype=torch.qint8)
    return tokenizer,model.eval()

def generate(prompt,plan):
    import ollama_client
    system = 'You are Chelsy. Use '+plan.params['language']+'. Follow the requested format. Do not invent sources, actions or download links.'
    messages=[{'role':'system','content':system},{'role':'user','content':prompt}]
    base=os.environ.get('CHELSY_LOCAL_BASE')
    try:
        if base:
            import torch
            adapter='' if os.environ.get('CHELSY_BASE_ONLY')=='1' else str(Path(__file__).resolve().parents[1]/'training/language/adapter')
            tokenizer,model=load_language_model(base,adapter)
            ids=tokenizer.apply_chat_template(messages,add_generation_prompt=True,return_tensors='pt')
            with torch.inference_mode():
                short=plan.route=='chat' and any(word in prompt.lower() for word in ('коротк','одн','только','слов','short','sentence','only','twelve','без вступления'))
                budget=80 if short else (320 if plan.route in ('docx','pdf','txt') else 768)
                result=model.generate(ids,attention_mask=torch.ones_like(ids),max_new_tokens=budget,do_sample=False,pad_token_id=tokenizer.eos_token_id)
            if int(result[0,-1]) not in {tokenizer.eos_token_id,151643}:
                raise Incomplete('Модель достигла лимита длины ответа.')
            return tokenizer.decode(result[0,ids.shape[1]:],skip_special_tokens=True).strip()
        if not ollama_client.available():
            raise ModelUnavailable()
        model=ollama_client.resolve_model(os.environ.get('CHELSY_MODEL'))
        return ollama_client.chat(model,messages,{'num_predict':2048,'temperature':0.2,'seed':42})
    except Incomplete:
        raise
    except Exception as exc:
        raise ModelUnavailable('Локальная модель недоступна. Проверьте конфигурацию Host.') from exc


def document_structure(intent,plan,fmt,generate_text):
    if fmt in ('docx','txt','pdf'):
        sections=[]
        count=intent.pages or 1
        for i in range(count):
            instruction=(f'Write section {i+1} of {count} in {intent.language} for: {intent.raw}. '
                         'First line: a specific heading. Next lines: one or two concise factual paragraphs. '
                         'Write only the actual document text, without JSON or commentary.')
            if sections:
                instruction+=' Earlier headings: '+', '.join(part['heading'] for part in sections)
            raw=generate_text(instruction,plan)
            lines=[line.strip().strip('#* ').strip() for line in raw.splitlines() if line.strip()]
            if not lines: raise Incomplete('Нет текста документа.')
            title=lines[0][:120]
            sections.append({'heading':title,'paragraphs':lines[1:] or [lines[0]],'bullets':[]})
        doc={'title':sections[0]['heading'],'sections':sections}
        check_structure(doc,fmt,count)
        return doc
    examples={
        'xlsx':{'tables':[{'headers':['category','amount'],'rows':[['example',2]],'add_total':True}]},
        'pptx':{'slides':[{'title':'heading','bullets':['point'],'notes':'speaker notes'}]},
    }
    schema={'title':'short title',**examples.get(fmt,{'sections':[{'heading':'heading','paragraphs':['body'],'bullets':[]}]})}
    count = intent.slides if fmt=='pptx' else intent.pages if fmt in ('docx','pdf') else None
    question=(f'Write a complete {fmt} in {intent.language} for this request: {intent.raw}\n'
              f'Return only valid JSON. Shape: {json.dumps(schema)}. Replace all example values. '
              'Use plain text and numeric cells. Do not include links or formulas unless given as source data. ')
    if count:
        question+=f'Exactly {count} '+('slides.' if fmt=='pptx' else 'sections. Each section starts a page.')
    for attempt in range(2):
        raw=generate_text(question,plan)
        try:
            raw=raw.strip()
            if raw.startswith('```') and raw.endswith('```'):
                raw=raw.partition('\n')[2][:-3].strip()
            if len(raw)>90000:
                raise ValueError()
            doc=json.loads(raw)
            check_structure(doc,fmt,count)
            return doc
        except (ValueError,TypeError,KeyError,AttributeError):
            question+=' Previous output failed validation. Return the exact JSON schema and requested count.'
    raise Incomplete('Модель не вернула корректную структуру документа после повторной попытки.')


def check_structure(doc,fmt,count):
    def text(value,limit=4000):
        if not isinstance(value,str) or not value.strip() or len(value)>limit or any(ord(c)<32 and c not in '\n\t' for c in value):
            raise ValueError()
    def items(value,maximum,minimum=0):
        if not isinstance(value,list) or not minimum<=len(value)<=maximum:
            raise ValueError()
        return value
    text(doc['title'],120)
    field={'xlsx':'tables','pptx':'slides'}.get(fmt,'sections')
    if set(doc)-{'title',field}: raise ValueError()
    entries=items(doc[field],50,1)
    if count and len(entries)!=count: raise ValueError()
    for part in entries:
        if fmt=='xlsx':
            columns=items(part['headers'],32,1)
            for label in columns: text(label,120)
            for row in items(part['rows'],250,1):
                items(row,len(columns),len(columns))
                for cell in row:
                    if isinstance(cell,str): text(cell)
                    elif type(cell) not in (int,float) or not -1e15<=cell<=1e15: raise ValueError()
            if type(part.get('add_total',False)) is not bool: raise ValueError()
        elif fmt=='pptx':
            text(part['title'],120)
            for line in items(part['bullets'],10,1): text(line,550)
            text(part['notes'])
        else:
            text(part['heading'],160)
            for line in items(part['paragraphs'],24,1): text(line)
            for line in items(part.get('bullets',[]),24): text(line)
