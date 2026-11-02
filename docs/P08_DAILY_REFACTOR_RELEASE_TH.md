# QAC Auto Register v1.7.65 P08 — Daily Document Independent Slot Register

**สถานะ: TEST CANDIDATE — ยังไม่ได้ทดสอบ QAC Server จริง และไม่ได้ทดสอบ GUI บน Windows/PySide6**

## โครงสร้างใหม่
- `app/qac_task_scan.py` — Scanner สำหรับ QAC Task ใช้ร่วมกัน (ไม่มีกฎ Daily/Sample)
- `app/qac_measure_actions.py` — คลิก Save/Popup และตรวจ Result QAC ส่วนกลาง
- `app/daily_slot_schema.py` — อ่านหน้าแรก Measure HTML ของ Daily และตรวจความถูกต้อง Slot/Item
- `app/daily_slot_memory.py` — Template แบบบันทึกอย่างชัดเจน (แยกเอกสาร/Line/Model/Period)
- `app/daily_document_register.py` — **Daily-only** Register เฉพาะ Item/Slot ที่พนักงานเลือก ไม่คำนวณจำนวนจาก Time Slot ของ Item อื่น
- `app/sample_register.py` — Exact Sample Business Logic เดิม; ไม่มี import จาก Daily Register หรือ Daily Task Scan อีกต่อไป

## วิธีใช้งาน
1. เปิดโปรแกรมแล้วเข้าสู่ QAC Module ของ Daily Document
2. Scan Selected ให้พบเอกสาร Task ID จริงใน QAC
3. เลือกเอกสารแล้วคลิก Register
4. โปรแกรมเปิด Measure เพื่ออ่าน Inspection Items, Slot และ Result ที่ลงแล้วจาก HTML ปัจจุบัน (มีหน้าต่างรอขณะอ่าน)
5. เลือกชนิดผลตรวจใน ComboBox ราย Slot: ไม่ลง / Initial / Middle / Final หรือ OK / NG ตามชนิด Item ที่ HTML รองรับ; VALUE ต้องกรอกค่าจริง
6. ช่องที่ QAC มี Result ID แล้วจะไม่ให้เลือก/เขียนทับ
7. สามารถ Load Template, Save Template และ Reset Template แยกตามเอกสาร โดย Template ไม่บันทึกค่าตัวเลขหรือผลตรวจที่ผ่านมา
8. ยืนยันแผนก่อนเริ่มบันทึกจริง; โปรแกรมตรวจ HTML ใหม่ก่อนบันทึกและหยุดทันทีเมื่อโครงสร้างเปลี่ยน, Slot ไม่ตรง, หรือยังไม่ทราบผล Save

## ข้อจำกัดที่ต้องทราบ
- QAC บางหน้าอาจอนุญาตบันทึก Slot แบบลำดับต่อเนื่องเท่านั้น จึงป้องกันการข้าม Slot ที่ยังว่างไว้ก่อน ไม่สร้างผลแทนหน้างาน
- ไม่ตีความ Popup Complete อย่างเดียวเป็นการยืนยันผลถาวร โดยพยายามตรวจ Result ID ของ Item/Slot หลัง Save
- เมื่อผลหลัง Save ไม่ชัดเจน ระบบหยุดรายการนั้น ไม่บันทึกซ้ำอัตโนมัติ
- Template เวลาเดิมของ P07 ไม่ได้ถูกลบจากฐานข้อมูล แต่ UI ใหม่ใช้ Slot Choice Template แยกต่างหาก ไม่ย้ายค่าตัวเลข/เวลาเดิมไปกรอกโดยอัตโนมัติ
- Session/DOM/ปุ่ม Save จริงแต่ละรูปแบบของ QAC ต้องทดสอบหน้างานก่อนนำไปใช้ข้อมูล Production; ทดสอบ Python ไม่เพียงพอต่อการรับรองการลงทะเบียนจริง

## สรุปการตรวจ
- Python compileall: PASS
- pytest: 119 passed + 6 subtests
- ไม่มี PySide6 ในสภาพแวดล้อมทดสอบนี้ จึงยังไม่ได้ GUI Smoke Test
- ยังไม่มีการทดสอบ Microsoft Edge + QAC Production Server จริง
