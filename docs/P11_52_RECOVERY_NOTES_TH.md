# P11.52 — Sample recovery / partial-slot safety (offline)

- Recover from interrupted Measure before **Register** when the session is demonstrably still on Measure, instead of asking user to return manually.
- Re-read every participating QAC item from its active left-nav panel before deciding which fields in the prepared master slot are saved. Never infer 'empty' from an unopened hidden panel.
- Handle detached auto-closing `Complete !` acknowledgement only when the rechecked modal is NONE; **never click Save a second time**. The saved result must still be validated.
- Keep planned master slot and skip only verified existing equal values; do not move to a new slot based on a retry.

## Important known limitations
- Re-Prepare is **not** the same as resuming a saved plan. Before the QAC 2D trace comment exists, the old slot cannot be proved to belong to the same 2D using QAC HTML alone. Preserve/reuse the queued plan to resume; do not force an automatic match.
- Electrode No. resolution requires exact per-field Local `ELECTRODE_NO` mapping to an active ISSUE (Line/Machine/Station/Position); the provided master does not by itself confirm Upper/Clamp position identities. Missing or ambiguous issues need explicit mapping, not guesses.
- Electrode Counter is not tracked live by the Issue/Return ledger; map each QAC counter to the correct exact CSV group/column or manually enter verified current counter.
- This version has no live QAC-server validation and no multi-PC central sync verification; do not treat as Production Ready.
