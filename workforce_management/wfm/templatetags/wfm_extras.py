from django import template

register = template.Library()

@register.simple_tag
def pop_param(params, key):
    """Entfernt einen Parameter aus dem QueryDict und gibt die restlichen Parameter zurück"""
    params.pop(key, None)
    return ''