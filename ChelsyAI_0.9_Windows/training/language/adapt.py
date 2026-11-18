"""CPU-reproducible supervised LoRA on prepared, non-personal bilingual examples."""
import argparse
import hashlib
import json
import platform
import random
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = Path(__file__).resolve().parent
BASE = 'Qwen/Qwen2.5-0.5B-Instruct'
REVISION = '7ae557604adf67be50417f59c2c2f167def9a775'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default=BASE)
    parser.add_argument('--output', type=Path, default=ROOT / 'adapter')
    args = parser.parse_args()
    torch.manual_seed(42)
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    tokenizer = AutoTokenizer.from_pretrained(args.base, revision=REVISION)
    base = AutoModelForCausalLM.from_pretrained(args.base, revision=REVISION, torch_dtype=torch.float32, attn_implementation='eager')
    model = get_peft_model(base, LoraConfig(r=4, lora_alpha=8, target_modules=['q_proj','v_proj'], layers_to_transform=[22,23], task_type='CAUSAL_LM'))
    model.peft_config['default'].base_model_name_or_path = BASE
    model.peft_config['default'].revision = REVISION
    records = [json.loads(line) for line in (ROOT/'corpus.jsonl').read_text(encoding='utf8').splitlines()]
    def loss(row):
        chat = [{'role':'user','content':row['prompt']}]
        prompt = tokenizer.apply_chat_template(chat, add_generation_prompt=True)
        ids = tokenizer.apply_chat_template(chat + [{'role':'assistant','content':row['answer']}], return_tensors='pt')
        labels = ids.clone()
        labels[:,:len(prompt)] = -100
        return model(ids, labels=labels, use_cache=False).loss
    @torch.no_grad()
    def evaluate():
        model.eval()
        return {split: sum(float(loss(row)) for row in records if row['split']==split) / sum(row['split']==split for row in records) for split in ('validation','test')}
    before = evaluate()
    model.train()
    opt = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=0.0008)
    train = [row for row in records if row['split']=='train']
    random.Random(42).shuffle(train)
    for row in train:
        opt.zero_grad()
        loss(row).backward()
        opt.step()
    after = evaluate()
    args.output.mkdir(parents=True,exist_ok=True)
    model.save_pretrained(args.output, save_embedding_layers=False)
    weights = args.output/'adapter_model.safetensors'
    report = dict(base=BASE,revision=REVISION,seed=42,steps=len(train),trainable_parameters=model.get_nb_trainable_parameters()[0],
                  evaluation='mean per-example answer token cross-entropy, lower is better', before=before,after=after,
                  platform=platform.platform(),torch=torch.__version__,threads=2,
                  corpus_sha256=hashlib.sha256((ROOT/'corpus.jsonl').read_bytes()).hexdigest(),adapter_sha256=hashlib.sha256(weights.read_bytes()).hexdigest())
    (args.output/'metrics.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report)
if __name__=='__main__':
    main()
