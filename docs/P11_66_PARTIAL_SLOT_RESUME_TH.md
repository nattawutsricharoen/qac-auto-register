# P11.66 — Resume Partial Sample Slot

- เมื่อ Prepare พบ Partial Slot ก่อน Slot ว่างถัดไป จะแสดง Dialog ให้เลือกใช้ Slot เดิมหรือ Slot ว่างถัดไป หรือยกเลิก
- กรณีใช้งาน Slot เดิม ผู้ปฏิบัติงานเป็นผู้ยืนยันว่าเป็น 2D ที่เลือก โปรแกรมไม่ได้พิสูจน์เจ้าของ 2D จาก QAC อัตโนมัติ
- อนุญาตเฉพาะ Slot ที่ถูกสแกนจากหน้า QAC จริง และทุก Document ในชุดต้องรองรับ Slot เดียวกัน
- ระหว่าง Register ตรวจข้อมูลล่าสุดของแต่ละ Item: EXIST+MATCH => SKIP, EMPTY => WRITE; EXIST+MISMATCH/UNKNOWN => HALT โดยไม่เขียนทับ
- ยังคงทำงานตาม Plan ทีละ Sample และยังไม่ใช่ Batch แบบเปิดเอกสารครั้งเดียวหลาย Slot
- ผลทดสอบ: 290 passed + 32 subtests (Offline); ยังไม่ได้ทดสอบบน QAC Server/Windows GUI จริง
