# P11.9 — Reference Snapshot ไม่ควรบล็อก Manual Register

## สาเหตุจาก P11.8
`discover_daily_slots` สั่ง `raise RuntimeError('DAILY REFERENCE STOP ...')` เมื่อวันที่ Reference ไม่ตรงกับวันที่ร้องขอ แม้จะอ่าน Slot ของเอกสารเป้าหมายสำเร็จแล้ว ทำให้ไม่สามารถเปิดหน้าต่างเลือกผล Manual ได้

## เปลี่ยนแปลง
- Reference Snapshot ที่มีข้อมูลผิดวันที่/ไม่ตรง Identity ยังบันทึกไว้สำหรับ Audit แต่ไม่ถูกอนุญาตให้ส่งค่าไปลงเอกสารเป้าหมาย
- ถ้าการอ่าน Reference ไม่ผ่าน ให้ล้างค่า `previous_*`/`reference_source` ออกจากแผน Slot แล้วเปิดให้ผู้ใช้เลือกผล Manual ต่อ
- การป้องกันการลงซ้ำต้องอ้างอิงสถานะจริงของ Target QAC และกฎ Preflight ณ เวลา Register ต่อไป ไม่ถือ Reference Snapshot เป็นผลที่บันทึกใน Target
- Log ใหม่ `DAILY REFERENCE UNAVAILABLE` และ `DAILY MANUAL PLAN READY`

## ยังไม่ได้แก้
- สาเหตุวันที่ QAC เลือก 2026-10-15 แต่รายการกลับแสดง lot วันที่ 2026-10-16
- การยืนยัน Result ID หลัง Save ในระบบ QAC จริง
- การจับคู่ Item ID ระหว่างหน้า View Matrix กับหน้า Measure

## การทดสอบ
รัน pytest กับ Source Code สำเร็จ; ยังไม่ได้รันทดสอบบน QAC Server จริง อย่า Register งานจริงจำนวนมากก่อนยืนยันบนเอกสารเดียว
