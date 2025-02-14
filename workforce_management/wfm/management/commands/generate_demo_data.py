from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import datetime, time, timedelta
from decimal import Decimal
import random
from wfm.models import (
    ScheduleTemplate,
    TherapistBooking, 
    TherapistScheduleTemplate,
    WorkingHours,
    Vacation,
    TimeCompensation
)

class Command(BaseCommand):
    help = 'Generiert Demo-Daten für die Zeiterfassung'

    def handle(self, *args, **kwargs):
        User = get_user_model()
        
        # Lösche existierende Daten
        self.stdout.write('Lösche alte Daten...')
        User.objects.exclude(is_superuser=True).delete()
        TherapistBooking.objects.all().delete()
        TherapistScheduleTemplate.objects.all().delete()
        WorkingHours.objects.all().delete()
        Vacation.objects.all().delete()
        TimeCompensation.objects.all().delete()
        
        # Erstelle Therapeuten
        self.stdout.write('Erstelle Therapeuten...')
        therapists = []
        for i in range(3):
            therapist = User.objects.create_user(
                username=f'therapeut{i+1}',
                password='test123',
                first_name=f'Vorname{i+1}',
                last_name=f'Nachname{i+1}',
                role='THERAPIST',
                hourly_rate=Decimal(str(random.randint(40, 60)))
            )
            therapists.append(therapist)
        
        # Erstelle Assistenten
        self.stdout.write('Erstelle Assistenten...')
        assistants = []
        for i in range(2):
            assistant = User.objects.create_user(
                username=f'assistent{i+1}',
                password='test123',
                first_name=f'Assistent{i+1}',
                last_name=f'Nachname{i+1}',
                role='ASSISTANT'
            )
            assistants.append(assistant)
        
        # Erstelle Zeitplan-Vorlagen für Therapeuten
        self.stdout.write('Erstelle Zeitplan-Vorlagen...')
        for therapist in therapists:
            for weekday in range(5):  # Montag bis Freitag
                morning_start = time(9, 0)
                morning_end = time(12, 0)
                afternoon_start = time(14, 0)
                afternoon_end = time(17, 0)
                
                TherapistScheduleTemplate.objects.create(
                    therapist=therapist,
                    weekday=weekday,
                    start_time=morning_start,
                    end_time=morning_end
                )
                
                TherapistScheduleTemplate.objects.create(
                    therapist=therapist,
                    weekday=weekday,
                    start_time=afternoon_start,
                    end_time=afternoon_end
                )
        
        # Erstelle Buchungen für die nächsten 30 Tage
        self.stdout.write('Erstelle Buchungen...')
        today = timezone.now().date()
        for day in range(30):
            current_date = today + timedelta(days=day)
            if current_date.weekday() < 5:  # Nur Werktage
                for therapist in therapists:
                    templates = TherapistScheduleTemplate.objects.filter(
                        therapist=therapist,
                        weekday=current_date.weekday()
                    )
                    
                    for template in templates:
                        # 80% Chance für eine Buchung
                        if random.random() < 0.8:
                            status = random.choice(['RESERVED', 'USED'])
                            actual_hours = template.hours * Decimal(str(random.uniform(0.8, 1.0))) if status == 'USED' else None
                            
                            TherapistBooking.objects.create(
                                therapist=therapist,
                                date=current_date,
                                start_time=template.start_time,
                                end_time=template.end_time,
                                actual_hours=actual_hours,
                                status=status,
                                notes='Demo-Buchung' if status == 'USED' else ''
                            )
        
        # Erstelle Arbeitszeiten für Assistenten
        self.stdout.write('Erstelle Arbeitszeiten...')
        for day in range(30):
            current_date = today + timedelta(days=day)
            if current_date.weekday() < 5:  # Nur Werktage
                for assistant in assistants:
                    # 90% Chance für einen Arbeitstag
                    if random.random() < 0.9:
                        start_time = time(8, 0)
                        end_time = time(16, 30)
                        break_duration = timedelta(minutes=30)
                        
                        ScheduleTemplate.objects.create(
                            employee=assistant,
                            weekday=current_date.weekday(),
                            start_time=start_time,
                            end_time=end_time
                        )

                        WorkingHours.objects.create(
                            employee=assistant,
                            date=current_date,
                            start_time=start_time,
                            end_time=end_time,
                            break_duration=break_duration
                        )
        
        # Erstelle Urlaub und Zeitausgleich
        self.stdout.write('Erstelle Urlaub und Zeitausgleich...')
        for assistant in assistants:
            # Urlaub in 2 Wochen
            start_date = today + timedelta(days=14)
            end_date = start_date + timedelta(days=4)
            Vacation.objects.create(
                employee=assistant,
                start_date=start_date,
                end_date=end_date,
                status='APPROVED'
            )
            
            # Zeitausgleich in 3 Wochen
            za_date = today + timedelta(days=21)
            TimeCompensation.objects.create(
                employee=assistant,
                date=za_date,
                hours=Decimal('8.00'),
                status='APPROVED'
            )
        
        self.stdout.write(self.style.SUCCESS('Demo-Daten erfolgreich erstellt!')) 
                end_date=end_date,
                status='APPROVED'
            )
            
            # Zeitausgleich in 3 Wochen
            za_date = today + timedelta(days=21)
            TimeCompensation.objects.create(
                employee=assistant,
                date=za_date,
                hours=Decimal('8.00'),
                status='APPROVED'
            )
        
        self.stdout.write(self.style.SUCCESS('Demo-Daten erfolgreich erstellt!'))