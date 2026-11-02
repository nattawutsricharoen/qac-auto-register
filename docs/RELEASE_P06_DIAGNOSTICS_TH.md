# QAC Auto Register v1.7.65 P06 — Diagnostic Coverage (Test Candidate)

## ขอบเขตที่แก้ไข
- `app/worker.py`: ทุก QThread Workflow ที่มี `progress` จะส่งข้อความเข้าไฟล์ Technical Log โดยคงการแสดงใน UI เดิม
- `app/qac_interaction.py`: log Modal classification, Click Start/Return/Uncertain, เวลาคลิก และสถานะ Popup หลังเกิด Exception
- `logs/qac_interaction.log`: สร้างเมื่อใช้งานจริง, หมุนไฟล์สูงสุด 5 MB ต่อไฟล์ และ Backup 5 ชุด
- รองรับ `QAC_DIAGNOSTIC_LOG_DIR` สำหรับกำหนดตำแหน่งเก็บ Log
- Mask คำที่เข้าข่าย password/token/cookie โดยพื้นฐาน (ไม่ควรพิมพ์ Password ในช่อง Remark หรือข้อความอิสระ)
- คงวิธี Click/Retry ของแต่ละ Workflow เดิม ไม่ฝืนกดและไม่กด Save ซ้ำโดยอัตโนมัติ

## ผลทดสอบ
- PYTHONPATH=. pytest -q : 115 passed + 6 subtests
- Python compile: ผ่าน
- ยังไม่สามารถทดสอบ GUI Windows, QAC Server จริง, การตอบ Complete/Refresh สำหรับทุก Workflow

## ข้อจำกัดที่ยังไม่แก้
- การรอ Complete / Recovery 60 วินาทีหลัง Save ยังมี Logic เฉพาะหน้า ซึ่งยังต้องทดสอบด้วย QAC จริง
- Browser Click timeout ยังสามารถเกิดได้เมื่อ DOM เคลื่อนไหวและจะแสดง `UNCERTAIN` เพิ่มใน Technical Log
- Logging เฉพาะเหตุการณ์ที่ Worker ส่ง progress และ shared QAC modal; ยังไม่ครอบคลุมทุก DOM action ภายในฟังก์ชันชั้นล่าง
- ก่อนส่ง Production ต้องทดสอบ Auto/Alarm/OCR/Output/Daily/Sample/Transfer บน Windows + QAC และพิสูจน์การไม่ลงทะเบียนซ้ำ

## วิธีติดตั้ง
สำรองโปรแกรมและ SQLite/config ก่อน, แตก ZIP ในโฟลเดอร์แยก, อย่าทับ Production ที่กำลังใช้งาน
