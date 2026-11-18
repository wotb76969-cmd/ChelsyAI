"""Download fixed public base weights to a chosen directory and verify every file."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
import os
import tempfile

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('destination',type=Path);args=p.parse_args()
    manifest=json.loads(Path(__file__).with_name('base-manifest.json').read_text())
    args.destination.mkdir(exist_ok=True,parents=True)
    for name,expected in manifest['files'].items():
        target=args.destination/name
        if target.is_file() and sha(target)==expected: continue
        url='https://huggingface.co/'+manifest['repo']+'/resolve/'+manifest['revision']+'/'+name
        with tempfile.NamedTemporaryFile(dir=args.destination,delete=False) as tmp:
            path=Path(tmp.name)
        try:
            with urlopen(url,timeout=120) as response,path.open('wb') as out:
                for chunk in iter(lambda:response.read(1024*1024),b''):out.write(chunk)
            if sha(path)!=expected: raise ValueError('Ошибка SHA-256: '+name)
            os.replace(path,target)
            print('OK',name,flush=True)
        finally:path.unlink(missing_ok=True)
if __name__=='__main__':main()
