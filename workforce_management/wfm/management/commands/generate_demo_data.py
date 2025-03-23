from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from wfm.models import (
    WorkingHours, Vacation, VacationEntitlement, 
    TimeCompensation, TherapistBooking, ScheduleTemplate,
    TherapistScheduleTemplate, SickLeave, OvertimeAccount, UserDocument
)
from datetime import date, time, timedelta
from decimal import Decimal
import random
from dateutil.relativedelta import relativedelta
from django.db.utils import IntegrityError
from django.db import transaction

User = get_user_model()

class Command(BaseCommand):
    help = 'Generiert Demo-Daten für die Zeiterfassung'

    def handle(self, *args, **options):
        self.stdout.write('Generiere Demo-Daten...')
        
        # Hole alle zu löschenden User
        users_to_delete = User.objects.filter(is_superuser=False)
        
        for user in users_to_delete:
            # 1. Lösche zuerst WorkingHours, da es auf Vacation, TimeComp und SickLeave verweist
            WorkingHours.objects.filter(employee=user).delete()
            
            # 2. Lösche SickLeave und verknüpfte Dokumente
            for sick_leave in SickLeave.objects.filter(employee=user):
                if sick_leave.document:
                    sick_leave.document.delete()
                sick_leave.delete()
            
            # 3. Lösche andere Dokumente
            UserDocument.objects.filter(user=user).delete()
            
            # 4. Lösche Abwesenheiten
            Vacation.objects.filter(employee=user).delete()
            TimeCompensation.objects.filter(employee=user).delete()
            
            # 5. Lösche Buchungen und Templates
            TherapistBooking.objects.filter(therapist=user).delete()
            ScheduleTemplate.objects.filter(employee=user).delete()
            TherapistScheduleTemplate.objects.filter(therapist=user).delete()
            
            # 6. Lösche Berechtigungen und Konten
            VacationEntitlement.objects.filter(employee=user).delete()
            OvertimeAccount.objects.filter(employee=user).delete()
            
            # 7. Lösche den User selbst
            user.delete()

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
        for i in range(1, 4):
            username = f'therapist{i}'
            if not User.objects.filter(username=username).exists():
                therapist = User.objects.create_user(
                    username=username,
                    password='test1234',
                    first_name=f'Therapeut{i}',
                    last_name=f'Test{i}',
                    email=f'therapist{i}@example.com',
                    role='THERAPIST',
                    room_rate=Decimal('15.00')
                )
                therapists.append(therapist)
            else:
                therapists.append(User.objects.get(username=username))

        # Erstelle Schedules für jeden Therapeuten
        for therapist in therapists:
            self.create_therapist_schedule(therapist)

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
        vacation = Vacation(
            employee=assistants[0],
            start_date=past_start,
            end_date=past_end,
            status='APPROVED',
            notes='Sommerurlaub'
        )
        vacation.save()

        # Zukünftiger Urlaub für erste Assistenz
        future_start = today + timedelta(days=14)
        future_end = future_start + timedelta(days=4)
        vacation = Vacation(
            employee=assistants[0],
            start_date=future_start,
            end_date=future_end,
            status='APPROVED',
            notes='Herbsturlaub'
        )
        vacation.save()

        # Anstehender Urlaub für zweite Assistenz
        vacation = Vacation(
            employee=assistants[1],
            start_date=today + timedelta(days=30),
            end_date=today + timedelta(days=35),
            status='REQUESTED',
            notes='Winterurlaub'
        )
        vacation.save()

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

        # Aktualisiere die Überstundenkonten am Ende
        self.stdout.write('Aktualisiere Überstundenkonten...')
        OvertimeAccount.update_all_balances()
        OvertimeAccount.objects.all().update(last_update=today)

        self.stdout.write(self.style.SUCCESS('Demo-Daten erfolgreich generiert!'))

    def create_therapist_schedule(self, therapist):
        """Erstellt einen Wochenplan für einen Therapeuten"""
        # Zufällige Arbeitszeiten für jeden Wochentag (Mo-Fr)
        for weekday in range(0, 5):  # 0 = Montag, 4 = Freitag
            # Zufällige Start- und Endzeit
            start_hour = random.choice([8, 9, 10])
            duration = random.choice([4, 6, 8])
            end_hour = start_hour + duration

            TherapistScheduleTemplate.objects.create(
                therapist=therapist,
                weekday=weekday,
                start_time=time(start_hour, 0),  # Volle Stunden
                end_time=time(end_hour, 0),
                valid_from=timezone.now().date()
            )