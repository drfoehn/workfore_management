from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from decimal import Decimal
from django.forms import DateField as FormDateField
from datetime import timedelta
from django.core.exceptions import ValidationError
from datetime import datetime
from django.conf import settings
from datetime import date

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

    # Füge related_names hinzu
    vacation = models.ForeignKey('Vacation', on_delete=models.SET_NULL, null=True, blank=True, related_name='working_hours')
    time_comp = models.ForeignKey('TimeCompensation', on_delete=models.SET_NULL, null=True, blank=True, related_name='working_hours')
    sick_leave = models.ForeignKey('SickLeave', on_delete=models.SET_NULL, null=True, blank=True, related_name='working_hours')

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
        ('REQUESTED', 'Beantragt'),
        ('APPROVED', 'Genehmigt'),
        ('REJECTED', 'Abgelehnt'),
    ]

    employee = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        verbose_name=_('Mitarbeiter')
    )
    date = models.DateField(_('Datum'))
    hours = models.DecimalField(
        _('Stunden'),
        max_digits=4,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    notes = models.TextField(
        _('Anmerkungen'),
        blank=True,
        null=True
    )
    status = models.CharField(
        _('Status'),
        max_length=10,
        choices=STATUS_CHOICES,
        default='REQUESTED'
    )
    created_at = models.DateTimeField(
        _('Erstellt am'),
        auto_now_add=True
    )
    updated_at = models.DateTimeField(
        _('Aktualisiert am'),
        auto_now=True
    )

    class Meta:
        verbose_name = _('Zeitausgleich')
        verbose_name_plural = _('Zeitausgleiche')
        ordering = ['-date']

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

