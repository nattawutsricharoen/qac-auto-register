P11.54 Sample Register performance optimization (offline tested)

Evidence: 2026-10-24 14:44–14:47 log showed ~9.8 sec between each QAC Save complete and next sample field, while Save+modal confirmation was commonly ~1–2 sec.

Root cause in code: _fill_field_at_master_slot called _wait_saved_state(timeout_ms=9000) before verifying the specific slot through _live_schema. QAC's generic data-result may stay unchanged after save, forcing all 9 sec per field.

Change: after a Save/confirmation, activate/read the same QAC item and verify the exact expected value at the same slot immediately; only if still unavailable, poll every 250 ms for up to 9 sec. Do not Save twice. Explicit errors on unverified result.

Not changed: Excel electrode Position/machine mapping, current Electrode No source configuration, mapping of counters, session behavior, and sample trace post.

Verification: Python compileall and unit/regression tests passed offline. Windows GUI and live QAC network latency/performance NOT tested. A 9-second fallback may still happen when QAC has not returned a verifiable value.
