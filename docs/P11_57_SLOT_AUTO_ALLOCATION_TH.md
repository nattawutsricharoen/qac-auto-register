# P11.57 – Sample Master Slot auto-allocation (offline tested)

Fixes Prepare incorrectly assigning Slot 1 repeatedly even when QAC's authoritative Initial/Middle/Final result #1 is occupied and/or prepared plans have reserved slots.

- Prepare activates each real QAC item before reading its slot states. QAC's hidden panels can render empty placeholders before activation; these must not be trusted for slot allocation.
- The Initial/Middle/Final item is the authoritative master sequence; all other fields are checked at that same slot.
- Already prepared reservations for the same document are excluded; e.g. QAC #1 USED + reserved #2 -> allocate #3.
- Does NOT overwrite an existing QAC slot, does NOT silently skip a slot collision, does NOT automatically retry uncertain Save.
- Diagnostic logs: SAMPLE MASTER OCCUPANCY and SAMPLE SLOT ALLOCATE.
- IMPORTANT: The program still reconnects/scans per Prepare and reloads for execution. Batch snapshot caching is not implemented in this patch. Existing Save/readback uncertainties are not resolved by this patch. Real QAC/browser GUI acceptance testing is required.

Offline test: 269 tests + 32 subtests pass. PySide6/live QAC interaction not tested here.
