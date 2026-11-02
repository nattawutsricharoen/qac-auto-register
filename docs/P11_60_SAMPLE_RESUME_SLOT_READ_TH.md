# P11.60 — Sample per-item Result Read & Resume Slot

- Fix: Read each inspection item's result rows while its own left-navigation panel is active. Do not rely on a final snapshot after switching to another panel.
- During Prepare and Register, capture the slot state of every item individually. Log `SAMPLE RESULT SNAPSHOT` per item, including number of result slots and occupied slots.
- Before writing, reread that item. If the planned slot is missing, reselect the same item once and recheck; if still missing, stop with `SAMPLE SLOT UNKNOWN`, not skip or auto-create a different slot.
- Skip only if existing value matches requested data exactly. Conflicts stop without overwrite.
- Preserve previously implemented Enter, no duplicate Save, final audit, CSV trace time, and sample-only Task Information navigation.
- Verification: 274 pytest tests + 32 subtests passed offline; no live QAC server or Windows UI validation. Do not claim production ready.
- IMPORTANT: Resume of incomplete Slot 2 requires manual selection of Slot 2 in Prepared List, with verification that the entry belongs to the same 2D. New Sample normally takes next free Slot.
