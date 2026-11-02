from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen


def cdp_ready(cdp_url: str) -> bool:
    try:
        with urlopen(
            cdp_url.rstrip("/") + "/json/version",
            timeout=1.0
        ) as r:
            return r.status == 200
    except Exception:
        return False


def find_browser_exe(
    candidates: list[str]
) -> str | None:
    for raw in candidates:
        p = os.path.expandvars(raw)
        if Path(p).exists():
            return p
    return None


def launch_browser(
    browser_cfg: dict,
    start_url: str = ""
) -> tuple[bool, str]:
    """
    Launch/activate the dedicated QAC browser profile.

    If CDP is already ready, launching the same executable/profile
    with start_url opens QAC in that existing browser instance.
    """
    cdp_url = browser_cfg["cdp_url"]
    exe = find_browser_exe(
        browser_cfg.get("exe_candidates", [])
    )

    if not exe:
        return (
            False,
            f'ไม่พบ {browser_cfg["display_name"]} executable'
        )

    profile = browser_cfg["profile_dir"]
    port = int(
        browser_cfg["remote_debugging_port"]
    )

    cmd = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
    ]

    was_ready = cdp_ready(cdp_url)

    if not was_ready:
        cmd.append("--new-window")

    if str(start_url or "").strip():
        cmd.append(str(start_url).strip())

    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # Already-connected browser only needs the URL invocation.
    if was_ready:
        return (
            True,
            f'{browser_cfg["display_name"]} พร้อมเชื่อมต่อ '
            f'และเปิด QAC แล้ว'
        )

    for _ in range(40):
        if cdp_ready(cdp_url):
            return (
                True,
                f'เปิด {browser_cfg["display_name"]} QAC สำเร็จ'
            )
        time.sleep(0.25)

    return (
        False,
        f'เปิด {browser_cfg["display_name"]} แล้ว '
        f'แต่ Remote Debugging ยังไม่พร้อม'
    )
