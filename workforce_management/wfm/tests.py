from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import datetime, time, timedelta
from decimal import Decimal
from .models import (
    TherapistBooking, 
    TherapistScheduleTemplate,
    WorkingHours,
    Vacation,
    TimeCompensation
)

class WFMTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        User = get_user_model()
        
        # Erstelle Test-Benutzer
        self.therapist = User.objects.create_user(
            username='therapist',
            password='test123',
            first_name='Test',
            last_name='Therapeut',
            role='THERAPIST',
            hourly_rate=Decimal('50.00')
        )
        
        self.assistant = User.objects.create_user(
            username='assistant',
            password='test123',
            first_name='Test',
            last_name='Assistent',
            role='ASSISTANT'
        )
        
        # Aktuelles Datum für Tests
        self.today = timezone.now().date()
        self.tomorrow = self.today + timedelta(days=1)
        
        # Erstelle Therapeuten-Zeitplan-Vorlage
        self.schedule_template = TherapistScheduleTemplate.objects.create(
            therapist=self.therapist,
            weekday=self.today.weekday(),
            start_time=time(9, 0),
            end_time=time(12, 0),
            hours=Decimal('3.00')
        )
        
        # Erstelle Therapeuten-Buchung
        self.booking = TherapistBooking.objects.create(
            therapist=self.therapist,
            date=self.today,
            start_time=time(9, 0),
            end_time=time(12, 0),
            hours=Decimal('3.00'),
            status='RESERVED'
        )
        
        # Erstelle Arbeitszeiten
        self.working_hours = WorkingHours.objects.create(
            employee=self.assistant,
            date=self.today,
            start_time=time(8, 0),
            end_time=time(16, 0),
            break_duration=timedelta(minutes=30)
        )
        
        # Erstelle Urlaub
        self.vacation = Vacation.objects.create(
            employee=self.assistant,
            start_date=self.tomorrow,
            end_date=self.tomorrow + timedelta(days=5),
            days=5,
            status='APPROVED'
        )
        
        # Erstelle Zeitausgleich
        self.time_comp = TimeCompensation.objects.create(
            employee=self.assistant,
            date=self.tomorrow + timedelta(days=7),
            hours=Decimal('8.00'),
            status='APPROVED'
        )

    def test_therapist_booking_workflow(self):
        """Test des kompletten Therapeuten-Buchungs-Workflows"""
        # Login als Therapeut
        self.client.login(username='therapist', password='test123')
        
        # Teste Monatsübersicht
        response = self.client.get(reverse('wfm:therapist-monthly-overview'))
        self.assertEqual(response.status_code, 200)
        
        # Teste Buchung als verwendet markieren
        response = self.client.post(
            reverse('wfm:api-therapist-booking-used'),
            {
                'booking_id': self.booking.id,
                'date': self.today.strftime('%Y-%m-%d'),
                'actual_hours': '2.75',
                'notes': 'Test-Notiz'
            },
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        
        # Überprüfe ob Buchung aktualisiert wurde
        booking = TherapistBooking.objects.get(id=self.booking.id)
        self.assertEqual(booking.status, 'USED')
        self.assertEqual(booking.actual_hours, Decimal('2.75'))
        self.assertEqual(booking.notes, 'Test-Notiz')

    def test_assistant_workflow(self):
        """Test des kompletten Assistenz-Workflows"""
        # Login als Assistent
        self.client.login(username='assistant', password='test123')
        
        # Teste Monatsübersicht
        response = self.client.get(reverse('wfm:monthly-overview'))
        self.assertEqual(response.status_code, 200)
        
        # Teste Arbeitszeiten-API
        response = self.client.get(
            reverse('wfm:api-get-working-hours', args=[self.today.strftime('%Y-%m-%d')])
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['start_time'], '08:00')
        self.assertEqual(data['end_time'], '16:00')
        
        # Teste Urlaub beantragen
        response = self.client.post(
            reverse('wfm:api-vacation-request'),
            {
                'start_date': (self.tomorrow + timedelta(days=14)).strftime('%Y-%m-%d'),
                'end_date': (self.tomorrow + timedelta(days=15)).strftime('%Y-%m-%d'),
                'days': 2
            },
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        
        # Teste Zeitausgleich beantragen
        response = self.client.post(
            reverse('wfm:api-time-compensation-request'),
            {
                'date': (self.tomorrow + timedelta(days=21)).strftime('%Y-%m-%d'),
                'hours': '4.00'
            },
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)

    def test_calendar_view(self):
        """Test der Kalenderansicht"""
        # Login als Therapeut
        self.client.login(username='therapist', password='test123')
        
        # Teste Kalenderansicht
        response = self.client.get(reverse('wfm:calendar'))
        self.assertEqual(response.status_code, 200)
        
        # Teste Kalender-Events API
        response = self.client.get(
            reverse('wfm:api-calendar-events'),
            {'year': self.today.year, 'month': self.today.month}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue('events' in data)
        
        # Überprüfe ob Buchung in Events enthalten ist
        events = data['events']
        booking_events = [e for e in events if e['type'] == 'booking']
        self.assertEqual(len(booking_events), 1)
        self.assertEqual(booking_events[0]['booking_id'], self.booking.id)

    def test_data_validation(self):
        """Test der Datenvalidierung"""
        self.client.login(username='therapist', password='test123')
        
        # Teste ungültige Buchungszeiten
        response = self.client.post(
            reverse('wfm:api-therapist-booking'),
            {
                'date': self.today.strftime('%Y-%m-%d'),
                'start_time': '12:00',
                'end_time': '09:00'  # Ungültig: Ende vor Start
            },
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['success'])
        
        # Teste Überschneidung mit existierender Buchung
        response = self.client.post(
            reverse('wfm:api-therapist-booking'),
            {
                'date': self.today.strftime('%Y-%m-%d'),
                'start_time': '10:00',
                'end_time': '11:00'  # Überschneidet sich mit existierender Buchung
            },
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['success'])
