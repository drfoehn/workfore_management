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
] 