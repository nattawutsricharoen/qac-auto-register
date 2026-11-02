# Electrode Issue & Return — P11.46

## ใช้งาน
1. เปิด QAC Auto Register > Electrode Control > Admin Settings และปลดล็อก PIN แบบ Local UI (ยังไม่ใช่ server-side authentication)
2. ตั้ง Electrode Code (ส่วนก่อนขีด เช่น `749C`), Target Shot และ Mapping Line/Machine/Station/Position (เพิ่มรายการต่อ Code ได้โดยใช้ Code เดิม)
3. หน้าเบิก/คืนสแกน Barcode BASE หรือ -R1 ถึง -R5 โดยไม่ต้องกรอก Employee ID
4. ระบบแสดง Machine Mapping ที่อนุญาตเท่านั้น; เมื่อเบิกต้องกดยืนยัน ISSUE
5. สแกน Barcode เดิมอีกครั้งขณะ ISSUED เพื่อคืน กรอก Used Shots ตาม Final Counter จริง; ต่ำกว่า Target ต้องมีเหตุผล; ถึง Target จะใช้ `Full counter`
6. ดูประวัติ และ Export CSV จากแท็บ 2

## ความปลอดภัย / ข้อจำกัดก่อนใช้หลายเครื่อง
- ข้อมูลอยู่ใน SQLite **เฉพาะเครื่อง**: `database/electrode_issue_return_local.sqlite3`
- `electrode_outbox` สร้าง Event ID ไม่ซ้ำ และเก็บ PENDING แต่ **ยังไม่มีตัวส่งไป LAN หรือ Central Sync Service**
- จึง **ห้ามใช้หลายเครื่องเบิก Barcode เดียวกันก่อนมี Central Service**: Local lock ป้องกันเฉพาะบนเครื่องเดียว
- ห้ามวาง/แชร์ SQLite active DB ไว้บน network SMB หรือใช้วิธีแทนที่ไฟล์ฐานข้อมูลรวมวันละครั้ง
- เพื่อใช้งานหลายเครื่อง ต้องทำ Central API แบบ single writer, idempotency, global active-barcode uniqueness และ acknowledgement; เมื่อ network unavailable ควรกำหนด conflict/safe mode ชัดเจน
- Admin PIN ในรุ่นนี้เป็นเพียง local UI gate ไม่ใช่การพิสูจน์สิทธิ์ server-side
- Sample Register เดิมยังใช้ ReplacementStore; **ยังไม่ได้เชื่อมข้อมูลจาก Ledger ใหม่เข้ากับ Sample Register** เพื่อเลี่ยงกระทบการลงทะเบียนเดิม
- การแก้ Target มีผลต่อ ISSUE ใหม่เท่านั้น และเก็บ target_shots_at_issue ในแต่ละรอบถาวร
- Barcode แต่ละ suffix เบิกได้รอบเดียว; R1–R5 ต้องมีประวัติคืน suffix ก่อนหน้า เพื่อรักษาลำดับการ Regrind

## Test
`python -m pytest -q`
Qt smoke test ต้องทดสอบบน Windows ที่ติดตั้ง PySide6; เครื่อง Build นี้ไม่มี PySide6/QAC LAN
