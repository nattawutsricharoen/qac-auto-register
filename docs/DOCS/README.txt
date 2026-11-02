QAC Auto Register v0.3
======================

เพิ่มจากรุ่นก่อน
- รองรับ Microsoft Edge
- รองรับ Google Chrome
- Edge ใช้ CDP port 9222
- Chrome ใช้ CDP port 9223
- Browser profile แยกจาก profile ใช้งานทั่วไป
- Playwright เปลี่ยนเป็น Async API
- Scan และ Register ทำใน QThread แยก
- ลดปัญหา PySide6 UI ค้าง
- แก้ error:
  "Playwright Sync API inside the asyncio loop"

การใช้งาน
1. เปิดโปรแกรม
2. เลือก Browser:
   - Microsoft Edge
   - Google Chrome
3. กด Open QAC Browser
4. Login QAC
5. เปิด QAC document ได้หลายแท็บ
6. กด Scan QAC Tabs
7. เลือก Document
8. เลือก Model
9. ใช้ Dry Run ก่อน
10. เมื่อตรวจสอบแล้วจึง Register จริง

Port
- Edge   : 127.0.0.1:9222
- Chrome : 127.0.0.1:9223

Profiles
- Edge   : C:\QAC_Auto\EdgeProfile
- Chrome : C:\QAC_Auto\ChromeProfile

ONEDIR BUILD
รัน:
    build_onedir.bat

หมายเหตุ
Night Shift schedule ยังไม่ได้กำหนด เพราะรอเวลาที่ผู้ใช้ยืนยัน


SHIFT PROFILES v0.4
===================

DAY
Production Output:
09:00, 10:00, 11:00, 12:00, 13:00, 14:00,
15:00, 16:00, 17:00, 18:00, 19:00, 20:00

Break:
10:00-10:10
12:10-12:50
15:00-15:10
17:00-17:30

NIGHT
Production Output:
21:00, 22:00, 23:00, 00:00, 01:00, 02:00,
03:00, 04:00, 05:00, 06:00, 07:00, 08:00

Break:
22:00-22:10
00:10-00:50
03:00-03:10
05:00-05:30

NOTE
Night shift crosses midnight.
The QAC page already contains its own night-shift date handling logic;
the automation enters the visible clock time and lets QAC validate/save it.


v0.5 STRICT SEQUENTIAL REGISTER
===============================
Register จริงทำทีละรายการ:
1. เปิด New Time & Event
2. เลือก Event
3. เลือก Category
4. เลือก Model (Production Output)
5. ใส่ Start / End
6. กด Save/Next
7. Confirm
8. รอ QAC Complete
9. ตรวจว่ามี Result ใหม่ใน DOM/timeline จริง
10. จึงทำรายการถัดไป

Safety
- ถ้า QAC Error -> หยุดทันที
- ถ้า Save timeout -> หยุดทันที
- ถ้าเห็น Complete แต่ไม่มี Result ใหม่ -> หยุดทันที
- ไม่ข้ามรายการที่ผิดพลาด
- Dry Run ยังไม่แตะหน้า QAC

v0.6 VISIBLE FORM + BREAK FIX
- แก้ strict mode violation จาก QAC ที่มี hidden cloned form
- ทุก selector scope เฉพาะ .task-downtime:visible
- Production: Production Output > Normal Production > Model > Start/End > Save > Wait Complete
- Break: Schedule Downtime > Break time > Description='Break time' > Start/Stop > Save > Wait Complete
- Error/Timeout = STOP ทันที

v0.7 PRODUCTION END + SAVE FIX
==============================
- Production Output:
  - ใส่ Start เท่านั้น
  - End เป็น disabled field ของ QAC
  - รอ QAC Auto copy Start -> End
  - ห้าม Playwright fill End โดยตรง
- Save:
  - กด button.btn-save ภายใน visible New Time & Event form โดยตรง
  - ไม่ใช้ fallback btn-next
- Break:
  - ยังคงใส่ Start + End/Stop เอง
  - Description = Break time

v0.8 PRODUCTION START ONLY
==========================
Production Output workflow:
1. New Time & Event
2. Downtime = Production Output
3. Category = Normal Production
4. Model = selected model
5. Start = hourly time
6. DO NOT touch End
7. Save
8. Confirm
9. Wait Complete
10. Verify new result
11. Next event

Break workflow unchanged:
- Schedule Downtime
- Break time
- Description = Break time
- Start
- End/Stop
- Save
- Wait Complete

v0.9 OPEN NEW EVENT FIX
=======================
Fix:
- Restore missing _open_new_event() accidentally removed in v0.8.
- Production remains START ONLY:
  New Time & Event > Production Output > Normal Production >
  Selected Model > Start > Save > Confirm > Wait Complete.
- Production does NOT read/fill/wait for End.
- Break remains:
  Schedule Downtime > Break time > Description=Break time >
  Start > End > Save > Confirm > Wait Complete.


v1.0 ALARM IMPORT
=================
Alarm Import supports multiple CSV/XLSX/XLSM files.

Source mapping:
A = ignored
B = Start Time
C = ignored
D = Alarm Code (kept in metadata/log)
E = Message
F = Machine Code

Table:
Check | Column F | Machine(QAC form) | NG Product(QAC form) |
Column E | Column B | Time Stop

Default Time Stop = Column B + 1 minute; editable per row.

Description sent to QAC:
Machine Alarm {Column E} No Action Monitor Run

QAC workflow per checked row:
New Time & Event
> Downtime = Trouble
> Category = Machine
> Model = selected model
> Machine = row selection
> NG Product = row selection
> NG Product Qty = 1
> Description
> Start = Column B
> Stop = edited Time Stop
> Save
> Confirm
> Wait Complete
> Verify Result
> Next row

Safety:
- Machine and NG Product must be selected for every checked row.
- Invalid Start/Stop blocks import before execution.
- Error/timeout stops the sequential import immediately.


v1.1 ROBUST QAC SCAN
====================
Fix Scan QAC Tabs returning 0 documents when the current QAC page is
already on New Time & Event or another event step.

Detection priority:
1. URL contains /app/view/measure.html
2. Fallback DOM:
   h1[data-title][data-line-id] + select.dropdown_topic

Scan no longer requires the visible text:
- "Task Information"
- "New Time & Event"

This means Scan works while the operator is on:
- Task Information
- New Time & Event
- Previously registered Event


v1.2 I-TAG ALARM IMPORT
=======================
Baseline preserved from v1.1.

Alarm Import header:
- QAC Document
- Model
- Shift 1..6
- Production Line Found (automatic from selected document)
- Process Found (read from QAC I-TAG service and selected by operator)

Imported row table additionally shows:
- Production Line Found
- Process Found
- Shift

Trouble row execution:
1. New Time & Event
2. Trouble
3. Category Machine
4. Model
5. Machine
6. NG Product
7. NG Product Qty = 1
8. Enable I-TAG
9. Keeping Place = NG box when empty
10. Production Line Found = selected QAC document line
11. Process Found = header selection
12. Shift = header Shift 1..6
13. Validate QAC generated Lot No
14. Description
15. Start / Stop
16. Save
17. Wait Complete
18. Next checked row

I-TAG hidden fields are read from DOM/service while preserving normal QAC UI behavior.

v1.2.1 UI correction
====================
- Shift remains only in the top Alarm Import controls.
- Removed Shift from imported-row table.
- Removed Production Line Found from imported-row table.
- The previous top Process Found selector is now displayed as Production Line Found.
- Imported rows keep only Process Found as the I-TAG-related row column.
- I-TAG execution logic remains unchanged from v1.2.

v1.2.2 I-TAG MAPPING FIX
========================
Corrected the swapped I-TAG mapping.

Top:
- Production Line Found = actual QAC Production Line Found master
  e.g. PRODUCTION-TS1-Sub / PRODUCTION-TS2-Sub.
- Auto-selects the line matching the selected QAC document.
- Shift remains at the top.

Rows:
- Process Found is now a combobox per imported row.
- Process Found options are loaded dynamically from QAC based on
  the selected top Production Line Found.
- Each checked row must have its own Process Found selection.

This fixes the previous wrong behavior where Process Found values such as
Cooling conveyor / Diffuser Assembly were shown in the top
Production Line Found combobox.

v1.2.3 I-TAG STRICT LOCATOR FIX
==============================
Fixes Playwright strict-mode violation when QAC contains duplicate hidden
I-TAG form fragments/options.

- Production Line Found: resolve the visible select only.
- Process Found: resolve the visible select only.
- Do not wait on option[value=...] with a strict descendant locator.
- Use select_option(value=...) directly on the visible select.
- If Process Found cannot be selected, error now reports the available
  options from the visible QAC form for diagnosis.


v1.3 PRODUCTION CONTROL
=======================
1. Duplicate Interlock reads existing QAC events before register/import.
2. Central LAN access CSV: ip,name,status,tab1,tab2. Fail closed.
3. JSONL system logs.
4. Pause / Resume / Stop between completed rows/events.
5. Alarm columns:
   Check | I-TAG | Column F | Machine | NG Product |
   Column E | Column B | Time Stop | Process Found
6. Case-insensitive contains search for long comboboxes.


v1.4 ACCESS / UI CONTROL
========================

QAC Browser
-----------
Open QAC Browser now opens:
  http://159.228.251.234:8077/
automatically.
The URL is stored in config/settings.json as qac_home_url and can be
changed from Settings when settings_show=1.

Central access schema v2
------------------------
CSV:
ip,name,status,tab1_enable,tab1_show,tab2_enable,tab2_show,settings_show

Rules:
- status must be active.
- show=0   -> hide the tab.
- show=1 + enable=0 -> show but disable the tab.
- show=1 + enable=1 -> show and allow use.
- settings_show=1 -> Settings tab is shown.
- settings_show=0 -> Settings tab is not created.

Backend permission checks are also enforced before Auto Register and
Alarm Import; hiding the UI is not the only permission control.

Settings tab
------------
When settings_show=1:
- edit Central Access Config path
- Browse for CSV
- Test Connection/current-IP access
- edit QAC Home URL
- Save local settings

To avoid locking the machine out accidentally, a new central config path
is not saved unless it is readable and contains the current machine IP.

Central Config remains fail-closed:
- unreadable file
- IP not registered
- inactive status
=> program denies access and instructs the user to contact developer.

Legacy access CSV
-----------------
Old schema:
ip,name,status,tab1,tab2
is still accepted for compatibility.
tab1/tab2 map to both show and enable, and Settings remains hidden.

Audit
-----
Daily JSONL logs include identity (central config name/IP), browser open,
scan, selected files, register/import start, progress, pause/stop/errors,
completion, Settings tests/saves, and program close.


v1.4.2 EXISTING VISIBLE - AUTO REGISTER
=======================================
Auto Register now displays Status:
  EXISTS ✓ = already saved in QAC
  NEW      = not found in QAC

Existing-event scan uses two sources:
1. saved detailed QAC result forms
2. visible .f1-step[data-result] timeline as fallback

This specifically handles documents where the timeline visibly contains:
  Production Output 9:00 - 9:00PM
even when QAC does not retain a detailed result form in DOM.

Register only sends NEW actions. EXISTS actions remain visible in the
preview but are excluded from the execution batch.

Alarm Import keeps the v1.4.1 Status behavior and forced I-TAG behavior.


v1.4.3 AUTO ENROLL UNKNOWN MACHINE
==================================
When the central access_control.csv is readable but the current machine IP
does not exist, the program automatically appends one pending row:

  ip=<detected LAN IP>
  name=<Windows computer/host name>
  status=pending
  tab1_enable=0
  tab1_show=0
  tab2_enable=0
  tab2_show=0
  settings_show=0

The program then denies access and asks the user to contact the developer.
The developer must manually change status/permissions before the next launch.

LAN write safety:
- atomic .lock file
- retry up to 8 seconds
- re-read and duplicate-IP check while locked
- append only after schema validation
- legacy tab1/tab2 CSV is still supported


v1.4.4 ICON + ONEDIR READY
==========================
- Auto.ico included in project.
- Auto.ico used as PyInstaller EXE icon.
- Auto.ico used as QApplication/MainWindow icon.
- Auto.png included as matching application artwork resource.
- resource_path() supports source and PyInstaller runtime.
- build_onedir.bat cleans build/dist/spec and packs onedir.
- BUILD_ONE_LINE.txt contains the same core build command as one line.
- config directory is included in the onedir package.
- Playwright package data is collected for CDP automation.

Run:
  build_onedir.bat

Result:
  dist\QAC_Auto_Register\QAC_Auto_Register.exe


v1.5.0 OCR NG IMPORT
====================
Base: v1.4.4.

New Tab 3: OCR NG Import
------------------------
Designed for AUTO REJECT / Machine Judge HMI photos.

Image workflow:
Add Images -> Run OCR -> Preview/Edit -> Existing QAC Check ->
REGISTER OCR TO QAC -> Pause/Resume/Stop.

Supported HMI rows:
1ST LOW PITCH
1ST-2ND LOW PITCH
1ST VERTICALITY
2ND VERTICALITY
1ST HIEGHT PITCH
1ST-2ND HIEGHT PITCH
COUNTER NG

COUNTER NG:
- OCR reads it.
- shown in OCR log/audit.
- NEVER creates a register row.

Per register row:
Check | Status | Source | Judge | Message editable | Counter editable |
Machine | NG Product | Start | Time Stop | Process Found

Description:
Machine Judge {Message} Counter {Counter} PCS

Important safety:
- OCR never invents unread counters; blank counter requires user correction.
- Message is editable and final edited value is used for QAC.
- Counter is also editable.
- counter=0 defaults unchecked but can be manually selected.
- every selected OCR row issues I-TAG.
- existing QAC rows are marked EXISTS and unchecked.
- final register still uses the existing duplicate interlock.

Photo time:
1. YYYYMMDD_HHMMSS filename
2. EXIF DateTimeOriginal
3. file modified time
Stop defaults to Start + 1 minute.

OCR engine:
- pytesseract + OpenCV
- Tesseract executable auto-detection:
  tools\Tesseract-OCR\tesseract.exe
  C:\Program Files\Tesseract-OCR\tesseract.exe
  Windows PATH


v1.5.1 OCR QTY/TIME FIX
=======================
OCR NG Import only:
- Counter is sent once as QAC NG Product (Qty).
  Counter=40 -> Qty=40 in a single QAC event.
- Description:
  Machine Judge 1ST-2ND HIEGHT PITCH NG 40 PCS
  (the word "Counter" is removed)
- Start == Time Stop.
- Alarm Import and Auto Register are unchanged.
- COUNTER NG remains excluded.


v1.5.2 OCR QTY ENGINE + PROGRESS
================================
Critical QAC engine fix:
- Alarm register engine no longer hard-codes NG Product Qty=1.
- It uses action.get("ng_qty", 1).
- OCR Counter=17 -> QAC NG Product Qty=17.
- Normal Alarm Import still defaults to Qty=1.
- Qty <= 0 is blocked from actual QAC save.

OCR progress:
- Progress bar added below OCR action controls.
- Run OCR shows image progress 0-100%.
- Register OCR shows QAC row progress 0-100%.
- Status text shows OCR/REGISTER/ERROR/COMPLETE.
- Detailed messages remain in the log below.


v1.6.0 PRODUCTION OUTPUT + CONFIG-DRIVEN AUTO REGISTER
======================================================

AUTO REGISTER SETTINGS
----------------------
Production and Break QAC master records are now read from settings.json:
- downtime value/name
- category value/name
- break description

Execution no longer embeds Production Output/Normal Production or
Schedule Downtime/Break time IDs in the Auto Register workflow.
Selection uses ID when valid and falls back to exact visible QAC name.

PRODUCTION OUTPUT IMPORT
------------------------
Line Data XLSX/XLSM is read using:
- Date/Time
- Serial(Temporary)

COUNTA semantics:
Every non-empty Serial(Temporary) row with a valid Date/Time counts once.

Night mapping example:
20:00-21:00 -> QAC Production Output 21:00
21:00-22:00 -> QAC Production Output 22:00
...
07:00-08:00 -> QAC Production Output 08:00

The tab:
1. Creates Setup / Run-up only when missing.
2. Updates Actual Qty on EXISTING hourly Production Output events.
3. Creates Schedule Downtime / Stop line only when missing.

Safety:
- Missing hourly Production Output points block the engine before any change.
- Timeline detail fallback is used when QAC does not retain full hidden forms.
- Matching supports configured QAC ID OR exact visible master name.
- Shift/date/line mismatch is blocked.
- Matching Actual Qty is skipped as COMPLETE.
- Setup/Stop duplicate is skipped.
- Pause/Resume/Stop supported.
- Progress and system log included.

Setup defaults:
Downtime=Setup
Category=Run-up
Machine=ME01 Housing assembly machine
Description=Run Up
Start=shift start
End=first Line Data time

Stop defaults:
Downtime=Schedule Downtime
Category=Stop line
Description=Stop Line
Start=last Line Data time
End=shift end

ACCESS CONTROL v4
-----------------
tab4_enable/tab4_show control Production Output Import.

AUTO REGISTER DRY RUN
---------------------
Auto Register Dry Run checkbox is hidden and forced False, preserving
the user's latest operating rule. Other tabs keep their own Dry Run controls.


v1.6.1 ALARM DUPLICATE + CSV + NO PRODUCTION DRY RUN
====================================================

Alarm Import duplicate detection
--------------------------------
Problem fixed:
Completed QAC records may remain only as timeline nodes. Their hidden
.task-downtime form can disappear, which made topic/model/description blank
and caused an already-entered Alarm row to appear NEW.

Fix:
- ExistingAlarmWorker now clicks timeline result nodes read-only and reads
  the actual completed QAC form values.
- No Save/Update/Delete is performed during duplicate scanning.
- Duplicate signature now includes:
  Trouble + Machine + Model + Machine + Start + Stop + Description
  + I-TAG Process.
- Start/Stop are normalized to minute precision to match QAC display.
- Alarm import engine repeats the timeline detail pre-flight itself before
  any new QAC record is created, so duplicate protection does not depend
  only on the UI status scan.

Production Output Import
------------------------
- Adds CSV alongside XLSX/XLSM.
- CSV auto-detects comma/semicolon/tab/pipe delimiter.
- Encoding fallbacks: UTF-8 BOM, UTF-8, CP932, CP874, Latin-1.
- Uses the same Date/Time + Serial(Temporary) COUNTA logic.
- Production Output Import Dry Run is removed.
- UPDATE QAC always requires the confirmation dialog and then runs live.
- Alarm Import/OCR Dry Run behavior is unchanged.


v1.6.2 ALARM ACTIVE ROW + PRODUCTION ROW CHECK
===============================================

Alarm Import
------------
- Clicking/focusing any editable widget in a row highlights the whole row
  with a light background.
- Applies to checkbox, Machine, NG Product, Time Stop and Process Found.
- Clicking ordinary table cells also selects/highlights the row.
- Only one active row is highlighted at a time.
- Existing NEW / EXISTS status text remains unchanged.

Production Output Import
------------------------
- New Check column for every row:
  Setup / Run-up
  each hourly Production Output
  Stop Line
- Check All / Uncheck All buttons added.
- Only checked rows are passed to the worker/engine.
- Unchecked rows are never created or updated.
- Engine pre-flight therefore validates only selected Production Output rows.
- Confirmation displays selected row count and selected Production Qty.
- System audit stores the exact selected actions.
- Production Output Import still has no Dry Run.


v1.7.0 SHARED SQLITE CACHE + ACCESS OFFLINE FALLBACK
====================================================

SHARED QAC SQLITE CACHE
-----------------------
Local persistent database:
  %LOCALAPPDATA%\QAC_Auto_Register\qac_cache.db

Retention:
- current production calendar day
- previous production calendar day
- older cache documents are removed automatically

Synchronization:
1. Read QAC Timeline Result IDs (cheap).
2. Compare IDs against local SQLite.
3. Reuse cached completed Result details.
4. Click/read only NEW or incomplete Result IDs.
5. After this program saves a record, write its known payload directly to
   SQLite immediately without reopening every Result.

Policies:
- Auto Register:
  SQLite duplicate interlock + incremental sync.
- Alarm Import:
  SQLite duplicate interlock + incremental sync.
- OCR NG Import:
  NO historical duplicate pre-scan.
  Successful new QAC Result is written directly into SQLite.
- Production Output Import:
  SQLite lookup for existing Production Output / Setup / Stop Line.
  Only selected checkbox rows are processed.
  Updated Result is refreshed in cache.

ACCESS CONTROL
--------------
Source of truth:
  central LAN access_control.csv

Startup order:
1. Try central LAN access_control.csv first.
2. When LAN read succeeds, store this machine's latest access decision at:
     %LOCALAPPDATA%\QAC_Auto_Register\access_cache.json
3. If LAN read fails:
   - use the local access snapshot for the same IP;
   - active permissions remain usable;
   - window title shows [OFFLINE ACCESS CACHE].
4. If no local snapshot exists:
   - fail closed / contact developer.
5. If LAN is available and central status was changed to disabled/pending:
   that latest state overwrites the local snapshot. A later offline launch
   cannot resurrect an older active permission.

CENTRAL SYSTEM LOG
------------------
Central log is stored in the SAME directory as access_control.csv.

Filename:
  <machine IP>.jsonl

Example:
  10.203.5.243.jsonl

If central LAN logging is unavailable:
- QAC work is NOT blocked.
- log records queue locally at:
    %LOCALAPPDATA%\QAC_Auto_Register\pending_logs\
- queued records are replayed automatically when the LAN path works again.

IMPORTANT
---------
qac_cache.db is an acceleration/interlock cache only.
The real QAC page remains the source of truth.
Deleting qac_cache.db is safe; the program can rebuild it incrementally.


v1.7.2 LOCAL DATA IN PROGRAM FOLDER
===================================

Local runtime data no longer uses %LOCALAPPDATA%.

PyInstaller OneDir layout:
  QAC_Auto_Register\
  ├── QAC_Auto_Register.exe
  ├── qac_cache.db
  ├── access_cache.json
  ├── pending_logs\
  └── _internal\...

Files:
- qac_cache.db
  Shared persistent QAC SQLite cache.
- access_cache.json
  Last successful LAN access-control decision for this machine.
- pending_logs\
  Offline audit records waiting to sync back to the central LAN log.

Central behavior is unchanged:
- access_control.csv remains on LAN.
- <machine_ip>.jsonl remains beside central access_control.csv.
- LAN-first access control remains source of truth.

Development/source mode:
- Runtime local files are placed in the project root containing main.py.

PyInstaller --onedir:
- Runtime local files are placed beside QAC_Auto_Register.exe.


v1.7.3 REMOVE ALARM ROW HIGHLIGHT
=================================

Performance change:
- Removed Alarm Import active-row highlight/event-filter system.
- Removed full-row SelectRows handling added for highlight.
- Removed event filters from Checkbox / Machine / NG Product /
  Time Stop / Process Found.
- Alarm Import data, checkbox selection, duplicate interlock,
  SQLite cache, and register logic are unchanged.

Reason:
The embedded-widget event filters and repeated stylesheet changes on
large Alarm Import tables caused noticeable UI slowdown.

Build:
- build_onedir.bat updated to include Playwright explicitly.
- BUILD_ONE_LINE_POWERSHELL.txt contains the recommended PowerShell
  OneDir command.
- Auto.ico remains embedded into QAC_Auto_Register.exe.
- Auto.ico/Auto.png remain bundled for window/taskbar application icon.


v1.7.5 ALARM NAVIGATION RECOVERY + NO DRY RUN
================================================
- Alarm Save tolerates QAC navigation/context destruction.
- Complete wait retries navigation until timeout and requires a new Result ID.
- Raw Result ID is used for SQLite cache.
- Alarm Import Dry Run removed; confirmation before live import retained.
- OCR Dry Run unchanged.
\n\nv1.7.6 CACHE RECONCILE FOR DELETED/RECREATED QAC DOCUMENT\n==========================================================\n\nProblem:\nA QAC document can be deleted and recreated with the same Production Date,\nLine, Shift and Document No. That produces the same SQLite document_key.\nThe old implementation could return old cached events when the recreated\nQAC Timeline was empty.\n\nFix:\n- QAC Timeline Result IDs are always the source of truth.\n- Every sync reconciles SQLite to current Timeline IDs.\n- Cached Result IDs missing from QAC are deleted immediately.\n- Empty current Timeline deletes all cached events for that document.\n- Returned events are always filtered to current Timeline IDs.\n

v1.7.7 ALARM ACTION TAKEN
=========================

Alarm Import now has two additional columns:
- Action Type
- Action Detail

Per-row behavior:
1. No Action (default)
   Final QAC description:
     Machine Alarm <Column E> No Action Monitor Run

2. Action Taken
   Action Detail becomes editable and mandatory.
   Final QAC description:
     Machine Alarm <Column E> Action: <Action Detail>

Examples:
  Machine Alarm UNLOAD IDX-ST2: SEAL PIN VIS NG No Action Monitor Run

  Machine Alarm UNLOAD IDX-ST2: SEAL PIN VIS NG Action: Clean sensor and reset machine

Safety:
- Action Taken cannot Register with blank Action Detail.
- Each row can have its own Action.
- Existing-QAC matching uses the final per-row description.
- Changing Action Type/Detail resets the visible row status to NEW so an old
  EXISTS status is not accidentally trusted after the description changes.

v1.7.25 READ-ONLY QAC HTML COLLECTOR
====================================

Daily Document now includes an HTML Collector for the selected Master List rows.

Workflow:
1. Select Production Date and one or more documents.
2. Choose an Output Folder.
3. Click Collect HTML Selected.
4. The collector opens temporary QAC tabs, reads the rendered DOM, and closes
   only the temporary tabs it created.
5. Results are written under QAC_HTML_<yyyy-mm-dd>:
   - raw_html/*.html
   - schemas/*.json
   - document_schema.json
   - field_mapping.csv
   - extraction_report.csv
   - manifest.json

Safety:
- Read-only: never fills an input and never clicks Save/Complete.
- Missing documents are reported and never created automatically.
- Line and Model are not fixed mapping keys. Model is classified as ALL_MODEL
  from the live document name, otherwise DYNAMIC.
- data-item is diagnostic metadata; section/label/document identity are the
  portable mapping fields.
- Pause takes effect before the next document. Stop preserves completed files.
- Re-running the same Production Date and Output Folder resumes by skipping
  documents already marked COLLECTED in manifest.json.

v1.7.26 QAC LIST ASYNC LOAD BARRIER
===================================

HTML Collector no longer treats the first visible tr[data-task] as ready.
QAC can keep the previous date's rows visible while loading the requested day.

The collector now:
- waits up to 60 seconds for task rows whose data-lot exactly matches the
  requested Production Date;
- requires the target-date task signature to remain unchanged for 3 seconds;
- logs WAIT QAC LIST with target row count and currently visible dates;
- stops with a diagnostic error instead of marking every Master row MISSING
  when the requested date never becomes ready;
- waits up to 60 seconds for each exact Task ID Measure button.

v1.7.27 RESPONSE-GATED TWO-DATE STATE MACHINE
==============================================

HTML Collector follows the QAC browser workflow sequentially:
Login -> View More Production Check Sheet -> COMPLETE -> Calendar D-1 ->
COMPLETE -> Measure -> COMPLETE -> Capture HTML -> Back -> COMPLETE -> repeat.

Rules:
- The selected date automatically searches previous day first and selected day
  second. A document is MISSING only after both dates are complete and searched.
- COMPLETE requires document.readyState=complete, jQuery.active=0, a quiet
  interval, and the required destination DOM selector.
- One QAC module page is reused. When Measure opens in the same tab, browser
  Back is used. When QAC opens a new tab, only that Measure tab is closed.
- Calendar state is restored and confirmed after every Back operation.

v1.7.28 HIDDEN MEASURE ACTION CLONE FIX
=======================================

QAC can render more than 100 duplicate menu-measure-task links for one Task ID
and keep the action links hidden inside collapsed action menus. Waiting for the
first clone to become visible caused a 90-second timeout.

The collector now:
- searches all exact Task ID action clones for a visible candidate;
- clicks the visible candidate when one exists;
- otherwise dispatches the native DOM click on the exact hidden Measure action;
- waits for the Measure page COMPLETE barrier before reading HTML;
- limits action lookup to 15 seconds instead of waiting 90 seconds for a hidden
  clone that QAC does not intend to make visible automatically.

v1.7.29 CALENDAR AND BACK STATE FIX
===================================

- Always clicks the visible i.calendar-monitor control before selecting a date.
- Hidden QAC rows can no longer suppress calendar selection.
- Back from Measure accepts navigation commit and validates master.html by its
  visible calendar DOM instead of waiting indefinitely for DOMContentLoaded.
- Adds CALENDAR CLICK, DATE SELECTED, BACK START, BACK NAVIGATION ACK, and
  BACK READY progress states.

v1.7.30 REUSE LIST BEFORE CALENDAR
==================================

- After Back, checks the active Production Check Sheet list first.
- If at least one target-date row is visible, reuses all rows for that date and
  immediately continues to the next selected document.
- Opens Calendar only when the returned list is not on the target date.
- Hidden historical rows cannot falsely mark a date as active.

v1.7.31 CALENDAR CLONE AND ADJACENT-DAY FALLBACK
================================================

- Calendar day lookup now searches every exact data-day clone.
- Clicks the visible day clone when available; otherwise dispatches the exact
  QAC day action without waiting 30 seconds for a hidden wrapper.
- If the calendar overlay contains no target day, uses the QAC left/right date
  control for an adjacent date and lets the existing target-list barrier verify it.
- Adds DATE DOM CLICK and DATE ARROW CLICK diagnostic states.

v1.7.32 FIELD MAPPING CSV SCHEMA FIX
====================================

- Adds data_type and data_judge to the field_mapping.csv header.
- Builds every CSV row from the declared output schema, so optional or future
  parser metadata cannot terminate a completed HTML collection run.
- Keeps all collected HTML and checkpoint resume behavior unchanged.

v1.7.33 VISIBLE CALENDAR DAY CELL
=================================

- Treats calendar opening and day selection as two explicit actions.
- After clicking the calendar icon, prefers an exact visible data-day cell.
- Supports QAC's blue/current day cell, which can omit data-action/data-day, by
  clicking the visible day number inside the open calendar popup.
- Retains hidden-clone DOM click and adjacent-day arrow only as later fallbacks.

v1.7.34 DOCUMENT GROUPS AND GLOBAL ALARM LEARNING
=================================================

- Daily Document Type is separated into AUTO_CSV, MANUAL_OK_NG,
  MANUAL_VALUE, and REVIEW from the document name and period.
- Alarm Learning prefers the exact QAC line and falls back to the same alarm
  learned on any page/line when the current line has no history.
- Alarm table selections survive Document, Production Line, and Process Found
  combobox rebuilds during the current session.
- Learned values are applied only when the option exists on the current page.

v1.7.35 DAILY CHECK SHEET REGISTER ENGINE FIX
- Daily Register now supports OK/NG multi-slot fields instead of only Required/1-slot.
- NUMBER fields can be populated from an explicit actual-value file.
- Save success is verified from QAC result state, not click success alone.
- Historical D-1..D-5 values from collected schemas are shown as references only.
- Initial Sample, Alarm Import and Global Alarm Learning logic are unchanged.
