# P11.49 – Sample Register Electrode Bridge + Editable Time + QAC Trace

## Changes
- `ELECTRODE_NO` local mapping now reads an **active ISSUE** from `database/electrode_issue_return_local.sqlite3`, not the old replacement database. Exact matching by Line + Machine + Position, exactly one matching active issue; otherwise blank/manual. Operator must configure mapping on the relevant QAC field and Prepare again.
- Live Electrode shot values are **not available** from the Issue/Return ledger. `ELECTRODE_SHOT` mapping returns manual rather than inventing a value; this applies to Upper/Lower Counters. They must be obtained from a real shot source or entered manually.
- In Sample Mapping Review, Time is editable even when mapped from CSV. Uses exact sample Time field value for both QAC result and trace. Format HH.MM or HH:MM.
- After verified field saves, select Task Information icon (`.fa-info`), enter `[QAC-SAMPLE-TRACE] 2D=... | Time=...` in Task Information comment, click Post once, and require posted comment to appear in the comment area. Existing matching marker prevents duplicates when visible.

## Unverified / restrictions
- No live QAC browser/server tested; Post button, asynchronous refresh and comment appearance may behave differently live. If comment state is uncertain, workflow halts with error; never blindly re-post.
- Multiple documents in a Sample plan post one trace per QAC document. In partial batch success, prior saved fields/comments cannot be rolled back automatically.
- Old Electrode 'installation' tracking and Issue/Return ledger are distinct. Configuration of Mapping uses Issue/Return destination Line/Machine/Position. No cross-PC central sync implemented; an active ISSUE on a different PC will not be known.
- Counter is NOT obtained from the Issue/Return ledger because it only records Final Counter upon RETURN. Do not equate this to live Electrode Counter.
- This release is OFFLINE TESTED only, not Production Ready.
