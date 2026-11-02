QAC Auto Register — Electrode Control Simple UI

- แสดงเฉพาะ Electrode No. / Shot และ History / Export
- Change Electrode: Old Final Shot ต้องกรอกเองทุกครั้ง, New Start Shot เริ่ม 0 แต่แก้ไขได้
- Save Shot: พนักงานบันทึก Shot ล่าสุด, ไม่ให้ลดลงจากค่าที่เคยบันทึก
- Master อยู่ในปุ่ม Settings (Admin PIN 12338) ไม่แสดงเป็นแท็บใช้งาน
- ตัดเมธอดหน้าจอ Spare Part Lifecycle, Drawing, Stock, Issue/Return เดิมจาก main.py
- SQLite เดิมไม่ถูกสั่ง DROP เพื่อป้องกันการทำลายข้อมูล Production โดยไม่ทราบตำแหน่งฐานข้อมูลจริง
- ข้อจำกัด: ไม่ได้ทดสอบ GUI/Edge/QAC จริง (ไม่มี PySide6 และ QAC Server)
- Sample Mapping ยังต้องทดสอบการจับคู่ Machine/Station/Diameter บนเอกสารจริง; อย่าใช้เขียน QAC Production ก่อนทดสอบ
