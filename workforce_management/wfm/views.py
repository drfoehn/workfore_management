from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView, View, TemplateView
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext_lazy as _
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
    UserDocument
)
from .forms import UserDocumentForm, WorkingHoursForm, VacationRequestForm, TimeCompensationForm
from django.db.models import Sum, Count, F, Case, When, DecimalField, ExpressionWrapper, Value, CharField
from django.db.models.functions import ExtractMonth, ExtractYear, ExtractHour, ExtractMinute, Coalesce, Concat
from datetime import date, datetime, timedelta, time
import calendar
from django.db import models
from decimal import Decimal  # Am Anfang der Datei hinzufügen
from django.http import JsonResponse
import json
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.core.exceptions import PermissionDenied
import logging
from django.utils.decorators import method_decorator
from django.contrib.auth import logout
from dateutil.relativedelta import relativedelta
from django.contrib import messages

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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 1. Hole Jahr und Monat aus URL oder nutze aktuelles Datum
        today = timezone.now().date()
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

        # Hier ist die Änderung: Hole nur die aktuellsten Templates pro Tag
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

        return context

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
    template_name = 'wfm/overtime_overview.html'

    def get(self, request):
        today = date.today()
        
        # Bestimme den relevanten Monat für die Überstunden
        if today.day <= 7:
            target_date = today - relativedelta(months=1)
        else:
            target_date = today
            
        year = target_date.year
        month = target_date.month
        
        # Berechne die Überstunden
        total_overtime = Decimal(str(calculate_overtime_hours(request.user, year, month)))  # Convert to Decimal
        
        # Hole oder erstelle das Überstundenkonto
        overtime_account, created = OvertimeAccount.objects.get_or_create(
            employee=request.user,
            year=year,
            month=month,
            defaults={
                'total_overtime': total_overtime
            }
        )
        
        if not created and overtime_account.total_overtime != total_overtime:
            overtime_account.total_overtime = total_overtime
            overtime_account.save()

        # Prüfe ob Übertrag möglich ist
        can_transfer = (
            request.user.role in ['ASSISTANT', 'CLEANING'] and
            not overtime_account.is_finalized and
            overtime_account.total_overtime > 0 and
            (
                (today.day <= 7 and month == (today - relativedelta(months=1)).month) or
                (today.day > 7 and month == today.month)
            )
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'overtime_hours': float(overtime_account.total_overtime),
                'transferred_hours': float(overtime_account.hours_for_timecomp),
                'payment_hours': float(overtime_account.hours_for_payment),
                'is_finalized': overtime_account.is_finalized,
                'can_transfer': can_transfer
            })
            
        context = {
            'overtime_hours': overtime_account.total_overtime,
            'transferred_hours': overtime_account.hours_for_timecomp,
            'payment_hours': overtime_account.hours_for_payment,
            'is_finalized': overtime_account.is_finalized,
            'can_transfer': can_transfer,
            'month_name': target_date.strftime('%B %Y')
        }
        
        return render(request, self.template_name, context)

    def post(self, request):
        try:
            if request.user.role not in ['ASSISTANT', 'CLEANING']:
                raise PermissionDenied
            
            data = json.loads(request.body)
            hours_for_timecomp = Decimal(str(data.get('hours_for_timecomp', 0)))
            
            today = date.today()
            if today.day <= 7:
                target_date = today - relativedelta(months=1)
            else:
                target_date = today
                
            overtime_account = OvertimeAccount.objects.get(
                employee=request.user,
                year=target_date.year,
                month=target_date.month
            )
            
            # Berechne die verfügbaren Stunden
            available_hours = overtime_account.total_overtime - overtime_account.hours_for_timecomp
            
            if hours_for_timecomp > available_hours:
                return JsonResponse({
                    'success': False,
                    'error': _('Nicht genügend Überstunden verfügbar')
                })
                
            # Addiere die neuen Stunden
            overtime_account.hours_for_timecomp += hours_for_timecomp
            overtime_account.save()  # Dies setzt automatisch is_finalized = True
            
            return JsonResponse({
                'success': True,
                'overtime_hours': float(overtime_account.total_overtime),
                'transferred_hours': float(overtime_account.hours_for_timecomp),
                'payment_hours': float(overtime_account.hours_for_payment)
            })
            
        except Exception as e:
            logger.error(f"Overtime overview error: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)

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
def save_working_hours(request, date=None):
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
            
            # Erstelle oder aktualisiere den Eintrag
            working_hours, created = WorkingHours.objects.update_or_create(
                employee=request.user,
                date=date,  # Datum aus der URL
                defaults={
                    'start_time': data['start_time'],
                    'end_time': data['end_time'],
                    'break_duration': timedelta(minutes=int(data['break_duration'])),
                    'notes': data.get('notes', '')
                }
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
    })

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
                'error': _('Kein Urlaubsanspruch für dieses Jahr')
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
                'error': _('Nicht genügend Urlaubsstunden verfügbar')
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
            
            # Prüfe verfügbare Stunden
            current_year = timezone.now().year
            total_hours = calculate_overtime_hours(request.user, current_year)
            
            used_hours = TimeCompensation.objects.filter(
                employee=request.user,
                date__year=current_year,
                status='APPROVED'
            ).count() * 8  # 8 Stunden pro Tag
            
            remaining_hours = total_hours - used_hours
            
            if remaining_hours < 8:  # Standard-Arbeitstag
                return JsonResponse({
                    'success': False,
                    'error': f'Nicht genügend Überstunden verfügbar. Verfügbar: {remaining_hours:.1f}h'
                })

            # Erstelle den Zeitausgleichsantrag
            time_comp = TimeCompensation.objects.create(
                employee=request.user,
                date=date,
                notes=data.get('notes', ''),
                status='REQUESTED'
            )
            
            return JsonResponse({'success': True})
            
        except Exception as e:
            logger.error(f"Time compensation request error: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({
        'success': False,
        'error': 'Ungültige Anfrage'
    }, status=400)

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
                
                total_hours = bookings.aggregate(
                    total=Coalesce(Sum('hours', output_field=DecimalField()), 0, output_field=DecimalField())
                )['total']
                
                total_actual = bookings.aggregate(
                    total=Coalesce(Sum('actual_hours', output_field=DecimalField()), 0, output_field=DecimalField())
                )['total']
                
                total_difference = bookings.aggregate(
                    total=Coalesce(Sum('difference_hours', output_field=DecimalField()), 0, output_field=DecimalField())
                )['total']
                
                pending_payment = bookings.filter(
                    actual_hours__gt=F('hours'),
                    extra_hours_payment_status='PENDING'
                ).aggregate(
                    total=Coalesce(Sum('difference_hours', output_field=DecimalField()), 0, output_field=DecimalField())
                )['total']

                months_data.append({
                    'month': month,
                    'month_name': date(year, month, 1).strftime('%B'),
                    'total_hours': total_hours,
                    'total_actual': total_actual,
                    'total_difference': total_difference,
                    'pending_payment': pending_payment,
                    'booking_count': bookings.count()
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
            context['pending_therapist_bookings'] = TherapistBooking.objects.filter(extra_hours_payment_status='PENDING').count()

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
                vacation.total_days = vacation.calculate_vacation_days()
            
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
                    'error': _('Keine Berechtigung')
                }, status=403)
        except WorkingHours.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': _('Arbeitszeit nicht gefunden')
            }, status=404)
    return JsonResponse({
        'success': False,
        'error': _('Ungültige Anfrage')
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
    """API View für Kalender-Events"""
    
    def get(self, request, *args, **kwargs):
        try:
            # Get filter parameters
            start = request.GET.get('start')
            end = request.GET.get('end')
            role = request.GET.get('role')
            employee_id = request.GET.get('employee')
            
            # Parse dates
            start_date = datetime.strptime(start[:10], '%Y-%m-%d').date() if start else None
            end_date = datetime.strptime(end[:10], '%Y-%m-%d').date() if end else None
            
            # Base employee queryset
            employees = CustomUser.objects.all()
            if role:
                employees = employees.filter(role=role)
            elif not request.user.role == 'OWNER':
                employees = employees.filter(id=request.user.id)
            if employee_id:
                employees = employees.filter(id=employee_id)
            
            # Filter events
            working_hours = WorkingHours.objects.filter(employee__in=employees)
            vacations = Vacation.objects.filter(employee__in=employees, status='APPROVED')
            time_comps = TimeCompensation.objects.filter(employee__in=employees, status='APPROVED')
            
            if start_date:
                working_hours = working_hours.filter(date__gte=start_date)
                vacations = vacations.filter(end_date__gte=start_date)
                time_comps = time_comps.filter(date__gte=start_date)
            if end_date:
                working_hours = working_hours.filter(date__lte=end_date)
                vacations = vacations.filter(start_date__lte=end_date)
                time_comps = time_comps.filter(date__lte=end_date)
            
            # Rest der Methode bleibt gleich...
            events = []
            
            # Arbeitszeiten zu Events konvertieren
            for wh in working_hours:
                # Berechne die Stunden
                start_datetime = datetime.combine(date.today(), wh.start_time)
                end_datetime = datetime.combine(date.today(), wh.end_time)
                duration = end_datetime - start_datetime
                hours = duration.total_seconds() / 3600  # Konvertiere zu Stunden
                
                # Ziehe die Pause ab
                if wh.break_duration:
                    break_hours = wh.break_duration.total_seconds() / 3600
                    hours -= break_hours

                event = {
                    'id': f'work_{wh.id}',
                    'title': f'{wh.employee.get_full_name()} ({hours:.1f}h)',
                    'start': f'{wh.date}T{wh.start_time}',
                    'end': f'{wh.date}T{wh.end_time}',
                    'color': wh.employee.color,
                    'type': 'working_hours',
                    'allDay': False
                }
                events.append(event)

            # Urlaub zu Events konvertieren
            for vacation in vacations:
                event = {
                    'id': f'vacation_{vacation.id}',
                    'title': f'{vacation.employee.get_full_name()} - Urlaub',
                    'start': vacation.start_date.isoformat(),
                    'end': (vacation.end_date + timedelta(days=1)).isoformat(),
                    'color': vacation.employee.color,
                    'type': 'vacation',
                    'allDay': True
                }
                events.append(event)

            # Zeitausgleich zu Events konvertieren
            for tc in time_comps:
                event = {
                    'id': f'timecomp_{tc.id}',
                    'title': f'{tc.employee.get_full_name()} - Zeitausgleich',
                    'start': tc.date.isoformat(),
                    'end': (tc.date + timedelta(days=1)).isoformat(),
                    'color': tc.employee.color,
                    'type': 'time_comp',
                    'allDay': True
                }
                events.append(event)
            
            return JsonResponse(events, safe=False)
            
        except Exception as e:
            logger.error(f"Calendar API Error: {str(e)}", exc_info=True)
            return JsonResponse({
                'error': str(e),
                'events': []
            }, status=500)

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
                    'error': _('Bitte Start- und Enddatum angeben')
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
        'error': _('Ungültige Anfrage')
    })

class AssistantCalendarView(LoginRequiredMixin, TemplateView):
    template_name = 'wfm/assistant_calendar.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Füge Mitarbeiter-Filter hinzu für Owner
        if self.request.user.role == 'OWNER':
            context['assistants'] = CustomUser.objects.filter(role='ASSISTANT')
            context['cleaners'] = CustomUser.objects.filter(role='CLEANING')
            
            # Hole den ausgewählten Mitarbeiter
            employee_id = self.request.GET.get('employee')
            if employee_id:
                context['selected_employee'] = CustomUser.objects.filter(id=employee_id).first()
            
            # Hole die ausgewählte Rolle
            role = self.request.GET.get('role')
            if role:
                context['selected_role'] = role
        
        return context

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
        extra_hours_payment_status = 'PENDING'    # Default Status

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
                # Wenn es Mehrstunden gibt und sie PENDING sind, setze Status auf PENDING
                if booking.extra_hours_payment_status == 'PAID':
                    extra_hours_payment_status = 'PAID'

            # Gesamtkosten
            total_sum = total_booked_amount + extra_costs

        context['totals'] = {
            'total_actual_hours': total_actual_hours,
            'total_extra_hours': total_extra_hours,
            'total_booked_amount': total_booked_amount,
            'extra_costs': extra_costs,
            'total_sum': total_sum,
            'extra_hours_payment_status': extra_hours_payment_status
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
            if 'extra_hours_payment_status' in data and booking.difference_hours:
                booking.extra_hours_payment_status = data['extra_hours_payment_status']
                if data['extra_hours_payment_status'] == 'PAID':
                    booking.extra_hours_payment_date = timezone.now().date()
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
                'extra_hours_payment_status': booking.extra_hours_payment_status
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
    context_object_name = 'absences'

    def get_queryset(self):
        return []

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        
        # Hole alle zukünftigen und aktuellen Abwesenheiten
        context['vacations'] = Vacation.objects.filter(
            employee=self.request.user,
            end_date__gte=today
        ).order_by('start_date')
        
        context['time_comps'] = TimeCompensation.objects.filter(
            employee=self.request.user,
            date__gte=today
        ).order_by('date')
        
        context['sick_leaves'] = SickLeave.objects.filter(
            employee=self.request.user,
            end_date__gte=today
        ).order_by('start_date')
        
        # Urlaubsübersicht
        entitlement = VacationEntitlement.objects.filter(
            employee=self.request.user,
            year=today.year
        ).first()
        
        if entitlement:
            # Genehmigte Urlaubsstunden
            approved_vacations = Vacation.objects.filter(
                employee=self.request.user,
                start_date__year=today.year,
                status='APPROVED'
            )
            approved_hours = sum(
                vacation.calculate_vacation_hours() 
                for vacation in approved_vacations
            )
            
            # Beantragte Urlaubsstunden
            pending_vacations = Vacation.objects.filter(
                employee=self.request.user,
                start_date__year=today.year,
                status='REQUESTED'
            )
            pending_hours = sum(
                vacation.calculate_vacation_hours() 
                for vacation in pending_vacations
            )
            
            # Übertrag aus Vorjahr
            last_year = today.year - 1
            last_year_entitlement = VacationEntitlement.objects.filter(
                employee=self.request.user,
                year=last_year
            ).first()
            
            last_year_remaining = Decimal('0')
            if last_year_entitlement:
                last_year_used = sum(
                    vacation.calculate_vacation_hours()
                    for vacation in Vacation.objects.filter(
                        employee=self.request.user,
                        start_date__year=last_year,
                        status='APPROVED'
                    )
                )
                last_year_remaining = max(
                    last_year_entitlement.total_hours - last_year_used, 
                    Decimal('0')
                )
            
            total_hours = entitlement.total_hours + last_year_remaining
            
            context['vacation_info'] = {
                'year': today.year,
                'entitlement': entitlement.total_hours,
                'carried_over': last_year_remaining,
                'total_available': total_hours,
                'approved_hours': approved_hours,
                'pending_hours': pending_hours,
                'remaining_hours': total_hours - approved_hours
            }

        # Zeitausgleich-Übersicht
        if self.request.user.role in ['ASSISTANT', 'CLEANING']:
            # Berechne Überstunden für das aktuelle Jahr
            total_overtime = Decimal('0')
            for month in range(1, 13):
                overtime_account = OvertimeAccount.objects.filter(
                    employee=self.request.user,
                    year=today.year,
                    month=month,
                    is_finalized=True
                ).first()
                if overtime_account:
                    total_overtime += overtime_account.hours_for_timecomp

            # Bereits genommener Zeitausgleich
            approved_timecomp = TimeCompensation.objects.filter(
                employee=self.request.user,
                date__year=today.year,
                status='APPROVED'
            )
            approved_timecomp_hours = sum(tc.hours for tc in approved_timecomp)

            # Beantragter Zeitausgleich
            pending_timecomp = TimeCompensation.objects.filter(
                employee=self.request.user,
                date__year=today.year,
                status='REQUESTED'
            )
            pending_timecomp_hours = sum(tc.hours for tc in pending_timecomp)

            context['timecomp_info'] = {
                'year': today.year,
                'total_hours': total_overtime,
                'approved_hours': approved_timecomp_hours,
                'pending_hours': pending_timecomp_hours,
                'remaining_hours': total_overtime - approved_timecomp_hours
            }
        
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
        remaining_hours = total_hours - used_hours
        
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
                messages.success(request, _('Antrag wurde genehmigt'))
            else:
                absence.status = 'REJECTED'
                messages.success(request, _('Antrag wurde abgelehnt'))
                
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
                'error': _('Kein Urlaubsanspruch für dieses Jahr')
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

class SickLeaveManagementView(OwnerRequiredMixin, ListView):
    template_name = 'wfm/sick_leave_management.html'
    context_object_name = 'sick_leaves'

    def get_queryset(self):
        return SickLeave.objects.all().select_related('employee').order_by('-start_date')

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

# TODO: Abgelehnte Anträge anzeigen in Liste und Kalender
# TODO: BEi ABlehnung Begründung einfügen
# TODO: Check og abgelehnte Abwesenheiten eh nicht bei den Tagen weggezählt werden



class UserDocumentListView(OwnerRequiredMixin, ListView):
    model = UserDocument
    template_name = 'wfm/user_documents.html'
    context_object_name = 'documents'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['users'] = CustomUser.objects.all().order_by('first_name', 'last_name')
        return context

@login_required
def upload_document(request):
    if request.user.role != 'OWNER':
        raise PermissionDenied
        
    if request.method == 'POST':
        form = UserDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save()
            messages.success(request, _('Dokument erfolgreich hochgeladen.'))
            return redirect('wfm:user-documents')
    return redirect('wfm:user-documents')

@login_required
def delete_document(request, pk):
    if request.user.role != 'OWNER':
        raise PermissionDenied
        
    if request.method == 'POST':
        document = get_object_or_404(UserDocument, pk=pk)
        document.delete()
        messages.success(request, _('Dokument wurde erfolgreich gelöscht.'))
        
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
                    status='COMPLETED'  # Nur abgeschlossene Buchungen
                )
                
                total_hours = bookings.aggregate(
                    total=Sum('actual_hours')
                )['total'] or 0
                
                pending_bookings = bookings.filter(extra_hours_payment_status='PENDING')
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
        context['owners'] = CustomUser.objects.filter(role='OWNER').order_by('first_name', 'last_name')
        
        return context

@login_required
def api_therapist_booking_mark_as_paid(request):
    if request.user.role != 'OWNER':
        return JsonResponse({'success': False, 'error': _('Keine Berechtigung')})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': _('Ungültige Anfrage')})
    
    try:
        data = json.loads(request.body)
        booking_ids = data.get('booking_ids', [])
        
        TherapistBooking.objects.filter(id__in=booking_ids).update(
            extra_hours_payment_status='PAID',
            extra_hours_payment_date=timezone.now().date()
        )
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

class FinanceOverviewView(LoginRequiredMixin, TemplateView):
    template_name = 'wfm/finance_overview.html'

    def get_context_data(self, **kwargs):
        if self.request.user.role != 'OWNER':
            raise PermissionDenied
            
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
        current_date = date(year, month, 1)

        print(f"\nDEBUG: Berechne für {month}/{year}")

        # 1. Einnahmen von Therapeuten
        therapist_income = TherapistBooking.objects.filter(
            date__year=year,
            date__month=month
        ).values(
            'therapist_id',
            'therapist__first_name',
            'therapist__last_name',
            'therapist__room_rate',
            'extra_hours_payment_status'
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

        print("\nDEBUG: Therapist Income Query:")
        for booking in therapist_income:
            print(f"Therapeut: {booking['therapist_name']}")
            print(f"Scheduled: {booking['scheduled_hours']}")
            print(f"Actual: {booking['actual_hours']}")
            print(f"Difference: {booking['difference_hours']}")
            print(f"Room Cost: {booking['room_cost']}")
            print(f"Extra Cost: {booking['extra_cost']}")
            print(f"Payment Status: {booking['extra_hours_payment_status']}")
            print("---")

        # Gruppiere die Ergebnisse nach Therapeut
        grouped_income = {}
        for booking in therapist_income:
            therapist_id = booking['therapist_id']
            if therapist_id not in grouped_income:
                grouped_income[therapist_id] = {
                    'therapist_name': booking['therapist_name'],
                    'scheduled_hours': booking['scheduled_hours'],
                    'actual_hours': booking['actual_hours'],
                    'difference_hours': booking['difference_hours'],
                    'room_cost': booking['room_cost'],
                    'extra_cost': booking['extra_cost'],
                    'extra_hours_payment_status': booking['extra_hours_payment_status'],
                    'total': booking['room_cost'] + booking['extra_cost']
                }

        print("\nDEBUG: Grouped Income:")
        for therapist_id, data in grouped_income.items():
            print(f"Therapeut ID: {therapist_id}")
            print(f"Name: {data['therapist_name']}")
            print(f"Scheduled: {data['scheduled_hours']}")
            print(f"Difference: {data['difference_hours']}")
            print(f"Room Cost: {data['room_cost']}")
            print(f"Extra Cost: {data['extra_cost']}")
            print(f"Payment Status: {data['extra_hours_payment_status']}")
            print(f"Total: {data['total']}")
            print("---")

        context['grouped_income'] = grouped_income.values()

        # 2. Ausgaben für Mitarbeiter
        # a) Assistenten
        assistant_hours = WorkingHours.objects.filter(
            date__year=year,
            date__month=month,
            employee__role='ASSISTANT'
        )
        print(f"\nGefundene Assistenten-Stunden: {assistant_hours.count()}")

        assistant_expenses = assistant_hours.select_related('employee').values(
            'employee__first_name',
            'employee__last_name'
        ).annotate(
            regular_hours=Coalesce(Sum('ist_hours'), Value(0, output_field=DecimalField())),
            amount=ExpressionWrapper(
                Sum(F('ist_hours') * F('employee__hourly_rate')),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            )
        ).order_by('employee__first_name', 'employee__last_name')

        print("\nAssistant Expenses:")
        for a in assistant_expenses:
            print(f"{a['employee__first_name']} {a['employee__last_name']}: {a['regular_hours']}h = {a['amount']}€")

        # b) Reinigungskräfte
        cleaning_hours = WorkingHours.objects.filter(
            date__year=year,
            date__month=month,
            employee__role='CLEANING'
        )
        print(f"\nGefundene Reinigungs-Stunden: {cleaning_hours.count()}")

        cleaning_expenses = cleaning_hours.select_related('employee').values(
            'employee__first_name',
            'employee__last_name'
        ).annotate(
            regular_hours=Coalesce(Sum('ist_hours'), Value(0, output_field=DecimalField())),
            amount=ExpressionWrapper(
                Sum(F('ist_hours') * F('employee__hourly_rate')),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            )
        ).order_by('employee__first_name', 'employee__last_name')

        # c) Überstunden-Ausgaben
        overtime_expenses = WorkingHours.objects.filter(
            date__year=year,
            date__month=month,
            ist_hours__gt=F('soll_hours')
        ).select_related('employee').values(
            'employee__first_name',
            'employee__last_name',
            'employee__role'
        ).annotate(
            hours=ExpressionWrapper(
                Sum(F('ist_hours') - F('soll_hours')),
                output_field=DecimalField()
            ),
            amount=ExpressionWrapper(
                Sum((F('ist_hours') - F('soll_hours')) * F('employee__hourly_rate')),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            )
        ).order_by('employee__first_name', 'employee__last_name')

        # Berechne Summen
        total_income = sum(
            income['total']
            for income in grouped_income.values()
        )

        # Berechne die Gesamtausgaben
        total_expenses = (
            sum(a['amount'] for a in assistant_expenses) +  # Summe aller Assistenten
            sum(c['amount'] for c in cleaning_expenses) +   # Summe aller Reinigungskräfte
            sum(o['amount'] for o in overtime_expenses)     # Summe aller Überstunden
        )

        context.update({
            'grouped_income': grouped_income.values(),
            'assistant_expenses': assistant_expenses,
            'cleaning_expenses': cleaning_expenses,
            'overtime_expenses': overtime_expenses,
            'total_income': total_income,
            'total_expenses': total_expenses,
            'current_date': current_date,
            'month_name': current_date.strftime('%B %Y'),
            'prev_month': (current_date - relativedelta(months=1)),
            'next_month': (current_date + relativedelta(months=1))
        })
        
        return context

@login_required
def api_mark_extra_hours_as_paid(request):
    if request.user.role != 'OWNER':
        return JsonResponse({'success': False, 'error': _('Keine Berechtigung')})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': _('Ungültige Anfrage')})
    
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
            actual_hours__gt=F('booked_hours'),
            extra_hours_payment_status='PENDING'
        ).update(
            extra_hours_payment_status='PAID',
            payment_date=timezone.now().date()
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
                    'error': _('Für diesen Tag wurde bereits ein Eintrag erstellt')
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
            'extra_hours_payment_status': booking.extra_hours_payment_status
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
