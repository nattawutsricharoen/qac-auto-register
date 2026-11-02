"""Local CDP/browser availability only. No QAC scan or business actions."""
from dataclasses import dataclass
from app.browser import cdp_ready, launch_browser

@dataclass(frozen=True)
class ConnectionResult:
    ok: bool
    message: str
    started: bool = False

class LocalConnection:
    def __init__(self, ready=cdp_ready, launch=launch_browser):
        self._ready = ready
        self._launch = launch

    def ensure(self, browser_cfg, home_url):
        endpoint = str(browser_cfg.get('cdp_url') or '').strip()
        if not endpoint:
            return ConnectionResult(False, 'CDP URL is missing')
        if self._ready(endpoint):
            return ConnectionResult(True, 'Local Web already available', False)
        ok, msg = self._launch(browser_cfg, home_url)
        if not ok:
            return ConnectionResult(False, str(msg), False)
        # Browser startup must be confirmed, not inferred from Popen success.
        if not self._ready(endpoint):
            return ConnectionResult(False, 'Local Web not ready after launch', True)
        return ConnectionResult(True, str(msg), True)
