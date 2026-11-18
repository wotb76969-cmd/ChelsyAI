"""Prepare a source Host in its own venv. Does not change firewall, DNS or system services."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv

def main():
    root=Path(__file__).resolve().parent
    host=root/'ChelsyAI_0.9_Windows'
    p=argparse.ArgumentParser()
    p.add_argument('--runtime',choices=('adapter','ollama'),default='ollama')
    p.add_argument('--state',type=Path,required=True,help='Directory for data and base weights, outside the source tree')
    p.add_argument('--no-renderer',action='store_true',help='Skip Docker build for a chat-only setup')
    args=p.parse_args()
    state=args.state.expanduser().resolve()
    if state.is_relative_to(root):p.error('Choose a directory outside the source tree for --state.')
    state.mkdir(exist_ok=True,parents=True)
    env=root/'.venv'
    python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.exists():venv.EnvBuilder(with_pip=True).create(env)
    run=lambda cmd:subprocess.run([str(i) for i in cmd],cwd=host,check=True)
    run([python,'-m','pip','install','-r','requirements-host.txt'])
    if args.runtime=='adapter':
        run([python,'-m','pip','install','--index-url','https://download.pytorch.org/whl/cpu','torch==2.7.1'])
        run([python,'-m','pip','install','-r','training/language/requirements.txt'])
        run([python,'training/language/fetch_base.py',state/'base'])
    if not args.no_renderer:run(['docker','build','-t','chelsy-renderer:0.9.4','-f','deploy/renderer/Dockerfile','.'])
    print('Python:',python,'\nData:',state/'data')
    if args.runtime=='adapter':print('CHELSY_LOCAL_BASE:',state/'base')
    print('Next: open INSTALL_0.9.4_RU.md, section 3.')
if __name__=='__main__':main()
