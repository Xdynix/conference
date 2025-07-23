"""Custom Django admin configuration with enhanced admin site."""

from django.contrib.admin import apps as django_admin_apps


class AdminConfig(django_admin_apps.AdminConfig):
    default_site = "app.admin.sites.AdminSite"
