from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'wfm'

urlpatterns = [
    path('', views.index, name='index'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('working-hours/', views.WorkingHoursListView.as_view(), name='working-hours-list'),
    path('working-hours/add/', views.WorkingHoursCreateView.as_view(), name='working-hours-add'),
    path('vacation/', views.VacationListView.as_view(), name='vacation-list'),
    path('vacation/request/', views.VacationRequestView.as_view(), name='vacation-request'),
    
    # Auth URLs
    path('login/', auth_views.LoginView.as_view(template_name='wfm/auth/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='wfm:index'), name='logout'),

    path('monthly-overview/', views.MonthlyOverviewView.as_view(), name='monthly-overview'),
    path('time-compensation/add/', views.TimeCompensationCreateView.as_view(), name='time-compensation-add'),
    path('working-hours/edit/<int:pk>/', views.WorkingHoursUpdateView.as_view(), name='working-hours-edit'),
    path('working-hours/check/', views.WorkingHoursCreateOrUpdateView.as_view(), name='working-hours-check'),
    path('vacation/edit/<int:pk>/', views.VacationUpdateView.as_view(), name='vacation-edit'),
    path('time-compensation/edit/<int:pk>/', views.TimeCompensationUpdateView.as_view(), name='time-compensation-edit'),
    path('api/working-hours/<str:date>/', views.get_working_hours, name='api-get-working-hours'),
    path('api/working-hours/<str:date>/save/', views.save_working_hours, name='api-save-working-hours'),
    path('api/vacation/request/', views.api_vacation_request, name='api-vacation-request'),
    path('api/time-compensation/request/', views.api_time_compensation_request, name='api-time-compensation-request'),
] 