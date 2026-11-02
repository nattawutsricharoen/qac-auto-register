from __future__ import annotations
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

def cdp_ready(cdp_url: str) -> bool:
    try:
        with urlopen(cdp_url.rstrip("/") + "/json/version", timeout=1.0) as r:
            return r.status == 200
    except Exception:
        return False

def find_edge(candidates: list[str]) -> str | None:
    for p in candidates:
        if Path(p).exists():
            return p
    return None

def launch_edge_for_qac(settings: dict) -> tuple[bool, str]:
    cdp = settings["cdp_url"]
    if cdp_ready(cdp):
        return True, "Edge QAC พร้อมเชื่อมต่ออยู่แล้ว"

    exe = find_edge(settings.get("edge_exe_candidates", []))
    if not exe:
        return False, "ไม่พบ msedge.exe"

    profile = settings.get("edge_profile_dir", r"C:\QAC_Auto\EdgeProfile")
    cmd = [
        exe,
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile}",
        "--new-window",
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(20):
        if cdp_ready(cdp):
            return True, "เปิด Edge QAC สำเร็จ"
        time.sleep(0.25)
    return False, "เปิด Edge แล้ว แต่ยังเชื่อมต่อ Remote Debugging ไม่สำเร็จ"
