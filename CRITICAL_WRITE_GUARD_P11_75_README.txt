QAC Auto Register P11_75 - Critical Write Guard, PARTIAL
Baseline: P11_74 (2026-10-27)
Changes:
- Auto Register passes scanned document identity (date, line, shift, document no, URL) into worker.
- Auto Register checks all five identity fields when binding page and immediately before each Save.
- The save result wait aborts rather than arbitrarily choosing among multiple new result IDs.
- Added six offline unit tests for changed/missing document and ambiguous result identities.
Test results:
- Syntax compileall: PASS.
- Targeted pytest (critical guard, sync empty timeline, QAC interaction/session): 26 passed.
- Entire suite: NOT PASSED/NOT COMPLETED: test_daily_5slot_preflight requires absent HTML fixture.
Unresolved Critical items:
- Cross-worker access/locking for all QAC browser workflows.
- Cross-machine duplicate atomicity requires QAC server support or central coordination and server readback.
- Save association: a single new result ID might still belong to an unrelated actor; definitive attribution requires server-provided operation identity.
- Other write workers (alarm, production, manual, sample, daily) do not yet have this new scanned-tab guard.
- No QAC production environment integration test or performance benchmark.
DO NOT deploy to production until remaining critical safeguards and regression tests are complete.
