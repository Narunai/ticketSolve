# แผนการเปลี่ยนจาก Django Admin มาใช้ Custom Admin System ในตัวแอปหลัก

แผนงานนี้เป็นการยกเลิกการใช้ Django Administration (`/admin/`) สำหรับ Client Admin และ System Admin เพื่อเปลี่ยนมาเป็นระบบควบคุมที่สร้างขึ้นมาเอง (Custom Admin Views & Templates) ที่ออกแบบด้วยดีไซน์ที่สอดคล้องกับระบบหลัก และมีความปลอดภัยสูง

---

## 📋 ภาพรวมสถาปัตยกรรม (Architecture Overview)

เราจะยกเลิกการเชื่อมโยงหลังบ้านไปยัง `/admin/` และสร้างเมนูจัดการข้อมูล 2 ส่วนหลักในโปรเจกต์:
1. **หน้าจัดการองค์กร/บริษัท (Company Management)**: 
   * เข้าถึงได้เฉพาะผู้ดูแลส่วนกลาง (`SYSTEM_ADMIN`)
   * สำหรับสร้าง แก้ไข และดูรายชื่อบริษัททั้งหมดในระบบ
2. **หน้าจัดการบัญชีผู้ใช้ (User Management)**:
   * **SYSTEM_ADMIN**: เห็นรายชื่อและจัดการผู้ใช้งานได้จากทุกบริษัท
   * **CLIENT_ADMIN**: เห็นรายชื่อและจัดการ (สร้าง/แก้ไข/เปลี่ยนบทบาท) ได้เฉพาะผู้ใช้งานที่อยู่ในบริษัทเดียวกันเท่านั้น (ห้ามจัดการผู้ใช้งานของบริษัทอื่น หรือแต่งตั้งสิทธิ์เป็น `SYSTEM_ADMIN`)
   * **CLIENT_USER**: เข้าถึงหน้านี้ไม่ได้เลย

---

## 🛠️ แผนงานรายไฟล์และเมนูที่เสนอปรับเปลี่ยน (Proposed Changes)

### Component 1: หน้าจอและวิวควบคุมแบบ Custom Admin (Views & Forms)

#### [MODIFY] [views.py](file:///d:/Project_personal/ticketSolve/tickets/views.py)
* เพิ่ม Forms:
  * `CompanyForm`: ฟอร์มเพิ่ม/แก้ไขบริษัท
  * `CustomUserForm`: ฟอร์มเพิ่มผู้ใช้งาน กำหนดให้กรองสิทธิ์และบริษัทแบบอัตโนมัติตามระดับผู้สร้าง (เช่น หากแอดมินบริษัท A สร้าง จะเลือกบริษัทอื่นไม่ได้ และสิทธิ์จะไม่สามารถเป็น System Admin ได้)
* เพิ่ม Views (พร้อมระบบความปลอดภัยเช็ค Role):
  * `CompanyListView` & `CompanyCreateView` & `CompanyUpdateView`: จัดการบริษัท (จำกัดเฉพาะ `SYSTEM_ADMIN`)
  * `UserListView` & `UserCreateView` & `UserUpdateView`: จัดการผู้ใช้รายบริษัท (กรองสิทธิ์ตาม Tenant)

---

### Component 2: เส้นทาง URL และส่วนนำทางหลัก (URLs & Base Template)

#### [MODIFY] [urls.py](file:///d:/Project_personal/ticketSolve/tickets/urls.py)
* เพิ่ม URL Paths สำหรับการจัดการบริษัทและจัดการบัญชีผู้ใช้งาน:
  * `companies/`
  * `companies/create/`
  * `companies/<int:pk>/edit/`
  * `users/`
  * `users/create/`
  * `users/<int:pk>/edit/`

#### [MODIFY] [base.html](file:///d:/Project_personal/ticketSolve/tickets/templates/tickets/base.html)
* แก้ไขลิงก์ใน Sidebar:
  * แทนที่ลิงก์ไปหน้า `/admin/` เดิมด้วยลิงก์ไปหน้า `จัดการผู้ใช้งาน` และ `จัดการองค์กร/บริษัท` แบบไดนามิกตามบทบาทผู้ใช้ (`SYSTEM_ADMIN` หรือ `CLIENT_ADMIN`)

---

### Component 3: เทมเพลตหน้าจอสำหรับ Custom Admin (HTML Templates)

#### [NEW] [company_list.html](file:///d:/Project_personal/ticketSolve/tickets/templates/tickets/company_list.html)
หน้าจอแสดงรายชื่อบริษัท/องค์กรทั้งหมดในระบบ พร้อมสถิติจำนวนผู้ใช้และ Ticket ของแต่ละบริษัท

#### [NEW] [company_form.html](file:///d:/Project_personal/ticketSolve/tickets/templates/tickets/company_form.html)
ฟอร์มสำหรับสร้างหรือแก้ไขชื่อบริษัท

#### [NEW] [user_list.html](file:///d:/Project_personal/ticketSolve/tickets/templates/tickets/user_list.html)
หน้าจอแสดงรายชื่อพนักงานย่อยในระบบและบทบาทของสมาชิก โดยกรองตามบริษัทของแอดมินที่ล็อกอินเข้ามา

#### [NEW] [user_form.html](file:///d:/Project_personal/ticketSolve/tickets/templates/tickets/user_form.html)
หน้าจอแบบฟอร์มเพิ่มหรือแก้ไขรายชื่อพนักงาน

---

### Component 4: ปรับปรุงการทดสอบและคู่มือ

#### [MODIFY] [tests.py](file:///d:/Project_personal/ticketSolve/tickets/tests.py)
* ยกเลิกการจำลองการทดสอบของหน้า Django Admin
* เพิ่มการทดสอบ Custom Views (`UserListView`, `CompanyListView`, `UserCreateView`) เพื่อตรวจสอบความปลอดภัยในระดับ URL & Method ว่าไม่มีการดึงข้อมูลข้าม Tenant สำเร็จ

#### [MODIFY] [walkthrough.md](file:///d:/Project_personal/ticketSolve/walkthrough.md) & [testing_guide.md](file:///d:/Project_personal/ticketSolve/testing_guide.md)
* อัปเดตข้อมูลลิงก์การทดสอบโดยตัดเนื้อหา Django Admin ออก และอธิบายการทดสอบผ่าน Custom Admin Panel แทน

---

## 🧪 แผนการตรวจสอบความถูกต้อง (Verification Plan)

### Automated Tests
* รัน `python manage.py test` และต้องไม่มีข้อผิดพลาด โดย Unit Tests ชุดใหม่จะเน้นตรวจจับการแฮกเข้าถึงหน้า Custom User/Company Admin
  
### Manual Verification
* ล็อกอินด้วย `admin_a` แล้วเข้าไปที่หน้า `/users/` ตรวจสอบว่าเห็นเฉพาะพนักงานบริษัท A หรือไม่ และสามารถเพิ่มพนักงานใหม่เข้าบริษัท A ได้หรือไม่
* ตรวจสอบว่า `admin_a` ไม่สามารถเข้าลิงก์ตรง `/companies/` ได้ (ต้องได้สิทธิ์ 403 / Redirect กลับ)
