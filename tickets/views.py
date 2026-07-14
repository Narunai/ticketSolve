from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView
from django.contrib.auth import logout
from django.views.generic import CreateView, UpdateView, DetailView, TemplateView, ListView
from django.urls import reverse_lazy
from django.core.exceptions import PermissionDenied
from .models import Ticket, CustomUser, Company, EmailLog, TicketAuditLog, ReportViewLog, SMTPConfiguration, get_smtp_connection, get_smtp_from_email, TicketComment
from django import forms

import os
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse, Http404
from io import BytesIO
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.core.mail import EmailMessage
from django.utils import timezone
from django.views import View

# Form for ticket creation
class TicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ['title', 'description', 'priority', 'category', 'attachment']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'placeholder': 'ระบุหัวข้อปัญหา...'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'placeholder': 'อธิบายรายละเอียดของปัญหา...',
                'rows': 4
            }),
            'priority': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'category': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'attachment': forms.ClearableFileInput(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            })
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

    def clean_attachment(self):
        attachment = self.cleaned_data.get('attachment')
        if attachment:
            max_size = 10 * 1024 * 1024  # 10 MB
            if attachment.size > max_size:
                lang = 'th'
                if self.request:
                    lang = self.request.COOKIES.get('lang', 'th')
                size_mb = attachment.size / (1024 * 1024)
                if lang == 'en':
                    raise forms.ValidationError(
                        f"Attachment size must not exceed 10 MB (your file is {size_mb:.1f} MB)"
                    )
                else:
                    raise forms.ValidationError(
                        f"ขนาดไฟล์แนบต้องไม่เกิน 10 MB (ไฟล์ของคุณขนาด {size_mb:.1f} MB)"
                    )
        return attachment

# Form for ticket update (Status, Assignee, Priority)
class TicketUpdateForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ['title', 'description', 'status', 'priority', 'category', 'assigned_to', 'attachment']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'rows': 4
            }),
            'status': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'priority': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'category': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'assigned_to': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'attachment': forms.ClearableFileInput(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            })
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        if user and user.company:
            # Only staff or users in the same company can be assigned
            self.fields['assigned_to'].queryset = CustomUser.objects.filter(company=user.company)
            # If the user is CLIENT_USER, disable details and only allow editing if needed, for simplicity we disable details
            if user.role == CustomUser.CLIENT_USER:
                for field in ['title', 'description', 'priority', 'assigned_to']:
                    self.fields[field].disabled = True
        elif user and (user.is_superuser or user.role == CustomUser.SYSTEM_ADMIN):
            self.fields['assigned_to'].queryset = CustomUser.objects.all()

    def clean_attachment(self):
        attachment = self.cleaned_data.get('attachment')
        if attachment:
            max_size = 10 * 1024 * 1024  # 10 MB
            if attachment.size > max_size:
                lang = 'th'
                if self.request:
                    lang = self.request.COOKIES.get('lang', 'th')
                size_mb = attachment.size / (1024 * 1024)
                if lang == 'en':
                    raise forms.ValidationError(
                        f"Attachment size must not exceed 10 MB (your file is {size_mb:.1f} MB)"
                    )
                else:
                    raise forms.ValidationError(
                        f"ขนาดไฟล์แนบต้องไม่เกิน 10 MB (ไฟล์ของคุณขนาด {size_mb:.1f} MB)"
                    )
        return attachment


class SMTPConfigurationForm(forms.ModelForm):
    class Meta:
        model = SMTPConfiguration
        fields = ['name', 'provider', 'host', 'port', 'use_tls', 'username', 'password', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'placeholder': 'เช่น Gmail ส่วนตัว, Outlook บริษัท'
            }),
            'provider': forms.Select(attrs={
                'id': 'id_provider',
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'host': forms.TextInput(attrs={
                'id': 'id_host',
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'placeholder': 'เช่น smtp.gmail.com'
            }),
            'port': forms.NumberInput(attrs={
                'id': 'id_port',
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'use_tls': forms.CheckboxInput(attrs={
                'id': 'id_use_tls',
                'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-indigo-500 focus:ring-offset-slate-900 h-4 w-4'
            }),
            'username': forms.TextInput(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'placeholder': 'เช่น narunaithaisenee@gmail.com'
            }),
            'password': forms.PasswordInput(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg pl-4 pr-10 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'placeholder': 'ใส่รหัสผ่านแอป 16 หลัก หรือรหัสผ่าน SMTP'
            }, render_value=True),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-indigo-500 focus:ring-offset-slate-900 h-4 w-4'
            })
        }

class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'placeholder': 'ชื่อบริษัท/องค์กร...'
            })
        }

class CustomUserForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg pl-4 pr-10 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
            'placeholder': 'ระบุรหัสผ่าน...'
        }),
        required=False,
        help_text="หากเว้นว่างไว้สำหรับผู้ใช้เดิม รหัสผ่านจะไม่ถูกเปลี่ยน"
    )

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'password', 'role', 'company']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'placeholder': 'ระบุชื่อผู้ใช้...'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'placeholder': 'ระบุอีเมล...'
            }),
            'role': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'company': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            })
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if self.instance and self.instance.pk:
            self.fields['password'].required = False
        else:
            self.fields['password'].required = True

        if user and not user.is_superuser and user.role == CustomUser.CLIENT_ADMIN:
            # Force the Client Admin's company and disable editing it
            if 'company' in self.fields:
                self.fields['company'].disabled = True
                self.fields['company'].initial = user.company
                self.fields['company'].required = False
            # Client Admin can only choose Client Admin or Client User roles
            if 'role' in self.fields:
                self.fields['role'].choices = [
                    (CustomUser.CLIENT_ADMIN, 'Client Administrator'),
                    (CustomUser.CLIENT_USER, 'Client User'),
                ]
        elif user and not user.is_superuser and user.role == CustomUser.SYSTEM_SUB_ADMIN:
            # System Sub-Admin can only choose Client Admin or Client User roles
            if 'role' in self.fields:
                self.fields['role'].choices = [
                    (CustomUser.CLIENT_ADMIN, 'Client Administrator'),
                    (CustomUser.CLIENT_USER, 'Client User'),
                ]
        elif user and (user.is_superuser or user.role == CustomUser.SYSTEM_ADMIN):
            pass

    def save(self, commit=True):
        password = self.cleaned_data.get("password")
        if self.instance and self.instance.pk and not password:
            old_password = CustomUser.objects.get(pk=self.instance.pk).password
            user_instance = super().save(commit=False)
            user_instance.password = old_password
        else:
            user_instance = super().save(commit=False)
            if password:
                user_instance.set_password(password)

        if commit:
            user_instance.save()
        return user_instance


# Custom Security Mixins
class SuperuserOrSystemAdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_superuser or user.role == CustomUser.SYSTEM_ADMIN)

class SystemStaffRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN])

class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN, CustomUser.CLIENT_ADMIN])


# Login & Authentication views
class CustomLoginView(LoginView):
    template_name = 'tickets/login.html'
    redirect_authenticated_user = True

def custom_logout(request):
    logout(request)
    return redirect('login')


# Dashboard view
class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'tickets/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        if user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            tickets = Ticket.objects.all()
            companies = Company.objects.all()
            users = CustomUser.objects.all()
        else:
            tickets = Ticket.objects.filter(company=user.company)
            companies = Company.objects.filter(id=user.company.id)
            users = CustomUser.objects.filter(company=user.company)

        # Statistics (Base counts)
        context['tickets_count'] = tickets.count()
        context['open_count'] = tickets.filter(status=Ticket.STATUS_OPEN).count()
        context['in_progress_count'] = tickets.filter(status=Ticket.STATUS_IN_PROGRESS).count()
        context['resolved_count'] = tickets.filter(status=Ticket.STATUS_RESOLVED).count()
        context['closed_count'] = tickets.filter(status=Ticket.STATUS_CLOSED).count()

        context['high_priority_count'] = tickets.filter(priority=Ticket.PRIORITY_HIGH).count()
        context['medium_priority_count'] = tickets.filter(priority=Ticket.PRIORITY_MEDIUM).count()
        context['low_priority_count'] = tickets.filter(priority=Ticket.PRIORITY_LOW).count()

        # Query Parameter Filtering
        status_filter = self.request.GET.get('status')
        priority_filter = self.request.GET.get('priority')

        filtered_tickets = tickets
        if status_filter in [Ticket.STATUS_OPEN, Ticket.STATUS_IN_PROGRESS, Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED]:
            filtered_tickets = filtered_tickets.filter(status=status_filter)
            context['selected_status'] = status_filter

        if priority_filter in [Ticket.PRIORITY_LOW, Ticket.PRIORITY_MEDIUM, Ticket.PRIORITY_HIGH]:
            filtered_tickets = filtered_tickets.filter(priority=priority_filter)
            context['selected_priority'] = priority_filter

        context['latest_tickets'] = filtered_tickets.order_by('-created_at')[:5]
        context['users_count'] = users.count()
        context['companies_count'] = companies.count()
        
        context['tickets'] = filtered_tickets.order_by('-created_at')
        return context


# Ticket Views
class TicketCreateView(LoginRequiredMixin, CreateView):
    model = Ticket
    form_class = TicketForm
    template_name = 'tickets/ticket_form.html'
    success_url = reverse_lazy('dashboard')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        user = self.request.user
        if not user.company:
            form.add_error(None, "System Admin ต้องเป็นสมาชิกของบริษัทใดบริษัทหนึ่ง หรือกรุณาเข้าสู่ระบบด้วยผู้ใช้ระดับบริษัทเพื่อเปิด Ticket")
            return self.form_invalid(form)
            
        form.instance.company = user.company
        form.instance.created_by = user
        response = super().form_valid(form)

        # Record initial audit log
        TicketAuditLog.objects.create(
            ticket=self.object,
            actor=user,
            old_status=None,
            new_status=self.object.status,
            details=f"เปิด Ticket ใหม่: '{self.object.title}'"
        )
        return response

class TicketUpdateView(LoginRequiredMixin, UpdateView):
    model = Ticket
    form_class = TicketUpdateForm
    template_name = 'tickets/ticket_form.html'
    success_url = reverse_lazy('dashboard')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['request'] = self.request
        return kwargs

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user
        if not user.is_superuser and user.role != CustomUser.SYSTEM_ADMIN:
            if obj.company != user.company:
                raise PermissionDenied("คุณไม่มีสิทธิ์เข้าถึงหรือแก้ไข Ticket ของบริษัทอื่น")
        return obj

    def form_valid(self, form):
        old_ticket = Ticket.objects.get(pk=self.object.pk)
        old_status = old_ticket.status
        old_priority = old_ticket.priority
        old_assignee = old_ticket.assigned_to

        response = super().form_valid(form)
        new_status = self.object.status

        # Compare and record audit changes
        changes = []
        if old_status != new_status:
            changes.append(f"สถานะเปลี่ยนจาก '{old_ticket.get_status_display()}' เป็น '{self.object.get_status_display()}'")
        if old_priority != self.object.priority:
            changes.append(f"ความสำคัญเปลี่ยนจาก '{old_ticket.get_priority_display()}' เป็น '{self.object.get_priority_display()}'")
        if old_assignee != self.object.assigned_to:
            old_name = old_assignee.username if old_assignee else "ยังไม่ได้มอบหมาย"
            new_name = self.object.assigned_to.username if self.object.assigned_to else "ยังไม่ได้มอบหมาย"
            changes.append(f"ผู้รับผิดชอบเปลี่ยนจาก '{old_name}' เป็น '{new_name}'")

        if changes:
            TicketAuditLog.objects.create(
                ticket=self.object,
                actor=self.request.user,
                old_status=old_status,
                new_status=new_status,
                details="; ".join(changes)
            )

        return response

class TicketDetailView(LoginRequiredMixin, DetailView):
    model = Ticket
    template_name = 'tickets/ticket_detail.html'
    context_object_name = 'ticket'

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user
        if not user.is_superuser and user.role != CustomUser.SYSTEM_ADMIN:
            if obj.company != user.company:
                raise PermissionDenied("คุณไม่มีสิทธิ์ดูรายละเอียด Ticket ของบริษัทอื่น")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['comments'] = self.object.comments.all().order_by('created_at')
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        content = request.POST.get('content', '').strip()
        if content:
            comment = TicketComment.objects.create(
                ticket=self.object,
                author=request.user,
                content=content
            )
            # Send email notifications to stakeholders
            self.send_comment_notifications(comment)
            messages.success(request, "โพสต์ความคิดเห็นและส่งอีเมลแจ้งเตือนผู้ที่เกี่ยวข้องเรียบร้อยแล้ว")
        return redirect('ticket_detail', pk=self.object.id)

    def send_comment_notifications(self, comment):
        from django.core.mail import send_mail
        
        ticket = comment.ticket
        recipients = set()
        
        # Add creator if not comment author
        if ticket.created_by.email and ticket.created_by != comment.author:
            recipients.add(ticket.created_by.email)
            
        # Add assignee if assigned and not comment author
        if ticket.assigned_to and ticket.assigned_to.email and ticket.assigned_to != comment.author:
            recipients.add(ticket.assigned_to.email)
            
        if not recipients:
            return
            
        subject = f"[TicketSolve] ความคิดเห็นใหม่ใน Ticket #{ticket.id}: {ticket.title}"
        message_body = (
            f"สวัสดีครับ,\n\n"
            f"มีการแสดงความคิดเห็นใหม่ใน Ticket #{ticket.id} ({ticket.title})\n\n"
            f"โดย: {comment.author.username} ({comment.author.get_role_display()})\n"
            f"ข้อความ:\n"
            f"----------------------------------------\n"
            f"{comment.content}\n"
            f"----------------------------------------\n\n"
            f"คุณสามารถดูรายละเอียดและตอบกลับได้ที่: http://127.0.0.1:8000/ticket/{ticket.id}/\n\n"
            f"ขอบคุณครับ,\n"
            f"ระบบ TicketSolve"
        )
        
        connection = get_smtp_connection()
        from_email = get_smtp_from_email(settings.DEFAULT_FROM_EMAIL)
        
        for email in recipients:
            try:
                send_mail(
                    subject=subject,
                    message=message_body,
                    from_email=from_email,
                    recipient_list=[email],
                    connection=connection,
                    fail_silently=False
                )
                EmailLog.objects.create(
                    recipient=email,
                    subject=subject,
                    message=message_body,
                    action_type=EmailLog.ACTION_COMMENT_ADDED,
                    success=True
                )
            except Exception:
                EmailLog.objects.create(
                    recipient=email,
                    subject=subject,
                    message=message_body,
                    action_type=EmailLog.ACTION_COMMENT_ADDED,
                    success=False
                )


# Custom User Management Views
class UserListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = CustomUser
    template_name = 'tickets/user_list.html'
    context_object_name = 'users_list'

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            return CustomUser.objects.all().order_by('company', 'username')
        return CustomUser.objects.filter(company=user.company).order_by('username')

class UserCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = CustomUser
    form_class = CustomUserForm
    template_name = 'tickets/user_form.html'
    success_url = reverse_lazy('user_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        user = self.request.user
        if not user.is_superuser and user.role in [CustomUser.CLIENT_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            if user.role == CustomUser.CLIENT_ADMIN:
                form.instance.company = user.company
            if form.instance.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
                form.instance.role = CustomUser.CLIENT_USER
            if form.instance.role == CustomUser.CLIENT_ADMIN:
                form.instance.is_staff = True
        elif form.instance.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN, CustomUser.CLIENT_ADMIN]:
            form.instance.is_staff = True
            
        return super().form_valid(form)

class UserUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = CustomUser
    form_class = CustomUserForm
    template_name = 'tickets/user_form.html'
    success_url = reverse_lazy('user_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user
        if not user.is_superuser:
            if user.role == CustomUser.CLIENT_ADMIN:
                if obj.company != user.company:
                    raise PermissionDenied("คุณไม่มีสิทธิ์จัดการบัญชีผู้ใช้งานของบริษัทอื่น")
                if obj.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
                    raise PermissionDenied("คุณไม่มีสิทธิ์แก้ไขบัญชีผู้ดูแลระบบส่วนกลาง")
            elif user.role == CustomUser.SYSTEM_SUB_ADMIN:
                if obj.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
                    raise PermissionDenied("คุณไม่มีสิทธิ์แก้ไขบัญชีผู้ดูแลระบบส่วนกลาง")
        return obj

    def form_valid(self, form):
        user = self.request.user
        if not user.is_superuser and user.role in [CustomUser.CLIENT_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            if user.role == CustomUser.CLIENT_ADMIN:
                form.instance.company = user.company
            if form.instance.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
                form.instance.role = CustomUser.CLIENT_USER
            if form.instance.role == CustomUser.CLIENT_ADMIN:
                form.instance.is_staff = True
        elif form.instance.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN, CustomUser.CLIENT_ADMIN]:
            form.instance.is_staff = True
            
        return super().form_valid(form)


# Custom Company Management Views
class CompanyListView(LoginRequiredMixin, SystemStaffRequiredMixin, ListView):
    model = Company
    template_name = 'tickets/company_list.html'
    context_object_name = 'companies_list'
    ordering = ['name']

class CompanyCreateView(LoginRequiredMixin, SystemStaffRequiredMixin, CreateView):
    model = Company
    form_class = CompanyForm
    template_name = 'tickets/company_form.html'
    success_url = reverse_lazy('company_list')

class CompanyUpdateView(LoginRequiredMixin, SystemStaffRequiredMixin, UpdateView):
    model = Company
    form_class = CompanyForm
    template_name = 'tickets/company_form.html'
    success_url = reverse_lazy('company_list')


# Activity & Email Logs View
class LogListView(LoginRequiredMixin, AdminRequiredMixin, TemplateView):
    template_name = 'tickets/log_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        if user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            email_logs = EmailLog.objects.all()
            audit_logs = TicketAuditLog.objects.select_related('ticket', 'actor', 'ticket__company').all()
        else:
            company_user_emails = list(CustomUser.objects.filter(company=user.company).values_list('email', flat=True))
            email_logs = EmailLog.objects.filter(recipient__in=company_user_emails)
            audit_logs = TicketAuditLog.objects.select_related('ticket', 'actor', 'ticket__company').filter(ticket__company=user.company)

        context['email_logs'] = email_logs[:100]
        context['audit_logs'] = audit_logs[:100]
        return context


def link_callback(uri, rel):
    """
    Convert HTML URIs to absolute system paths so xhtml2pdf can access those
    resources on the local file system.
    """
    import os
    from django.conf import settings
    
    if uri.startswith(settings.STATIC_URL):
        # Remove STATIC_URL prefix
        rel_path = uri[len(settings.STATIC_URL):]
        # Resolve to BASE_DIR/tickets/static/
        path = os.path.join(settings.BASE_DIR, 'tickets', 'static', rel_path.replace('/', os.sep))
        if os.path.exists(path):
            return path

    return uri


# Helper to convert HTML to PDF
def generate_pdf(template_src, context):
    # Programmatically register Sarabun font to avoid xhtml2pdf font parsing/loading issues on Windows/Linux
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    
    try:
        pdfmetrics.getFont('Sarabun')
    except Exception:
        font_regular_path = os.path.join(settings.BASE_DIR, 'tickets', 'static', 'fonts', 'Sarabun-Regular.ttf')
        font_bold_path = os.path.join(settings.BASE_DIR, 'tickets', 'static', 'fonts', 'Sarabun-Bold.ttf')
        if os.path.exists(font_regular_path):
            pdfmetrics.registerFont(TTFont('Sarabun', font_regular_path))
        if os.path.exists(font_bold_path):
            pdfmetrics.registerFont(TTFont('Sarabun-Bold', font_bold_path))
        try:
            pdfmetrics.registerFontFamily('Sarabun', normal='Sarabun', bold='Sarabun-Bold')
        except Exception:
            pass

    template = get_template(template_src)
    html = template.render(context)
    result = BytesIO()

    # Monkeypatch tempfile.NamedTemporaryFile to avoid file sharing/lock bugs on Windows
    import tempfile
    original_NamedTemporaryFile = tempfile.NamedTemporaryFile

    def custom_NamedTemporaryFile(*args, **kwargs):
        suffix = kwargs.get('suffix', '')
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        
        class TempFileWrapper:
            def __init__(self, p):
                self.name = p
                self.file_obj = open(p, 'wb')
            def write(self, d):
                self.file_obj.write(d)
            def flush(self):
                self.file_obj.flush()
            def close(self):
                if not self.file_obj.closed:
                    self.file_obj.close()
                try:
                    os.remove(self.name)
                except Exception:
                    pass
            def __enter__(self):
                return self
            def __exit__(self, *a):
                self.close()
                
        return TempFileWrapper(path)

    tempfile.NamedTemporaryFile = custom_NamedTemporaryFile

    try:
        # xhtml2pdf handles UTF-8 correctly
        pdf = pisa.pisaDocument(
            BytesIO(html.encode("utf-8")),
            result,
            link_callback=link_callback
        )
        if not pdf.err:
            return result.getvalue()
    finally:
        tempfile.NamedTemporaryFile = original_NamedTemporaryFile

    return None

# Helper to fetch report stats context
def get_report_context(user, company_id=None):
    selected_company = None
    if user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
        if company_id:
            selected_company = Company.objects.filter(id=company_id).first()
    else:
        selected_company = user.company

    tickets = Ticket.objects.all()
    if selected_company:
        tickets = tickets.filter(company=selected_company)

    # Filter to current month
    now = timezone.now()
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    tickets = tickets.filter(created_at__gte=start_of_month)

    # Stats
    tickets_count = tickets.count()
    open_count = tickets.filter(status=Ticket.STATUS_OPEN).count()
    in_progress_count = tickets.filter(status=Ticket.STATUS_IN_PROGRESS).count()
    resolved_count = tickets.filter(status=Ticket.STATUS_RESOLVED).count()
    closed_count = tickets.filter(status=Ticket.STATUS_CLOSED).count()

    high_priority_count = tickets.filter(priority=Ticket.PRIORITY_HIGH).count()
    medium_priority_count = tickets.filter(priority=Ticket.PRIORITY_MEDIUM).count()
    low_priority_count = tickets.filter(priority=Ticket.PRIORITY_LOW).count()

    done_count = resolved_count + closed_count
    active_count = open_count + in_progress_count

    resolution_rate = 0
    if tickets_count > 0:
        resolution_rate = round((done_count / tickets_count) * 100, 1)

    theme_color = "#6366f1"
    english_months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    month_name = f"{english_months[now.month - 1]} {now.year}"

    font_regular_path = "file:///" + os.path.join(settings.BASE_DIR, 'tickets', 'static', 'fonts', 'Sarabun-Regular.ttf').replace('\\', '/')
    font_bold_path = "file:///" + os.path.join(settings.BASE_DIR, 'tickets', 'static', 'fonts', 'Sarabun-Bold.ttf').replace('\\', '/')

    context = {
        'tickets': tickets,
        'tickets_count': tickets_count,
        'open_count': open_count,
        'in_progress_count': in_progress_count,
        'resolved_count': resolved_count,
        'closed_count': closed_count,
        'high_priority_count': high_priority_count,
        'medium_priority_count': medium_priority_count,
        'low_priority_count': low_priority_count,
        'done_count': done_count,
        'active_count': active_count,
        'resolution_rate': resolution_rate,
        'company_name': selected_company.name if selected_company else "All Companies (System Wide)",
        'selected_company': selected_company,
        'month_name': month_name,
        'current_date': now.strftime("%d/%m/%Y %H:%M"),
        'actor_name': user.username,
        'actor_role': user.get_role_display(),
        'theme_color': theme_color,
        'font_regular_path': font_regular_path,
        'font_bold_path': font_bold_path,
    }
    return context

# Dashboard Monthly Report View
class MonthlyReportView(LoginRequiredMixin, AdminRequiredMixin, TemplateView):
    template_name = 'tickets/report_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        company_id = self.request.GET.get('company_id')

        # Security: Enforce company filter for Client Admin
        if not (user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]):
            company_id = user.company.id

        report_context = get_report_context(user, company_id)
        context.update(report_context)

        selected_company = report_context['selected_company']

        # Get list of company members to display in the dropdown (for sending to individual)
        if selected_company:
            company_users = CustomUser.objects.filter(company=selected_company).order_by('username')
        else:
            company_users = CustomUser.objects.all().order_by('username')
        
        context['company_users'] = company_users

        # Retrieve Report Viewed Logs for this company
        if selected_company:
            view_logs = ReportViewLog.objects.select_related('viewer', 'company').filter(company=selected_company)[:50]
        else:
            view_logs = ReportViewLog.objects.select_related('viewer', 'company').all()[:50]
        context['view_logs'] = view_logs

        # Retrieve Report Sent Emails Logs for this company
        if selected_company:
            company_user_emails = list(company_users.exclude(email='').values_list('email', flat=True))
            sent_logs = EmailLog.objects.filter(action_type=EmailLog.ACTION_MONTHLY_REPORT, recipient__in=company_user_emails)[:50]
        else:
            sent_logs = EmailLog.objects.filter(action_type=EmailLog.ACTION_MONTHLY_REPORT)[:50]
        context['sent_logs'] = sent_logs

        # For system admin select dropdown
        if user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            context['companies'] = Company.objects.all()

        context['smtp_configs'] = SMTPConfiguration.objects.all().order_by('-is_active', 'name')

        return context

# View to generate and preview PDF
class GeneratePDFReportView(LoginRequiredMixin, AdminRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        user = self.request.user
        company_id = self.request.GET.get('company_id')

        # Security: Enforce company filter for Client Admin
        if not (user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]):
            company_id = user.company.id

        context = get_report_context(user, company_id)
        pdf = generate_pdf('tickets/report_pdf_template.html', context)
        
        if pdf:
            # Create a log entry indicating that this user viewed this company's report
            ReportViewLog.objects.create(
                viewer=user,
                company=context['selected_company'],
                report_month=context['month_name']
            )

            response = HttpResponse(pdf, content_type='application/pdf')
            # Inline display opens PDF inside browser preview tab
            filename = f"Monthly_Report_{context['company_name']}.pdf"
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            return response
        return HttpResponse("เกิดข้อผิดพลาดในการสร้างไฟล์ PDF", status=500)

# View to generate and send PDF report via email immediately (to entire company or to a specific individual)
class SendMonthlyReportView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        user = self.request.user
        company_id = request.POST.get('company_id')
        recipient_user_id = request.POST.get('recipient_user_id')

        # Security: Enforce company filter for Client Admin
        if not (user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]):
            company_id = user.company.id

        context = get_report_context(user, company_id)
        pdf_bytes = generate_pdf('tickets/report_pdf_template.html', context)

        if not pdf_bytes:
            messages.error(request, "เกิดข้อผิดพลาดในการสร้างไฟล์รายงาน PDF")
            return redirect('monthly_report')

        # Resolve recipient users list based on company and recipient_user_id parameter
        recipients = CustomUser.objects.all()
        if context['selected_company']:
            recipients = recipients.filter(company=context['selected_company'])
        
        # If sending to a specific individual
        if recipient_user_id:
            recipients = recipients.filter(id=recipient_user_id)
            if not recipients.exists():
                messages.error(request, "ไม่พบผู้ใช้ปลายทางที่ระบุ")
                return redirect('monthly_report')
            target_label = f"ผู้ใช้ {recipients.first().username}"
        else:
            target_label = f"ทุกคนใน {context['company_name']}"

        recipient_emails = list(recipients.exclude(email='').values_list('email', flat=True))

        if not recipient_emails:
            messages.error(request, f"ไม่พบอีเมลผู้ใช้งานของ {target_label} สำหรับการจัดส่งรายงาน")
            return redirect('monthly_report')

        # Create email
        subject = f"[TicketSolve] รายงานสรุปสถานะการแจ้งปัญหารายเดือน - {context['company_name']}"
        body = (
            f"เรียน ทีมงาน / พนักงาน {context['company_name']},\n\n"
            f"ระบบ TicketSolve ได้ออกรายงานสรุปสถานะการแจ้งปัญหารอบประจำเดือน {context['month_name']} เรียบร้อยแล้ว\n"
            f"ผู้ส่งรายงาน: {context['actor_name']} ({context['actor_role']})\n"
            f"จำนวนเคสทั้งหมดประจำเดือนนี้: {context['tickets_count']} รายการ (แก้ไขเสร็จสิ้น {context['done_count']} รายการ)\n\n"
            f"รายละเอียดเพิ่มเติมกรุณาเปิดไฟล์ PDF รายงานแนบฉบับนี้\n\n"
            f"ขอแสดงความนับถือ,\n"
            f"ทีมสนับสนุนระบบ TicketSolve"
        )

        # Resolve SMTP configuration dynamically based on user selection in request
        smtp_config_id = request.POST.get('smtp_config_id')
        connection = None
        from_email = settings.DEFAULT_FROM_EMAIL

        if smtp_config_id:
            smtp_config = SMTPConfiguration.objects.filter(id=smtp_config_id).first()
            if smtp_config:
                if smtp_config.provider != 'SIMULATION':
                    from django.core.mail.backends.smtp import EmailBackend
                    connection = EmailBackend(
                        host=smtp_config.host,
                        port=smtp_config.port,
                        username=smtp_config.username,
                        password=smtp_config.password,
                        use_tls=smtp_config.use_tls,
                        fail_silently=False
                    )
                    from_email = smtp_config.username or settings.DEFAULT_FROM_EMAIL
                else:
                    connection = None
                    from_email = smtp_config.username or settings.DEFAULT_FROM_EMAIL
        else:
            connection = get_smtp_connection()
            from_email = get_smtp_from_email(settings.DEFAULT_FROM_EMAIL)

        email = EmailMessage(
            subject,
            body,
            from_email,
            recipient_emails
        )
        
        # Attach PDF
        filename = f"Monthly_Report_{context['month_name'].replace(' ', '_')}_{context['company_name'].replace(' ', '_')}.pdf"
        email.attach(filename, pdf_bytes, 'application/pdf')

        try:
            if connection:
                email.connection = connection
            email.send(fail_silently=False)
            
            # Record email log in database for each recipient
            for recipient_email in recipient_emails:
                EmailLog.objects.create(
                    recipient=recipient_email,
                    subject=subject,
                    message=body,
                    action_type=EmailLog.ACTION_MONTHLY_REPORT,
                    success=True
                )

            messages.success(request, f"จัดส่งรายงานประจำเดือนให้ {target_label} (ทั้งหมด {len(recipient_emails)} บัญชี) สำเร็จเรียบร้อยแล้ว!")
        except Exception as e:
            messages.error(request, f"เกิดข้อผิดพลาดในการส่งอีเมล: {str(e)}")
            for recipient_email in recipient_emails:
                EmailLog.objects.create(
                    recipient=recipient_email,
                    subject=subject,
                    message=body,
                    action_type=EmailLog.ACTION_MONTHLY_REPORT,
                    success=False
                )

        return redirect('monthly_report')


# System Settings views (SMTP configurations)
class SystemSettingsView(LoginRequiredMixin, SuperuserOrSystemAdminRequiredMixin, TemplateView):
    template_name = 'tickets/settings.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        configs = SMTPConfiguration.objects.all().order_by('-is_active', 'name')
        context['configs'] = configs
        
        edit_id = self.request.GET.get('edit')
        if edit_id:
            config_instance = get_object_or_404(SMTPConfiguration, id=edit_id)
            form = SMTPConfigurationForm(instance=config_instance)
            context['editing_id'] = edit_id
        else:
            form = SMTPConfigurationForm()
            context['editing_id'] = None
            
        context['form'] = form
        return context

    def post(self, request, *args, **kwargs):
        edit_id = request.GET.get('edit')
        if edit_id:
            config_instance = get_object_or_404(SMTPConfiguration, id=edit_id)
            form = SMTPConfigurationForm(request.POST, instance=config_instance)
        else:
            form = SMTPConfigurationForm(request.POST)

        if form.is_valid():
            form.save()
            messages.success(request, "บันทึกการตั้งค่า SMTP สำเร็จเรียบร้อยแล้ว!")
            return redirect('system_settings')
        
        # If invalid, re-render context
        context = self.get_context_data(**kwargs)
        context['form'] = form
        return self.render_to_response(context)


class SMTPToggleActiveView(LoginRequiredMixin, SuperuserOrSystemAdminRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        config = get_object_or_404(SMTPConfiguration, pk=pk)
        config.is_active = not config.is_active
        config.save()
        messages.success(request, f"เปลี่ยนสถานะการใช้งานของ '{config.name}' เรียบร้อยแล้ว!")
        return redirect('system_settings')


class SMTPDeleteView(LoginRequiredMixin, SuperuserOrSystemAdminRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        config = get_object_or_404(SMTPConfiguration, pk=pk)
        name = config.name
        config.delete()
        messages.success(request, f"ลบการตั้งค่า '{name}' เรียบร้อยแล้ว!")
        return redirect('system_settings')


from django.http import HttpResponseRedirect

def set_language_view(request):
    lang = request.GET.get('lang', 'th')
    if lang not in ['th', 'en']:
        lang = 'th'
    response = HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))
    response.set_cookie('lang', lang, max_age=365*24*60*60)
    return response
