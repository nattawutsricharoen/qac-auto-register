import json
from pathlib import Path

def app_root() -> Path:
    return Path(__file__).resolve().parent.parent

def load_settings() -> dict:
    path = app_root() / "config" / "settings.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_settings(settings: dict) -> None:
    path = app_root() / "config" / "settings.json"
    temp = path.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    temp.replace(path)
