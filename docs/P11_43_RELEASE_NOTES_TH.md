# P11.43 – Numeric modal recovery and Measure preservation

Base: P11.42 ZIP delivered to user.

Changes:
1. When Enter already observed QAC CONFIRM but a later DOM inspection is UNKNOWN/NONE/BUSY, wait at most 2 seconds and resample read-only. No repeat Enter/Inspector/Save; stop if Confirm is still absent.
2. Any registration failure halts further writes and preserves the open Measure browser page (no unconditional Back/close). Only return to Check Sheet after a fully completed document.
3. Add `DAILY READER SLOW ITEM` with per-item duration >3s to identify costly lazy-loaded items. All original EXIST and UNKNOWN checks retained.

Unchanged: QAC reader still activates unknown item results; 109-item scan performance is not yet proven improved. Do not mark Production Ready. Verify behaviour with real QAC session before deployment.

Tests: Offline pytest 248 passed +32 subtests. Python compileall passed. No live QAC validation.
