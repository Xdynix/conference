import secrets
import string
from pathlib import Path

import django_stubs_ext
from decouple import Csv, config

from app.logging import configure_logging
from app.patches import (
    monkeypatch_django_async_auth,
    monkeypatch_django_aupdate_session_auth_hash,
    monkeypatch_django_ninja_openapi_csrf,
    monkeypatch_django_ninja_patch_dict,
)
from app.utils.shorthands import days, seconds

# Common

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR: Path = config("DATA_DIR", default=BASE_DIR / "var", cast=Path)


# Security

SECRET_KEY = config(
    "SECRET_KEY",
    default="".join(secrets.choice(string.printable) for _ in range(64)),
)

DEBUG = config("DEBUG", default=False, cast=bool)

ALLOWED_HOSTS: list[str] = config("ALLOWED_HOSTS", default="", cast=Csv())


# Cookies

COOKIE_DOMAIN = config("COOKIE_DOMAIN", default=None)

COOKIE_PATH = config("COOKIE_PATH", default="/")

CSRF_COOKIE_DOMAIN = COOKIE_DOMAIN

CSRF_COOKIE_PATH = COOKIE_PATH

CSRF_COOKIE_SECURE = True

SESSION_COOKIE_DOMAIN = COOKIE_DOMAIN

SESSION_COOKIE_PATH = COOKIE_PATH

SESSION_COOKIE_SECURE = True

SESSION_COOKIE_HTTPONLY = True


# Application Definition

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_extensions",
    "mailer",
    "ninja",
    "app.admin",
    "app.conference",
    "app.core",
    "app.infra",
    "app.misc",
    "app.turnstile",
    "app.verikit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "servestatic.middleware.ServeStaticMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # TODO: Add logging middleware: bind request context (request, response, session).
]

ROOT_URLCONF = "app.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "app.wsgi.application"


# Database

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": config("DATABASE_PATH", default=DATA_DIR / "db.sqlite3", cast=Path),
        "OPTIONS": {
            "timeout": 60,
        },
    }
}


# Authentication

AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

SESSION_SERIALIZER = "app.utils.orjson.ORJSONSerializer"


# Internationalization

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static Files

STATIC_ROOT: str = config("STATIC_ROOT", default=DATA_DIR / "static", cast=str)

STATIC_URL = "static/"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "servestatic.storage.CompressedManifestStaticFilesStorage",
    },
}


# Misc

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Email

EMAIL_BACKEND = "mailer.backend.DbBackend"

MAILER_EMAIL_BACKEND: str = config(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)

MAILER_EMPTY_QUEUE_SLEEP = 5

EMAIL_FILE_PATH = config("EMAIL_FILE_PATH", default=DATA_DIR / "emails", cast=str)

EMAIL_HOST = config("EMAIL_HOST", default="localhost")

EMAIL_PORT = config("EMAIL_PORT", default=25, cast=int)

EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")

EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")

EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=False, cast=bool)

EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=False, cast=bool)

EMAIL_TIMEOUT = config("EMAIL_TIMEOUT", default=60, cast=int)

EMAIL_SUBJECT_PREFIX = config("EMAIL_SUBJECT_PREFIX", default="[Django] ")

SERVER_EMAIL = config("SERVER_EMAIL", default="no-reply@localhost")

DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="no-reply@localhost")


# Logging

LOGGING_CONFIG = None

_log_dir = config("LOG_DIR", default="")

configure_logging(
    log_dir=Path(_log_dir) if _log_dir else None,
    debug=DEBUG,
)


# django-stubs

django_stubs_ext.monkeypatch()


# django-extensions

SHELL_PLUS = "ipython"

RUNSERVER_PLUS_EXCLUDE_PATTERNS = [
    str(BASE_DIR / ".cache" / "*"),
    str(BASE_DIR / "etc" / "*"),
    str(BASE_DIR / "scripts" / "*"),
    str(BASE_DIR / "seed" / "*"),
    str(BASE_DIR / "tests" / "*"),
    str(BASE_DIR / "var" / "*"),
]


# django-ipware

# TODO: Configure `IPWARE_META_PRECEDENCE_ORDER`.


# Site

SITE_NAME = config("SITE_NAME", default="Django")

FAVICON_TEXT = config("FAVICON_TEXT", default="💡")


# Infra

MUTEX_RETENTION = config("MUTEX_RETENTION", default=7, cast=days)


# Cloudflare Turnstile

CF_TURNSTILE_SITE_KEY = config("CF_TURNSTILE_SITE_KEY", default="")

CF_TURNSTILE_SECRET_KEY = config("CF_TURNSTILE_SECRET_KEY", default="")

CF_TURNSTILE_VERIFY_URL = config(
    "CF_TURNSTILE_VERIFY_URL",
    default="https://challenges.cloudflare.com/turnstile/v0/siteverify",
)

CF_TURNSTILE_RESPONSE_HEADER_NAME = config(
    "CF_TURNSTILE_RESPONSE_HEADER_NAME",
    default="cf-turnstile-response",
)

CF_TURNSTILE_BYPASS_SECRETS: frozenset[str] = frozenset(
    config(
        "CF_TURNSTILE_BYPASS_SECRETS",
        default="",
        cast=Csv(),
    )
)


# Verikit

VERIKIT_EMAIL_CODE_INTERVAL = config(
    "VERIKIT_EMAIL_CODE_INTERVAL",
    default=60,
    cast=seconds,
)

VERIKIT_EMAIL_CODE_EXPIRY = config(
    "VERIKIT_EMAIL_CODE_EXPIRY",
    default=1800,
    cast=seconds,
)

VERIKIT_EMAIL_TOKEN_EXPIRY = config(
    "VERIKIT_EMAIL_TOKEN_EXPIRY",
    default=3600,
    cast=seconds,
)

VERIKIT_VERIFICATION_RETENTION = config(
    "VERIKIT_VERIFICATION_RETENTION",
    default=7,
    cast=days,
)


# Core

PASSWORD_RESET_TOKEN_INTERVAL = config(
    "PASSWORD_RESET_TOKEN_INTERVAL",
    default=60,
    cast=seconds,
)

PASSWORD_RESET_TOKEN_EXPIRY = config(
    "PASSWORD_RESET_TOKEN_EXPIRY",
    default=1200,
    cast=seconds,
)

PASSWORD_RESET_TOKEN_RETENTION = config(
    "PASSWORD_RESET_TOKEN_RETENTION",
    default=7,
    cast=days,
)

PASSWORD_RESET_PAGE_URI = config("PASSWORD_RESET_PAGE_URI", default="")


# Monkeypatch

monkeypatch_django_async_auth()
monkeypatch_django_aupdate_session_auth_hash()
monkeypatch_django_ninja_openapi_csrf()
monkeypatch_django_ninja_patch_dict()
