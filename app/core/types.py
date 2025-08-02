__all__ = (
    "AuthedHttpRequest",
    "HttpRequest",
)


from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest as DjangoHttpRequest

from app.core.models import User


class HttpRequest(DjangoHttpRequest):
    user: User | AnonymousUser


class AuthedHttpRequest(HttpRequest):
    user: User
