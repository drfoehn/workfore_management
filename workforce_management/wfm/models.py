from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from decimal import Decimal

class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('OWNER', _('Ordinationsinhaber/in')),
        ('EMPLOYEE', _('Mitarbeiter/in')),
    ]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='EMPLOYEE')
    hourly_rate = models.DecimalField(
        max_digits=6, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name=_("Stundenlohn"),
        null=True,
        blank=True
    )

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
    shift_type = models.CharField(
        max_length=20,
        choices=[
            ('MORNING', _('Vormittag')),
            ('AFTERNOON', _('Nachmittag')),
            ('EVENING', _('Abend')),
            ('OTHER', _('Sonstige')),
        ],
        default='MORNING',
        verbose_name=_("Schicht")
    )
    
    class Meta:
        unique_together = ['employee', 'weekday', 'shift_type']
        verbose_name = _("Arbeitszeit-Vorlage")
        verbose_name_plural = _("Arbeitszeit-Vorlagen")

class WorkingHours(models.Model):
    """Tatsächlich geleistete Arbeitsstunden"""
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    date = models.DateField()
    start_time = models.TimeField(verbose_name="Beginn")
    end_time = models.TimeField(verbose_name="Ende")
    break_duration = models.DurationField(verbose_name="Pausendauer", default='0:30:00')
    shift_type = models.CharField(
        max_length=20,
        choices=[
            ('MORNING', 'Vormittag'),
            ('AFTERNOON', 'Nachmittag'),
            ('EVENING', 'Abend'),
            ('OTHER', 'Sonstige'),
        ],
        default='MORNING',
        verbose_name="Schicht"
    )
    notes = models.TextField(blank=True, null=True, verbose_name="Anmerkungen")

    class Meta:
        # Erlaubt mehrere Einträge pro Tag, aber verhindert Überlappungen
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'date', 'shift_type'],
                name='unique_shift_per_day'
            )
        ]

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
    """Krankenstand"""
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    start_date = models.DateField(verbose_name="Beginn Krankenstand")
    end_date = models.DateField(verbose_name="Ende Krankenstand")
    description = models.TextField(blank=True, null=True, verbose_name="Beschreibung")
    document_provided = models.BooleanField(default=False, verbose_name="Krankmeldung vorgelegt")

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
