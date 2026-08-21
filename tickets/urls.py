from django.urls import path
from django.views.generic import RedirectView
from . import views
from . import views_stream

urlpatterns = [
    path('', RedirectView.as_view(url='dashboard/', permanent=False)),
    path('events/stream/', views_stream.event_stream_view, name='event_stream'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.custom_logout, name='logout'),
    path('health/', views.healthcheck, name='healthcheck'),
    path('maintenance/access/', views.MaintenanceAccessView.as_view(), name='maintenance_access'),
    path('maintenance/settings/', views.MaintenanceSettingsView.as_view(), name='maintenance_settings'),
    # These endpoints are reachable only as internal Nginx auth subrequests in
    # production. They bind the isolated chatbot service to Django sessions.
    path('_internal/chatbot-auth/user/', views.chatbot_user_auth, name='chatbot_user_auth'),
    path('_internal/chatbot-auth/admin/', views.chatbot_admin_auth, name='chatbot_admin_auth'),
    path('account/password/', views.AccountPasswordView.as_view(), name='account_password'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('ticket/create/', views.TicketCreateView.as_view(), name='ticket_create'),
    path('ticket/<int:pk>/', views.TicketDetailView.as_view(), name='ticket_detail'),
    path('ticket/<int:pk>/edit/', views.TicketUpdateView.as_view(), name='ticket_update'),
    path('ticket/<int:pk>/preview-recipients/', views.TicketEmailRecipientPreviewView.as_view(), name='ticket_email_preview_recipients'),
    path('ticket/<int:pk>/attachment/', views.LegacyTicketAttachmentDownloadView.as_view(), name='ticket_legacy_attachment_download'),
    path('attachments/ticket/<int:pk>/download/', views.TicketAttachmentDownloadView.as_view(), name='ticket_attachment_download'),
    path('attachments/comment/<int:pk>/download/', views.CommentAttachmentDownloadView.as_view(), name='comment_attachment_download'),
    path('ticket/<int:pk>/delete/', views.TicketDeleteView.as_view(), name='ticket_delete'),
    path('ticket/<int:pk>/confirm-deployment/', views.ConfirmDeploymentView.as_view(), name='confirm_deployment'),
    path('email-log/<int:pk>/resend/', views.ResendEmailView.as_view(), name='resend_email'),
    path('tickets/manage-delete/', views.TicketDeleteManagementView.as_view(), name='ticket_delete_manage'),



    
    # Custom User Management URLs
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/create/', views.UserCreateView.as_view(), name='user_create'),
    path('users/<int:pk>/edit/', views.UserUpdateView.as_view(), name='user_update'),
    path('users/<int:pk>/simple-password/generate/', views.SimplePasswordGenerateView.as_view(), name='simple_password_generate'),

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
    path('categories/module/create/', views.ModuleCategoryCreateView.as_view(), name='module_category_create'),
    path('categories/module/<int:pk>/edit/', views.ModuleCategoryUpdateView.as_view(), name='module_category_update'),
    path('categories/module/<int:pk>/delete/', views.ModuleCategoryDeleteView.as_view(), name='module_category_delete'),


    # Notification Email Config URLs
    path('notification-configs/', views.NotificationConfigListView.as_view(), name='notification_config_list'),
    path('notification-configs/create/', views.NotificationConfigCreateView.as_view(), name='notification_config_create'),
    path('notification-configs/<int:pk>/edit/', views.NotificationConfigUpdateView.as_view(), name='notification_config_edit'),
    path('notification-configs/<int:pk>/delete/', views.NotificationConfigDeleteView.as_view(), name='notification_config_delete'),

    # Private in-app notifications
    path('notifications/', views.InAppNotificationListView.as_view(), name='notification_list'),
    path('notifications/<int:pk>/open/', views.InAppNotificationOpenView.as_view(), name='notification_open'),
    path('notifications/read-all/', views.InAppNotificationReadAllView.as_view(), name='notification_read_all'),

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
    path('settings/smtp/<int:pk>/import-email/', views.SMTPImportEmailView.as_view(), name='smtp_import_email'),
    path('settings/smtp/<int:pk>/delete/', views.SMTPDeleteView.as_view(), name='smtp_delete'),

    # Email to Ticket timer and execution logs
    path('email-timer/', views.EmailToTicketTimerView.as_view(), name='email_timer'),
    path('email-timer/run/', views.EmailToTicketTimerRunView.as_view(), name='email_timer_run'),
    path('email-timer/scan-step/', views.EmailToTicketBatchScanView.as_view(), name='email_timer_scan_step'),
    path('email-timer/keywords/save/', views.EmailToTicketKeywordFilterSaveView.as_view(), name='email_keyword_filter_save'),
    path('email-timer/routing/save/', views.InboundEmailRoutingRuleSaveView.as_view(), name='email_routing_rule_save'),
    path('email-timer/routing/<int:pk>/delete/', views.InboundEmailRoutingRuleDeleteView.as_view(), name='email_routing_rule_delete'),
    path('email-timer/pending/<int:pk>/approve/', views.InboundEmailApproveView.as_view(), name='inbound_email_approve'),
    path('email-timer/pending/<int:pk>/reject/', views.InboundEmailRejectView.as_view(), name='inbound_email_reject'),
    path('email-timer/pending-attachments/<int:pk>/download/', views.InboundEmailAttachmentDownloadView.as_view(), name='inbound_email_attachment_download'),

    # Backup Management URLs
    path('backups/', views.BackupManagementView.as_view(), name='backup_list'),
    path('backups/trigger/', views.TriggerBackupView.as_view(), name='backup_trigger'),
    path('backups/schedule/', views.BackupScheduleUpdateView.as_view(), name='backup_schedule_update'),
    path('backups/import/start/', views.BackupImportStartView.as_view(), name='backup_import_start'),
    path('backups/import/<uuid:upload_id>/chunk/', views.BackupImportChunkView.as_view(), name='backup_import_chunk'),
    path('backups/import/<uuid:upload_id>/complete/', views.BackupImportCompleteView.as_view(), name='backup_import_complete'),
    path('backups/import/<uuid:upload_id>/cancel/', views.BackupImportCancelView.as_view(), name='backup_import_cancel'),
    path('backups/<int:pk>/validate/', views.BackupValidateView.as_view(), name='backup_validate'),
    path('backups/<int:pk>/restore/', views.BackupRestoreRequestView.as_view(), name='backup_restore_request'),
    path('backups/restore-jobs/<uuid:job_id>/open-system/', views.RestoreOpenSystemView.as_view(), name='restore_open_system'),
    path('backups/<int:pk>/download/', views.DownloadBackupView.as_view(), name='backup_download'),
    path('backups/<int:pk>/delete/', views.DeleteBackupLogView.as_view(), name='backup_delete'),
    path('backups/delete-zero-mb/', views.DeleteAllZeroMbBackupsView.as_view(), name='backup_delete_zero_mb'),
]
