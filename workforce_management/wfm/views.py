from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView, View, TemplateView, DeleteView
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext_lazy as gettext  # Umbenennen zu gettext statt _
from .models import (
    WorkingHours, 
    Vacation, 
    VacationEntitlement, 
    SickLeave,
    ScheduleTemplate,
    # TimeCompensation,
    TherapistBooking,
    TherapistScheduleTemplate,
    CustomUser,
    OvertimeAccount,
    ClosureDay,
    UserDocument,
    OvertimeEntry,
    MonthlyWage,
    OvertimePayment,
)
from .forms import UserDocumentForm, WorkingHoursForm, VacationRequestForm
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
from django.core.exceptions import ValidationError
import decimal

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
        year = int(self.request.GET.get('year', today.year))
        month = int(self.request.GET.get('month', today.month))
        
        # 2. Erstelle Datum für Navigation
        current_date = date(year, month, 1)
        prev_month_date = (current_date - timedelta(days=1)).replace(day=1)
        next_month_date = (current_date + timedelta(days=32)).replace(day=1)

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

        # Füge die Mitarbeiterliste für das Add-Modal hinzu (für Owner)
        if self.request.user.role == 'OWNER':
            context['modal_employees'] = CustomUser.objects.filter(
                role__in=['ASSISTANT', 'CLEANING']
            ).order_by('first_name', 'last_name')

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

        # 5. Erstelle Liste aller Tage im Monat
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
                    valid_from__lte=day
                ).order_by('-valid_from').first()
                if template:
                    schedules.append(template)

        vacations = Vacation.objects.filter(
            employee__in=employees,
            start_date__lte=current_date + timedelta(days=31),
            end_date__gte=current_date,
            status__in=['REQUESTED', 'APPROVED']
        ).select_related('employee')

        sick_leaves = SickLeave.objects.filter(
            employee__in=employees,
            start_date__lte=current_date + timedelta(days=31),
            end_date__gte=current_date
        ).select_related('employee')

        # Initialisiere die Summen vor der Schleife
        total_soll = 0  # Diese werden noch für die Tagesansicht benötigt
        total_ist = 0   # Diese werden noch für die Tagesansicht benötigt
        # total_diff = 0  # Diese Variable können wir löschen

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
                    # 'time_comp': None,
                    'sick_leave': None,
                    'closure': closure,
                    'soll_hours': 0,
                    'ist_hours': 0,
                    'ist_hours_value': 0,
                    'difference_value': 0,
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
                    # 'time_comp': None,
                    'sick_leave': None,
                    'closure': None,
                    'soll_hours': 0,
                    'ist_hours': 0,
                    'ist_hours_value': 0,
                    'difference_value': 0,
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
                    has_sick_leave = next((sl for sl in sick_leaves 
                        if sl.employee_id == employee.id and 
                        sl.start_date <= day <= sl.end_date), None)

                    # Nur wenn es tatsächlich Einträge gibt oder ein Schedule existiert
                    if has_working_hours or has_schedule or has_vacation or has_sick_leave:
                        entry = {
                            'employee': employee,
                            'date': day,
                            'weekday': day.strftime('%A'),
                            'ist_hours': '--:--',  # Default Anzeige
                            'ist_hours_value': 0,  # Default numerischer Wert
                            'difference_value': 0,
                            'soll_hours': None,
                            'schedule': has_schedule,
                            'working_hours': has_working_hours,
                            'closure': None,
                            'sick_leave': has_sick_leave,
                            'vacation': has_vacation,
                            'is_weekend': False,
                            'break_minutes': int(has_working_hours.break_duration.total_seconds() / 60) if has_working_hours and has_working_hours.break_duration else None
                        }

                        # Berechne Stunden nur für die Tagesansicht
                        if has_schedule:
                            entry['schedule'] = has_schedule
                            start = datetime.combine(date.min, has_schedule.start_time)
                            end = datetime.combine(date.min, has_schedule.end_time)
                            duration = end - start  # Berechne duration hier
                            if has_schedule.break_duration:
                                entry['break_minutes'] = int(has_schedule.break_duration.total_seconds() / 60)
                                duration = duration - has_schedule.break_duration  # Ziehe Pause von duration ab
                            else:
                                entry['break_minutes'] = None
                            
                            entry['soll_hours'] = duration.total_seconds() / 3600
                            total_soll += entry['soll_hours']


                        if has_working_hours:
                            start = datetime.combine(date.min, has_working_hours.start_time)
                            end = datetime.combine(date.min, has_working_hours.end_time)
                            entry['ist_hours'] = f"{has_working_hours.start_time.strftime('%H:%M')}-{has_working_hours.end_time.strftime('%H:%M')}"
                            entry['ist_hours_value'] = (end - start).total_seconds() / 3600
                            if has_working_hours.break_duration:
                                entry['ist_hours_value'] -= has_working_hours.break_duration.total_seconds() / 3600
                            
                            # Addiere immer die ist_hours_value (auch wenn 0)
                            total_ist += entry['ist_hours_value']

                            #Wenn Ist-Stunden gelöscht werden anstatt verändert werden
                        elif has_schedule and not has_working_hours:
                            entry['ist_hours'] = '--:--'  # Zeige --:-- wenn Schedule aber keine Ist-Stunden
                            entry['ist_hours_value'] = 0
                            
                            
                            total_ist += entry['ist_hours_value']
                        else:
                            entry['ist_hours'] = ''  # Leerer String wenn kein Schedule
                            entry['ist_hours_value'] = 0
                            total_ist += entry['ist_hours_value']

                        # Berechne die Differenz nur wenn ein Schedule Template existiert und beide Werte vorhanden sind
                        if entry.get('schedule') and entry['ist_hours_value'] is not None and entry['soll_hours'] is not None:
                            entry['difference_value'] = entry['ist_hours_value'] - entry['soll_hours']
                        else:
                            entry['difference_value'] = None
                        print(entry['difference_value'])
                        day_entries.append(entry)

                # Wenn keine Einträge für diesen Tag existieren, füge einen leeren Tag hinzu
                if not day_entries:
                    entry = {
                        'date': day,
                        'employee': None,
                        'working_hours': None,
                        'schedule': None,
                        'vacation': None,
                        # 'time_comp': None,
                        'sick_leave': None,
                        'closure': None,
                        'soll_hours': 0,
                        'ist_hours': 0,
                        'ist_hours_value': 0,
                        'difference_value': 0,
                        'difference': 0,
                        'is_weekend': False
                    }
                    days_data.append(entry)
                else:
                    days_data.extend(day_entries)


        



        # 9. Hole die Gesamtbilanz für jeden Mitarbeiter
        employee_balances = {}
        total_balance = Decimal('0')
        
        # Erstelle ein Dictionary mit allen Mitarbeitern für das Template
        employees_dict = {str(emp.id): emp for emp in employees}
        context['employees'] = employees_dict  # Füge das Dictionary zum Context hinzu
        
        if self.request.user.role == 'OWNER':
            for employee in employees:
                if employee.role == 'ASSISTANT' or employee.role == 'CLEANING':
                    balance = OvertimeAccount.get_current_balance(employee)
                    employee_balances[str(employee.id)] = balance
            total_balance = sum(employee_balances.values())
        else:
            # Für normale Nutzer nur die eigene Balance
            total_balance = OvertimeAccount.get_current_balance(self.request.user)
            employee_balances[str(self.request.user.id)] = total_balance

        # Hole die Überstunden für den angezeigten Monat
        total_monthly_overtime = Decimal('0')
        for employee in employees:
            # Summiere die Überstunden des Monats
            monthly_entries = OvertimeEntry.objects.filter(
                employee=employee,
                date__year=year,
                date__month=month
            ).aggregate(total=models.Sum('hours'))['total'] or Decimal('0')
            total_monthly_overtime += monthly_entries

        # Berechne den Monatslohn für jeden Mitarbeiter
        monthly_salaries = {}  # Dictionary für alle Mitarbeiter-Gehälter
        total_monthly_salary = Decimal('0')

        

        # Hole oder erstelle MonthlyWage Einträge
        monthly_wages = {}
        total_monthly_wage = Decimal('0')

        for employee in employees:
            monthly_wage, created = MonthlyWage.objects.get_or_create(
                employee=employee,
                year=year,
                month=month
            )
            if created or monthly_wage.updated_at.date() < timezone.now().date():
                monthly_wage.calculate_wage()
            
            monthly_wages[employee.id] = monthly_wage.wage
            total_monthly_wage += monthly_wage.wage

        # Initialisiere die Dictionaries für die Summen pro Mitarbeiter
        total_soll_per_employee = {}
        total_ist_per_employee = {}
        monthly_wages_per_employee = {}



        # Berechne die Summen für jeden Mitarbeiter
        for employee_id, balance in employee_balances.items():
            total_soll = Decimal('0')
            total_ist = Decimal('0')
            
            # Hole das MonthlyWage für diesen Mitarbeiter
            monthly_wage = MonthlyWage.objects.filter(
                employee_id=employee_id,
                year=year,
                month=month
            ).first()
            
            # Speichere das Gehalt (oder 0 wenn keins gefunden)
            monthly_wages_per_employee[employee_id] = monthly_wage.wage if monthly_wage else Decimal('0')
            
            print(f"\nMitarbeiter ID: {employee_id}")
            
            # Filtere die Einträge für diesen Mitarbeiter
            employee_entries = [
                entry for entry in days_data 
                if entry.get('employee') and str(entry['employee'].id) == str(employee_id)
            ]

            
            # Berechne die Summen für diesen Mitarbeiter
            for entry in employee_entries:
                soll = Decimal(str(entry.get('soll_hours', 0) or 0))
                ist = Decimal(str(entry.get('ist_hours_value', 0) or 0))
                total_soll += soll
                total_ist += ist
                print(f"Eintrag - Soll: {soll}, Ist: {ist}")
            
            # Speichere die Summen für diesen Mitarbeiter
            total_soll_per_employee[employee_id] = total_soll
            total_ist_per_employee[employee_id] = total_ist
            print(f"Summen - Soll: {total_soll}, Ist: {total_ist}")



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
            'total_soll': total_soll,  # Wird noch für die Tagesansicht benötigt
            'total_ist': total_ist,    # Wird noch für die Tagesansicht benötigt
            'total_diff': total_monthly_overtime,  # Jetzt aus OvertimeEntries
            'employee_balances': employee_balances,  # Einzelbilanzen pro Mitarbeiter
            'total_balance': total_balance,  # Gesamtbilanz aller gefilterten Mitarbeiter
            'monthly_wages': monthly_wages,
            'total_monthly_wage': total_monthly_wage,
            'colors': {
                'primary': '#90BE6D',    # Pistachio
                'secondary': '#577590',   # Queen Blue
                'success': '#43AA8B',     # Zomp
                'warning': '#F9C74F',     # Maize Crayola
                'info': '#577590',        # Queen Blue
                'danger': '#F94144',      # Red Salsa
                'orange': '#F3722C',      # Orange Red
                'yellow': '#F8961E',      # Yellow Orange
            },
            'total_soll_per_employee': total_soll_per_employee,
            'total_ist_per_employee': total_ist_per_employee,
            'monthly_wages_per_employee': monthly_wages_per_employee,  # Neu
        })

        # Debug-Ausgaben

        for employee_id, balance in employee_balances.items():
            employee = employees_dict[employee_id]
            print(f"\nMitarbeiter: {employee.get_full_name()}")
            print(f"Gesamtbilanz: {balance:+.2f}h")
            
            # Zeige monatliche Überstunden
            monthly = OvertimeEntry.objects.filter(
                employee=employee,
                date__year=year,
                date__month=month
            ).aggregate(total=models.Sum('hours'))['total'] or Decimal('0')
            print(f"Monatliche Überstunden: {monthly:+.2f}h")
            
            # Zeige gesperrte/zur Auszahlung markierte Stunden
            locked = OvertimeEntry.objects.filter(
                employee=employee,
                is_locked=True
            ).aggregate(total=models.Sum('hours'))['total'] or Decimal('0')
            print(f"Gesperrte Stunden: {locked:+.2f}h")


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
    fields = ['start_time', 'end_time', 'break_duration', 'notes']
    template_name = 'wfm/modals/working_hours_modal_add.html'
    
    def dispatch(self, request, *args, **kwargs):
        # Prüfe ob bereits ein Eintrag für diesen Tag existiert
        date_str = self.kwargs['date']
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        existing_entry = WorkingHours.objects.filter(
            employee=request.user,
            date=date_obj
        ).exists()
        
        if existing_entry and request.user.role != 'OWNER':
            return JsonResponse({
                'success': False,
                'error': 'Für diesen Tag existiert bereits ein Eintrag'
            }, status=403)
            
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.role == 'OWNER':
            context['modal_employees'] = CustomUser.objects.filter(
                role__in=['ASSISTANT', 'CLEANING']
            ).order_by('first_name', 'last_name')
        return context

    def form_valid(self, form):
        # Setze den Mitarbeiter
        if self.request.user.role == 'OWNER' and 'employee' in self.request.POST:
            form.instance.employee = get_object_or_404(
                CustomUser, 
                id=self.request.POST['employee']
            )
        else:
            form.instance.employee = self.request.user  # Korrekte Einrückung nach else
            
        # Konvertiere das Datum aus der URL in ein date-Objekt
        date_str = self.kwargs['date']
        form.instance.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Speichere das Objekt ohne redirect
        self.object = form.save()
        
        return JsonResponse({
            'success': True,
            'id': self.object.id,
            'employee_id': self.object.employee.id
        })
    
    def form_invalid(self, form):
        return JsonResponse({
            'success': False,
            'error': form.errors
        })

class WorkingHoursUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = WorkingHours
    fields = ['start_time', 'end_time', 'break_duration', 'notes']
    template_name = 'wfm/modals/working_hours_modal_edit.html'
    
    def test_func(self):
        obj = self.get_object()
        return self.request.user.role == 'OWNER' or obj.employee == self.request.user
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.role == 'OWNER':
            context['modal_employees'] = CustomUser.objects.filter(
                role__in=['ASSISTANT', 'CLEANING']
            ).order_by('first_name', 'last_name')
        return context

    def form_valid(self, form):
        if self.request.user.role == 'OWNER' and 'employee' in self.request.POST:
            form.instance.employee = get_object_or_404(
                CustomUser, 
                id=self.request.POST['employee']
            )
        
        # Speichere das Objekt ohne redirect
        self.object = form.save()
        
        return JsonResponse({
            'success': True,
            'id': self.object.id,
            'employee_id': self.object.employee.id
        })
    
    def form_invalid(self, form):
        return JsonResponse({
            'success': False,
            'error': form.errors
        })

class OvertimeOverviewView(LoginRequiredMixin, View):
    template_name = 'wfm/overtime_overview.html'

    def get(self, request):
        try:
            today = timezone.now().date()
        
            # Bestimme den relevanten Monat für die Überstunden
            if today.day <= 7:
                target_date = today - relativedelta(months=1)
            else:
                target_date = today
                
            year = target_date.year
            month = target_date.month
            
            # Hole die aktuelle Gesamtbilanz
            total_balance = OvertimeAccount.get_current_balance(request.user)
        
            # Hole die Summe aller nicht bezahlten markierten Stunden
            marked_hours = OvertimePayment.objects.filter(
            employee=request.user,
                is_paid=False
            ).aggregate(
                total=Coalesce(Sum('hours_for_payment'), Decimal('0'))
            )['total']

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                            'balance': float(total_balance),
                            'hours_for_payment': float(marked_hours),
                            'remaining_balance': float(total_balance - marked_hours)
                })
                
            context = {
                        'balance': total_balance,
                        'hours_for_payment': marked_hours,
                        'remaining_balance': total_balance - marked_hours,
                'month_name': target_date.strftime('%B %Y')
            }
            
            return render(request, self.template_name, context)
            
        except Exception as e:
            logger.error(f"Overtime overview error: {str(e)}", exc_info=True)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                }, status=500)
            raise

    def post(self, request):
        try:
            if request.user.role not in ['ASSISTANT', 'CLEANING']:
                raise PermissionDenied
            
            data = json.loads(request.body)
            hours_for_payment = Decimal(str(data.get('hours_for_payment', 0)))
            
            # Hole die aktuelle Gesamtbilanz
            total_balance = OvertimeAccount.get_current_balance(request.user)
            
            if hours_for_payment > total_balance:
                return JsonResponse({
                    'success': False,
                    'error': gettext('Nicht genügend Überstunden verfügbar')
                })

            # Hole oder erstelle den OvertimePayment-Eintrag
            payment = OvertimePayment.objects.filter(
                employee=request.user,
                is_paid=False
            ).first()

            # Speichere die alten Stunden für die Differenzberechnung
            old_hours = payment.hours_for_payment if payment else Decimal('0')

            if not payment:
                payment = OvertimePayment(
                    employee=request.user,
                    hours_for_payment=hours_for_payment,
                    is_paid=False,
                    paid_date=None
                )
                # Berechne den Betrag vor dem Speichern
                payment.calculate_amount()
            else:
                payment.hours_for_payment = hours_for_payment
                payment.calculate_amount()
                payment.paid_date = None
            
            payment.save()

            # Berechne die Differenz und aktualisiere die Balance
            hours_difference = hours_for_payment - old_hours
            
            # Hole das aktuelle Überstundenkonto
            today = timezone.now().date()
            current_account = OvertimeAccount.objects.filter(
                employee=request.user,
                year=today.year,
                month=today.month
            ).first()
            
            if current_account:
                current_account.balance -= hours_difference
                current_account.save()
            
            # Aktualisiere die Gesamtbilanz für die Antwort
            new_total_balance = OvertimeAccount.get_current_balance(request.user)
            
            return JsonResponse({
                'success': True,
                'balance': float(new_total_balance),
                'hours_for_payment': float(payment.hours_for_payment)
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
            # time_compensation = TimeCompensation.objects.filter(
            #     employee=self.request.user,
            #     date=date
            # ).first()
            
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
                # 'time_compensation': time_compensation,
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
        # used_compensation = TimeCompensation.objects.filter(
        #     employee=self.request.user
        # ).aggregate(
        #     total=Sum('hours')
        # )['total'] or Decimal('0')

        # Verfügbarer Zeitausgleich
        # available_overtime = total_overtime - used_compensation
        
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

# class TimeCompensationCreateView(LoginRequiredMixin, CreateView):
#     model = TimeCompensation
#     form_class = TimeCompensationForm
#     template_name = 'wfm/time_compensation_form.html'
#     success_url = reverse_lazy('wfm:monthly-overview')

#     def get_form_kwargs(self):
#         kwargs = super().get_form_kwargs()
#         date = self.request.GET.get('date')
        
#         if date:
#             if 'initial' not in kwargs:
#                 kwargs['initial'] = {}
#             kwargs['initial']['date'] = datetime.strptime(date, '%Y-%m-%d').date()
#         return kwargs

#     def form_valid(self, form):
#         form.instance.employee = self.request.user
#         if 'selected_date' in self.request.session:
#             del self.request.session['selected_date']
#         return super().form_valid(form)

# class TimeCompensationUpdateView(LoginRequiredMixin, UpdateView):
#     model = TimeCompensation
#     form_class = TimeCompensationForm
#     template_name = 'wfm/time_compensation_form.html'
#     success_url = reverse_lazy('wfm:monthly-overview')

#     def get_queryset(self):
#         return TimeCompensation.objects.filter(employee=self.request.user)

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
def add_working_hours(request, date=None):
    """API-Endpoint zum Hinzufügen neuer Arbeitszeiten"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
            
            # Konvertiere den Datums-String in ein date-Objekt
            date_obj = datetime.strptime(date, '%Y-%m-%d').date()
            
            # Konvertiere die Zeitstrings in time-Objekte
            start_time = datetime.strptime(data['start_time'], '%H:%M').time()
            end_time = datetime.strptime(data['end_time'], '%H:%M').time()
            
            # Bestimme den Mitarbeiter
            if request.user.role == 'OWNER' and 'employee' in data:
                employee = get_object_or_404(CustomUser, id=data['employee'])
            else:
                employee = request.user
            
            # Erstelle den Eintrag
            working_hours = WorkingHours.objects.create(
                employee=employee,
                date=date_obj,
                start_time=start_time,
                end_time=end_time,
                break_duration=timedelta(minutes=int(data['break_duration'])),
                notes=data.get('notes', '')
            )
            
            return JsonResponse({
                'success': True,
                'id': working_hours.id,
                'employee_id': employee.id
            })
            
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

# @login_required
# def api_time_compensation_request(request):
#     """API-Endpunkt für Zeitausgleichsanträge"""
#     if request.method == 'POST':
#         try:
#             data = json.loads(request.body)
            
#             # Validiere die Daten
#             if not data.get('date'):
#                 return JsonResponse({
#                     'success': False,
#                     'error': 'Bitte Datum angeben'
#                 })

#             # Parse date
#             date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            
#             # Prüfe verfügbare Stunden
#             current_year = timezone.now().year
#             total_hours = calculate_overtime_hours(request.user, current_year)
            
#             used_hours = TimeCompensation.objects.filter(
#                 employee=request.user,
#                 date__year=current_year,
#                 status='APPROVED'
#             ).count() * 8  # 8 Stunden pro Tag
            
#             remaining_hours = total_hours - used_hours
            
#             if remaining_hours < 8:  # Standard-Arbeitstag
#                 return JsonResponse({
#                     'success': False,
#                     'error': f'Nicht genügend Überstunden verfügbar. Verfügbar: {remaining_hours:.1f}h'
#                 })

#             # Erstelle den Zeitausgleichsantrag
#             time_comp = TimeCompensation.objects.create(
#                 employee=request.user,
#                 date=date,
#                 notes=data.get('notes', ''),
#                 status='REQUESTED'
#             )
            
#             return JsonResponse({'success': True})
            
#         except Exception as e:
#             logger.error(f"Time compensation request error: {str(e)}", exc_info=True)
#             return JsonResponse({
#                 'success': False,
#                 'error': str(e)
#             })
    
#     return JsonResponse({
#         'success': False,
#         'error': 'Ungültige Anfrage'
#     }, status=400)

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
                    is_paid=False
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
            'CLEANING': 'wfm/dashboards/assistant_dashboard.html',
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
            # context['pending_time_compensations'] = TimeCompensation.objects.filter(status='PENDING').count()
            context['pending_sick_leaves'] = SickLeave.objects.filter(status='PENDING').count()
            context['pending_therapist_bookings'] = TherapistBooking.objects.filter(is_paid=False).count()

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
                'break_duration': working_hours.break_duration.seconds // 60,
                'notes': working_hours.notes or ''
            })
    
    return JsonResponse({'error': 'Invalid request'}, status=400)

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

@method_decorator(login_required, name='dispatch')
class TherapistCalendarView(LoginRequiredMixin, TemplateView):
    template_name = 'wfm/therapist_calendar.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get current month/year für Navigation
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
            'next_month': (current_date + relativedelta(months=1)),
        })

        # Füge Therapeuten-Filter hinzu für Owner
        if self.request.user.role == 'OWNER':
            context['therapists'] = CustomUser.objects.filter(
                role='THERAPIST'
            ).order_by('first_name', 'last_name')
            
        # Hole den ausgewählten Therapeuten
        therapist_id = self.request.GET.get('therapist')
        if therapist_id:
            context['selected_therapist'] = CustomUser.objects.filter(
                id=therapist_id
            ).first()

        return context

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
            status__in=['APPROVED', 'REQUESTED'],
            **employee_filter
        ).select_related('employee')

        events.extend([{
            'title': f"{v.employee.get_full_name()} - Urlaub {gettext('(Beantragt)') if v.status == 'REQUESTED' else ''}",
            'start': v.start_date.isoformat(),
            'end': (v.end_date + timedelta(days=1)).isoformat(),
            'backgroundColor': v.employee.color,
            'className': 'vacation-event',
                        'type': 'vacation',
                        'allDay': True
        } for v in vacations])
        

            
        # # Zeitausgleich
        # time_comps = TimeCompensation.objects.filter(
        #     date__lte=end_date.date(),
        #     date__gte=start_date.date(),
        #     status='APPROVED',
        #     **employee_filter
        # ).select_related('employee')
        
        # events.extend([{
        #     'title': f"{tc.employee.get_full_name()} - Zeitausgleich",
        #     'start': tc.date.isoformat(),
        #     'end': (tc.date + timedelta(days=1)).isoformat(),
        #     'backgroundColor': tc.employee.color,
        #     'className': 'time-comp-event',
        #     'type': 'time_comp',
        #     'allDay': True
        # } for tc in time_comps])
        
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
                'title': f"{wh.employee.get_full_name()}",
                'start': f"{wh.date}T{wh.start_time}" if wh.start_time else wh.date.isoformat(),
                'end': f"{wh.date}T{wh.end_time}" if wh.end_time else wh.date.isoformat(),
                'backgroundColor': wh.employee.color,
                'className': 'working-hours-event',
                'extendedProps': {  # Füge extendedProps hinzu
                    'type': 'working_hours',
                    'employee_id': wh.employee.id,
                    'allDay': not (wh.start_time and wh.end_time)
                }
            } for wh in working_hours])

            return JsonResponse(events, safe=False)



# class TimeCompensationListView(LoginRequiredMixin, ListView):
#     model = TimeCompensation
#     template_name = 'wfm/time_compensation_list.html'
#     context_object_name = 'time_compensations'

#     def get_queryset(self):
#         queryset = TimeCompensation.objects.select_related('employee')
        
#         if self.request.user.role != 'OWNER':
#             queryset = queryset.filter(employee=self.request.user)
            
#         return queryset.order_by('-date')

#     def get_context_data(self, **kwargs):
#         context = super().get_context_data(**kwargs)
#         if self.request.user.role == 'OWNER':
#             context['employees'] = CustomUser.objects.exclude(role='OWNER')
#         return context

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
        
        # Hole nur genehmigte oder beantragte Urlaube für den Kalender
        vacations = Vacation.objects.filter(
            status__in=['APPROVED', 'REQUESTED']
        ).select_related('employee')
        
        context['vacations'] = vacations

        # # Formatiere die Urlaube für den Kalender
        # vacation_events = []
        # for vacation in vacations:
        #     status_text = gettext("Beantragt") if vacation.status == 'REQUESTED' else ""
        #     vacation_events.append({
        #         'id': f'vacation_{vacation.id}',
        #         'title': f'{vacation.employee.get_full_name()} {status_text}',
        #         'start': vacation.start_date.isoformat(),
        #         'end': (vacation.end_date + timedelta(days=1)).isoformat(),
        #         'className': 'bg-warning' if vacation.status == 'REQUESTED' else 'bg-success',
        #         'type': 'vacation'
        #     })
            
        # context['events'] = vacation_events

        # # Hole genehmigte und beantragte Urlaube
        # vacations = Vacation.objects.filter(
        #     status__in=['APPROVED', 'REQUESTED']
        # ).select_related('employee')
        
        # # Formatiere die Urlaube für den Kalender
        # events = []
        # for vacation in vacations:
        #     status_text = gettext("Beantragt") if vacation.status == 'REQUESTED' else ""
        #     events.append({
        #         'id': f'vacation_{vacation.id}',
        #         'title': f"{vacation.employee.get_full_name()} - Urlaub {status_text}",
        #         'start': vacation.start_date.isoformat(),
        #         'end': (vacation.end_date + timedelta(days=1)).isoformat(),
        #         'className': 'bg-warning' if vacation.status == 'REQUESTED' else 'bg-success',
        #         'type': 'vacation',
        #         'allDay': True
        #     })
        
        # context['events'] = events
        return context

    def get_events(self, request, *args, **kwargs):
        # Debug prints
        print("\nDEBUG: AssistantCalendarView.get_events called")
        print("DEBUG: Request path:", request.path)
        print("DEBUG: Request GET params:", request.GET)
        
        start_date = parse_datetime(request.GET.get('start'))
        end_date = parse_datetime(request.GET.get('end'))
        show_absences_only = request.GET.get('absences') == '1'
        
        print(f"DEBUG: Parsed dates - start: {start_date}, end: {end_date}")
        
        employee_id = request.GET.get('employee')
        role = request.GET.get('role')
        
        employee_filter = {}
        if employee_id:
            employee_filter['employee_id'] = employee_id
        if role:
            employee_filter['employee__role'] = role

        # Debug: Print filter
        print("DEBUG: Employee filter:", employee_filter)
        
        if show_absences_only:
            events = []
            
             # # Zeitausgleich
            # time_comps = TimeCompensation.objects.filter(
            #     date__lte=end_date.date(),
            #     date__gte=start_date.date(),
            #     status='APPROVED',
            #     **employee_filter
            # ).select_related('employee')
            
            # events.extend([{
            #     'title': f"{tc.employee.get_full_name()} - Zeitausgleich",
            #     'start': tc.date.isoformat(),
            #     'end': (tc.date + timedelta(days=1)).isoformat(),
            #     'className': 'time-comp-event',
            #     'type': 'time_comp',
            #     'allDay': True
            # } for tc in time_comps])

            # Debug: Print query parameters
            print("DEBUG: Vacation query params:", {
                'start_date__lte': end_date.date(),
                'end_date__gte': start_date.date(),
                'status__in': ['APPROVED', 'REQUESTED'],
                **employee_filter
            })
            
            # Urlaube (genehmigte und beantragte)
            vacations = Vacation.objects.filter(
                start_date__lte=end_date.date(),
                end_date__gte=start_date.date(),
                status__in=['APPROVED', 'REQUESTED'],
                **employee_filter
            ).select_related('employee')
            
            # Debug: Print found vacations
            print("DEBUG: Found vacations:", list(vacations.values('id', 'employee__username', 'start_date', 'end_date', 'status')))

            for vacation in vacations:
                status_text = gettext("Beantragt") if vacation.status == 'REQUESTED' else ""
                event = {
                    'id': f'vacation_{vacation.id}',
                    'title': f"{vacation.employee.get_full_name()} - Urlaub {status_text}",
                    'start': vacation.start_date.isoformat(),
                    'end': (vacation.end_date + timedelta(days=1)).isoformat(),
                    'className': 'bg-warning' if vacation.status == 'REQUESTED' else 'bg-success',
                'type': 'vacation',
                'allDay': True
                }
                events.append(event)
                # Debug: Print created event
                print("DEBUG: Created event:", event)

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
                        # Debug: Print final events list
            print("DEBUG: Final events list:", events)
            
            return JsonResponse(events, safe=False)
        else:
            # Debug: Print branch taken
            print("DEBUG: Taking regular events branch")
            return self.get_regular_events(request, start_date, end_date)

class TherapistBookingListView(LoginRequiredMixin, ListView):
    template_name = 'wfm/therapist_booking_list.html'
    model = TherapistBooking
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
        
        # Hole alle Schließtage für den aktuellen Monat
        closure_days = ClosureDay.objects.filter(
            date__year=int(year),
            date__month=int(month)
        )
        
        # Erstelle ein Dictionary mit Schließtagen
        closure_dict = {closure.date: closure for closure in closure_days}
        
        # Füge Schließtage-Info zu den Buchungen hinzu
        bookings = list(context['bookings'])
        modified_bookings = []
        
        for booking in bookings:
            if booking.date in closure_dict:
                # Wenn es ein Schließtag ist, erstelle ein "Pseudo-Booking" mit den Schließtag-Informationen
                closure = closure_dict[booking.date]
                booking.is_closure = True
                booking.closure_info = closure
                booking.title = f"{closure.get_type_display()}: {closure.name}"
            modified_bookings.append(booking)
        
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
        is_paid = False    # Default Status bleibt PENDING

        for booking in modified_bookings:
            if not hasattr(booking, 'is_closure'):  # Nur echte Buchungen berücksichtigen
                if booking.actual_hours:
                    total_actual_hours += booking.actual_hours

                if booking.hours and booking.therapist.room_rate:
                    total_booked_amount += booking.hours * booking.therapist.room_rate
                
                if booking.difference_hours and booking.therapist.room_rate:
                    total_extra_hours += booking.difference_hours
                    extra_costs += booking.difference_hours * booking.therapist.room_rate
                    if booking.is_paid:
                        is_paid = True

            total_sum = total_booked_amount + extra_costs

        context['bookings'] = modified_bookings
        context['totals'] = {
            'total_actual_hours': total_actual_hours,
            'total_extra_hours': total_extra_hours,
            'total_booked_amount': total_booked_amount,
            'extra_costs': extra_costs,
            'total_sum': total_sum,
            'is_paid': is_paid
        }

        # Füge Therapeuten für Filter hinzu (nur für Owner)
        if self.request.user.role == 'OWNER':
            context['therapists'] = CustomUser.objects.filter(role='THERAPIST').order_by('first_name', 'last_name')

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
            if 'is_paid' in data and booking.difference_hours:
                booking.is_paid = data['is_paid']
                if data['is_paid']:
                    booking.paid_date = timezone.now().date()
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
                'is_paid': booking.is_paid
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

    def get_queryset(self):
        # Verwende select_related wie in der SickLeaveManagementView
        return SickLeave.objects.filter(
            employee=self.request.user
        ).select_related('employee', 'document').order_by('-start_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.now().date()
        
        # Hole die Urlaubsanträge und berechne die Stunden
        vacations = Vacation.objects.filter(
            employee=user
        ).order_by('-start_date')
        
        # Berechne die Stunden für jeden Urlaub
        for vacation in vacations:
            vacation.hours = vacation.calculate_vacation_hours()
        
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
            last_year_entitlement = VacationEntitlement.objects.filter(
                employee=user,
                year=last_year
            ).first()
            
            last_year_remaining = Decimal('0')
            if last_year_entitlement:
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
            
            context['vacation_info'] = {
                'year': today.year,
                'entitlement': entitlement.total_hours,
                'carried_over': last_year_remaining,
                'total_available': total_available,
                'approved_hours': approved_hours,
                'pending_hours': pending_hours,
                'pending_hours_percent': pending_hours / (total_available - approved_hours) * 100,
                'remaining_hours': total_available - approved_hours,
                'remaining_hours_minus_pending': total_available - approved_hours - pending_hours,
                'approved_percent': (approved_hours / total_available * 100) if total_available > 0 else 0,
                'pending_percent': (pending_hours / total_available * 100) if total_available > 0 else 0,
                'remaining_percent': (
                    ((total_available - approved_hours - pending_hours) / total_available * 100) 
                    if total_available > 0 else 0
                ),
            }

        context['vacations'] = vacations
        # context['time_comps'] = TimeCompensation.objects.filter(employee=user).order_by('-date')
        
        # # Zeitausgleich-Info für Assistenten und Reinigungskräfte
        # if user.role in ['ASSISTANT', 'CLEANING']:
        #     context['timecomp_info'] = self.get_timecomp_info(user)

        # Für das Upload-Modal
        context['users'] = [user]
        
        return context

    # def get_timecomp_info(self, user):
    #     # Berechne Überstunden für das aktuelle Jahr
    #     total_overtime = Decimal('0')
    #     for month in range(1, 13):
    #         overtime_account = OvertimeAccount.objects.filter(
    #             employee=user,
    #             year=date.today().year,
    #             month=month,
    #             is_finalized=True
    #         ).first()
    #         if overtime_account:
    #             total_overtime += overtime_account.hours_for_timecomp

    #     # Bereits genommener Zeitausgleich
    #     approved_timecomp = TimeCompensation.objects.filter(
    #         employee=user,
    #         date__year=date.today().year,
    #         status='APPROVED'
    #     )
    #     approved_timecomp_hours = sum(tc.hours for tc in approved_timecomp)

    #     # Beantragter Zeitausgleich
    #     pending_timecomp = TimeCompensation.objects.filter(
    #         employee=user,
    #         date__year=date.today().year,
    #         status='REQUESTED'
    #     )
    #     pending_timecomp_hours = sum(tc.hours for tc in pending_timecomp)

    #     return {
    #         'year': date.today().year,
    #         'total_hours': total_overtime,
    #         'approved_hours': approved_timecomp_hours,
    #         'pending_hours': pending_timecomp_hours,
    #         'remaining_hours': total_overtime - approved_timecomp_hours
    #     }

@login_required
def api_delete_absence(request, type, pk):
    """API zum Löschen von Abwesenheiten"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
        
    try:
        # Wähle das richtige Model basierend auf dem Typ
        if type == 'vacation':
            model = Vacation
        # elif type == 'time_comp':
        #     model = TimeCompensation
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

# @login_required
# def api_time_compensation_status(request):
#     """API-Endpunkt für den aktuellen Zeitausgleichsstatus"""
#     try:
#         today = timezone.now().date()
        
#         # Hole den relevanten Monat
#         if today.day <= 7:
#             target_date = today - relativedelta(months=1)
#         else:
#             target_date = today
            
#         # Hole das Überstundenkonto für diesen Monat
#         overtime_account = OvertimeAccount.objects.filter(
#             employee=request.user,
#             year=target_date.year,
#             month=target_date.month
#         ).first()
        
#         if overtime_account:
#             total_hours = overtime_account.hours_for_timecomp
#         else:
#             total_hours = 0
        
#         # Hole genehmigte und beantragte Zeitausgleiche
#         approved_time_comps = TimeCompensation.objects.filter(
#             employee=request.user,
#             status='APPROVED'
#         )
        
#         pending_time_comps = TimeCompensation.objects.filter(
#             employee=request.user,
#             status='REQUESTED'
#         )
        
#         # Berechne die Stunden
#         used_hours = sum(tc.hours for tc in approved_time_comps)
#         pending_hours = sum(tc.hours for tc in pending_time_comps)
#         remaining_hours = total_hours - used_hours
        
#         return JsonResponse({
#             'total_hours': float(total_hours),
#             'used_hours': float(used_hours),
#             'pending_hours': float(pending_hours),
#             'remaining_hours': float(remaining_hours)
#         })
        
#     except Exception as e:
#         logger.error(f"Time compensation status error: {str(e)}", exc_info=True)
#         return JsonResponse({'error': str(e)}, status=500)

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
        # Hole alle Urlaubsanträge (auch abgelehnte)
        vacations = Vacation.objects.all().select_related('employee')
        
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
                'is_vacation': True,
                'rejection_reason': vacation.notes if vacation.status == 'REJECTED' else None
            })
            
        # for time_comp in time_comps:
        #     absences.append({
        #         'id': time_comp.id,
        #         'type': 'time_comp',
        #         'employee': time_comp.employee,
        #         'start_date': time_comp.date,
        #         'end_date': time_comp.date,
        #         'status': time_comp.status,
        #         'notes': time_comp.notes,
        #         'is_vacation': False
        #     })
            
        # Sortiere nach Datum und Mitarbeiter
        return sorted(absences, key=lambda x: (x['start_date']), reverse=True)

    def post(self, request, *args, **kwargs):
        try:
            absence_type = request.POST.get('type')
            absence_id = request.POST.get('id')
            action = request.POST.get('action')
            notes = request.POST.get('notes')
            
            if absence_type == 'vacation':
                absence = Vacation.objects.get(id=absence_id)
            # else:
            #     absence = TimeCompensation.objects.get(id=absence_id)
                
            if action == 'approve':
                absence.status = 'APPROVED'
                messages.success(request, gettext('Antrag wurde genehmigt'))
            else:
                if not notes:
                    return JsonResponse({
                        'error': gettext('Bei Ablehnung muss eine Begründung angegeben werden')
                    }, status=400)
                absence.status = 'REJECTED'
                absence.notes = notes
                messages.success(request, gettext('Antrag wurde abgelehnt'))
                
            absence.save()
            
            return JsonResponse({'success': True})
            
        except ValidationError as e:
            return JsonResponse({'error': str(e)}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

# TODO: Abgelehnte Anträge anzeigen in Liste und Kalender
# TODO: BEi ABlehnung Begründung einfügen
# TODO: Check og abgelehnte Abwesenheiten eh nicht bei den Tagen weggezählt werden

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
        
        # Erstelle neues Dokument
        new_document = UserDocument.objects.create(
            user=sick_leave.employee,
            file=document,
            display_name=f"{sick_leave.employee.get_full_name()} - Krankmeldung vom {sick_leave.start_date.strftime('%d.%m.%Y')}",
            notes=''
        )
        
        # Verknüpfe mit dem Krankenstand und setze Status auf SUBMITTED
        sick_leave.document = new_document
        sick_leave.status = 'SUBMITTED'  # Setze Status auf "Krankmeldung vorgelegt"
        sick_leave.save()
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        logger.error(f"Error uploading sick leave document: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)





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
    if request.method == 'POST':
        try:
            user_id = request.POST.get('user')
            file = request.FILES.get('file')
            display_name = request.POST.get('display_name')
            notes = request.POST.get('notes')
            sick_leave_id = request.POST.get('sick_leave_id')
            
            # Überprüfe Berechtigungen
            if request.user.role != 'OWNER' and str(request.user.id) != user_id:
                messages.error(request, gettext('Keine Berechtigung'))
            return redirect('wfm:user-documents')
            
            # Erstelle das Dokument
            document = UserDocument.objects.create(
                user_id=user_id,
                file=file,
                display_name=display_name,
                notes=notes
            )
            
            # Bestimme die Redirect-URL basierend auf Dokumenttyp und Benutzerrolle
            if sick_leave_id:
                try:
                    sick_leave = SickLeave.objects.get(id=sick_leave_id)
                    # Prüfe ob der Benutzer Zugriff auf diesen Krankenstand hat
                    if request.user.role != 'OWNER' and request.user != sick_leave.employee:
                        document.delete()
                        messages.error(request, gettext('Keine Berechtigung'))
                        return redirect('wfm:absence-list')
                        
                    sick_leave.document = document
                    sick_leave.status = 'SUBMITTED'
                    sick_leave.save()
                    
                    # Redirect basierend auf Rolle bei Krankmeldungen
                    if request.user.role == 'OWNER':
                        redirect_url = 'wfm:sick-leave-management'
                    else:
                        redirect_url = 'wfm:absence-list'
                        
                except SickLeave.DoesNotExist:
                    document.delete()
                    messages.error(request, gettext('Krankenstand nicht gefunden'))
                    return redirect('wfm:absence-list')
            else:
                # Wenn es keine Krankmeldung ist, nur Owner dürfen zur Dokumentenliste
                redirect_url = 'wfm:user-documents' if request.user.role == 'OWNER' else 'wfm:absence-list'

            messages.success(request, gettext('Dokument erfolgreich hochgeladen'))
            return redirect(redirect_url)

        except Exception as e:
            logger.error(f"Fehler beim Hochladen: {str(e)}", exc_info=True)
            messages.error(request, gettext('Fehler beim Hochladen des Dokuments'))
            # Bei Fehler zur gleichen URL zurück wie bei Erfolg
            if sick_leave_id:
                if request.user.role == 'OWNER':
                    return redirect('wfm:sick-leave-management')
                return redirect('wfm:absence-list')
            return redirect(referer) if referer else redirect('wfm:user-documents' if request.user.role == 'OWNER' else 'wfm:absence-list')

                

    # GET-Request
    referer = request.META.get('HTTP_REFERER')
    return redirect(referer) if referer else redirect('wfm:user-documents' if request.user.role == 'OWNER' else 'wfm:absence-list')


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

        # # Berechne verfügbare Zeitausgleichstage
        # overtime_total = OvertimeAccount.objects.filter(
        #     employee=employee,
        #     year=current_year,
        #     is_finalized=True
        # ).aggregate(
        #     total=Sum('hours_for_timecomp')
        # )['total'] or 0

        # used_timecomp = TimeCompensation.objects.filter(
        #     employee=employee,
        #     date__year=current_year,
        #     status='APPROVED'
        # ).count() * 8  # 8 Stunden pro Tag

        # available_timecomp_hours = max(0, overtime_total - used_timecomp)
        # context['available_timecomp_days'] = available_timecomp_hours / 8
        # context['available_timecomp_hours'] = available_timecomp_hours

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
        # future_timecomps = TimeCompensation.objects.filter(
        #     employee=employee,
        #     date__gte=today
        # ).select_related(
        #     'employee'  # Falls wir employee-Informationen brauchen
        # ).order_by('date')

        # all_timecomps = TimeCompensation.objects.filter(employee=employee).order_by('-date') #Sortiere nach Datum, neuste zuerst
        # context['all_timecomps'] = all_timecomps
        # context['future_timecomps'] = future_timecomps

        # # Füge die Status-Display-Methode hinzu
        # for timecomp in future_timecomps:
        #     timecomp.get_status_display = dict(TimeCompensation.STATUS_CHOICES)[timecomp.status]
        #     timecomp.total_hours = timecomp.hours

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
                
                pending_bookings = bookings.filter(is_paid=False)
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
            is_paid=True,
            paid_date=timezone.now().date()
        )
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

class FinanceOverviewView(LoginRequiredMixin, OwnerRequiredMixin, TemplateView):
    template_name = 'wfm/finance_overview.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get current month/year
        month = self.request.GET.get('month')
        year = self.request.GET.get('year')
        if not month or not year:
            today = timezone.now()
            month = today.month
            year = today.year
        else:
            month = int(month)
            year = int(year)

        current_date = datetime_date(year, month, 1)

        # --- START DER KORREKTUR FÜR SOLL-STUNDEN BERECHNUNG ---
        # Berechne die Soll-Stunden für den Monat pro Mitarbeiter
        first_day_of_month = date(int(year), int(month), 1)
        last_day_of_month = (first_day_of_month + relativedelta(months=1)) - timedelta(days=1)

        # Hole alle potenziell relevanten Templates für Assistenten/Reinigung
        relevant_templates = ScheduleTemplate.objects.filter(
            employee__role__in=['ASSISTANT', 'CLEANING'],
            valid_from__lte=last_day_of_month
        ).select_related('employee').order_by('employee', '-valid_from')

        monthly_scheduled_hours_per_employee = {} # Dict zum Speichern der Soll-Stunden

        # Gehe durch jeden Tag des Monats
        d = first_day_of_month
        while d <= last_day_of_month:
            weekday = d.weekday() # 0 = Montag, ..., 6 = Sonntag

            # Finde das passende Template für jeden Mitarbeiter für diesen Tag
            current_templates_for_day = {}
            for template in relevant_templates:
                # Nur das neueste gültige Template pro Mitarbeiter berücksichtigen
                if template.employee_id not in current_templates_for_day and template.valid_from <= d:
                    current_templates_for_day[template.employee_id] = template

            # Addiere die Stunden des gültigen Templates zum Monatstotal
            for employee_id, template in current_templates_for_day.items():
                 if template.weekday == weekday: # Prüfe ob das Template für diesen Wochentag gilt
                    if employee_id not in monthly_scheduled_hours_per_employee:
                        monthly_scheduled_hours_per_employee[employee_id] = Decimal('0.00')

                    # Berechne die Stunden für dieses Template
                    duration = (
                        datetime.combine(date.min, template.end_time) -
                        datetime.combine(date.min, template.start_time)
                    ).total_seconds() / 3600
                    print(duration)
                    if template.break_duration:
                        duration -= template.break_duration.total_seconds() / 3600
                    print(duration)
                    monthly_scheduled_hours_per_employee[employee_id] += Decimal(str(duration))

            d += timedelta(days=1)
        # --- ENDE DER KORREKTUR FÜR SOLL-STUNDEN BERECHNUNG ---

        # 1. Einnahmen von Therapeuten (BLEIBT UNVERÄNDERT)
        therapist_income = TherapistBooking.objects.filter(
            date__year=year,
            date__month=month
        ).values(
            'therapist_id',
            'therapist__first_name',
            'therapist__last_name',
            'therapist__room_rate',
            'is_paid',
            'paid_date'
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
                    'therapist_id': therapist_id,
                    'therapist_name': booking['therapist_name'],
                    'scheduled_hours': booking['scheduled_hours'],
                    'actual_hours': booking['actual_hours'],
                    'difference_hours': booking['difference_hours'],
                    'room_cost': booking['room_cost'],
                    'extra_cost': booking['extra_cost'],
                    'is_paid': booking['is_paid'],
                    'paid_date': booking['paid_date'],
                    'total': booking['room_cost'] + booking['extra_cost']
                }

        context['grouped_income'] = grouped_income.values()

        total_therapist_hours = sum(income['scheduled_hours'] for income in grouped_income.values())
        total_therapist_room_cost = sum(income['room_cost'] for income in grouped_income.values())
        total_therapist_difference_hours = sum(income['difference_hours'] for income in grouped_income.values())
        total_therapist_extra_cost = sum(income['extra_cost'] for income in grouped_income.values())
        total_income = sum(income['total'] for income in grouped_income.values())


        # 2. Ausgaben für Mitarbeiter
        # Hole die MonthlyWage Einträge für den ausgewählten Monat (BLEIBT UNVERÄNDERT)
        monthly_wages_data = MonthlyWage.objects.filter(
            month=month,
            year=year,
            employee__role__in=['ASSISTANT', 'CLEANING']
        ).select_related('employee')

        # Erstelle assistant_expenses und cleaning_expenses
        assistant_expenses = {}
        cleaning_expenses = {}

        for wage_entry in monthly_wages_data:
            employee = wage_entry.employee
            employee_id = employee.id

            # --- ANPASSUNG: Nutze die berechneten Soll-Stunden ---
            total_scheduled = monthly_scheduled_hours_per_employee.get(employee_id, Decimal('0.00'))
            # --- ENDE ANPASSUNG ---

            # Hole Ist-Stunden aus MonthlyWage (BLEIBT UNVERÄNDERT)
            total_worked = wage_entry.total_hours or Decimal('0.00')

            # Berechne Differenz (BLEIBT UNVERÄNDERT)
            difference = total_scheduled - total_worked

            # Berechne den Lohn basierend auf Soll-Stunden (BLEIBT UNVERÄNDERT)
            amount = total_scheduled * employee.hourly_rate if employee.hourly_rate else Decimal('0.00')

            # Hole Bezahlstatus (BLEIBT UNVERÄNDERT)
            salary_payment = monthly_wages_data.filter(employee=employee, month=month, year=year).first()

            expense_data = {
                'employee__id': employee_id,
                'employee__first_name': employee.first_name,
                'employee__last_name': employee.last_name,
                'employee__hourly_rate': employee.hourly_rate,
                'total_soll': total_scheduled.quantize(Decimal("0.01")), # Verwende berechneten Wert
                'worked_hours': total_worked.quantize(Decimal("0.01")),
                'absence_hours': difference.quantize(Decimal("0.01")),
                'amount': amount.quantize(Decimal("0.01")),
                'is_paid': salary_payment.is_paid if salary_payment else False,
                'paid_date': salary_payment.paid_date if salary_payment else None
            }

            if employee.role == 'ASSISTANT':
                assistant_expenses[employee_id] = expense_data
            elif employee.role == 'CLEANING':
                cleaning_expenses[employee_id] = expense_data

        # Berechne die Summen für die Ausgaben (BLEIBT UNVERÄNDERT)
        total_assistant_soll_hours = sum(expense['total_soll'] for expense in assistant_expenses.values())
        total_assistant_ist_hours = sum(expense['worked_hours'] for expense in assistant_expenses.values())
        total_assistant_absence_hours = sum(expense['absence_hours'] for expense in assistant_expenses.values())
        total_assistant_amount = sum(expense['amount'] for expense in assistant_expenses.values())

        total_cleaning_soll_hours = sum(expense['total_soll'] for expense in cleaning_expenses.values())
        total_cleaning_ist_hours = sum(expense['worked_hours'] for expense in cleaning_expenses.values())
        total_cleaning_absence_hours = sum(expense['absence_hours'] for expense in cleaning_expenses.values())
        total_cleaning_amount = sum(expense['amount'] for expense in cleaning_expenses.values())


        # 3. Überstunden-Ausgaben (BLEIBT UNVERÄNDERT)
        overtime_expenses = OvertimePayment.objects.filter(
            created_at__year=year,
            created_at__month=month,
            hours_for_payment__gt=0
        ).select_related('employee').values(
            'id',
            'employee__id',
            'employee__first_name',
            'employee__last_name',
            'employee__role',
            'employee__hourly_rate',
            'is_paid',
            'paid_date',
            'created_at'
        ).annotate(
            overtime_hours=F('hours_for_payment'),
            amount=ExpressionWrapper(
                F('hours_for_payment') * F('employee__hourly_rate'),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            )
        ).order_by('employee__first_name', 'employee__last_name')
        
        # Berechne die Summen für Überstunden
        total_overtime_hours = overtime_expenses.aggregate(
            total=Coalesce(Sum('hours_for_payment'), Decimal('0.00'))
        )['total']
        total_overtime_amount = overtime_expenses.aggregate(
            total=Coalesce(Sum('amount'), Decimal('0.00'))
        )['total']

        # Füge die Rollen-Anzeige hinzu
        for expense in overtime_expenses:
            expense['role_display'] = {
                'OWNER': gettext('Inhaber'),
                'THERAPIST': gettext('Therapeut'),
                'ASSISTANT': gettext('Assistent'),
                'CLEANING': gettext('Reinigungskraft')
            }.get(expense['employee__role'], expense['employee__role'])

        # 4. Gesamtausgaben berechnen (BLEIBT UNVERÄNDERT)
        total_expenses = total_assistant_amount + total_cleaning_amount + total_overtime_amount

        # 5. Kontext zusammenstellen (BLEIBT UNVERÄNDERT)
        context.update({
            'grouped_income': grouped_income.values(),
            'current_date': current_date,
            'month_name': current_date.strftime('%B %Y'),
            'prev_month': (current_date - relativedelta(months=1)),
            'next_month': (current_date + relativedelta(months=1)),
            'total_income': total_income,
            'total_expenses': total_expenses,
            'grouped_income': list(grouped_income.values()), # In Liste umwandeln
            'assistant_expenses': list(assistant_expenses.values()), # In Liste umwandeln
            'cleaning_expenses': list(cleaning_expenses.values()),   # In Liste umwandeln
            'overtime_expenses': overtime_expenses,
            'total_therapist_hours': total_therapist_hours,
            'total_therapist_room_cost': total_therapist_room_cost,
            'total_therapist_difference_hours': total_therapist_difference_hours,
            'total_therapist_extra_cost': total_therapist_extra_cost,
            'total_assistant_soll_hours': total_assistant_soll_hours,
            'total_assistant_ist_hours': total_assistant_ist_hours,
            'total_assistant_absence_hours': total_assistant_absence_hours,
            'total_assistant_amount': total_assistant_amount,
            'total_cleaning_soll_hours': total_cleaning_soll_hours,
            'total_cleaning_ist_hours': total_cleaning_ist_hours,
            'total_cleaning_absence_hours': total_cleaning_absence_hours,
            'total_cleaning_amount': total_cleaning_amount,
            'total_overtime_hours': total_overtime_hours,
            'total_overtime_amount': total_overtime_amount,
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
        month = int(data.get('month'))
        year = int(data.get('year'))
        set_paid = data.get('set_paid', True)
        current_date = timezone.now().date()
        
        # Hole alle relevanten Buchungen
        bookings = TherapistBooking.objects.filter(
            therapist_id=therapist_id,
            date__year=year,
            date__month=month,
            actual_hours__gt=F('hours')
        )
        
        if not bookings.exists():
            return JsonResponse({
                'success': False,
                'error': gettext('Keine Mehrstunden gefunden')
            })
        
        # Aktualisiere den Status
        bookings.update(
            is_paid=set_paid,
            paid_date=current_date if set_paid else None
        )
        
        return JsonResponse({
            'success': True,
            'is_paid': set_paid,
            'paid_date': current_date.strftime('%d.%m.%Y') if set_paid else None
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Markieren der Therapeuten-Mehrstunden: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

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
        current_date = timezone.now().date()
        
        # Hole alle Buchungen für diesen Monat
        bookings = TherapistBooking.objects.filter(
            therapist_id=therapist_id,
            date__year=year,
            date__month=month,
            actual_hours__gt=F('hours')
        )
        
        if not bookings.exists():
            return JsonResponse({
                'success': False,
                'error': gettext('Keine Mehrstunden gefunden')
            })
        
        # Aktualisiere den Status - HIER ist der Fehler
        new_status = 'PAID' if set_paid else 'PENDING'  # Diese Zeile entfernen!
        new_date = current_date if set_paid else None
        
        updated_count = bookings.update(
            is_paid=set_paid,  # Direkt den Boolean verwenden
            paid_date=new_date
        )
        
        return JsonResponse({
            'success': True,
            'is_paid': set_paid,
            'paid_date': current_date.strftime('%d.%m.%Y') if set_paid else None
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Markieren der Therapeuten-Mehrstunden: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@ensure_csrf_cookie
@require_http_methods(["POST"])
def api_mark_overtime_as_paid(request):
    try:
        data = json.loads(request.body)
        payment_id = data.get('id')
        set_paid = data.get('set_paid', False)

        if not payment_id:
            return JsonResponse({'success': False, 'error': gettext('Überstunden ID fehlt')}, status=400)

        payment = OvertimePayment.objects.get(id=payment_id)
        
        # Hole oder erstelle OvertimeAccount für den aktuellen Monat
        today = timezone.now()
        overtime_account, created = OvertimeAccount.objects.get_or_create(
            employee=payment.employee,
            month=today.month,
            year=today.year,
            defaults={
                'balance': Decimal('0.00'),
                'current_balance': Decimal('0.00')
            }
        )
        
        # Wenn als bezahlt markiert wird, ziehe Stunden ab
        if set_paid and not payment.is_paid:  # Nur wenn vorher nicht bezahlt
            overtime_account.balance -= payment.hours_for_payment
            overtime_account.current_balance -= payment.hours_for_payment
        # Wenn Bezahlung zurückgesetzt wird, addiere Stunden wieder
        elif not set_paid and payment.is_paid:  # Nur wenn vorher bezahlt
            overtime_account.balance += payment.hours_for_payment
            overtime_account.current_balance += payment.hours_for_payment
            
        overtime_account.save()
        
        # Aktualisiere den Payment-Status
        payment.is_paid = set_paid
        payment.paid_date = timezone.now() if set_paid else None
        payment.save()

        return JsonResponse({
            'success': True,
            'is_paid': payment.is_paid,
            'paid_date': payment.paid_date.strftime('%d.%m.%Y') if payment.paid_date else None,
            'current_balance': float(overtime_account.current_balance)  # Sende aktuelle Balance zurück
        })

    except OvertimePayment.DoesNotExist:
        return JsonResponse({
            'success': False, 
            'error': gettext('Überstundeneintrag nicht gefunden')
        }, status=404)
    except Exception as e:
        logger.error(f"Fehler beim Markieren der Überstunden als bezahlt: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)





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
        month = int(data.get('month'))
        year = int(data.get('year'))
        set_paid = data.get('set_paid', True)
        current_date = timezone.now().date()
        
        # Hole oder erstelle MonthlyWage für diesen Monat
        monthly_wage, created = MonthlyWage.objects.get_or_create(
            employee_id=employee_id,
            year=year,
            month=month
        )
        
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
        
        # Aktualisiere den Bezahlstatus
        working_hours.update(
            is_paid=set_paid,
            paid_date=current_date if set_paid else None
        )
        
        # Aktualisiere auch den MonthlyWage Eintrag
        monthly_wage.is_paid = set_paid
        monthly_wage.paid_date = current_date if set_paid else None
        monthly_wage.save()
        
        # Hole den aktualisierten Status für die Antwort
        updated_wage = MonthlyWage.objects.get(pk=monthly_wage.pk)
        
        return JsonResponse({
            'success': True,
            'is_paid': updated_wage.is_paid,
            'paid_date': updated_wage.paid_date.strftime('%d.%m.%Y') if updated_wage.paid_date else None,
            'employee_id': employee_id
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Markieren des Gehalts: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False, 
            'error': str(e)
        }, status=500)

@login_required
def api_overtime_overview(request):
    """API für Überstunden-Übersicht und Auszahlungsmarkierung"""
    try:
        today = timezone.now().date()
        
        # Hole die aktuelle Gesamtbilanz
        total_balance = OvertimeAccount.get_current_balance(request.user)
        
        # Hole den aktuellen OvertimePayment-Eintrag
        payment = OvertimePayment.objects.filter(
            employee=request.user,
            is_paid=False  # Nur nicht bezahlte Einträge
        ).first()

        if request.method == 'GET':
            response_data = {
                'balance': float(total_balance),
                'hours_for_payment': float(payment.hours_for_payment if payment else 0),
                'is_paid': payment.is_paid if payment else False
            }
            return JsonResponse(response_data)

        elif request.method == 'POST':
            data = json.loads(request.body)
            hours_for_payment = Decimal(str(data.get('hours_for_payment', 0)))

            if hours_for_payment > total_balance:
                return JsonResponse({
                    'success': False,
                    'error': gettext('Nicht genügend Überstunden verfügbar')
                })

            # Erstelle oder aktualisiere den OvertimePayment-Eintrag
            if not payment:
                payment = OvertimePayment(
                    employee=request.user,
                    hours_for_payment=hours_for_payment,
                    is_paid=False
                )
                # Berechne den Betrag vor dem Speichern
                payment.calculate_amount()
                payment.save()
            else:
                payment.hours_for_payment = hours_for_payment
                payment.calculate_amount()
                payment.save()

            return JsonResponse({
                'success': True,
                'balance': float(total_balance),
                'hours_for_payment': float(payment.hours_for_payment)
            })

    except Exception as e:
        logger.error(f"Overtime overview error: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def api_get_balance(request):
    """API-Endpoint für die aktuelle Überstunden-Balance"""
    try:
        employee = request.user
        if request.user.role == 'OWNER':
            employee_id = request.GET.get('employee')
            if employee_id:
                employee = CustomUser.objects.get(id=employee_id)

        year = request.GET.get('year')
        month = request.GET.get('month')
        
        if year and month:
            year = int(year)
            month = int(month)
            balance = OvertimeAccount.get_current_balance(employee, year, month)
        else:
            balance = OvertimeAccount.get_current_balance(employee)

        return JsonResponse({
            'balance': float(balance)
        })

    except Exception as e:
        logger.error(f"Error getting balance: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def calculate_balances(request):
    """View für die manuelle Berechnung der Überstunden-Balances"""
    try:
        if request.user.role == 'OWNER':
            # Für Owner: Berechne für alle Mitarbeiter
            OvertimeAccount.update_all_balances()
            messages.success(request, 'Überstunden für alle Mitarbeiter aktualisiert.')
        else:
            # Für andere: Nur eigene Balance berechnen
            today = timezone.now().date()
            
            # Benutze die bestehende Methode zur Berechnung der Balance
            OvertimeAccount.update_all_balances()
            
            # Hole die aktuelle Balance
            account = OvertimeAccount.objects.get(
                employee=request.user,
                year=today.year,
                month=today.month
            )
            
            messages.success(
                request, 
                f'Ihre Überstunden wurden aktualisiert. Aktuelle Bilanz: {account.balance:+.2f} Stunden'
            )

    except Exception as e:
        messages.error(request, f'Fehler bei der Berechnung: {str(e)}')

    return redirect(request.META.get('HTTP_REFERER', 'wfm:working_hours_list'))

class WorkingHoursDetailView(LoginRequiredMixin, DetailView):
    model = WorkingHours
    
    def test_func(self):
        obj = self.get_object()
        return self.request.user.role == 'OWNER' or obj.employee == self.request.user
    
    def render_to_response(self, context):
        obj = context['object']
        return JsonResponse({
            'id': obj.id,
            'employee_id': obj.employee.id,
            'date': obj.date.strftime('%Y-%m-%d'),
            'start_time': obj.start_time.strftime('%H:%M'),
            'end_time': obj.end_time.strftime('%H:%M'),
            'break_duration': obj.break_duration.seconds // 60,
            'notes': obj.notes or ''
        })

class WorkingHoursDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = WorkingHours
    
    def test_func(self):
        obj = self.get_object()
        return self.request.user.role == 'OWNER' or obj.employee == self.request.user
    
    def post(self, request, *args, **kwargs):
        try:
            self.object = self.get_object()
            self.object.delete()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

class TherapistBookingCreateView(LoginRequiredMixin, CreateView):
    model = TherapistBooking
    fields = ['start_time', 'end_time', 'notes', 'actual_hours']
    template_name = 'wfm/modals/therapist_booking_modal_add.html'
    
    def post(self, request, *args, **kwargs):
        try:
            # Setze den Therapeuten basierend auf der Rolle
            if request.user.role == 'OWNER':
                therapist_id = request.POST.get('therapist_id')
                if not therapist_id:
                    return JsonResponse({
                        'success': False,
                        'error': gettext('Bitte wählen Sie einen Therapeuten aus.')
                    })
                therapist = CustomUser.objects.get(id=therapist_id)
            else:
                therapist = request.user
            
            # Prüfe ob bereits eine Buchung für diesen Tag existiert
            booking_date = request.POST.get('date')
            existing_booking = TherapistBooking.objects.filter(
                therapist=therapist,
                date=booking_date
            ).first()
            
            if existing_booking and request.user.role == 'THERAPIST':
                return JsonResponse({
                    'success': False,
                    'error': gettext('Für diesen Tag existiert bereits eine Buchung. '
                                   'Bitte bearbeiten Sie die bestehende Buchung.'),
                    'existing_booking_id': existing_booking.id
                })
            
            # Konvertiere Strings zu time-Objekten
            start_time = datetime.strptime(request.POST.get('start_time', '00:00'), '%H:%M').time()
            end_time = datetime.strptime(request.POST.get('end_time', '00:00'), '%H:%M').time()
            
            # Konvertiere actual_hours zu Decimal
            actual_hours = request.POST.get('actual_hours')
            if actual_hours:
                actual_hours = Decimal(str(actual_hours))
            
            # Erstelle die Buchung
            booking = TherapistBooking.objects.create(
                therapist=therapist,
                date=booking_date,
                start_time=start_time,
                end_time=end_time,
                hours=Decimal('0.00') if request.user.role == 'THERAPIST' else None,
                actual_hours=actual_hours,
                notes=request.POST.get('notes', '')
            )
            
            # Berechne die Differenz für Mehrstunden
            if request.user.role == 'THERAPIST' and actual_hours:
                # Wenn keine gebuchten Stunden vorliegen (hours=0), 
                # sind die kompletten actual_hours Mehrstunden
                booking.difference_hours = actual_hours
                booking.is_paid = False
                booking.save()
            
            return JsonResponse({
                'success': True,
                'id': booking.id,
                'therapist_id': booking.therapist.id
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })

class TherapistBookingUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = TherapistBooking
    fields = ['start_time', 'end_time', 'notes', 'actual_hours']  # client entfernt
    template_name = 'wfm/modals/therapist_booking_modal_edit.html'
    
    def test_func(self):
        # Prüfe ob der User ein Owner ist oder der Therapeut selbst
        return (self.request.user.role == 'OWNER' or 
                self.get_object().therapist == self.request.user)
    
    def form_valid(self, form):
        # Speichere das Objekt ohne redirect
        self.object = form.save()
        
        return JsonResponse({
            'success': True,
            'id': self.object.id,
            'therapist_id': self.object.therapist.id
        })
    
    def form_invalid(self, form):
        return JsonResponse({
            'success': False,
            'error': form.errors
        })

class TherapistBookingDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = TherapistBooking
    
    def test_func(self):
        # Prüfe ob der User ein Owner ist oder der Therapeut selbst
        return (self.request.user.role == 'OWNER' or 
                self.get_object().therapist == self.request.user)
    
    def render_to_response(self, context):
        obj = context['object']
        return JsonResponse({
            'id': obj.id,
            'therapist': {
                'id': obj.therapist.id,
                'name': obj.therapist.get_full_name()
            },
            'date': obj.date.strftime('%Y-%m-%d'),
            'start_time': obj.start_time.strftime('%H:%M') if obj.start_time else '',
            'end_time': obj.end_time.strftime('%H:%M') if obj.end_time else '',
            'hours': float(obj.hours) if obj.hours else None,
            'actual_hours': float(obj.actual_hours) if obj.actual_hours else None,
            'notes': obj.notes or '',
            'is_paid': obj.is_paid
        })

class TherapistBookingDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = TherapistBooking
    
    def test_func(self):
        # Prüfe ob der User ein Owner ist oder der Therapeut selbst
        return (self.request.user.role == 'OWNER' or 
                self.get_object().therapist == self.request.user)
    
    def post(self, request, *args, **kwargs):
        try:
            self.object = self.get_object()
            self.object.delete()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

@method_decorator(login_required, name='dispatch')
class TherapistCalendarEventsView(View):
    def get(self, request):
        # FullCalendar sendet start und end Parameter
        start = request.GET.get('start')
        end = request.GET.get('end')
        
        # Konvertiere die Strings zu Dates
        start_date = parse_datetime(start).date()
        end_date = parse_datetime(end).date()
        
        # Hole alle Buchungen im angefragten Zeitraum
        bookings = TherapistBooking.objects.filter(
            date__range=[start_date, end_date]
        ).select_related('therapist')
        
        # Generiere Events basierend auf der Rolle
        if request.user.role == 'THERAPIST':
            own_bookings = bookings.filter(therapist=request.user)
            other_bookings = bookings.exclude(therapist=request.user)
            
            events = [
                {
                    'id': str(booking.id),
                    'title': f"{booking.start_time.strftime('%H:%M')}-{booking.end_time.strftime('%H:%M')}",
                    'start': f"{booking.date}T{booking.start_time}",
                    'end': f"{booking.date}T{booking.end_time}",
                    'backgroundColor': booking.therapist.color,
                    'extendedProps': {
                        'therapist': {
                            'id': booking.therapist.id,
                            'name': booking.therapist.get_full_name()
                        },
                        'hours': float(booking.hours) if booking.hours else None,
                        'actual_hours': float(booking.actual_hours) if booking.actual_hours else None,
                        'notes': booking.notes
                    }
                }
                for booking in own_bookings
            ] + [
                {
                    'title': 'Belegt',
                    'start': f"{booking.date}T{booking.start_time}",
                    'end': f"{booking.date}T{booking.end_time}",
                    'backgroundColor': '#808080',
                    'className': 'blocked-time'
                }
                for booking in other_bookings
            ]
        else:
            events = [
                {
                    'id': str(booking.id),
                    'title': f"{booking.therapist.get_full_name()} ({booking.start_time.strftime('%H:%M')}-{booking.end_time.strftime('%H:%M')})",
                    'start': f"{booking.date}T{booking.start_time}",
                    'end': f"{booking.date}T{booking.end_time}",
                    'backgroundColor': booking.therapist.color,
                    'extendedProps': {
                        'therapist': {
                            'id': booking.therapist.id,
                            'name': booking.therapist.get_full_name()
                        },
                        'hours': float(booking.hours) if booking.hours else None,
                        'actual_hours': float(booking.actual_hours) if booking.actual_hours else None,
                        'notes': booking.notes
                    }
                }
                for booking in bookings
            ]
        
        return JsonResponse(events, safe=False)

class OvertimeYearlyReportView(LoginRequiredMixin, OwnerRequiredMixin, View):
    template_name = 'wfm/overtime_yearly_report.html'

    def get(self, request):
        year = int(request.GET.get('year', timezone.now().year))
        
        # Hole alle Mitarbeiter mit Überstunden im gewählten Jahr
        employees = CustomUser.objects.filter(
            overtimeentry__date__year=year
        ).distinct()
        
        yearly_data = []
        for employee in employees:
            monthly_data = []
            yearly_total = Decimal('0.00')
            yearly_paid = Decimal('0.00')
            
            for month in range(1, 13):
                # Monatliche Überstunden
                month_entries = OvertimeEntry.objects.filter(
                    employee=employee,
                    date__year=year,
                    date__month=month
                )
                
                # Ausgezahlte Überstunden
                paid_entries = OvertimePayment.objects.filter(
                    employee=employee,
                    created_at__year=year,
                    created_at__month=month,
                    is_paid=True
                )
                
                month_total = month_entries.aggregate(
                    total=Coalesce(Sum('hours'), Decimal('0.00'))
                )['total']
                
                month_paid = paid_entries.aggregate(
                    total=Coalesce(Sum('hours_for_payment'), Decimal('0.00'))
                )['total']
                
                monthly_data.append({
                    'month': month,
                    'month_name': calendar.month_name[month],
                    'hours': month_total,
                    'paid_hours': month_paid,
                    'amount': month_paid * employee.hourly_rate if month_paid else Decimal('0.00')
                })
                
                yearly_total += month_total
                yearly_paid += month_paid
            
            yearly_data.append({
                'employee': employee,
                'monthly_data': monthly_data,
                'yearly_total': yearly_total,
                'yearly_paid': yearly_paid,
                'yearly_amount': yearly_paid * employee.hourly_rate
            })
        
        context = {
            'year': year,
            'yearly_data': yearly_data,
            'prev_year': year - 1,
            'next_year': year + 1
        }
        
        return render(request, self.template_name, context)

class FinanceYearlyReportView(LoginRequiredMixin, OwnerRequiredMixin, View):
    template_name = 'wfm/finance_yearly_report.html'

    def get_therapist_monthly_data(self, employee, year, month):
        """Berechnet die monatlichen Daten für Therapeuten"""
        
        
        # Alle Buchungen für den Monat
        bookings = TherapistBooking.objects.filter(
            therapist=employee,
            date__year=year,
            date__month=month
        )
        
        # Gebuchte Stunden
        booked_hours = bookings.aggregate(
            total=Coalesce(Sum('hours'), Decimal('0.00'))
        )['total']
        
        # Mehrstunden (difference_hours)
        extra_hours = bookings.aggregate(
            total=Coalesce(Sum('difference_hours'), Decimal('0.00'))
        )['total']

        employee = CustomUser.objects.get(id=employee.id)
        # Berechne Beträge
        room_rate = employee.room_rate if employee.room_rate is not None else Decimal('0.00')
        print(f"Therapeut: {employee.get_full_name()}")
        print(f"Stundensatz: {room_rate}")
        base_amount = booked_hours * room_rate if booked_hours else Decimal('0.00')
        extra_amount = extra_hours * room_rate if extra_hours else Decimal('0.00')
        total_amount = base_amount + extra_amount
        print(f"Basis-Betrag: {base_amount}")
        print(f"Mehrstunden-Betrag: {extra_amount}")
        print(f"Gesamt-Betrag: {total_amount}")
        
        # Prüfe Zahlungsstatus
        unpaid_bookings = bookings.filter(
            difference_hours__gt=0,
            is_paid=False
        ).exists()
        print(f"Unbezahlte Buchungen vorhanden: {unpaid_bookings}")

        result = {
            'month': month,
            'month_name': calendar.month_name[month],
            'booked_hours': booked_hours,
            'base_amount': base_amount,
            'extra_hours': extra_hours,
            'extra_amount': extra_amount,
            'total': total_amount,
            'is_paid': not unpaid_bookings
        }
        print(f"Rückgabewert: {result}")
        print("="*50)
        return result

    def get(self, request):
        year = int(request.GET.get('year', timezone.now().year))
        role_filter = request.GET.get('role')
        employee_id = request.GET.get('employee')
    
        
        # Basis-Query für Mitarbeiter
        if role_filter:
            employees = CustomUser.objects.filter(role=role_filter)
        else:
            # Wenn kein Filter, zeige alle Mitarbeiter außer Owner
            employees = CustomUser.objects.exclude(role='OWNER')
                
        if employee_id:
            employees = employees.filter(id=employee_id)
            
        # Gesamtjahresübersicht initialisieren
        yearly_totals = {
            'booked_hours': Decimal('0.00'),
            'booked_amount': Decimal('0.00'),
            'extra_hours': Decimal('0.00'),
            'extra_amount': Decimal('0.00'),
            'working_hours': Decimal('0.00'),
            'salary': Decimal('0.00'),
            'overtime': Decimal('0.00'),
            'overtime_amount': Decimal('0.00'),
            'total_booked_hours': Decimal('0.00'),
            'total_working_hours': Decimal('0.00'),
            'total_earnings': Decimal('0.00'),
            'total_spendings': Decimal('0.00')
        }
                
        yearly_data = []
        for employee in employees:
            monthly_data = []
            employee_totals = {
                'working_hours': Decimal('0.00'),
                'salary': Decimal('0.00'),
                'overtime': Decimal('0.00'),
                'overtime_amount': Decimal('0.00'),
                'total_earnings': Decimal('0.00')
            }
            
            for month in range(1, 13):
                if employee.role == 'THERAPIST':
                    month_data = self.get_therapist_monthly_data(employee, year, month)
                    monthly_data.append(month_data)
                    
                    # Therapeuten Jahressummen (Einnahmen)
                    yearly_totals['booked_hours'] += month_data['booked_hours']
                    yearly_totals['booked_amount'] += month_data['base_amount']  
                    yearly_totals['extra_hours'] += month_data['extra_hours']
                    yearly_totals['extra_amount'] += month_data['extra_amount']  
                    yearly_totals['total_earnings'] += month_data['total']
                    
                    # Mitarbeiter Jahressummen
                    employee_totals['working_hours'] += month_data['booked_hours']
                    employee_totals['salary'] += month_data['base_amount']
                    employee_totals['overtime'] += month_data['extra_hours']
                    employee_totals['overtime_amount'] += month_data['extra_amount']
                    employee_totals['total_earnings'] += month_data['total']
                else:
                    # Arbeitsstunden
                    monthly_wage = MonthlyWage.objects.filter(
                        employee=employee,
                        year=year,
                        month=month
                    ).first()

                    working_hours = monthly_wage.total_hours if monthly_wage else Decimal('0.00')
                    salary_amount = monthly_wage.wage if monthly_wage else Decimal('0.00')
                    
                    # Überstunden
                    overtime_entries = OvertimePayment.objects.filter(
                        employee=employee,
                        paid_date__year=year,
                        paid_date__month=month
                    )
                    
                    overtime_hours = overtime_entries.aggregate(
                        total=Coalesce(Sum('hours_for_payment'), Decimal('0.00'))
                    )['total']
                    
                    # Überstundenbetrag
                    overtime_amount = Decimal('0.00')
                    if overtime_hours > 0:
                        overtime_amount = overtime_entries.aggregate(
                            total=Coalesce(Sum('amount'), Decimal('0.00'))
                        )['total']
                    
                    # Gesamteinnahmen für den Monat
                    total_month = salary_amount + overtime_amount
                    
                    month_data = {
                        'month': month,
                        'month_name': calendar.month_name[month],
                        'working_hours': working_hours,
                        'salary': salary_amount,
                        'is_paid': monthly_wage.is_paid if monthly_wage else False,
                        'overtime_hours': overtime_hours,
                        'overtime_amount': overtime_amount,
                        'overtime_is_paid': False,
                        'total': total_month
                    }
                    
                    monthly_data.append(month_data)
                    
                    # Ausgaben Jahressummen
                    yearly_totals['working_hours'] += working_hours
                    yearly_totals['salary'] += salary_amount
                    yearly_totals['overtime'] += overtime_hours
                    yearly_totals['overtime_amount'] += overtime_amount
                    yearly_totals['total_spendings'] += total_month
                    
                    # Mitarbeiter Jahressummen
                    employee_totals['working_hours'] += working_hours
                    employee_totals['salary'] += salary_amount
                    employee_totals['overtime'] += overtime_hours
                    employee_totals['overtime_amount'] += overtime_amount
                    employee_totals['total_earnings'] += total_month
            
            # Gesamtsummen berechnen
            yearly_totals['total_booked_hours'] = yearly_totals['booked_hours'] + yearly_totals['extra_hours']
            yearly_totals['total_working_hours'] = yearly_totals['working_hours'] + yearly_totals['overtime']
            
            yearly_data.append({
                'employee': employee,
                'monthly_data': monthly_data,
                'yearly_totals': employee_totals
            })
        
        context = {
            'year': year,
            'yearly_data': yearly_data,
            'yearly_totals': yearly_totals,  # Gesamtjahresübersicht
            'prev_year': year - 1,
            'next_year': year + 1,
            'roles': [
                ('ASSISTANT', gettext('Assistenten')), 
                ('CLEANING', gettext('Reinigung')),
                ('THERAPIST', gettext('Therapeuten'))
            ],
            'selected_role': role_filter,
            'employees': CustomUser.objects.exclude(role='OWNER'),
            'selected_employee': employee_id
        }
        
        return render(request, self.template_name, context)



