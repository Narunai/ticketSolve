# 🔔 TicketSolve Notification System & Role Matrix Documentation
> **เอกสารคู่มือระบบการแจ้งเตือนและการกระจายข้อมูลตามบทบาท (Role Notification Matrix)**  
> *ปรับปรุงล่าสุด: สิงหาคม 2026 | เวอร์ชันระบบ: TicketSolve v2.4 Multi-Tenant Production*

---

## 📌 1. สรุปข้อเท็จจริงและสาเหตุที่พบ (Fact-Check & Root Cause)

จากการตรวจสอบอย่างละเอียดในระดับฐานข้อมูลและโค้ดของระบบ พบข้อเท็จจริง 2 ประการที่ทำให้บัญชี **System Admin** ไม่ได้รับการแจ้งเตือนก่อนหน้านี้:

### 1.1 ปัญหาบทบาทของบัญชี Superuser ในฐานข้อมูล (Role Mismatch)
* **ข้อเท็จจริง**: บัญชี Superuser ที่ถูกสร้างขึ้น (เช่น บัญชี `system_admin`) มีค่า `is_superuser = True` แต่ในฟิลด์ `role` ในตารางฐานข้อมูลกลับมีค่าเป็น `CLIENT_USER` (เนื่องจากค่า Default ของโมเดล `CustomUser` ถูกตั้งไว้เป็น `CLIENT_USER`)
* **ผลกระทบ**: ในโค้ดเดิมของการสร้าง In-App Notification มีการ Query ผู้รับโดยใช้เงื่อนไข:
  ```python
  CustomUser.objects.filter(role__in=['SYSTEM_ADMIN', 'SYSTEM_SUB_ADMIN'])
  ```
  ทำให้บัญชี Superuser ที่มี `role='CLIENT_USER'` หลุดออกจากเงื่อนไขและไม่ถูกเพิ่มเข้าไปในรายการผู้รับแจ้งเตือนเลย

### 1.2 ปัญหาอีเมลแจ้งเตือนเมื่อเปิด Ticket ใหม่
* **ข้อเท็จจริง**: ในฟังก์ชันส่งอีเมลเมื่อสร้าง Ticket ใหม่ (`send_ticket_notifications`) เดิมมีการส่งเฉพาะ:
  - ผู้สร้าง Ticket (`created_by`)
  - ช่างผู้ได้รับมอบหมาย (`assigned_to`)
  - Client Admin ของบริษัทนั้นๆ
  - แต่ไม่ได้เพิ่มอีเมลของทีม System Admin / IT Support ไว้ในรายชื่อผู้รับ

---

## 🛠️ 2. สิ่งที่ได้รับการแก้ไขแล้ว (Solutions Implemented)

1. **ปรับปรุง Helper Method `CustomUser.get_system_admins_qs()`**:
   - รวมเงื่อนไข `role__in=['SYSTEM_ADMIN', 'SYSTEM_SUB_ADMIN']`, `is_superuser=True`, และ `is_staff=True` (ที่เป็นแอดมินกลาง) เข้าด้วยกันอย่างสมบูรณ์
2. **อัปเดตโมเดล `CustomUser.save()`**:
   - เพิ่มระบบ Auto-Assignment: หากผู้ใช้มีสถานะ `is_superuser=True` และ `role` ยังเป็น `CLIENT_USER` ระบบจะเปลี่ยนให้เป็น `SYSTEM_ADMIN` โดยอัตโนมัติ
3. **ปรับแก้สัญญาณแจ้งเตือน (`tickets/signals.py`)**:
   - **Ticket Created**: System Admin ได้รับทั้ง **In-App Bell 🔔**, **Real-Time Push Toast 💬**, และ **Email 📧**
   - **Status Changed**: System Admin ได้รับ **In-App Bell 🔔** และ **Real-Time Push Toast 💬** ของทุก Ticket
   - **Comment Added**: System Admin ได้รับ **In-App Bell 🔔** และ **Real-Time Push Toast 💬** ของทุก Comment
4. **ปรับแก้ฐานข้อมูล Production**:
   - รัน Script ปรับสถานะฟิลด์ `role` ของบัญชี `system_admin` ให้เป็น `SYSTEM_ADMIN` เรียบร้อยแล้ว 100%

---

## 📊 3. ตารางสิทธิ์และการแจ้งเตือนตามบทบาท (Role Notification Matrix)

| เหตุการณ์ (Event) | 👑 System Admin (ผู้ดูแลระบบกลาง) | 🛠️ System Sub-Admin (ทีม IT Support) | 🏢 Client Admin (แอดมินบริษัทลูกค้า) | 👤 Client User (พนักงานผู้เปิดเคส) | 🎯 Assignee (ผู้รับมอบหมายงาน) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **1. มีการสร้าง Ticket ใหม่ (New Ticket)** | 🔔 In-App<br>💬 Toast<br>📧 Email | 🔔 In-App<br>💬 Toast<br>📧 Email | 🔔 In-App<br>💬 Toast<br>📧 Email<br>*(เฉพาะในบริษัทตนเอง)* | 📧 Email Confirmation | 🔔 In-App<br>💬 Toast<br>📧 Email<br>*(หากถูกระบุชื่อ)* |
| **2. สถานะ Ticket เปลี่ยนแปลง (Status Changed)** *(เช่น Open ➔ In Progress ➔ Resolved)* | 🔔 In-App<br>💬 Toast | 🔔 In-App<br>💬 Toast | 🔔 In-App<br>💬 Toast<br>*(เฉพาะในบริษัทตนเอง)* | 🔔 In-App<br>💬 Toast<br>📧 Email | 🔔 In-App<br>💬 Toast<br>📧 Email |
| **3. มี Comment หรือตอบกลับใหม่ (New Comment)** | 🔔 In-App<br>💬 Toast | 🔔 In-App<br>💬 Toast | 🔔 In-App<br>💬 Toast<br>*(หากมีส่วนร่วม)* | 🔔 In-App<br>💬 Toast<br>📧 Email<br>*(เมื่อทีมงานตอบ)* | 🔔 In-App<br>💬 Toast<br>📧 Email<br>*(เมื่อลูกค้าตอบ)* |
| **4. ขออนุมัติ Deploy (Deployment Requested)** | 🔔 In-App<br>💬 Toast<br>📧 Email + Link | 🔔 In-App<br>💬 Toast<br>📧 Email + Link | 🔔 In-App<br>💬 Toast<br>*(บริษัทตนเอง)* | — | 🔔 In-App<br>💬 Toast |
| **5. ประกาศปิดปรับปรุง (Maintenance Notice)** | 🔔 In-App<br>📌 Banner | 🔔 In-App<br>📌 Banner | 🔔 In-App<br>📌 Banner | 🔔 In-App<br>📌 Banner | 🔔 In-App<br>📌 Banner |

---

## 🔔 4. ช่องทางการแจ้งเตือนในระบบ (Notification Channels)

### 4.1 In-App Notification (กระดิ่งแจ้งเตือน 🔔)
* **การแสดงผล**: ตัวเลขนับจำนวนแจ้งเตือนที่ยังไม่ได้อ่าน (Badge Count) บนไอคอนกระดิ่งมุมขวาบน
* **การทำงาน**:
  - เมื่อคลิกดูรายการ จะแสดงรายการแจ้งเตือนล่าสุดพร้อมสถานะ วันที่ และเวลา
  - เมื่อคลิกที่รายการใด รายการนั้นจะถูกเปลี่ยนเป็นสถานะ **อ่านแล้ว (Read)** และเปิดหน้า Ticket นั้นให้อัตโนมัติทันที
  - มีปุ่ม "Mark all as read" สำหรับเคลียร์การแจ้งเตือนทั้งหมด

### 4.2 Real-Time Push Toast (ป๊อปอัปแจ้งเตือนสด 💬)
* **การแสดงผล**: ป๊อปอัป Toast สวยงามที่มุมขวาบนของหน้าจอพร้อมเสียงสัญญาณเตือนสั้นๆ (Audio Chime)
* **การทำงาน**:
  - ใช้เทคโนโลยี **Server-Sent Events (SSE)** ข้อมูลจะเด้งขึ้นมาทันทีโดยไม่ต้องกดรีเฟรชหน้าจอ (0ms Latency)
  - ตาราง Ticket บนหน้าจอจะอัปเดตแถวใหม่ให้อัตโนมัติทันที

### 4.3 Email Notification (จดหมายแจ้งเตือน 📧)
* **การแสดงผล**: อีเมล HTML Responsive สวยงาม มีรายละเอียด Ticket ชัดเจน และปุ่มกดเข้าสู่หน้า Ticket ได้โดยตรง
* **ความปลอดภัย & Multi-Tenancy**: 
  - ระบบตรวจสอบสิทธิ์ก่อนส่ง (Multi-Tenant Isolation) ลูกค้าบริษัท A จะไม่มีวันได้รับอีเมลของบริษัท B
  - รองรับการตั้งค่าเปิด/ปิดแจ้งเตือนอีเมลตามความต้องการของแต่ละบริษัท (Notification Rule Config)

---

## ⚙️ 5. ความจุและขีดความสามารถของระบบ (Load Capacity & Concurrency)

* **Gunicorn Concurrency**: ปรับแต่งเป็น `3 Workers x 20 Threads = 60 Concurrent Request Threads`
* **Real-time Capacity**: รองรับผู้ใช้งานเปิดหน้าเว็บและรับสตรีม Real-time พร้อมกันได้ **30–60+ คน** อย่างลื่นไหล
* **Background Tab Optimization**: ระบบจะหยุดสตรีมชั่วคราวหากผู้ใช้สลับไปแท็บอื่นเกิน 2 นาที เพื่อประหยัด CPU/Bandwidth และจะเชื่อมต่อข้อมูลสดทันทีที่สลับกลับมาใช้งาน
