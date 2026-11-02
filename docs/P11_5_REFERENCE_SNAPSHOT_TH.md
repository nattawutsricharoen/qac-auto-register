# P11.5 Reference Snapshot Safety Patch

- เมื่อเปิดหน้า QAC Reference บันทึก HTML ทั้งหน้าและตารางที่แสดงใน `database/daily_reference_snapshots.sqlite3` ก่อนปิดหน้า
- เก็บ task, requested date, document identity, result fields, identity_verified และ timestamp แบบ transaction commit
- Reference identity ไม่ผ่าน: เก็บ snapshot เพื่อวิเคราะห์ แต่ **ไม่ใช้เป็นค่าตั้งต้น** และหยุดก่อน Register
- Reference ไม่เจอ/เจอหลาย Task/เกิดข้อผิดพลาด: หยุดก่อน Register พร้อม Log `DAILY REFERENCE STOP`
- Reference View แบบตารางยังไม่มี verified item/slot mapping จาก HTML จริง: snapshot เป็นหลักฐานดิบ ไม่ใช่ validated values สำหรับ auto register
- โปรแกรมยังไม่ได้รับการทดสอบกับ QAC จริง ห้ามถือว่า QAC save สำเร็จจากข้อความ Complete! เท่านั้น
