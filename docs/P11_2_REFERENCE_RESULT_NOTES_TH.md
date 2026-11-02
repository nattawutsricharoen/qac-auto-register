# P11.2 — Reference and existing QAC results diagnostics

- Daily current Measure reader logs existing saved result IDs for each Item/Slot and summary.
- Reference task lookup now considers `View` as well as `Measure`, which can differ for previously saved tasks.
- Read-only reference opens View first, then Measure where available; validates document number from opened QAC HTML before copying.
- Reference diagnostics distinguish Task not found, saved results with unavailable literal values, and successfully loaded slots.
- IMPORTANT: Where QAC HTML exposes only result ID (without the actual number or categorical label), the value is NOT invented. Such results show as saved but cannot be used as reference values until a real QAC representation is supplied.
- This is not live-QAC validated. Do not use on production without comparison against QAC.
