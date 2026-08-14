import os
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core import mail
from django.core.management import call_command
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection

from .models import Company, Ticket, CustomUser, EmailLog, MonthlyReportSchedule, TicketAuditLog, TicketAutomationConfig, SMTPConfiguration

from .admin import CustomUserAdmin, TicketAdmin

User = get_user_model()

class MultiTenantTicketTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from unittest import mock
        cls._close_old_conn_patch = mock.patch('django.db.close_old_connections', lambda: None)
        cls._close_old_conn_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._close_old_conn_patch.stop()
        super().tearDownClass()

    def setUp(self):
        connection.max_age = None
        connection.is_usable = lambda: True
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
        self.client.cookies['lang'] = 'th'

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
        self.assertNotIn("📌", mail.outbox[0].body)
        self.assertTrue(mail.outbox[0].alternatives)
        self.assertIn('Support Ticket Confirmation', mail.outbox[0].alternatives[0][0])
        all_to = [to_addr for m in mail.outbox for to_addr in m.to]
        self.assertIn(self.user_a.email, all_to)

    def test_chatbot_auth_subrequests_enforce_session_and_system_role(self):
        user_auth_url = reverse('chatbot_user_auth')
        admin_auth_url = reverse('chatbot_admin_auth')

        self.assertEqual(self.client.get(user_auth_url).status_code, 401)
        self.assertEqual(self.client.get(admin_auth_url).status_code, 401)

        self.client.login(username='user_a', password='password123')
        user_response = self.client.get(user_auth_url)
        self.assertEqual(user_response.status_code, 204)
        self.assertEqual(user_response['X-Chatbot-User'], str(self.user_a.pk))
        self.assertEqual(user_response['X-Chatbot-Role'], User.CLIENT_USER)
        self.assertEqual(self.client.get(admin_auth_url).status_code, 403)

        self.client.logout()
        self.client.login(username='system_admin', password='password123')
        admin_response = self.client.get(admin_auth_url)
        self.assertEqual(admin_response.status_code, 204)
        self.assertEqual(admin_response['X-Chatbot-Role'], 'SUPERUSER')


    def test_data_isolation_regular_user_a_cannot_see_b_data(self):
        # Log in as user_b
        self.client.login(username="user_b", password="password123")
        
        # Attempt to access Ticket Detail of Company A
        response = self.client.get(reverse('ticket_detail', args=[self.ticket_a.id]))
        # Should raise PermissionDenied or return 403 depending on implementation (class view raises PermissionDenied)
        self.assertEqual(response.status_code, 403)

    def test_data_isolation_regular_user_a_can_see_own_data(self):
        from bs4 import BeautifulSoup

        # Log in as user_a
        self.client.login(username="user_a", password="password123")
        
        response = self.client.get(reverse('ticket_detail', args=[self.ticket_a.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ticket_a.title)

        # Regression: malformed file-input markup previously broke the grid,
        # pushed Ticket Info below the comment form, and detached form controls.
        page = BeautifulSoup(response.content, 'html.parser')
        layout = page.find(id='ticket-detail-layout')
        main_column = page.find(id='ticket-detail-main')
        sidebar = page.find(id='ticket-detail-sidebar')
        uploader = page.find(id='comment-file-uploader-container')
        file_input = page.find(id='comment-real-file-input')
        file_controls = page.find(id='comment-file-controls')
        self.assertIsNotNone(layout)
        self.assertIsNotNone(main_column)
        self.assertIsNotNone(sidebar)
        self.assertEqual(main_column.parent, layout)
        self.assertEqual(sidebar.parent, layout)
        self.assertEqual(file_input.parent, uploader)
        self.assertEqual(file_controls.parent, uploader)
        self.assertEqual(file_input.get('type'), 'file')
        self.assertIn('xl:col-span-8', main_column.get('class', []))
        self.assertIn('xl:col-span-4', sidebar.get('class', []))

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
        self.assertIn("Monthly Ticket Summary Report", report_email.subject)
        self.assertIn("Company A", report_email.body)
        self.assertTrue(report_email.alternatives)
        self.assertIn('Service Management System', report_email.alternatives[0][0])

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
        self.assertIn("Account Registration Confirmation", welcome_email.subject)
        self.assertIn("new_employee", welcome_email.body)
        self.assertTrue(welcome_email.alternatives)

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
        self.assertIn("Status Update", email_entry.subject)

    def test_monthly_report_view_access(self):
        # Client Admin can access
        self.client.login(username="admin_a", password="password123")
        response = self.client.get(reverse('monthly_report'))
        self.assertEqual(response.status_code, 200)

        # Client User cannot access
        self.client.login(username="user_a", password="password123")
        response = self.client.get(reverse('monthly_report'))
        self.assertEqual(response.status_code, 403)

    def test_sidebar_navigation_follows_the_admin_workflow(self):
        self.client.login(username="system_admin", password="password123")
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

        page = response.content.decode('utf-8')
        nav_start = page.index('aria-label="Main navigation"')
        navigation = page[nav_start:page.index('</nav>', nav_start)]
        expected_order = [
            'Workspace',
            f'href="{reverse("dashboard")}"',
            f'href="{reverse("ticket_create")}"',
            'Administration',
            f'href="{reverse("user_list")}"',
            f'href="{reverse("company_list")}"',
            'Reports &amp; Data',
            f'href="{reverse("monthly_report")}"',
            f'href="{reverse("log_list")}"',
            f'href="{reverse("backup_list")}"',
            f'href="{reverse("ticket_delete_manage")}"',
            'Ticket Configuration',
            f'href="{reverse("category_list")}"',
            f'href="{reverse("notification_config_list")}"',
            f'href="{reverse("ticket_automation_list")}"',
            'Email Integration',
            f'href="{reverse("email_timer")}"',
            f'href="{reverse("system_settings")}"',
        ]
        positions = [navigation.index(marker) for marker in expected_order]
        self.assertEqual(positions, sorted(positions))

    def test_sidebar_identity_shows_name_company_and_effective_admin_role(self):
        self.client.login(username='system_admin', password='password123')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        page = response.content.decode('utf-8')
        card_start = page.index('id="sidebarIdentityCard"')
        admin_card = page[card_start:page.index('<!-- Navigation Links -->', card_start)]
        self.assertIn('Account Information', admin_card)
        self.assertIn('system_admin', admin_card)
        self.assertIn('Central Administration', admin_card)
        self.assertIn('System Administrator', admin_card)
        self.assertNotIn('Client User', admin_card)

        self.user_a.first_name = 'Alice'
        self.user_a.last_name = 'Support'
        self.user_a.save(update_fields=['first_name', 'last_name'])
        self.client.logout()
        self.client.login(username='user_a', password='password123')
        response = self.client.get(reverse('dashboard'))
        page = response.content.decode('utf-8')
        card_start = page.index('id="sidebarIdentityCard"')
        client_card = page[card_start:page.index('<!-- Navigation Links -->', card_start)]
        self.assertIn('Alice Support', client_card)
        self.assertIn('Company A', client_card)
        self.assertIn('Client User', client_card)

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
        self.assertIn('Please provide a resolution summary before changing status to Resolved/Closed', response.context['form'].errors['resolution_notes'])


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
        self.assertEqual(fields.count(), 6)

        # Add custom field (Location)
        response = self.client.post(reverse('company_ticket_design'), {
            'action': 'add_custom_field',
            'label': 'Location & Room Number',
            'field_key': 'location',
            'field_type': 'TEXT',
            'placeholder': 'e.g. Floor 2, Room 204...',
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
            'description': 'General IT Issues',
            'is_active': 'on'
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

        f1 = SimpleUploadedFile("doc1.pdf", b"%PDF-1.7\ncontent1", content_type="application/pdf")
        f2 = SimpleUploadedFile("doc2.jpg", b"\xff\xd8\xffcontent2\xff\xd9", content_type="image/jpeg")

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
        from io import BytesIO
        from pypdf import PdfReader
        from django.template.loader import get_template
        from .views import get_report_context

        thai_subject = 'ปัญหาการใช้งานภาษาไทย'
        Ticket.objects.create(
            title=thai_subject,
            description='รายละเอียดและชื่อผู้ส่งภาษาไทยต้องอ่านได้',
            company=self.company_a,
            created_by=self.user_a,
        )
        self.client.login(username="admin_a", password="password123")
        response = self.client.get(reverse('report_preview'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.assertIn(b'Sarabun', response.content)
        extracted_text = '\n'.join(
            page.extract_text() or ''
            for page in PdfReader(BytesIO(response.content)).pages
        )
        self.assertIn(thai_subject, extracted_text)

        context = get_report_context(self.admin_a)
        report_html = get_template('tickets/report_pdf_template.html').render(context)
        self.assertIn('Executive Summary', report_html)
        self.assertIn(context['report_reference'], report_html)
        self.assertNotIn('📌', report_html)

    def test_send_monthly_report_action(self):
        from .models import EmailLog
        mail.outbox = []

        self.client.login(username="admin_a", password="password123")
        response = self.client.post(reverse('report_send'))
        self.assertEqual(response.status_code, 302)

        # Check mail was sent
        self.assertTrue(len(mail.outbox) > 0)
        report_email = mail.outbox[0]
        self.assertIn("Monthly Ticket Summary Report", report_email.subject)
        self.assertIn('Report reference:', report_email.body)
        self.assertTrue(report_email.alternatives)
        self.assertIn('Monthly Ticket Summary Report', report_email.alternatives[0][0])
        
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
        smtp_conn = get_smtp_connection()
        self.assertIsNotNone(smtp_conn)
        self.assertEqual(smtp_conn.host, "smtp.office365.com")
        self.assertEqual(smtp_conn.port, 587)
        self.assertEqual(smtp_conn.username, "narunai@company.com")
        
        from_email = get_smtp_from_email("default@test.com")
        self.assertEqual(from_email, "narunai@company.com")

    def test_smtp_active_configuration_is_scoped_by_feature(self):
        from .models import SMTPConfiguration, get_smtp_connection

        outbound = SMTPConfiguration.objects.create(
            name='Outbound only',
            provider='GMAIL',
            host='smtp.gmail.com',
            username='outbound@example.com',
            password='outbound-password',
            feature_scope=SMTPConfiguration.FEATURE_OUTBOUND_EMAIL,
            is_active=True,
        )
        inbound = SMTPConfiguration.objects.create(
            name='Inbound only',
            provider='GMAIL',
            host='smtp.gmail.com',
            username='inbound@example.com',
            password='inbound-password',
            feature_scope=SMTPConfiguration.FEATURE_EMAIL_TO_TICKET,
            incoming_host='imap.gmail.com',
            email_to_ticket_company=self.company_a,
            email_to_ticket_creator=self.user_a,
            is_active=True,
        )

        outbound.refresh_from_db()
        inbound.refresh_from_db()
        self.assertTrue(outbound.is_active)
        self.assertTrue(inbound.is_active)
        self.assertEqual(get_smtp_connection().username, 'outbound@example.com')

        both = SMTPConfiguration.objects.create(
            name='Both features',
            provider='GMAIL',
            host='smtp.gmail.com',
            username='both@example.com',
            password='both-password',
            feature_scope=SMTPConfiguration.FEATURE_BOTH,
            incoming_host='imap.gmail.com',
            email_to_ticket_company=self.company_a,
            email_to_ticket_creator=self.user_a,
            is_active=True,
        )
        outbound.refresh_from_db()
        inbound.refresh_from_db()
        self.assertFalse(outbound.is_active)
        self.assertFalse(inbound.is_active)
        self.assertTrue(both.is_active)

    def test_email_to_ticket_import_requires_approval_and_prevents_duplicate(self):
        import tempfile
        from email.message import EmailMessage as RawEmailMessage
        from unittest import mock
        from django.test import override_settings
        from .email_to_ticket import (
            InboundMessage,
            _create_ticket,
            approve_inbound_email,
            _is_issue_message,
            import_email_to_tickets,
        )
        from .models import (
            InboundEmailContact,
            InboundEmailReceipt,
            InboundEmailRoutingRule,
            SMTPConfiguration,
            TicketAttachment,
        )

        raw_message = RawEmailMessage()
        raw_message['Subject'] = 'Issue: VPN connection failed'
        raw_message['From'] = 'External User <external@example.com>'
        raw_message['Message-ID'] = '<email-to-ticket-1@example.com>'
        raw_message.set_content('The VPN client reports error 500.')
        raw_message.add_attachment(
            b'log data',
            maintype='text',
            subtype='plain',
            filename='vpn-error.txt',
        )

        config = SMTPConfiguration.objects.create(
            name='Inbound mailbox',
            provider='GMAIL',
            host='smtp.gmail.com',
            username='support@example.com',
            password='app-password',
            feature_scope=SMTPConfiguration.FEATURE_EMAIL_TO_TICKET,
            incoming_host='imap.gmail.com',
            incoming_port=993,
            incoming_folder='INBOX',
            email_to_ticket_company=self.company_a,
            email_to_ticket_creator=self.user_a,
            email_to_ticket_assignee=self.user_a,
            filter_issue_only=True,
            issue_keywords='from gmail only',
            is_active=True,
        )
        routing_rule = InboundEmailRoutingRule.objects.create(
            smtp_configuration=config,
            sender_email='EXTERNAL@EXAMPLE.COM',
            assignee=self.user_b,
            is_active=True,
        )
        system_notification = InboundMessage(
            uid=b'100',
            message_id='<system-notification@example.com>',
            subject='[TicketSolve] New Support Ticket Created: Issue',
            body='Must never be imported back into TicketSolve.',
        )
        self.assertFalse(_is_issue_message(config, system_notification)[0])

        imap_client = mock.Mock()
        imap_client.select.return_value = ('OK', [b'1'])

        def imap_uid(command, *args):
            if command == 'search':
                return 'OK', [b'101']
            if command == 'fetch':
                if args[-1] == '(RFC822.SIZE)':
                    return 'OK', [(b'101 (RFC822.SIZE 512)', b'')]
                return 'OK', [(b'101 (BODY[] {1})', raw_message.as_bytes()), b')']
            if command == 'store':
                return 'OK', [b'101']
            raise AssertionError(f'Unexpected IMAP UID command: {command}')

        imap_client.uid.side_effect = imap_uid
        ticket_count = Ticket.objects.count()

        with tempfile.TemporaryDirectory() as media_root, tempfile.TemporaryDirectory() as backup_dir, \
                override_settings(MEDIA_ROOT=media_root), \
                mock.patch('tickets.backup_service.BACKUP_DIR', backup_dir), \
                mock.patch('tickets.email_to_ticket.imaplib.IMAP4_SSL', return_value=imap_client):
            first = import_email_to_tickets(config)
            pending_receipt = InboundEmailReceipt.objects.get(
                smtp_configuration=config,
                message_id='<email-to-ticket-1@example.com>',
            )
            self.assertEqual(pending_receipt.status, InboundEmailReceipt.STATUS_PENDING)
            self.assertIsNone(pending_receipt.ticket)
            self.assertEqual(pending_receipt.attachments.count(), 1)
            imported_ticket, _ = approve_inbound_email(
                pending_receipt.pk,
                self.system_admin,
            )
            second = import_email_to_tickets(config)
            fallback_ticket, _ = _create_ticket(
                config,
                InboundMessage(
                    uid=b'102',
                    message_id='<fallback-route@example.com>',
                    subject='Issue: printer offline',
                    body='Printer cannot print.',
                    sender_email='another-sender@example.com',
                ),
            )

        self.assertTrue(first['success'])
        self.assertEqual(first['pending'], 1)
        self.assertEqual(first['imported'], 0)
        self.assertEqual(second['duplicates'], 1)
        self.assertEqual(Ticket.objects.count(), ticket_count + 2)
        imported_ticket.refresh_from_db()
        self.assertEqual(imported_ticket.company, self.company_b)
        self.assertEqual(imported_ticket.created_by, self.user_b)
        self.assertEqual(imported_ticket.assigned_to, self.user_b)
        self.assertEqual(
            imported_ticket.custom_fields_data['email_to_ticket']['routing_rule_id'],
            routing_rule.pk,
        )
        self.assertEqual(
            imported_ticket.custom_fields_data['email_to_ticket']['assignment_source'],
            'SENDER_RULE',
        )
        self.assertEqual(
            imported_ticket.custom_fields_data['email_to_ticket']['company_source'],
            'ASSIGNEE_COMPANY',
        )
        self.assertEqual(
            imported_ticket.custom_fields_data['email_to_ticket']['creator_source'],
            'ROUTED_ASSIGNEE',
        )
        self.assertEqual(fallback_ticket.company, self.company_a)
        self.assertEqual(fallback_ticket.created_by, self.user_a)
        self.assertEqual(fallback_ticket.assigned_to, self.user_a)
        self.assertEqual(
            fallback_ticket.custom_fields_data['email_to_ticket']['assignment_source'],
            'SMTP_DEFAULT',
        )
        self.assertEqual(
            imported_ticket.custom_fields_data['email_to_ticket']['message_id'],
            '<email-to-ticket-1@example.com>',
        )
        self.assertEqual(TicketAttachment.objects.filter(ticket=imported_ticket).count(), 1)
        receipt = InboundEmailReceipt.objects.get(
            smtp_configuration=config,
            message_id='<email-to-ticket-1@example.com>',
        )
        self.assertEqual(receipt.status, InboundEmailReceipt.STATUS_IMPORTED)
        self.assertEqual(receipt.ticket, imported_ticket)
        self.assertEqual(receipt.decided_by, self.system_admin)
        self.assertIsNotNone(receipt.decided_at)
        self.assertEqual(receipt.attachments.count(), 0)
        contact = InboundEmailContact.objects.get(
            smtp_configuration=config,
            email='external@example.com',
        )
        self.assertEqual(contact.display_name, 'External User')
        self.assertEqual(contact.message_count, 1)
        self.client.login(username='system_admin', password='password123')
        contact_response = self.client.get(
            reverse('email_timer'),
            {'contact_q': 'external@example.com'},
        )
        self.assertContains(contact_response, 'External User')
        self.assertContains(contact_response, 'external@example.com')

    def test_address_book_entry_does_not_bypass_email_approval(self):
        from .email_to_ticket import _is_approved_sender
        from .models import (
            InboundEmailContact,
            InboundEmailReceipt,
            SMTPConfiguration,
        )

        config = SMTPConfiguration.objects.create(
            name='Approval mailbox',
            provider='GMAIL',
            username='approval@example.com',
            password='app-password',
            feature_scope=SMTPConfiguration.FEATURE_EMAIL_TO_TICKET,
            incoming_host='imap.gmail.com',
            email_to_ticket_company=self.company_a,
            email_to_ticket_creator=self.user_a,
            is_active=True,
        )
        sender = 'new.sender@example.com'
        InboundEmailContact.objects.create(
            smtp_configuration=config,
            email=sender,
            display_name='New Sender',
        )
        self.assertFalse(_is_approved_sender(config, sender))

        receipt = InboundEmailReceipt.objects.create(
            smtp_configuration=config,
            message_id='<rejected-sender@example.com>',
            sender_email=sender,
            subject='Rejected request',
            status=InboundEmailReceipt.STATUS_REJECTED,
        )
        self.assertFalse(_is_approved_sender(config, sender))

        receipt.status = InboundEmailReceipt.STATUS_IMPORTED
        receipt.save(update_fields=['status'])
        self.assertFalse(_is_approved_sender(config, sender))

        receipt.decided_by = self.system_admin
        receipt.decided_at = timezone.now()
        receipt.save(update_fields=['decided_by', 'decided_at'])
        self.assertTrue(_is_approved_sender(config, sender))

        InboundEmailContact.objects.filter(
            smtp_configuration=config,
            email=sender,
        ).delete()
        self.assertFalse(_is_approved_sender(config, sender))

    def test_email_to_ticket_manual_import_requires_system_admin(self):
        from unittest import mock
        from .models import SMTPConfiguration

        config = SMTPConfiguration.objects.create(
            name='Manual import mailbox',
            provider='GMAIL',
            username='support@example.com',
            password='app-password',
            feature_scope=SMTPConfiguration.FEATURE_EMAIL_TO_TICKET,
            incoming_host='imap.gmail.com',
            email_to_ticket_company=self.company_a,
            email_to_ticket_creator=self.user_a,
            is_active=True,
        )
        url = reverse('smtp_import_email', args=[config.pk])

        self.client.login(username='admin_a', password='password123')
        self.assertEqual(self.client.post(url).status_code, 403)

        self.client.logout()
        self.client.login(username='system_admin', password='password123')
        result = {
            'success': True,
            'found': 1,
            'imported': 1,
            'skipped': 0,
            'duplicates': 0,
            'failed': 0,
            'error': '',
        }
        outcome = {
            'executed': True,
            'reason': '',
            'log': None,
            'results': [(config, result)],
        }
        with mock.patch(
            'tickets.views.run_email_to_ticket_cycle',
            return_value=outcome,
        ) as importer:
            response = self.client.post(url)
        self.assertRedirects(response, reverse('system_settings'))
        importer.assert_called_once_with(
            trigger='MANUAL',
            actor=self.system_admin,
            config=config,
        )

    def test_email_timer_page_is_system_admin_only_and_saves_interval(self):
        from .models import (
            EmailToTicketSchedule,
            InboundEmailRoutingRule,
            SMTPConfiguration,
        )

        url = reverse('email_timer')
        self.client.login(username='admin_a', password='password123')
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.logout()
        self.client.login(username='system_admin', password='password123')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Email → Ticket Timer')
        self.assertContains(response, 'id="emailLogTabsContainer"', count=1)
        self.assertContains(response, 'data-email-log-tab="approval"', count=1)
        self.assertContains(response, 'data-email-log-tab="import"', count=1)
        self.assertContains(response, 'data-email-log-tab="execution"', count=1)
        self.assertContains(response, 'data-email-log-tab="contacts"', count=1)
        self.assertContains(response, 'id="emailApprovalTabPanel"', count=1)
        self.assertContains(response, 'id="emailImportTabPanel"', count=1)
        self.assertContains(response, 'id="executionLogTabPanel"', count=1)
        self.assertContains(response, 'id="emailContactsTabPanel"', count=1)
        rendered_page = response.content.decode('utf-8')
        log_container_start = rendered_page.index('id="emailLogTabsContainer"')
        log_container_end = rendered_page.index('</section>', log_container_start)
        log_container = rendered_page[log_container_start:log_container_end]
        self.assertIn('id="emailApprovalTabPanel"', log_container)
        self.assertIn('id="emailImportTabPanel"', log_container)
        self.assertIn('id="executionLogTabPanel"', log_container)
        self.assertIn('id="emailContactsTabPanel"', log_container)

        response = self.client.post(
            url,
            {
                'interval_minutes': '30',
                'is_active': 'on',
            },
        )
        self.assertRedirects(response, url)
        schedule = EmailToTicketSchedule.get_solo()
        self.assertEqual(schedule.interval_minutes, 30)
        self.assertTrue(schedule.is_active)
        self.assertEqual(schedule.updated_by, self.system_admin)

        config = SMTPConfiguration.objects.create(
            name='Routing mailbox',
            provider='GMAIL',
            username='routing@example.com',
            password='app-password',
            feature_scope=SMTPConfiguration.FEATURE_EMAIL_TO_TICKET,
            incoming_host='imap.gmail.com',
            email_to_ticket_company=self.company_a,
            email_to_ticket_creator=self.user_a,
            email_to_ticket_assignee=self.user_a,
            is_active=True,
        )
        routing_url = reverse('email_routing_rule_save')
        self.client.logout()
        self.client.login(username='admin_a', password='password123')
        self.assertEqual(
            self.client.post(
                routing_url,
                {
                    'smtp_configuration': config.pk,
                    'sender_email': 'CUSTOMER@EXAMPLE.COM',
                    'assignee': self.user_b.pk,
                    'is_active': 'on',
                },
            ).status_code,
            403,
        )

        self.client.logout()
        self.client.login(username='system_admin', password='password123')
        response = self.client.post(
            routing_url,
            {
                'smtp_configuration': config.pk,
                'sender_email': 'CUSTOMER@EXAMPLE.COM',
                'assignee': self.user_b.pk,
                'is_active': 'on',
            },
        )
        self.assertRedirects(response, url)
        rule = InboundEmailRoutingRule.objects.get(
            smtp_configuration=config,
        )
        self.assertEqual(rule.sender_email, 'customer@example.com')
        self.assertEqual(rule.assignee, self.user_b)

        InboundEmailRoutingRule.objects.create(
            smtp_configuration=config,
            sender_email='alpha@example.com',
            assignee=self.user_a,
            is_active=True,
        )
        company_filtered = self.client.get(
            url,
            {'routing_company': str(self.company_b.pk)},
        )
        self.assertEqual(company_filtered.status_code, 200)
        self.assertContains(company_filtered, 'customer@example.com')
        self.assertNotContains(company_filtered, 'alpha@example.com')
        self.assertContains(
            company_filtered,
            'data-routing-filter-active="true"',
        )

        search_filtered = self.client.get(url, {'routing_q': 'alpha@'})
        self.assertEqual(search_filtered.status_code, 200)
        self.assertContains(search_filtered, 'alpha@example.com')
        self.assertNotContains(search_filtered, 'customer@example.com')
        self.assertContains(
            search_filtered,
            'Search sender, mailbox, assignee or company',
        )

    def test_pending_email_approval_rejection_and_attachment_rbac(self):
        import tempfile
        from unittest import mock
        from django.test import override_settings
        from .email_to_ticket import InboundMessage, _queue_email_for_approval
        from .models import InboundEmailReceipt, SMTPConfiguration

        config = SMTPConfiguration.objects.create(
            name='Approval mailbox',
            provider='GMAIL',
            username='approval@example.com',
            password='app-password',
            feature_scope=SMTPConfiguration.FEATURE_EMAIL_TO_TICKET,
            incoming_host='imap.gmail.com',
            email_to_ticket_company=self.company_a,
            email_to_ticket_creator=self.user_a,
            email_to_ticket_assignee=self.user_a,
            is_active=True,
        )
        first_message = InboundMessage(
            uid=b'201',
            message_id='<approval-201@example.com>',
            subject='ปัญหา: เปิดระบบไม่ได้',
            body='ผู้ส่งแจ้งรายละเอียดภาษาไทย',
            sender_name='ลูกค้าทดสอบ',
            sender_email='thai.customer@example.com',
            attachments=[{
                'filename': 'details.txt',
                'content': b'safe attachment',
                'size': 15,
            }],
        )
        second_message = InboundMessage(
            uid=b'202',
            message_id='<approval-202@example.com>',
            subject='Issue: reject this email',
            body='Not a valid support request.',
            sender_email='reject@example.com',
            attachments=[{
                'filename': 'reject.txt',
                'content': b'reject attachment',
                'size': 17,
            }],
        )

        with tempfile.TemporaryDirectory() as media_root, tempfile.TemporaryDirectory() as backup_dir, \
                override_settings(MEDIA_ROOT=media_root), \
                mock.patch('tickets.backup_service.BACKUP_DIR', backup_dir):
            pending, _ = _queue_email_for_approval(config, first_message, ['ปัญหา'])
            pending_attachment = pending.attachments.get()
            download_url = reverse(
                'inbound_email_attachment_download',
                args=[pending_attachment.pk],
            )
            approve_url = reverse('inbound_email_approve', args=[pending.pk])

            self.client.login(username='admin_a', password='password123')
            self.assertEqual(self.client.get(download_url).status_code, 403)
            self.assertEqual(self.client.post(approve_url).status_code, 403)

            self.client.logout()
            self.client.login(username='system_admin', password='password123')
            download_response = self.client.get(download_url)
            self.assertEqual(download_response.status_code, 200)
            self.assertEqual(b''.join(download_response.streaming_content), b'safe attachment')

            ticket_count = Ticket.objects.count()
            response = self.client.post(approve_url)
            pending.refresh_from_db()
            self.assertRedirects(response, reverse('ticket_detail', args=[pending.ticket_id]))
            self.assertEqual(pending.status, InboundEmailReceipt.STATUS_IMPORTED)
            self.assertIsNotNone(pending.ticket)
            self.assertEqual(pending.ticket.title, first_message.subject)
            self.assertEqual(Ticket.objects.count(), ticket_count + 1)

            self.client.post(approve_url)
            self.assertEqual(Ticket.objects.count(), ticket_count + 1)

            rejected, _ = _queue_email_for_approval(config, second_message, ['issue'])
            rejected_attachment = rejected.attachments.get()
            rejected_file_path = rejected_attachment.file.path
            self.assertTrue(os.path.exists(rejected_file_path))
            reject_url = reverse('inbound_email_reject', args=[rejected.pk])
            response = self.client.post(reject_url, {'reason': 'Not a support request'})
            self.assertRedirects(response, reverse('email_timer'))
            rejected.refresh_from_db()
            self.assertEqual(rejected.status, InboundEmailReceipt.STATUS_REJECTED)
            self.assertIsNone(rejected.ticket)
            self.assertFalse(os.path.exists(rejected_file_path))

            timer_response = self.client.get(reverse('email_timer'))
            self.assertContains(timer_response, 'Approval queue')
            self.assertContains(timer_response, 'Email contacts')
            self.assertContains(timer_response, first_message.subject)

    def test_email_timer_command_respects_interval_and_creates_run_log(self):
        import tempfile
        from unittest import mock
        from .models import (
            EmailToTicketRunLog,
            EmailToTicketSchedule,
            SMTPConfiguration,
        )

        config = SMTPConfiguration.objects.create(
            name='Scheduled inbound mailbox',
            provider='GMAIL',
            username='scheduled@example.com',
            password='app-password',
            feature_scope=SMTPConfiguration.FEATURE_EMAIL_TO_TICKET,
            incoming_host='imap.gmail.com',
            email_to_ticket_company=self.company_a,
            email_to_ticket_creator=self.user_a,
            is_active=True,
        )
        schedule = EmailToTicketSchedule.get_solo()
        schedule.interval_minutes = 20
        schedule.is_active = True
        schedule.last_scheduled_run_at = None
        schedule.save()
        result = {
            'success': True,
            'found': 3,
            'pending': 1,
            'imported': 0,
            'skipped': 1,
            'duplicates': 1,
            'failed': 0,
            'error': '',
        }

        with tempfile.TemporaryDirectory() as backup_dir, \
                mock.patch('tickets.backup_service.BACKUP_DIR', backup_dir), \
                mock.patch(
                    'tickets.email_to_ticket_scheduler.import_all_active_email_to_ticket_configs',
                    return_value=[(config, result)],
                ) as importer:
            call_command('process_email_to_tickets', verbosity=0)
            call_command('process_email_to_tickets', verbosity=0)

        importer.assert_called_once_with()
        run_log = EmailToTicketRunLog.objects.get()
        self.assertEqual(run_log.trigger, EmailToTicketRunLog.TRIGGER_TIMER)
        self.assertEqual(run_log.status, EmailToTicketRunLog.STATUS_SUCCESS)
        self.assertEqual(run_log.mailbox_count, 1)
        self.assertEqual(run_log.found_count, 3)
        self.assertEqual(run_log.pending_count, 1)
        self.assertEqual(run_log.imported_count, 0)
        self.assertEqual(run_log.skipped_count, 1)
        self.assertEqual(run_log.duplicate_count, 1)
        schedule.refresh_from_db()
        self.assertIsNotNone(schedule.last_scheduled_run_at)

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
        self.assertIn(CustomUser.CLIENT_STAFF, role_choices)
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
        self.assertIn('New Comment', mail.outbox[0].subject)
        
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
        self.assertIn("must not exceed 10 MB", response.content.decode('utf-8'))

    def test_ticket_delete_manage_access_and_filtering(self):
        # Regular user should be denied access
        self.client.login(username="user_a", password="password123")
        response = self.client.get(reverse('ticket_delete_manage'))
        self.assertEqual(response.status_code, 403)

        # Company admin must not see server disk usage or ticket deletion tools.
        self.client.logout()
        self.client.login(username="admin_a", password="password123")
        response = self.client.get(reverse('ticket_delete_manage'))
        self.assertEqual(response.status_code, 403)

        # System admin can access
        self.client.logout()
        self.client.login(username="system_admin", password="password123")
        self.client.cookies['lang'] = 'th'
        response = self.client.get(reverse('ticket_delete_manage'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delete &amp; Manage Tickets')
        self.assertIn('disk_usage', response.context)
        self.assertGreater(response.context['disk_usage']['total_gb'], 0)

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

    def test_ticket_delete_reports_freed_attachment_megabytes(self):
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            ticket = Ticket.objects.create(
                title='Delete attachment size',
                description='One MB attachment',
                company=self.company_a,
                created_by=self.user_a,
                attachment=SimpleUploadedFile('one_mb.bin', b'x' * (1024 ** 2)),
            )
            attachment_path = ticket.attachment.path
            self.assertTrue(os.path.isfile(attachment_path))
            self.client.login(username='system_admin', password='password123')

            page_response = self.client.get(reverse('ticket_delete_manage'))
            listed_ticket = next(
                item for item in page_response.context['tickets'] if item.pk == ticket.pk
            )
            self.assertEqual(listed_ticket.storage_size_mb, 1.0)
            self.assertAlmostEqual(page_response.context['disk_usage']['ticket_used_mb'], 1.0)
            self.assertContains(page_response, 'Tickets (Attachments)')
            self.assertContains(page_response, '1.00 MB')

            response = self.client.post(
                reverse('ticket_delete', kwargs={'pk': ticket.pk}),
                follow=True,
            )

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, '1.00 MB')
            self.assertFalse(os.path.exists(attachment_path))

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

    def test_status_change_sends_creator_to_and_assignee_cc_only(self):
        self.ticket_a.assigned_to = self.admin_a
        self.ticket_a.save(update_fields=['assigned_to'])
        mail.outbox = []

        self.ticket_a.status = Ticket.STATUS_RESOLVED
        self.ticket_a.save(update_fields=['status'])

        status_emails = [message for message in mail.outbox if 'Status Update' in message.subject]
        self.assertEqual(len(status_emails), 1)
        self.assertEqual(status_emails[0].to, [self.user_a.email])
        self.assertEqual(status_emails[0].cc, [self.admin_a.email])
        self.assertNotIn(self.system_admin.email, status_emails[0].recipients())

        delivery_logs = EmailLog.objects.filter(
            action_type=EmailLog.ACTION_TICKET_UPDATED,
            subject=status_emails[0].subject,
        )
        self.assertEqual(delivery_logs.count(), 2)
        self.assertEqual(delivery_logs.values('delivery_group').distinct().count(), 1)
        self.assertTrue(delivery_logs.get(recipient=self.user_a.email).success)
        self.assertEqual(
            delivery_logs.get(recipient=self.admin_a.email).recipient_type,
            EmailLog.RECIPIENT_CC,
        )

    def test_status_change_applies_notification_rule_to_assignee_cc(self):
        from .models import NotificationConfig

        config = NotificationConfig.objects.create(
            name='Disable assignee status email',
            company=self.company_a,
            status_notification_mode=NotificationConfig.STATUS_NOTIFY_NONE,
        )
        config.target_users.add(self.admin_a)
        self.ticket_a.assigned_to = self.admin_a
        self.ticket_a.save(update_fields=['assigned_to'])
        mail.outbox = []

        self.ticket_a.status = Ticket.STATUS_RESOLVED
        self.ticket_a.save(update_fields=['status'])

        status_email = next(message for message in mail.outbox if 'Status Update' in message.subject)
        self.assertEqual(status_email.to, [self.user_a.email])
        self.assertEqual(status_email.cc, [])
        assignee_log = EmailLog.objects.filter(
            action_type=EmailLog.ACTION_TICKET_UPDATED,
            recipient=self.admin_a.email,
        ).latest('sent_at')
        self.assertFalse(assignee_log.success)
        self.assertEqual(assignee_log.recipient_type, EmailLog.RECIPIENT_CC)
        self.assertIn('Notification Filtered', assignee_log.error_message)

    def test_status_rule_uses_actual_assignee_when_email_is_shared(self):
        from .models import NotificationConfig

        shared_email = self.system_admin.email
        assigned_user = CustomUser.objects.create_user(
            username='assigned_with_shared_email',
            email=shared_email,
            password='password123',
            role=CustomUser.CLIENT_USER,
            company=self.company_a,
        )
        config = NotificationConfig.objects.create(
            name='Block shared-email assignee',
            company=self.company_a,
            status_notification_mode=NotificationConfig.STATUS_NOTIFY_NONE,
        )
        config.target_users.add(assigned_user)
        self.ticket_a.assigned_to = assigned_user
        self.ticket_a.save(update_fields=['assigned_to'])
        mail.outbox = []

        self.ticket_a.status = Ticket.STATUS_RESOLVED
        self.ticket_a.save(update_fields=['status'])

        status_email = next(message for message in mail.outbox if 'Status Update' in message.subject)
        self.assertEqual(status_email.to, [self.user_a.email])
        self.assertEqual(status_email.cc, [])
        assignee_log = EmailLog.objects.filter(
            action_type=EmailLog.ACTION_TICKET_UPDATED,
            recipient=shared_email,
        ).latest('sent_at')
        self.assertFalse(assignee_log.success)
        self.assertEqual(assignee_log.recipient_type, EmailLog.RECIPIENT_CC)
        self.assertIn('Notification Filtered', assignee_log.error_message)

    def test_non_status_ticket_edit_does_not_send_status_email(self):
        mail.outbox = []
        before_count = EmailLog.objects.filter(action_type=EmailLog.ACTION_TICKET_UPDATED).count()
        self.ticket_a.title = 'Title changed without status change'
        self.ticket_a.save(update_fields=['title'])
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            EmailLog.objects.filter(action_type=EmailLog.ACTION_TICKET_UPDATED).count(),
            before_count,
        )

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

        report_email = next(message for message in mail.outbox if 'Monthly Ticket Summary Report' in message.subject)
        self.assertEqual(report_email.to, [self.admin_a.email])
        self.assertEqual(report_email.cc, [self.user_a.email])
        schedule.refresh_from_db()
        self.assertIsNotNone(schedule.last_sent_at)
        self.assertEqual(schedule.last_error, '')

    def test_report_schedule_does_not_mark_zero_delivery_as_sent(self):
        from unittest.mock import patch

        schedule = MonthlyReportSchedule.objects.create(
            name='Zero delivery report',
            company=self.company_a,
            day_of_month=31,
            send_time='17:00',
            created_by=self.admin_a,
        )
        schedule.recipients.add(self.admin_a)

        with patch('tickets.views.EmailMultiAlternatives.send', return_value=0):
            call_command('process_report_schedules', '--schedule-id', schedule.id, '--force')

        schedule.refresh_from_db()
        self.assertIsNone(schedule.last_sent_at)
        self.assertIn('SMTP did not confirm email delivery (sent 0).', schedule.last_error)
        failed_log = EmailLog.objects.filter(
            action_type=EmailLog.ACTION_MONTHLY_REPORT,
            recipient=self.admin_a.email,
            success=False,
        ).latest('sent_at')
        self.assertIn('SMTP did not confirm email delivery (sent 0).', failed_log.error_message)

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
        report_email = next(message for message in mail.outbox if 'Monthly Ticket Summary Report' in message.subject)
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

        self.client.logout()
        self.client.login(username="system_admin", password="password123")
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

    def test_logs_are_restricted_to_system_staff(self):
        email_log = EmailLog.objects.first()

        self.client.login(username='admin_a', password='password123')
        self.assertEqual(self.client.get(reverse('log_list')).status_code, 403)
        self.assertEqual(
            self.client.get(reverse('email_log_detail', args=[email_log.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse('resend_email', args=[email_log.pk])).status_code,
            403,
        )

        system_sub_admin = User.objects.create_user(
            username='system_sub_admin',
            email='subadmin@system.com',
            password='password123',
            role=User.SYSTEM_SUB_ADMIN,
            is_staff=True,
        )
        self.client.logout()
        self.client.login(username=system_sub_admin.username, password='password123')
        self.assertEqual(self.client.get(reverse('log_list')).status_code, 200)
        self.assertEqual(
            self.client.get(reverse('email_log_detail', args=[email_log.pk])).status_code,
            200,
        )

    def test_ticket_automation_changes_due_open_ticket_and_writes_audit_log(self):
        import datetime

        TicketAutomationConfig.objects.create(
            company=self.company_a,
            open_age_value=2,
            open_age_unit=TicketAutomationConfig.UNIT_HOURS,
            created_by=self.admin_a,
        )
        self.ticket_a.assigned_to = self.admin_a
        self.ticket_a.save(update_fields=['assigned_to'])
        Ticket.objects.filter(pk=self.ticket_a.pk).update(
            status_changed_at=timezone.now() - datetime.timedelta(hours=3)
        )
        mail.outbox = []

        call_command('process_ticket_automations')

        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, Ticket.STATUS_IN_PROGRESS)
        audit = TicketAuditLog.objects.filter(ticket=self.ticket_a).latest('created_at')
        self.assertIsNone(audit.actor)
        self.assertEqual(audit.old_status, Ticket.STATUS_OPEN)
        self.assertEqual(audit.new_status, Ticket.STATUS_IN_PROGRESS)
        self.assertIn('Ticket Auto Schedule', audit.details)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user_a.email])
        self.assertEqual(mail.outbox[0].cc, [self.admin_a.email])

    def test_ticket_automation_does_not_change_ticket_before_due_time(self):
        TicketAutomationConfig.objects.create(
            company=self.company_a,
            open_age_value=1,
            open_age_unit=TicketAutomationConfig.UNIT_DAYS,
        )

        call_command('process_ticket_automations')

        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, Ticket.STATUS_OPEN)
        self.assertFalse(TicketAuditLog.objects.filter(
            ticket=self.ticket_a,
            actor__isnull=True,
            new_status=Ticket.STATUS_IN_PROGRESS,
        ).exists())

    def test_ticket_automation_supports_minutes(self):
        import datetime

        TicketAutomationConfig.objects.create(
            company=self.company_a,
            open_age_value=5,
            open_age_unit=TicketAutomationConfig.UNIT_MINUTES,
        )
        Ticket.objects.filter(pk=self.ticket_a.pk).update(
            status_changed_at=timezone.now() - datetime.timedelta(minutes=6)
        )

        call_command('process_ticket_automations')

        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, Ticket.STATUS_IN_PROGRESS)

    def test_ticket_automation_parent_rule_and_local_opt_out(self):
        child = Company.objects.create(name='Company A Branch', parent=self.company_a)
        child_user = User.objects.create_user(
            username='branch_user',
            email='branch@example.com',
            password='password123',
            company=child,
        )
        child_ticket = Ticket.objects.create(
            title='Branch issue',
            description='Waiting too long',
            company=child,
            created_by=child_user,
        )
        parent_rule = TicketAutomationConfig.objects.create(
            company=self.company_a,
            open_age_value=1,
            apply_to_subsidiaries=True,
        )
        self.assertEqual(TicketAutomationConfig.resolve_for_company(child), parent_rule)

        TicketAutomationConfig.objects.create(
            company=child,
            open_age_value=1,
            is_active=False,
        )
        self.assertIsNone(TicketAutomationConfig.resolve_for_company(child))
        call_command('process_ticket_automations', '--ticket-id', child_ticket.pk, '--force')
        child_ticket.refresh_from_db()
        self.assertEqual(child_ticket.status, Ticket.STATUS_OPEN)

    def test_ticket_automation_settings_page_and_create(self):
        self.client.login(username='system_admin', password='password123')
        list_response = self.client.get(reverse('ticket_automation_list'))
        self.assertEqual(list_response.status_code, 200)
        response = self.client.post(reverse('ticket_automation_create'), {
            'company': self.company_a.pk,
            'open_age_value': 6,
            'open_age_unit': TicketAutomationConfig.UNIT_HOURS,
            'is_active': 'on',
            'apply_to_subsidiaries': 'on',
        })
        self.assertRedirects(response, reverse('ticket_automation_list'))
        config = TicketAutomationConfig.objects.get(company=self.company_a)
        self.assertEqual(config.open_age_value, 6)
        self.assertEqual(config.created_by, self.system_admin)

    def test_ticket_automation_is_restricted_to_system_staff(self):
        config = TicketAutomationConfig.objects.create(
            company=self.company_a,
            open_age_value=5,
            open_age_unit=TicketAutomationConfig.UNIT_MINUTES,
        )
        self.client.login(username='admin_a', password='password123')
        self.assertEqual(self.client.get(reverse('ticket_automation_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('ticket_automation_create')).status_code, 403)
        self.assertEqual(
            self.client.get(reverse('ticket_automation_edit', args=[config.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse('ticket_automation_delete', args=[config.pk])).status_code,
            403,
        )
        self.assertTrue(TicketAutomationConfig.objects.filter(pk=config.pk).exists())

        system_sub_admin = User.objects.create_user(
            username='automation_sub_admin',
            email='automation-sub@system.com',
            password='password123',
            role=User.SYSTEM_SUB_ADMIN,
            is_staff=True,
        )
        self.client.logout()
        self.client.login(username=system_sub_admin.username, password='password123')
        self.assertEqual(self.client.get(reverse('ticket_automation_list')).status_code, 200)

    def test_manual_status_change_resets_status_clock(self):
        import datetime

        old_clock = timezone.now() - datetime.timedelta(days=4)
        Ticket.objects.filter(pk=self.ticket_a.pk).update(status_changed_at=old_clock)
        self.ticket_a.refresh_from_db()
        self.ticket_a.status = Ticket.STATUS_IN_PROGRESS
        self.ticket_a.save(update_fields=['status'])
        self.ticket_a.refresh_from_db()
    def test_backup_management_views_and_service(self):
        from unittest import mock
        from tickets.backup_service import perform_full_backup, perform_incremental_backup
        from tickets.models import BackupLog

        # Login as System Admin
        self.client.login(username="system_admin", password="password123")

        # 1. Test Backup Management List View
        response = self.client.get(reverse('backup_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Backup Management")

        # Create sample backup logs of different sizes for filter testing
        small_log = BackupLog.objects.create(
            filename="small_backup.zip",
            file_size_bytes=500 * 1024, # 0.5 MB
            backup_type=BackupLog.TYPE_INCREMENTAL,
            status=BackupLog.STATUS_SUCCESS,
            details="Small test log"
        )
        large_log = BackupLog.objects.create(
            filename="large_backup_archive.tar.gz",
            file_size_bytes=10 * 1024 * 1024, # 10 MB
            backup_type=BackupLog.TYPE_FULL,
            status=BackupLog.STATUS_SUCCESS,
            details="Large test log"
        )

        # Test filtering by minimum size (large files >= 5MB)
        res_min_size = self.client.get(reverse('backup_list'), {'min_size': '5'})
        self.assertEqual(res_min_size.status_code, 200)
        self.assertContains(res_min_size, "large_backup_archive.tar.gz")
        self.assertNotContains(res_min_size, "small_backup.zip")

        # Test filtering by query keyword
        res_search = self.client.get(reverse('backup_list'), {'q': 'small_backup'})
        self.assertEqual(res_search.status_code, 200)
        self.assertContains(res_search, "small_backup.zip")
        self.assertNotContains(res_search, "large_backup_archive.tar.gz")

        # Test sorting by largest size first
        res_sort = self.client.get(reverse('backup_list'), {'sort': 'size_desc'})
        self.assertEqual(res_sort.status_code, 200)
        logs_in_context = list(res_sort.context['backup_logs'])
        self.assertEqual(logs_in_context[0].filename, "large_backup_archive.tar.gz")

        # 2. Test Incremental Backup Service & Trigger View
        res_inc = perform_incremental_backup(hours=2)
        self.assertTrue(res_inc['success'])
        self.assertTrue(BackupLog.objects.filter(backup_type=BackupLog.TYPE_INCREMENTAL).exists())

        with mock.patch(
            'tickets.views.perform_incremental_backup',
            return_value={'success': True, 'details': 'Manual incremental complete.'},
        ) as manual_incremental:
            post_inc = self.client.post(
                reverse('backup_trigger'),
                {'backup_type': 'incremental', 'hours': '168'},
            )
        self.assertRedirects(post_inc, reverse('backup_list'))
        manual_incremental.assert_called_once_with(hours=2)

        # 3. Test Full Backup Service & Trigger View
        res_full = perform_full_backup()
        self.assertTrue(res_full['success'])
        self.assertTrue(BackupLog.objects.filter(backup_type=BackupLog.TYPE_FULL).exists())

        post_full = self.client.post(reverse('backup_trigger'), {'backup_type': 'full'})
        self.assertRedirects(post_full, reverse('backup_list'))

        # 4. Test Download Backup View
        log_to_download = BackupLog.objects.first()
        dl_res = self.client.get(reverse('backup_download', args=[log_to_download.id]))
        self.assertIn(dl_res.status_code, [200, 302])
        if hasattr(dl_res, 'file_to_stream') and dl_res.file_to_stream and not dl_res.file_to_stream.closed:
            dl_res.file_to_stream.close()
        del dl_res
        import gc; gc.collect()
        connection.ensure_connection()

        # 5. Test Delete Backup Log View
        log_to_delete = BackupLog.objects.first()
        log_id = log_to_delete.id
        post_del = self.client.post(reverse('backup_delete', args=[log_id]))
        self.assertRedirects(post_del, reverse('backup_list'))
        self.assertFalse(BackupLog.objects.filter(pk=log_id).exists())

    def test_empty_backup_record_has_delete_button_and_can_be_deleted(self):
        from tickets.models import BackupLog

        empty_log = BackupLog.objects.create(
            filename="incremental_no_changes.tar.gz",
            file_size_bytes=0,
            backup_type=BackupLog.TYPE_INCREMENTAL,
            status=BackupLog.STATUS_SUCCESS,
            details="No tickets changed during this backup window.",
        )
        self.client.login(username="system_admin", password="password123")

        response = self.client.get(reverse('backup_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No data file")
        self.assertContains(response, "Delete empty record")
        self.assertContains(
            response,
            reverse('backup_delete', args=[empty_log.pk]),
        )
        self.assertNotContains(
            response,
            reverse('backup_download', args=[empty_log.pk]),
        )

        delete_response = self.client.post(
            reverse('backup_delete', args=[empty_log.pk]),
        )
        self.assertRedirects(delete_response, reverse('backup_list'))
        self.assertFalse(BackupLog.objects.filter(pk=empty_log.pk).exists())

    def test_system_admin_can_delete_all_zero_mb_backup_records_safely(self):
        import os
        import tempfile
        from unittest import mock
        from tickets.models import BackupLog

        empty_with_file = BackupLog.objects.create(
            filename='empty_archive.zip',
            file_size_bytes=0,
            backup_type=BackupLog.TYPE_INCREMENTAL,
            status=BackupLog.STATUS_SUCCESS,
        )
        empty_without_file = BackupLog.objects.create(
            filename='missing_empty_archive.zip',
            file_size_bytes=0,
            backup_type=BackupLog.TYPE_INCREMENTAL,
            status=BackupLog.STATUS_SUCCESS,
        )
        non_empty = BackupLog.objects.create(
            filename='keep_archive.zip',
            file_size_bytes=1024,
            backup_type=BackupLog.TYPE_FULL,
            status=BackupLog.STATUS_SUCCESS,
        )

        with tempfile.TemporaryDirectory() as backup_dir, mock.patch(
            'tickets.backup_service.BACKUP_DIR',
            backup_dir,
        ):
            empty_path = os.path.join(backup_dir, empty_with_file.filename)
            with open(empty_path, 'wb'):
                pass

            self.client.login(username='system_admin', password='password123')
            page = self.client.get(reverse('backup_list'))
            self.assertContains(page, 'Delete all 0 MB (2)')
            self.assertContains(page, reverse('backup_delete_zero_mb'))

            response = self.client.post(reverse('backup_delete_zero_mb'))
            self.assertRedirects(response, reverse('backup_list'))
            self.assertFalse(os.path.exists(empty_path))

        self.assertFalse(BackupLog.objects.filter(pk=empty_with_file.pk).exists())
        self.assertFalse(BackupLog.objects.filter(pk=empty_without_file.pk).exists())
        self.assertTrue(BackupLog.objects.filter(pk=non_empty.pk).exists())

        forbidden_record = BackupLog.objects.create(
            filename='must_remain.zip',
            file_size_bytes=0,
            backup_type=BackupLog.TYPE_INCREMENTAL,
            status=BackupLog.STATUS_SUCCESS,
        )
        self.client.logout()
        self.client.login(username='user_a', password='password123')
        self.assertEqual(
            self.client.post(reverse('backup_delete_zero_mb')).status_code,
            403,
        )
        self.assertTrue(BackupLog.objects.filter(pk=forbidden_record.pk).exists())

    def test_system_data_backup_keeps_configuration_and_removes_ticket_rows(self):
        import json
        import os
        import sqlite3
        import tarfile
        import tempfile
        from pathlib import Path
        from unittest import mock
        from django.test import override_settings
        from tickets.backup_service import perform_system_data_backup
        from tickets.models import BackupLog

        with tempfile.TemporaryDirectory() as base_dir, tempfile.TemporaryDirectory() as backup_dir:
            source_db = os.path.join(base_dir, 'db.sqlite3')
            raw_sqlite_conn = sqlite3.connect(source_db)
            try:
                raw_sqlite_conn.execute('PRAGMA foreign_keys = ON')
                raw_sqlite_conn.executescript(
                    '''
                    CREATE TABLE tickets_company (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL
                    );
                    CREATE TABLE tickets_ticket (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL
                    );
                    CREATE TABLE tickets_ticketcomment (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ticket_id INTEGER NOT NULL REFERENCES tickets_ticket(id) ON DELETE CASCADE,
                        content TEXT NOT NULL
                    );
                    CREATE TABLE tickets_commentattachment (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        comment_id INTEGER NOT NULL REFERENCES tickets_ticketcomment(id) ON DELETE CASCADE
                    );
                    CREATE TABLE tickets_ticketauditlog (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ticket_id INTEGER NOT NULL REFERENCES tickets_ticket(id) ON DELETE CASCADE
                    );
                    CREATE TABLE tickets_inappnotification (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ticket_id INTEGER REFERENCES tickets_ticket(id) ON DELETE SET NULL,
                        title TEXT NOT NULL
                    );
                    CREATE TABLE tickets_inboundemailreceipt (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ticket_id INTEGER REFERENCES tickets_ticket(id) ON DELETE SET NULL,
                        subject TEXT NOT NULL
                    );
                    INSERT INTO tickets_company(name) VALUES ('Preserved Company');
                    INSERT INTO tickets_ticket(title) VALUES ('Must be removed');
                    INSERT INTO tickets_ticketcomment(ticket_id, content) VALUES (1, 'Must cascade');
                    INSERT INTO tickets_commentattachment(comment_id) VALUES (1);
                    INSERT INTO tickets_ticketauditlog(ticket_id) VALUES (1);
                    INSERT INTO tickets_inappnotification(ticket_id, title) VALUES (1, 'Ticket alert');
                    INSERT INTO tickets_inboundemailreceipt(ticket_id, subject) VALUES (1, 'Preserved log');
                    '''
                )
                raw_sqlite_conn.commit()
            finally:
                raw_sqlite_conn.close()

            with override_settings(
                BASE_DIR=Path(base_dir),
                DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': source_db}},
            ), mock.patch(
                'tickets.backup_service.BACKUP_DIR',
                backup_dir,
            ):
                result = perform_system_data_backup()

            self.assertTrue(result['success'])
            self.assertEqual(result['removed_ticket_count'], 1)
            self.assertEqual(result['log'].backup_type, BackupLog.TYPE_SYSTEM)

            extracted_db = os.path.join(base_dir, 'restored-system.sqlite3')
            with tarfile.open(result['file_path'], 'r:gz') as archive:
                self.assertIn('db.sqlite3', archive.getnames())
                self.assertIn('backup_manifest.json', archive.getnames())
                with open(extracted_db, 'wb') as destination:
                    destination.write(archive.extractfile('db.sqlite3').read())
                manifest = json.loads(
                    archive.extractfile('backup_manifest.json').read().decode('utf-8')
                )

            restored = sqlite3.connect(extracted_db)
            try:
                self.assertEqual(restored.execute('SELECT COUNT(*) FROM tickets_ticket').fetchone()[0], 0)
                self.assertEqual(restored.execute('SELECT COUNT(*) FROM tickets_ticketcomment').fetchone()[0], 0)
                self.assertEqual(restored.execute('SELECT COUNT(*) FROM tickets_commentattachment').fetchone()[0], 0)
                self.assertEqual(restored.execute('SELECT COUNT(*) FROM tickets_ticketauditlog').fetchone()[0], 0)
                self.assertEqual(restored.execute('SELECT COUNT(*) FROM tickets_inappnotification').fetchone()[0], 0)
                self.assertEqual(restored.execute('SELECT name FROM tickets_company').fetchone()[0], 'Preserved Company')
                self.assertIsNone(
                    restored.execute('SELECT ticket_id FROM tickets_inboundemailreceipt').fetchone()[0]
                )
            finally:
                restored.close()
            self.assertEqual(manifest['removed_ticket_count'], 1)
            self.assertEqual(manifest['backup_type'], 'SYSTEM_DATA_NO_TICKETS')

    def test_system_backup_uses_configured_timer_and_supports_manual_run(self):
        import datetime
        from unittest import mock
        from django.core.management import call_command
        from tickets.models import BackupLog, BackupSchedule

        schedule = BackupSchedule.get_solo()
        schedule.system_interval_minutes = 4320
        schedule.save(update_fields=['system_interval_minutes', 'updated_at'])

        recent_log = BackupLog.objects.create(
            filename='recent_system_data.tar.gz',
            file_size_bytes=1024,
            backup_type=BackupLog.TYPE_SYSTEM,
            status=BackupLog.STATUS_SUCCESS,
        )
        successful_result = {
            'success': True,
            'details': 'System data backed up without Tickets.',
        }
        with mock.patch(
            'tickets.management.commands.run_weekly_system_backup.perform_system_data_backup',
            return_value=successful_result,
        ) as scheduled_backup:
            call_command('run_weekly_system_backup', verbosity=0)
            scheduled_backup.assert_not_called()
            BackupLog.objects.filter(pk=recent_log.pk).update(
                created_at=timezone.now() - datetime.timedelta(days=4),
            )
            call_command('run_weekly_system_backup', verbosity=0)
            scheduled_backup.assert_called_once_with()
            schedule.system_is_active = False
            schedule.save(update_fields=['system_is_active', 'updated_at'])
            scheduled_backup.reset_mock()
            call_command('run_weekly_system_backup', verbosity=0)
            scheduled_backup.assert_not_called()
            call_command('run_weekly_system_backup', '--force', verbosity=0)
            scheduled_backup.assert_called_once_with()

        self.client.login(username='system_admin', password='password123')
        backup_page = self.client.get(reverse('backup_list'))
        self.assertContains(backup_page, 'Run Manually: System Data (No Tickets)')
        self.assertContains(backup_page, 'Automatic Backup Timer')
        self.assertContains(backup_page, 'Every 3 days')
        filtered_page = self.client.get(reverse('backup_list'), {'type': 'SYSTEM'})
        self.assertEqual(filtered_page.status_code, 200)
        self.assertEqual(filtered_page.context['filtered_count'], 1)
        with mock.patch(
            'tickets.views.perform_system_data_backup',
            return_value=successful_result,
        ) as manual_backup:
            response = self.client.post(
                reverse('backup_trigger'),
                {'backup_type': 'system'},
            )
        self.assertRedirects(response, reverse('backup_list'))
        manual_backup.assert_called_once_with()
        self.assertTrue(BackupLog.objects.filter(pk=recent_log.pk).exists())

    def test_backup_timer_settings_are_validated_and_restricted_to_system_admin(self):
        from tickets.models import BackupSchedule

        schedule = BackupSchedule.get_solo()
        self.assertEqual(schedule.incremental_interval_minutes, 120)
        self.assertEqual(schedule.full_interval_minutes, 1440)
        self.assertEqual(schedule.system_interval_minutes, 10080)

        self.client.login(username='system_admin', password='password123')
        page = self.client.get(reverse('backup_list'))
        self.assertContains(page, 'Save Backup Timer Settings')
        self.assertContains(page, 'Allowed range: 1 hour to 1 day')
        self.assertContains(page, 'Failed jobs wait 30 minutes before retrying')

        response = self.client.post(reverse('backup_schedule_update'), {
            'incremental_interval_minutes': '360',
            'incremental_is_active': 'on',
            'full_interval_minutes': '4320',
            'system_interval_minutes': '20160',
            'system_is_active': 'on',
        })
        self.assertRedirects(response, reverse('backup_list'))
        schedule.refresh_from_db()
        self.assertEqual(schedule.incremental_interval_minutes, 360)
        self.assertTrue(schedule.incremental_is_active)
        self.assertEqual(schedule.full_interval_minutes, 4320)
        self.assertFalse(schedule.full_is_active)
        self.assertEqual(schedule.system_interval_minutes, 20160)
        self.assertTrue(schedule.system_is_active)
        self.assertEqual(schedule.updated_by, self.system_admin)

        invalid_response = self.client.post(reverse('backup_schedule_update'), {
            'incremental_interval_minutes': '10',
            'incremental_is_active': 'on',
            'full_interval_minutes': '1440',
            'full_is_active': 'on',
            'system_interval_minutes': '10080',
            'system_is_active': 'on',
        })
        self.assertRedirects(invalid_response, reverse('backup_list'))
        schedule.refresh_from_db()
        self.assertEqual(schedule.incremental_interval_minutes, 360)

        sub_admin = User.objects.create_user(
            username='backup_sub_admin',
            email='backup-sub@example.com',
            password='password123',
            role=User.SYSTEM_SUB_ADMIN,
            is_staff=True,
        )
        self.client.logout()
        self.client.login(username=sub_admin.username, password='password123')
        read_only_page = self.client.get(reverse('backup_list'))
        self.assertContains(read_only_page, 'Timer settings are read-only')
        forbidden = self.client.post(reverse('backup_schedule_update'), {
            'incremental_interval_minutes': '60',
            'full_interval_minutes': '1440',
            'system_interval_minutes': '1440',
        })
        self.assertEqual(forbidden.status_code, 403)
        schedule.refresh_from_db()
        self.assertEqual(schedule.incremental_interval_minutes, 360)

    def test_incremental_backup_command_uses_timer_disable_and_failure_backoff(self):
        import datetime
        from unittest import mock
        from django.core.management import call_command
        from tickets.models import BackupLog, BackupSchedule

        schedule = BackupSchedule.get_solo()
        schedule.incremental_interval_minutes = 360
        schedule.save(update_fields=['incremental_interval_minutes', 'updated_at'])
        recent_log = BackupLog.objects.create(
            filename='recent_incremental.zip',
            file_size_bytes=1024,
            backup_type=BackupLog.TYPE_INCREMENTAL,
            status=BackupLog.STATUS_SUCCESS,
        )
        successful_result = {'success': True, 'details': 'Incremental complete.'}
        with mock.patch(
            'tickets.management.commands.run_2hr_backup.perform_incremental_backup',
            return_value=successful_result,
        ) as incremental_backup:
            call_command('run_2hr_backup', verbosity=0)
            incremental_backup.assert_not_called()

            BackupLog.objects.filter(pk=recent_log.pk).update(
                created_at=timezone.now() - datetime.timedelta(hours=7),
            )
            call_command('run_2hr_backup', verbosity=0)
            incremental_backup.assert_called_once_with(hours=6)

            failed_log = BackupLog.objects.create(
                filename='failed_incremental.zip',
                file_size_bytes=0,
                backup_type=BackupLog.TYPE_INCREMENTAL,
                status=BackupLog.STATUS_FAILED,
            )
            incremental_backup.reset_mock()
            call_command('run_2hr_backup', verbosity=0)
            incremental_backup.assert_not_called()

            BackupLog.objects.filter(pk=failed_log.pk).update(
                created_at=timezone.now() - datetime.timedelta(minutes=31),
            )
            call_command('run_2hr_backup', verbosity=0)
            incremental_backup.assert_called_once_with(hours=6)

            incremental_backup.reset_mock()
            schedule.incremental_is_active = False
            schedule.save(update_fields=['incremental_is_active', 'updated_at'])
            call_command('run_2hr_backup', verbosity=0)
            incremental_backup.assert_not_called()

            call_command('run_2hr_backup', '--force', '--hours', '8', verbosity=0)
            incremental_backup.assert_called_once_with(hours=8)

    def test_full_backup_command_uses_configured_timer_and_disable_switch(self):
        import datetime
        from unittest import mock
        from django.core.management import call_command
        from tickets.models import BackupLog, BackupSchedule

        schedule = BackupSchedule.get_solo()
        schedule.full_interval_minutes = 4320
        schedule.save(update_fields=['full_interval_minutes', 'updated_at'])
        recent_log = BackupLog.objects.create(
            filename='recent_full.tar.gz',
            file_size_bytes=1024,
            backup_type=BackupLog.TYPE_FULL,
            status=BackupLog.STATUS_SUCCESS,
        )
        successful_result = {'success': True, 'details': 'Full backup complete.'}
        with mock.patch(
            'tickets.management.commands.run_2hr_backup.perform_full_backup',
            return_value=successful_result,
        ) as full_backup:
            call_command('run_2hr_backup', '--full', verbosity=0)
            full_backup.assert_not_called()

            BackupLog.objects.filter(pk=recent_log.pk).update(
                created_at=timezone.now() - datetime.timedelta(days=4),
            )
            call_command('run_2hr_backup', '--full', verbosity=0)
            full_backup.assert_called_once_with()

            full_backup.reset_mock()
            schedule.full_is_active = False
            schedule.save(update_fields=['full_is_active', 'updated_at'])
            call_command('run_2hr_backup', '--full', verbosity=0)
            full_backup.assert_not_called()

            call_command('run_2hr_backup', '--full', '--force', verbosity=0)
            full_backup.assert_called_once_with()

    def test_client_user_can_only_read_own_tickets_and_cannot_update(self):
        coworker_ticket = Ticket.objects.create(
            title="Private coworker ticket",
            description="Must not be exposed to another regular user",
            company=self.company_a,
            created_by=self.admin_a,
        )
        self.client.login(username="user_a", password="password123")

        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertNotContains(dashboard, coworker_ticket.title)
        self.assertEqual(
            self.client.get(reverse('ticket_detail', args=[coworker_ticket.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse('ticket_update', args=[self.ticket_a.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse('ticket_update', args=[self.ticket_a.pk]),
                {'status': Ticket.STATUS_CLOSED},
            ).status_code,
            403,
        )

    def test_client_staff_can_view_and_update_company_ticket(self):
        staff = User.objects.create_user(
            username="company_staff",
            email="staff@company-a.com",
            password="password123",
            role=User.CLIENT_STAFF,
            company=self.company_a,
        )
        self.client.login(username=staff.username, password="password123")
        self.assertEqual(
            self.client.get(reverse('ticket_detail', args=[self.ticket_a.pk])).status_code,
            200,
        )
        response = self.client.post(
            reverse('ticket_update', args=[self.ticket_a.pk]),
            {
                'title': self.ticket_a.title,
                'description': self.ticket_a.description,
                'priority': self.ticket_a.priority,
                'status': Ticket.STATUS_IN_PROGRESS,
                'category': self.ticket_a.category,
                'assigned_to': staff.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, Ticket.STATUS_IN_PROGRESS)

    def test_client_user_cannot_manage_notification_configuration(self):
        from .models import NotificationConfig

        config = NotificationConfig.objects.create(
            name="Admin only",
            company=self.company_a,
        )
        self.client.login(username="user_a", password="password123")

        self.assertEqual(self.client.get(reverse('notification_config_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('notification_config_create')).status_code, 403)
        self.assertEqual(
            self.client.get(reverse('notification_config_edit', args=[config.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse('notification_config_delete', args=[config.pk])).status_code,
            403,
        )
        self.assertTrue(NotificationConfig.objects.filter(pk=config.pk).exists())

    def test_deployment_confirmation_requires_ticket_staff_and_post(self):
        self.ticket_a.status = Ticket.STATUS_DEPLOYMENT_REQUESTED
        self.ticket_a.save(update_fields=['status'])

        self.client.login(username="user_a", password="password123")
        self.assertEqual(
            self.client.post(reverse('confirm_deployment', args=[self.ticket_a.pk])).status_code,
            403,
        )
        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, Ticket.STATUS_DEPLOYMENT_REQUESTED)

        self.client.login(username="admin_a", password="password123")
        self.assertEqual(
            self.client.get(reverse('confirm_deployment', args=[self.ticket_a.pk])).status_code,
            405,
        )
        self.ticket_a.refresh_from_db()
        self.assertEqual(self.ticket_a.status, Ticket.STATUS_DEPLOYMENT_REQUESTED)

    def test_render_ticket_description_formatting(self):
        from tickets.templatetags.ticket_extras import render_ticket_description

        raw_desc = (
            "ตัดโล[https://res.public.onedcn.static.microsoft.com/assets/fluentui-resources/1.1.0/app-min/assets/item-types/24_1.5x/xlsx.png]"
            "ค่าใช้จ่าย.xlsx<https://systemoneitcoth-my.sharepoint.com/:x:/g/personal/test_file.xlsx>\n"
            "**Bold text** and *italic text* and `code` and <https://example.com/link>"
        )
        rendered = render_ticket_description(raw_desc)
        self.assertIn('Open File / Sharepoint', rendered)
        self.assertIn('ค่าใช้จ่าย.xlsx', rendered)
        self.assertIn('strong class="font-bold text-white"', rendered)
        self.assertIn('<a href="https://example.com/link"', rendered)
        self.assertIn('🔗', rendered)

    def test_recipient_preview_api_endpoint(self):
        self.client.force_login(self.admin_a)
        
        # Test preview API for comment
        resp = self.client.get(
            reverse('ticket_email_preview_recipients', args=[self.ticket_a.pk]),
            {'action_type': 'comment'}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('recipients', data)
        self.assertTrue(len(data['recipients']) > 0)

        # Test preview API for update with custom status
        resp_update = self.client.get(
            reverse('ticket_email_preview_recipients', args=[self.ticket_a.pk]),
            {'action_type': 'update', 'status': Ticket.STATUS_RESOLVED}
        )
        self.assertEqual(resp_update.status_code, 200)
        data_update = resp_update.json()
        self.assertEqual(data_update['status'], 'success')
        self.assertEqual(data_update['new_status'], Ticket.STATUS_RESOLVED)

        # A tenant administrator cannot use the preview endpoint to enumerate
        # an assignee or email address from another company.
        cross_tenant = self.client.get(
            reverse('ticket_email_preview_recipients', args=[self.ticket_a.pk]),
            {'action_type': 'update', 'assigned_to': self.user_b.pk},
        )
        self.assertEqual(cross_tenant.status_code, 400)
        self.assertNotIn(self.user_b.email, cross_tenant.content.decode('utf-8'))

        self.client.force_login(self.user_a)
        unauthorized_update = self.client.get(
            reverse('ticket_email_preview_recipients', args=[self.ticket_a.pk]),
            {'action_type': 'update'},
        )
        self.assertEqual(unauthorized_update.status_code, 403)



    def test_one_time_email_recipient_preview_and_customization(self):
        from tickets.models import EmailLog

        self.client.force_login(self.admin_a)
        
        # 1. Test ticket detail page context contains default_recipients
        detail_resp = self.client.get(reverse('ticket_detail', args=[self.ticket_a.pk]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertIn('default_recipients', detail_resp.context)
        recipients_list = detail_resp.context['default_recipients']
        self.assertTrue(len(recipients_list) > 0)
        self.assertIn('selected_recipients', detail_resp.content.decode('utf-8'))

        # 2. Test posting a comment with custom extra recipient
        extra_email = "extra.auditor@company-a.com"
        comment_resp = self.client.post(
            reverse('ticket_detail', args=[self.ticket_a.pk]),
            {
                'content': 'Test comment with extra email recipient',
                'selected_recipients': [self.user_a.email],
                'extra_recipients': extra_email,
            }
        )
        self.assertEqual(comment_resp.status_code, 302)

        # Verify EmailLog was created for extra recipient
        logs = EmailLog.objects.filter(recipient=extra_email)
        self.assertTrue(logs.exists())

        # 3. Test ticket update with one-time custom recipient
        extra_status_email = "status.reviewer@company-a.com"
        update_resp = self.client.post(
            reverse('ticket_update', args=[self.ticket_a.pk]),
            {
                'title': self.ticket_a.title,
                'description': self.ticket_a.description,
                'priority': self.ticket_a.priority,
                'status': Ticket.STATUS_IN_PROGRESS,
                'ticket_category': self.ticket_a.ticket_category_id or '',
                'selected_recipients': [self.admin_a.email],
                'extra_recipients': extra_status_email,
            }
        )
        self.assertEqual(update_resp.status_code, 302)
        status_logs = EmailLog.objects.filter(recipient=extra_status_email)
        self.assertTrue(status_logs.exists())

    def test_regular_user_cannot_inject_one_time_email_recipient(self):
        from tickets.models import EmailLog

        external_email = 'outside-recipient@example.net'
        self.client.force_login(self.user_a)
        response = self.client.post(
            reverse('ticket_detail', args=[self.ticket_a.pk]),
            {
                'content': 'A normal customer follow-up.',
                'selected_recipients': [external_email],
                'extra_recipients': external_email,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(EmailLog.objects.filter(recipient=external_email).exists())

    def test_non_superuser_system_admin_cannot_edit_django_superuser(self):
        app_admin = User.objects.create_user(
            username="app_admin_only",
            email="app-admin@example.com",
            password="password123",
            role=User.SYSTEM_ADMIN,
            is_staff=True,
            is_superuser=False,
        )
        root_user = User.objects.create_superuser(
            username="root_account",
            email="root@example.com",
            password="Root-password-2026!",
        )
        self.client.login(username=app_admin.username, password="password123")

        response = self.client.get(reverse('user_update', args=[root_user.pk]))
        self.assertEqual(response.status_code, 404)
        root_user.refresh_from_db()
        self.assertTrue(root_user.check_password("Root-password-2026!"))

    def test_attachment_download_requires_ticket_visibility(self):
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from .models import TicketAttachment

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            attachment = TicketAttachment.objects.create(
                ticket=self.ticket_a,
                file=SimpleUploadedFile("private.txt", b"private attachment"),
                filename="private.txt",
                file_size=18,
            )
            url = reverse('ticket_attachment_download', args=[attachment.pk])

            self.assertEqual(self.client.get(url).status_code, 302)
            self.client.login(username="user_b", password="password123")
            self.assertEqual(self.client.get(url).status_code, 404)
            self.client.login(username="user_a", password="password123")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'application/octet-stream')
            self.assertIn('attachment;', response['Content-Disposition'])
            self.assertEqual(self.client.get(attachment.file.url).status_code, 404)
            response.close()

    def test_ticket_automation_update_returns_redirect_and_saves(self):
        config = TicketAutomationConfig.objects.create(
            company=self.company_a,
            open_age_value=2,
            open_age_unit=TicketAutomationConfig.UNIT_HOURS,
        )
        self.client.login(username="system_admin", password="password123")
        response = self.client.post(
            reverse('ticket_automation_edit', args=[config.pk]),
            {
                'company': self.company_a.pk,
                'open_age_value': 7,
                'open_age_unit': TicketAutomationConfig.UNIT_HOURS,
                'is_active': 'on',
            },
        )
        self.assertRedirects(response, reverse('ticket_automation_list'))
        config.refresh_from_db()
        self.assertEqual(config.open_age_value, 7)

    def test_incremental_backup_includes_new_comment_on_old_ticket(self):
        import datetime
        import json
        import tempfile
        import zipfile
        from unittest import mock
        from .backup_service import perform_incremental_backup
        from .models import TicketComment

        old_time = timezone.now() - datetime.timedelta(days=3)
        Ticket.objects.filter(pk=self.ticket_a.pk).update(
            created_at=old_time,
            updated_at=old_time,
        )
        TicketComment.objects.create(
            ticket=self.ticket_a,
            author=self.admin_a,
            content="A recent comment on an old ticket",
        )

        with tempfile.TemporaryDirectory() as backup_dir, mock.patch(
            'tickets.backup_service.BACKUP_DIR',
            backup_dir,
        ):
            result = perform_incremental_backup(hours=2)
            self.assertTrue(result['success'])
            with zipfile.ZipFile(result['file_path']) as archive:
                payload = json.loads(archive.read('tickets.json').decode('utf-8'))
            self.assertIn(self.ticket_a.pk, [item['id'] for item in payload])

    def test_backup_path_rejects_parent_directory_traversal(self):
        import tempfile
        from unittest import mock
        from .backup_service import get_backup_file_path

        with tempfile.TemporaryDirectory() as backup_dir, mock.patch(
            'tickets.backup_service.BACKUP_DIR',
            backup_dir,
        ):
            self.assertIsNone(get_backup_file_path('../.env'))

    def test_imported_email_sender_is_pinned_to_ticket_and_logged_per_message(self):
        from .models import InAppNotification, InboundEmailReceipt, SMTPConfiguration

        config = SMTPConfiguration.objects.create(
            name='Support inbox',
            provider='GMAIL',
            username='support@example.com',
            password='app-password',
        )
        imported_ticket = Ticket.objects.create(
            title='Issue: Cannot sign in',
            description='Login returns an error.',
            company=self.company_a,
            created_by=self.user_a,
            assigned_to=self.user_a,
            custom_fields_data={
                'email_to_ticket': {
                    'source': 'EMAIL_TO_TICKET',
                    'sender_name': 'External Customer',
                    'sender_email': 'customer@example.com',
                    'message_id': '<imported@example.com>',
                },
            },
        )
        InboundEmailReceipt.objects.create(
            smtp_configuration=config,
            message_id='<imported@example.com>',
            sender_name='External Customer',
            sender_email='customer@example.com',
            subject=imported_ticket.title,
            status=InboundEmailReceipt.STATUS_IMPORTED,
            details=f'Imported as Ticket #{imported_ticket.pk}.',
            ticket=imported_ticket,
        )
        InboundEmailReceipt.objects.create(
            smtp_configuration=config,
            message_id='<skipped@example.com>',
            sender_name='Newsletter Robot',
            sender_email='news@example.com',
            subject='Weekly newsletter',
            status=InboundEmailReceipt.STATUS_SKIPPED,
            details='Skipped because the subject did not match any issue keyword.',
        )

        self.client.login(username='user_a', password='password123')
        detail_response = self.client.get(reverse('ticket_detail', args=[imported_ticket.pk]))
        self.assertContains(detail_response, 'Email sender')
        self.assertContains(detail_response, 'External Customer')
        self.assertContains(detail_response, 'customer@example.com')
        self.assertContains(detail_response, self.user_a.email)
        self.assertContains(detail_response, self.user_a.get_role_display())
        self.assertNotContains(detail_response, "'source': 'EMAIL_TO_TICKET'")
        self.assertTrue(InAppNotification.objects.filter(
            recipient=self.user_a,
            ticket=imported_ticket,
            event_type=InAppNotification.EVENT_TICKET_CREATED,
        ).exists())

        self.client.logout()
        self.client.login(username='system_admin', password='password123')
        timer_response = self.client.get(reverse('email_timer'))
        self.assertContains(timer_response, 'Email import details')
        self.assertContains(timer_response, 'Issue: Cannot sign in')
        self.assertContains(timer_response, 'Weekly newsletter')
        self.assertContains(timer_response, 'External Customer')
        self.assertContains(timer_response, 'Newsletter Robot')
        self.assertContains(timer_response, 'Imported as Ticket')
        self.assertContains(timer_response, 'did not match any issue keyword')

    def test_notification_bell_is_private_and_marks_notifications_read(self):
        from .models import InAppNotification

        own_notification = InAppNotification.objects.create(
            recipient=self.user_a,
            ticket=self.ticket_a,
            event_type=InAppNotification.EVENT_STATUS_CHANGED,
            title='Your private ticket update',
            message='Ticket is now In Progress',
        )
        InAppNotification.objects.create(
            recipient=self.user_b,
            event_type=InAppNotification.EVENT_TICKET_CREATED,
            title='Another tenant private notification',
            message='Must not be visible to Company A.',
        )

        self.client.login(username='user_a', password='password123')
        response = self.client.get(reverse('notification_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Your private ticket update')
        self.assertNotContains(response, 'Another tenant private notification')

        response = self.client.get(reverse('notification_open', args=[own_notification.pk]))
        self.assertRedirects(response, reverse('ticket_detail', args=[self.ticket_a.pk]))
        own_notification.refresh_from_db()
        self.assertTrue(own_notification.is_read)
        self.assertIsNotNone(own_notification.read_at)

        unread = InAppNotification.objects.create(
            recipient=self.user_a,
            event_type=InAppNotification.EVENT_COMMENT_ADDED,
            title='Another update',
        )
        response = self.client.post(reverse('notification_read_all'))
        self.assertRedirects(response, reverse('notification_list'))
        unread.refresh_from_db()
        self.assertTrue(unread.is_read)

        other_notification = InAppNotification.objects.filter(recipient=self.user_b).first()
        self.assertEqual(
            self.client.get(reverse('notification_open', args=[other_notification.pk])).status_code,
            404,
        )






class SecurityBaselineTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Security Tenant')
        self.user = User.objects.create_user(
            username='security_user',
            email='security@example.com',
            password='StrongPassword123!',
            company=self.company,
            role=User.CLIENT_USER,
        )
        self.system_admin = User.objects.create_user(
            username='security_admin',
            email='security-admin@example.com',
            password='StrongPassword123!',
            role=User.SYSTEM_ADMIN,
            is_staff=True,
        )

    def test_login_is_throttled_and_security_events_are_logged(self):
        from .models import SecurityAuditLog

        for attempt in range(5):
            response = self.client.post(reverse('login'), {
                'username': self.user.username,
                'password': 'wrong-password',
            })
            self.assertEqual(response.status_code, 429 if attempt == 4 else 200)

        blocked = self.client.post(reverse('login'), {
            'username': self.user.username,
            'password': 'StrongPassword123!',
        })
        self.assertEqual(blocked.status_code, 429)
        self.assertIn('Retry-After', blocked)
        self.assertEqual(SecurityAuditLog.objects.filter(event_type='LOGIN_FAILURE').count(), 5)
        self.assertTrue(SecurityAuditLog.objects.filter(event_type='LOGIN_BLOCKED').exists())

    def test_logout_requires_post_and_writes_audit_event(self):
        from .models import SecurityAuditLog

        self.client.login(username=self.user.username, password='StrongPassword123!')
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        response = self.client.post(reverse('logout'))
        self.assertRedirects(response, reverse('login'))
        self.assertTrue(SecurityAuditLog.objects.filter(
            event_type='LOGOUT', actor=self.user,
        ).exists())

    def test_smtp_password_is_encrypted_at_rest(self):
        from .models import SMTPConfiguration

        configuration = SMTPConfiguration.objects.create(
            name='Encrypted mailbox', provider='GMAIL',
            username='mailbox@example.com', password='smtp-app-secret',
        )
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT password FROM tickets_smtpconfiguration WHERE id = %s',
                [configuration.pk],
            )
            raw_password = cursor.fetchone()[0]
        self.assertTrue(raw_password.startswith('enc:v1:'))
        self.assertNotIn('smtp-app-secret', raw_password)
        configuration.refresh_from_db()
        self.assertEqual(configuration.password, 'smtp-app-secret')

    def test_attachment_content_is_checked_not_only_extension(self):
        from .security import validate_attachment

        fake_image = SimpleUploadedFile('invoice.jpg', b'MZ executable content')
        real_pdf = SimpleUploadedFile('report.pdf', b'%PDF-1.7\nminimal')
        self.assertIn('does not match', validate_attachment(fake_image))
        self.assertIsNone(validate_attachment(real_pdf))

    def test_security_headers_and_open_redirect_protection(self):
        from .security import safe_redirect_target

        response = self.client.get(reverse('login'))
        self.assertEqual(response['Permissions-Policy'], 'camera=(), microphone=(), geolocation=(), payment=(), usb=()')
        self.assertIn("object-src 'none'", response['Content-Security-Policy-Report-Only'])

        request = RequestFactory().post('/ticket/1/delete/')
        request.META['HTTP_HOST'] = 'testserver'
        self.assertEqual(safe_redirect_target(request, 'https://evil.example/', '/dashboard/'), '/dashboard/')
        self.assertEqual(safe_redirect_target(request, '/logs/', '/dashboard/'), '/logs/')


class SimplePasswordTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name='Simple Password Company A')
        self.company_b = Company.objects.create(name='Simple Password Company B')
        self.system_admin = User.objects.create_user(
            username='simple_system_admin', password='StrongPassword123!',
            role=User.SYSTEM_ADMIN, is_staff=True,
        )
        self.system_sub_admin = User.objects.create_user(
            username='simple_sub_admin', password='StrongPassword123!',
            role=User.SYSTEM_SUB_ADMIN, is_staff=True,
        )
        self.client_admin_a = User.objects.create_user(
            username='simple_client_admin_a', password='StrongPassword123!',
            role=User.CLIENT_ADMIN, company=self.company_a, is_staff=True,
        )
        self.user_a = User.objects.create_user(
            username='simple_user_a', email='simple-a@example.com',
            password='StrongPassword123!', role=User.CLIENT_USER,
            company=self.company_a,
        )
        self.user_b = User.objects.create_user(
            username='simple_user_b', email='simple-b@example.com',
            password='StrongPassword123!', role=User.CLIENT_USER,
            company=self.company_b,
        )

    def _enable_simple_password(self, target, actor=None):
        target.simple_password_enabled = True
        target.simple_password_approved_by = actor or self.system_admin
        target.simple_password_approved_at = timezone.now()
        target.save(update_fields=[
            'simple_password_enabled', 'simple_password_approved_by',
            'simple_password_approved_at',
        ])

    def _generate(self, actor, target):
        self.client.force_login(actor)
        response = self.client.post(reverse('simple_password_generate', args=[target.pk]))
        password = response.context['simple_password'] if response.status_code == 200 else None
        return response, password

    def test_system_admin_can_approve_and_issue_but_password_is_never_stored_plaintext(self):
        from .models import SecurityAuditLog

        self.client.force_login(self.system_admin)
        response = self.client.post(reverse('user_update', args=[self.user_a.pk]), {
            'username': self.user_a.username,
            'email': self.user_a.email,
            'password': '123456',
            'role': User.CLIENT_USER,
            'company': self.company_a.pk,
            'simple_password_enabled': 'on',
        })
        self.assertRedirects(response, reverse('user_list'))
        self.user_a.refresh_from_db()
        self.assertTrue(self.user_a.simple_password_enabled)
        self.assertEqual(self.user_a.simple_password_approved_by, self.system_admin)
        self.assertTrue(self.user_a.check_password('123456'))

        response, simple_password = self._generate(self.system_admin, self.user_a)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(simple_password), 6)
        self.assertTrue(simple_password.isdigit())
        self.user_a.refresh_from_db()
        self.assertTrue(self.user_a.check_password(simple_password))
        self.assertNotIn(simple_password, self.user_a.password)
        self.assertTrue(SecurityAuditLog.objects.filter(
            event_type='SIMPLE_PASSWORD_GENERATE', target_id=str(self.user_a.pk),
        ).exists())

    def test_company_admin_is_limited_to_own_company_scope(self):
        self._enable_simple_password(self.user_a, self.client_admin_a)
        self._enable_simple_password(self.user_b, self.system_admin)

        allowed, password = self._generate(self.client_admin_a, self.user_a)
        self.assertEqual(allowed.status_code, 200)
        self.assertIsNotNone(password)

        denied, _ = self._generate(self.client_admin_a, self.user_b)
        self.assertEqual(denied.status_code, 403)

    def test_system_sub_admin_cannot_reset_system_admin(self):
        self._enable_simple_password(self.user_b, self.system_admin)
        allowed, _ = self._generate(self.system_sub_admin, self.user_b)
        self.assertEqual(allowed.status_code, 200)

        self._enable_simple_password(self.system_admin, self.system_admin)
        denied, _ = self._generate(self.system_sub_admin, self.system_admin)
        self.assertEqual(denied.status_code, 403)

    def test_owner_can_issue_only_after_admin_approval(self):
        denied, _ = self._generate(self.user_a, self.user_a)
        self.assertEqual(denied.status_code, 403)

        self._enable_simple_password(self.user_a, self.client_admin_a)
        allowed, simple_password = self._generate(self.user_a, self.user_a)
        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, simple_password)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_simple_password_account_locks_for_ten_minutes_after_five_failures(self):
        self._enable_simple_password(self.user_a)
        self.client.logout()
        for attempt in range(5):
            response = self.client.post(reverse('login'), {
                'username': self.user_a.username,
                'password': 'wrong-password',
            })
        self.assertEqual(response.status_code, 429)
        retry_after = int(response['Retry-After'])
        self.assertGreaterEqual(retry_after, 590)
        self.assertLessEqual(retry_after, 601)

    def test_approved_owner_can_set_and_keep_123456(self):
        self._enable_simple_password(self.user_a)
        self.client.force_login(self.user_a)
        changed = self.client.post(reverse('account_password'), {
            'old_password': 'StrongPassword123!',
            'new_password1': '123456',
            'new_password2': '123456',
        })
        self.assertRedirects(changed, reverse('dashboard'))
        self.user_a.refresh_from_db()
        self.assertTrue(self.user_a.check_password('123456'))
        self.client.logout()
        self.assertTrue(self.client.login(username=self.user_a.username, password='123456'))
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_unapproved_owner_cannot_set_123456(self):
        self.client.force_login(self.user_a)
        response = self.client.post(reverse('account_password'), {
            'old_password': 'StrongPassword123!',
            'new_password1': '123456',
            'new_password2': '123456',
        })
        self.assertEqual(response.status_code, 200)
        self.user_a.refresh_from_db()
        self.assertFalse(self.user_a.check_password('123456'))

    def test_existing_password_is_not_rendered_to_admin_or_owner(self):
        secret = 'Never-Render-This-Password-2026!'
        self.user_a.set_password(secret)
        self.user_a.save(update_fields=['password'])

        self.client.force_login(self.system_admin)
        admin_page = self.client.get(reverse('user_update', args=[self.user_a.pk]))
        self.assertNotContains(admin_page, secret)
        self.assertContains(admin_page, 'Leave blank if you do not want to change the password')

        self.client.force_login(self.user_a)
        owner_page = self.client.get(reverse('account_password'))
        self.assertNotContains(owner_page, secret)
        self.assertContains(owner_page, 'Existing passwords are one-way hashes')

    def test_windows_874_decoding_support(self):
        from .email_to_ticket import _safe_decode_bytes, _decode_header
        sample_bytes = "ทดสอบ windows-874".encode('cp874')
        decoded = _safe_decode_bytes(sample_bytes, 'windows-874')
        self.assertIn("ทดสอบ", decoded)

        header_val = "=?windows-874?B?4OC04OC24OC3?="
        decoded_hdr = _decode_header(header_val)
        self.assertIsNotNone(decoded_hdr)

    def test_keyword_filter_save_view(self):
        SMTPConfiguration.objects.create(
            name='Keyword filter mailbox',
            provider='GMAIL',
            host='smtp.gmail.com',
            username='keyword-filter@example.com',
            password='app-password',
            feature_scope=SMTPConfiguration.FEATURE_EMAIL_TO_TICKET,
            incoming_host='imap.gmail.com',
            email_to_ticket_company=self.company_a,
            email_to_ticket_creator=self.user_a,
        )
        self.client.force_login(self.system_admin)
        response = self.client.post(
            reverse('email_keyword_filter_save'),
            {
                'mailbox_id': 'all',
                'filter_issue_only': 'on',
                'issue_keywords': 'ปัญหา, ticket, help, urgent',
                'ignore_keyword_filter_enabled': 'on',
                'ignore_keywords': 'newsletter, Automatic Reply, newsletter',
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Keyword Filter Settings updated')
        configs = SMTPConfiguration.objects.filter(
            feature_scope__in=[
                SMTPConfiguration.FEATURE_EMAIL_TO_TICKET,
                SMTPConfiguration.FEATURE_BOTH,
            ]
        )
        self.assertTrue(configs.exists())
        for config in configs:
            self.assertTrue(config.ignore_keyword_filter_enabled)
            self.assertEqual(
                config.ignore_keywords,
                'newsletter, Automatic Reply',
            )

    def test_ignore_keyword_filter_validation_and_permission(self):
        from django.contrib.messages import get_messages

        mailbox = SMTPConfiguration.objects.create(
            name='Ignore validation mailbox',
            provider='GMAIL',
            host='smtp.gmail.com',
            username='ignore-validation@example.com',
            password='app-password',
            feature_scope=SMTPConfiguration.FEATURE_EMAIL_TO_TICKET,
            incoming_host='imap.gmail.com',
            email_to_ticket_company=self.company_a,
            email_to_ticket_creator=self.user_a,
        )

        self.client.force_login(self.user_a)
        denied = self.client.post(
            reverse('email_keyword_filter_save'),
            {
                'mailbox_id': str(mailbox.pk),
                'ignore_keyword_filter_enabled': 'on',
                'ignore_keywords': 'newsletter',
            },
        )
        self.assertEqual(denied.status_code, 403)

        self.client.force_login(self.system_admin)
        invalid = self.client.post(
            reverse('email_keyword_filter_save'),
            {
                'mailbox_id': str(mailbox.pk),
                'ignore_keyword_filter_enabled': 'on',
                'ignore_keywords': '',
            },
        )
        self.assertRedirects(invalid, reverse('email_timer'))
        self.assertIn(
            'Add at least one ignore keyword',
            ' '.join(str(message) for message in get_messages(invalid.wsgi_request)),
        )
        mailbox.refresh_from_db()
        self.assertFalse(mailbox.ignore_keyword_filter_enabled)

    def test_ignore_keyword_filter_skips_email_and_records_reason(self):
        from email.message import EmailMessage as RawEmailMessage
        from unittest import mock
        from .email_to_ticket import (
            InboundMessage,
            _is_issue_message,
            import_email_to_tickets,
        )
        from .models import InboundEmailContact, InboundEmailReceipt

        config = SMTPConfiguration.objects.create(
            name='Ignore filter mailbox',
            provider='GMAIL',
            host='smtp.gmail.com',
            username='ignore-filter@example.com',
            password='app-password',
            feature_scope=SMTPConfiguration.FEATURE_EMAIL_TO_TICKET,
            incoming_host='imap.gmail.com',
            email_to_ticket_company=self.company_a,
            email_to_ticket_creator=self.user_a,
            filter_issue_only=False,
            ignore_keyword_filter_enabled=True,
            ignore_keywords='automatic reply, โฆษณา',
            is_active=True,
        )
        decision = _is_issue_message(
            config,
            InboundMessage(
                uid=b'701',
                message_id='<ignore-decision@example.com>',
                subject='AUTOMATIC REPLY: Issue VPN failed',
                body='This contains an issue keyword but must be ignored.',
            ),
        )
        self.assertEqual(decision, (False, ['ignored:automatic reply']))

        raw_message = RawEmailMessage()
        raw_message['Subject'] = 'Automatic Reply: Issue VPN failed'
        raw_message['From'] = 'Auto Responder <robot@example.com>'
        raw_message['Message-ID'] = '<ignored-email@example.com>'
        raw_message.set_content('Automated response.')

        imap_client = mock.Mock()
        imap_client.select.return_value = ('OK', [b'1'])

        def imap_uid(command, *args):
            if command == 'search':
                return 'OK', [b'701']
            if command == 'fetch':
                if args[-1] == '(RFC822.SIZE)':
                    return 'OK', [(b'701 (RFC822.SIZE 512)', b'')]
                return 'OK', [(b'701 (BODY[] {1})', raw_message.as_bytes()), b')']
            if command == 'store':
                return 'OK', [b'701']
            raise AssertionError(f'Unexpected IMAP UID command: {command}')

        imap_client.uid.side_effect = imap_uid
        ticket_count = Ticket.objects.count()
        with mock.patch(
            'tickets.email_to_ticket.imaplib.IMAP4_SSL',
            return_value=imap_client,
        ):
            result = import_email_to_tickets(config)

        self.assertTrue(result['success'])
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(Ticket.objects.count(), ticket_count)
        receipt = InboundEmailReceipt.objects.get(
            smtp_configuration=config,
            message_id='<ignored-email@example.com>',
        )
        self.assertEqual(receipt.status, InboundEmailReceipt.STATUS_SKIPPED)
        self.assertEqual(receipt.matched_keywords, ['ignored:automatic reply'])
        self.assertIn('ignore keyword filter', receipt.details)
        self.assertIn('automatic reply', receipt.details)
        self.assertFalse(
            InboundEmailContact.objects.filter(
                smtp_configuration=config,
                email='robot@example.com',
            ).exists()
        )


class MaintenanceBackupRestoreTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name='Maintenance Company A')
        self.system_admin = User.objects.create_user(
            username='system_admin',
            password='password123',
            role=User.SYSTEM_ADMIN,
            is_staff=True,
            email='system-admin@example.com',
        )
        self.user_a = User.objects.create_user(
            username='user_a',
            password='password123',
            role=User.CLIENT_USER,
            company=self.company_a,
            email='user-a@example.com',
        )

    def test_maintenance_gate_hashes_code_throttles_failures_and_keeps_rbac_login(self):
        from django.contrib.auth.hashers import check_password
        from django.test import Client
        from .models import MaintenanceSetting, SecurityAuditLog

        self.client.login(username='system_admin', password='password123')
        response = self.client.post(reverse('maintenance_settings'), {
            'is_enabled': 'on',
            'title': 'Database maintenance',
            'message': 'A controlled maintenance test is running.',
            'scheduled_start': '',
            'expected_end': '',
            'allow_test_access': 'on',
            'access_session_minutes': '120',
            'access_code': 'authorized-test-2026',
            'current_password': 'password123',
        })
        self.assertRedirects(response, reverse('maintenance_settings'))
        setting = MaintenanceSetting.get_solo()
        self.assertTrue(setting.is_active())
        self.assertNotEqual(setting.access_code_hash, 'authorized-test-2026')
        self.assertTrue(check_password('authorized-test-2026', setting.access_code_hash))

        public_client = Client()
        self.assertEqual(public_client.get(reverse('dashboard')).status_code, 503)
        for attempt in range(5):
            failed = public_client.post(
                reverse('maintenance_access'),
                {'access_code': 'wrong-code'},
                REMOTE_ADDR='198.51.100.10',
            )
            self.assertEqual(failed.status_code, 429 if attempt == 4 else 503)
        blocked = public_client.post(
            reverse('maintenance_access'),
            {'access_code': 'authorized-test-2026'},
            REMOTE_ADDR='198.51.100.10',
        )
        self.assertEqual(blocked.status_code, 429)

        tester_client = Client()
        granted = tester_client.post(
            reverse('maintenance_access'),
            {'access_code': 'authorized-test-2026'},
            REMOTE_ADDR='198.51.100.11',
        )
        self.assertRedirects(granted, reverse('login'), fetch_redirect_response=False)
        self.assertEqual(tester_client.get(reverse('dashboard')).status_code, 302)
        signed_in = tester_client.post(reverse('login'), {
            'username': 'user_a',
            'password': 'password123',
        })
        self.assertRedirects(signed_in, reverse('dashboard'), fetch_redirect_response=False)
        self.assertEqual(tester_client.get(reverse('dashboard')).status_code, 200)
        self.assertTrue(SecurityAuditLog.objects.filter(
            event_type='MAINTENANCE_ACCESS_BLOCKED'
        ).exists())

    def test_system_sub_admin_cannot_change_global_maintenance_or_import_backup(self):
        from .models import MaintenanceSetting

        sub_admin = CustomUser.objects.create_user(
            username='maintenance_sub_admin',
            password='password123',
            role=CustomUser.SYSTEM_SUB_ADMIN,
            email='maintenance-sub@example.com',
        )
        self.client.login(username=sub_admin.username, password='password123')
        self.assertEqual(self.client.get(reverse('maintenance_settings')).status_code, 200)
        denied = self.client.post(reverse('maintenance_settings'), {
            'is_enabled': 'on',
            'title': 'Blocked change',
            'message': 'Must not save',
            'allow_test_access': 'on',
            'access_session_minutes': '120',
            'access_code': 'should-not-save',
            'current_password': 'password123',
        })
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(MaintenanceSetting.get_solo().is_enabled)
        import_denied = self.client.post(reverse('backup_import_start'), {
            'filename': 'backup.zip',
            'size': '10',
        })
        self.assertEqual(import_denied.status_code, 403)

    def test_chunked_backup_import_validates_archive_and_rejects_traversal(self):
        import hashlib
        import io
        import json
        import tempfile
        import zipfile
        from unittest import mock
        from .backup_restore_service import make_backup_manifest
        from .models import BackupLog

        self.client.login(username='system_admin', password='password123')
        ticket_payload = b'[]'
        manifest = make_backup_manifest(
            backup_type=BackupLog.TYPE_INCREMENTAL,
            database_format='ticket_json',
            payloads={'tickets.json': hashlib.sha256(ticket_payload).hexdigest()},
            includes_media=False,
            includes_chatbot=False,
        )
        valid_buffer = io.BytesIO()
        with zipfile.ZipFile(valid_buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('tickets.json', ticket_payload)
            archive.writestr(
                'backup_manifest.json',
                json.dumps(manifest, ensure_ascii=False),
            )
        valid_bytes = valid_buffer.getvalue()

        malicious_buffer = io.BytesIO()
        with zipfile.ZipFile(malicious_buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('../outside.txt', b'blocked')
        malicious_bytes = malicious_buffer.getvalue()

        with tempfile.TemporaryDirectory() as root:
            backup_dir = os.path.join(root, 'backups')
            quarantine_dir = os.path.join(backup_dir, '.quarantine')
            with mock.patch('tickets.backup_restore_service.BACKUP_DIR', backup_dir), \
                    mock.patch('tickets.backup_restore_service.BACKUP_QUARANTINE_DIR', quarantine_dir), \
                    mock.patch('tickets.views.RESTORE_BACKUP_DIR', backup_dir):
                started = self.client.post(reverse('backup_import_start'), {
                    'filename': 'downloaded-ticket-backup.zip',
                    'size': str(len(valid_bytes)),
                })
                self.assertEqual(started.status_code, 200)
                upload = started.json()
                chunked = self.client.post(upload['chunk_url'], {
                    'index': '0',
                    'chunk': SimpleUploadedFile('chunk.bin', valid_bytes),
                })
                self.assertEqual(chunked.status_code, 200)
                completed = self.client.post(upload['complete_url'])
                self.assertEqual(completed.status_code, 200)
                imported = BackupLog.objects.get(pk=completed.json()['backup_id'])
                self.assertEqual(imported.source, BackupLog.SOURCE_IMPORTED)
                self.assertEqual(imported.validation_status, BackupLog.VALIDATION_VALID)
                self.assertFalse(imported.restore_supported)
                self.assertTrue(os.path.isfile(os.path.join(backup_dir, imported.filename)))

                malicious_started = self.client.post(reverse('backup_import_start'), {
                    'filename': 'malicious.zip',
                    'size': str(len(malicious_bytes)),
                }).json()
                self.client.post(malicious_started['chunk_url'], {
                    'index': '0',
                    'chunk': SimpleUploadedFile('chunk.bin', malicious_bytes),
                })
                rejected = self.client.post(malicious_started['complete_url'])
                self.assertEqual(rejected.status_code, 400)
                self.assertFalse(os.path.exists(os.path.join(root, 'outside.txt')))
                self.assertTrue(BackupLog.objects.filter(
                    source=BackupLog.SOURCE_IMPORTED,
                    validation_status=BackupLog.VALIDATION_INVALID,
                ).exists())

    def test_full_backup_v2_is_signed_checksummed_and_restore_request_is_queued(self):
        import datetime
        import io
        import tarfile
        import tempfile
        from unittest import mock
        from django.contrib.auth.hashers import make_password
        from django.test import override_settings
        from .backup_restore_service import validate_backup_archive
        from .backup_service import perform_full_backup
        from .models import BackupLog, MaintenanceSetting, RestoreJob

        self.client.login(username='system_admin', password='password123')
        with tempfile.TemporaryDirectory() as backup_dir, tempfile.TemporaryDirectory() as media_root, \
                override_settings(MEDIA_ROOT=media_root), \
                mock.patch('tickets.backup_service.BACKUP_DIR', backup_dir), \
                mock.patch('tickets.backup_service.CHATBOT_DB_PATH', os.path.join(backup_dir, 'missing-chatbot.db')):
            with open(os.path.join(media_root, 'thai-attachment.txt'), 'wb') as media_file:
                media_file.write('ไฟล์แนบสำหรับทดสอบ'.encode('utf-8'))
            result = perform_full_backup()
            self.assertTrue(result['success'], result.get('error'))
            backup = result['log']
            self.assertEqual(backup.format_version, '2')
            self.assertEqual(len(backup.sha256), 64)
            self.assertTrue(backup.restore_supported)
            validation = validate_backup_archive(
                result['file_path'],
                expected_sha256=backup.sha256,
            )
            self.assertTrue(validation['valid'], validation['details'])
            self.assertTrue(validation['restore_supported'])

            tampered_path = os.path.join(backup_dir, 'tampered-full-backup.tar.gz')
            with tarfile.open(result['file_path'], 'r:gz') as source_archive, \
                    tarfile.open(tampered_path, 'w:gz') as destination_archive:
                for member in source_archive.getmembers():
                    if member.isdir():
                        destination_archive.addfile(member)
                        continue
                    source = source_archive.extractfile(member)
                    content = source.read() if source else b''
                    if member.name == 'media/thai-attachment.txt':
                        content = b'tampered-media-content'
                        member.size = len(content)
                    destination_archive.addfile(member, io.BytesIO(content))
            tampered_validation = validate_backup_archive(tampered_path)
            self.assertFalse(tampered_validation['valid'])
            self.assertIn('Media checksum mismatch', tampered_validation['details'])

            maintenance = MaintenanceSetting.get_solo()
            maintenance.is_enabled = True
            maintenance.allow_test_access = True
            maintenance.access_code_hash = make_password('restore-access-2026')
            maintenance.save()
            session = self.client.session
            session['maintenance_access'] = {
                'version': maintenance.access_version,
                'expires_at': int((timezone.now() + datetime.timedelta(hours=1)).timestamp()),
            }
            session.save()

            with mock.patch('tickets.views.queue_restore_trigger') as trigger:
                queued = self.client.post(
                    reverse('backup_restore_request', args=[backup.pk]),
                    {
                        'current_password': 'password123',
                        'maintenance_code': 'restore-access-2026',
                        'confirmation_phrase': f'RESTORE {backup.pk}',
                    },
                )
            self.assertRedirects(queued, reverse('backup_list'))
            job = RestoreJob.objects.get(backup=backup)
            self.assertEqual(job.status, RestoreJob.STATUS_QUEUED)
            trigger.assert_called_once_with(job.job_id)
            backup.refresh_from_db()
            self.assertTrue(backup.is_protected)

    def test_restore_database_payload_replaces_isolated_sqlite_database(self):
        import sqlite3
        import tempfile
        from unittest import mock
        from django.test import override_settings
        from .backup_restore_service import restore_database_payload

        with tempfile.TemporaryDirectory() as root:
            staging = os.path.join(root, 'staging')
            os.makedirs(os.path.join(staging, 'database'))
            source_path = os.path.join(staging, 'database', 'db.sqlite3')
            target_path = os.path.join(root, 'target.sqlite3')
            source = sqlite3.connect(source_path)
            source.execute('CREATE TABLE marker (value TEXT)')
            source.execute("INSERT INTO marker VALUES ('restored')")
            source.commit()
            source.close()
            target = sqlite3.connect(target_path)
            target.execute('CREATE TABLE marker (value TEXT)')
            target.execute("INSERT INTO marker VALUES ('old')")
            target.commit()
            target.close()

            database_setting = {
                'default': {
                    'ENGINE': 'django.db.backends.sqlite3',
                    'NAME': target_path,
                }
            }
            with override_settings(DATABASES=database_setting), \
                    mock.patch('tickets.backup_restore_service.connections.close_all'), \
                    mock.patch('tickets.backup_restore_service.call_command'):
                restore_database_payload(staging, {'database_format': 'sqlite3'})
            restored = sqlite3.connect(target_path)
            try:
                self.assertEqual(restored.execute('SELECT value FROM marker').fetchone()[0], 'restored')
            finally:
                restored.close()





