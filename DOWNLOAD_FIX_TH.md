# รุ่นแก้ Sample Save และการอ่านผลเดิม

รุ่นสำหรับทดสอบ ยังไม่ได้ยืนยันการบันทึกบน QAC จริง และไม่มี Windows EXE

## การดาวน์โหลดและติดตั้งในโปรเจ็คเดิม

1. ดาวน์โหลด ZIP ของ branch นี้จาก GitHub แล้วแตกไฟล์
2. สำรองโปรเจ็คเดิมก่อน
3. คัดลอก `app/sample_register.py` และ `app/sample_result_snapshot.py` ไปที่โฟลเดอร์ `app` ของโปรเจ็คเดิม ต้องใช้ทั้งสองไฟล์ร่วมกัน
4. เก็บ `config/settings.json`, `config/access_control.csv`, mapping database และ config อื่นของเครื่องเดิมไว้
5. ถ้าใช้ EXE ต้อง rebuild จาก source ตามขั้นตอน build ที่ใช้อยู่ การเปลี่ยนไฟล์ Python ภายนอก EXE ไม่ได้แก้ตัว EXE
6. ทดลองกับเอกสารทดสอบก่อนใช้งานจริง

GitHub ZIP นี้ไม่รวม settings ประจำเครื่อง, access cache, access CSV, local SQLite database และ logs จึงไม่ใช่แพ็กเกจที่พร้อมเปิดใช้บนเครื่องใหม่โดยไม่ตั้งค่า

## สิ่งที่เปลี่ยน

- Sample ช่อง Text เช่นหัวข้อ 1-1/1-2 ใช้ Tab เพื่อ commit และออกจากช่องก่อนหา Save ป้องกัน focusout ซ่อนปุ่มระหว่างคลิก
- ถ้า QAC เปิด Confirm เองแล้ว จะไม่กด Save ซ้ำ และรอ Complete ก่อนทำข้อต่อไป
- Sample Prepare อ่านโครงสร้าง HTML ครั้งเดียว แล้วอ่านผลเดิมผ่าน getItemContent พร้อมกันไม่เกิน 3 requests โดยไม่เปิดทีละข้อ ปกติยังมีหนึ่ง read request ต่อข้อ เนื่องจาก API ที่พบรับหนึ่ง item ต่อ request
- ถ้าข้อมูลบางข้อไม่ชัดเจน จะกลับไปเปิดอ่านเฉพาะข้อนั้น ส่วนก่อนเขียนยังตรวจข้อเป้าหมายจริง
- ไม่เปลี่ยนอัลกอริทึม Auto Register และ Daily Check Sheet ในรุ่นนี้

## ผลตรวจ

Offline regression: 331 passed, 4 failed เพราะไม่ได้แนบ external HTML fixtures, 32 subtests passed
ยังไม่ได้วัด performance บน QAC จริง หรือทดสอบ Windows GUI/EXE แบบ end-to-end
