# P11.63 — Sample Focus Guard

## Changes
- Verify selected `.f1-step.active[data-item]`, visible `.fieldset[data-item]`, and Task Information visibility in one DOM snapshot.
- Re-select up to three times if QAC asynchronously changes the panel; fail closed on uncertain target.
- Recheck active item before writing and before Save, exclusively in Sample Register.
- Do not use cursor/keyboard focus as the authoritative item identity.

## Not changed
- Batch registration still opens Measure for each prepared plan, even for the same QAC document. Grouped-document batch registration has NOT been implemented in this release.
- The Prepare step is still required; one-click 2D+time automatic workflow is future work.

## Tests
- 282 passed, 32 subtests passed, Python compile, ZIP verification; no live QAC server test.
