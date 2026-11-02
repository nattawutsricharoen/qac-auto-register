def build_schedule(
    shift_text: str,
    model_value: str,
    model_name: str,
    settings: dict
):
    is_night = "NIGHT" in (shift_text or "").upper()
    profile = settings[
        "night_shift" if is_night else "day_shift"
    ]
    records = settings.get("auto_register_records", {})
    production_cfg = records.get("production", {})
    break_cfg = records.get("break", {})

    actions = []

    for hhmm in profile.get("production_points", []):
        actions.append({
            "kind": "production",
            "start": hhmm,
            "end": hhmm,
            "model_value": model_value,
            "model_name": model_name,
            "downtime_value": str(production_cfg.get("downtime_value", "")),
            "downtime_label": str(production_cfg.get("downtime_label", "Production Output")),
            "category_value": str(production_cfg.get("category_value", "")),
            "category_label": str(production_cfg.get("category_label", "Normal Production")),
            "description": str(production_cfg.get("description", "")),
            "time_rule": str(production_cfg.get("time_rule", "start_only")),
        })

    for start, end in profile.get("breaks", []):
        actions.append({
            "kind": "break",
            "start": start,
            "end": end,
            "model_value": "",
            "model_name": "",
            "downtime_value": str(break_cfg.get("downtime_value", "")),
            "downtime_label": str(break_cfg.get("downtime_label", "Schedule Downtime")),
            "category_value": str(break_cfg.get("category_value", "")),
            "category_label": str(break_cfg.get("category_label", "Break time")),
            "description": str(break_cfg.get("description", "Break time")),
            "time_rule": str(break_cfg.get("time_rule", "start_end")),
        })

    def key(action):
        h, m = map(int, action["start"].split(":"))
        if is_night and h < 12:
            h += 24
        return h * 60 + m

    return sorted(actions, key=key)
