# 🧪 คู่มือการทดสอบระบบ (Testing Guide)

เอกสารฉบับนี้อธิบายโครงสร้างชุดทดสอบ (Test Suite) และขั้นตอนการรันการทดสอบสำหรับระบบ **TicketSolve**

---

## 📌 1. ภาพรวมชุดทดสอบ (Test Suite Overview)

ชุดทดสอบใน `tickets/tests.py` และ `tickets/test_demo.py` ครอบคลุมการทำงานทั้ง 59 รายการ:

1. **Multi-Tenant Data Isolation**: ตรวจสอบว่าพนักงาน/ผู้บริหารแต่ละบริษัทเห็นเฉพาะ Ticket ในบริษัทตนเองเท่านั้น
2. **Role-Based Access Control (RBAC)**: ตรวจสอบสิทธิ์การเข้าถึง URL และการทำรายการของผู้ใช้ทั้ง 5 บทบาท
3. **Ticket Lifecycle & Custom Fields**: ทดสอบการสร้าง, แก้ไข, เปลี่ยนสถานะ, บันทึก Note, และการแสดงผล Custom Fields
4. **Ticket Status Automation**: ทดสอบการย้ายสถานะอัตโนมัติจาก Open ➔ In Progress เมื่อเวลาผ่านไปตามกำหนด
5. **Notification Config & Email Dispatch**: ทดสอบการสร้างจดหมายแจ้งเตือนและการบันทึก `EmailLog`
6. **Monthly PDF Report Generation & Schedule**: ทดสอบการออกรายงาน PDF และคำสั่งส่งรายงานประจำเดือน
7. **Backup System & Management Views**: ทดสอบคำสั่ง Backup (Full & 2-Hr Incremental), การบันทึก `BackupLog`, และการลบประวัติ Backup

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
```

### 2.3 รันด้วย Pytest (ถ้าติดตั้งไว้)
```bash
pytest
```

---

## 📊 3. สรุปผลการทดสอบล่าสุด (Latest Test Results)

```text
Creating test database for alias 'default'...
Ran 59 tests in 85.675s

OK
Destroying test database for alias 'default'...
System check identified no issues (0 silenced).
```
* **Total Tests**: 59
* **Status**: PASSED (100%)
