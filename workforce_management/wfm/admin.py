from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from .models import (
    CustomUser,
    WorkingHours,
    Vacation,
    VacationEntitlement,
    ScheduleTemplate,
    SickLeave,
    TimeCompensation,
    TherapistBooking,
    TherapistScheduleTemplate,
    MonthlyReport
)

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'hourly_rate', 'room_rate', 'color')
    list_filter = ('role', 'is_active')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    
    # Basis-Felder von UserAdmin
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Persönliche Informationen'), {'fields': ('first_name', 'last_name', 'email', 'color')}),
        (_('Berechtigungen'), {'fields': ('role', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        (_('Vergütung'), {'fields': ('hourly_rate', 'room_rate')}),
        (_('Wichtige Daten'), {'fields': ('last_login', 'date_joined')}),
    )
    
    # Felder für das Anlegen neuer Benutzer
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'role', 'hourly_rate', 'room_rate'),
        }),
    )

@admin.register(TherapistBooking)
class TherapistBookingAdmin(admin.ModelAdmin):
    list_display = ('therapist', 'date', 'start_time', 'end_time', 'status')
    list_filter = ('status', 'date', 'therapist')
    search_fields = ('therapist__username', 'notes')
    date_hierarchy = 'date'
    ordering = ('-date', 'start_time')

@admin.register(TimeCompensation)
class TimeCompensationAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'hours', 'status', 'created_at')
    list_filter = ('status', 'date', 'employee')
    search_fields = ('employee__username', 'notes')
    date_hierarchy = 'date'
    ordering = ('-date',)

@admin.register(WorkingHours)
class WorkingHoursAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'start_time', 'end_time', 'break_duration')
    list_filter = ('date', 'employee')
    search_fields = ('employee__username', 'notes')
    date_hierarchy = 'date'

@admin.register(Vacation)
class VacationAdmin(admin.ModelAdmin):
    list_display = ('employee', 'start_date', 'end_date', 'status')
    list_filter = ('status', 'start_date', 'employee')
    search_fields = ('employee__username', 'notes')
    date_hierarchy = 'start_date'

@admin.register(VacationEntitlement)
class VacationEntitlementAdmin(admin.ModelAdmin):
    list_display = ('employee', 'year', 'total_days')
    list_filter = ('year', 'employee')
    search_fields = ('employee__username',)

@admin.register(SickLeave)
class SickLeaveAdmin(admin.ModelAdmin):
    list_display = ('employee', 'start_date', 'end_date', 'status', 'notes')
    list_filter = ('status', 'employee')
    search_fields = ('employee__username', 'employee__first_name', 'employee__last_name', 'notes')
    date_hierarchy = 'start_date'
    ordering = ('-start_date',)
    
    fieldsets = (
        (None, {
            'fields': ('employee', 'start_date', 'end_date')
        }),
        ('Status', {
            'fields': ('status', 'notes')
        }),
    )

@admin.register(ScheduleTemplate)
class ScheduleTemplateAdmin(admin.ModelAdmin):
    list_display = ('employee', 'get_weekday_display', 'start_time', 'end_time')
    list_filter = ('weekday', 'employee')
    search_fields = ('employee__username',)

@admin.register(TherapistScheduleTemplate)
class TherapistScheduleTemplateAdmin(admin.ModelAdmin):
    list_display = ('therapist', 'get_weekday_display', 'start_time', 'end_time')
    list_filter = ('weekday', 'therapist')
    search_fields = ('therapist__username',)

@admin.register(MonthlyReport)
class MonthlyReportAdmin(admin.ModelAdmin):
    list_display = ('employee', 'month', 'year', 'total_hours', 'total_amount')
    list_filter = ('year', 'month', 'employee')
    search_fields = ('employee__username',)
    date_hierarchy = 'generated_at'
