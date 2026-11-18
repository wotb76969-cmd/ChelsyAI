"""Host-local lifecycle; administrative operations never pass shell commands."""
import os
import shutil
import threading
import time

draining=threading.Event()

def stats(folder):
    disk=shutil.disk_usage(folder)
    result={'disk_free_bytes':disk.free,'disk_total_bytes':disk.total,'accepting':not draining.is_set()}
    try:
        import psutil
        result.update(cpu_percent=psutil.cpu_percent(),ram_available_bytes=psutil.virtual_memory().available)
    except ImportError:
        pass
    return result

def stop(server):
    import core
    draining.set()
    with core.db() as conn:
        conn.execute("UPDATE mind_tasks SET cancel_requested=1 WHERE status IN ('queued','running')")
    def shutdown():
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            with core.db() as conn:
                pending=conn.execute("SELECT count(*) FROM mind_tasks WHERE status IN ('queued','running')").fetchone()[0]
            if not pending:break
            time.sleep(.25)
        server.shutdown()
    threading.Thread(target=shutdown,daemon=True).start()
