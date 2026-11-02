# P11_76 – Critical Safety Patch / Verification

Base: P11_75 (derived from P11_74). This is a candidate for further QA, **not production-ready**.

## Changes
- `app/qac_sync.py`: read live Measure labels accurately (`Document No.`, Production date, Line, Shift where present, document name).
- `app/register_engine.py`: normalize real QAC date display before write identity comparison; reject missing/mismatched required document attributes. Retain pre-write and pre-save guards.
- `app/worker.py` + `app/browser_operation_lock.py`: serialize CDP-connected workers sharing the same URL inside this process; no simultaneous browser navigation from background worker threads. Other CDP endpoints remain independent. Tradeoff: parallelism for operations on the same CDP endpoint is reduced.
- `tests/test_critical_p1176.py`: 5 regression cases using the supplied S50 Measure HTML, date comparison, fail-closed, and concurrent locks.

## Test evidence
- Python compileall: passed.
- Targeted P11_76 tests: 5 passed.
- Full offline suite: 311 passed, 3 failed, 32 subtests passed.
- Outstanding failures all caused by absent archived Daily HTML fixtures: `Pasted text(20261019-072032).txt`, `Pasted text(20261021-033632).txt`.
- Live QAC end-to-end, multi-PC duplicate safety, Windows PyInstaller, and real CPU/RAM benchmark: **NOT TESTED** in this environment. `PySide6` unavailable here for live GUI execution.

## Unresolved critical issues
1. Cross-machine duplicate prevention requires a central authoritative service / server-side constraints. Process-local locks cannot guarantee this.
2. Manual browser changes and other processes can still race writes to QAC; server-side compare-and-set cannot be added without QAC server capabilities.
3. Validate all distinct Sample/Daily write workflows with real DOM, especially after navigation, before any production deployment.
4. Performance improvement is unverified; serialization trades throughput for correctness. Measure baseline and after-patch Windows timings.

Do not replace an operating production package without a controlled staged end-to-end test.
