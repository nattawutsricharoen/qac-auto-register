# P11.13 — Daily HTML-driven register

เปลี่ยนเฉพาะ Daily Document Register จากลำดับการกดแบบตายตัว เป็นตรวจ DOM ของ Item ที่เปิดหลังทุก Slot:
- หลัง OK/NG หรือกรอกตัวเลข อ่านว่า Save/OK/NG เปิดให้กดจริงหรือไม่
- ถ้ามี Slot ตามแผนเหลือ ตรวจ/ลง Slot ถัดไป ไม่กด Save ก่อนจบแผน แม้ Save เปิดก่อน
- หลัง Slot สุดท้าย ต้องพบ Save ที่มองเห็นจริงจึงคลิก ไม่ Force Click และไม่กด Insert result
- ช่องตัวเลขตรวจค่าที่ใส่กับ Input สดอีกครั้ง
- หยุดเมื่อ Item ผิด, Save มากกว่า 1 ปุ่ม, หรือไม่พบ Action State ที่ถูกต้อง
- ตรวจ DOM เฉพาะ Item ที่กำลังใช้งาน ไม่อ่าน HTML ทั้งหน้าซ้ำทุกครั้ง

ทดสอบ: pytest 142 passed, 6 subtests passed (offline only).
ข้อจำกัด: ยังไม่ทดสอบ QAC Server จริง; P11.12 ยังมีปัญหา saved=0 / การยืนยัน Numeric Result หลัง Save ที่ต้องตรวจต่อจาก Live Trace; เวอร์ชันนี้ไม่ยืนยันว่าแก้ทุก Bug และยังไม่ Benchmark CPU/RAM.
