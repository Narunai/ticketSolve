from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from tickets.models import Company, Ticket

User = get_user_model()

class Command(BaseCommand):
    help = "Seed mock data for Companies, Users and Tickets to simplify verification."

    def handle(self, *args, **options):
        self.stdout.write("Seeding data...")

        # 1. Clear old data
        Ticket.objects.all().delete()
        User.objects.all().delete()
        Company.objects.all().delete()

        # 2. Create Companies
        company_a = Company.objects.create(name="บริษัท เอ จำกัด (Company A)")
        company_b = Company.objects.create(name="บริษัท บี จำกัด (Company B)")
        self.stdout.write(self.style.SUCCESS("Created Companies A and B."))

        # 3. Create Users
        # System Admin
        sys_admin = User.objects.create_superuser(
            username="system_admin",
            email="narunaithaisenee@gmail.com",
            password="password123"
        )
        sys_admin.role = User.SYSTEM_ADMIN
        sys_admin.save()

        # Company A Users
        admin_a = User.objects.create_user(
            username="admin_a",
            email="narunaithaisenee@gmail.com",
            password="password123",
            role=User.CLIENT_ADMIN,
            company=company_a,
            is_staff=True
        )
        user_a = User.objects.create_user(
            username="user_a",
            email="191aum@gmail.com",
            password="password123",
            role=User.CLIENT_USER,
            company=company_a
        )

        # Company B Users
        admin_b = User.objects.create_user(
            username="admin_b",
            email="admin_b@company-b.com",
            password="password123",
            role=User.CLIENT_ADMIN,
            company=company_b,
            is_staff=True
        )
        user_b = User.objects.create_user(
            username="user_b",
            email="user_b@company-b.com",
            password="password123",
            role=User.CLIENT_USER,
            company=company_b
        )
        self.stdout.write(self.style.SUCCESS("Created Users (system_admin, admin_a, user_a, admin_b, user_b). Password is 'password123' for all."))

        # 4. Create Tickets
        # Company A
        Ticket.objects.create(
            title="ระบบคลังสินค้าไม่สามารถตัดยอดได้ (Stock Discrepancy)",
            description="เกิดข้อผิดพลาดไม่พบรายการสินค้าเมื่อทำการกดปุ่มยืนยันตัดยอดในขั้นตอนสุดท้าย รหัสข้อผิดพลาด ERR-302",
            priority=Ticket.PRIORITY_HIGH,
            status=Ticket.STATUS_OPEN,
            company=company_a,
            created_by=user_a
        )
        Ticket.objects.create(
            title="ขอเพิ่มสิทธิ์ผู้ใช้งานใหม่ 3 อัตรา",
            description="ขออนุมัติเพิ่มสิทธิ์การใช้งานของพนักงานจัดส่งสินค้า 3 ท่าน เพื่อเตรียมความพร้อมสำหรับงานเทศกาลลดราคาประจำไตรมาส",
            priority=Ticket.PRIORITY_LOW,
            status=Ticket.STATUS_RESOLVED,
            company=company_a,
            created_by=user_a,
            assigned_to=admin_a
        )

        # Company B
        Ticket.objects.create(
            title="เครือข่ายอินเทอร์เน็ตใช้งานไม่ได้ชั่วคราว (Network Downtime)",
            description="สายสัญญาณฝั่งห้องเซิร์ฟเวอร์หลุดขาดชั่วคราว ทำให้เจ้าหน้าที่ไม่สามารถเข้าใช้งานระบบคลาวด์ได้",
            priority=Ticket.PRIORITY_HIGH,
            status=Ticket.STATUS_IN_PROGRESS,
            company=company_b,
            created_by=user_b,
            assigned_to=admin_b
        )
        self.stdout.write(self.style.SUCCESS("Created 3 Tickets across Company A and B."))
        self.stdout.write(self.style.SUCCESS("Seeding completed successfully!"))
