"""Central registration for custom URL path converters.

Registering converters in a root URLconf alone is not enough for test collection or any
code path that imports a sub-URLconf directly. In those cases, Django parses urlpatterns
before the root URLconf is loaded, so the converter is missing and the import can fail
mid-module with a misleading "no urlpatterns" error.

Import this module at the top of any URLconf that needs custom converters. Python's
module cache ensures the registration runs once per process, so repeated imports are
safe and do not re-register the converter.
"""

from django.urls import register_converter
from ulid_django.converters import ULIDConverter

register_converter(ULIDConverter, "ulid")
