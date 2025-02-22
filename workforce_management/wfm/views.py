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
    CustomUser
)
from .forms import WorkingHoursForm, VacationRequestForm, TimeCompensationForm
from django.db.models import Sum, Count
from django.db.models.functions import ExtractMonth, ExtractYear
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

logger = logging.getLogger(__name__)

class OwnerRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.role == 'OWNER'

@login_required
def dashboard(request):
    """Leitet zur Hauptseite weiter"""
    return redirect('wfm:dashboard')  # Statt 'owner-dashboard' verwenden wir jetzt 'dashboard'

class WorkingHoursListView(LoginRequiredMixin, ListView):
    model = WorkingHours
    template_name = 'wfm/working_hours_list.html'
    context_object_name = 'working_hours'
    paginate_by = None

    def get_queryset(self):
        # Hole Jahr und Monat aus URL-Parametern oder nutze aktuellen Monat
        year = int(self.request.GET.get('year', date.today().year))
        month = int(self.request.GET.get('month', date.today().month))
        
        # Erstelle Datum für Monatsanfang und -ende
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        # Basis-Queryset für tatsächliche Arbeitszeiten
        queryset = WorkingHours.objects.select_related('employee')
        
        # Filter nach Mitarbeiter und Rolle
        if self.request.user.role == 'OWNER':
            employee_id = self.request.GET.get('employee')
            role_filter = self.request.GET.get('role')
            
            if employee_id:
                # Filter nach spezifischem Mitarbeiter
                employees = [CustomUser.objects.get(id=employee_id)]
            elif role_filter:
                # Filter nach Rolle
                employees = CustomUser.objects.filter(role=role_filter)
            else:
                # Alle Assistenten und Reinigungskräfte
                employees = CustomUser.objects.filter(role__in=['ASSISTANT', 'CLEANING'])
        else:
            # Nicht-Owner sehen nur ihre eigenen Einträge
            employees = [self.request.user]

        # Hole alle relevanten Templates für die gefilterten Mitarbeiter
        all_templates = ScheduleTemplate.objects.filter(
            employee__in=employees
        ).order_by('employee', '-valid_from', 'weekday')
        
        # Erstelle Dictionary für schnellen Template-Zugriff
        template_dict = {}
        for template in all_templates:
            key = (template.employee_id, template.weekday)
            if key not in template_dict:
                template_dict[key] = template

        # Hole existierende Arbeitszeiten für den gewählten Zeitraum und die gefilterten Mitarbeiter
        working_hours_list = list(queryset.filter(
            date__range=[start_date, end_date],
            employee__in=employees
        ))
        existing_dates = {(wh.employee_id, wh.date): wh for wh in working_hours_list}
        
        # Fülle fehlende Tage mit Template-basierten Arbeitszeiten
        current_date = start_date
        while current_date <= end_date:
            weekday = current_date.weekday()
            if weekday < 5:  # Nur Werktage (Mo-Fr)
                for employee in employees:
                    key = (employee.id, current_date)
                    if key not in existing_dates:
                        template = template_dict.get((employee.id, weekday))
                        if template and template.valid_from <= current_date:
                            wh = WorkingHours(
                                employee=employee,
                                date=current_date,
                                start_time=template.start_time,
                                end_time=template.end_time,
                                break_duration=timedelta(minutes=30)  # Standard-Pause
                            )
                            working_hours_list.append(wh)
            current_date += timedelta(days=1)
            
        return sorted(working_hours_list, key=lambda x: (x.date, x.employee_id))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Füge die Buttons für Urlaub/Zeitausgleich/Krankmeldung hinzu
        if self.request.user.role in ['ASSISTANT', 'CLEANING']:
            context['show_request_buttons'] = True
            
            # Hole aktuelle Anträge
            context['pending_vacations'] = Vacation.objects.filter(
                employee=self.request.user,
                status='REQUESTED'
            )
            context['pending_time_comps'] = TimeCompensation.objects.filter(
                employee=self.request.user,
                status='REQUESTED'
            )
            context['active_sick_leaves'] = SickLeave.objects.filter(
                employee=self.request.user,
                end_date__gte=timezone.now().date()
            )
            
        # Hole Jahr und Monat
        year = int(self.request.GET.get('year', date.today().year))
        month = int(self.request.GET.get('month', date.today().month))
        
        # Berechne vorherigen und nächsten Monat
        if month == 1:
            prev_month = 12
            prev_year = year - 1
        else:
            prev_month = month - 1
            prev_year = year
            
        if month == 12:
            next_month = 1
            next_year = year + 1
        else:
            next_month = month + 1
            next_year = year
        
        # Füge Navigationsdaten zum Kontext hinzu
        context.update({
            'current_month': month,
            'current_year': year,
            'prev_month': prev_month,
            'prev_year': prev_year,
            'next_month': next_month,
            'next_year': next_year,
            'month_name': date(year, month, 1).strftime('%B %Y')
        })
        
        if self.request.user.role == 'OWNER':
            # Hole alle Mitarbeiter für Filter
            context['assistants'] = CustomUser.objects.filter(role='ASSISTANT')
            context['cleaners'] = CustomUser.objects.filter(role='CLEANING')
            
            # Hole ausgewählten Mitarbeiter und Rolle
            employee_id = self.request.GET.get('employee')
            role_filter = self.request.GET.get('role')
            
            if employee_id:
                context['selected_employee'] = CustomUser.objects.filter(id=employee_id).first()
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
        
        # Berechne die Stunden für jeden Eintrag
        for wh in context['working_hours']:
            # Hole das gültige Template für dieses Datum
            template = ScheduleTemplate.objects.filter(
                employee=wh.employee,
                weekday=wh.date.weekday(),
                valid_from__lte=wh.date
            ).order_by('-valid_from').first()
            
            if template:
                wh.soll_start = template.start_time
                wh.soll_end = template.end_time
                wh.soll_hours = template.hours
            else:
                wh.soll_start = time(8, 0)
                wh.soll_end = time(16, 0)
                wh.soll_hours = Decimal('8.0')
            
            # Berechne Ist-Stunden
            if wh.id:  # Nur für gespeicherte Einträge
                duration = datetime.combine(date.min, wh.end_time) - datetime.combine(date.min, wh.start_time)
                if wh.break_duration:
                    duration -= wh.break_duration
                wh.ist_hours = Decimal(str(duration.total_seconds() / 3600))
            else:
                wh.ist_hours = Decimal('0')
            
            # Hole Abwesenheiten
            wh.vacation = Vacation.objects.filter(
                employee=wh.employee,
                start_date__lte=wh.date,
                end_date__gte=wh.date
            ).first()
            
            wh.time_comp = TimeCompensation.objects.filter(
                employee=wh.employee,
                date=wh.date
            ).first()
            
            wh.sick_leave = SickLeave.objects.filter(
                employee=wh.employee,
                start_date__lte=wh.date,
                end_date__gte=wh.date
            ).first()
            
            # Differenz
            wh.difference = wh.ist_hours - wh.soll_hours
            
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
            'vacation_days_total': vacation_entitlement.total_days if vacation_entitlement else 0,
            'vacation_days_used': used_vacation_days,
            'vacation_days_remaining': (vacation_entitlement.total_days - used_vacation_days) if vacation_entitlement else 0,
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
@ensure_csrf_cookie
def api_vacation_request(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
            
            # Validiere die Daten
            required_fields = ['start_date', 'end_date']
            if not all(field in data and data[field] for field in required_fields):
                return JsonResponse({
                    'success': False,
                    'error': 'Bitte Start- und Enddatum angeben'
                })

            # Parse dates
            start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            
            # Berechne Werktage
            requested_days = sum(1 for date in (start_date + timedelta(n) for n in range((end_date - start_date).days + 1))
                               if date.weekday() < 5)
            
            # Prüfe verfügbare Urlaubstage
            vacation_entitlement = VacationEntitlement.objects.filter(
                employee=request.user,
                year=start_date.year
            ).first()
            
            if not vacation_entitlement:
                return JsonResponse({
                    'success': False,
                    'error': 'Keine Urlaubstage für dieses Jahr eingetragen'
                })
            
            used_vacation_days = Vacation.objects.filter(
                employee=request.user,
                start_date__year=start_date.year,
                status='APPROVED'
            ).count()
            
            remaining_days = vacation_entitlement.total_days - used_vacation_days
            
            if requested_days > remaining_days:
                return JsonResponse({
                    'success': False,
                    'error': f'Nicht genügend Urlaubstage verfügbar. Verfügbar: {remaining_days}, Angefragt: {requested_days}'
                })

            # Erstelle den Urlaubsantrag
            vacation = Vacation.objects.create(
                employee=request.user,
                start_date=start_date,
                end_date=end_date,
                notes=data.get('notes', ''),
                status='REQUESTED'
            )
            
            return JsonResponse({'success': True})
            
        except Exception as e:
            logger.error(f"Vacation request error: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({
        'success': False,
        'error': 'Ungültige Anfrage'
    })

@login_required
@ensure_csrf_cookie
def api_time_compensation_request(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
            
            # Validiere die Daten
            required_fields = ['date', 'hours']
            if not all(field in data and data[field] for field in required_fields):
                return JsonResponse({
                    'success': False,
                    'error': 'Bitte alle Pflichtfelder ausfüllen'
                })

            hours = float(data['hours'])
            
            # Prüfe verfügbare Stunden
            total_overtime = calculate_total_overtime(request.user)  # Diese Funktion müssen wir noch implementieren
            used_compensation = TimeCompensation.objects.filter(
                employee=request.user,
                status='APPROVED'
            ).aggregate(total=Sum('hours'))['total'] or 0
            
            available_hours = total_overtime - used_compensation
            
            if hours > available_hours:
                return JsonResponse({
                    'success': False,
                    'error': f'Nicht genügend Stunden verfügbar. Verfügbar: {available_hours:.2f}, Angefragt: {hours:.2f}'
                })

            # Erstelle den Zeitausgleichsantrag
            time_comp = TimeCompensation.objects.create(
                employee=request.user,
                date=data['date'],
                hours=hours,
                notes=data.get('notes', ''),
                status='REQUESTED'
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

class TherapistMonthlyOverviewView(LoginRequiredMixin, ListView):
    template_name = 'wfm/therapist_monthly_overview.html'
    context_object_name = 'days'

    def dispatch(self, request, *args, **kwargs):
        if request.user.role != 'THERAPIST':
            return redirect('wfm:monthly-overview')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        year = int(self.request.GET.get('year', datetime.now().year))
        month = int(self.request.GET.get('month', datetime.now().month))
        
        num_days = calendar.monthrange(year, month)[1]
        days = []
        
        for day in range(1, num_days + 1):
            date = datetime(year, month, day).date()
            
            # Hole die Standard-Buchungen für diesen Wochentag
            schedule = TherapistScheduleTemplate.objects.filter(
                therapist=self.request.user,
                weekday=date.weekday()
            )
            scheduled_hours = sum(Decimal(str(template.hours)) for template in schedule)
            
            # Hole alle tatsächlichen Buchungen für diesen Tag
            bookings = TherapistBooking.objects.filter(
                therapist=self.request.user,
                date=date
            )
            
            # Berechne die Stunden
            total_hours = scheduled_hours
            if bookings.exists():
                total_hours = sum(Decimal(str(booking.hours)) for booking in bookings)
            
            # Setze verwendete Stunden standardmäßig auf gebuchte Stunden
            used_hours = total_hours
            if bookings.filter(status='USED').exists():
                used_hours = sum(
                    booking.actual_hours or Decimal(str(booking.hours))
                    for booking in bookings.filter(status='USED')
                )
            
            # Berechne die Differenz - nur positive Werte (Mehrstunden)
            difference = Decimal('0')
            if used_hours > total_hours:
                difference = used_hours - total_hours
            
            days.append({
                'date': date,
                'schedule': schedule,
                'bookings': bookings,
                'total_hours': round(total_hours, 2),
                'used_hours': round(used_hours, 2),
                'difference': round(difference, 2)
            })
        
        return days

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year = int(self.request.GET.get('year', datetime.now().year))
        month = int(self.request.GET.get('month', datetime.now().month))
        
        context['year'] = year
        context['month'] = month
        context['month_name'] = calendar.month_name[month]
        
        # Berechne die Gesamtsummen für den Monat
        total_hours = sum(day['total_hours'] for day in context['days'])
        used_hours = sum(day['used_hours'] for day in context['days'])
        
        # Summiere nur die positiven Differenzen (Mehrstunden)
        total_difference = sum(
            day['difference']  # difference ist bereits auf Mehrstunden beschränkt
            for day in context['days']
        )
        
        room_rate = self.request.user.room_rate or 0
        
        # Berechne den zu zahlenden Betrag (keine negativen Differenzen)
        billable_hours = max(used_hours, total_hours)
        
        context.update({
            'total_hours': round(total_hours, 2),
            'used_hours': round(used_hours, 2),
            'total_difference': round(total_difference, 2),
            'total_amount': round(billable_hours * room_rate, 2)
        })
        
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
    })

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
    """Generiert eine konsistente Farbe für einen Benutzer"""
    colors = [
        '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEEAD',
        '#D4A5A5', '#9B59B6', '#3498DB', '#E67E22', '#2ECC71'
    ]
    return colors[user_id % len(colors)]

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'wfm/dashboard.html'

    def get(self, request, *args, **kwargs):
        # Für Assistenz und Cleaner direkt zur Arbeitszeiten-Liste weiterleiten
        if request.user.role in ['ASSISTANT', 'CLEANING']:
            return redirect('wfm:working-hours-list')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        if self.request.user.role == 'OWNER':
            # Owner-spezifische Daten...
            context['pending_vacations'] = Vacation.objects.filter(status='REQUESTED').count()
            context['pending_time_comps'] = TimeCompensation.objects.filter(status='REQUESTED').count()

        elif self.request.user.role == 'THERAPIST':
            # Therapeuten-spezifische Daten
            today = timezone.now().date()
            week_start = today - timedelta(days=today.weekday())
            week_end = week_start + timedelta(days=6)
            
            context['bookings'] = TherapistBooking.objects.filter(
                therapist=self.request.user,
                date__range=[week_start, week_end]
            ).order_by('date', 'start_time')
            
            context['week_dates'] = [week_start + timedelta(days=i) for i in range(7)]

        return context

@login_required
def delete_working_hours(request, pk):
    if request.method == 'POST':
        try:
            working_hours = WorkingHours.objects.get(pk=pk)
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
def api_therapist_booking_detail(request, pk):
    if request.user.role != 'OWNER' and request.user.role != 'THERAPIST':
        return JsonResponse({'error': 'Keine Berechtigung'}, status=403)
        
    try:
        booking = TherapistBooking.objects.select_related('therapist').get(pk=pk)
        
        # Prüfe ob der Therapeut seine eigene Buchung anschaut
        if request.user.role == 'THERAPIST' and booking.therapist != request.user:
            return JsonResponse({'error': 'Keine Berechtigung'}, status=403)
            
        return JsonResponse({
            'id': booking.id,
            'date': booking.date.isoformat(),
            'start_time': booking.start_time.strftime('%H:%M'),
            'end_time': booking.end_time.strftime('%H:%M'),
            'hours': float(booking.hours),
            'actual_hours': float(booking.actual_hours) if booking.actual_hours else None,
            'notes': booking.notes or '',
            'status': booking.status,
            'therapist': {
                'id': booking.therapist.id,
                'username': booking.therapist.username,
                'full_name': booking.therapist.get_full_name(),
                'color': booking.therapist.color
            }
        })
    except TherapistBooking.DoesNotExist:
        return JsonResponse({'error': 'Buchung nicht gefunden'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def api_therapist_booking_update(request):
    """API-Endpunkt zum Aktualisieren einer Therapeuten-Buchung"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Nur POST-Anfragen erlaubt'}, status=405)
        
    if request.user.role != 'OWNER' and request.user.role != 'THERAPIST':
        return JsonResponse({'error': 'Keine Berechtigung'}, status=403)
        
    try:
        data = json.loads(request.body)
        booking = TherapistBooking.objects.get(id=data['booking_id'])
        
        # Prüfe ob der Therapeut seine eigene Buchung bearbeitet
        if request.user.role == 'THERAPIST' and booking.therapist != request.user:
            return JsonResponse({'error': 'Keine Berechtigung'}, status=403)
        
        # Owner kann alles ändern
        if request.user.role == 'OWNER':
            booking.date = parse_date(data['date'])
            booking.start_time = datetime.strptime(data['start_time'], '%H:%M').time()
            booking.end_time = datetime.strptime(data['end_time'], '%H:%M').time()
            
        # Beide können actual_hours und notes ändern
        if data.get('actual_hours'):
            booking.actual_hours = Decimal(str(data['actual_hours']))
        booking.notes = data.get('notes', '')
        
        # Wenn actual_hours gesetzt wurden, Status auf USED setzen
        if booking.actual_hours is not None:
            booking.status = 'USED'
        
        booking.save()
        
        return JsonResponse({'success': True})
        
    except TherapistBooking.DoesNotExist:
        return JsonResponse({'error': 'Buchung nicht gefunden'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

class AssistantCalendarView(LoginRequiredMixin, TemplateView):
    template_name = 'wfm/assistant_calendar.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get current filters from request
        selected_role = self.request.GET.get('role')
        selected_employee = self.request.GET.get('employee')
        
        # Base URL for filters
        base_url = reverse('wfm:assistant-calendar')
        
        # URLs for role filters
        context['all_url'] = base_url
        context['assistant_url'] = f"{base_url}?role=ASSISTANT"
        context['cleaning_url'] = f"{base_url}?role=CLEANING"
        
        # Get employees based on role
        if selected_role == 'ASSISTANT':
            employees = CustomUser.objects.filter(role='ASSISTANT')
        elif selected_role == 'CLEANING':
            employees = CustomUser.objects.filter(role='CLEANING')
        else:
            employees = CustomUser.objects.filter(role__in=['ASSISTANT', 'CLEANING'])

        # Get selected employee if any
        if selected_employee:
            selected_employee = CustomUser.objects.filter(id=selected_employee).first()
        
        # Split employees by role for the dropdown
        context.update({
            'selected_role': selected_role,
            'selected_employee': selected_employee,
            'assistants': employees.filter(role='ASSISTANT'),
            'cleaners': employees.filter(role='CLEANING'),
            'current_year': self.request.GET.get('year', datetime.now().year),
            'current_month': self.request.GET.get('month', datetime.now().month),
        })
        
        return context

class TherapistBookingListView(LoginRequiredMixin, ListView):
    model = TherapistBooking
    template_name = 'wfm/therapist_booking_list.html'
    context_object_name = 'bookings'
    
    def get_queryset(self):
        queryset = TherapistBooking.objects.select_related('therapist')
        
        # Filter für bestimmten Therapeuten
        therapist_id = self.request.GET.get('therapist')
        if therapist_id:
            queryset = queryset.filter(therapist_id=therapist_id)
            
        # Berechne die Differenz für jede Buchung
        bookings = list(queryset)  # Konvertiere QuerySet in Liste
        for booking in bookings:
            
            if booking.actual_hours is not None:
                if booking.actual_hours > booking.hours:
                    booking.difference = float(booking.actual_hours) - float(booking.hours)
                else:
                    booking.difference = None
            else:
                booking.difference = None
                
        return sorted(bookings, key=lambda x: (-x.date.toordinal(), x.start_time))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['therapists'] = CustomUser.objects.filter(role='THERAPIST')
        context['debug'] = True  # Debug-Modus aktivieren
        
        # Hole den ausgewählten Therapeuten
        therapist_id = self.request.GET.get('therapist')
        if therapist_id:
            context['selected_therapist'] = CustomUser.objects.filter(id=therapist_id).first()
            
        return context

@login_required
def api_working_hours_update(request):
    """API-Endpunkt zum Aktualisieren einer Arbeitszeit"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Nur POST-Anfragen erlaubt'}, status=405)
        
    try:
        data = json.loads(request.body)
        working_hours = WorkingHours.objects.get(id=data['id'])
        
        if request.user.role != 'OWNER' and working_hours.employee != request.user:
            return JsonResponse({'error': 'Keine Berechtigung'}, status=403)
            
        working_hours.date = parse_date(data['date'])
        working_hours.start_time = datetime.strptime(data['start_time'], '%H:%M').time()
        working_hours.end_time = datetime.strptime(data['end_time'], '%H:%M').time()
        working_hours.break_duration = timedelta(minutes=int(data['break_duration']))
        working_hours.save()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    
    
@login_required
def api_working_hours_detail(request, pk):
    """API-Endpunkt zum Abrufen der Details einer Arbeitszeit"""
    try:
        working_hours = WorkingHours.objects.select_related('employee').get(pk=pk)
        if request.user.role != 'OWNER' and working_hours.employee != request.user:
            return JsonResponse({'error': 'Keine Berechtigung'}, status=403)
        
        # Hole Template für die Soll-Zeiten
        template = ScheduleTemplate.objects.filter(
            employee=working_hours.employee,
            weekday=working_hours.date.weekday()
        ).first()
        
        # Soll-Zeiten aus Template oder Standard
        # if template:
        soll_start = template.start_time
        soll_end = template.end_time
        soll_hours = template.hours
        # else:
        #     soll_start = time(8, 0)
        #     soll_end = time(16, 0)
        #     soll_hours = Decimal('8.0')
        
        # Berechne Ist-Stunden
        duration = datetime.combine(date.min, working_hours.end_time) - datetime.combine(date.min, working_hours.start_time)
        if working_hours.break_duration:
            duration -= working_hours.break_duration
        ist_hours = Decimal(str(duration.total_seconds() / 3600))
            
        return JsonResponse({
            'id': working_hours.id,
            'date': working_hours.date.isoformat(),
            'weekday': working_hours.date.weekday(),
            'start_time': working_hours.start_time.strftime('%H:%M'),
            'end_time': working_hours.end_time.strftime('%H:%M'),
            'break_duration': working_hours.break_duration.total_seconds() / 60 if working_hours.break_duration else 0,
            'employee': {
                'id': working_hours.employee.id,
                'username': working_hours.employee.username,
                'color': working_hours.employee.color
            },
            'soll_start': soll_start.strftime('%H:%M'),
            'soll_end': soll_end.strftime('%H:%M'),
            'soll_hours': float(soll_hours),
            'ist_hours': float(ist_hours),
            'difference': float(ist_hours - soll_hours)
        })
    except WorkingHours.DoesNotExist:
        return JsonResponse({'error': 'Arbeitszeit nicht gefunden'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def api_vacation_status(request):
    """API-Endpunkt zum Ändern des Urlaubsstatus"""
    if request.method != 'POST' or request.user.role != 'OWNER':
        return JsonResponse({'error': 'Keine Berechtigung'}, status=403)
        
    try:
        data = json.loads(request.body)
        vacation = Vacation.objects.get(id=data['vacation_id'])
        
        # Status aktualisieren
        vacation.status = data['status']
        vacation.save()
        
        # Wenn der Urlaub genehmigt wurde, aktualisiere die Urlaubstage
        if vacation.status == 'APPROVED':
            duration = (vacation.end_date - vacation.start_date).days + 1
            entitlement = VacationEntitlement.objects.get(
                employee=vacation.employee,
                year=vacation.start_date.year
            )
            entitlement.days_taken += duration
            entitlement.save()
        
        return JsonResponse({
            'success': True,
            'status': vacation.status,
            'vacation_id': vacation.id
        })
        
    except Vacation.DoesNotExist:
        return JsonResponse({
            'error': 'Urlaub nicht gefunden'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)

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
        context['therapists'] = CustomUser.objects.filter(role='THERAPIST')
        
        # Hole den ausgewählten Therapeuten
        therapist_id = self.request.GET.get('therapist')
        if therapist_id:
            context['selected_therapist'] = CustomUser.objects.filter(id=therapist_id).first()
            
        return context

@login_required
def api_therapist_calendar_events(request):
    start = request.GET.get('start')
    end = request.GET.get('end')
    therapist_id = request.GET.get('therapist')
    
    bookings = TherapistBooking.objects.select_related('therapist')
    
    if therapist_id:
        bookings = bookings.filter(therapist_id=therapist_id)
    
    if start:
        bookings = bookings.filter(date__gte=start[:10])
    if end:
        bookings = bookings.filter(date__lte=end[:10])
        
    events = []
    for booking in bookings:
        events.append({
            'id': booking.id,
            'title': f"{booking.therapist.get_full_name()} ({booking.hours}h)",
            'start': f"{booking.date}T{booking.start_time}",
            'end': f"{booking.date}T{booking.end_time}",
            'color': booking.therapist.color,
            'therapist': {
                'id': booking.therapist.id,
                'name': booking.therapist.get_full_name()
            },
            'status': booking.status
        })
        
    return JsonResponse(events, safe=False)

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