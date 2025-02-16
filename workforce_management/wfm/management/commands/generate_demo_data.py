from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from wfm.models import (
    WorkingHours, Vacation, VacationEntitlement, 
    TimeCompensation, TherapistBooking, ScheduleTemplate,
    TherapistScheduleTemplate, SickLeave
)
from datetime import date, time, timedelta
from decimal import Decimal
import random

User = get_user_model()

class Command(BaseCommand):
    help = 'Generiert Demo-Daten für die Zeiterfassung'

    def handle(self, *args, **kwargs):
        self.stdout.write('Generiere Demo-Daten...')
        
        # Lösche bestehende Daten
        User.objects.filter(is_superuser=False).delete()
        WorkingHours.objects.all().delete()
        Vacation.objects.all().delete()
        VacationEntitlement.objects.all().delete()
        TimeCompensation.objects.all().delete()
        TherapistBooking.objects.all().delete()
        ScheduleTemplate.objects.all().delete()
        TherapistScheduleTemplate.objects.all().delete()
        SickLeave.objects.all().delete()
        
        # Erstelle Owner
        owner = User.objects.create_user(
            username='owner',
            password='owner123',
            role='OWNER',
            first_name='Otto',
            last_name='Owner',
            color='#FF0000'
        )
        
        # Erstelle Assistenzen
        assistants = []
        for i in range(3):
            assistant = User.objects.create_user(
                username=f'assistant{i+1}',
                password='assistant123',
                role='ASSISTANT',
                first_name=f'Anna{i+1}',
                last_name='Assistant',
                hourly_rate=Decimal('15.00'),
                color=f'#3498DB'
            )
            assistants.append(assistant)
            
        # Erstelle Reinigungskräfte
        cleaners = []
        for i in range(2):
            cleaner = User.objects.create_user(
                username=f'cleaner{i+1}',
                password='cleaner123',
                role='CLEANING',
                first_name=f'Clara{i+1}',
                last_name='Cleaner',
                hourly_rate=Decimal('12.00'),
                color=f'#2ECC71'
            )
            cleaners.append(cleaner)
            
        # Erstelle Therapeuten
        therapists = []
        for i in range(3):
            therapist = User.objects.create_user(
                username=f'therapist{i+1}',
                password='therapist123',
                role='THERAPIST',
                first_name=f'Theo{i+1}',
                last_name='Therapist',
                hourly_rate=Decimal('50.00'),
                room_rate=Decimal('15.00'),
                color=f'#E67E22'
            )
            therapists.append(therapist)
        
        today = date.today()
        
        # Erstelle Arbeitszeit-Vorlagen für Assistenzen und Reinigungskräfte
        for employee in assistants + cleaners:
            # Vorlage Mo-Fr
            for weekday in range(5):
                ScheduleTemplate.objects.create(
                    employee=employee,
                    weekday=weekday,
                    start_time=time(8, 0),
                    end_time=time(16, 30)
                )
            
            # Urlaubsanspruch
            VacationEntitlement.objects.create(
                employee=employee,
                year=today.year,
                total_days=25
            )
            
            # Arbeitszeiten der letzten 30 Tage
            for i in range(30):
                work_date = today - timedelta(days=i)
                if work_date.weekday() < 5:  # Nur Werktage
                    WorkingHours.objects.create(
                        employee=employee,
                        date=work_date,
                        start_time=time(8, 0),
                        end_time=time(16, 30),
                        break_duration=timedelta(minutes=30)
                    )
        
        # Generiere einen Urlaub für die erste Assistenz
        start_date = today + timedelta(days=14)
        end_date = start_date + timedelta(days=4)
        Vacation.objects.create(
            employee=assistants[0],
            start_date=start_date,
            end_date=end_date,
            status='APPROVED'
        )
            
        # Zeitausgleich in 3 Wochen
        za_date = today + timedelta(days=21)
        TimeCompensation.objects.create(
            employee=assistants[1],
            date=za_date,
            hours=Decimal('8.00'),
            status='APPROVED'
        )
        
        # Krankenstand für die zweite Assistenz (mit Krankmeldung)
        sick_start = today - timedelta(days=5)
        sick_end = today - timedelta(days=2)
        SickLeave.objects.create(
            employee=assistants[1],
            start_date=sick_start,
            end_date=sick_end,
            status='SUBMITTED',
            notes='Grippe'
        )
        
        # Krankenstand für Reinigungskraft (ohne Krankmeldung)
        sick_start = today - timedelta(days=3)
        sick_end = today - timedelta(days=1)
        SickLeave.objects.create(
            employee=cleaners[0],
            start_date=sick_start,
            end_date=sick_end,
            status='PENDING',
            notes='Migräne'
        )
        
        # Therapeuten-Vorlagen und Buchungen
        for therapist in therapists:
            # Buchungsvorlagen
            for weekday in range(5):  # Montag bis Freitag
                TherapistScheduleTemplate.objects.create(
                    therapist=therapist,
                    weekday=weekday,
                    start_time=time(9, 0),
                    end_time=time(12, 0)
                )
                TherapistScheduleTemplate.objects.create(
                    therapist=therapist,
                    weekday=weekday,
                    start_time=time(14, 0),
                    end_time=time(17, 0)
                )
            
            # Buchungen der letzten 30 Tage
            for i in range(30):
                booking_date = today - timedelta(days=i)
                if booking_date.weekday() < 5:  # Nur Werktage
                    TherapistBooking.objects.create(
                        therapist=therapist,
                        date=booking_date,
                        start_time=time(9, 0),
                        end_time=time(12, 0),
                        status='RESERVED'
                    )
                    TherapistBooking.objects.create(
                        therapist=therapist,
                        date=booking_date,
                        start_time=time(14, 0),
                        end_time=time(17, 0),
                        status='RESERVED'
                    )
        
        self.stdout.write(self.style.SUCCESS('Demo-Daten erfolgreich generiert!'))