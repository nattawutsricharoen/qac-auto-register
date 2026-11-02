# P11.3 Daily click diagnostics and guarded Back

## หลักฐานจาก Log วันที่ 2026-10-19
- พบ Task 1327891 แต่ไม่มีการบันทึกสำเร็จ (`saved=0`)
- Fail ที่ item 411399 / slot 1 / OK
- reference 2026-10-15 มี identity mismatch จึงไม่ถูกนำค่ามาใช้
- `BACK START` ไม่ใช่หลักฐานว่าถูก Logout จริง ต้องตรวจ URL/Login form ประกอบ

## การแก้ไข
1. Daily format 3 และ format 4 เมื่อ Click ไม่สำเร็จ จะรายงาน Playwright error และ DOM diagnostic (URL, field visibility, button candidates, matching selector) เพื่อหาสาเหตุโดยไม่เดา/ไม่คลิกซ้ำ
2. ฟังก์ชัน Back ตรวจว่าหน้า Check Sheet เปิดอยู่แล้วหรือไม่ หากเปิดอยู่จะไม่กด go_back ซ้ำ
3. ตรวจพบหน้า Login ก่อน/หลัง Back ให้หยุดพร้อมข้อความแจ้ง แทนการนำทางต่อไป

## ข้อจำกัด
- ไม่ได้เปลี่ยน Selector OK/NG เพราะยังไม่มี QAC Measure HTML ของ item 411399 ยืนยัน DOM ปุ่มจริง
- ไม่ได้เปลี่ยนกลไก Back ของ QAC ที่ยังจำเป็นต้องย้อนหน้ากรณี Measure อยู่ในแท็บเดิม ต้องเก็บ DOM/URL จริงก่อนตัดสินใจปรับวิธีนำทาง
- row_dates ต่างจาก monitor date อาจถูกต้องตามช่วงเวลาผลิตของ QAC ไม่ใช้หลักฐานนี้เพียงอย่างเดียวตัดสินว่าผิด
- ยังไม่ได้ทดสอบกับ QAC จริง การทดสอบ 124 pytest + 6 subtests ไม่เท่ากับ end-to-end

## รอบทดสอบถัดไป
ทดสอบเอกสารเดียวก่อน ตรวจ DAILY CLICK DIAGNOSTIC และ BACK NAVIGATION/BACK SKIP หากยัง fail แล้วส่ง log กลับมา หยุดก่อนลงงานจริงแบบหลายเอกสาร
