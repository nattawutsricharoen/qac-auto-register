# QAC Auto Register — Cross-workflow Click/Response Stabilization Candidate

Baseline comparison: v1.7.24_COLUMN_WIDTH_MEMORY_AUTOFIT versus v1.7.65_P04_VERSION_UI_TEST_CANDIDATE.

Changes:
- app/qac_interaction.py: SweetAlert acknowledgement/navigation-blocker button click uses no_wait_after=True. Follow-on popup/page state inspection stays in existing controller, rather than allowing Playwright click to own navigation wait. No force=True, no JS synthetic click.
- app/register_engine.py: SAVE_TIMEOUT_MS changed 20000 to 60000; result IDs remain the success signal.
- app/production_transfer.py: QAC Complete popup wait changed 35s to 60s; acknowledgement click uses no_wait_after=True. Non-idempotent upload is still submitted once only.

Scope limitations:
- This is a focused shared-interaction patch, not proof of full stability for all QAC pages.
- A general automatic refresh after a non-idempotent submission is NOT added. Refresh must be conditioned on a workflow-specific reconciliation check for the exact task/lot/result and QAC permission to safely navigate; blind refresh risks duplicate writes/data loss.
- Alarm and Production Output adapters already use dedicated response-state loops and are preserved.
- Daily Document and Sample use additional form/navigation state; require real-QAC regression tests before Production.
- No live QAC, Windows PySide6 GUI or continuous-run validation was possible in this environment.

Test result: Python compileall passed; pytest: 112 passed, 6 subtests passed.

Deploy only on a separate test copy with backup. Observe exact QAC task results after a timeout. NOT PRODUCTION READY.
