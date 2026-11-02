# P11.64 – Partial Slot / 2D Ownership Guard

- อ่านทุก QAC Item ก่อนตรวจ Slot และรายงาน Slot ที่มีข้อมูลไม่ครบทุก Item
- หาก Slot ถัดไปเป็น Partial และไม่มีหลักฐานระบุว่าเป็น 2D ใด ให้หยุด Prepare พร้อม `PARTIAL_SLOT_REQUIRES_2D_PROOF`
- ตัวอย่าง Slot 8: `Upper electrode No.` มีข้อมูล แต่ช่องอื่นว่าง ไม่สามารถถือว่าเป็น 2D ที่กำลังเตรียมเพียงเพราะค่าตรงกันได้
- **ยังไม่รองรับการ Resume Partial Slot ที่ยืนยันเจ้าของแล้วแบบอัตโนมัติ**: Trace comment เก่าเก็บ 2D+Time แต่ไม่เก็บ Slot จึงยังไม่มีหลักฐานเชื่อมกับหมายเลข Slot โดยตรง
- แพตช์นี้ตั้งใจให้ Fail Closed ไม่เขียนทับหรือเลือก Slot ใหม่เงียบ ๆ
- ขอบเขตทดสอบ: Offline pytest / Python compile; ไม่ได้เชื่อม QAC Server
