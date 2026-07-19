import os
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core import mail
from django.core.management import call_command
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied

from .models import Company, Ticket, CustomUser, EmailLog, MonthlyReportSchedule

from .admin import CustomUserAdmin, TicketAdmin

User = get_user_model()

class MultiTenantTicketTests(TestCase):
    def setUp(self):
        # 1. Create Companies
        self.company_a = Company.objects.create(name="Company A")
        self.company_b = Company.objects.create(name="Company B")

        # 2. Create Users
        # Company A Admin
        self.admin_a = User.objects.create_user(
            username="admin_a",
            email="admin_a@company-a.com",
            password="password123",
            role=User.CLIENT_ADMIN,
            company=self.company_a,
            is_staff=True
        )
        # Company A Regular User
        self.user_a = User.objects.create_user(
            username="user_a",
            email="user_a@company-a.com",
            password="password123",
            role=User.CLIENT_USER,
            company=self.company_a
        )
        # Company B Regular User
        self.user_b = User.objects.create_user(
            username="user_b",
            email="user_b@company-b.com",
            password="password123",
            role=User.CLIENT_USER,
            company=self.company_b
        )
        
        # System Admin (No company restriction)
        self.system_admin = User.objects.create_user(
            username="system_admin",
            email="sysadmin@system.com",
            password="password123",
            role=User.SYSTEM_ADMIN,
            is_superuser=True,
            is_staff=True
        )

        # 3. Create Ticket for Company A
        self.ticket_a = Ticket.objects.create(
            title="Database Connection Issue in A",
            description="Unable to connect to production database from A",
            priority=Ticket.PRIORITY_HIGH,
            company=self.company_a,
            created_by=self.user_a
        )

    def test_ticket_creation_and_auto_email_signal(self):
        # Clear outbox
        mail.outbox = []
        
        # Create new ticket via model
        ticket = Ticket.objects.create(
            title="Billing Query",
            description="Billing details error",
            priority=Ticket.PRIORITY_LOW,
            company=self.company_a,
            created_by=self.user_a
        )
        
        # Verify custom signal triggered email sending (at least to creator and admins)
        self.assertTrue(len(mail.outbox) > 0)
        self.assertIn("Billing Query", mail.outbox[0].subject)
        all_to = [to_addr for m in mail.outbox for to_addr in m.to]
        self.assertIn(self.user_a.email, all_to)


    def test_data_isolation_regular_user_a_cannot_see_b_data(self):
        # Log in as user_b
        self.client.login(username="user_b", password="password123")
        
        # Attempt to access Ticket Detail of Company A
        response = self.client.get(reverse('ticket_detail', args=[self.ticket_a.id]))
        # Should raise PermissionDenied or return 403 depending on implementation (class view raises PermissionDenied)
        self.assertEqual(response.status_code, 403)

    def test_data_isolation_regular_user_a_can_see_own_data(self):
        # Log in as user_a
        self.client.login(username="user_a", password="password123")
        
        response = self.client.get(reverse('ticket_detail', args=[self.ticket_a.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ticket_a.title)

    def test_custom_user_list_view_filtering(self):
        # Log in as Client Admin of Company A
        self.client.login(username="admin_a", password="password123")
        
        response = self.client.get(reverse('user_list'))
        self.assertEqual(response.status_code, 200)
        
        # Should contain users from Company A, but NOT Company B
        self.assertContains(response, "user_a")
        self.assertContains(response, "admin_a")
        self.assertNotContains(response, "user_b")

    def test_custom_company_list_view_access_restriction(self):
        # Log in as Client Admin (should NOT have access to companies list)
        self.client.login(username="admin_a", password="password123")
        
        response = self.client.get(reverse('company_list'))
        # Should return 403 Forbidden because Client Admin has no access
        self.assertEqual(response.status_code, 403)
        
        # Log in as System Admin (should have access)
        self.client.login(username="system_admin", password="password123")
        response = self.client.get(reverse('company_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Company A")
        self.assertContains(response, "Company B")

    def test_updating_username_does_not_clear_password(self):
        # Log in as Client Admin of Company A
        self.client.login(username="admin_a", password="password123")

        # Edit admin_a's username to admin_a_test without providing a password
        response = self.client.post(reverse('user_update', args=[self.admin_a.id]), {
            'username': 'admin_a_test',
            'email': 'admin_a@company-a.com',
            'password': '',
            'role': CustomUser.CLIENT_ADMIN,
        })
        self.assertEqual(response.status_code, 302)

        # Refresh from DB
        self.admin_a.refresh_from_db()
        self.assertEqual(self.admin_a.username, 'admin_a_test')

        # Test logging in with new username and original password
        self.client.logout()
        login_success = self.client.login(username="admin_a_test", password="password123")
        self.assertTrue(login_success)

    def test_dashboard_status_filtering(self):
        self.client.login(username="admin_a", password="password123")
        
        # Create an OPEN ticket and a RESOLVED ticket for Company A
        Ticket.objects.create(
            title="Open Ticket Issue",
            description="Details",
            priority=Ticket.PRIORITY_LOW,
            status=Ticket.STATUS_OPEN,
            company=self.company_a,
            created_by=self.user_a
        )
        Ticket.objects.create(
            title="Resolved Ticket Issue",
            description="Details",
            priority=Ticket.PRIORITY_LOW,
            status=Ticket.STATUS_RESOLVED,
            company=self.company_a,
            created_by=self.user_a
        )

        # Filter by status=OPEN
        response = self.client.get(reverse('dashboard') + '?status=OPEN')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Open Ticket Issue")
        self.assertNotContains(response, "Resolved Ticket Issue")

    def test_monthly_report_management_command(self):
        # Clear outbox
        mail.outbox = []
        
        # Call the custom django command
        call_command('send_monthly_report')
        
        # Verify an email report was sent to company A admin (admin_a)
        self.assertTrue(len(mail.outbox) > 0)
        # Verify report content
        report_email = next((m for m in mail.outbox if self.admin_a.email in m.to), None)
        self.assertIsNotNone(report_email)
        self.assertIn("รายงานสรุปสถานะ Ticket ประจำเดือน", report_email.subject)
        self.assertIn("Company A", report_email.body)

    def test_user_welcome_email_notification(self):
        mail.outbox = []
        new_user = CustomUser.objects.create_user(
            username="new_employee",
            email="new_emp@company-a.com",
            password="password123",
            company=self.company_a,
            role=CustomUser.CLIENT_USER
        )
        # Check that welcome email was generated
        welcome_email = next((m for m in mail.outbox if "new_emp@company-a.com" in m.to), None)
        self.assertIsNotNone(welcome_email)
        self.assertIn("ข้อมูลบัญชีผู้ใช้งานใหม่ของคุณ", welcome_email.subject)
        self.assertIn("new_employee", welcome_email.body)

    def test_company_registration_email_notification(self):
        mail.outbox = []
        new_company = Company.objects.create(name="Company C")
        # Check that company registration notification was sent to system admin
        company_email = next((m for m in mail.outbox if self.system_admin.email in m.to), None)
        self.assertIsNotNone(company_email)
        self.assertIn("Company C", company_email.subject)

    def test_audit_and_email_logging_on_status_change(self):
        from .models import EmailLog, TicketAuditLog
        
        # Log in as Client Admin of Company A
        self.client.login(username="admin_a", password="password123")

        response = self.client.post(reverse('ticket_update', args=[self.ticket_a.id]), {
            'title': self.ticket_a.title,
            'description': self.ticket_a.description,
            'priority': self.ticket_a.priority,
            'status': Ticket.STATUS_IN_PROGRESS,
            'category': self.ticket_a.category,
            'assigned_to': self.admin_a.id
        })
        self.assertEqual(response.status_code, 302)

        # Check TicketAuditLog record
        audit_entry = TicketAuditLog.objects.filter(ticket=self.ticket_a, old_status=Ticket.STATUS_OPEN).first()
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry.actor, self.admin_a)
        self.assertEqual(audit_entry.new_status, Ticket.STATUS_IN_PROGRESS)

        # Check EmailLog record
        email_entry = EmailLog.objects.filter(recipient=self.user_a.email, action_type=EmailLog.ACTION_TICKET_UPDATED).first()
        self.assertIsNotNone(email_entry)
        self.assertIn("อัปเดตความคืบหน้า", email_entry.subject)

    def test_monthly_report_view_access(self):
        # Client Admin can access
        self.client.login(username="admin_a", password="password123")
        response = self.client.get(reverse('monthly_report'))
        self.assertEqual(response.status_code, 200)

        # Client User cannot access
        self.client.login(username="user_a", password="password123")
        response = self.client.get(reverse('monthly_report'))
        self.assertEqual(response.status_code, 403)

    def test_parent_subsidiary_company_hierarchy_and_clean_validation(self):
        from django.core.exceptions import ValidationError

        holding = Company.objects.create(name="Holding Group")
        subsidiary = Company.objects.create(name="Subsidiary Alpha", parent=holding)
        sub_unit = Company.objects.create(name="Sub Unit A1", parent=subsidiary)

        # Verify get_all_subsidiary_ids
        self.assertCountEqual(holding.get_all_subsidiary_ids(), [holding.id, subsidiary.id, sub_unit.id])
        self.assertCountEqual(subsidiary.get_all_subsidiary_ids(), [subsidiary.id, sub_unit.id])
        self.assertCountEqual(sub_unit.get_all_subsidiary_ids(), [sub_unit.id])

        # Verify get_full_path
        self.assertEqual(sub_unit.get_full_path(), "Holding Group > Subsidiary Alpha > Sub Unit A1")

        # Test self-parenting validation
        holding.parent = holding
        with self.assertRaises(ValidationError):
            holding.clean()

        # Test circular loop validation (subsidiary parent set to sub_unit)
        holding.parent = None
        subsidiary.parent = sub_unit
        with self.assertRaises(ValidationError):
            subsidiary.clean()

    def test_parent_company_admin_can_view_subsidiary_tickets_and_users(self):
        parent_comp = Company.objects.create(name="Parent Corp")
        child_comp = Company.objects.create(name="Child Corp", parent=parent_comp)

        parent_admin = User.objects.create_user(
            username="parent_admin",
            email="padmin@parent.com",
            password="password123",
            role=User.CLIENT_ADMIN,
            company=parent_comp,
            is_staff=True
        )

        child_user = User.objects.create_user(
            username="child_user",
            email="cuser@child.com",
            password="password123",
            role=User.CLIENT_USER,
            company=child_comp
        )

        child_ticket = Ticket.objects.create(
            title="Child Company Issue",
            description="Child details",
            company=child_comp,
            created_by=child_user
        )

        parent_ticket = Ticket.objects.create(
            title="Parent Secret Ticket",
            description="Parent details",
            company=parent_comp,
            created_by=parent_admin
        )

        # Parent Admin logs in
        self.client.login(username="parent_admin", password="password123")

        # Parent Admin can see child's ticket detail
        response = self.client.get(reverse('ticket_detail', args=[child_ticket.id]))
        self.assertEqual(response.status_code, 200)

        # Parent Admin user_list contains child_user
        response = self.client.get(reverse('user_list'))
        self.assertContains(response, "child_user")

        # Child User logs in
        self.client.login(username="child_user", password="password123")

        # Child User CANNOT see parent's ticket detail
        response = self.client.get(reverse('ticket_detail', args=[parent_ticket.id]))
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse('monthly_report'))
        self.assertEqual(response.status_code, 403)

    def test_dynamic_category_and_resolution_management(self):
        from .models import TicketCategory, ResolutionCategory
        
        self.client.login(username="admin_a", password="password123")
        
        # Access category list
        response = self.client.get(reverse('category_list'))
        self.assertEqual(response.status_code, 200)

        # Create company ticket category
        response = self.client.post(reverse('ticket_category_create'), {
            'name': 'Custom Billing Issue',
            'description': 'Billing and payment problems',
            'icon_code': 'credit-card',
            'color_code': '#ef4444',
            'is_active': True
        })
        self.assertEqual(response.status_code, 302)

        created_cat = TicketCategory.objects.filter(name='Custom Billing Issue').first()
        self.assertIsNotNone(created_cat)
        self.assertEqual(created_cat.company, self.company_a)

        # Create resolution category
        response = self.client.post(reverse('resolution_category_create'), {
            'name': 'Account Reset Completed',
            'description': 'Reset user account credentials',
            'is_active': True
        })
        self.assertEqual(response.status_code, 302)
        res_cat = ResolutionCategory.objects.filter(name='Account Reset Completed').first()
        self.assertIsNotNone(res_cat)
        self.assertEqual(res_cat.company, self.company_a)

    def test_company_ticket_config_and_prefix(self):
        from .models import CompanyTicketConfig, ResolutionCategory, TicketCategory

        config = CompanyTicketConfig.objects.create(
            company=self.company_a,
            ticket_prefix="SEC-",
            require_resolution_note=True
        )

        ticket_code = self.ticket_a.get_ticket_code()
        self.assertTrue(ticket_code.startswith("SEC-"))

        res_cat = ResolutionCategory.objects.create(name="Replaced Hardware", company=self.company_a)
        cat = TicketCategory.objects.create(name="Hardware Fault", company=self.company_a)

        self.client.login(username="admin_a", password="password123")

        # Try resolving ticket without resolution notes (should fail validation)
        response = self.client.post(reverse('ticket_update', args=[self.ticket_a.id]), {
            'title': self.ticket_a.title,
            'description': self.ticket_a.description,
            'status': Ticket.STATUS_RESOLVED,
            'priority': self.ticket_a.priority,
            'ticket_category': cat.id,
            'resolution_category': res_cat.id,
            'resolution_notes': ''
        })
        self.assertEqual(response.status_code, 200) # Form re-rendered with error
        self.assertIn('resolution_notes', response.context['form'].errors)
        self.assertIn('กรุณาระบุรายละเอียดสรุปวิธีแก้ไขปัญหาก่อนเปลี่ยนสถานะเป็น Resolved/Closed', response.context['form'].errors['resolution_notes'])


        # Now resolve with resolution notes (should succeed)
        response = self.client.post(reverse('ticket_update', args=[self.ticket_a.id]), {
            'title': self.ticket_a.title,
            'description': self.ticket_a.description,
            'status': Ticket.STATUS_RESOLVED,
            'priority': self.ticket_a.priority,
            'ticket_category': cat.id,
            'resolution_category': res_cat.id,
            'resolution_notes': 'Replaced broken RAM stick'
        })
        self.assertEqual(response.status_code, 302)
        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, Ticket.STATUS_RESOLVED)
        self.assertEqual(self.ticket_a.resolution_notes, 'Replaced broken RAM stick')

    def test_company_field_customization_and_ordering(self):
        from .models import CompanyTicketField, TicketCategory

        self.client.login(username="admin_a", password="password123")

        # Access company ticket design page
        response = self.client.get(reverse('company_ticket_design'))
        self.assertEqual(response.status_code, 200)

        # Check default baseline fields seeded
        fields = CompanyTicketField.objects.filter(company=self.company_a).order_by('order', 'id')
        self.assertEqual(fields.count(), 5)

        # Add custom field (Location)
        response = self.client.post(reverse('company_ticket_design'), {
            'action': 'add_custom_field',
            'label': 'อาคารและสถานที่',
            'field_key': 'location',
            'field_type': 'TEXT',
            'placeholder': 'ระบุชั้นและเลขห้อง...',
            'is_required': 'on',
            'order': 60
        })
        self.assertEqual(response.status_code, 302)

        custom_f = CompanyTicketField.objects.filter(company=self.company_a, field_key='location').first()
        self.assertIsNotNone(custom_f)
        self.assertTrue(custom_f.is_custom)

        # Move custom field UP
        response = self.client.post(reverse('company_ticket_design'), {
            'action': 'move_field',
            'field_id': custom_f.id,
            'direction': 'up'
        })
        self.assertEqual(response.status_code, 302)

        # Create ticket with custom field data
        cat = TicketCategory.objects.create(name="Office Equipment", company=self.company_a)
        response = self.client.post(reverse('ticket_create'), {
            'title': 'Broken Air Conditioner',
            'description': 'Leaking water',
            'priority': 'HIGH',
            'ticket_category': cat.id,
            'location': 'Building B, Floor 4, Room 402'
        })
        self.assertEqual(response.status_code, 302)



        created_ticket = Ticket.objects.get(title='Broken Air Conditioner')
        self.assertEqual(created_ticket.custom_fields_data.get('location'), 'Building B, Floor 4, Room 402')

    def test_system_admin_without_company_ticket_and_category_creation(self):
        from .models import TicketCategory

        # System admin with company=None
        self.system_admin.company = None
        self.system_admin.save()
        self.client.login(username="system_admin", password="password123")



        # Category creation without icon_code & color_code
        response = self.client.post(reverse('ticket_category_create'), {
            'name': 'Global IT Support',
            'description': 'General IT Issues'
        })
        self.assertEqual(response.status_code, 302)


        cat = TicketCategory.objects.get(name='Global IT Support')
        self.assertEqual(cat.icon_code, 'folder')
        self.assertEqual(cat.color_code, '#6366f1')

        # Ticket creation by System Admin without company
        response = self.client.post(reverse('ticket_create'), {
            'title': 'Server Maintenance',
            'description': 'Upgrading OS kernel',
            'priority': 'HIGH',
            'ticket_category': cat.id,
            'company': self.company_a.id
        })
        self.assertEqual(response.status_code, 302)


        ticket = Ticket.objects.get(title='Server Maintenance')
        self.assertEqual(ticket.company, self.company_a)

    def test_category_list_company_filtering(self):
        from .models import TicketCategory

        cat_global = TicketCategory.objects.create(name="Global Network", company=None)
        cat_b = TicketCategory.objects.create(name="Company B Special", company=self.company_b)

        self.client.login(username="system_admin", password="password123")


        # Filter by Company B
        response = self.client.get(reverse('category_list') + f"?company_id={self.company_b.id}")
        self.assertEqual(response.status_code, 200)
        t_cats = list(response.context['ticket_categories'])
        self.assertIn(cat_global, t_cats)
        self.assertIn(cat_b, t_cats)
        self.assertEqual(response.context['selected_company'], self.company_b)

    def test_multiple_attachments_for_tickets_and_comments(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import TicketAttachment, CommentAttachment, TicketComment, TicketCategory

        self.client.login(username="user_a", password="password123")

        f1 = SimpleUploadedFile("doc1.pdf", b"content1", content_type="application/pdf")
        f2 = SimpleUploadedFile("doc2.jpg", b"content2", content_type="image/jpeg")

        # Create ticket with multiple files
        response = self.client.post(reverse('ticket_create'), {
            'title': 'Ticket with multiple files',
            'description': 'Description text',
            'priority': 'MEDIUM',
            'category': 'HARDWARE',
            'attachments': [f1, f2]
        })
        self.assertEqual(response.status_code, 302)

        ticket = Ticket.objects.get(title='Ticket with multiple files')
        self.assertEqual(ticket.attachments.count(), 2)

        # Add comment with multiple files
        c_f1 = SimpleUploadedFile("log1.txt", b"log data 1", content_type="text/plain")
        c_f2 = SimpleUploadedFile("log2.txt", b"log data 2", content_type="text/plain")

        response = self.client.post(reverse('ticket_detail', kwargs={'pk': ticket.pk}), {
            'content': 'Check these logs',
            'attachments': [c_f1, c_f2]
        })
        self.assertEqual(response.status_code, 302)

        comment = TicketComment.objects.filter(ticket=ticket).first()
        self.assertIsNotNone(comment)
        self.assertEqual(comment.attachments.count(), 2)

    def test_report_preview_pdf_generation(self):
        self.client.login(username="admin_a", password="password123")
        response = self.client.get(reverse('report_preview'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(len(response.content) > 0)

    def test_send_monthly_report_action(self):
        from .models import EmailLog
        mail.outbox = []

        self.client.login(username="admin_a", password="password123")
        response = self.client.post(reverse('report_send'))
        self.assertEqual(response.status_code, 302)

        # Check mail was sent
        self.assertTrue(len(mail.outbox) > 0)
        report_email = mail.outbox[0]
        self.assertIn("รายงานสรุปสถานะการแจ้งปัญหารายเดือน", report_email.subject)
        
        # Verify PDF attachment
        self.assertEqual(len(report_email.attachments), 1)
        filename, content, mimetype = report_email.attachments[0]
        self.assertTrue(filename.endswith(".pdf"))
        self.assertEqual(mimetype, "application/pdf")

        # Verify EmailLog database entry
        email_log = EmailLog.objects.filter(action_type=EmailLog.ACTION_MONTHLY_REPORT).first()
        self.assertIsNotNone(email_log)
        self.assertTrue(email_log.success)

    def test_send_monthly_report_to_individual(self):
        from .models import EmailLog
        mail.outbox = []

        self.client.login(username="admin_a", password="password123")
        response = self.client.post(reverse('report_send'), {
            'recipient_user_id': self.user_a.id
        })
        self.assertEqual(response.status_code, 302)

        # Check mail was sent only to user_a
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user_a.email])

    def test_report_preview_generates_view_log(self):
        from .models import ReportViewLog
        ReportViewLog.objects.all().delete()

        self.client.login(username="admin_a", password="password123")
        response = self.client.get(reverse('report_preview'))
        self.assertEqual(response.status_code, 200)

        # Check that ReportViewLog has been created
        view_log = ReportViewLog.objects.first()
        self.assertIsNotNone(view_log)
        self.assertEqual(view_log.viewer, self.admin_a)
        self.assertEqual(view_log.company, self.company_a)

    def test_smtp_configuration_and_dynamic_backend(self):
        from .models import SMTPConfiguration, get_smtp_connection, get_smtp_from_email
        
        # Test default when no configuration is active
        self.assertIsNone(get_smtp_connection())
        self.assertEqual(get_smtp_from_email("default@test.com"), "default@test.com")
        
        # Create and active an SMTP configuration
        config1 = SMTPConfiguration.objects.create(
            name="Gmail Admin",
            provider="GMAIL",
            host="smtp.gmail.com",
            port=587,
            use_tls=True,
            username="narunaithaisenee@gmail.com",
            password="app-password-16-chars",
            is_active=True
        )
        
        # Verify first config is active
        self.assertTrue(config1.is_active)
        
        # Create a second active config, verify it deactivates the first
        config2 = SMTPConfiguration.objects.create(
            name="Microsoft Outlook",
            provider="MICROSOFT",
            host="smtp.office365.com",
            port=587,
            use_tls=True,
            username="narunai@company.com",
            password="another-app-password",
            is_active=True
        )
        
        config1.refresh_from_db()
        self.assertFalse(config1.is_active)
        self.assertTrue(config2.is_active)
        
        # Verify connection and from_email are resolved dynamically
        connection = get_smtp_connection()
        self.assertIsNotNone(connection)
        self.assertEqual(connection.host, "smtp.office365.com")
        self.assertEqual(connection.port, 587)
        self.assertEqual(connection.username, "narunai@company.com")
        
        from_email = get_smtp_from_email("default@test.com")
        self.assertEqual(from_email, "narunai@company.com")

    def test_sub_admin_permissions(self):
        sub_admin = CustomUser.objects.create_user(
            username="sub_admin_user",
            email="subadmin@ticketsolve.com",
            password="password123",
            role=CustomUser.SYSTEM_SUB_ADMIN
        )
        
        self.client.login(username="sub_admin_user", password="password123")
        
        # 1. Sub-Admin should be able to view dashboard
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        
        # 2. Sub-Admin should be able to view companies list
        response = self.client.get(reverse('company_list'))
        self.assertEqual(response.status_code, 200)
        
        # 3. Sub-Admin should be able to view user list
        response = self.client.get(reverse('user_list'))
        self.assertEqual(response.status_code, 200)
        
        # 4. Sub-Admin CANNOT access SMTP settings page (it requires SYSTEM_ADMIN or superuser)
        response = self.client.get(reverse('system_settings'))
        self.assertEqual(response.status_code, 403)
        
        # 5. Check if Sub-Admin form limits role choices (client admin and client user only)
        from .views import CustomUserForm
        form = CustomUserForm(user=sub_admin)
        role_choices = [c[0] for c in form.fields['role'].choices]
        self.assertIn(CustomUser.CLIENT_ADMIN, role_choices)
        self.assertIn(CustomUser.CLIENT_USER, role_choices)
        self.assertNotIn(CustomUser.SYSTEM_ADMIN, role_choices)
        self.assertNotIn(CustomUser.SYSTEM_SUB_ADMIN, role_choices)

    def test_send_monthly_report_with_custom_smtp_selection(self):
        from .models import SMTPConfiguration
        mail.outbox = []

        # Create custom inactive SMTP configuration
        smtp_config = SMTPConfiguration.objects.create(
            name="Test Custom Account",
            provider="SIMULATION",
            host="smtp.testserver.com",
            port=587,
            use_tls=True,
            username="sender@testserver.com",
            password="secretpassword",
            is_active=False
        )

        self.client.login(username="admin_a", password="password123")
        response = self.client.post(reverse('report_send'), {
            'smtp_config_id': smtp_config.id
        })
        self.assertEqual(response.status_code, 302)

        # Check mail was sent and used the selected SMTP configuration email as from_email
        self.assertTrue(len(mail.outbox) > 0)
        report_email = mail.outbox[0]
        self.assertEqual(report_email.from_email, "sender@testserver.com")

    def test_email_or_username_login(self):
        # 1. Test logging in using username
        login_success = self.client.login(username="admin_a", password="password123")
        self.assertTrue(login_success)
        self.client.logout()

        # 2. Test logging in using email
        login_success = self.client.login(username="admin_a@company-a.com", password="password123")
        self.assertTrue(login_success)

    def test_ticket_category_selection(self):
        self.client.login(username="admin_a", password="password123")
        # Create ticket with specific category
        response = self.client.post(reverse('ticket_create'), {
            'title': 'Test network category issue',
            'description': 'Description here',
            'priority': 'HIGH',
            'category': 'NETWORK'
        })
        self.assertEqual(response.status_code, 302)
        
        # Verify ticket was created with correct category
        ticket = Ticket.objects.get(title='Test network category issue')
        self.assertEqual(ticket.category, 'NETWORK')
        
        # Verify it displays on detail page
        detail_response = self.client.get(reverse('ticket_detail', args=[ticket.id]))
        self.assertContains(detail_response, 'Network &amp; Internet')


    def test_language_switch_view(self):
        # 1. Test switching to English
        response = self.client.get(reverse('set_language') + '?lang=en')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.cookies.get('lang').value, 'en')

        # Verify translations injected via context processor
        self.client.login(username="admin_a", password="password123")
        dashboard_response = self.client.get(reverse('dashboard'))
        self.assertContains(dashboard_response, 'Dashboard')
        self.assertNotContains(dashboard_response, 'หน้าจอควบคุม (Dashboard)')

        # 2. Test switching back to Thai
        response = self.client.get(reverse('set_language') + '?lang=th')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.cookies.get('lang').value, 'th')
        
        dashboard_response = self.client.get(reverse('dashboard'))
        self.assertContains(dashboard_response, 'หน้าจอควบคุม')

    def test_ticket_creation_with_attachment(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.login(username="admin_a", password="password123")
        
        # Create a mock file
        mock_file = SimpleUploadedFile("test_document.txt", b"Mock file content for test")
        
        response = self.client.post(reverse('ticket_create'), {
            'title': 'Ticket with Attachment',
            'description': 'Description here',
            'priority': 'MEDIUM',
            'category': 'SOFTWARE',
            'attachment': mock_file
        })
        self.assertEqual(response.status_code, 302)
        
        # Verify ticket has the file
        ticket = Ticket.objects.get(title='Ticket with Attachment')
        self.assertTrue(bool(ticket.attachment))
        self.assertIn('test_document', ticket.attachment.name)
        
        # Clean up file
        if os.path.exists(ticket.attachment.path):
            os.remove(ticket.attachment.path)

    def test_comment_creation_and_email_notification(self):
        from .models import TicketComment, EmailLog
        # Log in as technician admin_a
        self.client.login(username="admin_a", password="password123")
        
        # Ensure ticket_a has a stakeholder creator user_a. Assign tech_a admin_a to it.
        self.ticket_a.assigned_to = self.admin_a
        self.ticket_a.save()
        
        # Clear outbox
        mail.outbox = []
        
        # tech_a posts a comment. This should notify creator user_a.
        response = self.client.post(reverse('ticket_detail', args=[self.ticket_a.id]), {
            'content': 'This is a test comment by technician'
        })
        self.assertEqual(response.status_code, 302)
        
        # Verify comment is saved
        comment = TicketComment.objects.filter(ticket=self.ticket_a).first()
        self.assertIsNotNone(comment)
        self.assertEqual(comment.content, 'This is a test comment by technician')
        self.assertEqual(comment.author, self.admin_a)
        
        # Verify email is sent to user_a (ticket creator)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user_a.email])
        self.assertIn('ความคิดเห็นใหม่', mail.outbox[0].subject)
        
        # Verify EmailLog was created
        email_log = EmailLog.objects.filter(recipient=self.user_a.email, action_type=EmailLog.ACTION_COMMENT_ADDED).first()
        self.assertIsNotNone(email_log)
        self.assertTrue(email_log.success)

    def test_ticket_creation_file_size_limit_ok(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.login(username="admin_a", password="password123")
        
        # 5 MB file
        mock_file = SimpleUploadedFile("five_mb.txt", b"x" * (5 * 1024 * 1024))
        response = self.client.post(reverse('ticket_create'), {
            'title': 'Ticket with 5MB Attachment',
            'description': 'Description here',
            'priority': 'MEDIUM',
            'category': 'SOFTWARE',
            'attachment': mock_file
        })
        self.assertEqual(response.status_code, 302)
        
        # Clean up file
        ticket = Ticket.objects.get(title='Ticket with 5MB Attachment')
        if os.path.exists(ticket.attachment.path):
            os.remove(ticket.attachment.path)

    def test_ticket_creation_file_size_limit_exceeded(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.login(username="admin_a", password="password123")
        
        # 11 MB file
        mock_file = SimpleUploadedFile("eleven_mb.txt", b"x" * (11 * 1024 * 1024))
        response = self.client.post(reverse('ticket_create'), {
            'title': 'Ticket with 11MB Attachment',
            'description': 'Description here',
            'priority': 'MEDIUM',
            'category': 'SOFTWARE',
            'attachment': mock_file
        })
        # Validation should fail, rendering the form page (200) instead of redirecting (302)
        self.assertEqual(response.status_code, 200)
        self.assertIn("ต้องไม่เกิน 10 MB", response.content.decode('utf-8'))

    def test_ticket_delete_manage_access_and_filtering(self):
        # Regular user should be denied access
        self.client.login(username="user_a", password="password123")
        response = self.client.get(reverse('ticket_delete_manage'))
        self.assertEqual(response.status_code, 403)

        # System admin can access
        self.client.login(username="system_admin", password="password123")
        response = self.client.get(reverse('ticket_delete_manage'))
        self.assertEqual(response.status_code, 200)
        self.assertIn("จัดการและลบ Ticket", response.content.decode('utf-8'))

        # Test filtering by company and year
        response = self.client.get(reverse('ticket_delete_manage'), {'company_id': self.company_a.id, 'year': 2026})
        self.assertEqual(response.status_code, 200)

    def test_ticket_batch_and_single_delete_actions(self):
        # Create test tickets
        t1 = Ticket.objects.create(title="Delete T1", description="desc", company=self.company_a, created_by=self.user_a)
        t2 = Ticket.objects.create(title="Delete T2", description="desc", company=self.company_a, created_by=self.user_a)

        self.client.login(username="system_admin", password="password123")

        # Test batch delete
        response = self.client.post(reverse('ticket_delete_manage'), {
            'action': 'delete_selected',
            'ticket_ids': [t1.id, t2.id]
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Ticket.objects.filter(id__in=[t1.id, t2.id]).exists())

        # Test single delete
        t3 = Ticket.objects.create(title="Delete T3", description="desc", company=self.company_a, created_by=self.user_a)
        response = self.client.post(reverse('ticket_delete', kwargs={'pk': t3.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Ticket.objects.filter(id=t3.id).exists())

    def test_deployment_requested_and_confirm_flow(self):
        t = Ticket.objects.create(
            title="Deploy Request Test",
            description="Deployment needed",
            status=Ticket.STATUS_IN_PROGRESS,
            company=self.company_a,
            created_by=self.user_a
        )

        # Update status to DEPLOYMENT_REQUESTED
        t.status = Ticket.STATUS_DEPLOYMENT_REQUESTED
        t.save()

        # Confirm deployment via ConfirmDeploymentView
        self.client.login(username="admin_a", password="password123")
        response = self.client.post(reverse('confirm_deployment', kwargs={'pk': t.pk}))
        self.assertEqual(response.status_code, 302)

        t.refresh_from_db()
        self.assertEqual(t.status, Ticket.STATUS_READY_TO_DEPLOY)

    def test_resend_failed_email_log(self):
        from django.test import override_settings
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            elog = EmailLog.objects.create(
                recipient="test_resend@example.com",
                subject="Test Resend",
                message="Test Message",
                action_type=EmailLog.ACTION_TICKET_UPDATED,
                success=False,
                error_message="Simulated error"
            )
            self.client.login(username="system_admin", password="password123")
            response = self.client.post(reverse('resend_email', kwargs={'pk': elog.pk}))
            self.assertEqual(response.status_code, 302)

            elog.refresh_from_db()
            self.assertTrue(elog.success)
            self.assertEqual(elog.error_message, "")

    def test_notification_config_filtering(self):
        from .models import NotificationConfig, should_send_email_notification
        
        # Company A config: Only important status changes allowed
        config_a = NotificationConfig.objects.create(
            name="Company A Important Only",
            company=self.company_a,
            status_notification_mode=NotificationConfig.STATUS_NOTIFY_IMPORTANT_ONLY,
            notify_comments=False
        )

        # Test normal status change (IN_PROGRESS) -> should return False
        self.assertFalse(should_send_email_notification(
            self.user_a.email,
            event_type=EmailLog.ACTION_TICKET_UPDATED,
            new_status=Ticket.STATUS_IN_PROGRESS
        ))

        # Test important status change (DEPLOYMENT_REQUESTED) -> should return True
        self.assertTrue(should_send_email_notification(
            self.user_a.email,
            event_type=EmailLog.ACTION_TICKET_UPDATED,
            new_status=Ticket.STATUS_DEPLOYMENT_REQUESTED
        ))

        # Test comment notification -> should return False
        self.assertFalse(should_send_email_notification(
            self.user_a.email,
            event_type=EmailLog.ACTION_COMMENT_ADDED
        ))

        # Add User-specific override for User A: allow comments
        config_user = NotificationConfig.objects.create(
            name="User A Specific",
            company=self.company_a,
            notify_comments=True
        )
        config_user.target_users.add(self.user_a)

        # Now User A should receive comment notifications because of specific user override!
        self.assertTrue(should_send_email_notification(
            self.user_a.email,
            event_type=EmailLog.ACTION_COMMENT_ADDED
        ))

    def test_create_monthly_report_schedule_with_cc(self):
        self.client.login(username="admin_a", password="password123")
        response = self.client.post(reverse('report_schedule_save'), {
            'name': 'Month-end management report',
            'company': self.company_a.id,
            'recipients': [self.admin_a.id],
            'cc_recipients': [self.user_a.id],
            'day_of_month': 31,
            'send_hour': '23',
            'send_minute': '45',
            'timezone_name': MonthlyReportSchedule.TIMEZONE_HONG_KONG,
            'is_active': 'on',
        })
        self.assertEqual(response.status_code, 302)
        schedule = MonthlyReportSchedule.objects.get(name='Month-end management report')
        self.assertEqual(schedule.company, self.company_a)
        self.assertEqual(schedule.created_by, self.admin_a)
        self.assertEqual(schedule.send_time.strftime('%H:%M'), '23:45')
        self.assertEqual(schedule.timezone_name, MonthlyReportSchedule.TIMEZONE_HONG_KONG)
        self.assertCountEqual(schedule.recipients.all(), [self.admin_a])
        self.assertCountEqual(schedule.cc_recipients.all(), [self.user_a])

    def test_process_report_schedule_sends_to_and_cc_and_marks_sent(self):
        schedule = MonthlyReportSchedule.objects.create(
            name='Automated report',
            company=self.company_a,
            day_of_month=31,
            send_time='17:00',
            created_by=self.admin_a,
        )
        schedule.recipients.add(self.admin_a)
        schedule.cc_recipients.add(self.user_a)
        mail.outbox = []

        call_command('process_report_schedules', '--schedule-id', schedule.id, '--force')

        report_email = next(message for message in mail.outbox if 'รายงานสรุปสถานะ' in message.subject)
        self.assertEqual(report_email.to, [self.admin_a.email])
        self.assertEqual(report_email.cc, [self.user_a.email])
        schedule.refresh_from_db()
        self.assertIsNotNone(schedule.last_sent_at)
        self.assertEqual(schedule.last_error, '')

    def test_schedule_day_31_uses_last_day_for_short_month(self):
        import datetime
        schedule = MonthlyReportSchedule(
            name='Last day',
            day_of_month=31,
            send_time=datetime.time(9, 15),
        )
        scheduled_at = schedule.scheduled_datetime(2027, 2)
        self.assertEqual(scheduled_at.day, 28)
        self.assertEqual(scheduled_at.hour, 9)
        self.assertEqual(scheduled_at.minute, 15)

    def test_schedule_uses_selected_hong_kong_timezone(self):
        import datetime
        schedule = MonthlyReportSchedule(
            name='Hong Kong report',
            day_of_month=31,
            send_time=datetime.time(17, 0),
            timezone_name=MonthlyReportSchedule.TIMEZONE_HONG_KONG,
        )
        scheduled_at = schedule.scheduled_datetime(2027, 7)
        self.assertEqual(scheduled_at.utcoffset(), datetime.timedelta(hours=8))
        self.assertTrue(schedule.is_due(datetime.datetime(
            2027, 7, 31, 9, 1, tzinfo=datetime.timezone.utc
        )))

    def test_immediate_monthly_report_supports_cc(self):
        mail.outbox = []
        self.client.login(username="admin_a", password="password123")
        response = self.client.post(reverse('report_send'), {
            'recipient_user_id': self.admin_a.id,
            'cc_user_ids': [self.user_a.id],
        })
        self.assertEqual(response.status_code, 302)
        report_email = next(message for message in mail.outbox if 'รายงานสรุปสถานะ' in message.subject)
        self.assertEqual(report_email.to, [self.admin_a.email])
        self.assertEqual(report_email.cc, [self.user_a.email])

    def test_email_logs_group_to_and_cc_in_one_row_with_detail(self):
        mail.outbox = []
        self.client.login(username="admin_a", password="password123")
        response = self.client.post(reverse('report_send'), {
            'recipient_user_id': self.admin_a.id,
            'cc_user_ids': [self.user_a.id],
        })
        self.assertEqual(response.status_code, 302)

        grouped_logs = EmailLog.objects.filter(
            action_type=EmailLog.ACTION_MONTHLY_REPORT
        ).order_by('-sent_at')[:2]
        self.assertEqual(len(grouped_logs), 2)
        self.assertIsNotNone(grouped_logs[0].delivery_group)
        self.assertEqual(grouped_logs[0].delivery_group, grouped_logs[1].delivery_group)
        self.assertCountEqual(
            [log.recipient_type for log in grouped_logs],
            [EmailLog.RECIPIENT_TO, EmailLog.RECIPIENT_CC],
        )

        list_response = self.client.get(reverse('log_list'))
        self.assertEqual(list_response.status_code, 200)
        groups = list_response.context['email_logs']
        report_group = next(group for group in groups if group.subject == grouped_logs[0].subject)
        self.assertEqual(report_group.to_recipients, [self.admin_a.email])
        self.assertEqual(report_group.cc_recipients, [self.user_a.email])

        detail_response = self.client.get(reverse('email_log_detail', args=[report_group.detail_id]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, self.admin_a.email)
        self.assertContains(detail_response, self.user_a.email)






