from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    Company,
    CustomUser,
    InboundEmailReceipt,
    InboundEmailRoutingRule,
    EmailToTicketRunLog,
    EmailToTicketSchedule,
    MonthlyReportSchedule,
    Ticket,
    TicketAutomationConfig,
)

class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    
    def has_module_permission(self, request):
        # Only system admin can see Company module
        return request.user.is_superuser or (hasattr(request.user, 'role') and request.user.role == CustomUser.SYSTEM_ADMIN)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or (hasattr(request.user, 'role') and request.user.role == CustomUser.SYSTEM_ADMIN)

class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'company', 'is_staff')
    list_filter = ('role', 'company', 'is_staff')
    
    fieldsets = UserAdmin.fieldsets + (
        ('Tenant & Role Settings', {'fields': ('role', 'company')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Tenant & Role Settings', {'fields': ('role', 'company')}),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if request.user.role == CustomUser.SYSTEM_ADMIN:
            return qs.filter(is_superuser=False)
        if request.user.role == CustomUser.CLIENT_ADMIN:
            return qs.filter(company=request.user.company, is_superuser=False)
        return qs.none()

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # If user is CLIENT_ADMIN, restrict their edits
        if not request.user.is_superuser and request.user.role == CustomUser.CLIENT_ADMIN:
            # Prevent them from changing company field, or restrict options
            if 'company' in form.base_fields:
                form.base_fields['company'].disabled = True
                form.base_fields['company'].initial = request.user.company
            # Restrict choices of roles
            if 'role' in form.base_fields:
                form.base_fields['role'].choices = [
                    (CustomUser.CLIENT_ADMIN, 'Client Administrator'),
                    (CustomUser.CLIENT_STAFF, 'Client Staff'),
                    (CustomUser.CLIENT_USER, 'Client User'),
                ]
            # Restrict list of user_permissions or groups editing if any, or hide them
            if 'is_superuser' in form.base_fields:
                form.base_fields['is_superuser'].disabled = True
            if 'is_staff' in form.base_fields:
                form.base_fields['is_staff'].disabled = True
        return form

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and request.user.role == CustomUser.CLIENT_ADMIN:
            obj.company = request.user.company
            # Ensure they don't escalate role
            if obj.role == CustomUser.SYSTEM_ADMIN:
                obj.role = CustomUser.CLIENT_USER
            # If CLIENT_ADMIN, they can make other users staff to login to admin
            if obj.role == CustomUser.CLIENT_ADMIN:
                obj.is_staff = True
        else:
            obj.is_staff = obj.role in [
                CustomUser.SYSTEM_ADMIN,
                CustomUser.SYSTEM_SUB_ADMIN,
                CustomUser.CLIENT_ADMIN,
            ]
            if not request.user.is_superuser:
                obj.is_superuser = False
        super().save_model(request, obj, form, change)

class TicketAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'created_by', 'assigned_to', 'status', 'priority', 'created_at')
    list_filter = ('status', 'priority', 'company')
    search_fields = ('title', 'description')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or request.user.role == CustomUser.SYSTEM_ADMIN:
            return qs
        if request.user.role == CustomUser.CLIENT_ADMIN:
            return qs.filter(company=request.user.company)
        return qs.none()

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if not request.user.is_superuser and request.user.role == CustomUser.CLIENT_ADMIN:
            if 'company' in form.base_fields:
                form.base_fields['company'].disabled = True
                form.base_fields['company'].initial = request.user.company
            if 'created_by' in form.base_fields:
                form.base_fields['created_by'].queryset = CustomUser.objects.filter(company=request.user.company)
            if 'assigned_to' in form.base_fields:
                form.base_fields['assigned_to'].queryset = CustomUser.objects.filter(
                    company=request.user.company
                )
        return form

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and request.user.role == CustomUser.CLIENT_ADMIN:
            obj.company = request.user.company
        super().save_model(request, obj, form, change)


@admin.register(MonthlyReportSchedule)
class MonthlyReportScheduleAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'day_of_month', 'send_time', 'timezone_name', 'is_active', 'last_sent_at')
    list_filter = ('is_active', 'timezone_name', 'company')
    search_fields = ('name', 'recipients__username', 'recipients__email')
    filter_horizontal = ('recipients', 'cc_recipients')


@admin.register(TicketAutomationConfig)
class TicketAutomationConfigAdmin(admin.ModelAdmin):
    list_display = ('company', 'open_age_value', 'open_age_unit', 'is_active', 'apply_to_subsidiaries', 'last_applied_at')
    list_filter = ('is_active', 'open_age_unit', 'apply_to_subsidiaries')


@admin.register(InboundEmailReceipt)
class InboundEmailReceiptAdmin(admin.ModelAdmin):
    list_display = ('subject', 'sender_email', 'status', 'smtp_configuration', 'ticket', 'processed_at')
    list_filter = ('status', 'smtp_configuration')
    search_fields = ('subject', 'sender_email', 'message_id')
    readonly_fields = (
        'smtp_configuration',
        'message_id',
        'sender_name',
        'sender_email',
        'subject',
        'status',
        'details',
        'ticket',
        'processed_at',
        'created_at',
    )

    def has_add_permission(self, request):
        return False


@admin.register(InboundEmailRoutingRule)
class InboundEmailRoutingRuleAdmin(admin.ModelAdmin):
    list_display = (
        'sender_email',
        'smtp_configuration',
        'assignee',
        'is_active',
        'updated_at',
    )
    list_filter = ('is_active', 'smtp_configuration')
    search_fields = ('sender_email', 'assignee__username', 'assignee__email')


@admin.register(EmailToTicketSchedule)
class EmailToTicketScheduleAdmin(admin.ModelAdmin):
    list_display = (
        'interval_minutes',
        'is_active',
        'last_run_at',
        'last_status',
        'updated_at',
    )
    readonly_fields = (
        'singleton_key',
        'last_run_at',
        'last_scheduled_run_at',
        'last_status',
        'updated_at',
        'updated_by',
    )

    def has_add_permission(self, request):
        return not EmailToTicketSchedule.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(EmailToTicketRunLog)
class EmailToTicketRunLogAdmin(admin.ModelAdmin):
    list_display = (
        'started_at',
        'trigger',
        'status',
        'mailbox_count',
        'found_count',
        'imported_count',
        'failed_count',
        'duration_ms',
    )
    list_filter = ('trigger', 'status')
    search_fields = ('details', 'actor__username')
    readonly_fields = (
        'schedule',
        'trigger',
        'status',
        'actor',
        'mailbox_count',
        'found_count',
        'imported_count',
        'skipped_count',
        'duplicate_count',
        'failed_count',
        'duration_ms',
        'details',
        'started_at',
        'completed_at',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Company, CompanyAdmin)
admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(Ticket, TicketAdmin)
