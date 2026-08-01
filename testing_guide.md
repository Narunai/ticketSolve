# 🧪 คู่มือการทดสอบระบบ (Testing Guide)

เอกสารฉบับนี้อธิบายโครงสร้างชุดทดสอบ (Test Suite) และขั้นตอนการรันการทดสอบสำหรับระบบ **TicketSolve**

**อัปเดตล่าสุด**: 2 สิงหาคม 2026

---

## 📌 1. ภาพรวมชุดทดสอบ (Test Suite Overview)

ชุดทดสอบอยู่ใน `tickets/tests.py` ปัจจุบันมี test methods 79 รายการ ครอบคลุม:

1. **Multi-Tenant Data Isolation**: ตรวจสอบว่าพนักงาน/ผู้บริหารแต่ละบริษัทเห็นเฉพาะ Ticket ในบริษัทตนเองเท่านั้น
2. **Role-Based Access Control (RBAC)**: ตรวจสอบสิทธิ์การเข้าถึง URL และการทำรายการของผู้ใช้ทั้ง 5 บทบาท
3. **Ticket Lifecycle & Custom Fields**: ทดสอบการสร้าง, แก้ไข, เปลี่ยนสถานะ, บันทึก Note, และการแสดงผล Custom Fields
4. **Ticket Status Automation**: ทดสอบการย้ายสถานะอัตโนมัติจาก Open ➔ In Progress เมื่อเวลาผ่านไปตามกำหนด
5. **Notification Config & Email Dispatch**: ทดสอบการสร้างจดหมายแจ้งเตือนและการบันทึก `EmailLog`
6. **Monthly PDF Report Generation & Schedule**: ทดสอบการออกรายงาน PDF และคำสั่งส่งรายงานประจำเดือน
7. **Backup System & Management Views**: ทดสอบ Full, 2-Hr Incremental และ 7-Day System Data (No Tickets), ตรวจเนื้อหา SQLite/manifest, throttling 7 วัน, การบันทึก `BackupLog`, การลบประวัติ Backup และการลบรายการ 0 MB ทั้งหมดอย่างปลอดภัย
8. **Authorization Regression**: ทดสอบ `CLIENT_USER` เห็นเฉพาะ Ticket ของตน, `CLIENT_STAFF` แก้ไข Ticket ใน tenant ได้, การป้องกัน superuser และการดาวน์โหลดไฟล์แนบแบบ authenticated
9. **Backup Security Regression**: ทดสอบ path traversal, incremental backup เมื่อ Ticket เก่ามี comment ใหม่ และการลบรายการ backup ที่ไม่มี archive
10. **Email → Ticket**: ทดสอบ SMTP feature scope, การสร้าง Ticket/ไฟล์แนบจาก IMAP, การติดชื่อผู้ส่งบน Ticket, log รายอีเมล Imported/Skipped/Failed, Message-ID deduplication, built-in/custom keywords, Sender → Assignee routing ข้ามบริษัทแบบเปลี่ยน tenant context พร้อม default fallback, สิทธิ์ Import Now, หน้า Email Timer, interval gating และ run log
11. **In-App Notifications**: ทดสอบกระดิ่งแจ้งเตือน, การเปิด Ticket/ทำเครื่องหมายอ่านแล้ว, Mark all read และป้องกันการอ่านแจ้งเตือนข้ามผู้ใช้หรือข้าม tenant

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

# รัน regression test สำหรับชื่อผู้ส่ง/log รายอีเมลและกระดิ่งแจ้งเตือน
python manage.py test tickets.tests.MultiTenantTicketTests.test_imported_email_sender_is_pinned_to_ticket_and_logged_per_message tickets.tests.MultiTenantTicketTests.test_notification_bell_is_private_and_marks_notifications_read
```

### 2.3 รันด้วย Pytest (ถ้าติดตั้งไว้)
```bash
pytest
```

---

## 📊 3. สรุปผลการทดสอบล่าสุด (Latest Test Results)

ผลที่ยืนยันล่าสุดวันที่ 2 สิงหาคม 2026:

```text
Found 79 test(s).
Ran 79 tests in 124.071s
OK
System check identified no issues (0 silenced).
```

* **Discovered test methods**: 79
* **Full suite**: ผ่านครบ 79/79 บน development environment
