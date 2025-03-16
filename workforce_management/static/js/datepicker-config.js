// Globale Datepicker-Konfiguration
$(document).ready(function() {
    if ($.fn.datepicker) {
        $.fn.datepicker.defaults.language = 'de';
        $.fn.datepicker.defaults.format = 'dd.mm.yyyy';
        $.fn.datepicker.defaults.autoclose = true;
        $.fn.datepicker.defaults.todayHighlight = true;
        $.fn.datepicker.defaults.weekStart = 1;
    }
}); 