from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from .models import CustomUser, WorkingHours, Vacation, VacationEntitlement, ScheduleTemplate, SickLeave, TimeCompensation

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'hourly_rate', 'is_staff')
    list_filter = ('role', 'is_staff', 'is_active')
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'role', 'hourly_rate'),
        }),
    )
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Persönliche Informationen'), {'fields': ('first_name', 'last_name', 'email')}),
        (_('Arbeitsinformationen'), {'fields': ('role', 'hourly_rate')}),
        (_('Berechtigungen'), {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        (_('Wichtige Daten'), {'fields': ('last_login', 'date_joined')}),
    )
    
    search_fields = ('username', 'first_name', 'last_name', 'email')

@admin.register(WorkingHours)
class WorkingHoursAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'start_time', 'end_time', 'break_duration', 'shift_type')
    list_filter = ('employee', 'date', 'shift_type')
    search_fields = ('employee__username', 'employee__first_name', 'employee__last_name')
    date_hierarchy = 'date'

@admin.register(Vacation)
class VacationAdmin(admin.ModelAdmin):
    list_display = ('employee', 'start_date', 'end_date', 'status')
    list_filter = ('status', 'start_date', 'employee')
    search_fields = ('employee__username', 'employee__first_name', 'employee__last_name')
    date_hierarchy = 'start_date'

@admin.register(VacationEntitlement)
class VacationEntitlementAdmin(admin.ModelAdmin):
    list_display = ('employee', 'year', 'total_days')
    list_filter = ('year', 'employee')
    search_fields = ('employee__username', 'employee__first_name', 'employee__last_name')

@admin.register(ScheduleTemplate)
class ScheduleTemplateAdmin(admin.ModelAdmin):
    list_display = ('employee', 'weekday', 'start_time', 'end_time', 'shift_type')
    list_filter = ('weekday', 'shift_type', 'employee')
    search_fields = ('employee__username', 'employee__first_name', 'employee__last_name')

@admin.register(SickLeave)
class SickLeaveAdmin(admin.ModelAdmin):
    list_display = ('employee', 'start_date', 'end_date', 'document_provided')
    list_filter = ('document_provided', 'start_date', 'employee')
    search_fields = ('employee__username', 'employee__first_name', 'employee__last_name')
    date_hierarchy = 'start_date'

@admin.register(TimeCompensation)
class TimeCompensationAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'hours')
    list_filter = ('employee', 'date')
    search_fields = ('employee__username', 'employee__first_name', 'employee__last_name')
    date_hierarchy = 'date'
