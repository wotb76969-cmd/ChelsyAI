"""Regression matrix for the first-party API on a disposable local database."""
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request,urlopen
from urllib.error import HTTPError

def main():
    if len(sys.argv)!=2:raise SystemExit('access.py OUTPUT.json')
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    results=[]
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['CHELSY_DATA_DIR']=tmp
        import core,auth,host_server
        from auth import vault
        server=host_server.make_server(0)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        origin='http://127.0.0.1:'+str(server.server_port)+'/api/v3'
        def call(method,path,token=None,payload=None):
            headers={'Content-Type':'application/json'}
            if token:headers['Authorization']='Bearer '+token
            req=Request(origin+path,data=None if payload is None else json.dumps(payload).encode(),headers=headers,method=method)
            try:
                with urlopen(req,timeout=20) as r:return r.status,json.load(r)
            except HTTPError as e:return e.code,json.load(e)
        roles=['reader-a','reader-b','admin-a','admin-b']
        users={}
        for role in roles:
            pw=secrets.token_urlsafe(24)
            with core.db() as conn:u=auth.create_user(conn,role+'@example.invalid',pw,role='admin' if role.startswith('admin') else 'user')
            code,data=call('POST','/auth/login',payload=dict(email=u['email'],password=pw))
            assert code==200
            token=data['access_token']
            fid=call('POST','/memory',token,{'text':role+' saved fact'})[1]['id']
            hid=str(uuid.uuid4())
            with core.db() as conn:
                key=vault.unlock(conn,u['id'],pw)
                conn.execute("INSERT INTO private_history(id,user_id,created,payload) VALUES(?,?,'2026-11-18',?)",(hid,u['id'],vault.seal(key,{'question':role,'answer':'sample'},hid)))
            users[role]=(token,fid,hid,u['id'],data['session_id'])
        def record(case,actual,expected):
            results.append(dict(case=case,actual=actual,expected=expected,passed=actual==expected))
        for role,(token,fid,hid,uid,sid) in users.items():
            for path in ['/me','/me/sessions','/tasks','/history','/artifacts','/memory','/export','/cabinet/overview']:
                code,_=call('GET',path,token)
                record(role+' '+path,code,200)
            for path in ['/admin/status','/admin/users','/admin/errors']:
                record(role+' '+path,call('GET',path,token)[0],200 if role.startswith('admin') else 403)
            for other,(_,fid2,hid2,_,sid2) in users.items():
                if other==role:continue
                record(role+' cannot favorite '+other,call('POST','/history/'+hid2,token,{'favorite':True})[0],404)
                record(role+' cannot delete history '+other,call('DELETE','/history/'+hid2,token)[0],404)
                record(role+' cannot delete fact '+other,call('DELETE','/memory/'+fid2,token)[0],404)
                record(role+' cannot revoke session '+other,call('DELETE','/me/sessions/'+sid2,token)[1].get('revoked'),False)
                record(role+' export excludes '+other,other+' saved fact' in json.dumps(call('GET','/export',token)[1]),False)
        for path in ['/me','/me/sessions','/tasks','/history','/artifacts','/memory','/export','/cabinet/overview','/admin/status','/admin/users']:
            record('anonymous '+path,call('GET',path)[0],401)
        with ThreadPoolExecutor(max_workers=10) as pool:
            record('10 simultaneous checks of active sessions',list(pool.map(lambda i:call('GET','/me',users[roles[i%4]][0])[0],range(10))),[200]*10)
        server.shutdown();server.server_close()
    out={'environment':'local real HTTP and SQLite; test content; no external targets','total':len(results),'passed':sum(row['passed'] for row in results),'cases':results}
    Path(sys.argv[1]).write_text(json.dumps(out,indent=2))
    print(out['passed'], '/', out['total'])
    return int(out['passed']!=out['total'])
if __name__=='__main__':sys.exit(main())
