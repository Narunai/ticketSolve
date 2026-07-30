# 🚀 คู่มือการติดตั้งและสำรองข้อมูล (Deployment & Backup Guide)

เอกสารฉบับนี้อธิบายขั้นตอนการติดตั้งระบบ **TicketSolve** บนเซิร์ฟเวอร์ Cloud VPS (AWS Lightsail / Google Cloud) รวมถึงการตั้งค่า Nginx, Gunicorn, Systemd Timer และระบบ Backup

---

## ☁️ 1. รายละเอียดเซิร์ฟเวอร์ Production (Live Environment)

* **Domain**: `https://tikketsolve-systemoneit.uk`
* **Server IP**: `3.1.52.201` (AWS Lightsail / ap-southeast-1)
* **OS**: Ubuntu 22.04 LTS
* **Web Directory**: `/var/www/ticketSolve`
* **Python Environment**: `/var/www/ticketSolve/venv`
* **WSGI Server**: Gunicorn (`/var/www/ticketSolve/gunicorn.sock`)
* **Reverse Proxy**: Nginx (พร้อม SSL Certbot)

---

## 🛠️ 2. ขั้นตอนการ Deploy โค้ดไปยัง Production

### 2.1 อัปเดตโค้ดและไลบรารี
```bash
ssh -i LightsailDefaultKey-ap-southeast-1.pem ubuntu@3.1.52.201

cd /var/www/ticketSolve
git pull origin main

# activate virtual environment
source venv/bin/activate
pip install -r requirements.txt
```

### 2.2 รัน Database Migrations & Collect Static
```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

### 2.3 รีสตาร์ทบริการ Nginx & Gunicorn
```bash
sudo systemctl daemon-reload
sudo systemctl restart gunicorn
sudo systemctl restart nginx
```

---

## 💾 3. โครงสร้างและการทำงานของระบบสำรองข้อมูล (Backup System)

ระบบสำรองข้อมูลใน TicketSolve แบ่งออกเป็น 2 ประเภทหลัก:

### 3.1 ⏱️ 2-Hour Incremental Backup (สำรองข้อมูล 2 ชั่วโมงย้อนหลัง)
* **การทำงาน**: ดึง Ticket, Comments, และไฟล์แนบที่สร้างขึ้นใน 2 ชั่วโมงย้อนหลัง
* **ไฟล์ที่สร้าง**: `incremental_backup_YYYY-MM-DD_HH-MM-SS.zip` (ประกอบด้วย `tickets.json` และโฟลเดอร์ `attachments/`)
* **Google Drive Sync**: อัปโหลดไฟล์ ZIP เข้าไปยัง Google Drive Folder (ID: `1q_86246EXE63IItYtI2tklqwr8EuuNrM`)
* **Disk Cleanup**: ลบไฟล์ ZIP บน VM ทันทีหลังอัปโหลดเสร็จสิ้นเพื่อประหยัดพื้นที่ดิสก์

### 3.2 📦 Full System Backup (สำรองข้อมูลทั้งระบบ)
* **การทำงาน**: บีบอัดฐานข้อมูล `db.sqlite3` + โฟลเดอร์ไฟล์แนบ `media/` + ไฟล์ `.env`
* **ไฟล์ที่สร้าง**: `full_backup_YYYY-MM-DD_HH-MM-SS.tar.gz`
* **Google Drive Sync**: อัปโหลดไฟล์ TAR.GZ ไปยัง Google Drive และเก็บบันทึกประวัติ

### 3.3 📥 Backup Direct Download (ดาวน์โหลดไฟล์สำรองข้อมูล)
* **การใช้งาน**: สามารถดาวน์โหลดไฟล์ Backup (`.zip` หรือ `.tar.gz`) มาตรวจสอบและดูข้อมูลบนเครื่องของคุณได้ทันทีผ่านปุ่ม **📥 Download** ในหน้าจอ Backup Management (`/backups/`)
* **On-Demand Storage**: ไฟล์ Backup จะถูกเก็บไว้ในโฟลเดอร์ `backups/` ของระบบ และหากไฟล์บนดิสก์หายไป ระบบจะทำการสร้างไฟล์บีบอัดสำหรับดาวน์โหลดให้อัตโนมัติทันทีที่กดดาวน์โหลด

---

## ⚙️ 4. คำสั่งจัดการ Backup (Management Commands)

คุณสามารถสั่งรัน Backup ผ่าน Terminal ได้ตลอดเวลา:

```bash
# 1. รัน 2-Hour Incremental Backup (มีระบบป้องกันรันซ้ำซ้อนหากเพิ่งรันไปภายใน 2 ชม.)
python manage.py run_2hr_backup

# 2. บังคับรัน 2-Hour Incremental Backup ทันที (ข้ามตัวป้องกัน)
python manage.py run_2hr_backup --force

# 3. รัน 2-Hour Incremental Backup แบบระบุนานกว่า 2 ชม. (เช่น 6 ชม.)
python manage.py run_2hr_backup --hours 6

# 4. รัน Full System Backup (ทั้งระบบ)
python manage.py run_2hr_backup --full
```

---

## ⏰ 5. การตั้งเวลาอัตโนมัติ (Systemd Scheduler Timer)

ระบบใช้ `systemd` service และ timer ในการรันงานเบื้องหลังทุกๆ 1 นาที:

### ไฟล์ Service: `/etc/systemd/system/ticketsolve-scheduler.service`
```ini
[Unit]
Description=Process TicketSolve automatic schedules
After=network.target postgresql.service

[Service]
Type=oneshot
User=ubuntu
Group=www-data
WorkingDirectory=/var/www/ticketSolve
Environment=TIME_ZONE=Asia/Bangkok
ExecStart=/var/www/ticketSolve/venv/bin/python manage.py process_report_schedules
ExecStart=/var/www/ticketSolve/venv/bin/python manage.py process_ticket_automations
ExecStart=/var/www/ticketSolve/venv/bin/python manage.py run_2hr_backup
```

### ไฟล์ Timer: `/etc/systemd/system/ticketsolve-scheduler.timer`
```ini
[Unit]
Description=Run TicketSolve email schedule processor every minute

[Timer]
OnCalendar=*:0/1
Persistent=true

[Install]
WantedBy=timers.target
```

### คำสั่งตรวจสอบสถานะ Scheduler:
```bash
sudo systemctl status ticketsolve-scheduler.timer
sudo systemctl status ticketsolve-scheduler.service
```
