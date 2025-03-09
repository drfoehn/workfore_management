from django import forms
from .models import WorkingHours, Vacation, ScheduleTemplate, TimeCompensation, UserDocument
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

class WorkingHoursForm(forms.ModelForm):
    display_date = forms.CharField(
        disabled=True,
        label=_("Datum"),
        required=False
    )
    scheduled_hours = forms.DecimalField(
        disabled=True,
        required=False,
        label=_("Soll-Stunden"),
        help_text=_("Geplante Arbeitszeit für diesen Tag")
    )

    class Meta:
        model = WorkingHours
        fields = ['date', 'scheduled_hours', 'start_time', 'end_time', 'break_duration', 'notes']
        widgets = {
            'date': forms.HiddenInput(),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
        }
        field_classes = {
            'date': forms.DateField
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Hole das Datum aus den initialen Daten
        date = self.initial.get('date')
        if not date and self.instance and self.instance.pk:
            date = self.instance.date
            
        if user and date:
            # Setze das Datum für beide Felder
            self.fields['date'].initial = date
            # Formatiere das Anzeigedatum
            self.fields['display_date'].initial = date.strftime('%d.%m.%Y')
            
            # Berechne die Soll-Stunden
            schedule = ScheduleTemplate.objects.filter(
                employee=user,
                weekday=date.weekday()
            )
            scheduled_hours = sum(
                (t.end_time.hour + t.end_time.minute/60) - 
                (t.start_time.hour + t.start_time.minute/60)
                for t in schedule
            )
            self.fields['scheduled_hours'].initial = round(scheduled_hours, 2)

class VacationRequestForm(forms.ModelForm):
    class Meta:
        model = Vacation
        fields = ['start_date', 'end_date', 'notes']
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['start_date'].widget = forms.DateInput(attrs={'type': 'date'})
        self.fields['end_date'].widget = forms.DateInput(attrs={'type': 'date'})
        
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        
        if start_date and end_date:
            if start_date > end_date:
                raise ValidationError(_('Enddatum muss nach Startdatum liegen'))
                
            # Erstelle temporäres Objekt für Stundenberechnung
            temp_vacation = Vacation(
                employee=self.instance.employee if self.instance else None,
                start_date=start_date,
                end_date=end_date
            )
            
            if not temp_vacation.check_vacation_hours_available():
                raise ValidationError(_('Nicht genügend Urlaubsstunden verfügbar'))
                
        return cleaned_data

class TimeCompensationForm(forms.ModelForm):
    class Meta:
        model = TimeCompensation
        fields = ['date', 'hours', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'readonly': 'readonly'}),
        }

class UserDocumentForm(forms.ModelForm):
    class Meta:
        model = UserDocument
        fields = ['user', 'file', 'display_name', 'notes']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-select'})
        } 