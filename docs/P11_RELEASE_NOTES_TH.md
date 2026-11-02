# QAC Auto Register P11 — Daily Scroll and Reference Date (Test Candidate)

ฐาน P10 โปรแกรมเต็ม

- ไม่เลื่อนกลับบนสุดเองเมื่อแก้ช่อง Result. ถ้าแก้หลังจากตรวจทานครบ ต้องกลับไปบนสุดและเลื่อนลงล่างเพื่อยืนยันใหม่ด้วยตนเอง
- หน้า Daily Document เพิ่ม checkbox Read reference results from QAC date และตัวเลือกวันที่ก่อน Production Date
- เมื่อเปิดใช้ Reference Date ระบบจะนำทาง QAC ไปวันที่เลือก ค้นชื่อเอกสารที่ตรงกันแบบ exact แล้วเปิด Measure เพื่ออ่าน Result ID และค่าที่แสดงใน HTML จริง จากนั้นคืนวันที่เดิม
- หากไม่เลือก Reference Date จะใช้ latest-memory ใน SQLite เช่นเดิม
- หากอ้างอิงหาไม่ได้หรือพบหลาย Task ระบบไม่เดาค่า และแสดงสาเหตุใน Daily Log
- ค่า OK/NG และ Initial/Middle/Final จะใช้อ้างอิงเฉพาะเมื่อ QAC HTML แสดงเป็นข้อความที่ตีความได้ชัดเจน ไม่เดาจาก data-type

ยังไม่ได้ทดสอบ Live QAC บน Windows และการดึงผลย้อนหลังจริงทุกชนิด HTML จึงต้องทดลองกับเอกสารที่ได้รับอนุญาตก่อนใช้ Production
