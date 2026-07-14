# 🧠 รายงานวิเคราะห์และเหตุผลเชิงเทคนิคในการเลือกใช้ Python & SQLite (Tech Stack Rationale Report)

**วันที่จัดทำ**: 14 กรกฎาคม 2026 (14 July 2026)  
**ชื่อโปรเจกต์**: TicketSolve - Multi-tenant Helpdesk Ticket System  
**ไฟล์เอกสารประกอบ**: `report/tech_stack_rationale.md`  

---

## 🎯 1. ภาพรวมการตัดสินใจทางเทคโนโลยี (Executive Summary)

ในการออกแบบสถาปัตยกรรมสำหรับระบบ **TicketSolve** (ระบบแจ้งปัญหาและติดตามสถานะงานซ่อมบำรุงทางเทคนิคแบบแยกองค์กร Multi-tenant) คณะผู้พัฒนาได้พิจารณาคัดเลือกเทคโนโลยีประมวลผลหลักเป็น **Python (Django Framework)** และระบบจัดการฐานข้อมูล **SQLite** โดยยึดหลักการ 4 ประการ:
1. **ความปลอดภัยและการแยกสิทธิ์ข้อมูล (Security & Multi-tenant Data Isolation)**
2. **การประหยัดทรัพยากรเซิร์ฟเวอร์และควบคุมงบประมาณ (Resource & Cost Efficiency)**
3. **ความเร็วในการพัฒนาและการดูแลรักษาระบบ (Developer Productivity & Maintainability)**
4. **ความยืดหยุ่นในการขยายตัวในอนาคต (Future-Proof Scalability)**

---

## 🐍 2. เหตุผลเชิงลึกในการเลือกใช้ภาษา Python ร่วมกับ Django Framework

### 2.1 ความปลอดภัยและการกั้นขอบเขตข้อมูลรายบริษัท (Multi-tenant Security)
* **Built-in Security Architecture**: Django มีระบบจัดการสิทธิ์ผู้ใช้งาน (Authentication/Authorization) และ Middleware ป้องกันการโจมตีระดับสากล เช่น **SQL Injection**, **Cross-Site Scripting (XSS)**, **Cross-Site Request Forgery (CSRF)**, และ **Clickjacking** ในระดับแกนกลาง
* **Data Isolation Enforcement**: ด้วยการออกแบบผ่าน Django ORM ช่วยให้การเขียนลอจิกตรวจสอบสิทธิ์ใน View (`tickets/views.py`) ทำได้อย่างเด็ดขาด ผู้ใช้จากบริษัทหนึ่งจะไม่สามารถมองเห็น หรือแก้ไขข้อมูล Ticket ของอีกบริษัทหนึ่งได้โดยสิ้นเชิง (หากยิง URL ข้ามบริษัท ระบบจะส่งตอบกลับ `403 Forbidden` ทันที)

### 2.2 โครงสร้างแบบ Batteries-Included เพิ่มความเร็วในการพัฒนา
* Django มาพร้อมเครื่องมือสำเร็จรูปครบครัน ได้แก่ ระบบ Admin Panel หลังบ้าน, Form Validation & Cleaners, Message Framework, และ Context Processors (ที่ใช้สำหรับระบบสลับภาษา TH/EN)
* ช่วยลดเวลาในการเขียนโค้ดพื้นฐาน (Boilerplate Code) ทำให้ทีมงานโฟกัสกับการพัฒนาฟีเจอร์ธุรกิจหลักได้เต็มที่

### 2.3 ความเสถียรในการออกรายงาน PDF ภาษาไทย และส่งอีเมล
* **Ecosystem ภาษาไทยสมบูรณ์**: Python มีไลบรารีแปลงโครงสร้าง HTML เป็น PDF (`xhtml2pdf`) ที่รองรับการประมวลผลฟอนต์ภาษาไทย (Sarabun / Tahoma) ได้อย่างคมชัด แม่นยำ ไม่เจอปัญหาตัวอักษรสี่เหลี่ยมหรืออักขระเพี้ยน
* **SMTP Delivery Integration**: สามารถสร้างระบบยิงส่งอีเมลแจ้งเตือนรายงานประจำเดือน และการตั้งค่า SMTP Dynamic แบบเปลี่ยนผ่านหน้าเว็บได้อย่างราบรื่น

---

## 🗄️ 3. เหตุผลเชิงลึกในการเลือกใช้ฐานข้อมูล SQLite

### 3.1 การประหยัดทรัพยากร RAM บน Cloud VPS สเปคประหยัด
* **ข้อจำกัด VPS**: บนเซิร์ฟเวอร์ AWS Lightsail (แพ็กเกจ $10/เดือน) มีหน่วยความจำ RAM จำกัดที่ 2 GB
* **เทียบกับ RDBMS ขนาดใหญ่**: หากใช้ PostgreSQL หรือ MySQL ตัวระบบจัดการฐานข้อมูลจะถูกรันเป็น Background Service ค้างไว้ตลอดเวลา กิน RAM ไปทันที 300MB – 600MB
* **ข้อได้เปรียบของ SQLite**: SQLite เป็น **Embedded File-Based Database** ทำงานเป็นไฟล์เดียว (`db.sqlite3`) อ่านเขียนตรงผ่านภาษา Python เฉพาะเวลามี Request เข้ามา ทำให้ประหยัด RAM บน VPS ได้สูงสุดถึง **80%** ป้องกันปัญหาเซิร์ฟเวอร์ล่มจาก RAM เต็ม (Out of Memory / OOM Kill)

### 3.2 การติดตั้งแบบ Zero Configuration และความง่ายในการสำรองข้อมูล (Backup)
* **Zero Config**: ไม่ต้องตั้งค่า Database User, Password, Port, หรือ Network Socket ที่ซับซ้อน เพียงสั่งคำสั่ง `python manage.py migrate` ฐานข้อมูลก็พร้อมใช้งานทันที
* **Single-File Backup**: ข้อมูลทั้งหมดของระบบถูกจัดเก็บอยู่ในไฟล์เดียวคือ `db.sqlite3` การสำรองข้อมูล (Disaster Recovery) ทำได้ง่ายๆ เพียงคัดลอกไฟล์ `db.sqlite3` เก็บไว้ โดยไม่ต้องเสี่ยงกับสคริปต์ Dump SQL ที่ซับซ้อน

---

## 🔗 4. บทบาทและการทำงานของ Django ORM ในโปรเจกต์

Django ORM (Object-Relational Mapper) ทำหน้าที่เป็นตัวกลางเชื่อมต่อระหว่างภาษา Python และ SQLite โดยถูกนำไปใช้งานใน 4 ส่วนหลัก:

1. **Model Definition (`tickets/models.py`)**:
   กำหนดโครงสร้างตารางและความสัมพันธ์แบบ OOP แทนการเขียน `CREATE TABLE` ใน SQL เช่น ตาราง `Company`, `CustomUser`, `Ticket`, `TicketComment`, `TicketAuditLog`, `SMTPConfiguration`
2. **Data Querying & Multi-tenant Isolation (`tickets/views.py`)**:
   ใช้ดึง คัดกรอง และคำนวณสถิติข้อมูล เช่น:
   ```python
   # กั้นเขตข้อมูลเฉพาะบริษัทสังกัดผู้ใช้
   tickets = Ticket.objects.filter(company=user.company)
   # นับจำนวนสถิติตามสถานะ
   open_count = tickets.filter(status='OPEN').count()
   ```
3. **Automatic Form Binding (`ModelForms`)**:
   เชื่อมต่อฟอร์มหน้าเว็บเข้ากับ ORM สั่ง `form.save()` เพื่อ `INSERT` หรือ `UPDATE` ข้อมูลลงฐานข้อมูลโดยอัตโนมัติ
4. **Schema Migrations (`tickets/migrations/`)**:
   แปลงโครงสร้างคลาสใน Python เป็นคำสั่งปรับปรุงสคีมาตารางใน SQLite โดยอัตโนมัติเมื่อสั่ง `python manage.py migrate`

---

## 📈 5. แผนการรองรับการขยายตัวในอนาคต (Scalability & Migration Plan)

เนื่องจากโปรเจกต์ TicketSolve พัฒนาและเข้าถึงฐานข้อมูลผ่านชั้นกลาง **Django ORM** ทั้งหมด (ไม่ใช้วิธีเขียน Raw SQL คำสั่งตรง) ทำให้ระบบมีคุณสมบัติ **Decoupled Architecture**:

* **รองรับการขยายตัวในอนาคต**: หากในอนาคตองค์กรเติบโตขึ้นจนมีผู้ใช้งานพร้อมกันหลักหมื่นคน และจำเป็นต้องขยายไปใช้ Enterprise Database เช่น PostgreSQL หรือ MySQL
* **ขั้นตอนการเปลี่ยนทำได้ใน 1 บรรทัด**: เพียงเปลี่ยนค่า `DATABASE_URL` ในไฟล์ `.env` บนเซิร์ฟเวอร์เป็นสตรีม PostgreSQL
* **ไม่ต้องแก้โค้ดลอจิกแม้แต่บรรทัดเดียว**: โค้ดระบบทั้งหมดจะสลับไปดึงข้อมูลจาก PostgreSQL ได้ทันทีโดยไม่ต้องแก้ไขหรือรันใหม่

---

### 📌 สรุป
> **การเลือกใช้ Python (Django) ร่วมกับ SQLite เป็นการตัดสินใจเชิงสถาปัตยกรรมที่คำนึงถึงความปลอดภัย ความเสถียร ประสิทธิภาพ ความคุ้มค่าทางงบประมาณ และความสะดวกในการดูแลรักษาขององค์กรได้อย่างสมบูรณ์แบบ**
