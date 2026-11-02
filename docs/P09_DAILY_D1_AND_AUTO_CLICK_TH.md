# QAC Auto Register v1.7.65 P09 — Test Candidate

## Changes
- Auto Register: no separate scroll_into_view_if_needed before Save; if QAC replaces the DOM while clicking, treat the Save state as **uncertain**, then verify a new QAC Result ID. Never immediately send Save twice.
- Production Output uses the same uncertain-click/result-verification flow for Save; warning/error dialogs still fail safely.
- Daily Document: read the scanned Measure HTML and search the preceding calendar day in the QAC document list. Read persisted result values only from the actual previous-day QAC Measure HTML, and map on exact item label, input format, and slot number. Verify document no. and line if present. Do not invent defaults if D-1 is absent or ambiguous.
- Numeric field left empty: use verified previous-day result if available; '-' explicitly skips.
- Choice field: offer 'Use D-1' only when the previous result can be inferred unambiguously from visible QAC HTML text; otherwise default to 'Do not register'. Operator can explicitly choose current result.
- Explicit confirmation and source-result logging before carrying forward previous-day data; prior results are not current-day inspection evidence.
- Do not apply a saved Daily Template automatically upon opening the dialog. Template remains available through 'Load Template' only.
- Sample Register is unchanged.

## Important limitations
- This build has NOT been operated against a live Windows Edge/QAC instance. Popup, selector, navigation, and actual submission require validation in a safe test environment.
- HTML can expose a previous-day value without exposing its semantic meaning. Only numeric values or categorical values with explicit, unambiguous Initial/Middle/Final/OK/NG text will be copied. Missing or ambiguous values are left blank. Do not use previous readings as if they were freshly measured.
- 60s is a result-verification window, not proof of server failure. On an unresolved result, do not blind-retry.

## Testing
PYTHONPATH=. pytest -q --disable-warnings
Python compileall on app and main.py
