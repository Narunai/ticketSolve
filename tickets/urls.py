from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    path('', RedirectView.as_view(url='dashboard/', permanent=False)),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.custom_logout, name='logout'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('ticket/create/', views.TicketCreateView.as_view(), name='ticket_create'),
    path('ticket/<int:pk>/', views.TicketDetailView.as_view(), name='ticket_detail'),
    path('ticket/<int:pk>/edit/', views.TicketUpdateView.as_view(), name='ticket_update'),
    path('ticket/<int:pk>/delete/', views.TicketDeleteView.as_view(), name='ticket_delete'),
    path('ticket/<int:pk>/confirm-deployment/', views.ConfirmDeploymentView.as_view(), name='confirm_deployment'),
    path('email-log/<int:pk>/resend/', views.ResendEmailView.as_view(), name='resend_email'),
    path('tickets/manage-delete/', views.TicketDeleteManagementView.as_view(), name='ticket_delete_manage'),



    
    # Custom User Management URLs
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/create/', views.UserCreateView.as_view(), name='user_create'),
    path('users/<int:pk>/edit/', views.UserUpdateView.as_view(), name='user_update'),

    # Custom Company Management URLs
    path('companies/', views.CompanyListView.as_view(), name='company_list'),
    path('companies/create/', views.CompanyCreateView.as_view(), name='company_create'),
    path('companies/<int:pk>/edit/', views.CompanyUpdateView.as_view(), name='company_update'),

    # Category & Resolution Management URLs
    path('categories/', views.CategoryListView.as_view(), name='category_list'),
    path('categories/create/', views.TicketCategoryCreateView.as_view(), name='ticket_category_create'),
    path('categories/<int:pk>/edit/', views.TicketCategoryUpdateView.as_view(), name='ticket_category_update'),
    path('categories/<int:pk>/delete/', views.TicketCategoryDeleteView.as_view(), name='ticket_category_delete'),
    path('categories/resolution/create/', views.ResolutionCategoryCreateView.as_view(), name='resolution_category_create'),
    path('categories/resolution/<int:pk>/edit/', views.ResolutionCategoryUpdateView.as_view(), name='resolution_category_update'),
    path('categories/resolution/<int:pk>/delete/', views.ResolutionCategoryDeleteView.as_view(), name='resolution_category_delete'),

    # Notification Email Config URLs
    path('notification-configs/', views.NotificationConfigListView.as_view(), name='notification_config_list'),
    path('notification-configs/create/', views.NotificationConfigCreateView.as_view(), name='notification_config_create'),
    path('notification-configs/<int:pk>/edit/', views.NotificationConfigUpdateView.as_view(), name='notification_config_edit'),
    path('notification-configs/<int:pk>/delete/', views.NotificationConfigDeleteView.as_view(), name='notification_config_delete'),

    # Ticket status automation URLs
    path('ticket-automations/', views.TicketAutomationListView.as_view(), name='ticket_automation_list'),
    path('ticket-automations/create/', views.TicketAutomationCreateView.as_view(), name='ticket_automation_create'),
    path('ticket-automations/<int:pk>/edit/', views.TicketAutomationUpdateView.as_view(), name='ticket_automation_edit'),
    path('ticket-automations/<int:pk>/delete/', views.TicketAutomationDeleteView.as_view(), name='ticket_automation_delete'),

    # Company Ticket Customization URLs

    path('company/design/', views.CompanyTicketDesignView.as_view(), name='company_ticket_design'),
    path('company/<int:pk>/design/', views.CompanyTicketDesignView.as_view(), name='company_ticket_design_pk'),


    # Activity & Email Audit Log URLs
    path('logs/', views.LogListView.as_view(), name='log_list'),
    path('logs/email/<int:pk>/', views.EmailLogDetailView.as_view(), name='email_log_detail'),

    # Monthly PDF Report URLs
    path('report/', views.MonthlyReportView.as_view(), name='monthly_report'),
    path('report/preview/', views.GeneratePDFReportView.as_view(), name='report_preview'),
    path('report/send/', views.SendMonthlyReportView.as_view(), name='report_send'),
    path('report/schedules/save/', views.MonthlyReportScheduleSaveView.as_view(), name='report_schedule_save'),
    path('report/schedules/<int:pk>/toggle/', views.MonthlyReportScheduleToggleView.as_view(), name='report_schedule_toggle'),
    path('report/schedules/<int:pk>/delete/', views.MonthlyReportScheduleDeleteView.as_view(), name='report_schedule_delete'),

    # System settings (SMTP configurations) URLs
    path('settings/', views.SystemSettingsView.as_view(), name='system_settings'),
    path('settings/smtp/<int:pk>/toggle/', views.SMTPToggleActiveView.as_view(), name='smtp_toggle_active'),
    path('settings/smtp/<int:pk>/delete/', views.SMTPDeleteView.as_view(), name='smtp_delete'),

    # Language Switcher Route
    path('set-language/', views.set_language_view, name='set_language'),
]
