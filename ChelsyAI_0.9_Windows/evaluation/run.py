"""Launch an isolated real Host, run a fixed suite, save transcripts and downloaded binaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('suite',choices=['functional','documents'])
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    out=args.out/(args.suite+'.jsonl')
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['CHELSY_DATA_DIR']=tmp
        import core,auth,host_server
        import api_v3
        srv=host_server.make_server(0)
        threading.Thread(target=srv.serve_forever,daemon=True).start()
        origin='http://127.0.0.1:'+str(srv.server_port)+'/api/v3'
        token=''
        def call(path,data=None,raw=False):
            req=Request(origin+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token} if token else {'Content-Type':'application/json'})
            try:
                with urlopen(req,timeout=600) as r: return r.status,r.read() if raw else json.load(r)
            except HTTPError as e: return e.code,json.load(e)
        email='evaluation@example.invalid'
        password=secrets.token_urlsafe(32)
        with core.db() as conn:auth.create_user(conn,email,password)
        rows=[json.loads(s) for s in (HERE/(args.suite+'.jsonl')).read_text().splitlines()]
        with out.open('w',encoding='utf8') as f:
            for i,row in enumerate(rows):
                if i%5==0:
                    status,session=call('/auth/login',dict(email=email,password=password))
                    if status!=200: raise RuntimeError('Evaluation login failed')
                    token=session['access_token']
                start=time.monotonic()
                code,result=call('/mind/run',{'message':row['prompt'],'idempotency_key':row['id']})
                record=dict(**row,http=code,seconds=round(time.monotonic()-start,2),response=result)
                if result.get('artifact_id'):
                    status,blob=call('/artifacts/'+result['artifact_id']+'/download',raw=True)
                    if status==200:
                        target=args.out/(row['id']+'.'+result['route']);target.write_bytes(blob)
                        record['sha256']=hashlib.sha256(blob).hexdigest()
                f.write(json.dumps(record,ensure_ascii=False)+'\n');f.flush()
        srv.shutdown();srv.server_close()
if __name__=='__main__': main()
