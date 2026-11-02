QAC Auto Register Desktop — Electrode Replacement Ledger Patch

- เพิ่ม 3 แท็บใต้ Electrode Control: Current / Change, History / Export, Master
- เก็บข้อมูลใน SQLite ไฟล์เดียวกับ config electrode_control.sqlite_path เดิม แต่เป็นตารางใหม่ replacement_* ไม่ลบ lifecycle เดิม
- มี 46 slots ตั้งต้น; Gas Filling 3 stations x 2 diameters x 4 positions
- Common เป็นคุณสมบัติใช้ได้ทั้ง Ø20/Ø25 ไม่ใช่การรวมประวัติข้ามเครื่อง
- Initial Install ใช้เมื่อตำแหน่งยังไม่มีของเดิม; Replace บังคับกรอก Old Final Counter และ New No. / Start Counter (default 0)
- Replace ใช้ Transaction เดียว, ตรวจ stale old no, Final >= Start, เก็บประวัติถาวร
- Export Excel มี Current และ History; CSV เป็น History
- Master Add, Enable/Disable, Required Toggle ผ่าน PIN 12338 (ยังควรย้าย PIN ไปเป็น hash ที่กำหนดได้)

ข้อจำกัดสำคัญ:
1) ยังไม่ได้รันทดสอบ GUI บน Windows/เครื่อง QAC จริง — สภาพแวดล้อมนี้ไม่มี PySide6
2) Sample Register ปัจจุบันอ่านฐานเดิม app/electrode_control.py ไม่ใช่ replacement_* — ยังไม่เชื่อมอัตโนมัติเข้า QAC Sample
3) ตาราง replacement_* ใช้แยกจาก spare-part lifecycle ปัจจุบัน ผู้ดูแลต้องตัดสินใจกฎ sync ก่อน Production
4) ข้อมูล Current Counter ระหว่างใช้งานยังไม่อัปเดตอัตโนมัติ; Final Counter บันทึกเมื่อเปลี่ยน
5) ขอให้ Backup SQLite ก่อนใช้งานจริง และทดลองบน DB สำเนาก่อน

ทดสอบจริงใน environment: python -m unittest discover -s tests -p test_electrode_replacement_ledger.py -v
