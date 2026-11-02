# P11.68 — Sample Numeric Result Equivalence

- แก้การ Resume Sample เมื่อ QAC แสดงค่าเลขทศนิยมที่มีศูนย์ท้าย เช่น `21.60` แต่ CSV ให้ `21.6` ให้ถือเป็นค่าเลขเดียวกันและ SKIP ผลเดิม
- ใช้ Decimal เทียบค่าแบบแม่นยำ เฉพาะ QAC field ที่ `data-type=2` (numeric) และไม่ใช่ input_format ปุ่ม Sample Type/OK-NG
- ห้าม normalize ช่องข้อความ เช่น Electrode No., Serial, Time เพื่อคงตัวตนของรหัสรวมถึง leading zero
- ถ้า QAC มีค่าต่างจริง หรือค่าไม่ใช่ตัวเลขชัดเจน ให้ STOP ไม่เขียนทับ
- ไม่เปลี่ยนขั้นตอน Save: ต้องตอบ QAC Confirm + Complete! ตาม P11.67; ไม่กลับไปอ่าน Result หลัง Save

Offline tests: `python -m pytest -q` = 296 passed, 32 subtests passed. ยังไม่ได้ทดสอบกับ QAC จริง
