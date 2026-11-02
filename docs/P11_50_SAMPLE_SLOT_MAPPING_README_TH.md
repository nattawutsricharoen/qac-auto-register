# P11.50 — Sample slot retry + Electrode station mapping

## Fixed
- Registration of an already-prepared plan preflights the *same master slot* across its fields, marking verified matching occupied results SKIP and empty results WRITE. A conflict/unknown persisted result stops without overwriting it.
- Numeric/text fields already containing the exact same value are skipped; mismatches stop.
- Electrode local source mapping now stores and checks `Station` in addition to Line, Machine, and Position. Existing override rows migrate to a blank station, so mappings to non-blank stations MUST be re-saved.
- The existing exact local Sample mapping dialog allows selecting a real Electrode Master destination and stores the station explicitly.

## Important limitations
- A partially completed QAC sample whose 2D trace comment was not posted is not positively attributable to that 2D. Never force-resume a different sample in its occupied slot. The preparer still selects the next wholly empty master slot; to retry an interrupted *already-prepared* plan, retain the same plan rather than preparing a fresh one. Reconciliation of abandoned slots against server-side 2D identity remains future work.
- Actual QAC server behavior and hidden/dynamically populated results were not tested here. If a saved slot is represented without its actual value, the verifier stops (fail closed).
- The Issue/Return electrode ledger stores a Final Counter only when the electrode is returned; it CANNOT supply live counter values for ISSUED electrodes. Map QAC `Upper electrode Counter` and `Clamp chuck electrode Counter` to exact Sample CSV columns (e.g. `HD E-rode (U)` and `HD E-rode (L)`) or manual source. No fabricated counter.
- Assign `ELECTRODE_NO` explicitly for each QAC electrode-number field via `Set Source / Mapping`, then choose the matching real Electrode Master Machine / Station / Position. No fuzzy mapping of machine names. For Housing Disc Welding, verify `TS2-Sub` and the actual installed Position. Other machine categories include Housing Cap Crimping, Diffuser Disc Welding, Housing Bottle Welding, Diffuser Bottle Welding, Stud Bolt Welding and Gas Filling Station 1/2/3; configure their real line/station/position in the Electrode Master before mapping.
- Local SQLite has no central LAN sync: electrodes issued on other PCs do not appear in this local Sample lookup.
- PySide6 Windows QAC live integration has not been verified in this offline environment; not Production Ready.
