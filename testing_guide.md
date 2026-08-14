# 🧪 คู่มือการทดสอบระบบ (Testing Guide)

เอกสารฉบับนี้อธิบายโครงสร้างชุดทดสอบ (Test Suite) และขั้นตอนการรันการทดสอบสำหรับระบบ **TicketSolve**

**อัปเดตล่าสุด**: 14 สิงหาคม 2026

---

## 📌 1. ภาพรวมชุดทดสอบ (Test Suite Overview)

ชุดทดสอบ Django อยู่ใน `tickets/tests.py` และชุด FastAPI อยู่ใน `chatbot_service/test_gemini.py` ครอบคลุม:

1. **Multi-Tenant Data Isolation**: ตรวจสอบว่าพนักงาน/ผู้บริหารแต่ละบริษัทเห็นเฉพาะ Ticket ในบริษัทตนเองเท่านั้น
2. **Role-Based Access Control (RBAC)**: ตรวจสอบสิทธิ์การเข้าถึง URL และการทำรายการของผู้ใช้ทั้ง 5 บทบาท รวมถึงลำดับกลุ่มเมนู sidebar และการแสดงชื่อ/บริษัท/effective role ที่ถูกต้องแม้บัญชี superuser รุ่นเก่าจะมีค่า role ไม่ตรง
3. **Ticket Lifecycle & Custom Fields**: ทดสอบการสร้าง, แก้ไข, เปลี่ยนสถานะ, บันทึก Note, การแสดงผล Custom Fields และโครงสร้าง responsive ของหน้า Ticket Detail/ฟอร์มไฟล์แนบ
4. **Ticket Status Automation**: ทดสอบการย้ายสถานะอัตโนมัติจาก Open ➔ In Progress เมื่อเวลาผ่านไปตามกำหนด
5. **Notification Config & Email Dispatch**: ทดสอบการสร้างอีเมลทางการแบบ HTML + plain text, การส่งตามกฎแจ้งเตือน และการบันทึก `EmailLog`
6. **Monthly PDF Report Generation & Schedule**: ทดสอบ PDF รูปแบบเอกสารผู้บริหาร, การฝัง Sarabun และอ่านข้อความไทยจาก PDF จริง, เลขอ้างอิงรายงาน, ไฟล์แนบ, อีเมล HTML และคำสั่งส่งรายงานประจำเดือน
7. **Backup System & Management Views**: ทดสอบ Full, Incremental และ System Data (No Tickets), timer ที่กำหนดรอบ/เปิดปิดแยกกัน, interval allowlist, สิทธิ์แก้ไขเฉพาะ System Admin, failure backoff, manual override, เนื้อหา SQLite/manifest, `BackupLog` และการลบรายการ 0 MB อย่างปลอดภัย
8. **Authorization Regression**: ทดสอบ `CLIENT_USER` เห็นเฉพาะ Ticket ของตน, `CLIENT_STAFF` แก้ไข Ticket ใน tenant ได้, การป้องกัน superuser และการดาวน์โหลดไฟล์แนบแบบ authenticated
9. **Backup Security Regression**: ทดสอบ path traversal, incremental backup เมื่อ Ticket เก่ามี comment ใหม่ และการลบรายการ backup ที่ไม่มี archive
10. **Security Baseline Regression**: login throttling, POST-only logout, security audit, SMTP encryption at rest, file-signature validation, security headers และ open-redirect protection
11. **Simple Password**: approval scope, persistent password อย่าง `123456`, one-time display ของรหัสที่สุ่มใหม่, Argon2 storage, System Sub-Admin restrictions, tenant isolation, owner reset, การห้ามบัญชีที่ไม่ได้รับอนุมัติใช้รหัสง่าย และ lock 10 นาที
12. **Email → Ticket**: ทดสอบ Approval queue, Approve/Reject, การไม่สร้าง Ticket ก่อนอนุมัติ, การห้าม user/routing rule ข้าม Approval เมื่อ sender ยังไม่อนุมัติ, staged attachment authenticated download/cleanup, RBAC, contact directory, Message-ID deduplication, การค้นหา/กรอง sender routing ตามบริษัท, include/ignore keyword priority, skipped reason logging, timer gating และ run log ที่มี pending count
13. **In-App Notifications**: ทดสอบกระดิ่งแจ้งเตือน, การเปิด Ticket/ทำเครื่องหมายอ่านแล้ว, Mark all read และป้องกันการอ่านแจ้งเตือนข้ามผู้ใช้หรือข้าม tenant
14. **Chatbot Security**: ทดสอบ Django session/RBAC gateway, System Admin scope, same-origin mutation, API-key non-disclosure, per-user rate limit, payload/model allowlist, admin audit และ curated-document sandbox
15. **New Feature Regression**: ทดสอบว่า Address Book ไม่ข้าม Email Approval, recipient preview ไม่ enumerate ข้าม tenant, Client User inject arbitrary email ไม่ได้ และ override ถูก validate/ใช้ครั้งเดียว

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
python manage.py test tickets.tests.MultiTenantTicketTests.test_email_to_ticket_import_requires_approval_and_prevents_duplicate tickets.tests.MultiTenantTicketTests.test_pending_email_approval_rejection_and_attachment_rbac

# รัน regression test สำหรับชื่อผู้ส่ง/log รายอีเมลและกระดิ่งแจ้งเตือน
python manage.py test tickets.tests.MultiTenantTicketTests.test_imported_email_sender_is_pinned_to_ticket_and_logged_per_message tickets.tests.MultiTenantTicketTests.test_notification_bell_is_private_and_marks_notifications_read
```

### 2.3 รันด้วย Pytest (ถ้าติดตั้งไว้)
```bash
python -m pytest chatbot_service -q
```

---

## 📊 3. สรุปผลการทดสอบล่าสุด (Latest Test Results)

ผลที่ยืนยันล่าสุดวันที่ 14 สิงหาคม 2026:

```text
Found 108 test(s).
Ran 108 tests in 85.405s
OK
System check identified no issues (0 silenced).

Chatbot: 10 passed in 2.97s
Template script-tag check: PASS
pip-audit (main + chatbot): No known vulnerabilities found
```

* **Django suite**: ผ่านครบ 108/108 บน development environment (Django 5.2)
* **FastAPI chatbot suite**: ผ่านครบ 10/10
* **Deployment checks**: `check --deploy`, `makemigrations --check` และ template script-tag scan ผ่าน
* **Dependency audit**: `pip-audit` ของ requirements ทั้งสองชุดไม่พบ known vulnerabilities หลังอัปเดต `cryptography==50.0.0`
