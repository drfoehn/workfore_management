# Workforce Management System

Ein Django-basiertes System zur Verwaltung von Arbeitszeiten und Urlaubsanträgen für Ordinationsassistentinnen.

## Features

- Zeiterfassung mit Soll/Ist-Vergleich
- Urlaubsverwaltung mit Genehmigungsprozess
- Krankenstandsverwaltung
- Schichtplanung und Arbeitszeitvorlagen
- Rollenbasierte Zugriffssteuerung (Ordinationsinhaber/Mitarbeiter)
- Mehrsprachig (Deutsch/Englisch)
- Automatische Monatsberichte
- Stundenlohnberechnung

## Installation

1. Repository klonen und in das Verzeichnis wechseln

2. Python-Umgebung erstellen und aktivieren:
   ```bash
   python -m venv venv
   source venv/bin/activate # Linux/Mac
   venv\Scripts\activate # Windows
   ```

3. Abhängigkeiten installieren:
```bash
pip install django
pip install pillow
pip install django-crispy-forms
pip install crispy-bootstrap5
```

4. Datenbank migrieren:
```bash
python manage.py makemigrations
python manage.py migrate
```

5. Superuser erstellen:
```bash
python manage.py createsuperuser
```

6. Entwicklungsserver starten:
```bash
python manage.py runserver
```

## Verwendung

- Admin-Interface: `/admin`
- Dashboard: `/dashboard`
- Zeiterfassung: `/working-hours`
- Urlaubsanträge: `/vacation`

## Technologien

- Django 5.1
- Bootstrap 5
- SQLite (Entwicklung)
- Django Crispy Forms
- Django i18n für Mehrsprachigkeit

## Entwicklung

### Übersetzungen aktualisieren:
```bash
django-admin makemessages -l de
django-admin compilemessages
```

### Neue Migrations erstellen:
```bash
python manage.py makemigrations
python manage.py migrate
```

## Projektstruktur

```
workforce_management/
├── manage.py
├── workforce_management/    # Projekteinstellungen
├── wfm/                    # Hauptanwendung
│   ├── models.py          # Datenmodelle
│   ├── views.py           # Views
│   ├── urls.py            # URL-Routing
│   └── admin.py           # Admin-Interface
├── templates/             # HTML Templates
│   ├── base.html
│   ├── navigation.html
│   └── wfm/
└── static/               # Statische Dateien
    ├── css/
    └── js/
```

## Lizenz

MIT License
