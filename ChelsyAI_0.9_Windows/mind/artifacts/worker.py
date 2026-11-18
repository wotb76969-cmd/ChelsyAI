"""Render in a fresh process. On Linux confine reads/writes and deny networking."""
import ctypes as C
import errno
import json
import os
from pathlib import Path
import sys
import sysconfig

def confine(folder):
    import resource
    import platform
    if platform.machine() not in ('x86_64','aarch64'): raise RuntimeError('Unsupported worker architecture')
    resource.setrlimit(resource.RLIMIT_CPU,(45,50))
    resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE,(25*1024**2,25*1024**2))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    libc=C.CDLL(None,use_errno=True)
    def check(code):
        if code<0: raise OSError(C.get_errno(),'Renderer confinement unavailable')
        return code
    # Linux Landlock ABI v3+ (truncate is covered). Filesystem objects are
    # explicitly granted below; the parent does not pass its database or keys.
    abi=check(libc.syscall(444,0,0,1))
    if abi<3: raise RuntimeError('Landlock ABI 3 required')
    mask=(1<<15)-1
    rules=check(libc.syscall(444,C.byref(C.c_uint64(mask)),8,0))
    class Rule(C.Structure):
        _pack_=1
        _fields_=[('rights',C.c_uint64),('parent',C.c_int32)]
    read=(1<<2)|(1<<3)
    def allow(path,rights):
        if not path.exists(): return
        fd=os.open(path,os.O_PATH|os.O_CLOEXEC)
        try: check(libc.syscall(445,rules,1,C.byref(Rule(rights,fd)),0))
        finally: os.close(fd)
    for path in {Path(p) for p in sys.path if 'site-packages' in p or 'dist-packages' in p} | {Path(sysconfig.get_path('stdlib')),Path('/usr/lib'),Path('/lib'),Path('/usr/share/fonts'),Path(__file__).resolve().parents[2]/'assets/fonts'}:
        allow(path,read)
    allow(folder,mask & ~1)
    check(libc.prctl(38,1,0,0,0))
    check(libc.syscall(446,rules,0))
    os.close(rules)
    # libseccomp resolves architecture-specific syscall numbers.
    lib=C.CDLL('libseccomp.so.2')
    lib.seccomp_init.restype=C.c_void_p
    ctx=C.c_void_p(lib.seccomp_init(0x7fff0000))
    if not ctx: raise RuntimeError('seccomp unavailable')
    for name in ('socket','socketpair','connect','execve','execveat','ptrace','process_vm_readv','process_vm_writev','io_uring_setup','mount','unshare','setns','open_by_handle_at','pidfd_getfd','bpf'):
        num=lib.seccomp_syscall_resolve_name(name.encode())
        if num>=0: check(lib.seccomp_rule_add(ctx,0x50000|errno.EPERM,num,0))
    check(lib.seccomp_load(ctx))
    lib.seccomp_release(ctx)

def main():
    if getattr(sys,"frozen",False):
        from mind.artifacts.builder import ArtifactSpec,build_artifact
    else:
        from builder import ArtifactSpec,build_artifact
    folder=Path(sys.argv[1]).resolve()
    payload=json.load(sys.stdin)
    if sys.platform.startswith('linux'):
        confine(folder)
    result=build_artifact(ArtifactSpec(**payload),folder,basename='document')
    print(result.path.name)
if __name__=='__main__': main()
