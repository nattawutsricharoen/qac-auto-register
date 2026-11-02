# P10 — Daily Latest Result Memory and Review Gate (Test Candidate)

- อ่าน Item/Slot และ Result ปัจจุบันจาก QAC HTML จริงเสมอ
- อ่านค่าแนะนำล่าสุดจาก SQLite ในเครื่องแทนการย้อน D-1 ผ่าน QAC ทุกครั้ง
- แยก Line+Document No.+Document Name+Model; เอกสารชื่อ All Model ใช้ ALL_MODEL ร่วมกัน
- หาก Model ไม่ทราบ (และไม่ใช่ All Model) ไม่โหลด/เก็บค่าเก่า เพื่อลดความเสี่ยงข้ามรุ่น
- SQLite บันทึกค่าแบบ UPSERT หนึ่งแถวต่อ Item+Slot เก็บเฉพาะล่าสุด; เขียนใหม่หลังตรวจ Result ID จาก HTML
- ก่อน Register ต้องเลื่อนดูรายการจนถึงล่างสุดและติ๊กยืนยันหนึ่งครั้งต่อเอกสาร; เปลี่ยนค่าแล้วต้องตรวจใหม่
- งาน Daily ไม่ใช้ Sample Match Rules และไม่เติม Item ให้ครบ frequency เอง
- หลัง Save โปรแกรมรอ Result ID จาก HTML ต่อไป ไม่มี Server-Speed Timeout ตัดสินว่า Save Failed; มี Log ทุก 20 วินาที และยังสามารถสั่ง Stop ผ่าน Worker Control ได้
- เวลาเปิดเอกสารและการรอ UI Locator ยังคงมี Safety Timeout ทางเทคนิค (ไม่ใช่ Server Save Timeout)

## ข้อจำกัดสำคัญ
1. ไม่ได้รันจริงกับ QAC Server หรือ Windows PySide6; ต้องทดสอบก่อน Production.
2. การบันทึก OK/NG หรือค่าที่แนะนำเป็นการคัดลอกผลเดิม ผู้ปฏิบัติงานต้องรับผิดชอบตรวจสอบจริง.
3. Data source ที่มี Model หายไปจะไม่ทำ Memory เพื่อกันข้อมูล S91 ไปปน S92; ตรวจ Log `MODEL_UNKNOWN`.
4. ช่องที่ QAC HTML มี Result ID จะไม่ถูกเขียนซ้ำ.
5. การรอ Result ID ไม่จำกัดตามความเร็ว Server ตาม Requirement; หากระบบหยุดตอบสนองจริง ต้องให้ผู้ใช้ Stop และตรวจผลก่อนรันใหม่.
