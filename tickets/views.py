from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView
from django.contrib.auth import logout
from django.views.generic import CreateView, UpdateView, DetailView, TemplateView, ListView
from django.urls import reverse, reverse_lazy

from django.core.exceptions import PermissionDenied
from .models import Ticket, CustomUser, Company, EmailLog, TicketAuditLog, ReportViewLog, MonthlyReportSchedule, TicketAutomationConfig, SMTPConfiguration, get_smtp_connection, get_smtp_from_email, TicketComment, TicketCategory, ResolutionCategory, ModuleCategory, TicketStatusConfig, CompanyTicketConfig, CompanyTicketField, NotificationConfig, should_send_email_notification, BackupLog


from django.db import models
from django import forms



import os
import shutil
import datetime
import uuid

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse, Http404
from io import BytesIO
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.core.mail import EmailMessage, send_mail

from django.utils import timezone
from django.views import View
from types import SimpleNamespace

# Form for ticket creation
class TicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ['title', 'description', 'priority', 'ticket_category', 'module_category', 'category', 'attachment']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'placeholder': 'ระบุหัวข้อปัญหา...'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'placeholder': 'อธิบายรายละเอียดของปัญหา (ไม่บังคับ)...',
                'rows': 4
            }),
            'priority': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'ticket_category': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'module_category': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'category': forms.HiddenInput(),
            'attachment': forms.ClearableFileInput(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            })
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False
        self.fields['category'].required = False
        self.fields['ticket_category'].required = False
        self.fields['module_category'].required = False
        self.fields['ticket_category'].label = "หมวดหมู่ปัญหา (Category)"
        self.fields['module_category'].label = "หมวดหมู่โมดูล (Module Category)"

        inst_company = getattr(self.instance, 'company', None) if (self.instance and getattr(self.instance, 'company_id', None)) else None
        company = user.company if (user and user.company) else inst_company

        if not company and user and (user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]):
            self.fields['company'] = forms.ModelChoiceField(
                queryset=Company.objects.all(),
                required=True,
                label="บริษัทลูกค้า (Company)",
                widget=forms.Select(attrs={'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white'})
            )
            company = Company.objects.first()

        if company:
            from .models import CompanyTicketField
            CompanyTicketField.ensure_default_fields(company)
            company_fields = CompanyTicketField.objects.filter(company=company).order_by('order', 'id')
            parents = company.get_parents()
            self.fields['ticket_category'].queryset = TicketCategory.objects.filter(
                models.Q(company=None) | models.Q(company=company) | models.Q(company__in=parents),
                is_active=True
            )
            self.fields['module_category'].queryset = ModuleCategory.objects.filter(
                models.Q(company=None) | models.Q(company=company) | models.Q(company__in=parents),
                is_active=True
            )
        else:
            company_fields = None
            self.fields['ticket_category'].queryset = TicketCategory.objects.filter(is_active=True)
            self.fields['module_category'].queryset = ModuleCategory.objects.filter(is_active=True)

        self.custom_field_keys = []
        if company_fields:
            ordered_field_names = []
            for f_obj in company_fields:
                key = f_obj.field_key
                if not f_obj.is_visible and not f_obj.is_custom:
                    if key in self.fields:
                        self.fields[key].widget = forms.HiddenInput()
                        self.fields[key].required = False
                    continue

                if f_obj.is_custom:
                    self.custom_field_keys.append(key)
                    initial_val = self.instance.custom_fields_data.get(key, '') if self.instance else ''
                    if f_obj.field_type == CompanyTicketField.FIELD_TYPE_TEXTAREA:
                        self.fields[key] = forms.CharField(
                            label=f_obj.label,
                            required=f_obj.is_required,
                            initial=initial_val,
                            widget=forms.Textarea(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all', 'rows': 3, 'placeholder': f_obj.placeholder})
                        )
                    elif f_obj.field_type == CompanyTicketField.FIELD_TYPE_NUMBER:
                        self.fields[key] = forms.IntegerField(
                            label=f_obj.label,
                            required=f_obj.is_required,
                            initial=initial_val,
                            widget=forms.NumberInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all', 'placeholder': f_obj.placeholder})
                        )
                    elif f_obj.field_type == CompanyTicketField.FIELD_TYPE_SELECT:
                        choices = [(opt, opt) for opt in (f_obj.options or [])]
                        self.fields[key] = forms.ChoiceField(
                            label=f_obj.label,
                            required=f_obj.is_required,
                            initial=initial_val,
                            choices=[('', '-- เลือก --')] + choices,
                            widget=forms.Select(attrs={'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'})
                        )
                    elif f_obj.field_type == CompanyTicketField.FIELD_TYPE_DATE:
                        self.fields[key] = forms.DateField(
                            label=f_obj.label,
                            required=f_obj.is_required,
                            initial=initial_val,
                            widget=forms.DateInput(attrs={'type': 'date', 'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'})
                        )
                    elif f_obj.field_type == CompanyTicketField.FIELD_TYPE_BOOLEAN:
                        self.fields[key] = forms.BooleanField(
                            label=f_obj.label,
                            required=f_obj.is_required,
                            initial=bool(initial_val),
                            widget=forms.CheckboxInput(attrs={'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 h-4 w-4'})
                        )
                    else:
                        self.fields[key] = forms.CharField(
                            label=f_obj.label,
                            required=f_obj.is_required,
                            initial=initial_val,
                            widget=forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all', 'placeholder': f_obj.placeholder})
                        )
                else:
                    if key in self.fields:
                        self.fields[key].label = f_obj.label
                        if key not in ['ticket_category', 'module_category', 'description']:
                            self.fields[key].required = f_obj.is_required
                        if f_obj.placeholder and hasattr(self.fields[key].widget, 'attrs'):
                            self.fields[key].widget.attrs['placeholder'] = f_obj.placeholder


                ordered_field_names.append(key)

            new_fields = {}
            for k in ordered_field_names:
                if k in self.fields:
                    new_fields[k] = self.fields[k]
            for k, field in self.fields.items():
                if k not in new_fields:
                    new_fields[k] = field
            self.fields = new_fields

    def clean(self):
        cleaned_data = super().clean()
        cat = cleaned_data.get('category')
        ticket_cat = cleaned_data.get('ticket_category')
        valid_codes = [c[0] for c in Ticket.CATEGORY_CHOICES]

        if cat and not ticket_cat:
            match = TicketCategory.objects.filter(name__icontains=cat).first()
            if match:
                cleaned_data['ticket_category'] = match
        
        if ticket_cat:
            if ticket_cat.name.upper() in valid_codes:
                cleaned_data['category'] = ticket_cat.name.upper()
            else:
                cleaned_data['category'] = Ticket.CATEGORY_OTHER
        elif not cleaned_data.get('category'):
            cleaned_data['category'] = Ticket.CATEGORY_OTHER

        if 'category' in self.errors:
            del self.errors['category']

        files = []
        if self.files:
            files = self.files.getlist('attachments') or self.files.getlist('attachment')
        max_size = 10 * 1024 * 1024
        for f in files:
            if f.size > max_size:
                size_mb = f.size / (1024 * 1024)
                self.add_error('attachment', f"ขนาดไฟล์แนบ '{f.name}' ต้องไม่เกิน 10 MB (ไฟล์ของคุณขนาด {size_mb:.1f} MB)")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        custom_data = dict(instance.custom_fields_data or {})
        for k in getattr(self, 'custom_field_keys', []):
            if k in self.cleaned_data:
                val = self.cleaned_data[k]
                if isinstance(val, (datetime.datetime, datetime.date)):
                    val = str(val)
                custom_data[k] = val
        instance.custom_fields_data = custom_data
        if commit:
            instance.save()
            files = []
            if self.files:
                files = self.files.getlist('attachments') or self.files.getlist('attachment')
            from .models import TicketAttachment
            for f in files:
                att = TicketAttachment.objects.create(
                    ticket=instance,
                    file=f,
                    filename=f.name,
                    file_size=f.size
                )
                if not instance.attachment:
                    instance.attachment = att.file
                    instance.save(update_fields=['attachment'])
        return instance




# Form for ticket update (Status, Assignee, Priority, Resolution)
class TicketUpdateForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ['title', 'description', 'status', 'priority', 'ticket_category', 'module_category', 'assigned_to', 'resolution_category', 'resolution_notes', 'attachment']
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
            'ticket_category': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'module_category': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'assigned_to': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'resolution_category': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            }),
            'resolution_notes': forms.Textarea(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'placeholder': 'อธิบายสรุปวิธีการแก้ไขปัญหา...',
                'rows': 3
            }),
            'attachment': forms.ClearableFileInput(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            })
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False
        self.fields['ticket_category'].required = False
        self.fields['module_category'].required = False
        self.fields['ticket_category'].label = "หมวดหมู่ปัญหา (Category)"
        self.fields['module_category'].label = "หมวดหมู่โมดูล (Module Category)"
        ticket_company = self.instance.company if self.instance else (user.company if user else None)

        if user and user.company:
            self.fields['assigned_to'].queryset = CustomUser.objects.filter(company_id__in=user.company.get_all_subsidiary_ids())
            if user.role == CustomUser.CLIENT_USER:
                for field in ['title', 'description', 'priority', 'assigned_to', 'resolution_category', 'resolution_notes']:
                    if field in self.fields:
                        self.fields[field].disabled = True
        elif user and (user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]):
            self.fields['assigned_to'].queryset = CustomUser.objects.all()

        if ticket_company:
            from .models import CompanyTicketField
            CompanyTicketField.ensure_default_fields(ticket_company)
            company_fields = CompanyTicketField.objects.filter(company=ticket_company).order_by('order', 'id')

            self.fields['resolution_category'].queryset = ResolutionCategory.objects.filter(
                models.Q(company=None) | models.Q(company=ticket_company),
                is_active=True
            )
            self.fields['ticket_category'].queryset = TicketCategory.objects.filter(
                models.Q(company=None) | models.Q(company=ticket_company),
                is_active=True
            )
            self.fields['module_category'].queryset = ModuleCategory.objects.filter(
                models.Q(company=None) | models.Q(company=ticket_company),
                is_active=True
            )
        else:
            company_fields = None
            self.fields['resolution_category'].queryset = ResolutionCategory.objects.filter(is_active=True)
            self.fields['ticket_category'].queryset = TicketCategory.objects.filter(is_active=True)
            self.fields['module_category'].queryset = ModuleCategory.objects.filter(is_active=True)


        self.custom_field_keys = []
        if company_fields:
            ordered_field_names = []
            for f_obj in company_fields:
                key = f_obj.field_key
                if not f_obj.is_visible and not f_obj.is_custom:
                    if key in self.fields:
                        self.fields[key].widget = forms.HiddenInput()
                        self.fields[key].required = False
                    continue

                if f_obj.is_custom:
                    self.custom_field_keys.append(key)
                    initial_val = self.instance.custom_fields_data.get(key, '') if self.instance else ''
                    if f_obj.field_type == CompanyTicketField.FIELD_TYPE_TEXTAREA:
                        self.fields[key] = forms.CharField(
                            label=f_obj.label,
                            required=f_obj.is_required,
                            initial=initial_val,
                            widget=forms.Textarea(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all', 'rows': 3, 'placeholder': f_obj.placeholder})
                        )
                    elif f_obj.field_type == CompanyTicketField.FIELD_TYPE_NUMBER:
                        self.fields[key] = forms.IntegerField(
                            label=f_obj.label,
                            required=f_obj.is_required,
                            initial=initial_val,
                            widget=forms.NumberInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all', 'placeholder': f_obj.placeholder})
                        )
                    elif f_obj.field_type == CompanyTicketField.FIELD_TYPE_SELECT:
                        choices = [(opt, opt) for opt in (f_obj.options or [])]
                        self.fields[key] = forms.ChoiceField(
                            label=f_obj.label,
                            required=f_obj.is_required,
                            initial=initial_val,
                            choices=[('', '-- เลือก --')] + choices,
                            widget=forms.Select(attrs={'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'})
                        )
                    elif f_obj.field_type == CompanyTicketField.FIELD_TYPE_DATE:
                        self.fields[key] = forms.DateField(
                            label=f_obj.label,
                            required=f_obj.is_required,
                            initial=initial_val,
                            widget=forms.DateInput(attrs={'type': 'date', 'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'})
                        )
                    elif f_obj.field_type == CompanyTicketField.FIELD_TYPE_BOOLEAN:
                        self.fields[key] = forms.BooleanField(
                            label=f_obj.label,
                            required=f_obj.is_required,
                            initial=bool(initial_val),
                            widget=forms.CheckboxInput(attrs={'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 h-4 w-4'})
                        )
                    else:
                        self.fields[key] = forms.CharField(
                            label=f_obj.label,
                            required=f_obj.is_required,
                            initial=initial_val,
                            widget=forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all', 'placeholder': f_obj.placeholder})
                        )
                else:
                    if key in self.fields:
                        self.fields[key].label = f_obj.label
                        if key not in ['ticket_category', 'module_category', 'description']:
                            self.fields[key].required = f_obj.is_required
                        if f_obj.placeholder and hasattr(self.fields[key].widget, 'attrs'):
                            self.fields[key].widget.attrs['placeholder'] = f_obj.placeholder

                ordered_field_names.append(key)

            new_fields = {}
            for k in ordered_field_names:
                if k in self.fields:
                    new_fields[k] = self.fields[k]
            for k, field in self.fields.items():
                if k not in new_fields:
                    new_fields[k] = field
            self.fields = new_fields

    def save(self, commit=True):
        instance = super().save(commit=False)
        custom_data = dict(instance.custom_fields_data or {})
        for k in getattr(self, 'custom_field_keys', []):
            if k in self.cleaned_data:
                val = self.cleaned_data[k]
                if isinstance(val, (datetime.datetime, datetime.date)):
                    val = str(val)
                custom_data[k] = val
        instance.custom_fields_data = custom_data
        if commit:
            instance.save()
            files = []
            if self.files:
                files = self.files.getlist('attachments') or self.files.getlist('attachment')
            from .models import TicketAttachment
            for f in files:
                att = TicketAttachment.objects.create(
                    ticket=instance,
                    file=f,
                    filename=f.name,
                    file_size=f.size
                )
                if not instance.attachment:
                    instance.attachment = att.file
                    instance.save(update_fields=['attachment'])
        return instance


    def clean(self):
        cleaned_data = super().clean()
        if self.instance and self.instance.pk:
            for f in ['title', 'description', 'priority', 'ticket_category', 'category']:
                if f in self.fields and not cleaned_data.get(f):
                    cleaned_data[f] = getattr(self.instance, f)
                    if f in self.errors:
                        del self.errors[f]

        status = cleaned_data.get('status')
        resolution_notes = cleaned_data.get('resolution_notes')
        
        if status in [Ticket.STATUS_RESOLVED, Ticket.STATUS_CLOSED]:
            company = self.instance.company if self.instance else None
            require_note = True
            if company and hasattr(company, 'ticket_config'):
                require_note = company.ticket_config.require_resolution_note
                
            if require_note and not resolution_notes:
                self.add_error('resolution_notes', 'กรุณาระบุรายละเอียดสรุปวิธีแก้ไขปัญหาก่อนเปลี่ยนสถานะเป็น Resolved/Closed')

        files = []
        if self.files:
            files = self.files.getlist('attachments') or self.files.getlist('attachment')
        max_size = 50 * 1024 * 1024
        for f in files:
            if f.size > max_size:
                size_mb = f.size / (1024 * 1024)
                self.add_error('attachment', f"ขนาดไฟล์แนบ '{f.name}' ต้องไม่เกิน 50 MB (ไฟล์ของคุณขนาด {size_mb:.1f} MB)")

        return cleaned_data


class TicketCategoryForm(forms.ModelForm):
    class Meta:
        model = TicketCategory
        fields = ['name', 'company', 'description', 'icon_code', 'color_code', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'placeholder': 'ชื่อหมวดหมู่ปัญหา...'}),
            'company': forms.Select(attrs={'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white'}),
            'description': forms.Textarea(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'rows': 2, 'placeholder': 'คำอธิบายหมวดหมู่...'}),
            'icon_code': forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'placeholder': 'เช่น cpu, code, wifi'}),
            'color_code': forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'placeholder': 'เช่น #6366f1, #10b981'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 h-4 w-4'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'company' in self.fields:
            self.fields['company'].required = False
        if 'icon_code' in self.fields:
            self.fields['icon_code'].required = False
        if 'color_code' in self.fields:
            self.fields['color_code'].required = False
        if 'is_active' in self.fields:
            self.fields['is_active'].required = False


class ResolutionCategoryForm(forms.ModelForm):
    class Meta:
        model = ResolutionCategory
        fields = ['name', 'company', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'placeholder': 'ชื่อหมวดหมู่การแก้ปัญหา...'}),
            'company': forms.Select(attrs={'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white'}),
            'description': forms.Textarea(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'rows': 2, 'placeholder': 'คำอธิบายหมวดหมู่การแก้ปัญหา...'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 h-4 w-4'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'company' in self.fields:
            self.fields['company'].required = False
        if 'is_active' in self.fields:
            self.fields['is_active'].required = False


class ModuleCategoryForm(forms.ModelForm):
    class Meta:
        model = ModuleCategory
        fields = ['name', 'company', 'description', 'icon_code', 'color_code', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'placeholder': 'ชื่อหมวดหมู่โมดูล...'}),
            'company': forms.Select(attrs={'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white'}),
            'description': forms.Textarea(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'rows': 2, 'placeholder': 'คำอธิบายโมดูล...'}),
            'icon_code': forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'placeholder': 'เช่น cpu, code, layers'}),
            'color_code': forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'placeholder': 'เช่น #10b981, #3b82f6'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 h-4 w-4'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'company' in self.fields:
            self.fields['company'].required = False
        if 'icon_code' in self.fields:
            self.fields['icon_code'].required = False
        if 'color_code' in self.fields:
            self.fields['color_code'].required = False
        if 'is_active' in self.fields:
            self.fields['is_active'].required = False



class CompanyTicketConfigForm(forms.ModelForm):
    class Meta:
        model = CompanyTicketConfig
        fields = ['ticket_prefix', 'require_resolution_note', 'custom_help_text', 'allow_file_attachments']
        widgets = {
            'ticket_prefix': forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'placeholder': 'เช่น ACME-, SEC-'}),
            'custom_help_text': forms.Textarea(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'rows': 3, 'placeholder': 'ข้อความแนะนำช่วยเหลือประจำฟอร์ม...'}),
            'require_resolution_note': forms.CheckboxInput(attrs={'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 h-4 w-4'}),
            'allow_file_attachments': forms.CheckboxInput(attrs={'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 h-4 w-4'}),
        }


class CompanyTicketCustomFieldForm(forms.ModelForm):
    options_raw = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'placeholder': 'ตัวเลือก A, ตัวเลือก B, ตัวเลือก C (คั่นด้วยจุลภาค)'})
    )

    class Meta:
        model = CompanyTicketField
        fields = ['label', 'field_key', 'field_type', 'placeholder', 'is_required', 'order']
        widgets = {
            'label': forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'placeholder': 'เช่น หมายเลขอุปกรณ์ (Asset ID)'}),
            'field_key': forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'placeholder': 'เช่น asset_id, location'}),
            'field_type': forms.Select(attrs={'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white'}),
            'placeholder': forms.TextInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white', 'placeholder': 'เช่น ระบุรหัสทรัพย์สิน...'}),
            'is_required': forms.CheckboxInput(attrs={'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 h-4 w-4'}),
            'order': forms.NumberInput(attrs={'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white'}),
        }




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


class MonthlyReportScheduleForm(forms.ModelForm):
    send_hour = forms.ChoiceField(
        choices=[(f'{hour:02d}', f'{hour:02d}') for hour in range(24)],
        label='ชั่วโมง',
        widget=forms.Select(attrs={
            'class': 'w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-white',
        }),
    )
    send_minute = forms.ChoiceField(
        choices=[(f'{minute:02d}', f'{minute:02d}') for minute in range(60)],
        label='นาที',
        widget=forms.Select(attrs={
            'class': 'w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-white',
        }),
    )

    class Meta:
        model = MonthlyReportSchedule
        fields = [
            'name', 'company', 'recipients', 'cc_recipients',
            'smtp_configuration', 'day_of_month', 'timezone_name', 'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-white',
                'placeholder': 'เช่น ส่งรายงานให้ฝ่ายบริหาร',
            }),
            'company': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-white',
            }),
            'recipients': forms.CheckboxSelectMultiple(),
            'cc_recipients': forms.CheckboxSelectMultiple(),
            'smtp_configuration': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-white',
            }),
            'day_of_month': forms.NumberInput(attrs={
                'min': 1, 'max': 31,
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-white',
            }),
            'timezone_name': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-white',
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 h-4 w-4',
            }),
        }

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('user')
        selected_company = kwargs.pop('company', None)
        if args and args[0] is not None and 'send_hour' not in args[0] and args[0].get('send_time'):
            # Backward compatibility for older forms/API clients posting HH:MM.
            data = args[0].copy()
            hour, minute = data.get('send_time').split(':')[:2]
            data['send_hour'] = hour.zfill(2)
            data['send_minute'] = minute.zfill(2)
            args = (data,) + args[1:]
        super().__init__(*args, **kwargs)

        if not selected_company and self.instance and self.instance.pk:
            selected_company = self.instance.company

        user = self.request_user
        is_system_staff = user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]
        if is_system_staff:
            self.fields['company'].queryset = Company.objects.all().order_by('name')
            if selected_company:
                allowed_ids = selected_company.get_all_subsidiary_ids()
                users = CustomUser.objects.filter(company_id__in=allowed_ids)
            else:
                users = CustomUser.objects.all()
        else:
            selected_company = user.company
            self.fields['company'].queryset = Company.objects.filter(pk=getattr(user.company, 'pk', None))
            self.fields['company'].disabled = True
            allowed_ids = user.company.get_all_subsidiary_ids() if user.company else []
            users = CustomUser.objects.filter(company_id__in=allowed_ids)

        users = users.exclude(email='').order_by('username')
        self.fields['recipients'].queryset = users
        self.fields['cc_recipients'].queryset = users
        self.fields['smtp_configuration'].queryset = SMTPConfiguration.objects.all().order_by('-is_active', 'name')
        if selected_company and not self.is_bound and not self.instance.pk:
            self.fields['company'].initial = selected_company
        if not self.is_bound:
            current_time = self.instance.send_time if self.instance and self.instance.pk else datetime.time(17, 0)
            self.fields['send_hour'].initial = f'{current_time.hour:02d}'
            self.fields['send_minute'].initial = f'{current_time.minute:02d}'

    def clean(self):
        cleaned = super().clean()
        user = self.request_user
        if not (user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]):
            cleaned['company'] = user.company

        recipients = cleaned.get('recipients')
        cc_recipients = cleaned.get('cc_recipients')
        if recipients is not None and cc_recipients is not None:
            overlap = set(recipients.values_list('pk', flat=True)) & set(cc_recipients.values_list('pk', flat=True))
            if overlap:
                raise forms.ValidationError('ผู้รับหลักและผู้รับ CC ต้องไม่เป็นบุคคลเดียวกัน')
        return cleaned

    def save(self, commit=True):
        schedule = super().save(commit=False)
        schedule.send_time = datetime.time(
            int(self.cleaned_data['send_hour']),
            int(self.cleaned_data['send_minute']),
        )
        if commit:
            schedule.save()
            self.save_m2m()
        return schedule

def get_company_tree_choices(excluded_ids=None, allow_empty=True, empty_label='--------- (ไม่มี - เป็นบริษัทแม่สูงสุด)'):
    if excluded_ids is None:
        excluded_ids = []
    
    choices = []
    if allow_empty:
        choices.append(('', empty_label))
        
    visited = set()
    
    def build_branch(company, depth=0):
        if company.id in visited or company.id in excluded_ids:
            return
        visited.add(company.id)
        indent = "    " * depth + ("└─ " if depth > 0 else "")
        label = f"{indent}{company.name}"
        choices.append((company.id, label))
        
        children = company.subsidiaries.exclude(id__in=excluded_ids).order_by('name')
        for child in children:
            build_branch(child, depth + 1)

    roots = Company.objects.filter(parent__isnull=True).exclude(id__in=excluded_ids).order_by('name')
    for root in roots:
        build_branch(root, 0)
        
    remaining = Company.objects.exclude(id__in=excluded_ids).exclude(id__in=visited).order_by('name')
    for comp in remaining:
        build_branch(comp, 0)
        
    return choices


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ['name', 'parent']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all',
                'placeholder': 'ชื่อบริษัท/องค์กร...'
            }),
            'parent': forms.Select(attrs={
                'class': 'w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        excluded_ids = []
        if self.instance and self.instance.pk:
            excluded_ids = self.instance.get_all_subsidiary_ids()
        self.fields['parent'].choices = get_company_tree_choices(
            excluded_ids=excluded_ids,
            allow_empty=True,
            empty_label='--------- (ไม่มี - เป็นบริษัทแม่สูงสุด)'
        )


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

        if 'company' in self.fields:
            if user and not user.is_superuser and user.role == CustomUser.CLIENT_ADMIN and user.company:
                sub_ids = user.company.get_all_subsidiary_ids()
                allowed_companies = Company.objects.filter(id__in=sub_ids)
                choices = [('', '---------')] + [
                    (c.id, ("    " * c.get_depth() + ("└─ " if c.get_depth() > 0 else "") + c.name))
                    for c in allowed_companies
                ]
                self.fields['company'].choices = choices
            else:
                self.fields['company'].choices = get_company_tree_choices(allow_empty=True, empty_label='---------')


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
            if user.company:
                sub_ids = user.company.get_all_subsidiary_ids()
                tickets = Ticket.objects.filter(company_id__in=sub_ids)
                companies = Company.objects.filter(id__in=sub_ids)
                users = CustomUser.objects.filter(company_id__in=sub_ids)
            else:
                tickets = Ticket.objects.none()
                companies = Company.objects.none()
                users = CustomUser.objects.none()


        # Statistics (Base counts)
        context['tickets_count'] = tickets.count()
        context['open_count'] = tickets.filter(status=Ticket.STATUS_OPEN).count()
        context['in_progress_count'] = tickets.filter(status=Ticket.STATUS_IN_PROGRESS).count()
        context['deployment_requested_count'] = tickets.filter(status=Ticket.STATUS_DEPLOYMENT_REQUESTED).count()
        context['ready_to_deploy_count'] = tickets.filter(status=Ticket.STATUS_READY_TO_DEPLOY).count()
        context['resolved_count'] = tickets.filter(status=Ticket.STATUS_RESOLVED).count()
        context['closed_count'] = tickets.filter(status=Ticket.STATUS_CLOSED).count()

        context['high_priority_count'] = tickets.filter(priority=Ticket.PRIORITY_HIGH).count()
        context['medium_priority_count'] = tickets.filter(priority=Ticket.PRIORITY_MEDIUM).count()
        context['low_priority_count'] = tickets.filter(priority=Ticket.PRIORITY_LOW).count()

        # Query Parameter Filtering
        status_filter = self.request.GET.get('status')
        priority_filter = self.request.GET.get('priority')

        filtered_tickets = tickets
        valid_statuses = [
            Ticket.STATUS_OPEN,
            Ticket.STATUS_IN_PROGRESS,
            Ticket.STATUS_DEPLOYMENT_REQUESTED,
            Ticket.STATUS_READY_TO_DEPLOY,
            Ticket.STATUS_RESOLVED,
            Ticket.STATUS_CLOSED
        ]
        if status_filter in valid_statuses:
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
        kwargs['user'] = self.request.user
        return kwargs


    def form_valid(self, form):
        user = self.request.user
        if user.company:
            form.instance.company = user.company
        elif form.cleaned_data.get('company'):
            form.instance.company = form.cleaned_data.get('company')
        else:
            first_comp = Company.objects.first()
            if first_comp:
                form.instance.company = first_comp
            else:
                form.add_error(None, "ยังไม่มีบริษัทในระบบ กรุณาสร้างบริษัทก่อนเปิด Ticket")
                return self.form_invalid(form)

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
            if not user.company or obj.company_id not in user.company.get_all_subsidiary_ids():
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
            if not user.company or obj.company_id not in user.company.get_all_subsidiary_ids():
                raise PermissionDenied("คุณไม่มีสิทธิ์ดูรายละเอียด Ticket ของบริษัทอื่น")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['comments'] = self.object.comments.all().order_by('created_at')
        from .models import EmailLog
        context['email_logs'] = EmailLog.objects.filter(
            models.Q(subject__icontains=f"Ticket #{self.object.id}") |
            models.Q(message__icontains=f"Ticket #{self.object.id}")
        ).order_by('-sent_at')
        return context


    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        content = request.POST.get('content', '').strip()
        files = request.FILES.getlist('attachments') or request.FILES.getlist('comment_attachments')

        max_size = 10 * 1024 * 1024  # 10 MB
        for f in files:
            if f.size > max_size:
                size_mb = f.size / (1024 * 1024)
                messages.error(request, f"ไม่สามารถส่งความคิดเห็นได้: ไฟล์ '{f.name}' มีขนาดเกิน 10 MB (ขนาดไฟล์คือ {size_mb:.1f} MB)")
                return redirect('ticket_detail', pk=self.object.id)

        if content or files:
            comment = TicketComment.objects.create(
                ticket=self.object,
                author=request.user,
                content=content or "(แนบไฟล์ประกอบ)"
            )
            TicketAuditLog.objects.create(
                ticket=self.object,
                actor=request.user,
                details=f"💬 เพิ่มความคิดเห็น: \"{comment.content[:100]}\""
            )

            from .models import CommentAttachment
            for f in files:
                CommentAttachment.objects.create(
                    comment=comment,
                    file=f,
                    filename=f.name,
                    file_size=f.size
                )
            # Send email notifications to stakeholders
            self.send_comment_notifications(comment)
            messages.success(request, "โพสต์ความคิดเห็นและแนบไฟล์เรียบร้อยแล้ว")
        else:
            messages.success(request, 'เพิ่มความคิดเห็นเรียบร้อยแล้ว')
        return redirect('ticket_detail', pk=self.object.pk)

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
        delivery_group = uuid.uuid4()
        
        for email in recipients:
            if not should_send_email_notification(email, ticket=ticket, event_type=EmailLog.ACTION_COMMENT_ADDED):
                print(f"[Comment Email Filtered] Skipped email to {email} based on notification rules.")
                EmailLog.objects.create(
                    recipient=email,
                    recipient_type=EmailLog.RECIPIENT_TO,
                    delivery_group=delivery_group,
                    subject=subject,
                    message=message_body,
                    action_type=EmailLog.ACTION_COMMENT_ADDED,
                    success=False,
                    error_message="ข้ามการส่งตามกฎตั้งค่าการแจ้งเตือนของผู้รับ/บริษัท (Notification Filtered)"
                )
                continue

            sent_count = 0
            err_msg = ""
            try:
                kwargs = {
                    'subject': subject,
                    'message': message_body,
                    'from_email': from_email,
                    'recipient_list': [email],
                    'fail_silently': False
                }
                if connection:
                    kwargs['connection'] = connection
                sent_count = send_mail(**kwargs)
            except Exception as e:
                print(f"[Comment Email Error] Failed to send email to {email}: {e}")
                err_msg = str(e)
                sent_count = 0

            EmailLog.objects.create(
                recipient=email,
                recipient_type=EmailLog.RECIPIENT_TO,
                delivery_group=delivery_group,
                subject=subject,
                message=message_body,
                action_type=EmailLog.ACTION_COMMENT_ADDED,
                success=(sent_count > 0),
                error_message=err_msg
            )






def _ticket_file_paths(ticket):
    paths = set()
    if ticket.attachment and hasattr(ticket.attachment, 'path'):
        paths.add(ticket.attachment.path)
    for attachment in ticket.attachments.all():
        if attachment.file and hasattr(attachment.file, 'path'):
            paths.add(attachment.file.path)
    for comment in ticket.comments.all():
        for attachment in comment.attachments.all():
            if attachment.file and hasattr(attachment.file, 'path'):
                paths.add(attachment.file.path)
    return paths


def _existing_files_size(paths):
    total_bytes = 0
    for path in paths:
        try:
            if os.path.isfile(path):
                total_bytes += os.path.getsize(path)
        except OSError:
            continue
    return total_bytes


def _delete_ticket_files(ticket):
    """Delete all physical files for a ticket and return bytes actually removed."""
    paths = _ticket_file_paths(ticket)

    deleted_bytes = 0
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            file_size = os.path.getsize(path)
            os.remove(path)
            deleted_bytes += file_size
        except OSError:
            continue
    return deleted_bytes


def _server_disk_usage(ticket_used_bytes=0):
    disk_path = settings.MEDIA_ROOT if os.path.exists(settings.MEDIA_ROOT) else settings.BASE_DIR
    usage = shutil.disk_usage(disk_path)
    gib = 1024 ** 3
    mib = 1024 ** 2
    used_percent = (usage.used / usage.total * 100) if usage.total else 0
    system_used_bytes = max(usage.used - ticket_used_bytes, 0)
    return {
        'path': str(disk_path),
        'total_gb': usage.total / gib,
        'used_gb': usage.used / gib,
        'free_gb': usage.free / gib,
        'used_percent': used_percent,
        'ticket_used_bytes': ticket_used_bytes,
        'ticket_used_mb': ticket_used_bytes / mib,
        'ticket_used_gb': ticket_used_bytes / gib,
        'system_used_gb': system_used_bytes / gib,
    }


class TicketDeleteManagementView(LoginRequiredMixin, SystemStaffRequiredMixin, View):
    template_name = 'tickets/ticket_delete_list.html'

    def get(self, request, *args, **kwargs):
        queryset = Ticket.objects.all().select_related('company', 'created_by', 'ticket_category', 'assigned_to').order_by('-created_at')

        # Company filter
        company_id = request.GET.get('company_id')
        if company_id and company_id.isdigit():
            try:
                comp = Company.objects.get(pk=int(company_id))
                comp_ids = comp.get_all_subsidiary_ids()
                queryset = queryset.filter(company_id__in=comp_ids)
            except Company.DoesNotExist:
                pass

        # Year filter
        year = request.GET.get('year')
        if year and year.isdigit():
            queryset = queryset.filter(created_at__year=int(year))

        # Month filter
        month = request.GET.get('month')
        if month and month.isdigit():
            queryset = queryset.filter(created_at__month=int(month))

        # Specific Date filter (YYYY-MM-DD)
        date_str = request.GET.get('date', '').strip()
        if date_str:
            try:
                date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__date=date_obj)
            except ValueError:
                pass

        # Search query
        search_query = request.GET.get('search', '').strip()
        if search_query:
            if search_query.isdigit():
                queryset = queryset.filter(
                    models.Q(id=int(search_query)) |
                    models.Q(title__icontains=search_query) |
                    models.Q(created_by__username__icontains=search_query)
                )
            else:
                queryset = queryset.filter(
                    models.Q(title__icontains=search_query) |
                    models.Q(description__icontains=search_query) |
                    models.Q(created_by__username__icontains=search_query)
                )

        available_years = Ticket.objects.dates('created_at', 'year', order='DESC')
        years_list = [d.year for d in available_years] if available_years else [timezone.now().year]
        current_year = timezone.now().year
        if current_year not in years_list:
            years_list.append(current_year)
            years_list.sort(reverse=True)

        all_tickets = list(Ticket.objects.all().prefetch_related(
            'attachments', 'comments__attachments'
        ))
        ticket_size_by_id = {}
        all_ticket_paths = set()
        for ticket in all_tickets:
            paths = _ticket_file_paths(ticket)
            all_ticket_paths.update(paths)
            ticket_size_by_id[ticket.pk] = _existing_files_size(paths)
        ticket_used_bytes = _existing_files_size(all_ticket_paths)

        displayed_tickets = list(queryset.prefetch_related(
            'attachments', 'comments__attachments'
        ))
        for ticket in displayed_tickets:
            ticket.storage_size_mb = ticket_size_by_id.get(ticket.pk, 0) / (1024 ** 2)

        context = {
            'tickets': displayed_tickets,
            'companies': Company.objects.all().order_by('name'),
            'years_list': years_list,
            'months_list': [
                (1, 'มกราคม (Jan)'), (2, 'กุมภาพันธ์ (Feb)'), (3, 'มีนาคม (Mar)'),
                (4, 'เมษายน (Apr)'), (5, 'พฤษภาคม (May)'), (6, 'มิถุนายน (Jun)'),
                (7, 'กรกฎาคม (Jul)'), (8, 'สิงหาคม (Aug)'), (9, 'กันยายน (Sep)'),
                (10, 'ตุลาคม (Oct)'), (11, 'พฤศจิกายน (Nov)'), (12, 'ธันวาคม (Dec)')
            ],
            'selected_company_id': int(company_id) if (company_id and company_id.isdigit()) else '',
            'selected_year': int(year) if (year and year.isdigit()) else '',
            'selected_month': int(month) if (month and month.isdigit()) else '',
            'selected_date': date_str,
            'search_query': search_query,
            'total_count': len(displayed_tickets),
            'disk_usage': _server_disk_usage(ticket_used_bytes),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        ticket_ids = request.POST.getlist('ticket_ids')

        if action == 'delete_selected' and ticket_ids:
            tickets_to_delete = Ticket.objects.filter(id__in=ticket_ids).prefetch_related(
                'attachments', 'comments__attachments'
            )
            count = tickets_to_delete.count()
            deleted_bytes = 0

            for t in tickets_to_delete:
                deleted_bytes += _delete_ticket_files(t)

            id_summary = ", ".join([f"#{t.id}" for t in tickets_to_delete[:10]])
            if count > 10:
                id_summary += f" และอื่นๆ อีก {count - 10} รายการ"

            tickets_to_delete.delete()
            deleted_mb = deleted_bytes / (1024 ** 2)
            messages.success(
                request,
                f"ลบ Ticket จำนวน {count} รายการ ({id_summary}) สำเร็จ "
                f"คืนพื้นที่จากไฟล์แนบ {deleted_mb:.2f} MB"
            )
        else:
            messages.warning(request, "กรุณาเลือก Ticket ที่ต้องการลบอย่างน้อย 1 รายการ")

        redirect_url = reverse('ticket_delete_manage')
        query_params = request.GET.urlencode()
        if query_params:
            redirect_url += '?' + query_params
        return redirect(redirect_url)


class TicketDeleteView(LoginRequiredMixin, SystemStaffRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        ticket = get_object_or_404(Ticket, pk=pk)

        deleted_bytes = _delete_ticket_files(ticket)

        ticket_id = ticket.id
        ticket_title = ticket.title
        ticket.delete()

        deleted_mb = deleted_bytes / (1024 ** 2)
        messages.success(
            request,
            f"ลบ Ticket #{ticket_id} ('{ticket_title}') เรียบร้อยแล้ว "
            f"คืนพื้นที่จากไฟล์แนบ {deleted_mb:.2f} MB"
        )
        next_url = request.POST.get('next') or reverse('dashboard')
        return redirect(next_url)


class ConfirmDeploymentView(LoginRequiredMixin, View):
    def get(self, request, pk, *args, **kwargs):
        return self._process_confirmation(request, pk)

    def post(self, request, pk, *args, **kwargs):
        return self._process_confirmation(request, pk)

    def _process_confirmation(self, request, pk):
        ticket = get_object_or_404(Ticket, pk=pk)
        user = request.user

        if not user.is_superuser and user.role != CustomUser.SYSTEM_ADMIN:
            if not user.company or ticket.company_id not in user.company.get_all_subsidiary_ids():
                raise PermissionDenied("คุณไม่มีสิทธิ์เข้าถึงหรือยืนยันการ Deploy งานของบริษัทอื่น")

        if ticket.status == Ticket.STATUS_DEPLOYMENT_REQUESTED:
            old_status = ticket.status
            ticket.status = Ticket.STATUS_READY_TO_DEPLOY
            ticket.save(update_fields=['status'])

            TicketAuditLog.objects.create(
                ticket=ticket,
                actor=user,
                old_status=old_status,
                new_status=ticket.status,
                details=f"ยืนยันการอนุมัติให้ Deploy งานเรียบร้อยโดย {user.username} (สถานะเปลี่ยนเป็น Ready to Deploy)"
            )
            messages.success(request, f"⚡ ยืนยันการอนุมัติ Deploy งานสำหรับ Ticket #{ticket.id} เรียบร้อยแล้ว (สถานะเปลี่ยนเป็น Ready to Deploy)")
        elif ticket.status == Ticket.STATUS_READY_TO_DEPLOY:
            messages.info(request, f"Ticket #{ticket.id} อยู่ในสถานะ Ready to Deploy เรียบร้อยแล้ว")
        else:
            messages.warning(request, f"Ticket #{ticket.id} ไม่อยู่ในสถานะ Production Deployment Request (สถานะปัจจุบันคือ '{ticket.get_status_display()}')")


        return redirect('ticket_detail', pk=ticket.id)


class ResendEmailView(LoginRequiredMixin, SystemStaffRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        return self._resend_email(request, pk)

    def _resend_email(self, request, pk):
        scoped_queryset = _email_logs_for_user(request.user)
        email_log = get_object_or_404(scoped_queryset, pk=pk)
        delivery_logs = list(_delivery_logs_for(email_log, scoped_queryset))
        retry_logs = [
            log for log in delivery_logs
            if not log.success and not _is_filtered_email_log(log)
        ]
        if not retry_logs:
            messages.info(request, "รายการนี้ไม่มีอีเมลที่ล้มเหลวและต้องส่งซ้ำ")
            return redirect(request.META.get('HTTP_REFERER') or reverse('log_list'))

        to_recipients = [
            log.recipient for log in retry_logs if log.recipient_type == EmailLog.RECIPIENT_TO
        ]
        cc_recipients = [
            log.recipient for log in retry_logs if log.recipient_type == EmailLog.RECIPIENT_CC
        ]
        connection = get_smtp_connection()
        from_email = get_smtp_from_email(settings.DEFAULT_FROM_EMAIL)

        sent_count = 0
        err_msg = ""
        try:
            email = EmailMessage(
                subject=email_log.subject,
                body=email_log.message,
                from_email=from_email,
                to=to_recipients,
                cc=cc_recipients,
                connection=connection,
            )
            sent_count = email.send(fail_silently=False)
        except Exception as e:
            print(f"[Resend Email Error] {e}")
            err_msg = str(e)
            sent_count = 0


        if sent_count > 0:
            resent_at = timezone.now()
            for log in retry_logs:
                log.success = True
                log.error_message = ""
                log.sent_at = resent_at
            EmailLog.objects.bulk_update(retry_logs, ['success', 'error_message', 'sent_at'])
            messages.success(request, f"🔄 ส่งอีเมลซ้ำสำเร็จ {len(retry_logs)} ผู้รับ")
        else:
            attempted_at = timezone.now()
            for log in retry_logs:
                log.success = False
                log.error_message = err_msg
                log.sent_at = attempted_at
            EmailLog.objects.bulk_update(retry_logs, ['success', 'error_message', 'sent_at'])
            messages.error(request, f"❌ ส่งอีเมลซ้ำไม่สำเร็จ: {err_msg}")

        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('dashboard')
        return redirect(next_url)


# Custom User Management Views



class UserListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = CustomUser
    template_name = 'tickets/user_list.html'
    context_object_name = 'users_list'

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            return CustomUser.objects.all().order_by('company', 'username')
        if user.company:
            sub_ids = user.company.get_all_subsidiary_ids()
            return CustomUser.objects.filter(company_id__in=sub_ids).order_by('company', 'username')
        return CustomUser.objects.none()


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
                sub_ids = user.company.get_all_subsidiary_ids() if user.company else []
                if obj.company_id not in sub_ids:
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        companies_tree = []
        
        def add_to_tree(company, depth=0):
            company.tree_depth = depth
            company.has_children = company.subsidiaries.exists()
            companies_tree.append(company)
            for child in company.subsidiaries.all().order_by('name'):
                add_to_tree(child, depth + 1)
                
        roots = Company.objects.filter(parent__isnull=True).order_by('name')
        for root in roots:
            add_to_tree(root, 0)
            
        added_ids = [c.id for c in companies_tree]
        orphans = Company.objects.exclude(id__in=added_ids).order_by('name')
        for orphan in orphans:
            add_to_tree(orphan, 0)
            
        context['companies_list'] = companies_tree
        context['total_companies_count'] = Company.objects.count()
        return context


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
def _email_logs_for_user(user):
    queryset = EmailLog.objects.all()
    if user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
        return queryset
    if not user.company:
        return queryset.none()
    sub_ids = user.company.get_all_subsidiary_ids()
    allowed_emails = CustomUser.objects.filter(
        company_id__in=sub_ids
    ).exclude(email='').values_list('email', flat=True)
    return queryset.filter(recipient__in=allowed_emails)


def _is_filtered_email_log(log):
    return 'Filtered' in log.error_message or 'ข้ามการส่ง' in log.error_message


def _build_email_log_group(logs):
    logs = list(logs)
    representative = logs[0]
    to_recipients = list(dict.fromkeys(
        log.recipient for log in logs if log.recipient_type == EmailLog.RECIPIENT_TO
    ))
    cc_recipients = list(dict.fromkeys(
        log.recipient for log in logs if log.recipient_type == EmailLog.RECIPIENT_CC
    ))
    filtered_count = sum(1 for log in logs if _is_filtered_email_log(log))
    success_count = sum(1 for log in logs if log.success)
    failed_count = len(logs) - success_count - filtered_count
    if failed_count and success_count:
        status = 'partial'
    elif failed_count:
        status = 'failed'
    elif filtered_count and not success_count:
        status = 'filtered'
    elif filtered_count:
        status = 'partial'
    else:
        status = 'success'
    return SimpleNamespace(
        representative=representative,
        detail_id=representative.id,
        logs=logs,
        sent_at=representative.sent_at,
        subject=representative.subject,
        message=representative.message,
        action_type_display=representative.get_action_type_display(),
        to_recipients=to_recipients,
        cc_recipients=cc_recipients,
        success_count=success_count,
        failed_count=failed_count,
        filtered_count=filtered_count,
        status=status,
        error_messages=list(dict.fromkeys(log.error_message for log in logs if log.error_message)),
    )


def _group_email_logs(queryset, limit=100):
    grouped = {}
    order = []
    # Fetch extra recipient rows because multiple rows can collapse into one delivery.
    for log in queryset.order_by('-sent_at')[:500]:
        key = ('group', str(log.delivery_group)) if log.delivery_group else ('legacy', log.id)
        if key not in grouped:
            if len(order) >= limit:
                continue
            grouped[key] = []
            order.append(key)
        grouped[key].append(log)
    return [_build_email_log_group(grouped[key]) for key in order]


def _delivery_logs_for(log, scoped_queryset=None):
    queryset = scoped_queryset if scoped_queryset is not None else EmailLog.objects.all()
    if log.delivery_group:
        return queryset.filter(delivery_group=log.delivery_group).order_by('recipient_type', 'recipient')
    return queryset.filter(pk=log.pk)


class LogListView(LoginRequiredMixin, SystemStaffRequiredMixin, TemplateView):
    template_name = 'tickets/log_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        audit_logs = TicketAuditLog.objects.select_related(
            'ticket', 'actor', 'ticket__company'
        ).all()

        context['email_logs'] = _group_email_logs(_email_logs_for_user(user))
        context['email_log_count'] = len(context['email_logs'])
        context['audit_logs'] = audit_logs[:100]
        context['backup_logs'] = BackupLog.objects.all()[:100]
        context['backup_log_count'] = BackupLog.objects.count()
        return context


class EmailLogDetailView(LoginRequiredMixin, SystemStaffRequiredMixin, TemplateView):
    template_name = 'tickets/email_log_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        scoped_queryset = _email_logs_for_user(self.request.user)
        log = get_object_or_404(scoped_queryset, pk=self.kwargs['pk'])
        context['email_group'] = _build_email_log_group(
            _delivery_logs_for(log, scoped_queryset)
        )
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
        sub_ids = selected_company.get_all_subsidiary_ids()
        tickets = tickets.filter(company_id__in=sub_ids)


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


def _monthly_report_email_content(context):
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
    return subject, body


def _smtp_delivery_options(smtp_config=None):
    connection = None
    from_email = settings.DEFAULT_FROM_EMAIL
    if smtp_config:
        if smtp_config.provider != 'SIMULATION':
            from django.core.mail.backends.smtp import EmailBackend
            connection = EmailBackend(
                host=smtp_config.host,
                port=smtp_config.port,
                username=smtp_config.username,
                password=smtp_config.password,
                use_tls=smtp_config.use_tls,
                fail_silently=False,
            )
        from_email = smtp_config.username or settings.DEFAULT_FROM_EMAIL
    else:
        connection = get_smtp_connection()
        from_email = get_smtp_from_email(settings.DEFAULT_FROM_EMAIL)
    return connection, from_email


def send_scheduled_monthly_report(schedule):
    """Generate and send one saved schedule. Raises on delivery failure."""
    actor = schedule.created_by
    if not actor:
        raise ValueError('ไม่พบผู้สร้างตารางส่ง กรุณาแก้ไขและบันทึกรายการใหม่')

    context = get_report_context(actor, schedule.company_id)
    pdf_bytes = generate_pdf('tickets/report_pdf_template.html', context)
    if not pdf_bytes:
        raise RuntimeError('ไม่สามารถสร้างไฟล์รายงาน PDF ได้')

    recipient_emails = list(dict.fromkeys(
        schedule.recipients.exclude(email='').values_list('email', flat=True)
    ))
    cc_emails = list(dict.fromkeys(
        schedule.cc_recipients.exclude(email='').values_list('email', flat=True)
    ))
    cc_emails = [email for email in cc_emails if email not in recipient_emails]
    if not recipient_emails:
        raise ValueError('ตารางส่งไม่มีผู้รับหลักที่มีอีเมล')

    subject, body = _monthly_report_email_content(context)
    connection, from_email = _smtp_delivery_options(schedule.smtp_configuration)
    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=from_email,
        to=recipient_emails,
        cc=cc_emails,
        connection=connection,
    )
    filename = f"Monthly_Report_{context['month_name'].replace(' ', '_')}_{context['company_name'].replace(' ', '_')}.pdf"
    email.attach(filename, pdf_bytes, 'application/pdf')
    delivery_group = uuid.uuid4()

    try:
        sent_count = email.send(fail_silently=False)
        if sent_count <= 0:
            raise RuntimeError('SMTP ไม่ยืนยันการส่งอีเมล (ส่งได้ 0 ฉบับ)')
    except Exception as exc:
        for recipient_type, addresses in (
            (EmailLog.RECIPIENT_TO, recipient_emails),
            (EmailLog.RECIPIENT_CC, cc_emails),
        ):
            for recipient_email in addresses:
                EmailLog.objects.create(
                    recipient=recipient_email,
                    recipient_type=recipient_type,
                    delivery_group=delivery_group,
                    subject=subject,
                    message=body,
                    action_type=EmailLog.ACTION_MONTHLY_REPORT,
                    success=False,
                    error_message=str(exc),
                )
        raise

    for recipient_type, addresses in (
        (EmailLog.RECIPIENT_TO, recipient_emails),
        (EmailLog.RECIPIENT_CC, cc_emails),
    ):
        for recipient_email in addresses:
            EmailLog.objects.create(
                recipient=recipient_email,
                recipient_type=recipient_type,
                delivery_group=delivery_group,
                subject=subject,
                message=body,
                action_type=EmailLog.ACTION_MONTHLY_REPORT,
                success=True,
            )
    return len(recipient_emails), len(cc_emails)

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
            sub_ids = selected_company.get_all_subsidiary_ids()
            company_users = CustomUser.objects.filter(company_id__in=sub_ids).order_by('username')
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
        context['schedule_timezone'] = settings.TIME_ZONE

        schedule_id = self.request.GET.get('schedule_id')
        schedule_instance = None
        schedules = MonthlyReportSchedule.objects.select_related(
            'company', 'smtp_configuration', 'created_by'
        ).prefetch_related('recipients', 'cc_recipients')
        if user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            if selected_company:
                schedules = schedules.filter(company=selected_company)
        else:
            schedules = schedules.filter(company=user.company)
        if schedule_id:
            schedule_instance = get_object_or_404(schedules, pk=schedule_id)
        context['report_schedules'] = schedules
        context['editing_schedule'] = schedule_instance
        context['schedule_form'] = MonthlyReportScheduleForm(
            user=user,
            company=selected_company,
            instance=schedule_instance,
        )

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
        cc_user_ids = request.POST.getlist('cc_user_ids')

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
            recipients = recipients.filter(company_id__in=context['selected_company'].get_all_subsidiary_ids())

        allowed_users = recipients
        
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
        cc_emails = list(
            allowed_users.filter(id__in=cc_user_ids).exclude(email='').values_list('email', flat=True)
        )
        cc_emails = list(dict.fromkeys(email for email in cc_emails if email not in recipient_emails))

        if not recipient_emails:
            messages.error(request, f"ไม่พบอีเมลผู้ใช้งานของ {target_label} สำหรับการจัดส่งรายงาน")
            return redirect('monthly_report')

        subject, body = _monthly_report_email_content(context)

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
            recipient_emails,
            cc=cc_emails,
        )
        
        # Attach PDF
        filename = f"Monthly_Report_{context['month_name'].replace(' ', '_')}_{context['company_name'].replace(' ', '_')}.pdf"
        email.attach(filename, pdf_bytes, 'application/pdf')
        delivery_group = uuid.uuid4()

        try:
            if connection:
                email.connection = connection
            sent_count = email.send(fail_silently=False)
            if sent_count <= 0:
                raise RuntimeError('SMTP ไม่ยืนยันการส่งอีเมล (ส่งได้ 0 ฉบับ)')
            
            for recipient_type, addresses in (
                (EmailLog.RECIPIENT_TO, recipient_emails),
                (EmailLog.RECIPIENT_CC, cc_emails),
            ):
                for recipient_email in addresses:
                    EmailLog.objects.create(
                        recipient=recipient_email,
                        recipient_type=recipient_type,
                        delivery_group=delivery_group,
                        subject=subject,
                        message=body,
                        action_type=EmailLog.ACTION_MONTHLY_REPORT,
                        success=True,
                    )

            cc_label = f" และ CC {len(cc_emails)} บัญชี" if cc_emails else ""
            messages.success(request, f"จัดส่งรายงานประจำเดือนให้ {target_label} (ผู้รับหลัก {len(recipient_emails)} บัญชี{cc_label}) สำเร็จเรียบร้อยแล้ว!")
        except Exception as e:
            messages.error(request, f"เกิดข้อผิดพลาดในการส่งอีเมล: {str(e)}")
            for recipient_type, addresses in (
                (EmailLog.RECIPIENT_TO, recipient_emails),
                (EmailLog.RECIPIENT_CC, cc_emails),
            ):
                for recipient_email in addresses:
                    EmailLog.objects.create(
                        recipient=recipient_email,
                        recipient_type=recipient_type,
                        delivery_group=delivery_group,
                        subject=subject,
                        message=body,
                        action_type=EmailLog.ACTION_MONTHLY_REPORT,
                        success=False,
                        error_message=str(e),
                    )

        return redirect('monthly_report')


def _get_manageable_schedule(request, pk):
    schedule = get_object_or_404(MonthlyReportSchedule, pk=pk)
    user = request.user
    if not (user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]):
        if schedule.company_id != getattr(user.company, 'id', None):
            raise PermissionDenied('คุณไม่มีสิทธิ์จัดการตารางส่งของบริษัทอื่น')
    return schedule


class MonthlyReportScheduleSaveView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        schedule_id = request.POST.get('schedule_id')
        instance = _get_manageable_schedule(request, schedule_id) if schedule_id else None
        company = None
        company_id = request.POST.get('company')
        if company_id:
            company = Company.objects.filter(pk=company_id).first()
        if not (request.user.is_superuser or request.user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]):
            company = request.user.company

        form = MonthlyReportScheduleForm(
            request.POST,
            instance=instance,
            user=request.user,
            company=company,
        )
        if form.is_valid():
            schedule = form.save(commit=False)
            if not schedule.created_by_id:
                schedule.created_by = request.user
            schedule.save()
            form.save_m2m()
            messages.success(request, f"บันทึกตารางส่งอัตโนมัติ ‘{schedule.name}’ เรียบร้อยแล้ว")
            redirect_url = reverse('monthly_report')
            if schedule.company_id:
                redirect_url += f"?company_id={schedule.company_id}"
            return redirect(redirect_url)

        error_text = ' '.join(
            str(error) for errors in form.errors.values() for error in errors
        )
        messages.error(request, f"บันทึกตารางส่งไม่สำเร็จ: {error_text}")
        redirect_url = reverse('monthly_report')
        if company:
            redirect_url += f"?company_id={company.id}"
        return redirect(redirect_url)


class MonthlyReportScheduleToggleView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        schedule = _get_manageable_schedule(request, pk)
        schedule.is_active = not schedule.is_active
        schedule.save(update_fields=['is_active', 'updated_at'])
        status_label = 'เปิดใช้งาน' if schedule.is_active else 'หยุดใช้งาน'
        messages.success(request, f"{status_label}ตาราง ‘{schedule.name}’ แล้ว")
        return redirect('monthly_report')


class MonthlyReportScheduleDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        schedule = _get_manageable_schedule(request, pk)
        name = schedule.name
        schedule.delete()
        messages.success(request, f"ลบตารางส่ง ‘{name}’ แล้ว")
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


# Category & Resolution Management Views
class CategoryListView(LoginRequiredMixin, AdminRequiredMixin, TemplateView):
    template_name = 'tickets/category_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        selected_company_id = self.request.GET.get('company_id')

        if user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            companies = Company.objects.all()
            ticket_qs = TicketCategory.objects.all().select_related('company')
            res_qs = ResolutionCategory.objects.all().select_related('company')
            mod_qs = ModuleCategory.objects.all().select_related('company')
        else:
            if user.company:
                sub_ids = user.company.get_all_subsidiary_ids()
                companies = Company.objects.filter(id__in=sub_ids)
                ticket_qs = TicketCategory.objects.filter(
                    models.Q(company=None) | models.Q(company_id__in=sub_ids)
                ).select_related('company')
                res_qs = ResolutionCategory.objects.filter(
                    models.Q(company=None) | models.Q(company_id__in=sub_ids)
                ).select_related('company')
                mod_qs = ModuleCategory.objects.filter(
                    models.Q(company=None) | models.Q(company_id__in=sub_ids)
                ).select_related('company')
            else:
                companies = Company.objects.none()
                ticket_qs = TicketCategory.objects.none()
                res_qs = ResolutionCategory.objects.none()
                mod_qs = ModuleCategory.objects.none()

        selected_company = None
        if selected_company_id:
            if selected_company_id == 'global':
                ticket_qs = ticket_qs.filter(company=None)
                res_qs = res_qs.filter(company=None)
                mod_qs = mod_qs.filter(company=None)
            else:
                try:
                    c_id = int(selected_company_id)
                    selected_company = Company.objects.filter(id=c_id).first()
                    if selected_company:
                        sub_ids = selected_company.get_all_subsidiary_ids()
                        ticket_qs = ticket_qs.filter(models.Q(company=None) | models.Q(company_id__in=sub_ids))
                        res_qs = res_qs.filter(models.Q(company=None) | models.Q(company_id__in=sub_ids))
                        mod_qs = mod_qs.filter(models.Q(company=None) | models.Q(company_id__in=sub_ids))
                except ValueError:
                    pass

        initial_cat = {}
        initial_res = {}
        initial_mod = {}
        if selected_company:
            initial_cat['company'] = selected_company
            initial_res['company'] = selected_company
            initial_mod['company'] = selected_company

        context['ticket_categories'] = ticket_qs
        context['resolution_categories'] = res_qs
        context['module_categories'] = mod_qs
        context['category_form'] = TicketCategoryForm(initial=initial_cat)
        context['resolution_form'] = ResolutionCategoryForm(initial=initial_res)
        context['module_form'] = ModuleCategoryForm(initial=initial_mod)
        context['companies'] = companies
        context['selected_company_id'] = selected_company_id
        context['selected_company'] = selected_company
        return context




class TicketCategoryCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = TicketCategory
    form_class = TicketCategoryForm
    success_url = reverse_lazy('category_list')

    def form_valid(self, form):
        user = self.request.user
        if not user.is_superuser and user.role not in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            form.instance.company = user.company
        messages.success(self.request, f"เพิ่มหมวดหมู่ '{form.instance.name}' เรียบร้อยแล้ว!")
        return super().form_valid(form)

    def form_invalid(self, form):
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(self.request, f"ไม่สามารถสร้างหมวดหมู่ปัญหาได้ ({field}): {error}")
        return redirect('category_list')




class TicketCategoryUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = TicketCategory
    form_class = TicketCategoryForm
    success_url = reverse_lazy('category_list')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user
        if not user.is_superuser and user.role not in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            if obj.company != user.company:
                raise PermissionDenied("คุณไม่มีสิทธิ์แก้ไขหมวดหมู่ของบริษัทอื่นหรือหมวดหมู่ส่วนกลาง")
        return obj

    def form_valid(self, form):
        messages.success(self.request, f"บันทึกการแก้ไขหมวดหมู่ '{form.instance.name}' เรียบร้อยแล้ว!")
        return super().form_valid(form)

    def form_invalid(self, form):
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(self.request, f"ไม่สามารถแก้ไขหมวดหมู่ปัญหาได้ ({field}): {error}")
        return redirect('category_list')


class TicketCategoryDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        cat = get_object_or_404(TicketCategory, pk=pk)
        user = request.user
        if not user.is_superuser and user.role not in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            if cat.company != user.company:
                raise PermissionDenied("คุณไม่มีสิทธิ์ลบหมวดหมู่ของบริษัทอื่น")
        name = cat.name
        cat.delete()
        messages.success(request, f"ลบหมวดหมู่ '{name}' เรียบร้อยแล้ว!")
        return redirect('category_list')


class ResolutionCategoryCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = ResolutionCategory
    form_class = ResolutionCategoryForm
    success_url = reverse_lazy('category_list')

    def form_valid(self, form):
        user = self.request.user
        if not user.is_superuser and user.role not in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            form.instance.company = user.company
        messages.success(self.request, f"เพิ่มหมวดหมู่การแก้ปัญหา '{form.instance.name}' เรียบร้อยแล้ว!")
        return super().form_valid(form)

    def form_invalid(self, form):
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(self.request, f"ไม่สามารถสร้างหมวดหมู่การแก้ปัญหาได้ ({field}): {error}")
        return redirect('category_list')


class ResolutionCategoryUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = ResolutionCategory
    form_class = ResolutionCategoryForm
    success_url = reverse_lazy('category_list')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user
        if not user.is_superuser and user.role not in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            if obj.company != user.company:
                raise PermissionDenied("คุณไม่มีสิทธิ์แก้ไขหมวดหมู่การแก้ปัญหาของบริษัทอื่นหรือหมวดหมู่ส่วนกลาง")
        return obj

    def form_valid(self, form):
        messages.success(self.request, f"บันทึกการแก้ไขหมวดหมู่การแก้ปัญหา '{form.instance.name}' เรียบร้อยแล้ว!")
        return super().form_valid(form)

    def form_invalid(self, form):
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(self.request, f"ไม่สามารถแก้ไขหมวดหมู่การแก้ปัญหาได้ ({field}): {error}")
        return redirect('category_list')


class ResolutionCategoryDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):

    def post(self, request, pk, *args, **kwargs):
        cat = get_object_or_404(ResolutionCategory, pk=pk)
        user = request.user
        if not user.is_superuser and user.role not in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            if cat.company != user.company:
                raise PermissionDenied("คุณไม่มีสิทธิ์ลบหมวดหมู่การแก้ปัญหาของบริษัทอื่น")
        name = cat.name
        cat.delete()
        messages.success(request, f"ลบหมวดหมู่การแก้ปัญหา '{name}' เรียบร้อยแล้ว!")
        return redirect('category_list')


class ModuleCategoryCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = ModuleCategory
    form_class = ModuleCategoryForm
    success_url = reverse_lazy('category_list')

    def form_valid(self, form):
        user = self.request.user
        form.instance.is_active = True
        if not user.is_superuser and user.role not in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            form.instance.company = user.company
        messages.success(self.request, f"เพิ่มหมวดหมู่โมดูล '{form.instance.name}' เรียบร้อยแล้ว!")
        return super().form_valid(form)

    def form_invalid(self, form):
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(self.request, f"ไม่สามารถสร้างหมวดหมู่โมดูลได้ ({field}): {error}")
        return redirect('category_list')


class ModuleCategoryUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = ModuleCategory
    form_class = ModuleCategoryForm
    success_url = reverse_lazy('category_list')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user
        if not user.is_superuser and user.role not in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            if obj.company != user.company:
                raise PermissionDenied("คุณไม่มีสิทธิ์แก้ไขหมวดหมู่โมดูลของบริษัทอื่นหรือหมวดหมู่ส่วนกลาง")
        return obj

    def form_valid(self, form):
        messages.success(self.request, f"บันทึกการแก้ไขหมวดหมู่โมดูล '{form.instance.name}' เรียบร้อยแล้ว!")
        return super().form_valid(form)

    def form_invalid(self, form):
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(self.request, f"ไม่สามารถแก้ไขหมวดหมู่โมดูลได้ ({field}): {error}")
        return redirect('category_list')


class ModuleCategoryDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        cat = get_object_or_404(ModuleCategory, pk=pk)
        user = request.user
        if not user.is_superuser and user.role not in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            if cat.company != user.company:
                raise PermissionDenied("คุณไม่มีสิทธิ์ลบหมวดหมู่โมดูลของบริษัทอื่น")
        name = cat.name
        cat.delete()
        messages.success(request, f"ลบหมวดหมู่โมดูล '{name}' เรียบร้อยแล้ว!")
        return redirect('category_list')



class CompanyTicketDesignView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'tickets/company_ticket_design.html'

    def get_company(self, request, pk=None):
        user = request.user
        if pk and (user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]):
            return get_object_or_404(Company, pk=pk)
        elif user.company:
            return user.company
        else:
            raise PermissionDenied("กรุณาระบุบริษัทที่ต้องการดีไซน์ฟอร์ม Ticket")

    def get(self, request, pk=None):
        from .models import CompanyTicketField
        company = self.get_company(request, pk)
        CompanyTicketField.ensure_default_fields(company)
        config, _ = CompanyTicketConfig.objects.get_or_create(company=company)
        fields = CompanyTicketField.objects.filter(company=company).order_by('order', 'id')
        last_order = fields.last().order if fields.exists() else 0

        return render(request, self.template_name, {
            'company': company,
            'config_form': CompanyTicketConfigForm(instance=config),
            'custom_field_form': CompanyTicketCustomFieldForm(initial={'order': last_order + 10}),
            'fields': fields,
            'config': config
        })

    def post(self, request, pk=None):
        from .models import CompanyTicketField
        company = self.get_company(request, pk)
        config, _ = CompanyTicketConfig.objects.get_or_create(company=company)
        action = request.POST.get('action')

        if action == 'add_custom_field':
            form = CompanyTicketCustomFieldForm(request.POST)
            if form.is_valid():
                obj = form.save(commit=False)
                obj.company = company
                obj.is_custom = True
                opts = form.cleaned_data.get('options_raw', '')
                if opts:
                    obj.options = [opt.strip() for opt in opts.split(',') if opt.strip()]
                else:
                    obj.options = []
                obj.save()
                messages.success(request, f"เพิ่มฟิลด์เสริม '{obj.label}' เรียบร้อยแล้ว!")
            else:
                messages.error(request, "เกิดข้อผิดพลาดในการเพิ่มฟิลด์เสริม กรุณาตรวจสอบข้อมูล")

        elif action == 'move_field':
            field_id = request.POST.get('field_id')
            direction = request.POST.get('direction')
            field_obj = get_object_or_404(CompanyTicketField, id=field_id, company=company)
            fields = list(CompanyTicketField.objects.filter(company=company).order_by('order', 'id'))
            idx = next((i for i, f in enumerate(fields) if f.id == field_obj.id), -1)
            
            if direction == 'up' and idx > 0:
                prev_field = fields[idx - 1]
                field_obj.order, prev_field.order = prev_field.order, field_obj.order
                field_obj.save()
                prev_field.save()
                messages.success(request, f"ขยับลำดับฟิลด์ '{field_obj.label}' ขึ้นเรียบร้อยแล้ว")
            elif direction == 'down' and idx < len(fields) - 1:
                next_field = fields[idx + 1]
                field_obj.order, next_field.order = next_field.order, field_obj.order
                field_obj.save()
                next_field.save()
                messages.success(request, f"ขยับลำดับฟิลด์ '{field_obj.label}' ลงเรียบร้อยแล้ว")

        elif action == 'delete_custom_field':
            field_id = request.POST.get('field_id')
            field_obj = get_object_or_404(CompanyTicketField, id=field_id, company=company, is_custom=True)
            lbl = field_obj.label
            field_obj.delete()
            messages.success(request, f"ลบฟิลด์เสริม '{lbl}' เรียบร้อยแล้ว")

        elif action == 'update_config_and_fields':
            config_form = CompanyTicketConfigForm(request.POST, instance=config)
            if config_form.is_valid():
                config_form.save()
            
            fields = CompanyTicketField.objects.filter(company=company)
            for f_obj in fields:
                lbl_key = f"field_{f_obj.id}_label"
                req_key = f"field_{f_obj.id}_required"
                vis_key = f"field_{f_obj.id}_visible"
                ord_key = f"field_{f_obj.id}_order"
                
                if lbl_key in request.POST:
                    f_obj.label = request.POST.get(lbl_key, f_obj.label)
                f_obj.is_required = (req_key in request.POST)
                f_obj.is_visible = (vis_key in request.POST)
                if ord_key in request.POST:
                    try:
                        f_obj.order = int(request.POST.get(ord_key, f_obj.order))
                    except ValueError:
                        pass
                f_obj.save()

            messages.success(request, f"บันทึกการตั้งค่าและดีไซน์ Ticket ของบริษัท {company.name} เรียบร้อยแล้ว!")

        if pk:
            return redirect('company_ticket_design_pk', pk=company.id)
        return redirect('company_ticket_design')


class NotificationConfigForm(forms.ModelForm):
    status_checkboxes = forms.MultipleChoiceField(
        choices=Ticket.STATUS_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="เลือกสถานะ Ticket ที่ต้องการทริกเกอร์แจ้งเตือน"
    )

    class Meta:
        model = NotificationConfig
        fields = ['name', 'company', 'target_users', 'notify_ticket_created', 'status_notification_mode', 'notify_comments', 'apply_to_subsidiaries']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if self.instance and self.instance.pk:
            self.fields['status_checkboxes'].initial = self.instance.allowed_statuses or []
        else:
            self.fields['status_checkboxes'].initial = [s[0] for s in Ticket.STATUS_CHOICES]

        if user and not (user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]):
            if user.company:
                comp_ids = user.company.get_all_subsidiary_ids()
                self.fields['company'].queryset = Company.objects.filter(id__in=comp_ids)
                self.fields['target_users'].queryset = CustomUser.objects.filter(company_id__in=comp_ids)
            else:
                self.fields['company'].queryset = Company.objects.none()
                self.fields['target_users'].queryset = CustomUser.objects.none()
        else:
            self.fields['company'].queryset = Company.objects.all()
            self.fields['target_users'].queryset = CustomUser.objects.all()

        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-indigo-500'})
            elif isinstance(field.widget, forms.SelectMultiple):
                field.widget.attrs.update({
                    'class': 'w-full bg-slate-900 border border-slate-700 rounded-xl px-3.5 py-2.5 text-white focus:outline-none focus:border-indigo-500 text-sm min-h-[220px]',
                    'size': '9'
                })

            elif isinstance(field.widget, forms.CheckboxSelectMultiple):
                pass
            else:
                field.widget.attrs.update({'class': 'w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-indigo-500 text-sm'})

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.allowed_statuses = self.cleaned_data.get('status_checkboxes', [])
        if commit:
            instance.save()
            self.save_m2m()
        return instance



class NotificationConfigListView(LoginRequiredMixin, ListView):
    model = NotificationConfig
    template_name = 'tickets/notification_config_list.html'
    context_object_name = 'configs'

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            return NotificationConfig.objects.all().select_related('company').prefetch_related('target_users')
        elif user.company:
            comp_ids = user.company.get_all_subsidiary_ids()
            return NotificationConfig.objects.filter(company_id__in=comp_ids).select_related('company').prefetch_related('target_users')
        return NotificationConfig.objects.none()


class NotificationConfigCreateView(LoginRequiredMixin, CreateView):
    model = NotificationConfig
    form_class = NotificationConfigForm
    template_name = 'tickets/notification_config_form.html'
    success_url = reverse_lazy('notification_config_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import json
        company_hierarchy = {}
        for comp in Company.objects.all():
            company_hierarchy[str(comp.id)] = comp.get_all_subsidiary_ids()
        
        user_company_map = {}
        for u in CustomUser.objects.all():
            user_company_map[str(u.id)] = u.company_id if u.company_id else 0

        context['company_hierarchy_json'] = json.dumps(company_hierarchy)
        context['user_company_json'] = json.dumps(user_company_map)
        return context

    def form_valid(self, form):
        messages.success(self.request, f"สร้างกฎการตั้งค่าแจ้งเตือน '{form.instance.name}' เรียบร้อยแล้ว!")
        return super().form_valid(form)


class NotificationConfigUpdateView(LoginRequiredMixin, UpdateView):
    model = NotificationConfig
    form_class = NotificationConfigForm
    template_name = 'tickets/notification_config_form.html'
    success_url = reverse_lazy('notification_config_list')

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            return NotificationConfig.objects.all()
        elif user.company:
            comp_ids = user.company.get_all_subsidiary_ids()
            return NotificationConfig.objects.filter(company_id__in=comp_ids)
        return NotificationConfig.objects.none()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import json
        company_hierarchy = {}
        for comp in Company.objects.all():
            company_hierarchy[str(comp.id)] = comp.get_all_subsidiary_ids()
        
        user_company_map = {}
        for u in CustomUser.objects.all():
            user_company_map[str(u.id)] = u.company_id if u.company_id else 0

        context['company_hierarchy_json'] = json.dumps(company_hierarchy)
        context['user_company_json'] = json.dumps(user_company_map)
        return context

    def form_valid(self, form):
        messages.success(self.request, f"บันทึกการแก้ไขกฎแจ้งเตือน '{form.instance.name}' เรียบร้อยแล้ว!")
        return super().form_valid(form)



class NotificationConfigDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        user = request.user
        qs = NotificationConfig.objects.all()
        if not (user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]):
            if user.company:
                comp_ids = user.company.get_all_subsidiary_ids()
                qs = qs.filter(company_id__in=comp_ids)
            else:
                qs = qs.none()

        config = get_object_or_404(qs, pk=pk)
        name = config.name
        config.delete()
        messages.success(request, f"ลบกฎการตั้งค่าแจ้งเตือน '{name}' เรียบร้อยแล้ว!")
        return redirect('notification_config_list')


class TicketAutomationConfigForm(forms.ModelForm):
    class Meta:
        model = TicketAutomationConfig
        fields = ['company', 'open_age_value', 'open_age_unit', 'is_active', 'apply_to_subsidiaries']
        widgets = {
            'company': forms.Select(attrs={'class': 'w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-white'}),
            'open_age_value': forms.NumberInput(attrs={'min': 1, 'class': 'w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-white'}),
            'open_age_unit': forms.Select(attrs={'class': 'w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-white'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 h-4 w-4'}),
            'apply_to_subsidiaries': forms.CheckboxInput(attrs={'class': 'rounded bg-slate-900 border-slate-700 text-indigo-600 h-4 w-4'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        if user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            allowed_companies = Company.objects.all().order_by('name')
        elif user.company:
            allowed_companies = Company.objects.filter(id__in=user.company.get_all_subsidiary_ids()).order_by('name')
        else:
            allowed_companies = Company.objects.none()
        if self.instance and self.instance.pk:
            allowed_companies = allowed_companies.filter(
                models.Q(ticket_automation_config__isnull=True) | models.Q(pk=self.instance.company_id)
            )
        else:
            allowed_companies = allowed_companies.filter(ticket_automation_config__isnull=True)
        self.fields['company'].queryset = allowed_companies


class TicketAutomationListView(LoginRequiredMixin, SystemStaffRequiredMixin, ListView):
    model = TicketAutomationConfig
    template_name = 'tickets/ticket_automation_list.html'
    context_object_name = 'configs'

    def get_queryset(self):
        queryset = TicketAutomationConfig.objects.select_related('company', 'created_by')
        user = self.request.user
        if user.is_superuser or user.role in [CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN]:
            return queryset
        if user.company:
            return queryset.filter(company_id__in=user.company.get_all_subsidiary_ids())
        return queryset.none()


class TicketAutomationCreateView(LoginRequiredMixin, SystemStaffRequiredMixin, CreateView):
    model = TicketAutomationConfig
    form_class = TicketAutomationConfigForm
    template_name = 'tickets/ticket_automation_form.html'
    success_url = reverse_lazy('ticket_automation_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'บันทึก Ticket Auto Schedule เรียบร้อยแล้ว')
        return super().form_valid(form)


class TicketAutomationUpdateView(LoginRequiredMixin, SystemStaffRequiredMixin, UpdateView):
    model = TicketAutomationConfig
    form_class = TicketAutomationConfigForm
    template_name = 'tickets/ticket_automation_form.html'
    success_url = reverse_lazy('ticket_automation_list')

    def get_queryset(self):
        return TicketAutomationListView.get_queryset(self)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'อัปเดต Ticket Auto Schedule เรียบร้อยแล้ว')
        return super().form_valid(form)


class TicketAutomationDeleteView(LoginRequiredMixin, SystemStaffRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        queryset = TicketAutomationListView.get_queryset(self)
        config = get_object_or_404(queryset, pk=pk)
        config.delete()
        messages.success(request, 'ลบ Ticket Auto Schedule เรียบร้อยแล้ว')
        return redirect('ticket_automation_list')



