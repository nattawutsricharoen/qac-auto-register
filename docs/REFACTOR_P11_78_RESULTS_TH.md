# P11_78 Refactor Candidate — Audit & Test Report

Status: **DEVELOPMENT CANDIDATE — NOT PRODUCTION-READY**
Origin: P11_77 (itself based on P11_76). Does not change live QAC save algorithm.

## Code changes
- MainWindow Sample Register has its own `cmb_sample_line` sourced from document master, no longer reads Auto Register selected document line during Prepare, target lookup, or worker creation.
- Auto Register document selection no longer causes Sample target/line selection to be changed. Daily Document Line compatibility behavior remains unchanged.
- Selected Auto Register document publication date is distributed as default to Daily and Sample through ReferenceDateHub, with manual per-page overrides respected.
- Explicit Sample Status Refresh verifies Employee ID and checks/opens Local Browser before invoking its scoped status worker.
- Kept legacy Auto Register scan distribution to Alarm/OCR/Production for compatibility: it is NOT independent yet. Removing it before providing new module-owned document discovery would break those pages.
- Existing LocalConnection, module-scoped date state, registration no-scan guard from P11_77 remain.

## Verification
- `python -m compileall -q main.py app`: PASS.
- `python -m unittest tests.test_refactor_contracts tests.test_p1178_sample_isolation`: PASS 8/8 (static/source and unit contracts; no live QAC integration).
- `python -m unittest discover -s tests -p 'test_*.py'`: 87 tests executed in the initial full run: 83 passed, 1 failed, 3 errors; missing external real HTML fixtures (`Pasted text(20261021-033632).txt` and related). NOT a full regression pass.

## Still required to meet request completely
1. Real module isolation for Auto, Daily, Alarm, OCR, Production, Sample: separate UI controllers, worker ownership, session/profile, state, and document discovery. `main.py` and `worker.py` remain monolithic.
2. Single consistent Employee ID and Local Browser readiness guard for *every QAC-requiring button*, including module-specific status checks, while local-only buttons do not need a browser.
3. No unsolicited full scan after starting any workflow; detect document/slot state within the relevant workflow only. Audit indirect and asynchronous navigation triggers in real QAC.
4. Verify date behavior with multi-document/shift conditions on site; verify no override from reference publication.
5. Run full regression using actual HTML fixtures, and perform live end-to-end QAC tests with a safe test document/employee.

Do not replace production version with this candidate. Keep P11_76 and working stable package for rollback.
