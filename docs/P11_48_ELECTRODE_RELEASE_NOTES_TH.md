# P11.48 — Electrode control UX / legacy regrind interlock

- Admin: เปิด/ปิดการตรวจสอบประวัติ RETURN ของ Original/R ก่อนหน้า (ค่าเริ่มต้น **เปิด**); เมื่อปิด อนุญาตให้เบิก -R1…-R5 ที่ไม่มีประวัติย้อนหลังได้ เฉพาะใน Local SQLite นี้ ไม่ยกเลิกการตรวจสอบเบิกค้างซ้ำหรือเคยคืน Barcode เดียวกันแล้ว
- First scan: เมื่อมี Machine Mapping **เพียงรายการเดียว** บันทึก ISSUE ทันทีโดยไม่มีกล่องยืนยัน; ถ้ามีหลายรายการต้องเลือกเครื่อง/Station ก่อนบันทึก ไม่มีการเลือกเครื่องแรกให้เอง
- Admin: ตารางสรุป Electrode Master/Mapping ที่บันทึกไว้, บันทึก Target + Mapping ใน transaction เดียว, อัปเดต Target Mapping เดิมได้, ล้างฟอร์มหลังบันทึกสำเร็จ
- Admin: ล็อกเมื่อสลับออกจากแท็บ หรือซ่อนหน้าจอ Electrode
- Sample Register: รักษา P11.47 ไว้ ไม่แก้ workflow

## ข้อจำกัด
- Local SQLite ต่อเครื่องเท่านั้น, outbox ยังไม่ Sync LAN; ไม่ป้องกันเบิกซ้ำข้ามเครื่อง
- Admin PIN ยังคงตรวจภายใน Desktop client; ไม่มี server authorization
- ยังไม่ได้ทดสอบ PySide6 GUI จริงบนเครื่อง Windows หรือ QAC production
- โหมดปิด interlock เป็นการยกเว้นประวัติเก่า ไม่ยกเว้นกฎ Barcode uniqueness, Target, Mapping
