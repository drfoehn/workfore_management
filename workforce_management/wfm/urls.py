from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'wfm'

urlpatterns = [
    # Hauptseite/Dashboard
    path('', views.DashboardView.as_view(), name='dashboard'),
    
    # Auth URLs
    path('login/', auth_views.LoginView.as_view(template_name='wfm/auth/login.html'), name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Working Hours
    path('working-hours/', views.WorkingHoursListView.as_view(), name='working-hours-list'),
    # path('working-hours/check/', views.WorkingHoursCreateOrUpdateView.as_view(), name='working-hours-check'),
    path('api/working-hours/<int:pk>/', views.WorkingHoursDetailView.as_view(), name='api-working-hours-detail'),
    path('api/working-hours/<str:date>/', views.get_working_hours, name='api-get-working-hours'),
    path('api/working-hours/<str:date>/add/', views.WorkingHoursCreateView.as_view(), name='api-working-hours-add'),
    path('api/working-hours/<int:pk>/update/', views.WorkingHoursUpdateView.as_view(), name='api-working-hours-update'),
    path('api/working-hours/<int:pk>/delete/', views.WorkingHoursDeleteView.as_view(), name='api-working-hours-delete'),
    
    # Vacation & Time Compensation
    path('vacations/', views.VacationListView.as_view(), name='vacation-list'),
    path('vacation/edit/<int:pk>/', views.VacationUpdateView.as_view(), name='vacation-edit'),
    # path('time-compensations/', views.TimeCompensationListView.as_view(), name='time-compensation-list'),
    # path('time-compensation/add/', views.TimeCompensationCreateView.as_view(), name='time-compensation-add'),
    # path('time-compensation/edit/<int:pk>/', views.TimeCompensationUpdateView.as_view(), name='time-compensation-edit'),
    
    # API Endpoints
    path('api/vacation/request/', views.api_vacation_request, name='api-vacation-request'),
    path('api/vacation/status/', views.api_vacation_status, name='api-vacation-status'),
    # path('api/time-compensation/request/', views.api_time_compensation_request, name='api-time-compensation-request'),
    # path('api/time-compensation/status/', views.api_time_compensation_status, name='api-time-compensation-status'),
    path('api/sick-leave/', views.api_sick_leave, name='api-sick-leave'),
    path('api/scheduled-hours/', views.api_scheduled_hours, name='api-scheduled-hours'),
    path('api/vacation/calculate/', views.api_calculate_vacation_hours, name='api-vacation-calculate'),
    path('api/get-scheduled-hours/', views.api_get_scheduled_hours, name='api-get-scheduled-hours'),
    path('api/mark-therapist-extra-hours-as-paid/', views.api_mark_therapist_extra_hours_as_paid, name='api-mark-therapist-extra-hours-as-paid'),
    path('api/mark-overtime-as-paid/',  views.api_mark_overtime_as_paid,  name='api-mark-overtime-as-paid'),
    path('api/mark-salary-as-paid/', views.api_mark_salary_as_paid, name='api-mark-salary-as-paid'),
    
    # Calendars
    path('assistant-calendar/', views.AssistantCalendarView.as_view(), name='assistant-calendar'),
    path('therapist-calendar/', views.TherapistCalendarView.as_view(), name='therapist-calendar'),
    path('api/assistant-calendar/events/', views.AssistantCalendarEventsView.as_view(), name='api-assistant-calendar-events'),
    path('api/therapist-calendar/events/', views.TherapistCalendarEventsView.as_view(), name='api-therapist-calendar-events'),
    
    # Therapist Bookings
    path('therapist-bookings/', views.TherapistBookingListView.as_view(), name='therapist-booking-list'),
    path('therapist/monthly-overview/', views.TherapistMonthlyOverviewView.as_view(), name='therapist-monthly-overview'),
    path('api/therapist/booking/', views.api_therapist_booking, name='api-therapist-booking'),
    path('api/therapist/booking/used/', views.api_therapist_booking_used, name='api-therapist-booking-used'),
    path('api/therapist-booking/create/', views.TherapistBookingCreateView.as_view(), name='therapist-booking-create'),
    path('api/therapist-booking/<int:pk>/', views.TherapistBookingDetailView.as_view(), name='therapist-booking-detail'),
    path('api/therapist-booking/<int:pk>/update/', views.TherapistBookingUpdateView.as_view(), name='therapist-booking-update'),
    path('api/therapist-booking/<int:pk>/delete/', views.TherapistBookingDeleteView.as_view(), name='therapist-booking-delete'),
    path('api/therapist-booking/mark-as-paid/', views.api_therapist_booking_mark_as_paid, name='api-therapist-booking-mark-as-paid'),
    
    # Absences
    path('absences/', views.AbsenceListView.as_view(), name='absence-list'),
    path('api/absence/<str:type>/<int:pk>/delete/', views.api_delete_absence, name='api-delete-absence'),
    path('absence-management/', views.AbsenceManagementView.as_view(), name='absence-management'),

    # Overtime
    path('api/overtime/overview/', views.OvertimeOverviewView.as_view(), name='api-overtime-overview'),
    path('overtime/', views.OvertimeOverviewView.as_view(), name='overtime-overview'),
    path('calculate-balances/', views.calculate_balances, name='calculate_balances'),

    # Sick Leave Management
    path('sick-leave-management/', views.SickLeaveManagementView.as_view(), name='sick-leave-management'),

    # Dokumente
    path('documents/', views.UserDocumentListView.as_view(), name='user-documents'),
    path('documents/upload/', views.upload_document, name='upload-document'),
    path('documents/<int:pk>/delete/', views.delete_document, name='delete-document'),
    path('documents/<int:pk>/update/', views.api_document_update, name='api-document-update'),
    path('api/sick-leave/<int:sick_leave_id>/upload-document/', views.api_upload_sick_leave_document, name='api-upload-sick-leave-document'),

    # Mitarbeiter
    path('employees/', views.EmployeeListView.as_view(), name='employee-list'),
    path('employee/<int:pk>/', views.EmployeeDetailView.as_view(), name='employee-detail'),

    # Finance Overview
    path('finance-overview/', views.FinanceOverviewView.as_view(), name='finance-overview'),
    path('finance/yearly-report/', views.FinanceYearlyReportView.as_view(), name='finance-yearly-report'),

]



