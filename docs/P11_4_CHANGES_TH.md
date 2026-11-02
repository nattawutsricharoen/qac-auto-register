P11.4 — Daily Document Target Reader + QAC Button Scope

1. Daily target scan reads persisted slot result IDs and literal HTML values. Shows actual values in the slot dialog; unknown values explicitly marked unreadable, never inferred.
2. OK/NG uses fieldset-local button if present; otherwise exactly one visible enabled toolbar button; refuses ambiguous matches and logs scope.
3. QAC View modal uses data-task-scoped Close button before browser back.

Limitations: No live QAC endpoint available for end-to-end test. QAC categorical values absent from HTML cannot be reconstructed. Do not consider production validated.
