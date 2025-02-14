from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'wfm'

urlpatterns = [
    path('', views.index, name='index'),
    path('dashboard/', views.dashboard, name='dashboard'),

    
    path('working-hours/', views.WorkingHoursListView.as_view(), name='working-hours-list'),
    path('working-hours/add/', views.WorkingHoursCreateView.as_view(), name='working-hours-add'),
    path('working-hours/edit/<int:pk>/', views.WorkingHoursUpdateView.as_view(), name='working-hours-edit'),
    path('vacation/', views.VacationListView.as_view(), name='vacation-list'),
    path('vacation/request/', views.VacationRequestView.as_view(), name='vacation-request'),
    
    # Auth URLs
    path('login/', auth_views.LoginView.as_view(template_name='wfm/auth/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='wfm:index'), name='logout'),

    # AssistantViews
    path('monthly-overview/', views.MonthlyOverviewView.as_view(), name='monthly-overview'),
    path('time-compensation/add/', views.TimeCompensationCreateView.as_view(), name='time-compensation-add'),
    path('working-hours/edit/<int:pk>/', views.WorkingHoursUpdateView.as_view(), name='working-hours-edit'),
    path('working-hours/check/', views.WorkingHoursCreateOrUpdateView.as_view(), name='working-hours-check'),
    path('vacation/edit/<int:pk>/', views.VacationUpdateView.as_view(), name='vacation-edit'),
    path('time-compensation/edit/<int:pk>/', views.TimeCompensationUpdateView.as_view(), name='time-compensation-edit'),
    path('api/working-hours/<str:date>/', views.get_working_hours, name='api-get-working-hours'),
    path('api/working-hours/<str:date>/save/', views.save_working_hours, name='api-save-working-hours'),
    path('api/vacation/request/', views.api_vacation_request, name='api-vacation-request'),
    path('api/vacation/status/', views.api_vacation_status, name='api-vacation-status'),
    path('api/time-compensation/request/', views.api_time_compensation_request, name='api-time-compensation-request'),
    path('calendar/', views.CalendarView.as_view(), name='calendar'),
    path('api/calendar/events/', views.api_calendar_events, name='api-calendar-events'),
    
    
    path('owner/dashboard/', views.OwnerDashboardView.as_view(), name='owner-dashboard'),
    path('api/working-hours/<int:pk>/delete/', views.delete_working_hours, name='api-working-hours-delete'),

    # TherapistBookingViews
    path('therapist/monthly-overview/', views.TherapistMonthlyOverviewView.as_view(), name='therapist-monthly-overview'),
    path('therapist-bookings/', views.TherapistBookingListView.as_view(), name='therapist-booking-list'),
    path('api/therapist/booking/', views.api_therapist_booking, name='api-therapist-booking'),
    path('api/therapist/booking/used/', views.api_therapist_booking_used, name='api-therapist-booking-used'),
    path('api/therapist-booking/<int:pk>/', views.api_therapist_booking_detail, name='api-therapist-booking-detail'),
    path('api/therapist-booking/update/', views.api_therapist_booking_update, name='api-therapist-booking-update'),

    
    # AssistantCalendarView
    path('assistant-calendar/', views.AssistantCalendarView.as_view(), name='assistant-calendar'),
] 


