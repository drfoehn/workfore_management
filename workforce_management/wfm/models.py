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
    valid_from = models.DateField(verbose_name=_("Gültig ab"), default=date.today)
    
    class Meta:
        ordering = ['-valid_from', 'weekday']
        verbose_name = _("Arbeitszeit-Vorlage")
        verbose_name_plural = _("Arbeitszeit-Vorlagen")

    @property
    def hours(self):
        """Berechnet die Stunden zwischen Start- und Endzeit"""
        start = datetime.combine(date.min, self.start_time)
        end = datetime.combine(date.min, self.end_time)
        duration = end - start
        return Decimal(str(duration.total_seconds() / 3600))

    def __str__(self):
        return f"{self.employee.username} - {self.get_weekday_display()} (ab {self.valid_from})"

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
    soll_start = models.TimeField(null=True, blank=True)
    soll_end = models.TimeField(null=True, blank=True)

    # Stunden
    ist_hours = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    soll_hours = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # Füge related_names hinzu
    vacation = models.ForeignKey('Vacation', on_delete=models.SET_NULL, null=True, blank=True, related_name='working_hours')
    time_comp = models.ForeignKey('TimeCompensation', on_delete=models.SET_NULL, null=True, blank=True, related_name='working_hours')
    sick_leave = models.ForeignKey('SickLeave', on_delete=models.SET_NULL, null=True, blank=True, related_name='working_hours')

    def save(self, *args, **kwargs):
        # Berechne Ist-Stunden
        if self.start_time and self.end_time:
            start = datetime.combine(self.date, self.start_time)
            end = datetime.combine(self.date, self.end_time)
            duration = end - start
            self.ist_hours = Decimal(str(duration.total_seconds() / 3600))
            
            if self.break_duration:
                self.ist_hours -= Decimal(str(self.break_duration.total_seconds() / 3600))
        else:
            self.ist_hours = Decimal('0')  # Setze auf 0 wenn keine Zeiten vorhanden

        # Berechne Soll-Stunden
        if self.soll_start and self.soll_end:
            start = datetime.combine(self.date, self.soll_start)
            end = datetime.combine(self.date, self.soll_end)
            self.soll_hours = Decimal(str((end - start).total_seconds() / 3600))
        else:
            self.soll_hours = Decimal('0')  # Setze auf 0 wenn keine Zeiten vorhanden

        super().save(*args, **kwargs)

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

class Vacation(models.Model):
    """Urlaubsverwaltung"""
    STATUS_CHOICES = [
        ('REQUESTED', 'Angefragt'),
        ('APPROVED', 'Genehmigt'),
        ('REJECTED', 'Abgelehnt'),
    ]
    
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    start_date = models.DateField(verbose_name="Urlaubsbeginn")
    end_date = models.DateField(verbose_name="Urlaubsende")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='REQUESTED')
    notes = models.TextField(blank=True, null=True, verbose_name="Anmerkungen")

    @property
    def working_days(self):
        """Berechnet die Anzahl der Werktage zwischen Start- und Enddatum"""
        days = 0
        current = self.start_date
        while current <= self.end_date:
            if current.weekday() < 5:  # 0-4 sind Montag bis Freitag
                days += 1
            current += timedelta(days=1)
        return days

    class Meta:
        ordering = ['-start_date']

class VacationEntitlement(models.Model):
    """Jahresurlaub"""
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    year = models.IntegerField(verbose_name="Jahr")
    total_days = models.PositiveIntegerField(
        validators=[MaxValueValidator(50)],
        verbose_name="Gesamte Urlaubstage"
    )
    
    class Meta:
        unique_together = ['employee', 'year']

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
    
    def __str__(self):
        return f"{self.employee} - {self.start_date} bis {self.end_date}"

class MonthlyReport(models.Model):
    """Monatlicher Abrechnungsbericht"""
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    month = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        verbose_name="Monat"
    )
    year = models.IntegerField(verbose_name="Jahr")
    total_hours = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        verbose_name="Gesamtstunden"
    )
    total_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        verbose_name="Gesamtbetrag"
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['employee', 'month', 'year']

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
        help_text=_('Standardmäßig 8 Stunden für einen vollen Arbeitstag')
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='REQUESTED', verbose_name=_('Status'))
    notes = models.TextField(blank=True, verbose_name=_('Anmerkungen'))

    class Meta:
        ordering = ['-date']
        verbose_name = _('Zeitausgleich')
        verbose_name_plural = _('Zeitausgleiche')

    def __str__(self):
        return f"{self.employee} - {self.date} ({self.hours}h)"

class TherapistBooking(models.Model):
    """Raumbuchungen für Therapeuten"""
    STATUS_CHOICES = [
        ('RESERVED', _('Reserviert')),
        ('USED', _('Verwendet')),
        ('CANCELLED', _('Storniert')),
    ]

    therapist = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    actual_hours = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='RESERVED')

    @property
    def hours(self):
        """Berechnet die gebuchten Stunden"""
        start = datetime.combine(date.min, self.start_time)
        end = datetime.combine(date.min, self.end_time)
        duration = end - start
        return Decimal(str(duration.total_seconds() / 3600))

    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError('Endzeit muss nach Startzeit liegen')

    def __str__(self):
        return f"{self.therapist.username} - {self.date} ({self.start_time}-{self.end_time})"

class TherapistScheduleTemplate(models.Model):
    """Vorlage für die Standard-Raumbuchungen"""
    WEEKDAY_CHOICES = ScheduleTemplate.WEEKDAY_CHOICES
    
    therapist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'THERAPIST'}
    )
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    valid_from = models.DateField(verbose_name=_("Gültig ab"), default=date.today)
    hours = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('0.00')
    )

    class Meta:
        ordering = ['-valid_from', 'weekday', 'start_time']
        
    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError('Endzeit muss nach Startzeit liegen')
        
        # Berechne die Stunden bei Änderungen
        if self.start_time and self.end_time:
            start = datetime.combine(date.today(), self.start_time)
            end = datetime.combine(date.today(), self.end_time)
            duration = end - start
            self.hours = Decimal(str(duration.total_seconds() / 3600))
            
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.therapist} - {self.get_weekday_display()} ({self.start_time}-{self.end_time})"

class UserDocument(models.Model):
    """Dokumente für Benutzer (Verträge etc.)"""
    user = models.ForeignKey(
        CustomUser, 
        on_delete=models.CASCADE,
        related_name='documents'
    )
    title = models.CharField(max_length=255, verbose_name=_("Titel"))
    file = models.FileField(
        upload_to='user_documents/%Y/%m/',
        verbose_name=_("Datei")
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, verbose_name=_("Notizen"))

    class Meta:
        verbose_name = _("Benutzerdokument")
        verbose_name_plural = _("Benutzerdokumente")
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.user.username} - {self.title}"

class OvertimeAccount(models.Model):
    """Überstundenkonto für Zeitausgleich"""
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    month = models.IntegerField()
    year = models.IntegerField()
    total_overtime = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    hours_for_payment = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    hours_for_timecomp = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_finalized = models.BooleanField(default=False)
    finalized_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.pk:  # Wenn neuer Eintrag
            self.hours_for_payment = self.total_overtime
            self.hours_for_timecomp = 0
        else:  # Bei Update
            # Stelle sicher, dass die Summe stimmt
            self.hours_for_payment = self.total_overtime - self.hours_for_timecomp

        super().save(*args, **kwargs)

    class Meta:
        unique_together = ['employee', 'year', 'month']
        ordering = ['-year', '-month']

    def finalize(self, hours_for_payment):
        """Finalisiert die Überstunden für den Monat"""
        if self.is_finalized:
            raise ValueError("Überstunden wurden bereits finalisiert")
        
        if hours_for_payment > self.total_overtime:
            raise ValueError("Auszahlungsstunden können nicht größer als Gesamtstunden sein")
        
        self.hours_for_payment = hours_for_payment
        self.hours_for_timecomp = self.total_overtime - hours_for_payment
        self.is_finalized = True
        self.finalized_at = timezone.now()
        self.save()

    @property
    def available_hours(self):
        """Verfügbare Stunden für Zeitausgleich"""
        if not self.is_finalized:
            return 0
        return self.hours_for_timecomp

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

