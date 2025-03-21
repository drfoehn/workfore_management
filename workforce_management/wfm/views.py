from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView, View, TemplateView
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext_lazy as gettext  # Umbenennen zu gettext statt _
from .models import (
    WorkingHours, 
    Vacation, 
    VacationEntitlement, 
    SickLeave,
    ScheduleTemplate,
    TimeCompensation,
    TherapistBooking,
    TherapistScheduleTemplate,
    CustomUser,
    OvertimeAccount,
    ClosureDay,
    UserDocument,
    AveragingPeriod,
)
from .forms import UserDocumentForm, WorkingHoursForm, VacationRequestForm, TimeCompensationForm
from django.db.models import Sum, Count, F, Case, When, DecimalField, ExpressionWrapper, Value, CharField
from django.db.models.functions import ExtractMonth, ExtractYear, ExtractHour, ExtractMinute, Coalesce, Concat, ExtractWeekDay
from datetime import date, datetime, timedelta, time
import calendar
from django.db import models
from decimal import Decimal  
from django.http import JsonResponse, HttpResponse
import json
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.core.exceptions import PermissionDenied
import logging
from django.utils.decorators import method_decorator
from django.contrib.auth import logout
from dateutil.relativedelta import relativedelta
from django.contrib import messages
import traceback
from django.views.decorators.http import require_http_methods
from calendar import monthrange
from datetime import datetime, date as datetime_date  # Umbenennen des date imports
import re

logger = logging.getLogger(__name__)

class OwnerRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.role == 'OWNER'

@login_required
def dashboard(request):
    """Leitet zur Hauptseite weiter"""
    return redirect('wfm:dashboard')  # Statt 'owner-dashboard' verwenden wir jetzt 'dashboard'

class WorkingHoursListView(LoginRequiredMixin, ListView):
    template_name = 'wfm/working_hours_list.html'
    model = WorkingHours
    #TODO: Break-Duration mit Kaffehäferl anzeigen wenn >0 Minuten
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Hole das Datum aus den GET-Parametern oder nutze das aktuelle Datum
        selected_date = self.request.GET.get('date')
        if selected_date:
            current_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        else:
            current_date = date.today()

        # Berechne Montag und Freitag der aktuellen Woche
        monday = current_date - timedelta(days=current_date.weekday())
        friday = monday + timedelta(days=4)

        # Bestehender Code für Mitarbeiter-Filter bleibt unverändert
        employees = self.get_employees()

        # Hole die Arbeitsstunden für die aktuelle Woche
        working_hours = WorkingHours.objects.filter(
            date__range=[monday, friday],
            employee__in=employees
        ).select_related('employee')

        



        # Berechne die Wochenstunden pro Mitarbeiter
        weekly_hours = {}
        for employee in employees:
            total = working_hours.filter(employee=employee).aggregate(
                total=Coalesce(Sum('ist_hours'), Decimal('0'))
            )['total']
            weekly_hours[employee.id] = total

        # Erstelle eine Liste der Wochentage
        weekdays = []
        for i in range(5):  # Montag bis Freitag
            day = monday + timedelta(days=i)
            weekdays.append({
                'date': day,
                'name': day.strftime('%A'),
                'is_today': day == date.today(),
            })

        # Erstelle vorbereitete Daten für das Template
        employees_data = []
        for employee in employees:
            if employee.role not in ['ASSISTANT', 'CLEANING']:
                continue  # Überspringe andere Rollen
                
            employee_hours = []
            weekly_total = Decimal('0')
            
            # Übergebe das ausgewählte Datum an get_or_create_current
            averaging_period = AveragingPeriod.get_or_create_current(
                employee, 
                reference_date=current_date
            )
            
            if not averaging_period:
                continue  # Überspringe wenn kein Durchrechnungszeitraum erstellt werden konnte
            
            for day in weekdays:
                # Finde die Arbeitsstunden für diesen Tag
                wh = working_hours.filter(
                    employee=employee,
                    date=day['date']
                ).first()
                
                if wh:
                    weekly_total += wh.ist_hours or Decimal('0')
                
                employee_hours.append({
                    'working_hours': wh,
                    'date': day['date'],
                    'is_today': day['is_today']
                })
            
            employees_data.append({
                'employee': employee,
                'days': employee_hours,
                'weekly_total': weekly_total,
                'averaging_period': averaging_period,
                'target_hours_per_week': employee.working_hours_per_week
            })
            
        context.update({
            'weekdays': weekdays,
            'current_week': monday.isocalendar()[1],
            'current_year': monday.year,
            'prev_week': (monday - timedelta(days=7)).strftime('%Y-%m-%d'),
            'next_week': (monday + timedelta(days=7)).strftime('%Y-%m-%d'),
            'employees_data': employees_data
        })

        # 1. Hole Jahr und Monat aus URL oder nutze aktuelles Datum
        year = int(self.request.GET.get('year', date.today().year))
        month = int(self.request.GET.get('month', date.today().month))
        
        # 2. Erstelle Datum für Navigation
        current_date = date(year, month, 1)
        prev_month_date = current_date - timedelta(days=1)
        next_month_date = current_date + timedelta(days=32)

        # 3. Filter-Logik für Owner
        if self.request.user.role == 'OWNER':
            # Hole alle Mitarbeiter für Filter
            context['assistants'] = CustomUser.objects.filter(role='ASSISTANT')
            context['cleaners'] = CustomUser.objects.filter(role='CLEANING')
            
            # Hole ausgewählten Mitarbeiter und Rolle
            employee_id = self.request.GET.get('employee')
            role_filter = self.request.GET.get('role')
            
            if employee_id:
                context['selected_employee'] = CustomUser.objects.get(id=employee_id)
            context['selected_role'] = role_filter
            
            # Erstelle URLs für Rollenfilter
            current_params = self.request.GET.copy()
            current_params.pop('role', None)
            current_params.pop('employee', None)
            
            context['all_url'] = f"?{current_params.urlencode()}"
            current_params['role'] = 'ASSISTANT'
            context['assistant_url'] = f"?{current_params.urlencode()}"
            current_params['role'] = 'CLEANING'
            context['cleaning_url'] = f"?{current_params.urlencode()}"

        # 4. Hole die Mitarbeiter
        if self.request.user.role == 'OWNER':
            role = self.request.GET.get('role')
            employee_id = self.request.GET.get('employee')
            
            employees = CustomUser.objects.exclude(role='OWNER')
            if role:
                employees = employees.filter(role=role)
            if employee_id:
                employees = employees.filter(id=employee_id)
        else:
            employees = [self.request.user]

        # 5. Erstelle Liste aller Tage im Monat (nicht nur Werktage)
        workdays = []
        current_day = current_date
        while current_day.month == month:
            workdays.append(current_day)
            current_day += timedelta(days=1)

        # 6. Hole alle relevanten Daten für den Monat
        working_hours = WorkingHours.objects.filter(
            date__year=year,
            date__month=month,
            employee__in=employees
        ).select_related('employee')

        # Hole nur die aktuellsten Templates pro Tag
        schedules = []
        for employee in employees:
            for day in workdays:
                # Finde das neueste Template für diesen Wochentag, das vor oder am aktuellen Tag gültig ist
                template = ScheduleTemplate.objects.filter(
                    employee=employee,
                    weekday=day.weekday(),
                    valid_from__lte=day  # Wichtig: Prüfe valid_from gegen den aktuellen Tag
                ).order_by('-valid_from').first()
                if template:
                    schedules.append(template)

        vacations = Vacation.objects.filter(
            employee__in=employees,
            start_date__lte=current_date + timedelta(days=31),
            end_date__gte=current_date,
            status__in=['REQUESTED', 'APPROVED']
        ).select_related('employee')

        time_comps = TimeCompensation.objects.filter(
            employee__in=employees,
            date__year=year,
            date__month=month,
            status__in=['REQUESTED', 'APPROVED']
        ).select_related('employee')

        sick_leaves = SickLeave.objects.filter(
            employee__in=employees,
            start_date__lte=current_date + timedelta(days=31),
            end_date__gte=current_date
        ).select_related('employee')

        # Initialisiere die Summen vor der Schleife
        total_soll = 0
        total_ist = 0
        total_diff = 0

        # 7. Erstelle Lookup-Dictionaries
        working_hours_dict = {(wh.date, wh.employee_id): wh for wh in working_hours}
        schedule_dict = {}
        for schedule in schedules:
            key = (schedule.employee_id, schedule.weekday)
            if key not in schedule_dict:
                schedule_dict[key] = schedule

        # 8. Erstelle Tageseinträge
        days_data = []
        for day in workdays:
            # Prüfe ob Tag ein Schließtag ist
            closure = ClosureDay.objects.filter(
                models.Q(date__year=year, date__month=month) |
                models.Q(
                    is_recurring=True,
                    date__month=month,
                    date__day=day.day
                )
            ).filter(date=day).first()
            
            if closure:
                # Bei Schließtag: Nur ein Eintrag
                entry = {
                    'date': day,
                    'employee': None,
                    'working_hours': None,
                    'schedule': None,
                    'vacation': None,
                    'time_comp': None,
                    'sick_leave': None,
                    'closure': closure,
                    'soll_hours': 0,
                    'ist_hours': 0,
                    'difference': 0
                }
                days_data.append(entry)
            elif day.weekday() >= 5:  # Wochenende
                # Bei Wochenende: Nur ein Eintrag
                entry = {
                    'date': day,
                    'employee': None,
                    'working_hours': None,
                    'schedule': None,
                    'vacation': None,
                    'time_comp': None,
                    'sick_leave': None,
                    'closure': None,
                    'soll_hours': 0,
                    'ist_hours': 0,
                    'difference': 0,
                    'is_weekend': True
                }
                days_data.append(entry)
            else:
                # Normale Werktage: Filtere Mitarbeiter nach tatsächlichen Einträgen
                day_entries = []
                for employee in employees:
                    # Prüfe ob es Einträge für diesen Mitarbeiter an diesem Tag gibt
                    has_working_hours = working_hours_dict.get((day, employee.id))
                    has_schedule = schedule_dict.get((employee.id, day.weekday()))
                    has_vacation = next((v for v in vacations 
                        if v.employee_id == employee.id and 
                        v.start_date <= day <= v.end_date), None)
                    has_time_comp = next((tc for tc in time_comps 
                        if tc.employee_id == employee.id and 
                        tc.date == day), None)
                    has_sick_leave = next((sl for sl in sick_leaves 
                        if sl.employee_id == employee.id and 
                        sl.start_date <= day <= sl.end_date), None)

                    # Nur wenn es tatsächlich Einträge gibt oder ein Schedule existiert
                    if has_working_hours or has_schedule or has_vacation or has_time_comp or has_sick_leave:
                        entry = {
                            'date': day,
                            'employee': employee,
                            'working_hours': has_working_hours,
                            'schedule': has_schedule,
                            'vacation': has_vacation,
                            'time_comp': has_time_comp,
                            'sick_leave': has_sick_leave,
                            'is_weekend': False
                        }

                        # Berechne Stunden nur für normale Tage
                        if has_schedule:
                            entry['schedule'] = has_schedule
                            start = datetime.combine(date.min, has_schedule.start_time)
                            end = datetime.combine(date.min, has_schedule.end_time)
                            # Füge break_minutes zum entry hinzu
                            if has_schedule.break_duration:
                                entry['break_minutes'] = int(has_schedule.break_duration.total_seconds() / 60)
                            else:
                                entry['break_minutes'] = None
                            duration = end - start
                            if has_schedule.break_duration:
                                duration = duration - has_schedule.break_duration
                            entry['soll_hours'] = (duration).total_seconds() / 3600
                            total_soll += entry['soll_hours']

                        if has_working_hours:
                            start = datetime.combine(date.min, has_working_hours.start_time)
                            end = datetime.combine(date.min, has_working_hours.end_time)
                            entry['ist_hours'] = (end - start).total_seconds() / 3600
                            if has_working_hours.break_duration:
                                entry['ist_hours'] -= has_working_hours.break_duration.total_seconds() / 3600
                            total_ist += entry['ist_hours']

                        entry['difference'] = entry.get('ist_hours', 0) - entry.get('soll_hours', 0)
                        if not (has_vacation or has_time_comp or has_sick_leave):
                            total_diff += entry['difference']

                        day_entries.append(entry)

                # Wenn keine Einträge für diesen Tag existieren, füge einen leeren Tag hinzu
                if not day_entries:
                    entry = {
                        'date': day,
                        'employee': None,
                        'working_hours': None,
                        'schedule': None,
                        'vacation': None,
                        'time_comp': None,
                        'sick_leave': None,
                        'closure': None,
                        'soll_hours': 0,
                        'ist_hours': 0,
                        'difference': 0,
                        'is_weekend': False
                    }
                    days_data.append(entry)
                else:
                    days_data.extend(day_entries)

        # Entferne die doppelte Summenberechnung am Ende
        context.update({
            'dates': days_data,
            'year': year,
            'month': month,
            'prev_month': prev_month_date.month,
            'prev_year': prev_month_date.year,
            'next_month': next_month_date.month,
            'next_year': next_month_date.year,
            'month_name': current_date.strftime('%B %Y'),
            'show_request_buttons': self.request.user.role in ['ASSISTANT', 'CLEANING'],
            'current_year': year,
            'current_month': month,
            'total_soll': total_soll,
            'total_ist': total_ist,
            'total_diff': total_diff,
            'colors': {
                'primary': '#90BE6D',    # Pistachio
                'secondary': '#577590',   # Queen Blue
                'success': '#43AA8B',     # Zomp
                'warning': '#F9C74F',     # Maize Crayola
                'info': '#577590',        # Queen Blue
                'danger': '#F94144',      # Red Salsa
                'orange': '#F3722C',      # Orange Red
                'yellow': '#F8961E',      # Yellow Orange
            }
        })

        # Füge Durchrechnungszeitraum-Informationen hinzu
        if self.request.user.role in ['ASSISTANT', 'CLEANING']:
            current_period = AveragingPeriod.get_or_create_current(self.request.user)
            
            if current_period:
                context['current_period'] = {
                    'calendar_weeks': current_period.calendar_weeks,
                    'target_hours': current_period.target_hours,
                    'actual_hours': current_period.actual_hours,
                    'balance': current_period.balance
                }

        return context

    def get_queryset(self):
        # Nur Owner dürfen alle Mitarbeiter sehen, andere nur sich selbst
        if self.request.user.role == 'OWNER':
            return CustomUser.objects.all()
        return CustomUser.objects.filter(id=self.request.user.id)

    def get_employees(self):
        """Holt die relevanten Mitarbeiter basierend auf Filtern"""
        # Schließe Therapeuten und Owner aus
        queryset = CustomUser.objects.exclude(role__in=['OWNER', 'THERAPIST'])
        
        # Wenn ein Rollenfilter gesetzt ist
        role_filter = self.request.GET.get('role')
        if role_filter:
            queryset = queryset.filter(role=role_filter)
        
        # Wenn ein spezifischer Mitarbeiter ausgewählt ist
        employee_id = self.request.GET.get('employee')
        if employee_id:
            queryset = queryset.filter(id=employee_id)
        
        return queryset.order_by('first_name', 'last_name')

class WorkingHoursCreateOrUpdateView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        date_str = request.GET.get('date')
        if date_str:
            # Datum in Session speichern
            request.session['selected_date'] = date_str
        
        if not date_str and 'selected_date' in request.session:
            date_str = request.session['selected_date']
            
        if not date_str:
            return redirect('wfm:monthly-overview')
        
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
        working_hours = WorkingHours.objects.filter(
            employee=request.user,
            date=date
        ).first()
        
        if working_hours:
            return redirect('wfm:working-hours-edit', pk=working_hours.pk)
        else:
            return redirect('wfm:working-hours-add')

class WorkingHoursCreateView(LoginRequiredMixin, CreateView):
    model = WorkingHours
    form_class = WorkingHoursForm
    template_name = 'wfm/working_hours_form.html'
    success_url = reverse_lazy('wfm:monthly-overview')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user

        # Hole das Datum aus der URL
        date_str = self.request.GET.get('date')
        if date_str:
            try:
                date = datetime.strptime(date_str, '%Y-%m-%d').date()
                # Setze initial für beide Felder
                if 'initial' not in kwargs:
                    kwargs['initial'] = {}
                kwargs['initial']['date'] = date
                # Setze auch das Display-Datum
                kwargs['initial']['display_date'] = date.strftime('%d.%m.%Y')
            except ValueError:
                pass

        return kwargs

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Stelle sicher, dass die Soll-Stunden auch für neue Einträge berechnet werden
        if 'date' in form.initial:
            date = form.initial['date']
            schedule = ScheduleTemplate.objects.filter(
                employee=self.request.user,
                weekday=date.weekday()
            )
            scheduled_hours = sum(
                (t.end_time.hour + t.end_time.minute/60) - 
                (t.start_time.hour + t.start_time.minute/60)
                for t in schedule
            )
            form.fields['scheduled_hours'].initial = round(scheduled_hours, 2)
        return form

    def form_valid(self, form):
        form.instance.employee = self.request.user
        return super().form_valid(form)

class WorkingHoursUpdateView(LoginRequiredMixin, UpdateView):
    model = WorkingHours
    form_class = WorkingHoursForm
    template_name = 'wfm/working_hours_form.html'
    success_url = reverse_lazy('wfm:monthly-overview')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        # Bei Update kommt das Datum aus der Instanz
        return kwargs

    def get_queryset(self):
        return WorkingHours.objects.filter(employee=self.request.user)

    def form_valid(self, form):
        if 'selected_date' in self.request.session:
            del self.request.session['selected_date']
        return super().form_valid(form)

class OvertimeOverviewView(LoginRequiredMixin, View):
    def get(self, request):
        try:
            user = request.user
            today = timezone.now().date()

            print(f"\n=== DEBUG: OvertimeOverview ===")
            print(f"User: {user}")
            print(f"Today: {today}")

            # Hole den aktuellen Durchrechnungszeitraum
            current_period = AveragingPeriod.objects.filter(
                start_date__lte=today,
                end_date__gte=today
            ).first()

            # Wenn kein aktueller Zeitraum gefunden wurde, hole den letzten abgeschlossenen
            if not current_period:
                current_period = AveragingPeriod.objects.filter(
                    end_date__lt=today
                ).order_by('-end_date').first()

            print(f"Current period found: {current_period}")
            
            if not current_period:
                return JsonResponse({
                    'error': 'Kein Durchrechnungszeitraum gefunden'
                })

            print(f"Period start: {current_period.start_date}")
            print(f"Period end: {current_period.end_date}")
            print(f"Period balance: {current_period.balance}")

            # Hole oder erstelle den OvertimeAccount Eintrag
            overtime_account, created = OvertimeAccount.objects.get_or_create(
                employee=user,
                year=current_period.end_date.year,
                month=current_period.end_date.month,
                defaults={
                    'total_overtime': current_period.balance or Decimal('0'),
                    'hours_for_timecomp': Decimal('0'),
                    'is_finalized': False
                }
            )

            print(f"Overtime account: {overtime_account}")
            print(f"Was created: {created}")

            # Prüfe ob die 2-Wochen-Frist noch läuft
            transfer_deadline = current_period.end_date + timedelta(days=14)
            can_transfer = today <= transfer_deadline and not overtime_account.is_finalized

            print(f"Transfer deadline: {transfer_deadline}")
            print(f"Can transfer: {can_transfer}")

            response_data = {
                'overtime_hours': float(overtime_account.total_overtime or 0),
                'transferred_hours': float(overtime_account.hours_for_timecomp or 0),
                'payment_hours': float((overtime_account.total_overtime or 0) - (overtime_account.hours_for_timecomp or 0)),
                'is_finalized': overtime_account.is_finalized,
                'can_transfer': can_transfer,
                'transfer_deadline': transfer_deadline.strftime('%d.%m.%Y'),
                'period_end': current_period.end_date.strftime('%d.%m.%Y'),
                'period_start': current_period.start_date.strftime('%d.%m.%Y')
            }

            print(f"Response data: {response_data}")
            print("================================\n")

            return JsonResponse(response_data)

        except Exception as e:
            print(f"Error in OvertimeOverview: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'error': f'Ein Fehler ist aufgetreten: {str(e)}'
            })

    def post(self, request):
        try:
            data = json.loads(request.body)
            hours = Decimal(str(data.get('hours_for_timecomp', 0)))
            
            today = timezone.now().date()

            # Hole den aktuellen Durchrechnungszeitraum (gleiche Logik wie in get)
            current_period = AveragingPeriod.objects.filter(
                start_date__lte=today,
                end_date__gte=today
            ).first()

            # Wenn kein aktueller Zeitraum gefunden wurde, hole den letzten abgeschlossenen
            if not current_period:
                current_period = AveragingPeriod.objects.filter(
                    end_date__lt=today
                ).order_by('-end_date').first()

            if not current_period:
                return JsonResponse({
                    'error': 'Kein Durchrechnungszeitraum gefunden'
                })

            # Prüfe ob die 2-Wochen-Frist noch läuft
            transfer_deadline = current_period.end_date + timedelta(days=14)
            
            if today > transfer_deadline:
                return JsonResponse({
                    'error': 'Die Frist für die Übertragung ist abgelaufen'
                })

            overtime_account = OvertimeAccount.objects.filter(
                employee=request.user,
                year=current_period.end_date.year,
                month=current_period.end_date.month,
                is_finalized=False
            ).first()

            if not overtime_account:
                return JsonResponse({
                    'error': 'Keine offenen Überstunden gefunden'
                })

            if hours > overtime_account.total_overtime:
                return JsonResponse({
                    'error': 'Nicht genügend Überstunden verfügbar'
                })

            # Übertrage die Stunden
            overtime_account.hours_for_timecomp = hours
            overtime_account.save()

            return JsonResponse({
                'success': True,
                'overtime_hours': float(overtime_account.total_overtime),
                'transferred_hours': float(overtime_account.hours_for_timecomp),
                'payment_hours': float(overtime_account.total_overtime - overtime_account.hours_for_timecomp)
            })

        except Exception as e:
            print(f"Error in overtime transfer: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)})

class VacationListView(LoginRequiredMixin, ListView):
    model = Vacation
    template_name = 'wfm/vacation_list.html'
    context_object_name = 'vacations'

    def get_queryset(self):
        if self.request.user.role == 'OWNER':
            return Vacation.objects.all()
        return Vacation.objects.filter(employee=self.request.user)

class VacationRequestView(LoginRequiredMixin, CreateView):
    model = Vacation
    form_class = VacationRequestForm
    template_name = 'wfm/vacation_request_form.html'
    success_url = reverse_lazy('wfm:monthly-overview')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date', start_date)  # Falls end_date nicht gesetzt, verwende start_date
        
        if start_date:
            if 'initial' not in kwargs:
                kwargs['initial'] = {}
            kwargs['initial'].update({
                'start_date': datetime.strptime(start_date, '%Y-%m-%d').date(),
                'end_date': datetime.strptime(end_date, '%Y-%m-%d').date()
            })
        return kwargs

    def form_valid(self, form):
        form.instance.employee = self.request.user
        if 'selected_date' in self.request.session:
            del self.request.session['selected_date']
        return super().form_valid(form)

class VacationUpdateView(LoginRequiredMixin, UpdateView):
    model = Vacation
    form_class = VacationRequestForm
    template_name = 'wfm/vacation_request_form.html'
    success_url = reverse_lazy('wfm:monthly-overview')

    def get_queryset(self):
        return Vacation.objects.filter(employee=self.request.user)

def index(request):
    if request.user.is_authenticated:
        return redirect('wfm:dashboard')
    return render(request, 'wfm/index.html')

class MonthlyOverviewView(LoginRequiredMixin, ListView):
    template_name = 'wfm/monthly_overview.html'
    context_object_name = 'days'

    def dispatch(self, request, *args, **kwargs):
        if request.user.role == 'THERAPIST':
            return redirect('wfm:therapist-monthly-overview')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        year = int(self.request.GET.get('year', datetime.now().year))
        month = int(self.request.GET.get('month', datetime.now().month))
        
        num_days = calendar.monthrange(year, month)[1]
        days = []
        
        for day in range(1, num_days + 1):
            date = datetime(year, month, day).date()
            

            
            # Soll-Stunden
            schedule = ScheduleTemplate.objects.filter(
                employee=self.request.user,
                weekday=date.weekday()
            )
            
            # Ist-Stunden
            actual_hours = WorkingHours.objects.filter(
                employee=self.request.user,
                date=date
            )
            
            # Urlaub mit Objekt - jetzt auch REQUESTED Status
            vacation = Vacation.objects.filter(
                employee=self.request.user,
                start_date__lte=date,
                end_date__gte=date
            ).first()  # Entferne status='APPROVED' Filter
            
            # Zeitausgleich
            time_compensation = TimeCompensation.objects.filter(
                employee=self.request.user,
                date=date
            ).first()
            
            # Berechnung der Stunden
            scheduled_hours = sum(
                (t.end_time.hour + t.end_time.minute/60) - 
                (t.start_time.hour + t.start_time.minute/60)
                for t in schedule
            )
            
            actual_total = sum(
                (t.end_time.hour + t.end_time.minute/60) - 
                (t.start_time.hour + t.start_time.minute/60) - 
                (t.break_duration.seconds/3600)
                for t in actual_hours
            )
            
            # Berechne die Differenz - nur positive Werte (Mehrstunden)
            difference = Decimal('0')
            if actual_total > scheduled_hours:
                difference = actual_total - scheduled_hours
            
            days.append({
                'date': date,
                'scheduled': scheduled_hours,
                'actual': actual_total,
                'difference': round(difference, 2),
                'vacation': vacation,  # Enthält jetzt auch REQUESTED Urlaube
                'time_compensation': time_compensation,
                'schedule': schedule,
            })
        
        return days

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year = int(self.request.GET.get('year', datetime.now().year))
        month = int(self.request.GET.get('month', datetime.now().month))
        
        # Monatssummen
        total_scheduled = Decimal(str(sum(day['scheduled'] for day in context['days'])))
        total_actual = Decimal(str(sum(day['actual'] for day in context['days'])))
        
        # Gesamte Überstunden (alle Jahre)
        total_overtime = Decimal('0')
        working_hours = WorkingHours.objects.filter(employee=self.request.user)
        
        for wh in working_hours:
            # Tatsächliche Stunden
            actual_hours = Decimal(str(
                (wh.end_time.hour + wh.end_time.minute/60) - 
                (wh.start_time.hour + wh.start_time.minute/60) - 
                (wh.break_duration.seconds/3600)
            ))
            
            # Soll-Stunden für diesen Tag
            schedule = ScheduleTemplate.objects.filter(
                employee=self.request.user,
                weekday=wh.date.weekday()
            )
            scheduled_hours = Decimal(str(sum(
                (t.end_time.hour + t.end_time.minute/60) - 
                (t.start_time.hour + t.start_time.minute/60)
                for t in schedule
            )))
            
            # Überstunden
            total_overtime += actual_hours - scheduled_hours

        # Bereits genommener Zeitausgleich
        used_compensation = TimeCompensation.objects.filter(
            employee=self.request.user
        ).aggregate(
            total=Sum('hours')
        )['total'] or Decimal('0')

        # Verfügbarer Zeitausgleich
        available_overtime = total_overtime - used_compensation
        
        # Verfügbare Urlaubstage
        vacation_entitlement = VacationEntitlement.objects.filter(
            employee=self.request.user,
            year=year
        ).first()
        
        used_vacation_days = Vacation.objects.filter(
            employee=self.request.user,
            start_date__year=year,
            status='APPROVED'
        ).count()
        
        context.update({
            'year': year,
            'month': month,
            'month_name': calendar.month_name[month],
            'total_scheduled': round(total_scheduled, 2),
            'total_actual': round(total_actual, 2),
            'total_difference': round(total_actual - total_scheduled, 2),
            'vacation_days_total': vacation_entitlement.total_hours if vacation_entitlement else 0,
            'vacation_days_used': used_vacation_days,
            'vacation_days_remaining': (vacation_entitlement.total_hours - used_vacation_days) if vacation_entitlement else 0,
            'overtime_total': round(available_overtime, 2)
        })
        
        return context

class TimeCompensationCreateView(LoginRequiredMixin, CreateView):
    model = TimeCompensation
    form_class = TimeCompensationForm
    template_name = 'wfm/time_compensation_form.html'
    success_url = reverse_lazy('wfm:monthly-overview')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        date = self.request.GET.get('date')
        
        if date:
            if 'initial' not in kwargs:
                kwargs['initial'] = {}
            kwargs['initial']['date'] = datetime.strptime(date, '%Y-%m-%d').date()
        return kwargs

    def form_valid(self, form):
        form.instance.employee = self.request.user
        if 'selected_date' in self.request.session:
            del self.request.session['selected_date']
        return super().form_valid(form)

class TimeCompensationUpdateView(LoginRequiredMixin, UpdateView):
    model = TimeCompensation
    form_class = TimeCompensationForm
    template_name = 'wfm/time_compensation_form.html'
    success_url = reverse_lazy('wfm:monthly-overview')

    def get_queryset(self):
        return TimeCompensation.objects.filter(employee=self.request.user)

@login_required
def get_working_hours(request, date):
    try:
        # Hole die Soll-Zeiten aus dem Schedule
        schedule = ScheduleTemplate.objects.filter(
            employee=request.user,
            weekday=datetime.strptime(date, '%Y-%m-%d').date().weekday()
        )
        
        schedule_times = [{
            'start': t.start_time.strftime('%H:%M'),
            'end': t.end_time.strftime('%H:%M'),
            'hours': round((t.end_time.hour + t.end_time.minute/60) - 
                         (t.start_time.hour + t.start_time.minute/60), 2)
        } for t in schedule]
        
        total_scheduled = sum(t['hours'] for t in schedule_times)

        # Hole existierende Arbeitszeiten
        working_hours = WorkingHours.objects.filter(
            employee=request.user,
            date=date
        ).first()
        
        if working_hours:
            return JsonResponse({
                'exists': True,
                'start_time': working_hours.start_time.strftime('%H:%M'),
                'end_time': working_hours.end_time.strftime('%H:%M'),
                'break_duration': working_hours.break_duration.seconds // 60,
                'notes': working_hours.notes or '',
                'schedule': schedule_times,
                'total_scheduled': total_scheduled
            })
        return JsonResponse({
            'exists': False,
            'schedule': schedule_times,
            'total_scheduled': total_scheduled
        })
    except Exception as e:
        return JsonResponse({'exists': False, 'error': str(e)})

@login_required
@ensure_csrf_cookie  # Stellt sicher, dass der CSRF-Token verfügbar ist
def save_working_hours(request, date):
    """API-Endpoint zum Speichern von Arbeitsstunden"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
        
    try:
        data = json.loads(request.body)
        
        # Hole den Mitarbeiter aus der ID oder verwende den aktuellen User
        employee_id = data.get('employee_id') or request.user.id
        
        try:
            employee = CustomUser.objects.get(id=employee_id)
        except CustomUser.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Mitarbeiter nicht gefunden'
            }, status=404)
        
        # Prüfe Berechtigung (nur Owner oder der Mitarbeiter selbst)
        if not (request.user.role == 'OWNER' or request.user.id == employee.id):
            return JsonResponse({
                'success': False,
                'error': 'Keine Berechtigung'
            }, status=403)
        
        work_date = datetime.strptime(date, '%Y-%m-%d').date()
        start_time = datetime.strptime(data['start_time'], '%H:%M').time()
        end_time = datetime.strptime(data['end_time'], '%H:%M').time()
        break_duration = timedelta(minutes=int(data.get('break_duration', 0)))
        
        # Berechne die Ist-Stunden
        start_datetime = datetime.combine(work_date, start_time)
        end_datetime = datetime.combine(work_date, end_time)
        duration = end_datetime - start_datetime - break_duration
        ist_hours = Decimal(str(duration.total_seconds() / 3600))
        
        working_hours = WorkingHours.objects.create(
            employee=employee,  # Verwende den ausgewählten Mitarbeiter
            date=work_date,
            start_time=start_time,
            end_time=end_time,
            break_duration=break_duration,
            ist_hours=ist_hours,
            notes=data.get('notes', '')
        )
        
        return JsonResponse({
            'success': True,
            'id': working_hours.id
        })
        
    except Exception as e:
        logger.error(f"Error saving working hours: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@login_required
def api_vacation_request(request):
    """API-Endpunkt für Urlaubsanträge"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
        
    try:
        data = json.loads(request.body)
        start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        
        # Erstelle temporären Urlaubsantrag zur Stundenberechnung
        temp_vacation = Vacation(
            employee=request.user,
            start_date=start_date,
            end_date=end_date
        )
        
        # Berechne benötigte Stunden
        needed_hours = temp_vacation.calculate_vacation_hours()
        
        # Prüfe verfügbare Stunden
        entitlement = VacationEntitlement.objects.filter(
            employee=request.user,
            year=start_date.year
        ).first()
        
        if not entitlement:
            return JsonResponse({
                'error': gettext('Kein Urlaubsanspruch für dieses Jahr')
            }, status=400)
            
        # Berechne bereits verwendete Stunden
        used_hours = sum(
            v.calculate_vacation_hours() 
            for v in Vacation.objects.filter(
                employee=request.user,
                start_date__year=start_date.year,
                status='APPROVED'
            )
        )

        


        remaining_hours = entitlement.total_hours - used_hours

        if needed_hours > remaining_hours:
            return JsonResponse({
                'error': gettext('Nicht genügend Urlaubsstunden verfügbar')
            }, status=400)
            
        # Speichere den Urlaubsantrag
        vacation = Vacation.objects.create(
            employee=request.user,
            start_date=start_date,
            end_date=end_date,
            notes=data.get('notes', '')
        )
        
        return JsonResponse({
            'success': True,
            'needed_hours': float(needed_hours),
            'remaining_hours': float(remaining_hours - needed_hours)
        })
        
    except Exception as e:
        logger.error(f"Vacation request error: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def api_time_compensation_request(request):
    #TODO: Anträge werden doppelt gestellt
    """API-Endpunkt für Zeitausgleichsanträge"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Validiere die Daten
            if not data.get('date'):
                return JsonResponse({
                    'success': False,
                    'error': 'Bitte Datum angeben'
                })

            # Parse date
            date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            
            # Prüfe ob bereits ein Antrag für diesen Tag existiert
            existing_request = TimeCompensation.objects.filter(
                employee=request.user,
                date=date,
                status__in=['REQUESTED', 'APPROVED']  # Prüfe nur aktive Anträge
            ).first()
            
            if existing_request:
                return JsonResponse({
                    'success': False,
                    'error': f'Für den {date.strftime("%d.%m.%Y")} existiert bereits ein Zeitausgleichsantrag'
                })

            # Hole die geplanten Stunden für diesen Tag
            schedule = ScheduleTemplate.objects.filter(
                employee=request.user,
                weekday=date.weekday(),
                valid_from__lte=date
            ).order_by('-valid_from').first()

            if not schedule:
                return JsonResponse({
                    'success': False,
                    'error': 'Keine Arbeitszeit für diesen Tag geplant'
                })

            required_hours = schedule.hours

            # Erstelle den Zeitausgleichsantrag
            time_comp = TimeCompensation.objects.create(
                employee=request.user,
                date=date,
                hours=required_hours,  # Speichere die tatsächlich benötigten Stunden
                notes=data.get('notes', ''),
                status='REQUESTED'
            )
            
            return JsonResponse({'success': True})
            
        except Exception as e:
            logger.error(f"Error in time compensation request: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            })

    return JsonResponse({
        'success': False,
        'error': 'Invalid method'
    })

class TherapistMonthlyOverviewView(LoginRequiredMixin, TemplateView):
    template_name = 'wfm/therapist_monthly_overview.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Hole Jahr aus URL oder nutze aktuelles Jahr
        year = int(self.request.GET.get('year', date.today().year))
        
        # Hole alle Therapeuten
        if self.request.user.role == 'OWNER':
            therapists = CustomUser.objects.filter(role='THERAPIST')
            selected_therapist = None
            if therapist_id := self.request.GET.get('therapist'):
                selected_therapist = therapists.filter(id=therapist_id).first()
                therapists = [selected_therapist] if selected_therapist else therapists
        else:
            therapists = [self.request.user]
            selected_therapist = self.request.user

        # Erstelle Monatsstatistiken für jeden Therapeuten
        therapist_stats = []
        for therapist in therapists:
            months_data = []
            for month in range(1, 13):
                bookings = TherapistBooking.objects.filter(
                    therapist=therapist,
                    date__year=year,
                    date__month=month
                )
                
                # Berechne die Summen
                total_hours = bookings.aggregate(
                    total=Coalesce(Sum('hours', output_field=DecimalField()), 0, output_field=DecimalField())
                )['total']
                
                total_actual = bookings.aggregate(
                    total=Coalesce(Sum('actual_hours', output_field=DecimalField()), 0, output_field=DecimalField())
                )['total']
                
                total_difference = bookings.aggregate(
                    total=Coalesce(Sum('difference_hours', output_field=DecimalField()), 0, output_field=DecimalField())
                )['total']
                
                # Berechne ausstehende Zahlungen
                pending_payment = bookings.filter(
                    actual_hours__gt=F('hours'),
                    therapist_extra_hours_payment_status='PENDING'
                ).aggregate(
                    total=Coalesce(Sum('difference_hours', output_field=DecimalField()), 0, output_field=DecimalField())
                )['total'] * (therapist.room_rate or 0)  # Multipliziere mit dem Stundensatz

                months_data.append({
                    'month': month,
                    'month_name': date(year, month, 1).strftime('%B'),
                    'booking_count': bookings.count(),
                    'total_hours': total_hours,
                    'total_actual': total_actual,
                    'total_difference': total_difference,
                    'pending_payment': pending_payment
                })

            # Berechne Jahressummen
            year_totals = {
                'total_hours': sum(m['total_hours'] for m in months_data),
                'total_actual': sum(m['total_actual'] for m in months_data),
                'total_difference': sum(m['total_difference'] for m in months_data),
                'pending_payment': sum(m['pending_payment'] for m in months_data),
                'booking_count': sum(m['booking_count'] for m in months_data)
            }

            therapist_stats.append({
                'therapist': therapist,
                'months': months_data,
                'year_totals': year_totals
            })

        context.update({
            'year': year,
            'prev_year': year - 1,
            'next_year': year + 1,
            'therapist_stats': therapist_stats,
            'therapists': CustomUser.objects.filter(role='THERAPIST') if self.request.user.role == 'OWNER' else None,
            'selected_therapist': selected_therapist
        })
        
        return context

    def calculate_stats(self, queryset):
        # Berechne die Stunden direkt in der Abfrage
        queryset = queryset.annotate(
            booked_hours=ExpressionWrapper(
                (ExtractHour('end_time') + ExtractMinute('end_time') / 60.0) -
                (ExtractHour('start_time') + ExtractMinute('start_time') / 60.0),
                output_field=DecimalField()
            )
        )
        
        # Berechne die Summen
        totals = {
            'total_booked': queryset.aggregate(
                sum=Sum('booked_hours')
            )['sum'] or Decimal('0'),
            'total_actual': queryset.aggregate(
                sum=Sum('actual_hours')
            )['sum'] or Decimal('0'),
            'total_extra': queryset.aggregate(
                sum=Sum(Case(
                    When(
                        actual_hours__gt=F('booked_hours'),
                        then=F('actual_hours') - F('booked_hours')
                    ),
                    default=0,
                    output_field=DecimalField()
                ))
            )['sum'] or Decimal('0')
        }
        
        return totals

    def get_month_detail(self, year, month):
        """Zeigt die Detailansicht für einen bestimmten Monat"""
        context = {}
        
        # Berechne Start- und Enddatum des Monats
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        
        # Hole alle Buchungen für diesen Monat
        bookings = TherapistBooking.objects.filter(
            therapist=self.request.user,
            date__gte=start_date,
            date__lte=end_date
        ).order_by('date', 'start_time')
        
        # Gruppiere Buchungen nach Datum
        days = []
        current_date = start_date
        while current_date <= end_date:
            day_bookings = [b for b in bookings if b.date == current_date]
            
            # Berechne die Stunden für diesen Tag
            total_hours = sum(booking.hours for booking in day_bookings)
            used_hours = sum(booking.actual_hours or booking.hours for booking in day_bookings)
            difference = max(0, used_hours - total_hours)  # Nur positive Differenzen (Mehrstunden)
            
            days.append({
                'date': current_date,
                'weekday': current_date.strftime('%A'),
                'bookings': day_bookings,
                'total_hours': total_hours,
                'used_hours': used_hours,
                'difference': difference
            })
            
            current_date += timedelta(days=1)
        
        # Berechne die Monatssummen
        monthly_totals = {
            'total_hours': sum(day['total_hours'] for day in days),
            'used_hours': sum(day['used_hours'] for day in days),
            'total_difference': sum(day['difference'] for day in days)
        }
        
        # Berechne die zusätzlichen Kosten
        room_rate = self.request.user.room_rate or Decimal('0')
        monthly_totals['total_amount'] = monthly_totals['total_difference'] * room_rate
        
        context.update({
            'days': days,
            'month': month,
            'year': year,
            'month_name': date(year, month, 1).strftime('%B'),
            'totals': monthly_totals,
            'room_rate': room_rate
        })
        
        # Verwende das Detail-Template
        self.template_name = 'wfm/therapist_monthly_overview.html'
        return context

@login_required
@ensure_csrf_cookie
def api_therapist_booking(request):
    if request.method == 'POST':
        if request.user.role != 'THERAPIST':
            return JsonResponse({
                'success': False,
                'error': 'Nur für Therapeuten verfügbar'
            })

        try:
            data = json.loads(request.body.decode('utf-8'))
            
            # Validiere die Daten
            required_fields = ['date', 'start_time', 'end_time']
            if not all(field in data and data[field] for field in required_fields):
                return JsonResponse({
                    'success': False,
                    'error': 'Bitte alle Pflichtfelder ausfüllen'
                })

            # Konvertiere Strings in Datum/Zeit
            date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            start_time = datetime.strptime(data['start_time'], '%H:%M').time()
            end_time = datetime.strptime(data['end_time'], '%H:%M').time()

            # Prüfe ob die Zeit verfügbar ist
            existing_bookings = TherapistBooking.objects.filter(
                date=date,
                status='RESERVED'
            ).exclude(therapist=request.user)

            for booking in existing_bookings:
                if (start_time < booking.end_time and end_time > booking.start_time):
                    return JsonResponse({
                        'success': False,
                        'error': f'Zeitraum bereits belegt von {booking.start_time.strftime("%H:%M")} bis {booking.end_time.strftime("%H:%M")}'
                    })

            # Erstelle die Buchung
            booking = TherapistBooking.objects.create(
                therapist=request.user,
                date=date,
                start_time=start_time,
                end_time=end_time,
                notes=data.get('notes', ''),
                status='RESERVED'
            )
            
            return JsonResponse({'success': True})
            
        except Exception as e:
            print("Error:", str(e))
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({
        'success': False,
        'error': 'Ungültige Anfrage'
    }, status=400)

@login_required
@ensure_csrf_cookie
def api_therapist_booking_used(request):
    if request.method == 'GET':
        date = request.GET.get('date')
        if date:
            # Suche zuerst nach einer USED Buchung
            booking = TherapistBooking.objects.filter(
                therapist=request.user,
                date=date,
                status='USED'
            ).first()
            
            # Wenn keine USED Buchung gefunden wurde, suche nach RESERVED
            if not booking:
                booking = TherapistBooking.objects.filter(
                    therapist=request.user,
                    date=date,
                    status='RESERVED'
                ).first()
            
            if booking:
                return JsonResponse({
                    'booking_id': booking.id,
                    'actual_hours': float(booking.actual_hours) if booking.actual_hours is not None else None,
                    'notes': booking.notes,
                    'start_time': booking.start_time.strftime('%H:%M'),
                    'end_time': booking.end_time.strftime('%H:%M')
                })
            
        return JsonResponse({
            'error': 'Keine Buchung gefunden'
        }, status=404)
        
    elif request.method == 'POST':
        data = json.loads(request.body)
        booking_id = data.get('booking_id')
        
        try:
            booking = TherapistBooking.objects.get(
                id=booking_id,
                therapist=request.user
            )
            
            booking.actual_hours = data.get('actual_hours')
            booking.notes = data.get('notes')
            booking.status = 'USED'  # Status auf USED setzen
            booking.save()
            
            return JsonResponse({'success': True})
            
        except TherapistBooking.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Buchung nicht gefunden'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
    
    return JsonResponse({
        'success': False,
        'error': 'Ungültige Anfrage'
    }, status=400)

class CalendarView(LoginRequiredMixin, TemplateView):
    template_name = 'wfm/calendar_view.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year = int(self.request.GET.get('year', datetime.now().year))
        month = int(self.request.GET.get('month', datetime.now().month))
        
        context.update({
            'year': year,
            'month': month,
            'month_name': calendar.month_name[month],
            'hours': range(7, 21)  # Erzeugt Liste von 7 bis 20
        })
        
        return context

@login_required
def api_calendar_events(request):
    """Einfache API für Kalender-Events"""
    try:
        # Parse start/end dates from request
        start = request.GET.get('start')
        end = request.GET.get('end')
        
        # Convert to date objects
        start_date = datetime.strptime(start[:10], '%Y-%m-%d').date()
        end_date = datetime.strptime(end[:10], '%Y-%m-%d').date()
        
        # Get all working hours for the current user
        working_hours = WorkingHours.objects.filter(
            date__range=[start_date, end_date],
            employee=request.user
        ).select_related('employee')
        
        # Format events for FullCalendar
        events = []
        for wh in working_hours:
            events.append({
                'id': f'work_{wh.id}',
                'title': f'{wh.hours:.1f}h',
                'start': f'{wh.date}T{wh.start_time}',
                'end': f'{wh.date}T{wh.end_time}',
                'color': wh.employee.color
            })
        
        return JsonResponse(events, safe=False)
        
    except Exception as e:
        logger.error(f"Calendar API Error: {str(e)}", exc_info=True)
        return JsonResponse({
            'error': str(e),
            'events': []
        }, status=500)

def generate_color_for_user(user_id):
    """Generiert eine konsistente Farbe für einen Benutzer basierend auf der CI-Palette"""
    colors = [
        '#90BE6D',  # Pistachio (Hauptfarbe)
        '#43AA8B',  # Zomp
        '#577590',  # Queen Blue
        '#F9C74F',  # Maize Crayola
        '#F8961E',  # Yellow Orange
        '#F3722C',  # Orange Red
        '#F94144'   # Red Salsa
    ]
    return colors[user_id % len(colors)]

class DashboardView(LoginRequiredMixin, TemplateView):
    def get_template_names(self):
        # Wähle Template basierend auf Benutzerrolle
        templates = {
            'OWNER': 'wfm/dashboards/owner_dashboard.html',
            'ASSISTANT': 'wfm/dashboards/assistant_dashboard.html',
            'CLEANING': 'wfm/dashboards/cleaning_dashboard.html',
            'THERAPIST': 'wfm/dashboards/therapist_dashboard.html'
        }
        return [templates.get(self.request.user.role, 'wfm/dashboards/assistant_dashboard.html')]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        context['documents'] = UserDocument.objects.filter(user=user)

        if user.role == 'OWNER':
            # Statistiken für Owner Dashboard
            context['pending_vacations'] = Vacation.objects.filter(status='PENDING').count()
            context['pending_time_compensations'] = TimeCompensation.objects.filter(status='PENDING').count()
            context['pending_sick_leaves'] = SickLeave.objects.filter(status='PENDING').count()
            context['pending_therapist_bookings'] = TherapistBooking.objects.filter(therapist_extra_hours_payment_status='PENDING').count()

        if user.role == 'ASSISTANT' or user.role == 'CLEANING':
            # Kontext für Assistenz/Reinigung
            today = timezone.now().date()
            week_start = today - timedelta(days=today.weekday())
            context['working_hours'] = WorkingHours.objects.filter(
                employee=user,
                date__gte=week_start,
                date__lte=week_start + timedelta(days=6)
            )
            
            # Hole zukünftige Urlaube mit Berechnungen
            future_vacations = Vacation.objects.filter(
                employee=user,
                start_date__gte=today
            ).order_by('start_date')
            
            # Berechne die Stunden/Tage für jeden Urlaub
            for vacation in future_vacations:
                vacation.total_hours = vacation.calculate_vacation_hours()
                # vacation.total_days = vacation.calculate_vacation_days()
            
            context['future_vacations'] = future_vacations

        if user.role == 'THERAPIST':
            # Kontext für Therapeuten
            today = timezone.now().date()
            week_start = today - timedelta(days=today.weekday())
            context['bookings'] = TherapistBooking.objects.filter(
                therapist=user,
                date__gte=week_start,
                date__lte=week_start + timedelta(days=6)
            ).order_by('date', 'start_time')

        return context

@login_required
def delete_working_hours(request, id):
    if request.method == 'POST':
        try:
            working_hours = WorkingHours.objects.get(id=id)
            if request.user.role == 'OWNER' or working_hours.employee == request.user:
                working_hours.delete()
                return JsonResponse({'success': True})
            else:
                return JsonResponse({
                    'success': False,
                    'error': gettext('Keine Berechtigung')
                }, status=403)
        except WorkingHours.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': gettext('Arbeitszeit nicht gefunden')
            }, status=404)
    return JsonResponse({
        'success': False,
        'error': gettext('Ungültige Anfrage')
    }, status=400)

@login_required
def api_working_hours_detail(request, id=None):
    """API für Arbeitszeiten-Details"""
    if request.method == 'GET':
        if id:
            # Existierender Eintrag
            working_hours = get_object_or_404(WorkingHours, id=id)
            if request.user.role != 'OWNER' and working_hours.employee != request.user:
                raise PermissionDenied
                
            return JsonResponse({
                'id': working_hours.id,
                'date': working_hours.date.strftime('%Y-%m-%d'),
                'start_time': working_hours.start_time.strftime('%H:%M') if working_hours.start_time else '',
                'end_time': working_hours.end_time.strftime('%H:%M') if working_hours.end_time else '',
                'break_duration': working_hours.break_duration.seconds // 60 if working_hours.break_duration else 0,
                'notes': working_hours.notes or ''
            })
    
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def api_working_hours_update(request, id):
    """API für das Aktualisieren von Arbeitszeiten"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
        
    working_hours = get_object_or_404(WorkingHours, pk=id)
    if request.user.role != 'OWNER' and working_hours.employee != request.user:
        return JsonResponse({'error': 'Permission denied'}, status=403)
        
    try:
        data = json.loads(request.body)
        working_hours.start_time = datetime.strptime(data['start_time'], '%H:%M').time()
        working_hours.end_time = datetime.strptime(data['end_time'], '%H:%M').time()
        working_hours.break_duration = timedelta(minutes=int(data['break_duration']))
        working_hours.notes = data.get('notes', '')
        working_hours.save()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@login_required
def api_vacation_status(request):
    """API-Endpunkt für den aktuellen Urlaubsstatus"""
    try:
        current_year = timezone.now().year
        
        # Hole Urlaubsanspruch für aktuelles Jahr
        entitlement = VacationEntitlement.objects.filter(
            employee=request.user,
            year=current_year
        ).first()
        
        if not entitlement:
            return JsonResponse({
                'total_hours': 0,
                'approved_hours': 0,
                'pending_hours': 0,
                'remaining_hours': 0,
                'year': current_year
            })
        
        # Genehmigte Urlaubsstunden
        approved_vacations = Vacation.objects.filter(
            employee=request.user,
            start_date__year=current_year,
            status='APPROVED'
        )
        approved_hours = sum(
            vacation.calculate_vacation_hours() 
            for vacation in approved_vacations
        )
        
        # Beantragte (noch nicht genehmigte) Urlaubsstunden
        pending_vacations = Vacation.objects.filter(
            employee=request.user,
            start_date__year=current_year,
            status='REQUESTED'
        )
        pending_hours = sum(
            vacation.calculate_vacation_hours() 
            for vacation in pending_vacations
        )
        
        # Übertrag vom Vorjahr (falls vorhanden)
        last_year = current_year - 1
        last_year_entitlement = VacationEntitlement.objects.filter(
            employee=request.user,
            year=last_year
        ).first()
        
        last_year_remaining = Decimal('0')
        if last_year_entitlement:
            last_year_used = sum(
                vacation.calculate_vacation_hours()
                for vacation in Vacation.objects.filter(
                    employee=request.user,
                    start_date__year=last_year,
                    status='APPROVED'
                )
            )
            last_year_remaining = max(last_year_entitlement.total_hours - last_year_used, Decimal('0'))
        
        total_hours = entitlement.total_hours + last_year_remaining
        
        return JsonResponse({
            'total_hours': float(total_hours),
            'approved_hours': float(approved_hours),
            'pending_hours': float(pending_hours),
            'remaining_hours': float(total_hours - approved_hours),
            'year': current_year,
            'carried_over': float(last_year_remaining)
        })
        
    except Exception as e:
        logger.error(f"Vacation status error: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def api_therapist_booking_delete(request, pk):
    """API-Endpunkt zum Löschen einer Therapeuten-Buchung"""
    if request.method != 'POST' or request.user.role != 'OWNER':
        return JsonResponse({'error': 'Keine Berechtigung'}, status=403)
        
    try:
        booking = TherapistBooking.objects.get(pk=pk)
        booking.delete()
        return JsonResponse({'success': True})
        
    except TherapistBooking.DoesNotExist:
        return JsonResponse({
            'error': 'Buchung nicht gefunden'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)

class TherapistCalendarView(LoginRequiredMixin, TemplateView):
    template_name = 'wfm/therapist_calendar.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get current month/year
        month = self.request.GET.get('month')
        year = self.request.GET.get('year')
        if not month or not year:
            today = timezone.now()
            month = today.month
            year = today.year
        
        current_date = date(int(year), int(month), 1)
        
        # Hole alle Buchungen für den Monat
        bookings = TherapistBooking.objects.filter(
            date__year=int(year),
            date__month=int(month)
        ).select_related('therapist')

        # Wenn Therapeut eingeloggt, zeige nur eigene Details
        if self.request.user.role == 'THERAPIST':
            # Eigene Buchungen mit vollen Details
            own_bookings = [
                {
                    'id': str(booking.id),  # Nur die ID als String
                    'title': f"{booking.start_time.strftime('%H:%M')}-{booking.end_time.strftime('%H:%M')}",
                    'start': f"{booking.date}T{booking.start_time}",
                    'end': f"{booking.date}T{booking.end_time}",
                    'backgroundColor': booking.therapist.color,
                    'extendedProps': {
                        'therapist': {
                            'id': booking.therapist.id,
                            'name': booking.therapist.get_full_name()
                        },
                        'hours': booking.hours,
                        'actual_hours': booking.actual_hours,
                        'notes': booking.notes
                    }
                }
                for booking in bookings.filter(therapist=self.request.user)
            ]
            
            # Andere Buchungen nur als blockierte Zeit
            other_bookings = [
                {
                    'title': 'Belegt',
                    'start': f"{booking.date}T{booking.start_time}",
                    'end': f"{booking.date}T{booking.end_time}",
                    'backgroundColor': '#808080',  # Grau
                    'className': 'blocked-time'
                }
                for booking in bookings.exclude(therapist=self.request.user)
            ]
            
            calendar_events = own_bookings + other_bookings

        else:  # OWNER und ASSISTANT sieht alle Details
            calendar_events = [
                {
                    'id': str(booking.id),  # Nur die ID als String
                    'title': f"{booking.therapist.get_full_name()} ({booking.start_time.strftime('%H:%M')}-{booking.end_time.strftime('%H:%M')})",
                    'start': f"{booking.date}T{booking.start_time}",
                    'end': f"{booking.date}T{booking.end_time}",
                    'backgroundColor': booking.therapist.color,
                    'extendedProps': {
                        'therapist': {
                            'id': booking.therapist.id,
                            'name': booking.therapist.get_full_name()
                        },
                        'hours': booking.hours,
                        'actual_hours': booking.actual_hours,
                        'notes': booking.notes
                    }
                }
                for booking in bookings
            ]

        # Berechne Summen für den Monat
        total_actual_hours = Decimal('0.00')
        total_extra_hours = Decimal('0.00')
        total_booked_amount = Decimal('0.00')
        extra_costs = Decimal('0.00')

        for booking in bookings:
            if self.request.user.role == 'THERAPIST' and booking.therapist != self.request.user:
                continue  # Überspringe andere Therapeuten für die Summen
                
            if booking.actual_hours:
                total_actual_hours += booking.actual_hours

            if booking.hours and booking.therapist.room_rate:
                total_booked_amount += booking.hours * booking.therapist.room_rate
            
            if booking.difference_hours and booking.therapist.room_rate:
                total_extra_hours += booking.difference_hours
                extra_costs += booking.difference_hours * booking.therapist.room_rate

        context.update({
            'calendar_events': calendar_events,
            'current_date': current_date,
            'month_name': current_date.strftime('%B %Y'),
            'prev_month': (current_date - relativedelta(months=1)),
            'next_month': (current_date + relativedelta(months=1)),
            'totals': {
                'total_actual_hours': total_actual_hours,
                'total_extra_hours': total_extra_hours,
                'total_sum': total_booked_amount,
                'extra_costs': extra_costs
            }
        })

        # Füge Therapeuten-Filter hinzu für Owner
        if self.request.user.role == 'OWNER':
            context['therapists'] = CustomUser.objects.filter(role='THERAPIST').order_by('first_name', 'last_name')
            
        # Hole den ausgewählten Therapeuten
        therapist_id = self.request.GET.get('therapist')
        if therapist_id:
            context['selected_therapist'] = CustomUser.objects.filter(id=therapist_id).first()

        return context

@ensure_csrf_cookie
def api_therapist_calendar_events(request):
    """API-Endpunkt für Kalender-Events"""
    print("\n=== Debug api_therapist_calendar_events ===")
    
    start = request.GET.get('start')
    end = request.GET.get('end')
    therapist_id = request.GET.get('therapist')  # Für Owner-Filter
    print(f"Requested date range: {start} to {end}")
    print(f"User role: {request.user.role}")
    print(f"Selected therapist: {therapist_id}")

    # Basis-Query für alle Buchungen im Zeitraum
    bookings = TherapistBooking.objects.filter(
        date__range=[start.split('T')[0], end.split('T')[0]]
    ).select_related('therapist')

    # Filter für Owner wenn Therapeut ausgewählt
    if request.user.role == 'OWNER' and therapist_id:
        bookings = bookings.filter(therapist_id=therapist_id)

    print(f"Total bookings found: {bookings.count()}")

    calendar_events = []
    
    if request.user.role == 'THERAPIST':
        # Eigene Buchungen mit vollen Details
        own_bookings = bookings.filter(therapist=request.user)
        print(f"Own bookings: {own_bookings.count()}")
        
        calendar_events.extend([
            {
                'id': str(booking.id),
                'title': f"{booking.start_time.strftime('%H:%M')}-{booking.end_time.strftime('%H:%M')}",
                'start': f"{booking.date}T{booking.start_time}",
                'end': f"{booking.date}T{booking.end_time}",
                'backgroundColor': booking.therapist.color,
                'borderColor': booking.therapist.color,
                'extendedProps': {
                    'therapist': {
                        'id': booking.therapist.id,
                        'name': booking.therapist.get_full_name()
                    },
                    'hours': booking.hours,
                    'actual_hours': booking.actual_hours,
                    'notes': booking.notes
                }
            }
            for booking in own_bookings
        ])
        
        # Andere Buchungen als blockierte Zeiten
        other_bookings = bookings.exclude(therapist=request.user)
        print(f"Other bookings: {other_bookings.count()}")
        
        calendar_events.extend([
            {
                'title': 'Belegt',
                'start': f"{booking.date}T{booking.start_time}",
                'end': f"{booking.date}T{booking.end_time}",
                'backgroundColor': '#808080',
                'borderColor': '#808080',
                'className': 'blocked-time'
            }
            for booking in other_bookings
        ])

    else:  # OWNER oder ASSISTANT
        # Alle Buchungen mit vollen Details
        print(f"All bookings for {request.user.role}: {bookings.count()}")
        calendar_events = [
            {
                'id': str(booking.id),
                'title': f"{booking.therapist.get_full_name()} ({booking.start_time.strftime('%H:%M')}-{booking.end_time.strftime('%H:%M')})",
                'start': f"{booking.date}T{booking.start_time}",
                'end': f"{booking.date}T{booking.end_time}",
                'backgroundColor': booking.therapist.color,
                'borderColor': booking.therapist.color,
                'extendedProps': {
                    'therapist': {
                        'id': booking.therapist.id,
                        'name': booking.therapist.get_full_name()
                    },
                    'hours': booking.hours,
                    'actual_hours': booking.actual_hours,
                    'notes': booking.notes
                }
            }
            for booking in bookings
        ]

    print(f"Total events returned: {len(calendar_events)}")
    return JsonResponse(calendar_events, safe=False)

@method_decorator(login_required, name='dispatch')
class AssistantCalendarEventsView(View):
    def get(self, request):
        # Parse start und end dates aus den Request-Parametern
        start_date = parse_datetime(request.GET.get('start'))
        end_date = parse_datetime(request.GET.get('end'))
        show_absences_only = request.GET.get('absences') == '1'
        
        # Hole employee und role Filter
        employee_id = request.GET.get('employee')
        role = request.GET.get('role')
        
        # Basis-Filter für Mitarbeiter
        employee_filter = {}
        if employee_id:
            employee_filter['employee_id'] = employee_id
        if role:
            employee_filter['employee__role'] = role

        events = []
        
        # Lade IMMER die Abwesenheiten
        # Urlaub
        vacations = Vacation.objects.filter(
            start_date__lte=end_date.date(),
            end_date__gte=start_date.date(),
            status='APPROVED',
            **employee_filter
        ).select_related('employee')
        
        events.extend([{
            'title': f"{v.employee.get_full_name()} - Urlaub",
            'start': v.start_date.isoformat(),
            'end': (v.end_date + timedelta(days=1)).isoformat(),
            'backgroundColor': v.employee.color,
            'className': 'vacation-event',
            # 'type': 'vacation',
            'allDay': True
        } for v in vacations])
        
        # Zeitausgleich
        time_comps = TimeCompensation.objects.filter(
            date__lte=end_date.date(),
            date__gte=start_date.date(),
            status='APPROVED',
            **employee_filter
        ).select_related('employee')
        
        events.extend([{
            'title': f"{tc.employee.get_full_name()} - Zeitausgleich",
            'start': tc.date.isoformat(),
            'end': (tc.date + timedelta(days=1)).isoformat(),
            'backgroundColor': tc.employee.color,
            'className': 'time-comp-event',
            'type': 'time_comp',
            'allDay': True
        } for tc in time_comps])
        
        # Krankenstände
        sick_leaves = SickLeave.objects.filter(
            start_date__lte=end_date.date(),
            end_date__gte=start_date.date(),
            **employee_filter
        ).select_related('employee')
        
        events.extend([{
            'title': f"{sl.employee.get_full_name()} - Krankenstand",
            'start': sl.start_date.isoformat(),
            'end': (sl.end_date + timedelta(days=1)).isoformat(),
            'backgroundColor': sl.employee.color,
            'className': 'sick-leave-event',
            'type': 'sick_leave',
            'allDay': True
        } for sl in sick_leaves])

        # Lade Arbeitsstunden nur wenn nicht nur Abwesenheiten angezeigt werden sollen
        if not show_absences_only:
            working_hours = WorkingHours.objects.filter(
                date__range=(start_date.date(), end_date.date()),
                **employee_filter
            ).select_related('employee')
            
            events.extend([{
                'id': f'work_{wh.id}',
                'title': f"{wh.employee.get_full_name()}\n{wh.notes if wh.notes else ''}",
                'start': f"{wh.date}T{wh.start_time}" if wh.start_time else wh.date.isoformat(),
                'end': f"{wh.date}T{wh.end_time}" if wh.end_time else wh.date.isoformat(),
                'backgroundColor': wh.employee.color,
                'className': 'working-hours-event',
                'type': 'working_hours',
                'allDay': not (wh.start_time and wh.end_time),
                'extendedProps': {
                    'notes': wh.notes,
                    'employee_id': wh.employee.id,
                    'ist_hours': float(wh.ist_hours) if wh.ist_hours else 0,
                    'type': 'working_hours'
                }
            } for wh in working_hours])

        return JsonResponse(events, safe=False)



class TimeCompensationListView(LoginRequiredMixin, ListView):
    model = TimeCompensation
    template_name = 'wfm/time_compensation_list.html'
    context_object_name = 'time_compensations'

    def get_queryset(self):
        queryset = TimeCompensation.objects.select_related('employee')
        
        if self.request.user.role != 'OWNER':
            queryset = queryset.filter(employee=self.request.user)
            
        return queryset.order_by('-date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.role == 'OWNER':
            context['employees'] = CustomUser.objects.exclude(role='OWNER')
        return context

@login_required
def logout_view(request):
    logout(request)
    return redirect('wfm:login')

@login_required
@ensure_csrf_cookie
def api_sick_leave(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
            
            # Validiere die Daten
            required_fields = ['start_date', 'end_date']
            if not all(field in data and data[field] for field in required_fields):
                return JsonResponse({
                    'success': False,
                    'error': gettext('Bitte Start- und Enddatum angeben')
                })

            # Parse dates
            start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            
            # Erstelle den Krankenstand
            sick_leave = SickLeave.objects.create(
                employee=request.user,
                start_date=start_date,
                end_date=end_date,
                notes=data.get('notes', '')
            )
            
            return JsonResponse({'success': True})
            
        except Exception as e:
            logger.error(f"Sick leave error: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({
        'success': False,
        'error': gettext('Ungültige Anfrage')
    })

class AssistantCalendarView(LoginRequiredMixin, TemplateView):
    template_name = 'wfm/assistant_calendar.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Bestehender Code...
        role = self.request.GET.get('role')
        employee_id = self.request.GET.get('employee')
        
        # Abwesenheiten Filter Status
        context['show_absences_only'] = self.request.GET.get('absences') == '1'
        
        # Mitarbeiter Filter
        if employee_id:
            try:
                context['selected_employee'] = CustomUser.objects.get(id=employee_id)
            except CustomUser.DoesNotExist:
                pass
        
        # Rollen Filter
        context['selected_role'] = role
        if role == 'ASSISTANT':
            context['assistants'] = CustomUser.objects.filter(role='ASSISTANT')
        elif role == 'CLEANING':
            context['cleaners'] = CustomUser.objects.filter(role='CLEANING')
        else:
            context['assistants'] = CustomUser.objects.filter(role='ASSISTANT')
            context['cleaners'] = CustomUser.objects.filter(role='CLEANING')
        
        
        return context

    def get_events(self, request):
        # Parse start und end dates aus den Request-Parametern
        start_date = parse_datetime(request.GET.get('start'))
        end_date = parse_datetime(request.GET.get('end'))
        show_absences_only = request.GET.get('absences') == '1'
        
        # Hole employee und role Filter
        employee_id = request.GET.get('employee')
        role = request.GET.get('role')
        
        # Basis-Filter für Mitarbeiter
        employee_filter = {}
        if employee_id:
            employee_filter['employee_id'] = employee_id
        if role:
            employee_filter['employee__role'] = role

        if show_absences_only:
            # Nur Abwesenheiten zurückgeben
            events = []
            
            # Urlaub
            vacations = Vacation.objects.filter(
                start_date__lte=end_date.date(),
                end_date__gte=start_date.date(),
                status='APPROVED',
                **employee_filter
            ).select_related('employee')
            
            events.extend([{
                'title': f"{v.employee.get_full_name()} - Urlaub",
                'start': v.start_date.isoformat(),
                'end': (v.end_date + timedelta(days=1)).isoformat(),
                'className': 'vacation-event',
                'type': 'vacation',
                'allDay': True
            } for v in vacations])
            
            # Zeitausgleich
            time_comps = TimeCompensation.objects.filter(
                date__lte=end_date.date(),
                date__gte=start_date.date(),
                status='APPROVED',
                **employee_filter
            ).select_related('employee')
            
            events.extend([{
                'title': f"{tc.employee.get_full_name()} - Zeitausgleich",
                'start': tc.date.isoformat(),
                'end': (tc.date + timedelta(days=1)).isoformat(),
                'className': 'time-comp-event',
                'type': 'time_comp',
                'allDay': True
            } for tc in time_comps])
            
            # Krankenstand - Korrigierte Filterung
            sick_leaves = SickLeave.objects.filter(
                start_date__lte=end_date.date(),
                end_date__gte=start_date.date(),
                **employee_filter
            ).select_related('employee')
            
            events.extend([{
                'title': f"{sl.employee.get_full_name()} - Krankenstand",
                'start': sl.start_date.isoformat(),
                'end': (sl.end_date + timedelta(days=1)).isoformat(),
                'className': 'sick-leave-event',
                'type': 'sick_leave',
                'allDay': True
            } for sl in sick_leaves])
            
            return JsonResponse(events, safe=False)
        else:
            # Normaler Event-Code
            return self.get_regular_events(request, start_date, end_date)

class TherapistBookingListView(LoginRequiredMixin, ListView):
    model = TherapistBooking
    template_name = 'wfm/therapist_booking_list.html'
    context_object_name = 'bookings'

    def get_queryset(self):
        # Filter by month/year
        month = self.request.GET.get('month')
        year = self.request.GET.get('year')
        if not month or not year:
            today = timezone.now()
            month = today.month
            year = today.year
        
        # Basis-Query für den ausgewählten Monat
        queryset = super().get_queryset().filter(
            date__year=int(year),
            date__month=int(month)
        )

        # Filter by therapist
        therapist_id = self.request.GET.get('therapist')
        if therapist_id:
            queryset = queryset.filter(therapist_id=therapist_id)
            self.selected_therapist = CustomUser.objects.get(id=therapist_id)
        elif self.request.user.role == 'THERAPIST':
            queryset = queryset.filter(therapist=self.request.user)
            self.selected_therapist = self.request.user
        else:
            self.selected_therapist = None

        return queryset.order_by('date', 'start_time')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get current month/year
        month = self.request.GET.get('month')
        year = self.request.GET.get('year')
        if not month or not year:
            today = timezone.now()
            month = today.month
            year = today.year
        
        current_date = date(int(year), int(month), 1)
        context.update({
            'current_date': current_date,
            'month_name': current_date.strftime('%B %Y'),
            'prev_month': (current_date - relativedelta(months=1)),
            'next_month': (current_date + relativedelta(months=1))
        })

        # Berechne Summen für die Buchungen
        bookings = context['bookings']
        total_actual_hours = Decimal('0.00')  # Verwendete Stunden gesamt
        total_extra_hours = Decimal('0.00')   # Summe der Mehrstunden
        total_booked_amount = Decimal('0.00') # Gebuchte Stunden * room_rate
        extra_costs = Decimal('0.00')         # Mehrstunden * room_rate
        total_sum = Decimal('0.00')           # Gesamtkosten
        therapist_extra_hours_payment_status = 'PENDING'    # Default Status bleibt PENDING

        for booking in bookings:
            # Verwendete Stunden
            if booking.actual_hours:
                total_actual_hours += booking.actual_hours

            # Gebuchte Stunden * room_rate
            if booking.hours and booking.therapist.room_rate:
                total_booked_amount += booking.hours * booking.therapist.room_rate
            
            # Mehrstunden und deren Kosten
            if booking.difference_hours and booking.therapist.room_rate:
                total_extra_hours += booking.difference_hours
                extra_costs += booking.difference_hours * booking.therapist.room_rate
                # Wenn alle Buchungen mit Mehrstunden PAID sind, setze Status auf PAID
                if booking.therapist_extra_hours_payment_status == 'PAID':
                    therapist_extra_hours_payment_status = 'PAID'

            # Gesamtkosten
            total_sum = total_booked_amount + extra_costs

        context['totals'] = {
            'total_actual_hours': total_actual_hours,
            'total_extra_hours': total_extra_hours,
            'total_booked_amount': total_booked_amount,
            'extra_costs': extra_costs,
            'total_sum': total_sum,
            'payment_status': therapist_extra_hours_payment_status  # Schlüssel geändert
        }

        # Füge Therapeuten für Filter hinzu (nur für Owner)
        if self.request.user.role == 'OWNER':
            context['therapists'] = CustomUser.objects.filter(role='THERAPIST')
            context['selected_therapist'] = getattr(self, 'selected_therapist', None)

        return context

@login_required
def api_therapist_booking_update(request):
    """API-Endpunkt zum Aktualisieren einer Therapeuten-Buchung"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    try:
        data = json.loads(request.body)
        booking = TherapistBooking.objects.get(id=data['id'])
        
        # Prüfe Berechtigungen
        if request.user.role == 'OWNER':
            # Owner darf alles ändern
            booking.therapist_id = data.get('therapist_id', booking.therapist_id)
            booking.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            booking.start_time = datetime.strptime(data['start_time'], '%H:%M').time()
            booking.end_time = datetime.strptime(data['end_time'], '%H:%M').time()
            if 'actual_hours' in data and data['actual_hours']:
                booking.actual_hours = Decimal(data['actual_hours'])
            if 'notes' in data:
                booking.notes = data['notes']
            # Füge extra_hours_payment_status Update für OWNER hinzu
            if 'therapist_extra_hours_payment_status' in data and booking.difference_hours:
                booking.therapist_extra_hours_payment_status = data['therapist_extra_hours_payment_status']
                if data['therapist_extra_hours_payment_status'] == 'PAID':
                    booking.therapist_extra_hours_payment_date = timezone.now().date()
        elif request.user == booking.therapist:
            # Therapeut darf nur actual_hours und notes ändern
            if 'actual_hours' in data and data['actual_hours']:
                booking.actual_hours = Decimal(data['actual_hours'])
            if 'notes' in data:
                booking.notes = data['notes']
        else:
            return JsonResponse({'error': 'Permission denied'}, status=403)
            
        booking.save()  # Dies berechnet auch die difference_hours automatisch
        
        return JsonResponse({
            'success': True,
            'booking': {
                'id': booking.id,
                'therapist': {
                    'id': booking.therapist.id,
                    'name': booking.therapist.get_full_name() or booking.therapist.username
                },
                'date': booking.date.strftime('%Y-%m-%d'),
                'start_time': booking.start_time.strftime('%H:%M'),
                'end_time': booking.end_time.strftime('%H:%M'),
                'hours': float(booking.hours) if booking.hours else None,
                'actual_hours': float(booking.actual_hours) if booking.actual_hours else None,
                'difference_hours': float(booking.difference_hours) if booking.difference_hours else None,
                'notes': booking.notes,
                'therapist_extra_hours_payment_status': booking.therapist_extra_hours_payment_status
            }
        })
        
    except TherapistBooking.DoesNotExist:
        return JsonResponse({
            'error': 'Buchung nicht gefunden'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)

class AbsenceListView(LoginRequiredMixin, ListView):
    template_name = 'wfm/absence_list.html'
    model = SickLeave
    context_object_name = 'sick_leaves'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.now().date()

        # Urlaubsübersicht
        entitlement = VacationEntitlement.objects.filter(
            employee=user,
            year=today.year
        ).first()

        if entitlement:
            # Genehmigte Urlaubsstunden
            approved_vacations = Vacation.objects.filter(
                employee=user,
                start_date__year=today.year,
                status='APPROVED'
            )
            approved_hours = sum(
                vacation.calculate_vacation_hours() 
                for vacation in approved_vacations
            )

            # Beantragte Urlaubsstunden
            pending_vacations = Vacation.objects.filter(
                employee=user,
                start_date__year=today.year,
                status='REQUESTED'
            )
            pending_hours = sum(
                vacation.calculate_vacation_hours() 
                for vacation in pending_vacations
            )

            # Übertrag aus Vorjahr
            last_year = today.year - 1
            last_year_remaining = Decimal('0')
            if last_year_entitlement := VacationEntitlement.objects.filter(
                employee=user,
                year=last_year
            ).first():
                last_year_used = sum(
                    vacation.calculate_vacation_hours()
                    for vacation in Vacation.objects.filter(
                        employee=user,
                        start_date__year=last_year,
                        status='APPROVED'
                    )
                )
                last_year_remaining = max(
                    last_year_entitlement.total_hours - last_year_used,
                    Decimal('0')
                )

            # Gesamtverfügbare Stunden
            total_available = entitlement.total_hours + last_year_remaining
            remaining_hours = total_available - approved_hours - pending_hours
            remaining_minus_pending = remaining_hours - pending_hours
            


            context.update({
                'vacation_entitlement': entitlement,
                'vacation_total_available': total_available,
                'vacation_approved_hours': approved_hours,
                'vacation_pending_hours': pending_hours,
                'vacation_remaining_hours': remaining_hours,
                'vacation_last_year_remaining': last_year_remaining,
                'vacation_remaining_minus_pending': remaining_minus_pending
            })

        # Hole alle Urlaube
        vacations = Vacation.objects.filter(
            employee=user
        ).order_by('-start_date')
        
        context['vacations'] = vacations
        
        # Zeitausgleichsübersicht
        print("\n=== DEBUG: TimeCompensation Info ===")
        print(f"Current user: {user}, Today: {today}")

        # Hole das Überstundenkonto für diesen Monat
        overtime_account = OvertimeAccount.objects.filter(
            employee=user,
            year=today.year,
            month=today.month
        ).first()

        print(f"\nOvertime Account found: {overtime_account}")
        
        if overtime_account:
            total_hours = overtime_account.hours_for_timecomp
            print(f"Total overtime hours: {total_hours}")
        else:
            total_hours = 0
            print("No overtime account found, setting total_hours to 0")

        # Hole genehmigte und beantragte Zeitausgleiche
        approved_time_comps = TimeCompensation.objects.filter(  
            employee=user,
            status='APPROVED'
        )
        pending_time_comps = TimeCompensation.objects.filter(
            employee=user,
            status='REQUESTED'
        )

        # Berechne die Stunden
        used_hours = sum(tc.hours for tc in approved_time_comps)
        pending_hours = sum(tc.hours for tc in pending_time_comps)
        remaining_hours = total_hours - pending_hours - used_hours      

        print(f"\nApproved time comps count: {approved_time_comps.count()}")
        print(f"Used hours: {used_hours}")
        print(f"Pending time comps count: {pending_time_comps.count()}")
        print(f"Pending hours: {pending_hours}")
        print(f"Remaining hours: {remaining_hours}")

        context.update({
            'timecomp_total_hours': total_hours,
            'timecomp_used_hours': used_hours,
            'timecomp_pending_hours': pending_hours,
            'timecomp_remaining_hours': remaining_hours
        })
        
        
        
        

        # Hole alle Zeitausgleiche
        time_comps = TimeCompensation.objects.filter(
            employee=user
        ).order_by('-date')
        context['time_comps'] = time_comps

        print("\n=== Final TimeComp context values ===")
        print(f"Total hours: {context.get('timecomp_total_hours')}")
        print(f"Used hours: {context.get('timecomp_used_hours')}")
        print(f"Pending hours: {context.get('timecomp_pending_hours')}")
        print(f"Remaining hours: {context.get('timecomp_remaining_hours')}")
        print("================================\n")
        
        return context

@login_required
def api_delete_absence(request, type, pk):
    """API zum Löschen von Abwesenheiten"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
        
    try:
        # Wähle das richtige Model basierend auf dem Typ
        if type == 'vacation':
            model = Vacation
        elif type == 'time_comp':
            model = TimeCompensation
        else:
            return JsonResponse({'error': 'Invalid type'}, status=400)
            
        # Hole den Eintrag
        absence = model.objects.get(pk=pk, employee=request.user)
        
        # Prüfe ob der Eintrag in der Zukunft liegt
        if type == 'vacation':
            if absence.start_date < timezone.now().date():
                return JsonResponse({'error': 'Vergangene Einträge können nicht gelöscht werden'}, status=400)
        else:
            if absence.date < timezone.now().date():
                return JsonResponse({'error': 'Vergangene Einträge können nicht gelöscht werden'}, status=400)
                
        # Prüfe den Status
        if absence.status != 'REQUESTED':
            return JsonResponse({'error': 'Nur offene Anträge können storniert werden'}, status=400)
            
        # Lösche den Eintrag
        absence.delete()
        return JsonResponse({'success': True})
        
    except model.DoesNotExist:
        return JsonResponse({'error': 'Eintrag nicht gefunden'}, status=404)
    except Exception as e:
        logger.error(f"Delete absence error: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def api_time_compensation_status(request):
    """API-Endpunkt für den aktuellen Zeitausgleichsstatus"""
    try:
        today = timezone.now().date()
        
        # Hole den relevanten Monat
        if today.day <= 7:
            target_date = today - relativedelta(months=1)
        else:
            target_date = today
            
        # Hole das Überstundenkonto für diesen Monat
        overtime_account = OvertimeAccount.objects.filter(
            employee=request.user,
            year=target_date.year,
            month=target_date.month
        ).first()
        
        if overtime_account:
            total_hours = overtime_account.hours_for_timecomp
        else:
            total_hours = 0
        
        # Hole genehmigte und beantragte Zeitausgleiche
        approved_time_comps = TimeCompensation.objects.filter(
            employee=request.user,
            status='APPROVED'
        )
        
        pending_time_comps = TimeCompensation.objects.filter(
            employee=request.user,
            status='REQUESTED'
        )
        
        # Berechne die Stunden
        used_hours = sum(tc.hours for tc in approved_time_comps)
        pending_hours = sum(tc.hours for tc in pending_time_comps)
        remaining_hours = total_hours - used_hours - pending_hours
        
        return JsonResponse({
            'total_hours': float(total_hours),
            'used_hours': float(used_hours),
            'pending_hours': float(pending_hours),
            'remaining_hours': float(remaining_hours)
        })
        
    except Exception as e:
        logger.error(f"Time compensation status error: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

def calculate_overtime_hours(user, year, month=None):
    """Berechnet die Überstunden für einen Benutzer in einem Jahr/Monat"""
    # Basis-Query
    query = WorkingHours.objects.filter(
        employee=user,
        date__year=year
    )
    
    # Wenn ein Monat angegeben ist, filtere zusätzlich danach
    if month is not None:
        query = query.filter(date__month=month)
    
    total_overtime = 0
    for wh in query:
        # Berechne Ist-Stunden
        if wh.start_time and wh.end_time:
            start = datetime.combine(wh.date, wh.start_time)
            end = datetime.combine(wh.date, wh.end_time)
            duration = end - start
            ist_hours = duration.total_seconds() / 3600
            
            # Ziehe Pause ab
            if wh.break_duration:
                ist_hours -= wh.break_duration.total_seconds() / 3600
        else:
            ist_hours = 0

        # Berechne Soll-Stunden
        if wh.soll_start and wh.soll_end:
            soll_start = datetime.combine(wh.date, wh.soll_start)
            soll_end = datetime.combine(wh.date, wh.soll_end)
            soll_hours = (soll_end - soll_start).total_seconds() / 3600
        else:
            soll_hours = 0

        # Berechne Differenz und addiere positive Differenzen
        difference = ist_hours - soll_hours
        if difference > 0:
            total_overtime += difference

    return round(total_overtime, 1)

@login_required
def api_scheduled_hours(request):
    """API-Endpunkt für geplante Arbeitsstunden an einem Tag"""
    try:
        date_str = request.GET.get('date')
        if not date_str:
            return JsonResponse({'error': 'Kein Datum angegeben'}, status=400)
            
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Prüfe ob das Datum in der Zukunft liegt
        if date_obj <= timezone.now().date():
            return JsonResponse({
                'error': 'Zeitausgleich kann nur für zukünftige Tage beantragt werden',
                'hours': 0
            })
        
        # Hole das Template für diesen Tag
        template = ScheduleTemplate.objects.filter(
            employee=request.user,
            weekday=date_obj.weekday(),
            valid_from__lte=date_obj
        ).order_by('-valid_from').first()
        
        if template and date_obj.weekday() < 5:  # Nur Werktage (0-4 = Montag-Freitag)
            # Berechne die Stunden
            start = datetime.combine(date.min, template.start_time)
            end = datetime.combine(date.min, template.end_time)
            hours = (end - start).total_seconds() / 3600
            return JsonResponse({'hours': round(hours, 2)})
        else:
            return JsonResponse({
                'error': 'An diesem Tag gibt es keine geplante Arbeitszeit',
                'hours': 0
            })
            
    except Exception as e:
        logger.error(f"Scheduled hours error: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

class AbsenceManagementView(OwnerRequiredMixin, ListView):
    template_name = 'wfm/absence_management.html'
    context_object_name = 'absences'

    def get_queryset(self):
        # Hole alle offenen Urlaubs- und ZA-Anträge
        vacations = Vacation.objects.filter(
            status='REQUESTED'
        ).select_related('employee').order_by('start_date')
        
        time_comps = TimeCompensation.objects.filter(
            status='REQUESTED'
        ).select_related('employee').order_by('date')
    
        
        # Kombiniere die Anträge in eine Liste
        absences = []
        for vacation in vacations:
            absences.append({
                'id': vacation.id,
                'type': 'vacation',
                'employee': vacation.employee,
                'start_date': vacation.start_date,
                'end_date': vacation.end_date,
                'status': vacation.status,
                'notes': vacation.notes,
                'is_vacation': True
            })
            
        for time_comp in time_comps:
            absences.append({
                'id': time_comp.id,
                'type': 'time_comp',
                'employee': time_comp.employee,
                'start_date': time_comp.date,
                'end_date': time_comp.date,
                'status': time_comp.status,
                'notes': time_comp.notes,
                'is_vacation': False
            })
            
        # Sortiere nach Datum und Mitarbeiter
        return sorted(absences, key=lambda x: (x['start_date'], x['employee'].username))

    def post(self, request, *args, **kwargs):
        try:
            absence_type = request.POST.get('type')
            absence_id = request.POST.get('id')
            action = request.POST.get('action')
            
            if absence_type == 'vacation':
                absence = Vacation.objects.get(id=absence_id)
            else:
                absence = TimeCompensation.objects.get(id=absence_id)
                
            if action == 'approve':
                absence.status = 'APPROVED'
                messages.success(request, gettext('Antrag wurde genehmigt'))
            else:
                absence.status = 'REJECTED'
                messages.success(request, gettext('Antrag wurde abgelehnt'))
                
            absence.save()
            
            return JsonResponse({'success': True})
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

@login_required
def api_calculate_vacation_hours(request):
    """API-Endpunkt zur Berechnung der Urlaubsstunden (ohne Speicherung)"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
        
    try:
        data = json.loads(request.body)
        start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        
        # Erstelle temporären Urlaubsantrag zur Stundenberechnung
        temp_vacation = Vacation(
            employee=request.user,
            start_date=start_date,
            end_date=end_date
        )
        
        # Berechne benötigte Stunden
        needed_hours = temp_vacation.calculate_vacation_hours()
        
        # Prüfe verfügbare Stunden
        entitlement = VacationEntitlement.objects.filter(
            employee=request.user,
            year=start_date.year
        ).first()
        
        if not entitlement:
            return JsonResponse({
                'error': gettext('Kein Urlaubsanspruch für dieses Jahr')
            }, status=400)
            
        # Berechne bereits verwendete Stunden
        used_hours = sum(
            v.calculate_vacation_hours() 
            for v in Vacation.objects.filter(
                employee=request.user,
                start_date__year=start_date.year,
                status='APPROVED'
            )
        )
        
        remaining_hours = entitlement.total_hours - used_hours
        
        return JsonResponse({
            'success': True,
            'needed_hours': float(needed_hours),
            'remaining_hours': float(remaining_hours - needed_hours)
        })
        
    except Exception as e:
        logger.error(f"Vacation calculation error: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

class SickLeaveManagementView(LoginRequiredMixin, OwnerRequiredMixin, ListView):
    template_name = 'wfm/sick_leave_management.html'
    model = SickLeave
    context_object_name = 'sick_leaves'  # Wichtig für das Template
    
    def get_queryset(self):
        # Verwende select_related für effiziente Datenbankabfragen
        return SickLeave.objects.all().select_related('employee', 'document').order_by('-start_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['users'] = CustomUser.objects.all()
        return context

    def post(self, request, *args, **kwargs):
        try:
            sick_leave_id = request.POST.get('id')
            action = request.POST.get('action')
            
            sick_leave = SickLeave.objects.get(id=sick_leave_id)
            
            if action == 'toggle':
                # Toggle zwischen SUBMITTED und PENDING
                sick_leave.status = 'PENDING' if sick_leave.status == 'SUBMITTED' else 'SUBMITTED'
                sick_leave.save()
                return JsonResponse({'success': True})
                
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

@login_required
def api_upload_sick_leave_document(request, sick_leave_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
        
    try:
        sick_leave = get_object_or_404(SickLeave, id=sick_leave_id)
        
        # Prüfe Berechtigung
        if request.user.role != 'OWNER' and request.user != sick_leave.employee:
            return JsonResponse({'error': gettext('Keine Berechtigung')}, status=403)
        
        if 'document' not in request.FILES:
            return JsonResponse({'error': gettext('Keine Datei ausgewählt')}, status=400)
            
        document = request.FILES['document']
        
        # Lösche altes Dokument falls vorhanden
        if sick_leave.document:
            sick_leave.document.delete()
        
        # Erstelle neues Dokument mit korrektem User-Feld
        new_document = UserDocument.objects.create(
            user=sick_leave.employee,  # employee statt user
            file=document,
            display_name=f"Krankmeldung - {sick_leave.employee.get_full_name()} - {sick_leave.start_date:%d.%m.%Y}",  # Formatierung geändert
            notes=''
        )
        
        # Verknüpfe mit dem Krankenstand und setze Status auf SUBMITTED
        sick_leave.document = new_document
        sick_leave.status = 'SUBMITTED'
        sick_leave.save()
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        logger.error(f"Document upload error: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

# TODO: Abgelehnte Anträge anzeigen in Liste und Kalender
# TODO: BEi ABlehnung Begründung einfügen
# TODO: Check og abgelehnte Abwesenheiten eh nicht bei den Tagen weggezählt werden



class UserDocumentListView(LoginRequiredMixin, ListView):  # OwnerRequiredMixin entfernt
    model = UserDocument
    template_name = 'wfm/user_documents.html'
    context_object_name = 'documents'

    def get_queryset(self):
        # Owner sieht alle Dokumente, andere nur ihre eigenen
        if self.request.user.role == 'OWNER':
            return UserDocument.objects.all()
        return UserDocument.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Nur Owner sieht die User-Liste für das Dropdown
        if self.request.user.role == 'OWNER':
            context['users'] = CustomUser.objects.all().order_by('first_name', 'last_name')
        return context

@login_required
def upload_document(request):
    if request.method == 'POST':
        try:
            # Wenn kein user_id übergeben wurde oder User kein Owner ist, 
            # verwende den eingeloggten User
            if not request.POST.get('user') or request.user.role != 'OWNER':
                user_id = request.user.id
            else:
                user_id = request.POST.get('user')
                
            file = request.FILES.get('file')
            display_name = request.POST.get('display_name')
            notes = request.POST.get('notes')
            sick_leave_id = request.POST.get('sick_leave_id')
            
            # Erstelle das Dokument
            document = UserDocument.objects.create(
                user_id=user_id,
                file=file,
                display_name=display_name,
                notes=notes
            )

            # Wenn eine sick_leave_id vorhanden ist, verknüpfe das Dokument
            if sick_leave_id:
                try:
                    sick_leave = SickLeave.objects.get(id=sick_leave_id)
                    sick_leave.document = document
                    sick_leave.status = 'SUBMITTED'
                    sick_leave.save()
                except SickLeave.DoesNotExist:
                    document.delete()
                    messages.error(request, gettext('Krankenstand nicht gefunden'))
                    return redirect('wfm:user-documents')

            messages.success(request, gettext('Dokument erfolgreich hochgeladen'))
            return redirect('wfm:user-documents')

        except Exception as e:
            logger.error(f"Fehler beim Hochladen: {str(e)}", exc_info=True)
            messages.error(request, gettext('Fehler beim Hochladen des Dokuments'))
            return redirect('wfm:user-documents')

    return redirect('wfm:user-documents')

@login_required
def api_document_update(request, pk):
    """API zum Aktualisieren eines Dokuments"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    document = get_object_or_404(UserDocument, pk=pk)
    
    # Prüfe Berechtigungen
    if request.user.role != 'OWNER' and document.user != request.user:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    try:
        data = json.loads(request.body)
        document.display_name = data.get('display_name', document.display_name)
        document.notes = data.get('notes', document.notes)
        document.save()
        
        return JsonResponse({
            'success': True,
            'document': {
                'id': document.id,
                'display_name': document.display_name,
                'notes': document.notes,
                'file_url': document.file.url if document.file else None,
                'uploaded_at': document.uploaded_at.strftime('%d.%m.%Y %H:%M')
            }
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
def delete_document(request, pk):
    if request.user.role != 'OWNER':
        raise PermissionDenied
        
    if request.method == 'POST':
        document = get_object_or_404(UserDocument, pk=pk)
        document.delete()
        messages.success(request, gettext('Dokument wurde erfolgreich gelöscht.'))
        
    return redirect('wfm:user-documents')

class EmployeeDetailView(LoginRequiredMixin, DetailView):
    model = CustomUser
    template_name = 'wfm/employee_detail.html'
    context_object_name = 'employee'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        employee = self.get_object()
        
        # Get selected year or use current year
        selected_year = self.request.GET.get('year')
        current_year = timezone.now().year
        today = timezone.now().date()
        
        if selected_year:
            selected_year = int(selected_year)
        else:
            selected_year = current_year
            
        context['selected_year'] = selected_year
        context['current_year'] = current_year
        
        # Liste der verfügbaren Jahre (von Anstellungsbeginn bis heute)
        start_year = employee.employed_since.year if employee.employed_since else current_year
        context['available_years'] = range(current_year, start_year - 1, -1)

        # Berechne Alter und Betriebszugehörigkeit
        if employee.date_of_birth:
            age = relativedelta(today, employee.date_of_birth).years
            context['age'] = age

        if employee.employed_since:
            years_employed = relativedelta(today, employee.employed_since).years
            months_employed = relativedelta(today, employee.employed_since).months
            context['years_employed'] = years_employed
            context['months_employed'] = months_employed

        # Hole die Dokumente
        context['documents'] = employee.documents.all()

        # Hole Urlaubsanspruch und berechne verwendete Stunden
        vacation_entitlement = VacationEntitlement.objects.filter(
            employee=employee,
            year=selected_year  # Verwende selected_year statt current_year
        ).first()
        context['vacation_entitlement'] = vacation_entitlement

        # Hole genommenen Urlaub für das ausgewählte Jahr
        vacations = Vacation.objects.filter(
            employee=employee,
            start_date__year=selected_year  # Verwende selected_year
        ).order_by('-start_date')
        context['vacations'] = vacations

        # Berechne verwendete Urlaubsstunden (8 Stunden pro Tag)
        if vacation_entitlement:
            used_vacation_hours = sum((v.end_date - v.start_date).days + 1 for v in vacations) * 8
            context['used_vacation_hours'] = used_vacation_hours
            context['vacation_progress_percent'] = int((used_vacation_hours / vacation_entitlement.total_hours) * 100)

        # Hole Krankmeldungen für das ausgewählte Jahr
        context['sick_leaves'] = SickLeave.objects.filter(
            employee=employee,
            start_date__year=selected_year  # Verwende selected_year
        ).order_by('-start_date')

        # Hole Überstunden für das ausgewählte Jahr
        context['overtime_accounts'] = OvertimeAccount.objects.filter(
            employee=employee,
            year=selected_year  # Verwende selected_year
        ).order_by('-month')

        if employee.role == 'THERAPIST':
            # Hole die letzten Raumbuchungen für Therapeuten
            context['bookings'] = TherapistBooking.objects.filter(
                therapist=employee
            ).order_by('-date')[:5]

        # Berechne verfügbare Zeitausgleichstage
        overtime_total = OvertimeAccount.objects.filter(
            employee=employee,
            year=current_year,
            is_finalized=True
        ).aggregate(
            total=Sum('hours_for_timecomp')
        )['total'] or 0

        used_timecomp = TimeCompensation.objects.filter(
            employee=employee,
            date__year=current_year,
            status='APPROVED'
        ).count() * 8  # 8 Stunden pro Tag

        available_timecomp_hours = max(0, overtime_total - used_timecomp)
        context['available_timecomp_days'] = available_timecomp_hours / 8
        context['available_timecomp_hours'] = available_timecomp_hours

        # Hole Wochenarbeitszeiten
        weekdays = range(0, 7)  # 0 = Montag, 6 = Sonntag
        weekly_schedule = []
        total_weekly_hours = Decimal('0.00')
        
        if employee.role == 'THERAPIST':
            schedule_model = TherapistScheduleTemplate
            schedule_filter = {'therapist': employee}
        else:
            schedule_model = ScheduleTemplate
            schedule_filter = {'employee': employee}

        for weekday in weekdays:
            schedule = schedule_model.objects.filter(
                **schedule_filter,
                weekday=weekday
            ).order_by('-valid_from').first()

            if schedule:
                total_weekly_hours += schedule.hours

            weekly_schedule.append({
                'weekday': dict(schedule_model.WEEKDAY_CHOICES)[weekday],
                'schedule': schedule
            })
        
        context['weekly_schedule'] = weekly_schedule
        context['total_weekly_hours'] = total_weekly_hours

        # Hole nur zukünftige Urlaube
        future_vacations = Vacation.objects.filter(
            employee=employee,
            start_date__gte=today
        ).order_by('start_date')

        # Berechne die Stunden/Tage für jeden Urlaub
        for vacation in future_vacations:
            vacation.total_hours = vacation.calculate_vacation_hours()
            vacation.total_days = vacation.total_hours / 8
            
            context['future_vacations'] = future_vacations

        # Hole zukünftige Zeitausgleiche
        future_timecomps = TimeCompensation.objects.filter(
            employee=employee,
            date__gte=today
        ).select_related(
            'employee'  # Falls wir employee-Informationen brauchen
        ).order_by('date')

        all_timecomps = TimeCompensation.objects.filter(employee=employee).order_by('-date') #Sortiere nach Datum, neuste zuerst
        context['all_timecomps'] = all_timecomps
        context['future_timecomps'] = future_timecomps

        # Füge die Status-Display-Methode hinzu
        for timecomp in future_timecomps:
            timecomp.get_status_display = dict(TimeCompensation.STATUS_CHOICES)[timecomp.status]
            timecomp.total_hours = timecomp.hours

        # Hole alle Arbeitszeitpläne (nicht nur den aktuellsten)
        weekdays = range(0, 7)
        if employee.role == 'THERAPIST':
            schedule_model = TherapistScheduleTemplate
            schedule_filter = {'therapist': employee}
        else:
            schedule_model = ScheduleTemplate
            schedule_filter = {'employee': employee}

        # Hole alle unique valid_from Daten
        schedule_periods = schedule_model.objects.filter(
            **schedule_filter
        ).values('valid_from').distinct().order_by('-valid_from')

        schedule_history = []
        for period in schedule_periods:
            weekly_schedule = []
            total_hours = Decimal('0.00')
            
            for weekday in weekdays:
                # Hier ist die Änderung: Hole das letzte gültige Template VOR diesem Datum
                schedule = schedule_model.objects.filter(
                    **schedule_filter,
                    weekday=weekday,
                    valid_from__lte=period['valid_from']  # Wichtig: __lte statt = 
                ).order_by('-valid_from').first()

                if schedule:
                    total_hours += schedule.hours

                weekly_schedule.append({
                    'weekday': dict(schedule_model.WEEKDAY_CHOICES)[weekday],
                    'schedule': schedule
                })
            
            schedule_history.append({
                'valid_from': period['valid_from'],
                'schedule': weekly_schedule,
                'total_hours': total_hours
            })

        context['schedule_history'] = schedule_history

        # Zahlungsübersicht für Therapeuten
        if employee.role == 'THERAPIST':
            payment_overview = []
            current_date = timezone.now().date()
            
            # Zeige die letzten 6 Monate
            for i in range(6):
                date = current_date - relativedelta(months=i)
                bookings = TherapistBooking.objects.filter(
                    therapist=employee,
                    date__year=date.year,
                    date__month=date.month,
                )
                
                total_hours = bookings.aggregate(
                    total=Sum('actual_hours')
                )['total'] or 0
                
                pending_bookings = bookings.filter(therapist_extra_hours_payment_status='PENDING')
                pending_hours = pending_bookings.aggregate(
                    total=Sum('actual_hours')
                )['total'] or 0
                
                pending_amount = pending_hours * employee.room_rate
                
                payment_overview.append({
                    'year': date.year,
                    'month': date.month,
                    'month_name': date.strftime('%B'),
                    'total_hours': total_hours,
                    'pending_hours': pending_hours,
                    'pending_amount': pending_amount
                })
            
            context['payment_overview'] = payment_overview

        return context

    def get_queryset(self):
        # Nur Owner dürfen alle Mitarbeiter sehen, andere nur sich selbst
        if self.request.user.role == 'OWNER':
            return CustomUser.objects.all()
        return CustomUser.objects.filter(id=self.request.user.id)

class EmployeeListView(LoginRequiredMixin, OwnerRequiredMixin, TemplateView):
    template_name = 'wfm/employee_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Mitarbeiter nach Rollen gruppieren
        context['therapists'] = CustomUser.objects.filter(role='THERAPIST').order_by('first_name', 'last_name')
        context['assistants'] = CustomUser.objects.filter(role='ASSISTANT').order_by('first_name', 'last_name')
        context['cleaners'] = CustomUser.objects.filter(role='CLEANING').order_by('first_name', 'last_name')
        context['owners'] = CustomUser.objects.filter(role='OWNER').order_by('first_name', 'last_name')
        
        return context

@login_required
def api_therapist_booking_mark_as_paid(request):
    if request.user.role != 'OWNER':
        return JsonResponse({'success': False, 'error': gettext('Keine Berechtigung')})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': gettext('Ungültige Anfrage')})
    
    try:
        data = json.loads(request.body)
        booking_ids = data.get('booking_ids', [])
        
        TherapistBooking.objects.filter(id__in=booking_ids).update(
            therapist_extra_hours_payment_status='PAID',
            therapist_extra_hours_payment_date=timezone.now().date()
        )
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

class FinanceOverviewView(LoginRequiredMixin, OwnerRequiredMixin, TemplateView):
    template_name = 'wfm/finance_overview.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        month = self.request.GET.get('month')
        year = self.request.GET.get('year')
        if not month or not year:
            today = timezone.now()
            month = today.month
            year = today.year
        else:
            month = int(month)
            year = int(year)

        # Create current_date for navigation
        current_date = datetime_date(year, month, 1)

        # 1. Einnahmen von Therapeuten
        therapist_income = TherapistBooking.objects.filter(
            date__year=year,
            date__month=month
        ).values(
            'therapist_id',
            'therapist__first_name',
            'therapist__last_name',
            'therapist__room_rate',
            'therapist_extra_hours_payment_status',
            'therapist_extra_hours_payment_date'  # Hinzugefügt für Datumsanzeige
        ).annotate(
            scheduled_hours=Coalesce(Sum('hours'), Value(0, output_field=DecimalField())),
            actual_hours=Coalesce(Sum('actual_hours'), Value(0, output_field=DecimalField())),
            difference_hours=Coalesce(Sum('difference_hours'), Value(0, output_field=DecimalField())),
            room_cost=ExpressionWrapper(
                F('scheduled_hours') * F('therapist__room_rate'),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            ),
            extra_cost=ExpressionWrapper(
                F('difference_hours') * F('therapist__room_rate'),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            ),
            therapist_name=Concat(
                'therapist__first_name', 
                Value(' '), 
                'therapist__last_name',
                output_field=CharField()
            )
        ).order_by('therapist__first_name', 'therapist__last_name')


        # Gruppiere die Ergebnisse nach Therapeut
        grouped_income = {}
        for booking in therapist_income:
            therapist_id = booking['therapist_id']
            if therapist_id not in grouped_income:
                grouped_income[therapist_id] = {
                    'therapist_id': therapist_id,  # Wichtig: ID für den Button
                    'therapist_name': booking['therapist_name'],
                    'scheduled_hours': booking['scheduled_hours'],
                    'actual_hours': booking['actual_hours'],
                    'difference_hours': booking['difference_hours'],
                    'room_cost': booking['room_cost'],
                    'extra_cost': booking['extra_cost'],
                    'therapist_extra_hours_payment_status': booking['therapist_extra_hours_payment_status'],
                    'therapist_extra_hours_payment_date': booking['therapist_extra_hours_payment_date'],
                    'total': booking['room_cost'] + booking['extra_cost']
                }


        context['grouped_income'] = grouped_income.values()

        total_therapist_hours = sum(income['scheduled_hours'] for income in grouped_income.values())
        total_therapist_room_cost = sum(income['room_cost'] for income in grouped_income.values())
        total_therapist_difference_hours = sum(income['difference_hours'] for income in grouped_income.values())
        total_therapist_extra_cost = sum(income['extra_cost'] for income in grouped_income.values())

        # 2. Ausgaben für Mitarbeiter
        # Hole die Daten aus der WorkingHoursListView
        working_hours_view = WorkingHoursListView()
        working_hours_view.request = self.request
        working_hours_view.kwargs = {'year': year, 'month': month}
        working_hours_view.object_list = working_hours_view.get_queryset()  # Setze object_list
        working_hours_context = working_hours_view.get_context_data()

        # Extrahiere die relevanten Daten für Assistenten und Reinigungskräfte
        assistant_expenses = {}  # Verwende ein Dict statt Liste für eindeutige Einträge
        cleaning_expenses = {}   # Verwende ein Dict statt Liste für eindeutige Einträge

        for date_data in working_hours_context['dates']:
            if date_data.get('employee'):
                employee = date_data['employee']
                if employee.role == 'ASSISTANT':
                    if employee.id not in assistant_expenses:
                        assistant_expenses[employee.id] = {
                            'employee__id': employee.id,
                            'employee__first_name': employee.first_name,
                            'employee__last_name': employee.last_name,
                            'employee__hourly_rate': employee.hourly_rate,
                            'total_soll': Decimal('0'),
                            'worked_hours': Decimal('0'),
                            'absence_hours': Decimal('0')
                        }
                    # Addiere die Stunden
                    assistant_expenses[employee.id]['total_soll'] += Decimal(str(date_data.get('soll_hours', 0)))
                    assistant_expenses[employee.id]['worked_hours'] += Decimal(str(date_data.get('ist_hours', 0)))
                    
                    # In der FinanceOverviewView, bei der Berechnung der assistant_expenses und cleaning_expenses
                    working_hours = WorkingHours.objects.filter(
                        employee_id=employee.id,
                        date__year=year,
                        date__month=month
                    ).values(
                        'is_paid',
                        'paid_date'
                    ).first()

                    if working_hours:
                        assistant_expenses[employee.id]['is_paid'] = working_hours['is_paid']
                        assistant_expenses[employee.id]['paid_date'] = working_hours['paid_date']
                    else:
                        assistant_expenses[employee.id]['is_paid'] = False
                        assistant_expenses[employee.id]['paid_date'] = None
                    
                elif employee.role == 'CLEANING':
                    if employee.id not in cleaning_expenses:
                        cleaning_expenses[employee.id] = {
                            'employee__id': employee.id,
                            'employee__first_name': employee.first_name,
                            'employee__last_name': employee.last_name,
                            'employee__hourly_rate': employee.hourly_rate,
                            'total_soll': Decimal('0'),
                            'worked_hours': Decimal('0'),
                            'absence_hours': Decimal('0')
                        }
                    # Addiere die Stunden
                    cleaning_expenses[employee.id]['total_soll'] += Decimal(str(date_data.get('soll_hours', 0)))
                    cleaning_expenses[employee.id]['worked_hours'] += Decimal(str(date_data.get('ist_hours', 0)))

        # Berechne die finalen Werte für jeden Mitarbeiter
        for expense in assistant_expenses.values():
            expense['absence_hours'] = expense['total_soll'] - expense['worked_hours']
            expense['amount'] = expense['total_soll'] * expense['employee__hourly_rate']

        for expense in cleaning_expenses.values():
            expense['absence_hours'] = expense['total_soll'] - expense['worked_hours']
            expense['amount'] = expense['total_soll'] * expense['employee__hourly_rate']

        # Berechne die Summen für die Ausgaben
        total_assistant_soll_hours = sum(expense['total_soll'] for expense in assistant_expenses.values())
        total_assistant_ist_hours = sum(expense['worked_hours'] for expense in assistant_expenses.values())
        total_assistant_absence_hours = sum(expense['absence_hours'] for expense in assistant_expenses.values())
        total_assistant_amount = sum(expense['amount'] for expense in assistant_expenses.values())

        total_cleaning_soll_hours = sum(expense['total_soll'] for expense in cleaning_expenses.values())
        total_cleaning_ist_hours = sum(expense['worked_hours'] for expense in cleaning_expenses.values())
        total_cleaning_absence_hours = sum(expense['absence_hours'] for expense in cleaning_expenses.values())
        total_cleaning_amount = sum(expense['amount'] for expense in cleaning_expenses.values())

        # c) Überstunden-Ausgaben
        overtime_expenses = OvertimeAccount.objects.filter(
            year=year,
            month=month,
            hours_for_payment__gt=0  # Nur Einträge mit zu bezahlenden Stunden
        ).select_related('employee').values(
            'employee__id',
            'employee__first_name',
            'employee__last_name',
            'employee__role',
            'employee__hourly_rate',
            'overtime_paid',
            'overtime_paid_date'
        ).annotate(
            overtime_hours=Sum('hours_for_payment'),
            amount=ExpressionWrapper(
                Sum('hours_for_payment') * F('employee__hourly_rate'),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            )
        ).order_by('employee__first_name', 'employee__last_name')


        # Berechne Summen
        total_income = sum(
            income['total']
            for income in grouped_income.values()
        )

        
        # Berechne die Summen für Überstunden
        total_overtime_hours = overtime_expenses.aggregate(
            total=Coalesce(Sum('overtime_hours'), Decimal('0.00'))
        )['total']
        total_overtime_amount = overtime_expenses.aggregate(
            total=Coalesce(Sum('amount'), Decimal('0.00'))
        )['total']

        # Füge die Rollen-Anzeige und Summen zum Context hinzu
        for expense in overtime_expenses:
            expense['role_display'] = {
                'OWNER': gettext('Inhaber'),
                'THERAPIST': gettext('Therapeut'),
                'ASSISTANT': gettext('Assistent'),
                'CLEANING': gettext('Reinigungskraft')
            }.get(expense['employee__role'], expense['employee__role'])


        # Berechne die Summen für die Ausgaben
        total_expenses = sum(
            a['amount'] for a in assistant_expenses.values()) + sum(c['amount'] for c in cleaning_expenses.values()) + total_overtime_amount
        

        
        context.update({
            'grouped_income': grouped_income.values(),
            'total_therapist_hours': total_therapist_hours,
            'total_therapist_room_cost': total_therapist_room_cost,
            'total_therapist_difference_hours': total_therapist_difference_hours,
            'total_therapist_extra_cost': total_therapist_extra_cost,
            'assistant_expenses': assistant_expenses.values(),
            'cleaning_expenses': cleaning_expenses.values(),
            'overtime_expenses': overtime_expenses,
            'total_overtime_hours': total_overtime_hours,
            'total_overtime_amount': total_overtime_amount,
            'total_income': total_income,
            'total_expenses': total_expenses,
            'total_assistant_soll_hours': total_assistant_soll_hours,
            'total_assistant_ist_hours': total_assistant_ist_hours,
            'total_assistant_absence_hours': total_assistant_absence_hours,
            'total_assistant_amount': total_assistant_amount,

            'total_cleaning_soll_hours': total_cleaning_soll_hours,
            'total_cleaning_ist_hours': total_cleaning_ist_hours,
            'total_cleaning_absence_hours': total_cleaning_absence_hours,
            'total_cleaning_amount': total_cleaning_amount,
            'current_date': current_date,
            'month_name': current_date.strftime('%B %Y'),
            'prev_month': (current_date - relativedelta(months=1)),
            'next_month': (current_date + relativedelta(months=1))
        })
        
        return context

@login_required
def api_mark_extra_hours_as_paid(request):
    if request.user.role != 'OWNER':
        return JsonResponse({'success': False, 'error': gettext('Keine Berechtigung')})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': gettext('Ungültige Anfrage')})
    
    try:
        data = json.loads(request.body)
        therapist_id = data.get('therapist_id')
        month = data.get('month')
        year = data.get('year')
        
        # Markiere alle Mehrstunden als bezahlt
        TherapistBooking.objects.filter(
            therapist_id=therapist_id,
            date__year=year,
            date__month=month,
            actual_hours__gt=F('hours'),
            therapist_extra_hours_payment_status='PENDING'
        ).update(
            therapist_extra_hours_payment_status='PAID',
            therapist_extra_hours_payment_date=timezone.now().date()
        )
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def api_working_hours_create(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            date = parse_date(data.get('date'))
            
            # Prüfe ob bereits ein Eintrag für diesen Tag existiert
            existing_entry = WorkingHours.objects.filter(
                employee=request.user,
                date=date
            ).first()
            
            if existing_entry:
                return JsonResponse({
                    'success': False,
                    'error': gettext('Für diesen Tag wurde bereits ein Eintrag erstellt')
                }, status=400)

            # Hole den Arbeitsplan für diesen Tag
            schedule = ScheduleTemplate.objects.filter(
                employee=request.user,
                weekday=date.weekday()
            ).order_by('-valid_from').first()
            
            # Standardmäßig die geplanten Stunden verwenden
            soll_hours = schedule.hours if schedule else Decimal('0.00')
            ist_hours = data.get('ist_hours')
            
            # Wenn keine IST-Stunden angegeben wurden, verwende die SOLL-Stunden
            if ist_hours is None or ist_hours == '':
                ist_hours = soll_hours
            else:
                ist_hours = Decimal(str(ist_hours))  # Konvertiere zu Decimal

            working_hours = WorkingHours.objects.create(
                employee=request.user,
                date=date,
                soll_hours=soll_hours,  # Geplante Stunden aus dem Schedule
                ist_hours=ist_hours,    # Tatsächliche Stunden (oder geplante wenn nicht angegeben)
                notes=data.get('notes', '')
            )
            
            return JsonResponse({
                'success': True,
                'id': working_hours.id,
                'soll_hours': float(working_hours.soll_hours),
                'ist_hours': float(working_hours.ist_hours)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
            
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def api_get_scheduled_hours(request):
    date = parse_date(request.GET.get('date'))
    if not date:
        return JsonResponse({'error': 'Invalid date'}, status=400)
        
    schedule = ScheduleTemplate.objects.filter(
        employee=request.user,
        weekday=date.weekday()
    ).order_by('-valid_from').first()
    
    scheduled_hours = float(schedule.hours) if schedule else 0.0
    
    return JsonResponse({
        'scheduled_hours': scheduled_hours
    })

@login_required
def api_therapist_booking_get(request, pk):
    """API-Endpunkt zum Abrufen einer Therapeuten-Buchung"""
    print("\n=== Debug api_therapist_booking_get ===")
    print(f"Requested booking ID: {pk}")
    
    try:
        # Erlaube Zugriff für Owner und den zugewiesenen Therapeuten
        booking = TherapistBooking.objects.get(id=pk)
        print(f"Found booking: {booking}")
        print(f"Therapist: {booking.therapist.username}")
        
        if not (request.user.role == 'OWNER' or request.user == booking.therapist):
            print("Permission denied")
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        response_data = {
            'id': booking.id,
            'therapist': {
                'id': booking.therapist.id,
                'name': booking.therapist.get_full_name() or booking.therapist.username
            },
            'date': booking.date.strftime('%Y-%m-%d'),
            'start_time': booking.start_time.strftime('%H:%M'),
            'end_time': booking.end_time.strftime('%H:%M'),
            'hours': float(booking.hours) if booking.hours else None,
            'actual_hours': float(booking.actual_hours) if booking.actual_hours else None,
            'notes': booking.notes or '',
            'therapist_extra_hours_payment_status': booking.therapist_extra_hours_payment_status
        }
        print(f"Response data: {response_data}")
        return JsonResponse(response_data)
        
    except TherapistBooking.DoesNotExist:
        print(f"Booking not found: {pk}")
        return JsonResponse({
            'error': 'Buchung nicht gefunden'
        }, status=404)
    except Exception as e:
        print(f"Error: {str(e)}")
        return JsonResponse({
            'error': str(e)
        }, status=500)

@login_required
@ensure_csrf_cookie
@require_http_methods(["POST"])
def api_mark_therapist_extra_hours_as_paid(request):
    """API-Endpoint zum Markieren von Therapeuten-Mehrstunden als bezahlt"""
    if request.method != 'POST':
        return HttpResponse(status=405)
        
    if request.user.role != 'OWNER':
        return HttpResponse(status=403)
    
    try:
        data = json.loads(request.body)
        therapist_id = data.get('therapist_id')
        if not therapist_id:
            return JsonResponse({
                'success': False, 
                'error': 'Therapeut ID fehlt'
            }, status=400)
            
        month = int(data.get('month'))
        year = int(data.get('year'))
        set_paid = data.get('set_paid', True)
        
        # Hole alle Buchungen für diesen Monat
        bookings = TherapistBooking.objects.filter(
            therapist_id=therapist_id,
            date__year=year,
            date__month=month,
            actual_hours__gt=F('hours'),
            therapist_extra_hours_payment_status='PENDING' if set_paid else 'PAID'
        )
        
        # Markiere alle als bezahlt/unbezahlt
        new_status = 'PAID' if set_paid else 'PENDING'
        new_date = timezone.now().date() if set_paid else None
        
        updated_count = bookings.update(
            therapist_extra_hours_payment_status=new_status,
            therapist_extra_hours_payment_date=new_date
        )
        
        return JsonResponse({
            'success': True,
            'updated': updated_count
        })
        
    except Exception as e:
        logger.error(f"Error in api_mark_therapist_extra_hours_as_paid: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def api_mark_overtime_as_paid(request):
    """API-Endpoint zum Markieren von Überstunden als bezahlt"""
    if request.user.role != 'OWNER':
        return JsonResponse({'success': False, 'error': gettext('Keine Berechtigung')})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': gettext('Ungültige Anfrage')})
    
    try:
        data = json.loads(request.body)
        
        employee_id = data.get('employee_id')
        month = data.get('month')
        year = data.get('year')
        set_paid = data.get('set_paid', True)
        
        # Hole den Überstunden-Eintrag
        overtime = OvertimeAccount.objects.filter(
            employee_id=employee_id,
            month=month,
            year=year
        )
        
        if not overtime.exists():
            return JsonResponse({
                'success': False,
                'error': gettext('Keine Überstunden gefunden')
            })
        
        # Markiere als bezahlt/unbezahlt
        updated_count = overtime.update(
            overtime_paid=set_paid,
            overtime_paid_date=timezone.now() if set_paid else None
        )
        
        return JsonResponse({
            'success': True,
            'updated': updated_count,
            'new_status': {
                'paid': set_paid,
                'paid_date': timezone.now().strftime('%Y-%m-%d') if set_paid else None
            }
        })
    except Exception as e:
        logger.error(f"Fehler beim Markieren der Überstunden: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def api_mark_salary_as_paid(request):
    """API-Endpoint zum Markieren des Monatsgehalts als bezahlt"""
    if request.user.role != 'OWNER':
        return JsonResponse({'success': False, 'error': gettext('Keine Berechtigung')})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': gettext('Ungültige Anfrage')})
    
    try:
        data = json.loads(request.body)
        employee_id = data.get('employee_id')
        month = data.get('month')
        year = data.get('year')
        set_paid = data.get('set_paid', True)
        
        # Aktualisiere alle Arbeitsstunden-Einträge für diesen Monat
        working_hours = WorkingHours.objects.filter(
            employee_id=employee_id,
            date__year=year,
            date__month=month
        )
        
        if not working_hours.exists():
            return JsonResponse({
                'success': False,
                'error': gettext('Keine Arbeitsstunden gefunden')
            })
        
        updated_count = working_hours.update(
            is_paid=set_paid,
            paid_date=timezone.now().date() if set_paid else None
        )
        
        return JsonResponse({
            'success': True,
            'updated': updated_count
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Markieren des Gehalts: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def check_averaging_periods(request):
    """API-Endpoint zum Überprüfen und Erstellen von Durchrechnungszeiträumen"""
    if request.method == 'POST':
        try:
            AveragingPeriod.check_and_create_periods()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid method'})


