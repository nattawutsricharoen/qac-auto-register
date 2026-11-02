# Safety barrier: all Playwright workers sharing the same CDP endpoint must not
# navigate or manipulate the QAC browser concurrently. This is process-local;
# it is NOT a multi-PC distributed lease and cannot prevent manual browser edits.
import functools as _qac_functools
import threading as _qac_threading
_qac_browser_mutexes = {}
_qac_browser_mutexes_guard = _qac_threading.Lock()

def _serialize_qac_browser_run(original_run):
    @_qac_functools.wraps(original_run)
    def guarded_run(self):
        endpoint = str(getattr(self, 'cdp_url', '') or '').strip()
        if not endpoint:
            return original_run(self)
        with _qac_browser_mutexes_guard:
            mutex = _qac_browser_mutexes.setdefault(endpoint, _qac_threading.RLock())
        with mutex:
            return original_run(self)
    return guarded_run

