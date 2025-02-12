from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView, View
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from .models import (
    WorkingHours, 
    Vacation, 
    VacationEntitlement, 
    SickLeave,
    ScheduleTemplate,
    TimeCompensation
)
from .forms import WorkingHoursForm, VacationRequestForm, TimeCompensationForm
from django.db.models import Sum
from django.db.models.functions import ExtractMonth, ExtractYear
from datetime import datetime, timedelta
import calendar
from django.db import models
from decimal import Decimal  # Am Anfang der Datei hinzufügen
from django.http import JsonResponse
import json
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

class OwnerRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.role == 'OWNER'

@login_required
def dashboard(request):
    return render(request, 'wfm/dashboard.html')

class WorkingHoursListView(LoginRequiredMixin, ListView):
    model = WorkingHours
    template_name = 'wfm/working_hours_list.html'
    context_object_name = 'working_hours'

    def get_queryset(self):
        if self.request.user.role == 'OWNER':
            return WorkingHours.objects.all()
        return WorkingHours.objects.filter(employee=self.request.user)

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
            
            days.append({
                'date': date,
                'scheduled': scheduled_hours,
                'actual': actual_total,
                'difference': actual_total - scheduled_hours,
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

            # Prüfe ob genügend Urlaubstage verfügbar sind
            start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            
            # Berechne die Anzahl der Urlaubstage (ohne Wochenenden)
            requested_days = sum(1 for date in (start_date + timedelta(n) for n in range((end_date - start_date).days + 1))
                               if date.weekday() < 5)  # 0-4 sind Montag bis Freitag
            
            # Hole verfügbare Urlaubstage
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
                status='REQUESTED'  # Initial status
            )
            
            return JsonResponse({'success': True})
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Ungültiges JSON-Format'
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
