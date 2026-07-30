# 🎟️ TicketSolve - Multi-Tenant IT Support Ticket & Service Desk System

**TicketSolve** คือระบบบริหารจัดการตั๋วแจ้งซ่อมและสนับสนุนงานบริการ IT (IT Service Desk & Support Ticket Management System) ในรูปแบบ Multi-Tenant รองรับการทำงานหลายบริษัทในระบบเดียว มีระบบสิทธิ์การใช้งาน 5 ระดับ, ระบบปรับแต่งฟิลด์และหน้าตาตามบริษัท, ระบบแจ้งเตือนทางอีเมลพร้อมสถิติการส่ง, ระบบย้ายสถานะอัตโนมัติ (Status Automation), ระบบรายงานประจำเดือน PDF, และระบบสำรองข้อมูลอัตโนมัติ 2 ชั่วโมง (2-Hour Incremental Backup & Cloud Sync)

---

## 🏗️ 1. เทคโนโลยีและสถาปัตยกรรมระบบ (Tech Stack & Architecture)

* **Backend**: Python 3.12+, Django 5.x
* **Database**: PostgreSQL (Production) / SQLite3 (Development)
* **Frontend**: HTML5, Vanilla CSS + Tailwind CSS (Glassmorphism Dark & Light Theme UI)
* **Web Server & WSGI**: Nginx + Gunicorn
* **PDF Engine**: xhtml2pdf (HTML/CSS to PDF Engine)
* **Background Scheduler**: Systemd Service & Timer (`ticketsolve-scheduler`)
* **Cloud Storage & Backup**: Google Drive API v3 (Service Account / OAuth2)

---

## 🗄️ 2. โครงสร้างข้อมูลและ Data Models (Core Models)

| Model Name | Description / Details |
| :--- | :--- |
| **`Company`** | องค์กร/บริษัทลูกค้า รองรับโครงสร้างแม่-ลูก (Subsidiary companies) |
| **`CustomUser`** | ผู้ใช้งานระบบ ขยายจาก AbstractUser เพิ่ม `role` (5 ระดับ) และผูกกับ `Company` |
| **`Ticket`** | ตั๋วแจ้งซ่อม เก็บหัวข้อ, รายละเอียด, สถานะ, ความสำคัญ, หมวดหมู่, ผู้สร้าง, ผู้รับผิดชอบ, `custom_fields_data` (JSON), `status_changed_at` |
| **`CompanyTicketConfig`** | การตั้งค่า prefix ของ Ticket, ข้อความช่วยเหลือ, และการบังคับกรอก Resolution Note |
| **`CompanyTicketField`** | ฟิลด์แบบกำหนดเอง (Custom Fields) ตามบริษัท (Text, Textarea, Number, Select, Date, Checkbox) |
| **`NotificationConfig`** | การตั้งค่าการส่งแจ้งเตือนอีเมลตามอีเวนต์และบทบาทผู้รับ |
| **`TicketAutomationConfig`** | การตั้งค่าระยะเวลาย้ายสถานะ Ticket จาก Open ➔ In Progress อัตโนมัติ |
| **`MonthlyReportSchedule`** | การตั้งค่าการส่งรายงานสรุป Ticket ประจำเดือนแบบ PDF |
| **`SMTPConfiguration`** | ตั้งค่าการเชื่อมต่อเมลเซิร์ฟเวอร์ SMTP |
| **`EmailLog`** | บันทึกประวัติการส่งอีเมล, ผู้รับ To/CC, สถานะ, เหตุผลข้อผิดพลาด, ปุ่ม Resend |
| **`BackupLog`** | บันทึกประวัติการสำรองข้อมูล (FULL / INCREMENTAL 2-HR), ขนาดไฟล์, สถานะ |
| **`TicketAuditLog`** | บันทึกการเปลี่ยนแปลงสถานะและผู้ดำเนินการสำหรับตรวจสอบย้อนหลัง |

---

## 👥 3. บทบาทผู้ใช้งาน (User Roles & Permissions)

1. **`SYSTEM_ADMIN` (ผู้ดูแลระบบสูงสุด)**: สิทธิ์เต็มรูปแบบ เข้าถึงทุกบริษัท, จัดการผู้ใช้, จัดการ SMTP, จัดการ Backup, และลบ Ticket
2. **`SYSTEM_SUB_ADMIN` (ผู้ช่วยผู้ดูแลระบบ)**: สิทธิ์เทียบเท่า System Admin ยกเว้นการจัดการ SMTP หรือการลบข้อมูลสำคัญบางส่วน
3. **`CLIENT_ADMIN` (ผู้ดูแลระบบระดับบริษัท)**: สิทธิ์จัดการผู้ใช้ในบริษัทตนเอง, ตั้งค่าฟิลด์ Ticket, ตั้งค่าการแจ้งเตือน, และออกรายงานประจำเดือน
4. **`CLIENT_STAFF` (เจ้าหน้าที่ไอทีประจำบริษัท)**: รับผิดชอบการแก้ไข Ticket, เปลี่ยนสถานะ, ตอบกลับความคิดเห็น, และปิดงาน
5. **`CLIENT_USER` (พนักงานทั่วไป)**: แจ้ง Ticket ใหม่, ติดตามสถานะ Ticket ของตนเอง, และเพิ่มความคิดเห็น

---

## ⚡ 4. ระบบเบื้องหลังอัตโนมัติ (Background Services & Schedulers)

ระบบทำงานอัตโนมัติผ่าน Systemd Timer (`ticketsolve-scheduler.timer`) รันทุกๆ 1 นาที:

```bash
# คำสั่งที่รันอัตโนมัติใน scheduler service:
python manage.py process_report_schedules   # ตรวจสอบและส่งรายงาน PDF ประจำเดือน
python manage.py process_ticket_automations # ย้ายสถานะ Ticket Open ➔ In Progress ตามเวลาที่ตั้งไว้
python manage.py run_2hr_backup             # สั่งทำ Backup 2 ชั่วโมงย้อนหลัง (มี Throttling ป้องกันรันซ้ำ)
```

---

## 💻 5. การติดตั้งและรันในเครื่องพัฒนา (Local Development)

```bash
# 1. Clone repository & ติดตั้ง dependencies
git clone https://github.com/Narunai/ticketSolve.git
cd ticketSolve
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# 2. Run migrations
python manage.py makemigrations
python manage.py migrate

# 3. Seed data (สร้างผู้ใช้และข้อมูลตัวอย่าง)
python manage.py seed_data

# 4. Start local dev server
python manage.py runserver 0.0.0.0:8000

# 5. Run test suite
python manage.py test
```
