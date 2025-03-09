from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from wfm.models import (
    WorkingHours, Vacation, VacationEntitlement, 
    TimeCompensation, TherapistBooking, ScheduleTemplate,
    TherapistScheduleTemplate, SickLeave, OvertimeAccount  
)
from datetime import date, time, timedelta
from decimal import Decimal
import random
from dateutil.relativedelta import relativedelta

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
        OvertimeAccount.objects.all().delete()

        
        today = date.today()
        
        # Erstelle Owner mit Details
        # owner = User.objects.create_user(
        #     username='owner',
        #     password='owner123',
        #     role='OWNER',
        #     first_name='Otto',
        #     last_name='Owner',
        #     email='otto@example.com',
        #     phone='0123456789',
        #     date_of_birth=date(1980, 5, 15),
        #     employed_since=date(2010, 1, 1),
        #     color='#FF0000'
        # )
        
        # Erstelle Assistenzen mit Details
        assistants = []
        for i in range(3):
            assistant = User.objects.create_user(
                username=f'assistant{i+1}',
                password='assistant123',
                role='ASSISTANT',
                first_name=f'Anna{i+1}',
                last_name='Assistant',
                email=f'anna{i+1}@example.com',
                phone=f'0123456{i+1}',
                date_of_birth=date(1990 + i, 6, 15),
                employed_since=date(2020 + i, 1, 1),
                hourly_rate=Decimal('15.00'),
                color=f'#{i}498DB'
            )
            assistants.append(assistant)
            
            # Verschiedene Arbeitszeiten-Vorlagen für jeden Assistenten
            # 1. Vorlage (älteste) - Teilzeit
            valid_from = assistant.employed_since
            for weekday in range(5):
                ScheduleTemplate.objects.create(
                    employee=assistant,
                    weekday=weekday,
                    start_time=time(9, 0),
                    end_time=time(14, 0),
                    valid_from=valid_from
                )
            
            # 2. Vorlage (nach 6 Monaten) - Vollzeit
            valid_from = assistant.employed_since + relativedelta(months=6)
            for weekday in range(5):
                ScheduleTemplate.objects.create(
                    employee=assistant,
                    weekday=weekday,
                    start_time=time(8, 0),
                    end_time=time(16, 30),
                    valid_from=valid_from
                )
            
            # 3. Vorlage (aktuell) - Flexible Zeiten
            valid_from = date(2023, 1, 1)
            schedule_times = [
                (time(8, 0), time(16, 30)),  # Montag
                (time(9, 0), time(17, 30)),  # Dienstag
                (time(8, 30), time(17, 0)),  # Mittwoch
                (time(8, 0), time(16, 30)),  # Donnerstag
                (time(8, 0), time(14, 0)),   # Freitag
            ]
            for weekday, (start, end) in enumerate(schedule_times):
                ScheduleTemplate.objects.create(
                    employee=assistant,
                    weekday=weekday,
                    start_time=start,
                    end_time=end,
                    valid_from=valid_from
                )
            
        # Erstelle Reinigungskräfte mit Details
        cleaners = []
        for i in range(2):
            cleaner = User.objects.create_user(
                username=f'cleaner{i+1}',
                password='cleaner123',
                role='CLEANING',
                first_name=f'Clara{i+1}',
                last_name='Cleaner',
                email=f'clara{i+1}@example.com',
                phone=f'0987654{i+1}',
                date_of_birth=date(1985 + i, 8, 20),
                employed_since=date(2021 + i, 3, 1),
                hourly_rate=Decimal('12.00'),
                color=f'#{i}ECC71'
            )
            cleaners.append(cleaner)
            
            # Verschiedene Arbeitszeiten für Reinigungskräfte
            # Aktuelle Vorlage
            schedule_times = [
                (time(17, 0), time(21, 0)),  # Montag
                (time(17, 0), time(21, 0)),  # Dienstag
                (time(17, 0), time(21, 0)),  # Mittwoch
                (time(17, 0), time(21, 0)),  # Donnerstag
                (time(15, 0), time(19, 0)),  # Freitag
            ]
            for weekday, (start, end) in enumerate(schedule_times):
                ScheduleTemplate.objects.create(
                    employee=cleaner,
                    weekday=weekday,
                    start_time=start,
                    end_time=end,
                    valid_from=cleaner.employed_since
                )
            
        # Erstelle Therapeuten mit Details
        therapists = []
        for i in range(3):
            therapist = User.objects.create_user(
                username=f'therapist{i+1}',
                password='therapist123',
                role='THERAPIST',
                first_name=f'Theo{i+1}',
                last_name='Therapist',
                email=f'theo{i+1}@example.com',
                phone=f'0456789{i+1}',
                date_of_birth=date(1975 + i, 3, 10),
                employed_since=date(2019 + i, 6, 1),
                hourly_rate=Decimal('50.00'),
                room_rate=Decimal('15.00'),
                color=f'#E{i}7E22'
            )
            therapists.append(therapist)
            
            # Verschiedene Buchungszeiten für Therapeuten
            # 1. Vorlage (ursprünglich)
            valid_from = therapist.employed_since
            morning_slots = [(time(9, 0), time(12, 0))]
            afternoon_slots = [(time(14, 0), time(17, 0))]
            
            # 2. Vorlage (aktuell) - mehr Slots
            valid_from = date(2023, 1, 1)
            morning_slots = [
                (time(8, 0), time(10, 0)),
                (time(10, 30), time(12, 30))
            ]
            afternoon_slots = [
                (time(14, 0), time(16, 0)),
                (time(16, 30), time(18, 30))
            ]
            
            for weekday in range(5):
                for start, end in morning_slots + afternoon_slots:
                    TherapistScheduleTemplate.objects.create(
                        therapist=therapist,
                        weekday=weekday,
                        start_time=start,
                        end_time=end,
                        valid_from=valid_from
                    )

        # Urlaubsanspruch für alle Mitarbeiter
        for employee in assistants + cleaners:
            VacationEntitlement.objects.create(
                employee=employee,
                year=today.year,
                total_hours=300
            )

        # Vergangene und zukünftige Urlaube
        # Vergangener Urlaub für erste Assistenz
        past_start = today - timedelta(days=45)
        past_end = past_start + timedelta(days=4)
        Vacation.objects.create(
            employee=assistants[0],
            start_date=past_start,
            end_date=past_end,
            status='APPROVED',
            notes='Sommerurlaub'
        )

        # Zukünftiger Urlaub für erste Assistenz
        future_start = today + timedelta(days=14)
        future_end = future_start + timedelta(days=4)
        Vacation.objects.create(
            employee=assistants[0],
            start_date=future_start,
            end_date=future_end,
            status='APPROVED',
            notes='Herbsturlaub'
        )

        # Anstehender Urlaub für zweite Assistenz
        Vacation.objects.create(
            employee=assistants[1],
            start_date=today + timedelta(days=30),
            end_date=today + timedelta(days=35),
            status='REQUESTED',
            notes='Winterurlaub'
        )

        # Zeitausgleiche
        # Vergangene Zeitausgleiche
        for i, assistant in enumerate(assistants):
            TimeCompensation.objects.create(
                employee=assistant,
                date=today - timedelta(days=30+i),
                hours=Decimal('8.00'),
                status='APPROVED',
                notes=f'Zeitausgleich für Überstunden im letzten Monat'
            )

        # Zukünftige Zeitausgleiche
        TimeCompensation.objects.create(
            employee=assistants[1],
            date=today + timedelta(days=21),
            hours=Decimal('8.00'),
            status='REQUESTED',
            notes='Zeitausgleich für Inventur'
        )
        
        TimeCompensation.objects.create(
            employee=cleaners[0],
            date=today + timedelta(days=7),
            hours=Decimal('4.00'),
            status='APPROVED',
            notes='Halber Tag Zeitausgleich'
        )

        # Krankmeldungen
        # Vergangene Krankmeldungen
        SickLeave.objects.create(
            employee=assistants[1],
            start_date=today - timedelta(days=20),
            end_date=today - timedelta(days=18),
            status='SUBMITTED',
            notes='Grippe mit ärztlicher Bestätigung'
        )

        SickLeave.objects.create(
            employee=cleaners[0],
            start_date=today - timedelta(days=15),
            end_date=today - timedelta(days=14),
            status='SUBMITTED',
            notes='Migräne mit Attest'
        )

        # Aktuelle/Laufende Krankmeldung
        if today.weekday() < 5:  # Nur an Werktagen
            SickLeave.objects.create(
                employee=assistants[2],
                start_date=today,
                end_date=today + timedelta(days=2),
                status='PENDING',
                notes='Erkältung, Attest folgt'
            )

        # Arbeitszeiten der letzten 30 Tage für alle Mitarbeiter
        for employee in assistants + cleaners:
            for i in range(30):
                work_date = today - timedelta(days=i)
                if work_date.weekday() < 5:  # Nur Werktage
                    # Hole den gültigen Schedule für diesen Tag
                    schedule = ScheduleTemplate.objects.filter(
                        employee=employee,
                        weekday=work_date.weekday(),
                        valid_from__lte=work_date
                    ).order_by('-valid_from').first()

                    if schedule:
                        # Normale Arbeitszeit
                        WorkingHours.objects.create(
                            employee=employee,
                            date=work_date,
                            start_time=schedule.start_time,
                            end_time=schedule.end_time,
                            break_duration=timedelta(minutes=30),
                            soll_hours=schedule.hours,
                            ist_hours=schedule.hours + (Decimal('0.5') if random.random() > 0.8 else Decimal('0.0'))  # 20% Chance auf Überstunden
                        )

        # Therapeuten-Buchungen der letzten 30 Tage
        for therapist in therapists:
            for i in range(30):
                booking_date = today - timedelta(days=i)
                if booking_date.weekday() < 5:  # Nur Werktage
                    # Hole alle gültigen Slots für diesen Tag
                    schedules = TherapistScheduleTemplate.objects.filter(
                        therapist=therapist,
                        weekday=booking_date.weekday(),
                        valid_from__lte=booking_date
                    ).order_by('-valid_from')

                    for schedule in schedules:
                        TherapistBooking.objects.create(
                            therapist=therapist,
                            date=booking_date,
                            start_time=schedule.start_time,
                            end_time=schedule.end_time,
                            # status='COMPLETED' if booking_date < today else 'RESERVED',
                            payment_status='PAID' if booking_date < today - timedelta(days=7) else 'PENDING'
                        )

        self.stdout.write(self.style.SUCCESS('Demo-Daten erfolgreich generiert!'))