# 🚀 คู่มือการติดตั้งและสำรองข้อมูล (Deployment & Backup Guide)

เอกสารฉบับนี้อธิบายขั้นตอนการติดตั้งระบบ **TicketSolve** บน AWS Lightsail รวมถึงการตั้งค่า Nginx, Gunicorn, Systemd Timer และ Local VPS Backup

**อัปเดตล่าสุด**: 2 สิงหาคม 2026

---

## ☁️ 1. รายละเอียดเซิร์ฟเวอร์ Production (Live Environment)

* **Domain**: `https://tikketsolve-systemoneit.uk`
* **Server IP**: `3.1.52.201` (AWS Lightsail / ap-southeast-1)
* **OS**: Ubuntu 24.04 LTS
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
git status --short
git pull --ff-only origin main

# activate virtual environment
source venv/bin/activate
pip install -r requirements.txt
```

### 2.2 รัน Database Migrations & Collect Static
```bash
sudo bash deployment/deploy.sh
```

Production secrets อยู่ที่ `/etc/ticketsolve/ticketsolve.env` (สิทธิ์ `0640`,
เจ้าของ `root:www-data`) และเป็นแหล่งค่าหลักของ Gunicorn/Scheduler โดยต้องไม่ commit
ไฟล์นี้หรือ private key เข้า Git สคริปต์จะสร้าง `SECRET_KEY` แบบสุ่มเมื่อไม่พบค่า
หรือเมื่อพบค่าเดิมที่สั้น/ขึ้นต้นด้วย `django-insecure-`

หากเป็นการย้ายระบบจากเวอร์ชันเก่า สคริปต์จะใช้ `.env` ใน checkout เป็นข้อมูลตั้งต้น
เพียงครั้งแรก หลังตรวจว่า `/etc/ticketsolve/ticketsolve.env` มีค่าครบแล้วควรนำ legacy
`.env` ออกจาก checkout

### 2.3 รีสตาร์ทบริการ Nginx & Gunicorn
```bash
sudo systemctl daemon-reload
sudo systemctl restart gunicorn
sudo systemctl restart nginx
```

---

## 💾 3. โครงสร้างและการทำงานของระบบสำรองข้อมูล (Backup System)

ระบบสำรองข้อมูลใน TicketSolve แบ่งออกเป็น 3 ประเภทหลัก:

### 3.1 ⏱️ 2-Hour Incremental Backup (สำรองข้อมูล 2 ชั่วโมงย้อนหลัง)
* **การทำงาน**: ดึง Ticket ที่ถูกสร้าง/แก้ไข หรือมี Comments/ไฟล์แนบใหม่ใน 2 ชั่วโมงย้อนหลัง
* **ไฟล์ที่สร้าง**: `incremental_backup_YYYY-MM-DD_HH-MM-SS.zip` (ประกอบด้วย `tickets.json` และโฟลเดอร์ `attachments/`)
* **ที่จัดเก็บ**: `/var/backups/ticketsolve` บน AWS VPS
* **Retention**: ลบ archive ที่เก่ากว่า `BACKUP_RETENTION_DAYS` (ค่าเริ่มต้น 30 วัน)

### 3.2 📦 Full System Backup (สำรองข้อมูลทั้งระบบ)
* **การทำงาน**: สำรองฐานข้อมูลผ่าน SQLite Online Backup API แล้วบีบอัดร่วมกับ `media/`
* **ไฟล์ที่สร้าง**: `full_backup_YYYY-MM-DD_HH-MM-SS.tar.gz`
* **Secrets**: ไม่รวม `/etc/ticketsolve/ticketsolve.env` ใน archive ต้องสำรอง secrets แยกต่างหาก
* **ตารางเวลา**: Scheduler เรียกคำสั่งทุกนาที แต่ระบบสร้าง Full Backup สำเร็จไม่เกินวันละหนึ่งครั้ง เว้นแต่ใช้ `--force`

### 3.3 🧩 7-Day System Data Backup (ไม่รวม Ticket)
* **การทำงาน**: ใช้ SQLite Online Backup API สร้างสำเนาฐานข้อมูล จากนั้นลบ Ticket ในสำเนาเท่านั้น โดยให้ foreign-key `CASCADE`/`SET_NULL` จัดการข้อมูลที่สัมพันธ์กัน ฐานข้อมูลจริงไม่ถูกแก้ไข
* **ข้อมูลที่คงไว้**: Users, Companies, roles, SMTP/IMAP, Email-to-Ticket configuration, routing, schedules, categories และข้อมูลระบบอื่น
* **ไฟล์ที่สร้าง**: `system_data_no_tickets_YYYY-MM-DD_HH-MM-SS.tar.gz` ภายในมี `db.sqlite3` และ `backup_manifest.json`
* **ข้อมูลที่ไม่รวม**: Ticket rows, ข้อมูลลูกที่ถูก cascade, `media/` และ `/etc/ticketsolve/ticketsolve.env`
* **ตารางเวลา**: `run_weekly_system_backup` ตรวจทุกนาทีผ่าน scheduler แต่สร้างสำเร็จไม่เกินหนึ่งครั้งในทุก 7 วัน เว้นแต่ใช้ `--force`

### 3.4 📥 Backup Download และ Delete
* **การใช้งาน**: สามารถดาวน์โหลดไฟล์ Backup (`.zip` หรือ `.tar.gz`) มาตรวจสอบและดูข้อมูลบนเครื่องของคุณได้ทันทีผ่านปุ่ม **📥 Download** ในหน้าจอ Backup Management (`/backups/`)
* **Authorization**: ดาวน์โหลดและลบได้เฉพาะ System Staff ที่ยืนยันตัวตนแล้ว
* **Empty/Missing Archive**: รายการขนาด 0 หรือ archive ที่ไม่มีอยู่จะแสดง **No data file** โดยซ่อน Download และแสดงปุ่ม **Delete empty record**; ปุ่ม **Delete all 0 MB** ลบรายการ 0 MB ทั้งหมดในครั้งเดียว และจะไม่ลบไฟล์จริงหากตรวจพบว่าขนาดบนดิสก์มากกว่า 0
* **Delete Behavior**: การลบใช้ `POST` + CSRF; ถ้ามี archive จะลบทั้งไฟล์และ `BackupLog` แต่หากลบไฟล์ไม่ได้ ระบบจะคง log ไว้และแจ้งข้อผิดพลาด

> Backup ชุดนี้อยู่บน VPS เครื่องเดียวกับแอป จึงช่วยกู้คืนจากความเสียหายระดับไฟล์/ฐานข้อมูล แต่ไม่ใช่ off-site backup หากต้องการป้องกันกรณี VPS หรือดิสก์สูญหายทั้งเครื่อง ต้องทำสำเนา archive ไปยัง storage คนละระบบเพิ่มเติม

---

## ⚙️ 4. คำสั่งจัดการ Backup (Management Commands)

ใน local development สามารถใช้ `python manage.py ...` โดยตรงได้ ส่วน production
ต้องโหลด environment file ที่ป้องกันด้วย permission และรัน archive ในชื่อ
`ubuntu:www-data` เพื่อให้แอปดาวน์โหลด/ลบไฟล์ภายหลังได้:

```bash
sudo bash
set -a
source /etc/ticketsolve/ticketsolve.env
set +a
cd /var/www/ticketSolve

# 1. รัน 2-Hour Incremental Backup (มีระบบป้องกันรันซ้ำซ้อนหากเพิ่งรันไปภายใน 2 ชม.)
runuser -u ubuntu -g www-data --preserve-environment -- venv/bin/python manage.py run_2hr_backup

# 2. บังคับรัน 2-Hour Incremental Backup ทันที (ข้ามตัวป้องกัน)
runuser -u ubuntu -g www-data --preserve-environment -- venv/bin/python manage.py run_2hr_backup --force

# 3. รัน 2-Hour Incremental Backup แบบระบุนานกว่า 2 ชม. (เช่น 6 ชม.)
runuser -u ubuntu -g www-data --preserve-environment -- venv/bin/python manage.py run_2hr_backup --hours 6

# 4. รัน Full System Backup (ทั้งระบบ)
runuser -u ubuntu -g www-data --preserve-environment -- venv/bin/python manage.py run_2hr_backup --full

# 5. บังคับรัน Full Backup แม้มี backup ภายใน 24 ชั่วโมง
runuser -u ubuntu -g www-data --preserve-environment -- venv/bin/python manage.py run_2hr_backup --full --force

# 6. รัน System Data Backup ที่ไม่มี Ticket (ระบบป้องกันการรันซ้ำภายใน 7 วัน)
runuser -u ubuntu -g www-data --preserve-environment -- venv/bin/python manage.py run_weekly_system_backup

# 7. บังคับรัน System Data Backup ทันที
runuser -u ubuntu -g www-data --preserve-environment -- venv/bin/python manage.py run_weekly_system_backup --force

exit
```

---

## ⏰ 5. การตั้งเวลาอัตโนมัติ (Systemd Scheduler Timer)

ระบบแยก timer เป็นสองชุด:

* `ticketsolve-scheduler.timer` ตรวจรายงาน, Ticket automation และ backup ทุก 1 นาที
* `ticketsolve-email-to-ticket.timer` ปลุกตัวประมวลผลทุก 10 นาที และตัวประมวลผล
  ตรวจ interval จากฐานข้อมูลก่อนสแกนจริง

### ไฟล์ Service: `/etc/systemd/system/ticketsolve-scheduler.service`
```ini
[Unit]
Description=Process TicketSolve automatic schedules
After=network.target

[Service]
Type=oneshot
User=ubuntu
Group=www-data
WorkingDirectory=/var/www/ticketSolve
EnvironmentFile=/etc/ticketsolve/ticketsolve.env
ExecStart=-/var/www/ticketSolve/venv/bin/python manage.py process_report_schedules
ExecStart=-/var/www/ticketSolve/venv/bin/python manage.py process_ticket_automations
ExecStart=-/var/www/ticketSolve/venv/bin/python manage.py run_2hr_backup
ExecStart=/var/www/ticketSolve/venv/bin/python manage.py run_2hr_backup --full
ExecStart=/var/www/ticketSolve/venv/bin/python manage.py run_weekly_system_backup
UMask=0027
PrivateTmp=true
NoNewPrivileges=true
```

### ไฟล์ Timer: `/etc/systemd/system/ticketsolve-scheduler.timer`
```ini
[Unit]
Description=Run TicketSolve automatic task processors every minute

[Timer]
OnCalendar=*-*-* *:*:00
Persistent=true
AccuracySec=1s
Unit=ticketsolve-scheduler.service

[Install]
WantedBy=timers.target
```

### Email → Ticket Service และ Timer

ไฟล์ `/etc/systemd/system/ticketsolve-email-to-ticket.service`:

```ini
[Unit]
Description=Import TicketSolve tickets from unread email
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=ubuntu
Group=www-data
WorkingDirectory=/var/www/ticketSolve
EnvironmentFile=/etc/ticketsolve/ticketsolve.env
UMask=0027
ExecStart=/var/www/ticketSolve/venv/bin/python manage.py process_email_to_tickets
PrivateTmp=true
NoNewPrivileges=true
```

ไฟล์ `/etc/systemd/system/ticketsolve-email-to-ticket.timer`:

```ini
[Unit]
Description=Check the TicketSolve email scan schedule every 10 minutes

[Timer]
OnCalendar=*-*-* *:0/10:00
Persistent=true
AccuracySec=1s
Unit=ticketsolve-email-to-ticket.service

[Install]
WantedBy=timers.target
```

### คำสั่งตรวจสอบสถานะ Scheduler:
```bash
sudo systemctl status ticketsolve-scheduler.timer
sudo systemctl status ticketsolve-scheduler.service
sudo systemctl status ticketsolve-email-to-ticket.timer
sudo systemctl status ticketsolve-email-to-ticket.service
sudo systemctl list-timers ticketsolve-email-to-ticket.timer
```

---

## 🔐 6. Production Security และไฟล์แนบ

* Nginx ให้บริการเฉพาะ `/static/`; `/media/` ตอบ `404`
* Ticket และ Comment attachments ต้องดาวน์โหลดผ่าน authenticated Django endpoints ซึ่งตรวจ tenant/Ticket visibility ก่อนทุกครั้ง
* Production บังคับ HTTPS, secure session/CSRF cookies, HSTS, `X-Content-Type-Options: nosniff` และ referrer policy
* เปิด HSTS preload เฉพาะเมื่อยืนยันว่าจะคง HTTPS สำหรับโดเมนและทุก subdomain ระยะยาว เพราะการ preload ย้อนกลับได้ช้า

คำสั่งตรวจหลัง deploy:

```bash
sudo nginx -t
sudo systemctl is-active gunicorn nginx ticketsolve-scheduler.timer ticketsolve-email-to-ticket.timer

sudo bash -c '
  set -a
  source /etc/ticketsolve/ticketsolve.env
  set +a
  cd /var/www/ticketSolve
  venv/bin/python manage.py check --deploy
  venv/bin/python manage.py showmigrations tickets
'
```

---

## 📥 7. Email → Ticket

หน้า `/settings/` ให้ System Admin กำหนดการใช้งานบัญชีแต่ละรายการ:

* **Send system email**: ใช้ SMTP ส่ง notification/report
* **Email to Ticket import**: ใช้ username/app password อ่าน IMAP SSL
* **Send email and Email to Ticket**: ใช้บัญชีเดียวกันทั้งสองทาง

ระบบอนุญาต active configuration หนึ่งรายการต่อ feature จึงเปิด outbound และ inbound
คนละบัญชีพร้อมกันได้ สำหรับ inbound ต้องกำหนด IMAP host/port/folder, target company,
ticket creator และ optional assignee

timer จะปลุกตัวประมวลผลตามนาที `00, 10, 20, 30, 40, 50` ของทุกชั่วโมง
ตัวประมวลผลจะอ่านค่าจากหน้า **Email Timer** แล้วสแกนเมื่อครบ 10, 20, 30 นาที
(ครึ่งชั่วโมง) หรือ 1 ชั่วโมง หากยังไม่ครบ interval จะจบโดยไม่สร้าง run log
`Persistent=true` จะสั่งทำรอบที่พลาดหลังเครื่องกลับมาทำงาน ส่วนปุ่ม **Scan now**,
**Import Now** และคำสั่ง `--force` จะเรียกทันทีโดยไม่ต้องรอรอบถัดไป

หน้า Email Timer แสดง execution log 50 รอบล่าสุด โดยเก็บ trigger/ผู้สั่งรัน,
สถานะ, จำนวน mailbox และอีเมลที่ found/imported/skipped/duplicate/failed,
ระยะเวลา และรายละเอียด error
พร้อมตารางรายละเอียดอีเมล 100 รายการล่าสุดที่แสดง mailbox, ผู้ส่ง, subject,
Message-ID, ผล Imported/Skipped/Failed, Ticket ที่สร้าง และเหตุผลของผลลัพธ์

ส่วน **Sender → Assignee routing** ใช้จับคู่อีเมลผู้ส่งกับผู้ดูแล Ticket ได้ทุกบริษัท
เมื่อเลือกผู้ดูแลต่างจาก Target Company ระบบจะสร้าง Ticket ในบริษัทของผู้ดูแลและใช้
ผู้ดูแลเป็น creator เพื่อรักษา tenant isolation หากไม่พบกฎ, กฎถูกปิด หรือผู้ดูแลไม่ active
ระบบจะใช้ Company, Creator และ Default Assignee จาก SMTP configuration เดิม
Custom subject keywords จะถูกรวมกับ
คำมาตรฐานของระบบ จึงไม่ทำให้คำอย่าง `ปัญหา` หรือ `issue` หายไป

ค่ามาตรฐาน:

| Provider | SMTP | IMAP SSL |
| :--- | :--- | :--- |
| Gmail | `smtp.gmail.com:587` | `imap.gmail.com:993` |
| Outlook ที่เปิด IMAP | `smtp.office365.com:587` | `outlook.office365.com:993` |

คำสั่ง manual:

```bash
sudo bash -c '
  set -a
  source /etc/ticketsolve/ticketsolve.env
  set +a
  cd /var/www/ticketSolve
  runuser -u ubuntu -g www-data --preserve-environment -- \
    venv/bin/python manage.py process_email_to_tickets --force
'
```

การเชื่อมต่อใช้ IMAP SSL และอ่านด้วย `BODY.PEEK[]`; ระบบจะตั้ง `\Seen` หลัง import/skip
เมื่อเปิดตัวเลือก Mark as read เท่านั้น Message-ID ที่ import หรือ skip แล้วจะไม่สร้าง Ticket ซ้ำ
และประวัติ 20 รายการล่าสุดแสดงในหน้า SMTP Settings อีเมลที่หัวข้อขึ้นต้น `[TicketSolve]`
จะถูกข้ามเพื่อป้องกัน mail loop พร้อมจำกัด raw email ที่ 55 MB และเนื้อหา Ticket
ที่ 100,000 ตัวอักษร

> Microsoft 365 tenant ที่ปิด IMAP/Basic Auth ต้องเพิ่ม Microsoft Graph OAuth credentials
> ก่อนใช้งาน บัญชีดังกล่าวไม่ควรกรอกรหัสผ่านปกติเพื่อพยายาม bypass นโยบายขององค์กร
