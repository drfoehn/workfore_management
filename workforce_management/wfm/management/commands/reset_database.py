from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Setzt die Datenbank zurück'

    def handle(self, *args, **options):
        self.stdout.write('Setze Datenbank zurück...')
        
        with connection.cursor() as cursor:
            # SQLite-spezifischer Befehl zum Deaktivieren der Foreign Key Constraints
            cursor.execute('PRAGMA foreign_keys=OFF;')
            
            # Hole alle Tabellen
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence' AND name!='django_migrations';")
            tables = cursor.fetchall()
            
            # Leere jede Tabelle außer django_migrations
            for table in tables:
                table_name = table[0]
                if table_name != 'auth_user' or options.get('include_users', False):
                    cursor.execute(f'DELETE FROM {table_name};')
            
            # Aktiviere Foreign Key Constraints wieder
            cursor.execute('PRAGMA foreign_keys=ON;')
        
        self.stdout.write(self.style.SUCCESS('Datenbank erfolgreich zurückgesetzt!')) 