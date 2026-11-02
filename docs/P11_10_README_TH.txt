P11.10 Daily Document Item-Level Save

ปรับจาก P11.9 โดยคง OCR/Auto Register/Sample Register ที่ไม่เกี่ยวข้องไว้
1) ตรวจสอบ Slot ที่บันทึกแล้ว และข้ามโดยไม่เขียนซ้ำ
2) ทำรายการ OK/NG หรือ Value ที่เลือกทุก Slot ของหนึ่งหัวข้อให้เสร็จก่อน Save หนึ่งครั้ง
3) เมื่อ Save แล้วตรวจ Result ID ทุกช่องที่ร้องขอ; ไม่พบให้หยุดและไม่ Retry การเขียน
4) ไม่เก็บ Full HTML Snapshot เพิ่มในเส้นทาง Register; แยก Snapshot ของ Reference เดิมออกจากการลง Manual
5) ZIP ลดไฟล์ DOCS/TEST_REPORT รุ่นเก่าและ cache ทดสอบ แต่ยังเก็บ tools/Tesseract-OCR เพราะระบบ OCR Import ใช้งานร่วมกัน

Verification: offline pytest 133 passed + 6 subtests
Limits: HTML ที่ได้รับยังแสดง No Result บางหัวข้อ; Browser แบบ dynamic และ QAC server ยังไม่ได้ทดสอบกับการ Save จริง.
