# P11.61 Sample Numeric Saved Result Row Fix

ฐาน: P11.60

ปัญหาที่พิสูจน์จากภาพ QAC: Item 389500 (Upper electrode Counter) Slot 1 = 1, Slot 2 = 564 เป็น Result สีเขียวที่บันทึกแล้ว ในขณะที่ Slot 3+ เป็น input ว่าง โค้ดเดิมอ่านเฉพาะ input ทำให้ Slot 2 หายจาก schema และแจ้งว่าไม่มี slot ที่ใช้งานได้

แก้ไข:
- อ่าน `tbody tr[data-result-no]` ของทุกชนิด Item เป็นหลัก ไม่ใช่เฉพาะ input ที่ยังแก้ได้
- แยกค่าที่บันทึกแล้วจากช่องแสดงผลในแถว และค่า input ที่ยังว่าง โดยคงเลข Slot จริง
- ช่อง Sample Type ใช้ text ของทั้ง Result Row เพื่อคงค่า Initial/Middle/Final
- เมื่อเขียนเลือก input ตาม `data-result-no` จริง ป้องกันเลือกตำแหน่งผิดเมื่อมีแถวบันทึกก่อนหน้า
- คงข้อห้ามเขียนทับข้อมูลต่างค่า / ห้าม Save ซ้ำเมื่อสถานะไม่แน่นอน

ผลทดสอบ offline: 276 tests + 32 subtests passed (PYTHONPATH=. pytest -q), compileall ผ่าน; ZIP integrity ผ่าน

ข้อจำกัด: ยังไม่ได้ทดสอบ QAC live; ต้องยืนยันกับ Server จริง โดยเลือก Resume Slot 2 ของ 2D เดิมและตรวจว่า Upper electrode Counter=564 ถูก SKIP จาก persisted result ก่อนกรอก Item ต่อไป
