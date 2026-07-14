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
    
    # Custom User Management URLs
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/create/', views.UserCreateView.as_view(), name='user_create'),
    path('users/<int:pk>/edit/', views.UserUpdateView.as_view(), name='user_update'),

    # Custom Company Management URLs
    path('companies/', views.CompanyListView.as_view(), name='company_list'),
    path('companies/create/', views.CompanyCreateView.as_view(), name='company_create'),
    path('companies/<int:pk>/edit/', views.CompanyUpdateView.as_view(), name='company_update'),

    # Activity & Email Audit Log URLs
    path('logs/', views.LogListView.as_view(), name='log_list'),

    # Monthly PDF Report URLs
    path('report/', views.MonthlyReportView.as_view(), name='monthly_report'),
    path('report/preview/', views.GeneratePDFReportView.as_view(), name='report_preview'),
    path('report/send/', views.SendMonthlyReportView.as_view(), name='report_send'),

    # System settings (SMTP configurations) URLs
    path('settings/', views.SystemSettingsView.as_view(), name='system_settings'),
    path('settings/smtp/<int:pk>/toggle/', views.SMTPToggleActiveView.as_view(), name='smtp_toggle_active'),
    path('settings/smtp/<int:pk>/delete/', views.SMTPDeleteView.as_view(), name='smtp_delete'),

    # Language Switcher Route
    path('set-language/', views.set_language_view, name='set_language'),
]
