# P11.65 – Sample Register Resizable Workspace (offline patch)

- Sample Register: แยกพื้นที่ด้านล่างเป็น 4 Pane ปรับความสูงโดยลากเส้นแบ่งระหว่าง CSV Row, Prepared List, Prepared QAC Values, Execution Log
- เอา max height ของตาราง Sample และ Log ออก; คอลัมน์ยังลากปรับความกว้างและเลื่อนแนวนอนได้
- ไม่แก้พฤติกรรม Daily Document
- Partial Slot: การถามผู้ใช้เพื่อเลือก Resume Slot เดิมโดยยืนยันเจ้าของ 2D ยังไม่เสร็จสมบูรณ์ในแพตช์ UI นี้ การข้ามไป Slot ใหม่ต้องยืนยันจากผู้ใช้งานก่อน ไม่อ้างว่า Resume อัตโนมัติได้
- Tested: 285 unit tests + 32 subtests, compileall. ยังไม่ได้ตรวจหน้าจอด้วย PySide6 และไม่ได้เชื่อม Live QAC
