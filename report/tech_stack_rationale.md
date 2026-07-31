# 🧠 รายงานวิเคราะห์และเหตุผลเชิงเทคนิคในการเลือกใช้ Python & SQLite (Tech Stack Rationale Report)

**วันที่จัดทำ**: 14 กรกฎาคม 2026 (14 July 2026)  
**ปรับปรุงข้อมูลระบบล่าสุด**: 31 กรกฎาคม 2026
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
* **Data Isolation Enforcement**: ขอบเขตการอ่านและแก้ไข Ticket รวมไว้ใน `tickets/permissions.py` แล้วให้ View, Dashboard และ attachment endpoints ใช้กติกาเดียวกัน System Staff เห็นทุก tenant, Client Admin/Staff เห็น company tree ของตน และ Client User เห็นเฉพาะ Ticket ที่ตนสร้าง
* **Defense in Depth**: ไฟล์แนบไม่ถูกเสิร์ฟจาก `/media/` โดยตรง แต่ผ่าน authenticated Django views ซึ่งตรวจ Ticket visibility ก่อนส่งไฟล์

### 2.2 โครงสร้างแบบ Batteries-Included เพิ่มความเร็วในการพัฒนา
* Django มาพร้อมเครื่องมือสำเร็จรูปครบครัน ได้แก่ ระบบ Admin Panel หลังบ้าน, Form Validation & Cleaners, Message Framework, และ Context Processors (ที่ใช้สำหรับระบบสลับภาษา TH/EN)
* ช่วยลดเวลาในการเขียนโค้ดพื้นฐาน (Boilerplate Code) ทำให้ทีมงานโฟกัสกับการพัฒนาฟีเจอร์ธุรกิจหลักได้เต็มที่

### 2.3 ความเสถียรในการออกรายงาน PDF ภาษาไทย และส่งอีเมล
* **Ecosystem ภาษาไทยสมบูรณ์**: Python มีไลบรารีแปลงโครงสร้าง HTML เป็น PDF (`xhtml2pdf`) ที่รองรับการประมวลผลฟอนต์ภาษาไทย (Sarabun / Tahoma) ได้อย่างคมชัด แม่นยำ ไม่เจอปัญหาตัวอักษรสี่เหลี่ยมหรืออักขระเพี้ยน
* **SMTP Delivery Integration**: สามารถสร้างระบบยิงส่งอีเมลแจ้งเตือนรายงานประจำเดือน และการตั้งค่า SMTP Dynamic แบบเปลี่ยนผ่านหน้าเว็บได้อย่างราบรื่น
* **Email Ingestion**: ใช้ IMAP SSL จาก Python standard library และ `BeautifulSoup` ล้าง HTML ก่อนสร้าง Ticket พร้อม Message-ID deduplication; Microsoft 365 ที่ปิด IMAP ต้องเพิ่ม Graph/OAuth แยกต่างหาก
* **Database-controlled Timer**: systemd ใช้ base tick 10 นาที ขณะที่ Django เก็บ interval 10/20/30/60 นาทีและ execution log ในฐานข้อมูล ทำให้ปรับรอบจากหน้าเว็บได้โดยไม่แก้ unit file
* **Database-driven Sender Routing**: ตาราง routing แยกตาม SMTP mailbox ใช้ sender email เลือก assignee และ fallback ไปค่าหลักเมื่อไม่พบกฎ

---

## 🗄️ 3. เหตุผลเชิงลึกในการเลือกใช้ฐานข้อมูล SQLite

### 3.1 การประหยัดทรัพยากร RAM บน Cloud VPS สเปคประหยัด
* **ข้อจำกัด VPS**: บนเซิร์ฟเวอร์ AWS Lightsail (แพ็กเกจ $10/เดือน) มีหน่วยความจำ RAM จำกัดที่ 2 GB
* **เทียบกับ RDBMS ขนาดใหญ่**: หากใช้ PostgreSQL หรือ MySQL ตัวระบบจัดการฐานข้อมูลจะถูกรันเป็น Background Service ค้างไว้ตลอดเวลา กิน RAM ไปทันที 300MB – 600MB
* **ข้อได้เปรียบของ SQLite**: SQLite เป็น **Embedded File-Based Database** ทำงานเป็นไฟล์เดียว (`db.sqlite3`) อ่านเขียนตรงผ่านภาษา Python เฉพาะเวลามี Request เข้ามา ทำให้ประหยัด RAM บน VPS ได้สูงสุดถึง **80%** ป้องกันปัญหาเซิร์ฟเวอร์ล่มจาก RAM เต็ม (Out of Memory / OOM Kill)

### 3.2 การติดตั้งแบบ Zero Configuration และความง่ายในการสำรองข้อมูล (Backup)
* **Zero Config**: ไม่ต้องตั้งค่า Database User, Password, Port, หรือ Network Socket ที่ซับซ้อน เพียงสั่งคำสั่ง `python manage.py migrate` ฐานข้อมูลก็พร้อมใช้งานทันที
* **Consistent Database Backup**: ระบบใช้ SQLite Online Backup API เพื่อสร้าง snapshot ที่สอดคล้องระหว่างที่แอปยังทำงาน แล้วจึงบีบอัดร่วมกับ `media/` เก็บที่ `/var/backups/ticketsolve`
* **Operational Limitation**: SQLite เหมาะกับ workload ขนาดเล็กถึงกลาง แต่มีข้อจำกัดเรื่อง concurrent writes จึงต้องวัดผลและวางแผนย้ายฐานข้อมูลเมื่อปริมาณการเขียนเติบโต

---

## 🔗 4. บทบาทและการทำงานของ Django ORM ในโปรเจกต์

Django ORM (Object-Relational Mapper) ทำหน้าที่เป็นตัวกลางเชื่อมต่อระหว่างภาษา Python และ SQLite โดยถูกนำไปใช้งานใน 4 ส่วนหลัก:

1. **Model Definition (`tickets/models.py`)**:
   กำหนดโครงสร้างตารางและความสัมพันธ์แบบ OOP แทนการเขียน `CREATE TABLE` ใน SQL เช่น ตาราง `Company`, `CustomUser`, `Ticket`, `TicketComment`, `TicketAuditLog`, `SMTPConfiguration`
2. **Data Querying & Multi-tenant Isolation (`tickets/permissions.py`, `tickets/views.py`)**:
   ใช้ดึง คัดกรอง และคำนวณสถิติข้อมูล เช่น:
   ```python
   # ใช้กติกากลาง: Client User เห็นเฉพาะ Ticket ที่ตนสร้าง
   tickets = visible_tickets_for(request.user)
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
* **ORM ลดขอบเขตการแก้โค้ด**: Business queries ส่วนใหญ่ใช้ Django ORM จึงนำไปปรับใช้กับ PostgreSQL ได้ง่ายกว่าการผูกกับ Raw SQL
* **ไม่ใช่การเปลี่ยนเพียงหนึ่งบรรทัดในระบบปัจจุบัน**: `ticket_system/settings.py` ยังตั้งค่า SQLite โดยตรง การย้ายต้องเพิ่ม database configuration, ย้ายและตรวจความครบถ้วนของข้อมูล, ทดสอบ transaction/concurrency, ปรับ backup/restore และทำ rollback plan
* **จุดตัดสินใจ**: ควรพิจารณา PostgreSQL เมื่อพบ write contention, lock timeout, จำนวน concurrent writes เพิ่มต่อเนื่อง หรือต้องทำ high availability

---

### 📌 สรุป
> **Python (Django) ร่วมกับ SQLite เหมาะกับขนาดระบบปัจจุบันเพราะดูแลง่ายและใช้ทรัพยากรต่ำ โดยต้องคง authorization tests, backup/restore verification และติดตามข้อจำกัด concurrent writes เพื่อกำหนดเวลาย้ายไป PostgreSQL อย่างมีข้อมูลรองรับ**
