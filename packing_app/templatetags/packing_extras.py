from django import template

register = template.Library()


@register.filter
def split(value, sep):
    return value.split(sep)


@register.filter
def index(lst, i):
    try:
        return lst[int(i)]
    except (IndexError, TypeError, ValueError):
        return ""
