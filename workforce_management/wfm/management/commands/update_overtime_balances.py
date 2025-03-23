from django.core.management.base import BaseCommand
from wfm.models import OvertimeAccount

class Command(BaseCommand):
    help = 'Aktualisiert die Überstundenkonten aller Mitarbeiter'

    def handle(self, *args, **options):
        self.stdout.write('Starte Aktualisierung der Überstundenkonten...')
        OvertimeAccount.update_all_balances()
        self.stdout.write(self.style.SUCCESS('Überstundenkonten erfolgreich aktualisiert')) 