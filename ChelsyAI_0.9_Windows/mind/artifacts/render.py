import json
import os
from pathlib import Path
import subprocess
import sys
from dataclasses import asdict
from .builder import BuiltArtifact,MIME,safe_filename,_sha256

def render(spec,folder):
    if os.environ.get('CHELSY_RENDER_MODE','container')=='container':
        command=['docker','run','--rm','-i','--pull=never','--network=none','--read-only','--cap-drop=ALL',
                 '--security-opt=no-new-privileges','--pids-limit=48','--memory=512m','--cpus=1','--user=65532:65532',
                 '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777','--ulimit','cpu=45:50',
                 'chelsy-renderer:0.9.4']
        try:
            result=subprocess.run(command,input=json.dumps(asdict(spec)).encode(),capture_output=True,timeout=75)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise ValueError('Обработчик файлов недоступен.') from exc
        if result.returncode or not 0<len(result.stdout)<=25*1024*1024:
            raise ValueError('Обработчик файлов отклонил операцию.')
        path=folder/('document.'+spec.format)
        path.write_bytes(result.stdout)
        return BuiltArtifact(spec.format,MIME[spec.format],safe_filename(spec.title,spec.format),path,_sha256(path),path.stat().st_size)
    if sys.platform!='linux' or os.environ.get('CHELSY_RENDER_MODE')!='landlock':
        raise ValueError('Неизвестный профиль изоляции обработчика.')
    worker=Path(__file__).with_name('worker.py')
    env={k:v for k,v in os.environ.items() if k in ('PATH','SystemRoot','SYSTEMROOT','WINDIR','TEMP','TMP','LD_LIBRARY_PATH')}
    env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',TMPDIR=str(folder),XDG_CACHE_HOME=str(folder))
    command=[sys.executable,'--render-worker',str(folder)] if getattr(sys,'frozen',False) else [sys.executable,str(worker),str(folder)]
    result=subprocess.run(command,input=json.dumps(asdict(spec)),text=True,encoding='utf-8',capture_output=True,cwd=folder,env=env,timeout=60)
    if result.returncode: raise ValueError('Изолированный обработчик не смог проверить или создать файл.')
    path=folder/('document.'+spec.format)
    return BuiltArtifact(spec.format,MIME[spec.format],safe_filename(spec.title,spec.format),path,_sha256(path),path.stat().st_size)
