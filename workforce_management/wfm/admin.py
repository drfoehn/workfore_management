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
    # MonthlyReport,
    OvertimeAccount,
    UserDocument,
    ClosureDay,
    OvertimeEntry,
    MonthlyWage,
    OvertimePayment
)
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from django.utils import timezone
from django.contrib import messages
from django.db.models import F

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'phone', 'employed_since')
    list_filter = ('role', 'is_active')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'phone', 'mobile', 'street', 'city')
    
    # Basis-Felder von UserAdmin
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Persönliche Informationen'), {
            'fields': (
                'first_name', 
                'last_name', 
                'email',
                'phone',
                'mobile',
                'date_of_birth',
                'street',
                'zip_code',
                'city',
                'color'
            )
        }),
        (_('Beschäftigung'), {
            'fields': (
                'role',
                'employed_since',
                'hourly_rate',
                'room_rate'
            )
        }),
        (_('Berechtigungen'), {
            'fields': (
                'is_active',
                'is_staff',
                'is_superuser',
                'groups',
                'user_permissions'
            )
        }),
        (_('Wichtige Daten'), {
            'fields': ('last_login', 'date_joined')
        }),
    )
    
    # Felder für das Anlegen neuer Benutzer
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'username',
                'password1',
                'password2',
                'email',
                'first_name',
                'last_name',
                'role',
                'employed_since',
                'hourly_rate',
                'room_rate'
            ),
        }),
    )

@admin.register(TherapistBooking)
class TherapistBookingAdmin(admin.ModelAdmin):
    list_display = ('therapist', 'date', 'start_time', 'end_time', 'hours', 'actual_hours', 'difference_hours', 'is_paid', 'paid_date')
    list_filter = ('is_paid', 'date', 'therapist')
    search_fields = ('therapist__username', 'notes')
    date_hierarchy = 'date'
    ordering = ('-date', 'start_time')
    actions = ['mark_as_paid', 'mark_as_unpaid']

    def mark_as_paid(self, request, queryset):
        current_date = timezone.now().date()
        updated = queryset.update(
            is_paid=True,
            paid_date=current_date
        )
        self.message_user(
            request,
            _(f'{updated} Buchungen wurden als bezahlt markiert.'),
            messages.SUCCESS
        )
    mark_as_paid.short_description = _('Als bezahlt markieren')

    def mark_as_unpaid(self, request, queryset):
        updated = queryset.update(
            is_paid=False,
            paid_date=None
        )
        self.message_user(
            request,
            _(f'{updated} Buchungen wurden als unbezahlt markiert.'),
            messages.SUCCESS
        )
    mark_as_unpaid.short_description = _('Bezahlung zurücksetzen')

    def get_queryset(self, request):
        # Zeige nur Buchungen mit Mehrstunden
        return super().get_queryset(request).filter(actual_hours__gt=F('hours'))

@admin.register(TimeCompensation)
class TimeCompensationAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'hours', 'status')
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
    list_display = ('employee', 'year', 'total_hours')
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
    list_display = ('employee', 'get_weekday_display', 'start_time', 'end_time', 'valid_from')
    list_filter = ('weekday', 'employee')
    search_fields = ('employee__username',)

@admin.register(TherapistScheduleTemplate)
class TherapistScheduleTemplateAdmin(admin.ModelAdmin):
    list_display = ('therapist', 'get_weekday_display', 'start_time', 'end_time', 'valid_from')
    list_filter = ('weekday', 'therapist')
    search_fields = ('therapist__username',)

# @admin.register(MonthlyReport)
# class MonthlyReportAdmin(admin.ModelAdmin):
#     list_display = ('employee', 'month', 'year', 'total_hours', 'total_amount')
#     list_filter = ('year', 'month', 'employee')
#     search_fields = ('employee__username',)
#     date_hierarchy = 'generated_at'

@admin.register(OvertimeAccount)
class OvertimeAccountAdmin(admin.ModelAdmin):
    list_display = [
        'employee', 
        'year', 
        'month', 
        'balance', 
        'current_balance',

    ]
    list_filter = ['employee', 'year', 'month']
    search_fields = ['employee__first_name', 'employee__last_name']
    ordering = ['-year', '-month', 'employee__first_name']
    
    def get_readonly_fields(self, request, obj=None):
        if obj and obj.payment_locked_until:  # Wenn Eintrag gesperrt ist
            return self.readonly_fields + ['hours_for_payment', 'payment_locked_until']
        return self.readonly_fields
    
    actions = ['mark_as_paid']

    def mark_as_paid(self, request, queryset):
        for account in queryset:
            if account.hours_for_payment > 0 and not account.overtime_paid:
                account.overtime_paid = True
                account.overtime_paid_date = timezone.now()
                account.save()
    mark_as_paid.short_description = _("Als ausgezahlt markieren")


@admin.register(OvertimePayment)
class OvertimePaymentAdmin(admin.ModelAdmin):
    list_display = ['employee', 'hours_for_payment', 'created_at', 'amount', 'is_paid', 'paid_date']
    list_filter = ['employee', 'is_paid']
    search_fields = ['employee__username', 'employee__first_name', 'employee__last_name']
    date_hierarchy = 'paid_date'


@admin.register(UserDocument)
class UserDocumentAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'user', 'uploaded_at']
    list_filter = ['user']
    search_fields = ['display_name', 'notes']
    date_hierarchy = 'uploaded_at'

class ClosureDayResource(resources.ModelResource):
    class Meta:
        model = ClosureDay
        import_id_fields = ['date', 'type']
        fields = ('date', 'name', 'type', 'is_recurring', 'notes')
        export_order = fields

@admin.register(ClosureDay)
class ClosureDayAdmin(ImportExportModelAdmin):
    list_display = ['date', 'name', 'type', 'is_recurring']
    list_filter = ['type', 'is_recurring']
    search_fields = ['name', 'notes']
    date_hierarchy = 'date'
    resource_class = ClosureDayResource

@admin.register(OvertimeEntry)
class OvertimeEntryAdmin(admin.ModelAdmin):
    list_display = ['employee', 'date', 'hours', 'is_locked', 'created_at']
    list_filter = ['employee', 'is_locked', 'date']
    search_fields = ['employee__username', 'employee__first_name', 'employee__last_name']
    date_hierarchy = 'date'

@admin.register(MonthlyWage)
class MonthlyWageAdmin(admin.ModelAdmin):
    list_display = [
        'employee', 
        'year', 
        'month', 
        'total_hours',
        'wage',
        'updated_at'
    ]
    list_filter = ['year', 'month', 'employee']
    search_fields = [
        'employee__username', 
        'employee__first_name', 
        'employee__last_name'
    ]
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-year', '-month', 'employee__first_name']
    
    actions = ['recalculate_wages', 'change_is_paid_true', 'change_is_paid_false']
    
    def recalculate_wages(self, request, queryset):
        """Neuberechnung der ausgewählten Monatslöhne"""
        for wage in queryset:
            wage.calculate_wage()
        self.message_user(
            request,
            _(f'{queryset.count()} Monatslöhne wurden neu berechnet.'),
            messages.SUCCESS
        )
    recalculate_wages.short_description = _("Ausgewählte Löhne neu berechnen")

        #is_paid status auf true setzen  
    def change_is_paid_true(self, request, queryset):
        for wage in queryset:
            wage.is_paid = True
            wage.save()
        self.message_user(
            request,
                _(f'{queryset.count()} Monatslöhne wurden als bezahlt markiert.'),
            messages.SUCCESS
        )
    change_is_paid_true.short_description = _("Als bezahlt markieren")

    #is_paid status auf false setzen 
    def change_is_paid_false(self, request, queryset):
        for wage in queryset:
            wage.is_paid = False
            wage.save()
        self.message_user(
            request,
            _(f'{queryset.count()} Monatslöhne wurden als nicht bezahlt markiert.'),
            messages.SUCCESS
        )
    change_is_paid_false.short_description = _("Als nicht bezahlt markieren")
