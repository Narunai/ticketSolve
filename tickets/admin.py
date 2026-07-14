from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Company, CustomUser, Ticket

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
        if request.user.is_superuser or request.user.role == CustomUser.SYSTEM_ADMIN:
            return qs
        if request.user.role == CustomUser.CLIENT_ADMIN:
            return qs.filter(company=request.user.company)
        return qs.none()

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
        elif obj.role == CustomUser.SYSTEM_ADMIN:
            obj.is_superuser = True
            obj.is_staff = True
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

admin.site.register(Company, CompanyAdmin)
admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(Ticket, TicketAdmin)
