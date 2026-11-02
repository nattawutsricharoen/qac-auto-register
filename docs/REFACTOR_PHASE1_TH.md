# QAC Architecture Refactor — Phase 1 (development candidate)

ต้นทาง: P11_76_CRITICAL_SAFETY_QA_CANDIDATE — ไม่เปลี่ยน logic การบันทึก QAC

## ทำแล้ว
- `app/core/local_connection.py` ตรวจ CDP ของ Local Browser และเปิดให้เมื่อยังไม่พร้อม; **ไม่มีการ Scan และไม่คลิก QAC**
- `app/core/reference_date.py` เก็บวันอ้างอิงกลางและวันของแต่ละ Module แยกกัน; แก้วันที่เฉพาะหน้าได้
- `app/modules/auto_register.py` เก็บสถานะเอกสารและป้องกันการแทนรายการระหว่าง Register
- ปุ่มดำเนินการสำคัญ ได้แก่ Auto Register, Sample Prepare/Register, Daily Register, Alarm Import และ Production Transfer ตรวจ Employee ID และ Local Browser ก่อนเริ่ม
- ผลการ Scan QAC Tabs ที่ผู้ใช้สั่งเอง: ถ้าเอกสารทั้งหมดมีวันเดียวกันจะเผยแพร่วันนั้นเป็นค่าเริ่มต้นของ Daily/Sample; วันปรับเองไม่ถูกทับ
- Scan QAC Tabs และ Daily Scan Selected ถูกกั้นขณะ Worker ที่รู้จักกำลังทำงาน
- มี Offline Unit Tests สำหรับ Local Connection, Date Independence และ Scan State

## ยังไม่เสร็จ / ต้องดำเนินการก่อนใช้งาน Production
- ยังไม่ได้ย้าย Worker / QWebEngine / CDP Profile ของทุก Module จาก `main.py` และ `worker.py` แยกให้สมบูรณ์
- Sample Prepare ยังอ้างอิง Auto Register Line และ Daily Document selection (legacy); จึงยังไม่ผ่านเป้าหมาย Isolation
- หน้า Alarm/OCR/Production ยังคงได้รับเอกสารจาก `scan_completed()` แบบเดิมเพื่อป้องกัน backward compatibility แตก; ต้องออกแบบ source แยก
- Guard ครอบเฉพาะ action สำคัญ ไม่ใช่ทุกปุ่ม UI (ปุ่ม File/Settings ไม่ควรเปิด Browser)
- การเปิด Local Browser สำเร็จไม่ได้รับประกัน login/QAC page identity ถูกต้อง; ต้องทดสอบหน้างาน
- ยังไม่ทดสอบ Live QAC หรือการ Register จริง ไม่มีข้อยืนยันว่า Sample Register หรือ Auto Register ทำงานสำเร็จ

## เกณฑ์ก่อนปล่อย Production
1. Module แยก Browser Profile, Session, Worker, State, Cancel/Abort อย่างชัดเจน
2. Register ไม่สั่ง Scan แฝง, ไม่ Login แฝงระหว่างงาน; Recheck ที่จำเป็นต้องตรวจเฉพาะ record/slot ไม่ใช่ Full Scan
3. เริ่มการทำงานหลัง Employee ID + Local Browser ready + QAC page identity ready
4. ทดสอบ Known Good workflows เปรียบเทียบ P11_76 + Regression และทดสอบหน้างานด้วยสิทธิ์จริง
5. Rollback กลับเวอร์ชันเดิมได้ทันที
