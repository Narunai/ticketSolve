# 🛠️ คู่มือฟีเจอร์และบทบาทผู้ใช้ (System Features & Roles Guide)

เอกสารฉบับนี้อธิบายฟีเจอร์การทำงานทั้งหมดของระบบ **TicketSolve** รวมถึงโครงสร้างสิทธิ์การใช้งานของแต่ละบทบาทผู้ใช้

**อัปเดตล่าสุด**: 2 สิงหาคม 2026

---

## 📋 1. ฟีเจอร์หลักของระบบ (Core Features)

### 🎫 1.1 การบริหารจัดการ Ticket (Ticket Lifecycle Management)
* **Ticket Creation**: กรอกข้อมูลหัวข้อ, รายละเอียด, ความสำคัญ (Low, Medium, High, Urgent), หมวดหมู่ปัญหา, และอัปโหลดไฟล์แนบ
* **Protected Attachments**: ดาวน์โหลดไฟล์แนบได้หลัง login และผ่านการตรวจสิทธิ์ Ticket เท่านั้น; URL `/media/` โดยตรงไม่เปิดให้เข้าถึง
* **Upload Limits**: สูงสุด 10 MB ต่อไฟล์, 10 ไฟล์ต่อ request และรวมไม่เกิน 50 MB
* **Custom Fields**: รองรับฟิลด์ข้อมูลเพิ่มเติมตามบริษัท ( Text, Textarea, Number, Select, Date, Checkbox)
* **Ticket Prefix & Code**: สร้างรหัส Ticket อัตโนมัติ เช่น `ACME-0001`, `SEC-0002` ตาม Prefix ของแต่ละบริษัท
* **Ticket Status Workflow**:
  * `Open` ➔ `In Progress` ➔ `Pending User` ➔ `Resolved` ➔ `Closed`
* **Resolution Notes**: บังคับกรอกบันทึกการแก้ไขปัญหาก่อนปิด Ticket (สามารถตั้งค่าเปิด/ปิดได้ใน Company Configuration)
* **Confirmation Modal on Deployment**: เมื่อปิดงานแล้ว พนักงานสามารถกดปุ่มยืนยันการติดตั้ง/แก้ไขสำเร็จได้

---

### 🎨 1.2 การออกแบบหน้าตา Ticket ตามบริษัท (Company Ticket Customization)
* **Custom Ticket Prefix**: ตั้งค่า Prefix ประจำบริษัท
* **Help Guidelines Header**: ตั้งค่าข้อความช่วยเหลือและคำแนะนำสำหรับการกรอก Ticket
* **Custom Fields Builder**: สร้าง, แก้ไข, ลบ, และจัดลำดับฟิลด์ข้อมูลเพิ่มเติมตามความต้องการของแต่ละบริษัท
* **Allow/Disallow Attachments**: เลือกเปิดหรือปิดการแนบไฟล์สำหรับบริษัทนั้นๆ

---

### ⏱️ 1.3 ระบบย้ายสถานะอัตโนมัติ (Ticket Status Automations)
* **Automated Clock**: เมื่อ Ticket อยู่ในสถานะ `Open` เป็นเวลานานเกินที่กำหนด (เช่น 15 นาที หรือ 2 ชั่วโมง) ระบบจะย้ายสถานะเป็น `In Progress` ให้อัตโนมัติ
* **Company Override**: สามารถตั้งค่ากำหนดระยะเวลาแยกตามบริษัทได้ หรือส่งต่อไปยังบริษัทลูก (Subsidiary companies)
* **Reset Status Clock**: เมื่อมีการเปลี่ยนสถานะด้วยมือ ตัวนับเวลา `status_changed_at` จะถูกรีเซ็ตใหม่ทันที

---

### 📧 1.4 ระบบแจ้งเตือนทางอีเมลและการตั้งค่า SMTP (Email Notifications & Log)
* **Event Notifications**: แจ้งเตือนเมื่อมีการสร้าง Ticket ใหม่, อัปเดตสถานะ, หรือเพิ่มความคิดเห็น
* **Formal Email Template**: อีเมลผู้ใช้ทุกประเภทมีทั้ง HTML และ plain text ใช้โครงสร้างหัวเรื่อง ตารางรายละเอียด ปุ่มไปยัง production และข้อความรักษาความลับที่สม่ำเสมอ โดยไม่พึ่ง emoji/ไอคอนตกแต่ง
* **Multi-SMTP Support**: สามารถตั้งค่าการเชื่อมต่อ SMTP Server ได้หลายตัว และเลือกเปิดใช้งาน (Active) ตัวหลักได้
* **Email Delivery Logs & Resend**:
  * บันทึกประวัติการส่งอีเมลทุกฉบับ (To, CC, Subject, Event Type, Timestamp, Status)
  * หากส่งไม่สำเร็จ สามารถกดปุ่ม **🔄 Resend** เพื่อส่งใหม่อีกครั้งได้จากหน้า Log
* **Feature Scope**: บัญชีแต่ละรายการเลือกใช้สำหรับส่งอีเมล, Email → Ticket หรือทั้งสองฟังก์ชันได้

### 📥 1.5 Email → Ticket
* อ่านอีเมลที่ยังไม่อ่านผ่าน IMAP SSL แล้วสร้าง Ticket ใน company ที่กำหนด
* เลือก ticket creator/default assignee และกรอง subject ด้วย keyword ไทย/อังกฤษ
* ป้องกันการสร้างซ้ำด้วย Message-ID และมี import receipts สำหรับ Imported/Skipped/Failed
* แสดงชื่อ/อีเมลผู้ส่งจริงบน Ticket และมีตาราง receipt รายอีเมล 100 รายการล่าสุดพร้อมเหตุผลที่นำเข้าหรือคัดออก
* Email import details และ Execution logs อยู่ในการ์ดเดียวกันและเลือกดูผ่านแท็บที่รองรับคีย์บอร์ด
* รองรับไฟล์แนบภายใต้ขีดจำกัด 10 MB ต่อไฟล์, 10 ไฟล์ และรวม 50 MB
* หน้า Email Timer แยกสำหรับเปิด/ปิดและเลือกรอบ 10, 20, 30 นาที (ครึ่งชั่วโมง) หรือ 1 ชั่วโมง
* กด **Scan now** หรือ **Import Now** เพื่อสแกนทันที พร้อมเก็บ execution log ของทุกครั้งที่ทำงานจริง
* กำหนด Sender → Assignee routing ต่อ mailbox ได้ทุกบริษัท; Ticket จะอยู่ในบริษัทของผู้ดูแล และ fallback ไปค่า SMTP เมื่อไม่พบกฎ
* รองรับ Gmail และ Outlook ที่เปิด IMAP; Microsoft Graph/OAuth ยังไม่รวมใน integration นี้
* กระดิ่ง in-app แจ้ง Ticket ใหม่/เปลี่ยนสถานะ/ความคิดเห็นใหม่ พร้อมรายการส่วนตัวและ Mark all read
* หน้า Ticket แสดง username, อีเมล, บทบาทและบริษัทของ Reporter/Assignee โดยซ่อน metadata เทคนิคของ Email-to-Ticket จาก Custom Fields

---

### 📊 1.6 ระบบรายงานประจำเดือน PDF (Monthly PDF Reports)
* **PDF Generation**: ออกรายงาน PDF รูปแบบเอกสารผู้บริหาร พร้อมเลขอ้างอิง ขอบเขต/ช่วงเวลา ผู้จัดทำ Executive Summary, Status/Priority Breakdown, Ticket Register, หลักเกณฑ์คำนวณ และข้อความรักษาความลับ
* **Automated Monthly Schedule**: ตั้งเวลาส่งรายงานสรุปเข้าอีเมลผู้บริหาร/ผู้ดูแลระบบอัตโนมัติในวันและเวลาที่กำหนด

---

### 💾 1.7 ระบบสำรองข้อมูล (AWS VPS Backup)
* **Configurable Incremental Backup**: บันทึก Ticket ที่ถูกสร้าง/แก้ไข หรือมี Comments/ไฟล์แนบใหม่ตามช่วงที่ตั้ง (1, 2, 4, 6, 12 หรือ 24 ชั่วโมง; ค่าเริ่มต้น 2 ชั่วโมง) เป็น `.zip` ไว้ที่ `/var/backups/ticketsolve`
* **Full Backup**: ใช้ SQLite Online Backup API สำรองฐานข้อมูลและบีบอัดร่วมกับ `media/` เป็น `.tar.gz` บน AWS VPS โดยไม่รวม secrets
* **System Data (No Tickets)**: สำรองฐานข้อมูลส่วน Users, Companies, roles, SMTP/IMAP, routing, schedules, categories และค่าระบบตามรอบที่ตั้ง โดยล้าง Ticket/ข้อมูลลูกที่ cascade ออกจากสำเนา และไม่รวม `media/` หรือ runtime secrets
* **Backup Timer**: System Admin ตั้งรอบและเปิด/ปิด Incremental, Full และ System Data แยกกันได้จากหน้า Backup; จำกัด Incremental ขั้นต่ำ 1 ชั่วโมง และ Full/System Data ขั้นต่ำ 1 วัน พร้อม failure backoff 30 นาที ส่วน System Sub Admin ดูสถานะได้แต่แก้ timer ไม่ได้
* **Retention**: ลบ archive ที่เก่ากว่า `BACKUP_RETENTION_DAYS` ซึ่งมีค่าเริ่มต้น 30 วัน
* **Backup Management UI (`/backups/`)**: กดสำรองข้อมูล, ดาวน์โหลด archive, ดูสถิติ และลบทั้ง archive/log; รายการไม่มีข้อมูลหรือไฟล์หายมีปุ่ม **Delete empty record** และปุ่มรวม **Delete all 0 MB**
* **Access Control**: `SYSTEM_ADMIN`, `SYSTEM_SUB_ADMIN` และ Django superuser เข้าหน้า Backup ได้ แต่การแก้ Backup Timer จำกัดเฉพาะ `SYSTEM_ADMIN`/superuser และทุกการบันทึกใช้ `POST` + CSRF

---

## 🔐 2. ตารางสิทธิ์การใช้งานตามบทบาท (Permissions Matrix)

Sidebar แสดงชื่อผู้ใช้ บริษัท/ส่วนกลาง และบทบาทที่มีผลจริงแยกกัน โดย Django superuser จะแสดงเป็น **System Administrator** แม้ข้อมูลบัญชีรุ่นเก่าจะยังเก็บค่า role เป็น Client User

| ฟีเจอร์ / การกระทำ | SYSTEM_ADMIN | SYSTEM_SUB_ADMIN | CLIENT_ADMIN | CLIENT_STAFF | CLIENT_USER |
| :--- | :---: | :---: | :---: | :---: | :---: |
| สร้างและดู Ticket ของตนเอง | ✅ | ✅ | ✅ | ✅ | ✅ |
| ดู Ticket ทั้งหมดในบริษัทตนเอง | ✅ | ✅ | ✅ | ✅ | ❌ |
| ดู Ticket ทุกบริษัทในระบบ | ✅ | ✅ | ❌ | ❌ | ❌ |
| แก้ไข/เปลี่ยนสถานะ Ticket | ✅ | ✅ | ✅ | ✅ | ❌ |
| จัดการผู้ใช้งาน (Manage Users) | ✅ (ทุกบริษัท) | ✅ (ทุกบริษัท) | ✅ (เฉพาะบริษัทตนเอง) | ❌ | ❌ |
| จัดการบริษัท (Manage Companies) | ✅ | ✅ | ❌ | ❌ | ❌ |
| ปรับแต่ง Custom Fields ของบริษัท | ✅ | ✅ | ✅ | ❌ | ❌ |
| ตั้งค่าแจ้งเตือน Notification Email | ✅ | ✅ | ✅ | ❌ | ❌ |
| ตั้งค่าย้ายสถานะอัตโนมัติ (Automation) | ✅ | ✅ | ❌ | ❌ | ❌ |
| ตั้งค่าและลบข้อมูล Backup | ✅ | ✅ | ❌ | ❌ | ❌ |
| จัดการตั้งค่า SMTP Server | ✅ | ❌ | ❌ | ❌ | ❌ |
| ลบ Ticket ออกจากระบบ (Delete Ticket) | ✅ | ✅ | ❌ | ❌ | ❌ |

### หลักการสำคัญของสิทธิ์

* `CLIENT_USER` อ่านได้เฉพาะ Ticket ที่ตนสร้าง แม้อยู่บริษัทเดียวกัน และไม่สามารถแก้ไข/เปลี่ยนสถานะ Ticket
* `CLIENT_ADMIN` และ `CLIENT_STAFF` อ่านและจัดการ Ticket ภายใน company tree ของตน
* System roles อ่าน Ticket ได้ทุก tenant แต่บัญชีที่เป็น Django superuser จะแก้ไขได้เฉพาะ Django superuser ด้วยกัน
* การยืนยัน deployment เป็นคำสั่ง `POST` และจำกัดเฉพาะ Ticket Staff
# เอกสารประกอบความปลอดภัย

ภาพรวมระบบทั้งหมด, architecture/trust-boundary diagrams, มาตรฐานอ้างอิง, รายการแก้ไขและ residual risks อยู่ที่
[`SECURITY_AND_SYSTEM_ARCHITECTURE_REPORT.md`](SECURITY_AND_SYSTEM_ARCHITECTURE_REPORT.md)

## Simple Password (Admin-approved)

* System Admin อนุมัติ/ตั้ง Simple Password ให้บัญชีที่ไม่ใช่ Django superuser ได้ทุกบริษัท
* System Sub-Admin อนุมัติ/ตั้งให้บัญชี Client ได้ แต่แตะ System Admin/Sub-Admin ไม่ได้
* Client Admin อนุมัติ/ตั้งให้สมาชิกในบริษัทและบริษัทลูกตาม tenant scope
* เจ้าของบัญชีตั้งรหัสแบบจำง่ายของตนเองได้หลัง Admin อนุมัติแล้ว
* บัญชีที่ได้รับอนุมัติใช้รหัสอย่าง `123456` ได้ (อย่างน้อย 6 ตัวอักษร) และใช้ต่อเนื่องจนกว่าจะเปลี่ยนรหัสหรือผู้ดูแลยกเลิกสิทธิ์
* เจ้าของบัญชีหรือผู้ดูแลตามขอบเขตสามารถสร้างรหัสตัวเลข 6 หลักใหม่ ระบบแสดงค่าเพียง response เดียวและเก็บเฉพาะ Argon2 hash
* บัญชีประเภทนี้ถูก lock 10 นาทีหลังกรอกผิดครบ 5 ครั้ง; สำเร็จแล้วล้าง failed-attempt counter
* เมื่อยกเลิกสิทธิ์ Simple Password ผู้ดูแลต้องกำหนดรหัสมาตรฐานใหม่ในรายการเดียวกัน
* หน้า Manage Users แสดงเฉพาะสถานะ `Simple approved`/`Standard` ไม่แสดงรหัสเดิม เพราะรหัสเป็น one-way hash
