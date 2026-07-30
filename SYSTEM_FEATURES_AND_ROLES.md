# 🛠️ คู่มือฟีเจอร์และบทบาทผู้ใช้ (System Features & Roles Guide)

เอกสารฉบับนี้อธิบายฟีเจอร์การทำงานทั้งหมดของระบบ **TicketSolve** รวมถึงโครงสร้างสิทธิ์การใช้งานของแต่ละบทบาทผู้ใช้

---

## 📋 1. ฟีเจอร์หลักของระบบ (Core Features)

### 🎫 1.1 การบริหารจัดการ Ticket (Ticket Lifecycle Management)
* **Ticket Creation**: กรอกข้อมูลหัวข้อ, รายละเอียด, ความสำคัญ (Low, Medium, High, Urgent), หมวดหมู่ปัญหา, และอัปโหลดไฟล์แนบ
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
* **Multi-SMTP Support**: สามารถตั้งค่าการเชื่อมต่อ SMTP Server ได้หลายตัว และเลือกเปิดใช้งาน (Active) ตัวหลักได้
* **Email Delivery Logs & Resend**:
  * บันทึกประวัติการส่งอีเมลทุกฉบับ (To, CC, Subject, Event Type, Timestamp, Status)
  * หากส่งไม่สำเร็จ สามารถกดปุ่ม **🔄 Resend** เพื่อส่งใหม่อีกครั้งได้จากหน้า Log

---

### 📊 1.5 ระบบรายงานประจำเดือน PDF (Monthly PDF Reports)
* **PDF Generation**: ออกรายงานสรุปสถิติ Ticket ประจำเดือนในรูปแบบ PDF สวยงาม (ภาพรวม Ticket, อัตราการแก้ไขสำเร็จ, กราฟสถิติ, และตารางสรุป)
* **Automated Monthly Schedule**: ตั้งเวลาส่งรายงานสรุปเข้าอีเมลผู้บริหาร/ผู้ดูแลระบบอัตโนมัติในวันและเวลาที่กำหนด

---

### 💾 1.6 ระบบสำรองข้อมูล (Backup System & Cloud Sync)
* **2-Hour Incremental Backup**: บันทึกเฉพาะ Ticket, Comments และไฟล์แนบที่เกิดขึ้นใหม่ใน 2 ชั่วโมงย้อนหลัง บีบอัดเป็น `.zip` แล้วส่งขึ้น Google Drive
* **Full Backup**: บีบอัดฐานข้อมูล `db.sqlite3` + โฟลเดอร์ `media/` + `.env` เป็น `.tar.gz` แล้วส่งขึ้น Cloud
* **Backup Management UI (`/backups/`)**: หน้าจอสำหรับกดสำรองข้อมูลทันที, ดูสถิติการสำรองข้อมูล, และลบประวัติ Backup

---

## 🔐 2. ตารางสิทธิ์การใช้งานตามบทบาท (Permissions Matrix)

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
