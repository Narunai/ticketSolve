import os
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core import mail
from django.core.management import call_command
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied

from .models import Company, Ticket, CustomUser
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
        self.assertIn(self.user_a.email, mail.outbox[0].to)

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
        self.assertContains(detail_response, 'Network / Internet')

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
        self.assertIn("ขนาดไฟล์แนบต้องไม่เกิน 10 MB", response.content.decode('utf-8'))
