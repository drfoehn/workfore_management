from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from .models import WorkingHours, Vacation, VacationEntitlement, SickLeave
from .forms import WorkingHoursForm, VacationRequestForm

class OwnerRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.role == 'OWNER'

@login_required
def dashboard(request):
    return render(request, 'wfm/dashboard.html')

class WorkingHoursListView(LoginRequiredMixin, ListView):
    model = WorkingHours
    template_name = 'wfm/working_hours_list.html'
    context_object_name = 'working_hours'

    def get_queryset(self):
        if self.request.user.role == 'OWNER':
            return WorkingHours.objects.all()
        return WorkingHours.objects.filter(employee=self.request.user)

class WorkingHoursCreateView(LoginRequiredMixin, CreateView):
    model = WorkingHours
    form_class = WorkingHoursForm
    template_name = 'wfm/working_hours_form.html'
    success_url = reverse_lazy('working-hours-list')

    def form_valid(self, form):
        form.instance.employee = self.request.user
        return super().form_valid(form)

class VacationListView(LoginRequiredMixin, ListView):
    model = Vacation
    template_name = 'wfm/vacation_list.html'
    context_object_name = 'vacations'

    def get_queryset(self):
        if self.request.user.role == 'OWNER':
            return Vacation.objects.all()
        return Vacation.objects.filter(employee=self.request.user)

class VacationRequestView(LoginRequiredMixin, CreateView):
    model = Vacation
    form_class = VacationRequestForm
    template_name = 'wfm/vacation_request_form.html'
    success_url = reverse_lazy('vacation-list')

    def form_valid(self, form):
        form.instance.employee = self.request.user
        return super().form_valid(form)

def index(request):
    if request.user.is_authenticated:
        return redirect('wfm:dashboard')
    return render(request, 'wfm/index.html')
