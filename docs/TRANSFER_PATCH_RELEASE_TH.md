# QAC Auto Register — Transfer + OMBiz Header

เปลี่ยนเฉพาะสองเรื่องจาก PARTIAL_VALIDATED_20261017

1. เพิ่ม `Transfer Data to QAC` ใน Production Output พร้อมแยก QThread / Playwright asyncio และล็อกปุ่มระหว่างทำงาน
2. เพิ่ม `OMBiz` ด้านขวาของแถบหัวโปรแกรมทุกหน้า (`app/modern_shell.py`)

Flow ของ Transfer: ใช้ Employee ID ปัจจุบัน → CDP Edge → เปิด QAC Inflator Data Inspection (process=10, product=4) ในแท็บแยก → ตรวจ Lot เดิมในรายการที่มองเห็น → Register Task → เลือกไฟล์ → Submit ครั้งเดียว → ต้องได้ success popup → ค้น Lot เพียงหนึ่ง Task → ตรวจ Inspection Result แถว Judge ทุกคอลัมน์เป็น PASS → Checked → success popup → Close

FAIL CLOSED: ไม่พบ Task / ไม่ตรง Lot / Judge ไม่ครบหรือ NG / popup ไม่ชัดเจน → หยุดทันที ห้าม retry upload เอง. ระวังว่ารายการ QAC อาจแบ่งหน้า/โหลดไม่ครบ ทำให้การตรวจ Lot ซ้ำไม่ครอบคลุมทุก Task.

ผลทดสอบในระบบพัฒนา: 112 pytest ผ่าน + 6 subtests, Python compile ผ่าน. **ยังไม่มีการทดลอง QAC Live, Browser login, Upload, Checked, GUI บน Windows** และยังไม่มีหลักฐานว่าผ่านการตรวจ Task ที่อยู่คนละหน้า/วันที่. ห้ามเรียกว่า Production Ready จนผ่านการทดสอบ End-to-End บน QAC จริง. ก่อนทดลองต้อง Backup โปรเจกต์และข้อมูล และใช้ไฟล์ทดลองที่อนุญาต ไม่ควรทดลองกับ Lot ที่มีข้อมูล Production อยู่แล้ว.
