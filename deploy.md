# 🚀 คู่มือการตั้งค่า Cloudflare DNS & AWS Lightsail สำหรับ TicketSolve

ยินดีด้วยครับที่คุณเลือกใช้ **AWS Lightsail** ซึ่งเป็นบริการคลาวด์ VPS ที่มีประสิทธิภาพและควบคุมงบประมาณได้ง่ายจาก Amazon Web Services! 

เอกสารฉบับนี้คือคู่มือการสร้างและติดตั้งระบบ TicketSolve บน AWS Lightsail ร่วมกับโดเมน **`ticketsolve-systemoneit.uk`** ที่จัดการผ่าน Cloudflare

---

## 📌 สรุปขั้นตอนภาพรวม (Deployment Pipeline)

```mermaid
graph TD
    A[สร้าง Ubuntu 22.04 ใน AWS Lightsail] --> B[ผูก Static IP ใน Lightsail]
    B --> C[เปิด Port 80/443 ใน Lightsail Firewall]
    C --> D[ชี้ A Record ใน Cloudflare DNS]
    D --> E[ตั้งค่า SSL/TLS ใน Cloudflare เป็น Full]
    E --> F[SSH เข้า VPS และรัน deploy.sh]
    F --> G[ตั้งค่า .env และรัน Migrate / Certbot SSL]
```

---

## 🛠️ ขั้นตอนที่ 1: การตั้งค่าบน AWS Lightsail (VPS Configuration)

### 1. การสร้าง Instance บน AWS Lightsail
1. ล็อกอินเข้าสู่หน้าเว็บ [AWS Management Console](https://aws.amazon.com/) และค้นหาบริการ **Lightsail**
2. กดปุ่ม **"Create instance"**
3. **Select instance location**: แนะนำให้เลือกภูมิภาค **Singapore (ap-southeast-1)** ซึ่งเป็นดาต้าเซ็นเตอร์ที่อยู่ใกล้ประเทศไทยและมีความเร็วตอบสนองสูงที่สุด
4. **Select platform**: เลือก **Linux/Unix**
5. **Select blueprint**: ให้เลือก **OS Only** แล้วกดเลือก **Ubuntu 22.04 LTS** (หรือ Ubuntu 24.04 LTS)
6. **Choose your instance plan**: เลือกแพ็คเกจราคา **$10 USD / เดือน** 
   *(สเปค: 2 vCPUs, 2 GB RAM, 60 GB SSD, และปริมาณโอนถ่ายข้อมูล 3 TB)*
7. **Identify your instance**: ตั้งชื่อให้เซิร์ฟเวอร์ (เช่น `ticketsolve-prod`)
8. กดปุ่ม **"Create instance"** และรอประมาณ 1-2 นาทีให้เครื่องเปิดระบบสำเร็จ

### 2. การสร้างและผูก Static IP (สำคัญมาก)
*โดยปกติหากเซิร์ฟเวอร์โดนรีสตาร์ท AWS จะเปลี่ยน IP สาธารณะใหม่ทันที การผูก Static IP จะล็อกไม่ให้ IP ของเซิร์ฟเวอร์เปลี่ยนตลอดไป*
1. ไปที่แท็บ **Networking** ในหน้าหลักของ Lightsail
2. คลิกปุ่ม **"Create static IP"**
3. เลือกผูก (Attach) เข้ากับ Instance `ticketsolve-prod` ที่เพิ่งสร้างขึ้นมา
4. ตั้งชื่อ Static IP จากนั้นคลิก **Create**
5. คัดลอกหมายเลข IP Address ที่ได้มา (เช่น `54.254.123.45`) เพื่อใช้ในขั้นตอน DNS ถัดไป

### 3. การเปิดพอร์ตบน Firewall (IPv4 Firewall Rules)
*โดยปกติ AWS จะปิดพอร์ตเว็บไว้ทั้งหมด ยกเว้นพอร์ต SSH (22) เราจำเป็นต้องเปิดพอร์ตเพื่อให้ผู้ใช้เข้าถึงเว็บได้*
1. คลิกเข้าไปที่ชื่อ Instance `ticketsolve-prod` แล้วไปที่แท็บ **Networking**
2. เลื่อนลงมาที่หัวข้อ **IPv4 Firewall**
3. กดปุ่ม **"Add rule"** เพื่อเปิดพอร์ตดังนี้:
   * **Rule 1**: เลือก Application: `HTTP` (พอร์ต `80`)
   * **Rule 2**: เลือก Application: `HTTPS` (พอร์ต `443`)
4. กด **Save** ทุกครั้งหลังจากเพิ่มกฎเสร็จสิ้น

---

## 🌐 ขั้นตอนที่ 2: การตั้งค่า DNS บน Cloudflare

1. ล็อกอินเข้าบัญชี Cloudflare ของคุณ และคลิกเลือกโดเมน **`ticketsolve-systemoneit.uk`**
2. ไปที่เมนู **DNS** -> **Records** ทางด้านซ้ายมือ
3. กดปุ่ม **"Add record"** เพื่อป้อนค่าชี้โดเมนหลักไปยัง VPS:
   * **Type**: `A`
   * **Name**: `@` (แทนโดเมนหลัก `ticketsolve-systemoneit.uk`) หรือพิมพ์คำว่า `ticket` (หากต้องการซับโดเมน `ticket.ticketsolve-systemoneit.uk`)
   * **IPv4 address**: ป้อนหมายเลข Static IP ที่ได้มาจาก AWS Lightsail ในข้อก่อนหน้า
   * **Proxy status**: **เปิดใช้งาน (Proxied - ไอคอนก้อนเมฆสีส้ม)** เพื่อรับการปกป้องและเร่งความเร็วจาก Cloudflare
   * **TTL**: `Auto`
4. กด **Save**
5. ไปที่เมนู **SSL/TLS** -> **Overview** แล้วตั้งค่าระดับการเข้ารหัสให้เป็น **Full** (เพื่อให้ทราฟฟิกข้อมูลระหว่าง Cloudflare และ Nginx VPS เข้ารหัสอย่างปลอดภัย)

---

## 🖥️ ขั้นตอนที่ 3: การโคลนโค้ดและติดตั้งระบบบนเซิร์ฟเวอร์จริง (VPS Server Installation)

1. ดาวน์โหลดไฟล์คีย์ความปลอดภัย SSH (ไฟล์ `.pem`) จากหน้าตั้งค่าบัญชี AWS Lightsail หรือใช้ปุ่มเบราว์เซอร์ **"Connect using SSH"** ของ AWS โดยตรงเพื่อเปิดหน้าจอ Command Line
2. นำซอร์สโค้ดโปรเจกต์ของคุณไปวางไว้ที่โฟลเดอร์ `/var/www/ticketSolve` ใน VPS
3. เปลี่ยนสิทธิ์การรันสคริปต์อัตโนมัติ และเริ่มสั่งติดตั้ง:
   ```bash
   cd /var/www/ticketSolve
   chmod +x deployment/deploy.sh
   ./deployment/deploy.sh
   ```
   *สคริปต์อัตโนมัติจะทำการลงโปรแกรม Nginx, Postgres, สร้าง Virtual Environment และตั้งค่าไฟล์ systemd service daemon ให้อัตโนมัติทันที*

4. สร้างไฟล์ตั้งค่าระบบ `.env` ภายในโฟลเดอร์ `/var/www/ticketSolve` เพื่อเก็บข้อมูลรหัสผ่าน:
   ```bash
   nano .env
   ```
   *ป้อนค่าที่ต้องการ เช่น:*
   ```ini
   DEBUG=False
   SECRET_KEY=สุ่มข้อความยาวๆความปลอดภัยสูง
   ALLOWED_HOSTS=ticketsolve-systemoneit.uk,54.254.123.45  # ใส่โดเมนและ IP ของคุณ
   DATABASE_URL=postgres://ticketuser:รหัสผ่านที่คุณตั้ง@localhost:5432/ticketsolve
   ```

5. เปิดใช้งาน Environment และรันคำสั่ง Migration ฐานข้อมูล:
   ```bash
   source venv/bin/activate
   python manage.py migrate
   python manage.py createsuperuser  # สร้างไอดีแอดมินคนแรก
   ```

6. ดำเนินการติดตั้ง SSL Certificate บน VPS ด้วย Certbot:
   ```bash
   sudo certbot --nginx -d ticketsolve-systemoneit.uk
   ```
   *(ทำตามขั้นตอนบนหน้าจอโดยป้อนอีเมลของคุณ และตอบ Y ยอมรับเงื่อนไข เพื่อให้ระบบ Nginx รันบนช่องทางปลอดภัย HTTPS สมบูรณ์แบบ)*

---

## 🌟 บริการย่อยอื่นๆ ของ Cloudflare ที่แนะนำ
* **WAF (Web Application Firewall)**: ช่วยสกัดบล็อกความพยายามเข้าใช้หน้าจัดการของแฮกเกอร์ หรือบล็อกบอทสแกนช่องโหว่ได้อัตโนมัติโดยไม่เปลืองแรงประมวลผลของ VPS
* **Always Online**: ทำหน้าที่แคชหน้าเพจบางส่วนเพื่อคงการแสดงผลไว้หาก VPS ของคุณต้องหยุดทำงานเพื่ออัปเดตระบบชั่วคราว
