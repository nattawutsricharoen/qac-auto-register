# P11.53 — Sample Excel Electrode Mapping & Save Readback

## Change summary
- Use Excel `Mapping` sheet Source Type (EDIT) = `ELECTRODE_NO` with columns P/Q/R `Electrode Machine (EDIT)`, `Electrode Station (EDIT)`, `Electrode Position (EDIT)`.
- `1-2 Upper electrode No.` and `1-4 Clamp chuck electrode No.` for TS2-Sub SC1 Housing disc are configured as ELECTRODE_NO. `Position` intentionally left empty until verified against the actual Electrode Control SQLite database. The supplied files do not establish the exact position strings. Do not infer Upper/Clamp from the QAC field name.
- Electrode lookup matches one and only one active ISSUE for exact Line/Machine/Station/Position in local database/electrode_issue_return_local.sqlite3. If mapping incomplete, no match, or multiple matches, requires manual correction; no automatic wrong barcode.
- Existing CSV Counter/Weld mappings stay unchanged.
- When QAC Save UI state doesn't immediately confirm, re-select item and re-read the requested slot before reporting uncertain. NEVER send a second Save automatically.

## IMPORTANT before live testing
1. In Electrode Control > History/Admin inspect actual `machine`, `station`, and `position` values used in ISSUE records.
2. In config/QAC_Sample_Mapping_Master_SC1_MAPPED.xlsx > Mapping, edit P/Q/R for row `1-2` and `1-4` **exactly** to their corresponding ISSUE destination strings. Leave Q blank only if the source Station is blank.
3. If Local Mapping Override exists in SQLite for a QAC field, it has priority over Excel. Clear or align override before testing.
4. No real QAC Server session or PySide6 Windows GUI was available during this build. Unit/regression tests don't prove successful production registration.
5. Existing Slot 1 values must be attributed to the same 2D; don't overwrite uncertain records. The partial 2D comment may not yet exist.
6. Local SQLite is NOT centrally synced to other PCs; issue lookup only covers the same local ledger.

## Testing
- pytest 266 passed + 32 subtests
- compileall successful
- ZIP integrity checked
