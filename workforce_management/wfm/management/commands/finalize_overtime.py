from django.core.management.base import BaseCommand
from django.utils import timezone
from wfm.models import OvertimeAccount
from datetime import date
from dateutil.relativedelta import relativedelta

class Command(BaseCommand):
    help = 'Finalisiert die Überstunden des Vormonats am 8. des Monats'

    def handle(self, *args, **options):
        today = date.today()
        
        # Nur am 8. des Monats ausführen
        if today.day != 8:
            self.stdout.write('Nicht der 8. des Monats - keine Aktion notwendig')
            return
            
        # Hole den vorherigen Monat
        target_date = today - relativedelta(months=1)
        
        # Hole alle nicht finalisierten Überstundenkonten vom Vormonat
        accounts = OvertimeAccount.objects.filter(
            year=target_date.year,
            month=target_date.month,
            is_finalized=False
        )
        
        for account in accounts:
            # Alle verbleibenden Stunden gehen zur Auszahlung
            if not account.hours_for_payment:
                account.hours_for_payment = account.total_overtime - (account.hours_for_timecomp or 0)
            
            account.is_finalized = True
            account.finalized_at = timezone.now()
            account.save()
            
            self.stdout.write(f'Finalisiert: {account.employee} - {account.total_overtime}h') 