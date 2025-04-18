from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from decimal import Decimal
from django.forms import DateField as FormDateField
from datetime import timedelta
from django.core.exceptions import ValidationError
from datetime import datetime, date
from django.conf import settings
from django.db.models import Q, Sum
from django.utils import timezone
from django.core.exceptions import ValidationError
import decimal
from django.db.models.functions import Extract
from django.db.models.signals import pre_delete, post_save, post_delete
from django.dispatch import receiver
from django.db.models.functions import Coalesce


class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('OWNER', _('Ordinationsinhaber/in')),
        ('ASSISTANT', _('Ordinationsassistenz')),
        ('CLEANING', _('Reinigungsdienst')),  
        ('THERAPIST', _('Therapeut/in')),
    ]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='ASSISTANT')
    hourly_rate = models.DecimalField(
        max_digits=6, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name=_("Stundenlohn"),
        null=True,
        blank=True
    )
    room_rate = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name=_("Raummiete pro Stunde"),
        null=True,
        blank=True
    )
    color = models.CharField(
        max_length=7,
        default='#3498DB',
        verbose_name=_("Anzeigefarbe"),
        help_text=_("Farbe für die Anzeige in Kalendern und Listen")
    )

    # Neue persönliche Informationen
    phone = models.CharField(max_length=20, blank=True, verbose_name=_("Telefon"))
    mobile = models.CharField(max_length=20, blank=True, verbose_name=_("Mobil"))
    email = models.EmailField(blank=True, verbose_name=_("E-Mail"))
    street = models.CharField(max_length=100, blank=True, verbose_name=_("Straße"))
    zip_code = models.CharField(max_length=10, blank=True, verbose_name=_("PLZ"))
    city = models.CharField(max_length=100, blank=True, verbose_name=_("Ort"))
    date_of_birth = models.DateField(null=True, blank=True, verbose_name=_("Geburtsdatum"))
    employed_since = models.DateField(null=True, blank=True, verbose_name=_("Angestellt seit"))

    def save(self, *args, **kwargs):
        if not self.color:
            colors = [
                '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEEAD',
                '#D4A5A5', '#9B59B6', '#3498DB', '#E67E22', '#2ECC71'
            ]
            self.color = colors[self.id % len(colors)] if self.id else colors[0]
        super().save(*args, **kwargs)

    def get_available_timecomp_hours(self):
        """Berechnet die verfügbaren Stunden für Zeitausgleich"""
        # Summe aller finalisierten Zeitausgleichsstunden
        total_hours = OvertimeAccount.objects.filter(
            employee=self,
            is_finalized=True
        ).aggregate(total=Sum('hours_for_timecomp'))['total'] or 0

        # Abzüglich bereits genutzter Stunden (genehmigte Zeitausgleiche)
        used_hours = TimeCompensation.objects.filter(
            employee=self,
            status='APPROVED'
        ).count() * 8  # 8 Stunden pro Tag

        return total_hours - used_hours

class ScheduleTemplate(models.Model):
    """Vorlage für die Soll-Arbeitszeiten"""
    WEEKDAY_CHOICES = [
        (0, _('Montag')),
        (1, _('Dienstag')),
        (2, _('Mittwoch')),
        (3, _('Donnerstag')),
        (4, _('Freitag')),
        (5, _('Samstag')),
        (6, _('Sonntag')),
    ]
    
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE, verbose_name=_("Mitarbeiter"))
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES, verbose_name=_("Wochentag"))
    start_time = models.TimeField(verbose_name=_("Beginn"))
    end_time = models.TimeField(verbose_name=_("Ende"))
    break_duration = models.DurationField(null=True, blank=True, verbose_name=_("Pause"), default=timedelta(minutes=0))
    valid_from = models.DateField(verbose_name=_("Gültig ab"), default=date.today)
    
    class Meta:
        ordering = ['-valid_from', 'weekday']
        verbose_name = _("Arbeitszeit-Vorlage")
        verbose_name_plural = _("Arbeitszeit-Vorlagen")

    @property
    def hours(self):
        """Berechnet die Stunden zwischen Start- und Endzeit, abzüglich Pause"""
        if not self.start_time or not self.end_time:
            return Decimal('0.00')
            
        start = datetime.combine(date.min, self.start_time)
        end = datetime.combine(date.min, self.end_time)
        duration = end - start
        
        # Ziehe die Pause ab, falls vorhanden
        if self.break_duration:
            duration = duration - self.break_duration
            
        # Konvertiere zu Dezimalstunden mit 2 Nachkommastellen
        return Decimal(str(duration.total_seconds() / 3600)).quantize(Decimal('0.01'))

    def __str__(self):
        return f"{self.employee.username} - {self.get_weekday_display()} (ab {self.valid_from})"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        

        
        # 2. Speichere das aktuelle Template
        super().save(*args, **kwargs)
        
        # 3. Lösche alle WorkingHours für diesen Wochentag ab valid_from
        workinghours_to_delete = WorkingHours.objects.filter(
            employee=self.employee,
            date__gte=self.valid_from
        ).filter(
            # Filtere manuell nach Wochentag
            date__week_day=(self.weekday + 2 if self.weekday < 6 else 1)
        )
        
        workinghours_to_delete.delete()
        
        # 4. Erstelle neue WorkingHours
        start_date = self.valid_from
        end_date = start_date + timedelta(days=3*365)
        
        # 2. Erstelle neue WorkingHours für jeden passenden Tag
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() == self.weekday:
                # Prüfe ob es einen Urlaub/Krankenstand/Feiertag gibt
                has_vacation = Vacation.objects.filter(
                    employee=self.employee,
                    start_date__lte=current_date,
                    end_date__gte=current_date,
                    status='APPROVED'
                ).exists()
                
                has_sick_leave = SickLeave.objects.filter(
                    employee=self.employee,
                    start_date__lte=current_date,
                    end_date__gte=current_date
                ).exists()
                
                is_closure_day = ClosureDay.objects.filter(
                    date=current_date
                ).exists()
                
                # Erstelle WorkingHours nur wenn kein Urlaub/Krankenstand/Feiertag
                if not (has_vacation or has_sick_leave or is_closure_day):
                    # Berechne die Stunden aus dem Template
                    start = datetime.combine(date.min, self.start_time)
                    end = datetime.combine(date.min, self.end_time)
                    duration = end - start
                    if self.break_duration:
                        duration -= self.break_duration
                    hours = Decimal(str(duration.total_seconds() / 3600))

                    # Erstelle den WorkingHours Eintrag
                    WorkingHours.objects.create(
                        employee=self.employee,
                        date=current_date,
                        start_time=self.start_time,
                        end_time=self.end_time,
                        break_duration=self.break_duration,

                    )
            
            current_date += timedelta(days=1)

    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError('Endzeit muss nach Startzeit liegen')

class GermanDateField(models.DateField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def formfield(self, **kwargs):
        defaults = {
            'form_class': FormDateField,
            'input_formats': ['%d.%m.%Y', '%Y-%m-%d']
        }
        defaults.update(kwargs)
        return super().formfield(**defaults)

class WorkingHours(models.Model):
    """Tatsächlich geleistete Arbeitsstunden"""
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    break_duration = models.DurationField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Soll-Zeiten
    # soll_start = models.TimeField(null=True, blank=True)
    # soll_end = models.TimeField(null=True, blank=True)
    # soll_hours = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    ist_hours = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    vacation = models.ForeignKey('Vacation', on_delete=models.SET_NULL, null=True, blank=True, related_name='working_hours')
    time_comp = models.ForeignKey('TimeCompensation', on_delete=models.SET_NULL, null=True, blank=True, related_name='working_hours')
    sick_leave = models.ForeignKey('SickLeave', on_delete=models.SET_NULL, null=True, blank=True, related_name='working_hours')
    is_paid = models.BooleanField(default=False)
    paid_date = models.DateField(null=True, blank=True)

    # def save(self, *args, **kwargs):
    #     # Berechne Ist-Stunden
    #     if self.start_time and self.end_time:
    #         start = datetime.combine(self.date, self.start_time)
    #         end = datetime.combine(self.date, self.end_time)
    #         duration = end - start

    #         if self.break_duration:
    #             duration -= self.break_duration
            
    #         self.ist_hours = Decimal(str(duration.total_seconds() / 3600))

    #     else:
    #         self.ist_hours = Decimal('0')

    #     # Berechne Soll-Stunden
    #     if self.soll_start and self.soll_end:
    #         start = datetime.combine(self.date, self.soll_start)
    #         end = datetime.combine(self.date, self.soll_end)
    #         duration = end - start
    #         self.soll_hours = Decimal(str(duration.total_seconds() / 3600))
    #     else:
    #         self.soll_hours = Decimal('0')

    #     super().save(*args, **kwargs)

    @property
    def difference(self):
        """Differenz zwischen Ist- und Soll-Stunden"""
        ist = self.ist_hours or Decimal('0')
        soll = self.soll_hours or Decimal('0')
        return ist - soll

    def get_template_times(self):
        """Holt die Soll-Zeiten aus dem Template"""
        template = ScheduleTemplate.objects.filter(
            employee=self.employee,
            weekday=self.date.weekday(),
            valid_from__lte=self.date
        ).order_by('-valid_from').first()
        
        if template:
            self.soll_start = template.start_time
            self.soll_end = template.end_time
            self.save()

    class Meta:
        verbose_name = _('Arbeitszeit')
        verbose_name_plural = _('Arbeitszeiten')
        ordering = ['-date', 'start_time']
        unique_together = ['employee', 'date']

    def save(self, *args, **kwargs):
        if not self._state.adding:  # Wenn es ein Update ist
            original = WorkingHours.objects.get(pk=self.pk)
            if original.is_paid:
                # Erlaube nur Änderungen an is_paid und paid_date
                protected_fields = ['start_time', 'end_time', 'break_duration', 'date', 'employee_id']
                for field in protected_fields:
                    if getattr(self, field) != getattr(original, field):
                        raise ValidationError(_("Bezahlte Arbeitszeiten können nicht mehr geändert werden."))
                
                # Toggle is_paid und paid_date
                if self.is_paid != original.is_paid:
                    self.paid_date = timezone.now().date() if self.is_paid else None
                
        super().save(*args, **kwargs)

        # Berechne Überstunden
        if self.start_time and self.end_time:
            # Berechne Ist-Stunden
            start = datetime.combine(date.min, self.start_time)
            end = datetime.combine(date.min, self.end_time)
            duration = end - start
            if self.break_duration:
                duration -= self.break_duration
            ist_hours = Decimal(str(round(duration.total_seconds() / 3600, 2)))

            # Hole Template und berechne Soll-Stunden
            template = ScheduleTemplate.objects.filter(
                employee=self.employee,
                weekday=self.date.weekday(),
                valid_from__lte=self.date
            ).order_by('-valid_from').first()

            if template:
                template_start = datetime.combine(date.min, template.start_time)
                template_end = datetime.combine(date.min, template.end_time)
                template_duration = template_end - template_start
                if template.break_duration:
                    template_duration -= template.break_duration
                template_hours = Decimal(str(round(template_duration.total_seconds() / 3600, 2)))
            else:
                template_hours = Decimal('0')

            # Erstelle/Aktualisiere OvertimeEntry
            overtime_hours = ist_hours - template_hours
            print(f"Overtimehours: {overtime_hours}")
            if overtime_hours != 0:
                OvertimeEntry.objects.update_or_create(
                    employee=self.employee,
                    date=self.date,
                    defaults={
                    'hours': overtime_hours,
                    'working_hours': self
                }
            )

    @classmethod
    def get_working_hours_for_date(cls, employee, date):
        """Holt oder berechnet die Arbeitszeiten für einen bestimmten Tag"""
        # Prüfe auf existierende Einträge
        existing = cls.objects.filter(employee=employee, date=date).first()
        if existing:
            return existing

        # Prüfe auf genehmigte Urlaube
        has_vacation = Vacation.objects.filter(
            employee=employee,
            start_date__lte=date,
            end_date__gte=date,
            status='APPROVED'  # Nur genehmigte Urlaube berücksichtigen
        ).exists()
        
        if has_vacation:
            return None

        # Prüfe auf Krankenstand
        has_sick_leave = SickLeave.objects.filter(
            employee=employee,
            start_date__lte=date,
            end_date__gte=date
        ).exists()
        
        if has_sick_leave:
            return None

        # Prüfe auf Schließtage
        is_closure_day = ClosureDay.is_closure_day(date)
        if is_closure_day:
            return None

        # Hole Template für diesen Wochentag
        template = ScheduleTemplate.objects.filter(
            employee=employee,
            weekday=date.weekday(),
            valid_from__lte=date
        ).order_by('-valid_from').first()

        if not template:
            return None

        # Erstelle WorkingHours aus Template
        return cls.objects.create(
            employee=employee,
            date=date,
            start_time=template.start_time,
            end_time=template.end_time,
            break_duration=template.break_duration
        )

class Vacation(models.Model):
    """Urlaubsverwaltung"""
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    hours = models.DecimalField(  # Hinzufügen des Feldes mit Default-Wert
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text=_("Berechnete Urlaubsstunden")
    )
    status = models.CharField(
        max_length=10,
        choices=[
            ('REQUESTED', _('Beantragt')),
            ('APPROVED', _('Genehmigt')),
            ('REJECTED', _('Abgelehnt')),
        ],
        default='REQUESTED'
    )
    notes = models.TextField(blank=True)

    def calculate_vacation_hours(self):
        """Berechnet die Urlaubsstunden basierend auf den Soll-Arbeitszeiten"""
        total_hours = Decimal('0')
        current_date = self.start_date
        
        while current_date <= self.end_date:
            # Überspringe Wochenenden
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue
                
            # Überspringe Schließtage
            closure = ClosureDay.objects.filter(
                models.Q(
                    date=current_date,
                    is_recurring=False
                ) |
                models.Q(
                    date__month=current_date.month,
                    date__day=current_date.day,
                    is_recurring=True
                )
            ).first()
            
            if closure:
                current_date += timedelta(days=1)
                continue
            
            # Hole Schedule für diesen Tag
            schedule = ScheduleTemplate.objects.filter(
                employee=self.employee,
                weekday=current_date.weekday(),
                valid_from__lte=current_date
            ).order_by('-valid_from').first()
            
            if schedule:
                # Berechne Stunden für diesen Tag
                start = datetime.combine(date.min, schedule.start_time)
                end = datetime.combine(date.min, schedule.end_time)
                hours = Decimal(str((end - start).total_seconds() / 3600))
                total_hours += hours
            
            current_date += timedelta(days=1)
            
        return total_hours

    def check_vacation_hours_available(self):
        """Prüft ob genügend Urlaubsstunden verfügbar sind"""
        entitlement = VacationEntitlement.objects.filter(
            employee=self.employee,
            year=self.start_date.year
        ).first()
        
        if not entitlement:
            return False
            
        needed_hours = self.calculate_vacation_hours()
        remaining_hours = entitlement.get_remaining_hours()
        
        return needed_hours <= remaining_hours

    def clean(self):
        super().clean()
        if self.status == 'APPROVED' and not self.check_vacation_hours_available():
            raise ValidationError(_('Nicht genügend Urlaubsstunden verfügbar'))

    def save(self, *args, **kwargs):
        # Prüfe ob es eine Statusänderung zu REJECTED gibt und notes leer ist
        if self.pk:
            old_instance = Vacation.objects.get(pk=self.pk)
            if old_instance.status != 'REJECTED' and self.status == 'REJECTED' and not self.notes:
                raise ValidationError(_('Bei Ablehnung muss eine Begründung angegeben werden'))

        # Berechne die Stunden vor dem Speichern
        self.hours = self.calculate_vacation_hours()
        
        # Lösche/Erstelle WorkingHours nur bei APPROVED Status
        if self.pk:
            old_instance = Vacation.objects.get(pk=self.pk)
            if (old_instance.status in ['REQUESTED', 'PENDING'] and 
                self.status == 'APPROVED'):
                # Lösche WorkingHours für die Urlaubstage
                current_date = self.start_date
                while current_date <= self.end_date:
                    if current_date.weekday() < 5:  # Nur Werktage
                        WorkingHours.objects.filter(
                            employee=self.employee,
                            date=current_date
                        ).delete()
                    current_date += timedelta(days=1)
        
        super().save(*args, **kwargs)
    
    class Meta:
        ordering = ['-start_date']
        verbose_name = _('Urlaub')
        verbose_name_plural = _('Urlaube')

class VacationEntitlement(models.Model):
    """Jahresurlaub"""
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    year = models.IntegerField()
    total_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0)  # Statt total_days
    
    class Meta:
        unique_together = ('employee', 'year')
        ordering = ['-year']
        verbose_name = _('Urlaubsanspruch')
        verbose_name_plural = _('Urlaubsansprüche')

    def get_remaining_hours(self):
        used_hours = Decimal('0')
        approved_vacations = Vacation.objects.filter(
            employee=self.employee,
            start_date__year=self.year,
            status='APPROVED'
        )
        
        for vacation in approved_vacations:
            used_hours += vacation.calculate_vacation_hours()
            
        return self.total_hours - used_hours




# class MonthlyReport(models.Model):
#     """Monatlicher Abrechnungsbericht"""
#     employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
#     month = models.IntegerField(
#         validators=[MinValueValidator(1), MaxValueValidator(12)],
#         verbose_name="Monat"
#     )
#     year = models.IntegerField(verbose_name="Jahr")
#     total_hours = models.DecimalField(
#         max_digits=6,
#         decimal_places=2,
#         verbose_name="Gesamtstunden"
#     )
#     total_amount = models.DecimalField(
#         max_digits=8,
#         decimal_places=2,
#         verbose_name="Gesamtbetrag"
#     )
#     generated_at = models.DateTimeField(auto_now_add=True)
    
#     class Meta:
#         unique_together = ['employee', 'month', 'year']

class TimeCompensation(models.Model):
    """Zeitausgleich"""
    STATUS_CHOICES = [
        ('REQUESTED', 'Angefragt'),
        ('APPROVED', 'Genehmigt'),
        ('REJECTED', 'Abgelehnt'),
    ]
    
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE, verbose_name=_('Mitarbeiter'))
    date = models.DateField(verbose_name=_('Datum'))
    hours = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=8,
        verbose_name=_('Stunden'),
        help_text=_('Wird automatisch aus dem Arbeitsplan berechnet')
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='REQUESTED', verbose_name=_('Status'))
    notes = models.TextField(blank=True, verbose_name=_('Anmerkungen'))

    def calculate_scheduled_hours(self):
        """Berechnet die geplanten Arbeitsstunden für den Tag"""
        schedule = ScheduleTemplate.objects.filter(
            employee=self.employee,
            weekday=self.date.weekday(),
            valid_from__lte=self.date
        ).order_by('-valid_from').first()

        if schedule:
            if schedule.start_time and schedule.end_time:
                # Berechne die Stunden aus Start- und Endzeit
                start = datetime.combine(self.date, schedule.start_time)
                end = datetime.combine(self.date, schedule.end_time)
                duration = end - start
                return Decimal(duration.total_seconds() / 3600)
            return schedule.hours
        return Decimal('0')

    def save(self, *args, **kwargs):
        #FIXME: Eintrag wird doppelt gespeichert
        # Setze die Stunden basierend auf dem Arbeitsplan, wenn es ein neuer Eintrag ist
        if not self.pk:
            self.hours = self.calculate_scheduled_hours()
            
        # Prüfe ob es eine Statusänderung von REQUESTED/PENDING zu APPROVED gibt
        if self.pk:
            old_instance = TimeCompensation.objects.get(pk=self.pk)
            if (old_instance.status in ['REQUESTED', 'PENDING'] and 
                self.status == 'APPROVED'):
                # Lösche WorkingHours für den Tag des Zeitausgleichs
                WorkingHours.objects.filter(
                    employee=self.employee,
                    date=self.date
                ).delete()
        
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-date']
        verbose_name = _('Zeitausgleich')
        verbose_name_plural = _('Zeitausgleiche')

    def __str__(self):
        return f"{self.employee} - {self.date} ({self.hours}h)"

    def check_hours_available(self):
        """Prüft ob genügend Zeitausgleichsstunden verfügbar sind"""
        # Hole alle finalisierten Überstundenkonten
        overtime_accounts = OvertimeAccount.objects.filter(
            employee=self.employee,
            hours_for_timecomp__gt=0  # Nur Konten mit umgebuchten Stunden
        )
        
        # Berechne verfügbare Stunden
        total_available = sum(account.hours_for_timecomp for account in overtime_accounts)
        
        # Berechne bereits verwendete Stunden
        used_hours = TimeCompensation.objects.filter(
            employee=self.employee,
            status='APPROVED'
        ).aggregate(total=Sum('hours'))['total'] or 0
        
        # Berechne noch verfügbare Stunden
        remaining_hours = total_available - used_hours
        
        return self.hours <= remaining_hours

class TherapistBooking(models.Model):
    """Raumbuchungen für Therapeuten"""
    therapist = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    hours = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True)
    actual_hours = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True)
    difference_hours = models.DecimalField(  # Neues Feld
        max_digits=4, 
        decimal_places=2, 
        blank=True, 
        null=True,
        verbose_name=_('Stundendifferenz'),
        help_text=_('Differenz zwischen geplanten und tatsächlichen Stunden')
    )
    is_paid = models.BooleanField(
        default=False,
        verbose_name=_('Bezahlt'),
        help_text=_('Gibt an, ob die Mehrstunden bezahlt wurden')
    )
    paid_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_('Bezahlt am'),
        help_text=_('Datum der Bezahlung der Mehrstunden')
    )
    notes = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        # Berechne hours wenn nicht gesetzt
        if not self.hours and self.start_time and self.end_time:
            start = datetime.combine(date.min, self.start_time)
            end = datetime.combine(date.min, self.end_time)
            duration = end - start
            self.hours = Decimal(str(duration.total_seconds() / 3600))

        # Wenn actual_hours nicht gesetzt ist, setze es auf hours
        if self.actual_hours is None and self.hours:
            self.actual_hours = self.hours

        # Berechne die Differenz
        if self.actual_hours is not None:
            if self.actual_hours > self.hours:
                # Wenn mehr Stunden verwendet als gebucht wurden
                self.difference_hours = self.actual_hours - self.hours
                self.is_paid = False
            else:
                self.difference_hours = None  # Keine Differenz wenn actual_hours <= hours
                
        if not self._state.adding:  # Wenn es ein Update ist
            original = TherapistBooking.objects.get(pk=self.pk)
            if original.is_paid:
                # Erlaube nur Änderungen an is_paid und paid_date
                protected_fields = ['therapist', 'date', 'start_time', 'end_time', 'hours', 'actual_hours']
                for field in protected_fields:
                    if getattr(self, field) != getattr(original, field):
                        raise ValidationError(_("Bezahlte Buchungen können nicht mehr geändert werden."))
                
                # Toggle is_paid und paid_date
                if self.is_paid != original.is_paid:
                    self.paid_date = timezone.now().date() if self.is_paid else None
        super().save(*args, **kwargs)

    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError('Endzeit muss nach Startzeit liegen')

    def __str__(self):
        return f"{self.therapist.username} - {self.date} ({self.start_time}-{self.end_time})"


    class Meta:
        ordering = ['-date']
        verbose_name = _('Therapeutenbuchung')
        verbose_name_plural = _('Therapeutenbuchungen')


class TherapistScheduleTemplate(models.Model):
    """Vorlage für die Standard-Raumbuchungen"""
    WEEKDAY_CHOICES = ScheduleTemplate.WEEKDAY_CHOICES
    
    therapist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'THERAPIST'},
        verbose_name=_('Therapeut')
    )
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    valid_from = models.DateField(verbose_name=_("Gültig ab"), default=date.today)
    hours = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        blank=True,
        null=True
    )

    class Meta:
        ordering = ['-valid_from', 'weekday', 'start_time']
        verbose_name = _('Therapeuten-Stundenvorlage')
        verbose_name_plural = _('Therapeuten-Stundenvorlagen')
        
    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError('Endzeit muss nach Startzeit liegen')
        
        # Berechne die Stunden bei Änderungen
        if self.start_time and self.end_time:
            start = datetime.combine(date.today(), self.start_time)
            end = datetime.combine(date.today(), self.end_time)
            duration = end - start
            self.hours = Decimal(str(duration.total_seconds() / 3600))
            
    def create_future_bookings(self):
        """Erstellt Buchungen für die nächsten 3 Jahre basierend auf diesem Template"""
        # Verwende immer valid_from als Startdatum, unabhängig vom aktuellen Datum
        start_date = self.valid_from
        end_date = start_date + timedelta(days=3*365)  # 3 Jahre
        current_date = start_date
        
        while current_date <= end_date:
            if current_date.weekday() == self.weekday:
                # Prüfe ob bereits eine Buchung existiert
                booking_exists = TherapistBooking.objects.filter(
                    date=current_date,
                    therapist=self.therapist
                ).exists()
                
                if not booking_exists:
                    # Berechne die Stunden mit Minuten
                    start = datetime.combine(date.min, self.start_time)
                    end = datetime.combine(date.min, self.end_time)
                    duration = end - start
                    # Konvertiere zu Dezimalstunden mit 2 Nachkommastellen
                    hours = Decimal(str(duration.total_seconds() / 3600)).quantize(Decimal('0.01'))

                    TherapistBooking.objects.create(
                        therapist=self.therapist,
                        date=current_date,
                        start_time=self.start_time,
                        end_time=self.end_time,
                        hours=hours,
                        actual_hours=hours,  # Initial gleich den gebuchten Stunden
                        difference_hours=0,
                        is_paid=False,
                        paid_date=None
                    )
            
            current_date += timedelta(days=1)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Erstelle Buchungen nach dem Speichern des Templates
        self.create_future_bookings()

    def __str__(self):
        return f"{self.therapist} - {self.get_weekday_display()} ({self.start_time}-{self.end_time})"

class UserDocument(models.Model):
    def get_upload_path(self, filename):
        # Generiert: user_documents/username/filename
        return f'user_documents/{self.user.username}/{filename}'

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='documents')
    file = models.FileField(upload_to=get_upload_path)
    display_name = models.CharField(max_length=255, verbose_name=_("Anzeigename"), default="")
    original_filename = models.CharField(max_length=255, null=True, blank=True, verbose_name=_("Originaldatei"))
    uploaded_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, verbose_name=_("Notizen"), default="")

    def save(self, *args, **kwargs):
        # Wenn das Dokument neu ist (keine ID) und kein display_name gesetzt ist
        if not self.id and not self.display_name:
            self.display_name = self.file.name
        
        # Speichere den Original-Dateinamen beim ersten Speichern
        if not self.id and not self.original_filename:
            self.original_filename = self.file.name
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.display_name} ({self.user.get_full_name()})"
    
    class Meta:
        verbose_name = _("Dokument")
        verbose_name_plural = _("Dokumente")
        ordering = ['-uploaded_at']

class SickLeave(models.Model):
    STATUS_CHOICES = [
        ('SUBMITTED', _('Krankmeldung vorgelegt')),
        ('PENDING', _('Keine Krankmeldung')),
    ]
    
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sick_leaves'
    )
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    notes = models.TextField(blank=True)
    document = models.OneToOneField( 
        UserDocument, 
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sick_leave'
    )

    def __str__(self):
        return f"{self.employee} - {self.start_date} bis {self.end_date}"

    def save(self, *args, **kwargs):
        # Bei Krankmeldungen immer die WorkingHours löschen
        if self.pk:  # Wenn es ein existierender Eintrag ist
            old_instance = SickLeave.objects.get(pk=self.pk)
            if (old_instance.status in ['PENDING'] and 
                self.status == 'SUBMITTED'):
                # Lösche WorkingHours für die Krankheitstage
                current_date = self.start_date
                while current_date <= self.end_date:
                    if current_date.weekday() < 5:  # Nur Werktage
                        WorkingHours.objects.filter(
                            employee=self.employee,
                            date=current_date
                        ).delete()
                    current_date += timedelta(days=1)
        
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-start_date']
        verbose_name = _('Krankenstand')
        verbose_name_plural = _('Krankenstände')


class OvertimeEntry(models.Model):
    """Einzelne Überstundeneinträge pro Tag"""
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    date = models.DateField()
    hours = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        help_text=_("Positive Werte = Überstunden, Negative = Minderstunden")
    )
    working_hours = models.ForeignKey(
        'WorkingHours', 
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    is_locked = models.BooleanField(
        default=False,
        help_text=_("Gesperrt wenn zur Auszahlung markiert")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']
        unique_together = ['employee', 'date']
        verbose_name = _("Überstundeneintrag")
        verbose_name_plural = _("Überstundeneinträge")

    def __str__(self):
        return f"{self.employee.get_full_name()} - {self.date}: {self.hours:+.2f}h"

class OvertimeAccount(models.Model):
    """Überstundenkonto für Auszahlungen und Gesamtübersicht"""
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    month = models.IntegerField()
    year = models.IntegerField()
    balance = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    current_balance = models.DecimalField(
        max_digits=8, 
        decimal_places=2, 
        default=0,
        help_text=_("Aktuelle Gesamtbilanz inklusive aller Änderungen")
    )
    hours_for_payment = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    payment_locked_until = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    @classmethod
    def get_current_balance(cls, employee):
        """Holt die aktuelle Überstundenbilanz des Mitarbeiters"""
        latest_account = cls.objects.filter(
            employee=employee
        ).order_by('-year', '-month').first()
        
        return latest_account.current_balance if latest_account else Decimal('0.00')

    @classmethod
    def get_monthly_balance(cls, employee, year, month):
        """Holt die Überstunden für einen bestimmten Monat"""
        return OvertimeEntry.objects.filter(
            employee=employee,
            date__year=year,
            date__month=month
        ).aggregate(total=Sum('hours'))['total'] or Decimal('0')

    def mark_for_payment(self, hours_to_pay, payment_date=None):
        """Markiert Überstunden zur Auszahlung"""
        if not payment_date:
            payment_date = timezone.now().date()

        # Prüfe ob genug Stunden verfügbar
        available_hours = self.calculate_available_hours()
        if hours_to_pay > available_hours:
            raise ValidationError(_("Nicht genügend Überstunden verfügbar"))

        # Markiere Überstunden als gesperrt bis zum aktuellen Datum
        OvertimeEntry.objects.filter(
            employee=self.employee,
            date__lte=payment_date,
            is_locked=False
        ).update(is_locked=True)

        self.hours_for_payment = hours_to_pay
        self.payment_locked_until = payment_date
        self.save()

    def calculate_available_hours(self):
        """Berechnet verfügbare Überstunden (nicht gesperrt/ausgezahlt)"""
        return OvertimeEntry.objects.filter(
            employee=self.employee,
            is_locked=False
        ).aggregate(total=Sum('hours'))['total'] or Decimal('0')

    @classmethod
    def update_monthly_balance(cls, employee, year, month):
        """Aktualisiert die monatliche Bilanz aus den Einzeleinträgen"""
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        total_hours = OvertimeEntry.objects.filter(
            employee=employee,
            date__range=(start_date, end_date)
        ).aggregate(total=Sum('hours'))['total'] or Decimal('0')

        account, _ = cls.objects.update_or_create(
            employee=employee,
            year=year,
            month=month,
            defaults={
                'balance': total_hours,
                'current_balance': total_hours  # Setze initial gleich
            }
        )
        return account

    def save(self, *args, **kwargs):
        if not self.current_balance:
            self.current_balance = self.balance
        if not self.id:  # Wenn neuer Eintrag
            self.created_at = timezone.now()
        self.updated_at = timezone.now()  # Immer aktualisieren
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ('employee', 'month', 'year')
        ordering = ['-year', '-month']
        verbose_name = _("Überstundenkonto")
        verbose_name_plural = _("Überstundenkonten")

class OvertimePayment(models.Model):
    employee = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='overtime_payments'
    )
    hours_for_payment = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('Betrag'),
        help_text=_('Berechneter Auszahlungsbetrag')
    )
    is_paid = models.BooleanField(
        default=False,
        verbose_name=_('Bezahlt')
    )
    paid_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Bezahlt am')
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Überstunden-Auszahlung')
        verbose_name_plural = _('Überstunden-Auszahlungen')
        ordering = ['-paid_date', 'employee']
        unique_together = []

    def calculate_amount(self):
        """Berechnet den Auszahlungsbetrag basierend auf dem Stundenlohn"""
        if self.employee.hourly_rate:
            self.amount = self.hours_for_payment * self.employee.hourly_rate
        else:
            self.amount = Decimal('0.00')

class ClosureDay(models.Model):
    CLOSURE_TYPES = [
        ('HOLIDAY', _('Gesetzlicher Feiertag')),
        ('VACATION', _('Ordinationsurlaub')),
        ('TRAINING', _('Fortbildung')),
        ('OTHER', _('Sonstiges'))
    ]

    date = models.DateField(_('Datum'))
    name = models.CharField(_('Bezeichnung'), max_length=100)
    type = models.CharField(
        _('Art der Schließung'),
        max_length=20,
        choices=CLOSURE_TYPES,
        default='OTHER'
    )
    is_recurring = models.BooleanField(
        _('Jährlich wiederkehrend'),
        default=False,
        help_text=_('Gilt für gesetzliche Feiertage')
    )
    notes = models.TextField(_('Notizen'), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date']
        verbose_name = _('Schließtag')
        verbose_name_plural = _('Schließtage')
        unique_together = ['date', 'type']  # Verhindert doppelte Einträge

    def __str__(self):
        return f"{self.date.strftime('%d.%m.%Y')}: {self.name}"

    @classmethod
    def is_closure_day(cls, check_date):
        """Prüft ob ein Datum ein Schließtag ist"""
        # Prüfe einmalige Schließtage
        if cls.objects.filter(date=check_date).exists():
            return True
            
        # Prüfe wiederkehrende Feiertage (nur Monat und Tag)
        return cls.objects.filter(
            is_recurring=True,
            date__month=check_date.month,
            date__day=check_date.day
        ).exists()

    class Meta:
        ordering = ['date']
        verbose_name = _('Schließtag')
        verbose_name_plural = _('Schließtage')
        unique_together = ['date', 'type']  # Verhindert doppelte Einträge

@receiver(pre_delete, sender=WorkingHours)
def handle_working_hours_deletion(sender, instance, **kwargs):
    """Handler für das Löschen von WorkingHours"""
    # Hole das passende Template für diesen Tag
    template = ScheduleTemplate.objects.filter(
        employee=instance.employee,
        weekday=instance.date.weekday(),
        valid_from__lte=instance.date
    ).order_by('-valid_from').first()
    
    if template:
        # Berechne Soll-Stunden aus Template
        template_start = datetime.combine(date.min, template.start_time)
        template_end = datetime.combine(date.min, template.end_time)
        template_duration = template_end - template_start
        if template.break_duration:
            template_duration -= template.break_duration
        soll_hours = Decimal(str(template_duration.total_seconds() / 3600))
        
        # Erstelle OvertimeEntry mit negativen Stunden
        OvertimeEntry.objects.update_or_create(
            employee=instance.employee,
            date=instance.date,
            defaults={
                'hours': -soll_hours,  # Negative Stunden da keine Arbeitszeit
                'working_hours': None  # WorkingHours wird gelöscht
            }
        )

class MonthlyWage(models.Model):
    employee = models.ForeignKey(
        'CustomUser',
        on_delete=models.CASCADE,
        related_name='monthly_wages'
    )
    year = models.IntegerField()
    month = models.IntegerField()
    total_scheduled_hours = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0')
    )
    total_hours = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0')
    )
    difference_hours = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0')
    )
    wage = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0')
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_paid = models.BooleanField(default=False)
    paid_date = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = _('Monatliches Gehalt')
        verbose_name_plural = _('Monatliche Gehälter')
        unique_together = ['employee', 'year', 'month']
        ordering = ['-year', '-month', 'employee']

    def calculate_wage(self):
        """Berechnet den Monatslohn basierend auf den Arbeitsstunden"""
        monthly_working_hours = WorkingHours.objects.filter(
            employee=self.employee,
            date__year=self.year,
            date__month=self.month
        ).aggregate(
            total_hours=models.Sum(
                models.ExpressionWrapper(
                    models.F('end_time') - models.F('start_time'),
                    output_field=models.DurationField()
                )
            )
        )['total_hours'] or timedelta()

        # Konvertiere zu Dezimalstunden
        self.total_hours = Decimal(str(monthly_working_hours.total_seconds() / 3600))
        
        # monthly_scheduled_hours = ScheduleTemplate.objects.filter(
        #     employee=self.employee,
        #     valid_from__year=self.year,
        #     valid_from__month=self.month
        # ).aggregate(
        #     total_hours=models.Sum(
        #         models.ExpressionWrapper(
        #             models.F('end_time') - models.F('start_time'),
        #             output_field=models.DurationField()
        #         )
        #     )
        # )['total_scheduled_hours'] or timedelta()

        # # Konvertiere zu Dezimalstunden
        # self.total_scheduled_hours = Decimal(str(monthly_scheduled_hours.total_seconds() / 3600))

        # # Berechne die Differenz zwischen geplanten und tatsächlichen Stunden
        # self.difference_hours = self.total_scheduled_hours - self.total_hours   

        # Prüfe ob hourly_rate existiert
        if self.employee.hourly_rate is not None:
            self.wage = self.total_hours * self.employee.hourly_rate
        else:
            self.wage = Decimal('0.00')
        
        self.save()

    def save(self, *args, **kwargs):
        if not self._state.adding:  # Wenn es ein Update ist
            original = MonthlyWage.objects.get(pk=self.pk)
            if original.is_paid:
                # Erlaube nur Änderungen an is_paid und paid_date
                protected_fields = ['total_hours', 'wage', 'year', 'month', 'employee_id']
                for field in protected_fields:
                    if getattr(self, field) != getattr(original, field):
                        raise ValidationError(_("Bezahlte Gehälter können nicht mehr geändert werden."))
                
                # Toggle is_paid und paid_date
                if self.is_paid != original.is_paid:
                    self.paid_date = timezone.now().date() if self.is_paid else None
                
        super().save(*args, **kwargs)

@receiver(post_save, sender=WorkingHours)
def update_monthly_wage_on_working_hours_change(sender, instance, **kwargs):
    """Aktualisiert das MonthlyWage wenn WorkingHours geändert werden"""
    monthly_wage, created = MonthlyWage.objects.get_or_create(
        employee=instance.employee,
        year=instance.date.year,
        month=instance.date.month
    )
    monthly_wage.calculate_wage()

@receiver(post_delete, sender=WorkingHours)
def update_monthly_wage_on_working_hours_delete(sender, instance, **kwargs):
    """Aktualisiert das MonthlyWage wenn WorkingHours gelöscht werden"""
    try:
        monthly_wage = MonthlyWage.objects.get(
            employee=instance.employee,
            year=instance.date.year,
            month=instance.date.month
        )
        monthly_wage.calculate_wage()
    except MonthlyWage.DoesNotExist:
        pass  # Wenn kein MonthlyWage existiert, muss nichts aktualisiert werden

@receiver(post_save, sender=OvertimeEntry)
def update_overtime_account(sender, instance, created, **kwargs):
    """Aktualisiert das OvertimeAccount wenn ein OvertimeEntry erstellt/geändert wird"""
    entry_date = instance.date  # Nutze das Datum des Eintrags
    
    # Hole oder erstelle OvertimeAccount für den Monat des Eintrags
    account, created = OvertimeAccount.objects.get_or_create(
        employee=instance.employee,
        year=entry_date.year,
        month=entry_date.month,
        defaults={
            'balance': Decimal('0.00'),
            'current_balance': Decimal('0.00')
        }
    )
    
    # Berechne die neue Gesamtbilanz für alle nicht gesperrten Einträge
    total_balance = OvertimeEntry.objects.filter(
        employee=instance.employee,
        is_locked=False  # Nur nicht gesperrte Einträge
    ).aggregate(
        total=Coalesce(Sum('hours'), Decimal('0.00'))
    )['total']
    
    # Berechne die Monatsbilanz
    month_balance = OvertimeEntry.objects.filter(
        employee=instance.employee,
        date__year=entry_date.year,
        date__month=entry_date.month,
        is_locked=False
    ).aggregate(
        total=Coalesce(Sum('hours'), Decimal('0.00'))
    )['total']
    
    # Aktualisiere die Bilanzen
    account.balance = month_balance  # Monatliche Bilanz
    account.current_balance = total_balance  # Gesamtbilanz
    account.save()

@receiver(post_delete, sender=OvertimeEntry)
def update_overtime_account_on_delete(sender, instance, **kwargs):
    """Aktualisiert das OvertimeAccount wenn ein OvertimeEntry gelöscht wird"""
    entry_date = instance.date  # Nutze das Datum des gelöschten Eintrags
    
    try:
        account = OvertimeAccount.objects.get(
            employee=instance.employee,
            year=entry_date.year,
            month=entry_date.month
        )
        
        # Berechne die neue Gesamtbilanz
        total_balance = OvertimeEntry.objects.filter(
            employee=instance.employee,
            is_locked=False
        ).aggregate(
            total=Coalesce(Sum('hours'), Decimal('0.00'))
        )['total']
        
        # Berechne die neue Monatsbilanz
        month_balance = OvertimeEntry.objects.filter(
            employee=instance.employee,
            date__year=entry_date.year,
            date__month=entry_date.month,
            is_locked=False
        ).aggregate(
            total=Coalesce(Sum('hours'), Decimal('0.00'))
        )['total']
        
        # Aktualisiere die Bilanzen
        account.balance = month_balance  # Monatliche Bilanz
        account.current_balance = total_balance  # Gesamtbilanz
        account.save()
    except OvertimeAccount.DoesNotExist:
        pass  # Wenn kein Account existiert, muss nichts aktualisiert werden





