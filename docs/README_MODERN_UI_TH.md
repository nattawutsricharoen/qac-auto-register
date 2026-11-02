# QAC Auto Register — Modern PySide6 UI Patch

ฐาน: QAC_Auto_Register_v1_7_65_ELECTRODE_NO_SHOT_HISTORY_SIMPLIFIED.zip

## เปลี่ยนแปลง
- เพิ่ม `app/modern_shell.py` สำหรับ Navigation Sidebar, Home Dashboard, Quick Access และ QSS theme
- ปรับ `main.py` ให้ใช้งาน ModernShell เป็น Central Widget โดยเก็บทุกหน้าฟังก์ชันเดิมไว้
- หน้าควบคุม QAC Connection ถูกย้ายไปบนแท็บ Auto Register (ยังใช้เมธอดเดิม)
- ปุ่ม Home/Sidebar เปลี่ยนเฉพาะหน้าจอ ไม่สั่งทำงาน QAC / เปลี่ยนแท็บ Browser เอง
- ตรงกับ access permissions เดิม: เมนูที่ไม่มีสิทธิ์ถูก Disable
- Dashboard ไม่สร้าง KPI หรือสถานะ Connected ปลอม

## จุดที่ไม่ได้เปลี่ยน
- Workers, QAC Login, Playwright, Import, Scan, Register, Daily, Sample, Electrode/Shot/History, Database
- โปรแกรมยังต้องอาศัย configuration/access_control เดิมที่เครื่องหน้างานและยังไม่ใช่ Android

## ผลทดสอบ
- Python compileall: PASSED
- pytest: 102 passed + 6 subtests passed
- PySide6 GUI launch, click / screenshot on Windows: NOT TESTED (environment lacks PySide6 and cannot download dependency)
- End-to-end QAC live login/register: NOT TESTED

## ติดตั้งทดสอบ
1. สำรองทั้งโฟลเดอร์โปรแกรมและฐานข้อมูลก่อน
2. แตก ZIP ลงโฟลเดอร์ทดสอบใหม่ (อย่าทับ Production ทันที)
3. ติดตั้ง requirements.txt ผ่าน Python environment บน Windows ที่ใช้รันโปรแกรมเดิม
4. ตรวจ config/settings.json และ config/access_control.csv ให้ตรงสภาพแวดล้อมจริง
5. เรียก `python main.py` จากโฟลเดอร์ qac_1759
6. ตรวจว่า Home เปิดได้, เมนู Sidebar เปิดหน้าเดิมได้, Connect QAC ยังอยู่ใน Auto Register, และสลับหน้าไม่ก่อให้เกิด QAC Navigation
7. ทดสอบ Auto/Daily/Sample/History ด้วยข้อมูลทดสอบที่ปลอดภัยก่อนปล่อย Production

## ข้อจำกัด
งานนี้คือ UI redesign ขั้นแรกของโครงหลักและ theme ภายใน ไม่ใช่การทำ pixel-perfect ทุกหน้าตามภาพจำลอง และยังไม่ได้ผ่าน GUI runtime test จึงไม่ใช่ Production Ready
