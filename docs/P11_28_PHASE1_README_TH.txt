QAC Auto Register P11.28 PHASE 1 - Independent Durable Scan Checkpoints

ฐานโค้ด: P11.27
สิ่งที่เพิ่ม:
- app/daily_scan_checkpoint.py: ตาราง SQLite แยก TARGET และ REFERENCE
- คีย์แยกขอบเขต Line, Model (All Model ตามกฎเดิม), Document No., Document Name, Production Date และ Task ID
- บันทึก TARGET checkpoint หลังยืนยันหน้า Measure และอ่านผล Item ครบ ก่อนเริ่มค้น Reference
- บันทึก REFERENCE checkpoint หลังยืนยันหน้า Measure และอ่านผล Item ครบ ก่อนปิดหน้า QAC
- มี 4 regression cases สำหรับความแยกอิสระ, restart, line/model isolation และ fail-closed

ขอบเขตที่ยังไม่เสร็จ:
- ยังไม่เชื่อม UI ให้ Retry/Resume เฉพาะ TARGET หรือ REFERENCE จาก checkpoint
- ยังไม่ได้เพิ่ม Batch DOM Reader, Multi-select end-to-end, Responsive UI ทุกหน้า หรือ Learning Engine กลาง
- Checkpoint เป็นหลักฐานการอ่านในอดีตเท่านั้น ห้ามนำไปแทน live preflight ก่อน Register
- ยังไม่ได้ทดสอบกับ QAC Server/Windows GUI จริง ห้ามใช้กับข้อมูล Production จนผ่านการทดสอบ
