# 🎟️ TicketSolve - Multi-Tenant IT Support Ticket & Service Desk System

**TicketSolve** คือระบบบริหารจัดการตั๋วแจ้งซ่อมและสนับสนุนงานบริการ IT (IT Service Desk & Support Ticket Management System) ในรูปแบบ Multi-Tenant รองรับการทำงานหลายบริษัทในระบบเดียว มีระบบสิทธิ์การใช้งาน 5 ระดับ, ระบบปรับแต่งฟิลด์และหน้าตาตามบริษัท, ระบบแจ้งเตือนทางอีเมลพร้อมสถิติการส่ง, ระบบนำอีเมลเข้าเป็น Ticket, ระบบย้ายสถานะอัตโนมัติ (Status Automation), ระบบรายงานประจำเดือน PDF, และระบบสำรองข้อมูลอัตโนมัติบน AWS VPS ทุก 2 ชั่วโมง

**อัปเดตล่าสุด**: 2 สิงหาคม 2026

> เอกสารภาพรวมสถาปัตยกรรม การควบคุมความปลอดภัย ผลการแก้ไข และแผนผังระบบ:
> [SECURITY_AND_SYSTEM_ARCHITECTURE_REPORT.md](SECURITY_AND_SYSTEM_ARCHITECTURE_REPORT.md)

---

## 🏗️ 1. เทคโนโลยีและสถาปัตยกรรมระบบ (Tech Stack & Architecture)

* **Backend**: Python 3.12+, Django 5.x
* **Database**: SQLite3 พร้อม SQLite Online Backup API
* **Frontend**: HTML5, Vanilla CSS + Tailwind CSS (Glassmorphism Dark & Light Theme UI)
* **Web Server & WSGI**: Nginx + Gunicorn
* **PDF Engine**: xhtml2pdf (HTML/CSS to PDF Engine)
* **Background Scheduler**: Systemd Service & Timer (`ticketsolve-scheduler`)
* **Backup Storage**: AWS VPS filesystem (`/var/backups/ticketsolve`)

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
| **`InboundEmailReceipt`** | เก็บอีเมลรออนุมัติ, เนื้อหาที่ sanitize แล้ว, Message-ID, ผู้อนุมัติ/ปฏิเสธ และผลการนำเข้า |
| **`InboundEmailAttachment`** | เก็บไฟล์แนบชั่วคราวแบบ private ระหว่างรออนุมัติ และลบเมื่ออนุมัติ/ปฏิเสธ |
| **`InboundEmailContact`** | สมุดรายชื่อผู้ส่งแยกตาม mailbox พร้อมชื่อ จำนวนข้อความ และเวลาที่พบล่าสุด |
| **`InboundEmailRoutingRule`** | จับคู่อีเมลผู้ส่งกับผู้ดูแล Ticket โดยแยกตาม mailbox |
| **`EmailToTicketSchedule`** | ตั้งค่าเปิด/ปิดและรอบสแกน Email → Ticket |
| **`EmailToTicketRunLog`** | สรุปผลการทำงานแต่ละรอบ พร้อมจำนวนรายการและระยะเวลา |
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

ขอบเขต Ticket ถูกบังคับใช้จากศูนย์กลาง:

* System Staff อ่านและจัดการ Ticket ได้ทุกบริษัท
* `CLIENT_ADMIN` และ `CLIENT_STAFF` อ่าน Ticket ในบริษัทของตนและบริษัทลูก พร้อมแก้ไขตามสิทธิ์
* `CLIENT_USER` อ่านได้เฉพาะ Ticket ที่ตนเป็นผู้สร้างและไม่มีสิทธิ์แก้ไข Ticket
* ผู้ดูแลระดับแอปที่ไม่ใช่ Django superuser ไม่สามารถเปิด แก้ไข หรือรีเซ็ตรหัสผ่านบัญชี superuser ได้

---

## ⚡ 4. ระบบเบื้องหลังอัตโนมัติ (Background Services & Schedulers)

งานรายงาน, Ticket automation และ backup ตรวจทุก 1 นาทีผ่าน
`ticketsolve-scheduler.timer` โดยรอบ Backup จริงกำหนดแยกจากหน้า **Backup System**
(Incremental 1 ชั่วโมง–1 วัน, Full/System Data 1–30 วัน และเปิด/ปิดแยกกันได้)
ส่วน Email → Ticket แยกเป็น
`ticketsolve-email-to-ticket.timer` ปลุกตัวประมวลผลทุก 10 นาที ส่วนรอบสแกนจริง
กำหนดจากหน้า **Email Timer** เป็น 10, 20, 30 นาที หรือ 1 ชั่วโมง:

```bash
# คำสั่งที่รันอัตโนมัติใน scheduler service:
python manage.py process_report_schedules   # ตรวจสอบและส่งรายงาน PDF ประจำเดือน
python manage.py process_ticket_automations # ย้ายสถานะ Ticket Open ➔ In Progress ตามเวลาที่ตั้งไว้
python manage.py run_2hr_backup             # Incremental ตามรอบที่ตั้ง (ค่าเริ่มต้น 2 ชั่วโมง)
python manage.py run_2hr_backup --full      # Full backup ตามรอบที่ตั้ง (ค่าเริ่มต้น 1 วัน)
python manage.py run_weekly_system_backup   # System Data ตามรอบที่ตั้ง (ค่าเริ่มต้น 7 วัน)

# Systemd เรียกทุก 10 นาทีและคำสั่งตรวจรอบเวลาจากฐานข้อมูล:
python manage.py process_email_to_tickets   # อ่าน IMAP และส่งอีเมลใหม่เข้าคิวอนุมัติก่อนสร้าง Ticket
```

Backup archive เก็บที่ `/var/backups/ticketsolve` บน AWS VPS และลบไฟล์ที่เก่ากว่า 30 วันโดยอัตโนมัติ ค่า production secrets เก็บแยกที่ `/etc/ticketsolve/ticketsolve.env` และไม่รวมอยู่ใน archive

---

## 🔐 5. Security Controls

* ไฟล์แนบดาวน์โหลดผ่าน Django view ที่ตรวจ login และขอบเขต Ticket เท่านั้น; Nginx ตอบ `404` สำหรับ `/media/` โดยตรง
* จำกัดไฟล์แนบสูงสุด 10 MB ต่อไฟล์, 10 ไฟล์ต่อ request และรวมไม่เกิน 50 MB
* Production เปิด HTTPS redirect, secure cookies, HSTS, `nosniff` และ referrer policy
* ล็อกอินถูกจำกัด 5 ครั้งต่อช่วง 15 นาทีทั้งระดับบัญชีและ IP พร้อม Security Audit Log; logout ใช้ POST + CSRF
* รหัสผ่านเว็บใช้ Argon2 เป็นค่าเริ่มต้น, กำหนดขั้นต่ำ 12 ตัวอักษร และ session หมดอายุภายใน 8 ชั่วโมง/เมื่อปิด browser
* Simple Password ใช้ได้เฉพาะบัญชีที่ System Admin/System Sub-Admin หรือ Client Admin ตามขอบเขตอนุมัติ ผู้ใช้จึงตั้งรหัสแบบจำง่ายอย่าง `123456` (อย่างน้อย 6 ตัวอักษร) และใช้ต่อเนื่องได้ โดยบัญชีประเภทนี้จะ lock 10 นาทีเมื่อกรอกผิดครบ 5 ครั้ง
* ไม่มีผู้ใช้หรือผู้ดูแลคนใดเปิดดูรหัสเดิมย้อนหลังได้ รหัสจริงยังคงเป็น Argon2 one-way hash; เจ้าของบัญชีและผู้ดูแลตามขอบเขตทำได้เฉพาะตั้งรหัสใหม่หรือสร้างรหัส Simple Password แบบตัวเลข 6 หลักซึ่งแสดงครั้งเดียว
* รหัสผ่าน SMTP/IMAP เข้ารหัสด้วย Fernet ในฐานข้อมูล โดย key แยกออกจาก Git และ backup
* ไฟล์แนบตรวจทั้ง allowlist, นามสกุล และ file signature รวมถึงจำกัด zip bomb/macro ในไฟล์ Office
* Dependency หลักตรึงเวอร์ชันและตรวจด้วย `pip-audit`; security headers และ login rate limit ถูกบังคับทั้ง Django/Nginx
* `SECRET_KEY`, allowed hosts, CSRF origins, SMTP credentials และตำแหน่ง backup กำหนดผ่าน environment file นอก Git checkout
* หน้า Backup Management แสดง Download เฉพาะ archive ที่มีข้อมูล; รายการขนาด 0 หรือไฟล์หายสามารถลบรายรายการด้วย **Delete empty record** หรือลบรายการ 0 MB ทั้งหมดด้วย **Delete all 0 MB**
* **System Data (No Tickets)** สร้างทุก 7 วัน: เก็บ Users, Companies, roles, SMTP/IMAP, routing, schedules, categories และค่าระบบใน SQLite ที่ล้าง Ticket ออกจากสำเนาแล้ว โดยไม่รวม `media/` และ runtime secrets; System Admin สามารถสั่งทันทีด้วยปุ่ม **Run Manually: System Data (No Tickets)** โดยไม่กระทบรอบอัตโนมัติ
* SMTP Configuration แยกขอบเขตการใช้งานเป็นส่งอีเมล, Email → Ticket หรือทั้งสองฟังก์ชัน โดยมี active configuration แยกตาม feature
* อีเมลแจ้งเตือนใช้แม่แบบทางการแบบ multipart (HTML + plain text) ร่วมกันทั้ง Ticket, Status, Deployment Approval, Comment, Account, Company และ Monthly Report พร้อมลิงก์ production ที่กำหนดผ่าน `PUBLIC_BASE_URL`
* Monthly PDF Report ใช้รูปแบบเอกสารผู้บริหาร มีเลขอ้างอิง ขอบเขตและช่วงเวลารายงาน Executive Summary, Status/Priority Breakdown, Ticket Register และข้อความกำกับความลับ โดยลดไอคอนและสีที่ไม่จำเป็น
* Monthly PDF ฝังฟอนต์ Sarabun Regular/Bold โดยบังคับใช้กับทุก element เพื่อรองรับชื่อบริษัท ชื่อผู้ส่ง หัวข้อและรายละเอียดภาษาไทยบน Windows/Linux

## 📥 Email → Ticket

* รองรับ Gmail/Google Workspace และ Outlook ที่เปิด IMAP SSL
* หน้า **Email Timer** แยกสำหรับเปิด/ปิดและเลือกรอบ 10, 20, 30 นาที (ครึ่งชั่วโมง) หรือ 1 ชั่วโมง
* กด **Scan now** หรือ **Import Now** เพื่อสแกนทันทีโดยไม่รอรอบ
* อีเมลที่ผ่านตัวกรองจะเข้า **Approval queue** ก่อนและยังไม่ปรากฏใน Dashboard/รายงาน ผู้มีสิทธิ์จึงกด Approve เพื่อสร้าง Ticket หรือ Reject พร้อมเหตุผลได้
* ไฟล์แนบระหว่างรอถูกเก็บใน private media และดาวน์โหลดผ่าน authenticated view เท่านั้น; เมื่ออนุมัติจะย้ายเข้า Ticket และเมื่อปฏิเสธจะลบออก
* เก็บ run log 50 รอบล่าสุด พร้อม trigger/ผู้สั่งรัน, สถานะ, จำนวน mailbox,
  found/pending/imported/skipped/duplicate/failed, ระยะเวลา และรายละเอียดข้อผิดพลาด
* เก็บ log รายอีเมล 100 รายการล่าสุด พร้อม mailbox, ชื่อ/อีเมลผู้ส่ง, subject, Message-ID, ผล Pending/Imported/Rejected/Skipped/Failed, Ticket ที่สร้าง และเหตุผล
* หน้า Email Timer รวม Approval queue, log รายอีเมล, execution log และสมุดรายชื่อผู้ส่งไว้ใน container เดียว โดยสลับดูผ่านแท็บและจำแท็บล่าสุดใน browser
* สมุดรายชื่อบันทึกชื่อและอีเมลผู้ส่งอัตโนมัติแยกตาม mailbox ค้นหาด้วยชื่อ/อีเมล/subject ได้ และ Message-ID ที่สแกนซ้ำไม่เพิ่มจำนวนข้อความ
* Ticket ที่สร้างจากอีเมลจะแสดงการ์ด **Email sender** แยกจาก internal creator เพื่อให้ติดตามผู้แจ้งตัวจริงได้
* Sender → Assignee routing กำหนดผู้ดูแลตามอีเมลผู้ส่งได้ทุกบริษัท โดย Ticket จะอยู่ในบริษัทของผู้ดูแลเพื่อรักษา tenant isolation; หากไม่มีกฎหรือผู้ดูแลในกฎไม่ active จะใช้ค่า Company/Creator/Default Assignee จาก SMTP
* Custom subject keywords เป็นคำเพิ่มเติมจากคำมาตรฐาน เช่น `ปัญหา` และ `issue` ไม่ได้แทนที่คำมาตรฐาน
* อ่านเฉพาะข้อความ `UNSEEN` ย้อนหลังตามจำนวนวันที่กำหนด และจำกัดจำนวนต่อรอบ
* กรอง subject ด้วย keyword ไทย/อังกฤษก่อนสร้าง Ticket ได้
* กำหนด target company, ticket creator และ default assignee ต่อ mailbox
* เก็บ Message-ID ป้องกัน import ซ้ำ และ mark as read หลังประมวลผลสำเร็จ/ข้ามแล้ว
* ไฟล์แนบใช้ข้อจำกัดเดียวกับหน้าเว็บ: 10 MB ต่อไฟล์, 10 ไฟล์ และรวม 50 MB
* ข้ามอีเมลระบบที่ขึ้นต้น `[TicketSolve]` เพื่อป้องกันวงจรส่งแล้วนำกลับเข้า และจำกัด raw email ที่ 55 MB/เนื้อหา 100,000 ตัวอักษร
* กระดิ่ง **In-App Notifications** แจ้ง Ticket ใหม่, การเปลี่ยนสถานะ และความคิดเห็นใหม่ ผู้ใช้เปิด Ticket หรือ Mark all read ได้ และเห็นเฉพาะแจ้งเตือนของบัญชีตนเอง
* Microsoft 365 ที่ปิด IMAP ต้องใช้ Graph/OAuth integration เพิ่มเติม; รุ่นนี้ยังไม่ใช้ Basic Auth เพื่อหลีกเลี่ยงการอ้างว่ารองรับบัญชีที่ปิด IMAP

---

## 💻 6. การติดตั้งและรันในเครื่องพัฒนา (Local Development)

```bash
# 1. Clone repository & ติดตั้ง dependencies
git clone https://github.com/Narunai/ticketSolve.git
cd ticketSolve
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# 2. Create local environment settings, then set DEBUG=True and a local SECRET_KEY
copy .env.example .env

# 3. Run migrations
python manage.py migrate

# 4. Seed data (สร้างผู้ใช้และข้อมูลตัวอย่าง)
python manage.py seed_data

# 5. Start local dev server
python manage.py runserver 0.0.0.0:8000

# 6. Run test suite
python manage.py test
```
