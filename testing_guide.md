# 🧪 คู่มือการทดสอบระบบ (Testing Guide)

เอกสารฉบับนี้อธิบายโครงสร้างชุดทดสอบ (Test Suite) และขั้นตอนการรันการทดสอบสำหรับระบบ **TicketSolve**

**อัปเดตล่าสุด**: 31 กรกฎาคม 2026

---

## 📌 1. ภาพรวมชุดทดสอบ (Test Suite Overview)

ชุดทดสอบอยู่ใน `tickets/tests.py` ปัจจุบันมี test methods 72 รายการ ครอบคลุม:

1. **Multi-Tenant Data Isolation**: ตรวจสอบว่าพนักงาน/ผู้บริหารแต่ละบริษัทเห็นเฉพาะ Ticket ในบริษัทตนเองเท่านั้น
2. **Role-Based Access Control (RBAC)**: ตรวจสอบสิทธิ์การเข้าถึง URL และการทำรายการของผู้ใช้ทั้ง 5 บทบาท
3. **Ticket Lifecycle & Custom Fields**: ทดสอบการสร้าง, แก้ไข, เปลี่ยนสถานะ, บันทึก Note, และการแสดงผล Custom Fields
4. **Ticket Status Automation**: ทดสอบการย้ายสถานะอัตโนมัติจาก Open ➔ In Progress เมื่อเวลาผ่านไปตามกำหนด
5. **Notification Config & Email Dispatch**: ทดสอบการสร้างจดหมายแจ้งเตือนและการบันทึก `EmailLog`
6. **Monthly PDF Report Generation & Schedule**: ทดสอบการออกรายงาน PDF และคำสั่งส่งรายงานประจำเดือน
7. **Backup System & Management Views**: ทดสอบคำสั่ง Backup (Full & 2-Hr Incremental), การบันทึก `BackupLog`, และการลบประวัติ Backup
8. **Authorization Regression**: ทดสอบ `CLIENT_USER` เห็นเฉพาะ Ticket ของตน, `CLIENT_STAFF` แก้ไข Ticket ใน tenant ได้, การป้องกัน superuser และการดาวน์โหลดไฟล์แนบแบบ authenticated
9. **Backup Security Regression**: ทดสอบ path traversal, incremental backup เมื่อ Ticket เก่ามี comment ใหม่ และการลบรายการ backup ที่ไม่มี archive
10. **Email → Ticket**: ทดสอบ SMTP feature scope, การสร้าง Ticket/ไฟล์แนบจาก IMAP, Message-ID deduplication และสิทธิ์ Import Now

---

## ⚡ 2. คำสั่งรันการทดสอบ (Executing Tests)

### 2.1 รันชุดทดสอบทั้งหมด (Django Test Suite)
```bash
python manage.py test
```

### 2.2 รันเฉพาะคลาสทดสอบหรือฟังก์ชันทดสอบ
```bash
# รันเฉพาะคลาส MultiTenantTicketTests
python manage.py test tickets.tests.MultiTenantTicketTests

# รันเฉพาะฟังก์ชันทดสอบระบบ Backup
python manage.py test tickets.tests.MultiTenantTicketTests.test_backup_management_views_and_service

# รัน regression test สำหรับรายการ Backup ที่ไม่มีข้อมูล
python manage.py test tickets.tests.MultiTenantTicketTests.test_empty_backup_record_has_delete_button_and_can_be_deleted

# รัน regression test สำหรับ Email → Ticket
python manage.py test tickets.tests.MultiTenantTicketTests.test_email_to_ticket_import_creates_ticket_and_prevents_duplicate
```

### 2.3 รันด้วย Pytest (ถ้าติดตั้งไว้)
```bash
pytest
```

---

## 📊 3. สรุปผลการทดสอบล่าสุด (Latest Test Results)

ผลที่ยืนยันระหว่างการ deploy วันที่ 31 กรกฎาคม 2026:

```text
Found 1 test(s).
test_empty_backup_record_has_delete_button_and_can_be_deleted ... ok
Ran 1 test in 3.653s
OK
System check identified no issues (0 silenced).
```

* **Discovered test methods**: 72
* **ยืนยันแล้วบน AWS**: regression test สำหรับลบ backup ว่างผ่าน
* **Full suite**: ต้องใช้ผลจากคำสั่ง `python manage.py test` ล่าสุดเป็นเกณฑ์ก่อน release; ไม่ควรสรุปว่า test methods ทั้งหมดผ่านจากผล targeted test ข้างต้น
