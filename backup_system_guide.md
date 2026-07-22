# 🛡️ คู่มือระบบสำรองข้อมูลอัตโนมัติไปยัง Microsoft OneDrive (TicketSolve Backup System)

เอกสารฉบับนี้อธิบายโครงสร้าง นโยบายการเก็บรักษาข้อมูล (Retention Policy) และขั้นตอนการติดตั้ง/ใช้งาน **ระบบสำรองข้อมูลอัตโนมัติ (Automated Backup System)** สำหรับโปรเจกต์ **TicketSolve** บน Google Cloud VPS

---

## 📌 1. ภาพรวมและนโยบายการเก็บรักษาข้อมูล (Retention Policy)

ระบบสำรองข้อมูลนี้ถูกออกแบบให้ทำงานอัตโนมัติทุกๆ 1 ชั่วโมง โดยบีบอัดข้อมูลสำคัญของระบบ แล้วส่งไปจัดเก็บบน **Microsoft OneDrive** พร้อมนโยบายจัดการพื้นที่ดังนี้:

| ประเภทการสำรองข้อมูล | ความถี่ในการทำงาน | การลบไฟล์ย้อนหลัง | โฟลเดอร์ปลายทางบน Google Drive |
| :--- | :--- | :--- | :--- |
| **Continuous 2-Hour Backup** | ทุก 2 ชั่วโมง (`0 */2 * * *`) | **บันทึกต่อเนื่องไปเรื่อยๆ (ไม่ลบไฟล์เก่า)** | โฟลเดอร์ `TicketSolveBackups` บน Personal Google Drive |

### 📦 ข้อมูลที่ถูกสำรองไว้ในไฟล์บีบอัด (`.tar.gz`):
1. **`db.sqlite3`** – ฐานข้อมูลระบบ Ticket ทั้งหมด (ข้อมูลผู้ใช้, รายการ Ticket, ประวัติการอัปเดต)
2. **`media/`** – รูปภาพและไฟล์เอกสารแนบทั้งหมดใน Ticket
3. **`.env`** – ไฟล์การตั้งค่าแวดล้อม (Environment Variables)

---

## 🏗️ 2. โครงสร้างไฟล์และระบบที่เกี่ยวข้อง

```text
/var/www/ticketSolve/
└── deployment/
    └── backup.sh             <-- สคริปต์หลักสำหรับรันการสำรองข้อมูล

/var/backups/ticketsolve/
├── hourly/                   <-- โฟลเดอร์เก็บไฟล์รายชั่วโมง (สูงสุด 24 ไฟล์)
│   ├── backup_2026-07-22_18-00-00.tar.gz
│   └── backup_2026-07-22_19-00-00.tar.gz
└── daily/                    <-- โฟลเดอร์เก็บไฟล์รายวัน (สูงสุด 2 ไฟล์)
    ├── daily_backup_2026-07-21.tar.gz
    └── daily_backup_2026-07-22.tar.gz
```

---

## 🛠️ 3. ขั้นตอนการติดตั้งและเชื่อมต่อกับ OneDrive

### ขั้นตอนที่ 1: ติดตั้งโปรแกรมและเตรียมโฟลเดอร์บน VPS
เชื่อมต่อ SSH เข้าไปยังเซิร์ฟเวอร์ GCP แล้วรันคำสั่ง:

```bash
cd /var/www/ticketSolve
git pull
chmod +x deployment/backup.sh

# ติดตั้ง rclone สำหรับเชื่อมต่อ OneDrive
sudo apt update && sudo apt install -y rclone

# สร้างโฟลเดอร์สำรองข้อมูลบนเซิร์ฟเวอร์
sudo mkdir -p /var/backups/ticketsolve
sudo chown -R ubuntu:ubuntu /var/backups/ticketsolve
```

---

### ขั้นตอนที่ 2: เชื่อมต่อ rclone เข้ากับบัญชี Microsoft OneDrive
พิมพ์คำสั่งตั้งค่า:
```bash
rclone config
```

ปฏิบัติตามขั้นตอนบนหน้าจอ:
1. พิมพ์ `n` เพื่อสร้าง **New remote**
2. ตั้งชื่อ remote: **`onedrive`** *(ต้องเป็นอักษรพิมพ์เล็กตามนี้เท่านั้น)*
3. เลือกประเภท Storage: มองหาลำดับของ **Microsoft OneDrive** (พิมพ์หมายเลขลำดับ)
4. `client_id` ➡️ กด **Enter** (เว้นว่าง)
5. `client_secret` ➡️ กด **Enter** (เว้นว่าง)
6. `national_cloud` ➡️ พิมพ์ `1` (Global)
7. `Edit advanced config?` ➡️ พิมพ์ `n`
8. `Use auto config?` ➡️ พิมพ์ **`n`**
9. ระบบจะแสดง **URL ลิงก์ยืนยันตัวตน** ขึ้นมา:
   * คัดลอก URL ดังกล่าวไปเปิดในเว็บเบราว์เซอร์บนคอมพิวเตอร์ของคุณ
   * ล็อกอินบัญชี Microsoft และกดกดยินยอม (Allow)
   * คัดลอก **Verification Code** ที่ปรากฏบนหน้าเว็บ กลับมาวางใน terminal SSH แล้วกด **Enter**
10. เลือกไดรฟ์ที่ต้องการ (พิมพ์ `1` สำหรับ OneDrive Personal/Business)
11. ยืนยันการตั้งค่า พิมพ์ `y` และพิมพ์ `q` เพื่อออกจากเมนู

---

### ขั้นตอนที่ 3: ตั้งค่าตั้งเวลาทำงานอัตโนมัติ (Crontab)
เปิดไฟล์ตั้งค่าเวลาของระบบ:
```bash
crontab -e
```

เพิ่มบรรทัดนี้ไว้ที่ล่างสุดของไฟล์:
```cron
0 * * * * /var/www/ticketSolve/deployment/backup.sh >> /var/log/ticketsolve_backup.log 2>&1
```
*(ระบบจะรันสคริปต์สำรองข้อมูลทุกๆ ต้นชั่วโมงอัตโนมัติ)*

---

## ⚡ 4. การรันสำรองข้อมูลด้วยตนเอง (Manual Run)

หากต้องการสั่งให้ระบบสำรองข้อมูลและส่งขึ้น OneDrive ทันทีโดยไม่ต้องรอให้ครบชั่วโมง สามารถรันคำสั่งนี้ได้ตลอดเวลา:

```bash
/var/www/ticketSolve/deployment/backup.sh
```

---

## 🔄 5. ขั้นตอนการกู้คืนข้อมูล (Restore Procedure)

หากเกิดเหตุฉุกเฉินและต้องการกู้คืนระบบกลับมาจากไฟล์สำรองข้อมูล:

1. **ดาวน์โหลดไฟล์สำรองข้อมูล** จากโฟลเดอร์ `TicketSolveBackups` บน OneDrive หรือจาก `/var/backups/ticketsolve/`
2. **คัดแยกไฟล์ออกมาระบุโฟลเดอร์โปรเจกต์:**
   ```bash
   cd /var/www/ticketSolve
   # หยุดการทำงานของ Gunicorn ชั่วคราว
   sudo systemctl stop gunicorn

   # แตกไฟล์สำรองข้อมูลทับไฟล์เดิม (เช่น ไฟล์ daily_backup_2026-07-22.tar.gz)
   tar -xzf /var/backups/ticketsolve/daily/daily_backup_2026-07-22.tar.gz -C /var/www/ticketSolve/

   # รีสตาร์ทบริการระบบ
   sudo systemctl start gunicorn
   ```

---

## 📝 6. การตรวจสอบสถานะและบันทึกประวัติการทำงาน (Logs)

คุณสามารถตรวจสอบประวัติการสำรองข้อมูลย้อนหลังได้จากไฟล์ Log:

```bash
tail -f /var/log/ticketsolve_backup.log
```
