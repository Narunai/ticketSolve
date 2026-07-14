---
marp: true
theme: gaia
_class: lead
paginate: true
backgroundColor: #0f172a
color: #f1f5f9
style: |
  section {
    font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
    padding: 40px;
  }
  h1 {
    color: #38bdf8;
  }
  h2 {
    color: #38bdf8;
    border-bottom: 2px solid #334155;
  }
  footer {
    color: #64748b;
  }
  strong {
    color: #38bdf8;
  }
---

# 🚀 สรุปผลงานการพัฒนาระบบ TicketSolve
### ระบบจัดการแจ้งปัญหาแยกข้อมูลองค์กร (Multi-tenant Ticket System)
และโครงสร้างการติดตั้งบนระบบ AWS Lightsail & Cloudflare

**ผู้จัดทำ**: Antigravity AI Co-Developer

---

## 🎯 ภาพรวมและสถาปัตยกรรมของโปรเจกต์
* **Multi-tenant Data Isolation**: แยกข้อมูลตั๋ว พนักงาน และผู้รับผิดชอบอย่างเด็ดขาดตามรายบริษัท ป้องกันการมองเห็นข้อมูลข้ามองค์กร
* **Flexible SMTP Dispatcher**: ระบบตั้งค่าเซิร์ฟเวอร์ SMTP บนหน้าเว็บพร้อมใช้งานแบบไดนามิก และสามารถเลือกเมลผู้ส่งได้ทันทีเมื่อกดส่งรายงาน
* **Role-Based Access Control (RBAC)**: ระบบแบ่งสิทธิ์ผู้ใช้งานจากส่วนกลาง (System Admin, System Sub-Admin) และสิทธิ์ระดับองค์กร (Client Admin, Client User)

---

## 🔒 1. ระบบรักษาความปลอดภัย & สิทธิ์ Sub-Admin

* **System Sub-Administrator (สิทธิ์ผู้ดูแลย่อยส่วนกลาง)**:
  * มีสิทธิ์ดูและจัดการ Ticket และองค์กรได้ทุกแห่งเพื่อช่วยเหลือผู้ใช้
  * **ข้อจำกัดความปลอดภัย**: ไม่สามารถเข้าถึงหน้าตั้งค่าระบบ SMTP และไม่สามารถสร้าง/แก้ไขสิทธิ์แอดมินคนอื่นๆ ได้ (ป้องกันสิทธิ์ข้ามระดับ)
* **การบันทึกประวัติ (Audit Logs)**:
  * **ReportViewLog**: บันทึกทุกครั้งเมื่อมีใครคลิกเปิดดูไฟล์ PDF รายงาน
  * **EmailLog**: บันทึกประวัติและผลลัพธ์ (SUCCESS/FAILED) การส่งอีเมลแจ้งรายงานทุกฉบับ

---

## 📧 2. ระบบจัดการ SMTP & ตัวเลือกอีเมลผู้ส่ง (On-Demand Selector)

* **Dynamic SMTP Settings Page**:
  * ลงทะเบียน ลบ และแก้ไขเซิร์ฟเวอร์ SMTP ผ่านหน้าเว็บได้ทันที
  * มี Preset อำนวยความสะดวกกรอกค่าอัตโนมัติ (Gmail / Microsoft Outlook / Simulation)
  * บังคับใช้งาน Active ได้สูงสุดเพียง 1 เครื่องเพื่อป้องกันความสับสน
* **ตัวเลือกอีเมลส่งรายงาน**:
  * บนหน้าส่งรายงาน PDF สามารถกดเลือกได้ว่าจะใช้เมล SMTP ตัวไหนในการกดจัดส่งออกไป หรือเลือกใช้เซิร์ฟเวอร์หลักของระบบ

---

## 🔑 3. ระบบเข้าใช้งาน & ความสะดวกในการใช้งาน (UX/UI Improvements)

* **Dual-Field Authentication**: 
  * หน้าเข้าสู่ระบบ (Login) รองรับการตรวจสอบผ่านการกรอก **ชื่อผู้ใช้งาน (Username)** หรือ **อีเมล (Email)** ตัวใดตัวหนึ่งได้ทันที
* **ปุ่มสลับการซ่อน/แสดงรหัสผ่าน (Password Visibility Toggle)**:
  * ติดตั้งปุ่มตา (Eye Icon) ควบคุมด้วย JavaScript ในทุกหน้ารับรหัสผ่าน (หน้าเข้าสู่ระบบ, ฟอร์มจัดการผู้ใช้, และหน้ารหัสผ่านแอป SMTP)
* **Mobile UI Optimization**:
  * แก้ไขลำดับการซ้อนทับ (Z-Index) เมนูโหมดธีมและสีไม่ให้ถูกทับบนมือถือ

---

## 📦 4. แผนการติดตั้งบน AWS Lightsail & Cloudflare

* **เครื่องเซิร์ฟเวอร์**: AWS Lightsail (Ubuntu 22.04 LTS, RAM 2GB, 2 vCPUs) ทำงานใน Region สิงคโปร์
* **โครงสร้างซอฟต์แวร์**: Nginx + Gunicorn (4 Workers) + PostgreSQL 15 + Certbot SSL
* **Cloudflare Integration**: ปกป้อง IP เซิร์ฟเวอร์จริงด้วย Proxied Cloud, เปิดใช้ WAF ตรวจจับภัยคุกคาม และตั้งกฎข้ามการแคชหน้าเว็บไดนามิกเพื่อให้หน้าข้อมูลตั๋วแสดงผลเรียลไทม์

---

## 🧪 5. การทดสอบและความมั่นใจในระบบ (Testing & Quality)

* **Unit Tests**: พัฒนาขึ้นครอบคลุมทุกฟีเจอร์สำคัญ (Multi-tenant, Sub-Admin, SMTP Dynamic, Dual-Login, Dynamic Sender Email)
* **คำสั่งรันการตรวจสอบ**:
  ```powershell
  python manage.py test
  ```
* **ผลการรันชุดทดสอบ**:
  * **จำนวนการทดสอบที่รัน**: **20 เคส**
  * **ผลลัพธ์**: **OK (ผ่าน 100% ทุกหัวข้อ)** 🥳
