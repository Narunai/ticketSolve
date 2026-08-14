# 🚀 คู่มือการติดตั้งและสำรองข้อมูล (Deployment & Backup Guide)

เอกสารฉบับนี้อธิบายขั้นตอนการติดตั้งระบบ **TicketSolve** บน AWS Lightsail รวมถึงการตั้งค่า Nginx, Gunicorn, Systemd Timer และ Local VPS Backup

**อัปเดตล่าสุด**: 14 สิงหาคม 2026

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

### 3.1 ⏱️ Incremental Backup (กำหนดรอบได้)
* **การทำงาน**: ดึง Ticket ที่ถูกสร้าง/แก้ไข หรือมี Comments/ไฟล์แนบใหม่ตามช่วงที่เลือก 1, 2, 4, 6, 12 หรือ 24 ชั่วโมง (ค่าเริ่มต้น 2 ชั่วโมง)
* **ไฟล์ที่สร้าง**: `incremental_backup_YYYY-MM-DD_HH-MM-SS.zip` (ประกอบด้วย `tickets.json` และโฟลเดอร์ `attachments/`)
* **ที่จัดเก็บ**: `/var/backups/ticketsolve` บน AWS VPS
* **Retention**: ลบ archive ที่เก่ากว่า `BACKUP_RETENTION_DAYS` (ค่าเริ่มต้น 30 วัน)

### 3.2 📦 Full System Backup (สำรองข้อมูลทั้งระบบ)
* **การทำงาน**: สำรอง Django database ตาม engine (PostgreSQL export หรือ SQLite Online Backup), `media/` และ transaction-consistent snapshot ของ `/var/lib/ticketsolve-chatbot/chatbot.db`
* **ไฟล์ที่สร้าง**: `full_backup_YYYY-MM-DD_HH-MM-SS.tar.gz`
* **Secrets**: ไม่รวม `/etc/ticketsolve/ticketsolve.env` ใน archive ต้องสำรอง secrets แยกต่างหาก
* **ตารางเวลา**: เลือกได้ทุก 1, 3, 7, 14 หรือ 30 วัน (ค่าเริ่มต้น 1 วัน) และเปิด/ปิดงานอัตโนมัติได้

### 3.3 🧩 System Data Backup (ไม่รวม Ticket)
* **การทำงาน**: PostgreSQL export จะ exclude ticket models; SQLite ใช้ Online Backup แล้วลบ Ticket ในสำเนาเท่านั้น ฐานข้อมูลจริงไม่ถูกแก้ไข
* **ข้อมูลที่คงไว้**: Users, Companies, roles, SMTP/IMAP, Email-to-Ticket configuration, routing, schedules, categories, ข้อมูลระบบอื่น และ Chatbot config/knowledge/admin audit
* **ไฟล์ที่สร้าง**: `system_data_no_tickets_YYYY-MM-DD_HH-MM-SS.tar.gz` ภายในมี `system_data.json` หรือ `db.sqlite3`, `chatbot/chatbot.db` (ถ้าติดตั้ง) และ `backup_manifest.json`
* **ข้อมูลที่ไม่รวม**: Ticket rows, ข้อมูลลูกที่ถูก cascade, `media/` และ `/etc/ticketsolve/ticketsolve.env`
* **ตารางเวลา**: เลือกได้ทุก 1, 3, 7, 14 หรือ 30 วัน (ค่าเริ่มต้น 7 วัน) และเปิด/ปิดงานอัตโนมัติได้
* **สั่งจากหน้าเว็บ**: ปุ่ม Manual ของทั้งสามประเภทสร้าง backup ทันทีได้โดยไม่เปลี่ยน timer อัตโนมัติ; Incremental Manual ใช้ look-back window ตาม timer ที่ตั้ง

### 3.4 ⏲️ Backup Timer และข้อจำกัดด้านความปลอดภัย
* Systemd ตรวจงานทุกนาที แต่คำสั่งจะทำงานเฉพาะเมื่อครบ interval ในฐานข้อมูล
* การแก้ timer จำกัดเฉพาะ `SYSTEM_ADMIN`/Django superuser ผ่าน `POST` + CSRF; `SYSTEM_SUB_ADMIN` ดูสถานะและรอบถัดไปได้แบบ read-only
* ค่า interval รับเฉพาะตัวเลือกที่กำหนดฝั่ง server เพื่อลดความเสี่ยงจาก Full Backup ที่ถี่เกินไป
* หากงานล่าสุดล้มเหลว ระบบรอ 30 นาทีก่อน retry เพื่อลด log flood และภาระ disk/CPU
* Backup ทั้งสามประเภทใช้ lock กลาง ป้องกันการเขียน archive พร้อมกัน และ runtime secrets ไม่ถูกนำเข้า archive

### 3.5 📥 Backup Download และ Delete
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

# 1. รัน Incremental Backup เมื่อครบ timer ที่ตั้ง
runuser -u ubuntu -g www-data --preserve-environment -- venv/bin/python manage.py run_2hr_backup

# 2. บังคับรัน Incremental ทันที โดยใช้ช่วงย้อนหลังตาม timer
runuser -u ubuntu -g www-data --preserve-environment -- venv/bin/python manage.py run_2hr_backup --force

# 3. บังคับรันทันทีและกำหนดช่วงย้อนหลังเฉพาะครั้งนี้ (เช่น 6 ชม.)
runuser -u ubuntu -g www-data --preserve-environment -- venv/bin/python manage.py run_2hr_backup --force --hours 6

# 4. รัน Full System Backup (ทั้งระบบ)
runuser -u ubuntu -g www-data --preserve-environment -- venv/bin/python manage.py run_2hr_backup --full

# 5. บังคับรัน Full Backup แม้ timer ยังไม่ครบหรือถูกปิด
runuser -u ubuntu -g www-data --preserve-environment -- venv/bin/python manage.py run_2hr_backup --full --force

# 6. รัน System Data Backup เมื่อครบ timer ที่ตั้ง
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

สคริปต์ deploy จะ **ไม่สร้างหรือแทนที่ `FIELD_ENCRYPTION_KEYS`** หากไม่มีค่าจะหยุดแบบ fail-closed
key นี้ใช้ถอดรหัส SMTP/IMAP password ในฐานข้อมูล จึงต้อง provision/สำรองไว้ใน secret manager ที่ได้รับอนุมัติ
และห้ามรวมใน Git หรือ backup archive หาก key สูญหายจะไม่สามารถกู้ credential ที่เข้ารหัสไว้ได้
ก่อน deploy สคริปต์จะสร้างสำเนา environment แบบ root-only (`0600`); หากไม่มี
`FIELD_ENCRYPTION_KEYS` จะหยุดทันทีเพื่อไม่ให้ encrypted data สูญหาย

Chatbot ใช้ Fernet key แยกจาก Django secrets ที่ `/etc/ticketsolve-chatbot/fernet.key` และ runtime DB ที่
`/var/lib/ticketsolve-chatbot/chatbot.db` สคริปต์จะ migrate legacy files โดยรักษา key เดิม,
สร้าง dedicated user และตรวจว่า Nginx มี `auth_request` module ห้ามลบ/สร้าง key ใหม่เมื่อ DB เดิมยังใช้งาน

* Nginx ให้บริการเฉพาะ `/static/`; `/media/` ตอบ `404`
* Ticket และ Comment attachments ต้องดาวน์โหลดผ่าน authenticated Django endpoints ซึ่งตรวจ tenant/Ticket visibility ก่อนทุกครั้ง
* Chatbot `/api/chat` ต้องมี Django session; `/chatbot-admin` และ `/api/admin/*` ต้องเป็น System Admin/Sub Admin และ admin mutation ต้อง same-origin
* Production บังคับ HTTPS, secure session/CSRF cookies, HSTS, `X-Content-Type-Options: nosniff` และ referrer policy
* Login ถูกจำกัดทั้ง Nginx และ application, logout ใช้ POST + CSRF, password hash ใหม่ใช้ Argon2
* SMTP/IMAP password เข้ารหัสในฐานข้อมูล และ Security events แสดงในหน้า Logs
* ไฟล์แนบตรวจ allowlist และ file signature ทุกช่องทาง รวม Email → Ticket
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
สถานะ, จำนวน mailbox และอีเมลที่ found/pending/imported/skipped/duplicate/failed,
ระยะเวลา และรายละเอียด error
พร้อมตารางรายละเอียดอีเมล 100 รายการล่าสุดที่แสดง mailbox, ผู้ส่ง, subject,
Message-ID, ผล Pending/Imported/Rejected/Skipped/Failed, Ticket ที่สร้าง และเหตุผลของผลลัพธ์
โดย Approval queue, Email import details, execution log และ Email contacts อยู่ใน container เดียวกันและสลับดูผ่านแท็บ

อีเมลที่ผ่าน keyword filter จะถูกเก็บเป็น **Pending approval** ก่อน จึงยังไม่ปรากฏ
ใน Dashboard, รายงาน หรือ Ticket list จนกว่า System Admin จะกด Approve การกด Reject
จะบันทึกผู้ตัดสินใจ/เหตุผลและลบ staged attachment ส่วนการ Approve จะสร้าง Ticket
พร้อม routing ปัจจุบันและย้ายไฟล์แนบเข้า authenticated Ticket attachment สมุดรายชื่อผู้ส่ง
จะอัปเดตอัตโนมัติจาก Message-ID ใหม่แยกตาม mailbox

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

---

## 8. Maintenance, Backup Import และ Restore Runbook

### 8.1 ส่วนประกอบ production

* `/var/lib/ticketsolve-restore/restore.trigger` — one-job trigger ที่ Django สร้างแบบ exclusive
* `/run/ticketsolve/restore-in-progress` — hard-maintenance sentinel
* `/var/log/ticketsolve/restore/<job-id>.jsonl` — restore log ภายนอกฐานข้อมูล
* `ticketsolve-restore.path` — เฝ้า trigger และเรียก root-owned service
* `ticketsolve-restore.service` — oneshot restore unit
* `/usr/local/sbin/ticketsolve-restore-worker` — หยุด/เริ่ม write services และคง sentinel เมื่อเกิด failure

Deployment script จะสร้าง directory/permission, ติดตั้ง PostgreSQL client (`pg_dump`/`pg_restore`), unit files, Nginx fallback page และเปิด path unit อัตโนมัติ

### 8.2 Archive ที่ Restore ได้

Complete Restore รองรับเฉพาะ **Full Backup format v2** ที่มี signed manifest, SHA-256, database magic, payload checksums และ signed media index และต้องใช้ database engine กับ `FIELD_ENCRYPTION_KEYS` fingerprint เดียวกับ runtime ปัจจุบัน System Data, Incremental และ legacy archive ยังคงเก็บ/ดาวน์โหลดได้แต่ Restore แบบทั้งระบบไม่ได้

Runtime secrets และ `/etc/ticketsolve/ticketsolve.env` ไม่อยู่ใน archive ผู้ปฏิบัติงานต้องเก็บ `FIELD_ENCRYPTION_KEYS` และ `BACKUP_MANIFEST_SIGNING_KEY` เดิมแยกต่างหาก มิฉะนั้นระบบจะตรวจลายเซ็น archive หรือถอดข้อมูล SMTP/IMAP ที่เข้ารหัสไม่ได้

### 8.3 ลำดับ Restore ผ่านหน้าเว็บ

1. System Admin ตรวจว่า Full Backup มีสถานะ Validated/Restore supported และมี off-host copy
2. เปิด Maintenance Mode ตั้งรหัสทดสอบอย่างน้อย 10 ตัวอักษร และแจ้งผู้ใช้
3. เปิด Restore ของ archive ที่เลือก แล้วยืนยัน current account password, maintenance code และ `RESTORE <backup-id>`
4. Worker หยุด Gunicorn/chatbot/scheduler/email worker สร้าง protected rollback backup และตรวจ archive ซ้ำ
5. Worker กู้ database/media/chatbot, migrate, `check` และ smoke test จากนั้นเริ่ม service โดยยังคง application Maintenance Mode
6. System Admin ตรวจ login, tenant scope, Ticket count, attachment, SMTP configuration และ background-service status แล้วพิมพ์ `OPEN SYSTEM`

### 8.4 Failure และ operator recovery

ถ้า restore หรือ automatic rollback ไม่สามารถยืนยันความปลอดภัยได้ worker จะไม่ลบ hard sentinel และจะไม่เปิด write services เอง ห้ามลบ sentinel เพื่อ bypass ให้ตรวจ:

```bash
sudo systemctl status ticketsolve-restore.service --no-pager
sudo journalctl -u ticketsolve-restore.service --no-pager -n 200
sudo tail -200 /var/log/ticketsolve/restore/<job-id>.jsonl
sudo systemctl status gunicorn ticket-chatbot ticketsolve-scheduler.timer ticketsolve-email-to-ticket.timer --no-pager
```

หลังตรวจและกู้/rollback สำเร็จโดยผู้ปฏิบัติงานที่ได้รับอนุมัติเท่านั้น จึงเริ่ม services และลบ `/run/ticketsolve/restore-in-progress` การ Restore จริงต้องอยู่ใน approved maintenance window ส่วน regression/restore drill ให้ใช้ isolated copy เท่านั้น

### 8.5 Import limits

| Environment variable | Default | Purpose |
|---|---:|---|
| `BACKUP_IMPORT_MAX_BYTES` | 536870912 | ขนาด archive นำเข้าสูงสุด 512 MB |
| `BACKUP_CHUNK_MAX_BYTES` | 8388608 | chunk สูงสุด 8 MB |
| `BACKUP_MAX_EXPANDED_BYTES` | 4294967296 | expanded content สูงสุด 4 GiB |
| `BACKUP_MAX_MEMBERS` | 50000 | จำนวน archive entries สูงสุด |
| `BACKUP_MAX_COMPRESSION_RATIO` | 200 | ป้องกัน archive bomb |
| `BACKUP_MEDIA_INDEX_MAX_BYTES` | 8388608 | signed media index สูงสุด 8 MB |
