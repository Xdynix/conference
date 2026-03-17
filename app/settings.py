import secrets
import string
from pathlib import Path
from typing import Literal, cast

import django_stubs_ext
from decouple import Choices, Csv, config

from app.logging import configure_logging
from app.patches import (
    monkeypatch_django_async_auth,
    monkeypatch_django_ninja_openapi_csrf,
    monkeypatch_django_ninja_openapi_examples,
    monkeypatch_django_ninja_patch_dict,
)
from app.utils.cf_turnstile.types import CFTurnstileMode
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

CSRF_TRUSTED_ORIGINS: list[str] = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

# Reverse Proxy / Sub-Path Deployment
#
# When deploying under a sub-path (e.g., https://example.com/submission/), set
# FORCE_SCRIPT_NAME to the path prefix. This makes reverse(), build_absolute_uri(),
# {% url %}, STATIC_URL, MEDIA_URL, and cookie paths subpath-aware.
#
# Example nginx configuration:
#
#     location /submission/ {
#         proxy_pass http://127.0.0.1:8000/;  # Trailing slash strips prefix
#         proxy_set_header Host $host;
#         proxy_set_header X-Real-IP $remote_addr;
#         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
#         proxy_set_header X-Forwarded-Proto $scheme;
#         client_max_body_size 256m;  # Must exceed MAX_FINAL_SOURCE_SIZE * 4 (50MB * 4)
#     }
#
#     # If serving static files via nginx:
#     location /submission/static/ {
#         alias /path/to/staticfiles/;
#     }

_raw_script_name = config("FORCE_SCRIPT_NAME", default="")
FORCE_SCRIPT_NAME: str | None = _raw_script_name.rstrip("/") or None

# Cookies

# When FORCE_SCRIPT_NAME is set, cookie path defaults to the subpath so multiple
# instances on the same domain don't collide. Env vars can still override.

COOKIE_DOMAIN = config("COOKIE_DOMAIN", default=None)

COOKIE_PATH = config("COOKIE_PATH", default=FORCE_SCRIPT_NAME or "/")

CSRF_COOKIE_DOMAIN = COOKIE_DOMAIN

CSRF_COOKIE_PATH = COOKIE_PATH

CSRF_COOKIE_SECURE = True

SESSION_COOKIE_DOMAIN = COOKIE_DOMAIN

SESSION_COOKIE_PATH = COOKIE_PATH

SESSION_COOKIE_SECURE = True

SESSION_COOKIE_HTTPONLY = True

# Application Definition

INSTALLED_APPS = [
    "servestatic",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_extensions",
    "mailer",
    "ninja",
    "app.admin",
    "app.audit",
    "app.conference",
    "app.core",
    "app.frontend",
    "app.infra",
    "app.misc",
    "app.verikit",
    "django_cleanup",  # Must be last to connect signals after all other apps.
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "app.middleware.request_meta_middleware",
    "servestatic.middleware.ServeStaticMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
                "app.frontend.context_processors.cf_turnstile",
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
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA journal_mode=WAL;",
        },
    }
}

# Authentication

AUTH_USER_MODEL = "core.User"

AUTHENTICATION_BACKENDS = [
    "app.core.backends.EmailOrUsernameBackend",
]

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

# Static Files and File Upload

STATIC_ROOT: str = config("STATIC_ROOT", default=DATA_DIR / "static", cast=str)

STATIC_URL = f"{FORCE_SCRIPT_NAME}/static/" if FORCE_SCRIPT_NAME else "/static/"

# NOTE: File handling code assumes local filesystem storage. When switching to cloud
# storage (S3, GCS, etc.), audit file operations (deletion, validation, etc.).
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "servestatic.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_ROOT: Path = config("MEDIA_ROOT", default=DATA_DIR / "media", cast=Path)

MEDIA_URL = f"{FORCE_SCRIPT_NAME}/media/" if FORCE_SCRIPT_NAME else "/media/"

# Email

# TODO: Add prod check for the settings.

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
_sentry_dsn = config("SENTRY_DSN", default="")

configure_logging(
    log_dir=Path(_log_dir) if _log_dir else None,
    debug=DEBUG,
    sentry_dsn=_sentry_dsn,
)

# django-stubs

django_stubs_ext.monkeypatch()

# django-extensions

SHELL_PLUS = "ipython"

RUNSERVER_PLUS_POLLER_RELOADER_TYPE = "stat"

RUNSERVER_PLUS_EXCLUDE_PATTERNS = [
    str(BASE_DIR / ".cache" / "*"),
    str(BASE_DIR / "etc" / "*"),
    str(BASE_DIR / "scripts" / "*"),
    str(BASE_DIR / "tests" / "*"),
    str(BASE_DIR / "var" / "*"),
]

# Site

SITE_NAME = config("SITE_NAME", default="Django")

FAVICON_TEXT = config("FAVICON_TEXT", default="💡")

ADMIN_LOGIN_DENY_UNAUTHORIZED = config(
    "ADMIN_LOGIN_DENY_UNAUTHORIZED",
    default=True,
    cast=bool,
)

# Infra & Misc

MUTEX_RETENTION = config("MUTEX_RETENTION", default=7, cast=days)

DISK_FREE_THRESHOLD = config("DISK_FREE_THRESHOLD", default=2.0, cast=float)  # GB

# Reverse proxy

# REVERSE_PROXY_COUNT controls how many proxy IPs are appended after the client IP in
# X-Forwarded-For. django-ipware uses strict validation: len(ips) - 1 == proxy_count.
# 0 (default) means direct connection; all proxy headers are ignored.
#
# Examples:
#   Dev (no proxy):            (defaults are fine, no env vars needed)
#   Sidecar nginx only:        REVERSE_PROXY_COUNT=1
#   Sidecar + Cloudflare:      REVERSE_PROXY_COUNT=2
#                              REVERSE_PROXY_IP_HEADERS=CF-Connecting-IP,X-Forwarded-For
#   Adopt upstream request ID: REVERSE_PROXY_REQUEST_ID_HEADER=X-Request-ID

REVERSE_PROXY_COUNT: int = config("REVERSE_PROXY_COUNT", default=0, cast=int)

# When behind a reverse proxy that terminates SSL, trust X-Forwarded-Proto so that
# request.is_secure() returns True for HTTPS requests. This is required for correct CSRF
# origin checks, secure cookie handling, and `build_absolute_uri()` scheme.
SECURE_PROXY_SSL_HEADER: tuple[str, str] | None = (
    ("HTTP_X_FORWARDED_PROTO", "https") if REVERSE_PROXY_COUNT > 0 else None
)

REVERSE_PROXY_REQUEST_ID_HEADER: str = config(
    "REVERSE_PROXY_REQUEST_ID_HEADER",
    default="",
)

REVERSE_PROXY_IP_HEADERS: list[str] = config(
    "REVERSE_PROXY_IP_HEADERS",
    default="",
    cast=Csv(),
)

# Cloudflare Turnstile

# TODO: Add prod check for the settings.

CF_TURNSTILE_MODE: CFTurnstileMode = config(
    "CF_TURNSTILE_MODE",
    default=CFTurnstileMode.STRICT,
    cast=CFTurnstileMode,
)

# TODO: Add geo-based mode overriding.

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

API_KEY_SESSION_EXPIRY = config("API_KEY_SESSION_EXPIRY", default=3600, cast=seconds)

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

# TODO: Add prod check for the settings.

PASSWORD_RESET_PAGE_URL = config("PASSWORD_RESET_PAGE_URL", default="")

PASSWORD_RESET_PAGE_URL_NAME = config(
    "PASSWORD_RESET_PAGE_URL_NAME",
    default="frontend:password-reset-confirm",
)

# File Downloads

# In "django" mode, files are served directly by Django using `FileResponse`. In "nginx"
# mode, Django returns an empty response with `X-Accel-Redirect header`, letting nginx
# serve the file from an internal location.
#
# Example nginx configuration for internal file serving:
#
#     location /internal-media/ {
#         internal;
#         alias /var/www/media/;
#     }
#
# Corresponding Django settings:
#
#     FILE_DOWNLOAD_MODE=nginx
#     FILE_DOWNLOAD_NGINX_INTERNAL_PREFIX=/internal-media
#     MEDIA_ROOT=/var/www/media
#
# The internal location path must match FILE_DOWNLOAD_NGINX_INTERNAL_PREFIX, and the
# alias must point to MEDIA_ROOT (or wherever the storage backend stores files).

# TODO: Add prod check for the settings.

FileDownloadMode = Literal["django", "nginx"]

FILE_DOWNLOAD_MODE: FileDownloadMode = config(
    "FILE_DOWNLOAD_MODE",
    default="django",
    cast=Choices(cast(list[FileDownloadMode], ["django", "nginx"])),
)

FILE_DOWNLOAD_NGINX_INTERNAL_PREFIX = config(
    "FILE_DOWNLOAD_NGINX_INTERNAL_PREFIX",
    default="",
)

FILE_DOWNLOAD_NGINX_HEADER = config(
    "FILE_DOWNLOAD_NGINX_HEADER",
    default="X-Accel-Redirect",
)

# Typst

TYPST_FONT_DIR: Path = config(
    "TYPST_FONT_DIR",
    default=BASE_DIR / "etc" / "fonts",
    cast=Path,
)

TYPST_ASSET_DIR: Path = config(
    "TYPST_ASSET_DIR",
    default=DATA_DIR / "assets",
    cast=Path,
)

# Conference

INVITATION_EMAIL_INTERVAL = config(
    "INVITATION_EMAIL_INTERVAL",
    default=3600,
    cast=seconds,
)

REVIEWER_NOTIFICATION_EMAIL_INTERVAL = config(
    "REVIEWER_NOTIFICATION_EMAIL_INTERVAL",
    default=3600,
    cast=seconds,
)

MAX_SUBMISSION_SIZE = 20 * 1024 * 1024

ALLOWED_SUBMISSION_TYPES = {
    "application/pdf": [".pdf"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [
        ".docx"
    ],
    "application/msword": [".doc"],
}

MAX_FINAL_SOURCE_SIZE = 50 * 1024 * 1024

ALLOWED_FINAL_SOURCE_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [
        ".docx"
    ],
    "application/msword": [".doc"],
    "application/zip": [".zip"],
    "application/gzip": [".tgz", ".gz"],
}

MAX_FINAL_VIEWABLE_SIZE = MAX_SUBMISSION_SIZE

ALLOWED_FINAL_VIEWABLE_TYPES = ALLOWED_SUBMISSION_TYPES

MAX_PROOF_SIZE = MAX_SUBMISSION_SIZE

ALLOWED_PROOF_TYPES = {
    "application/pdf": [".pdf"],
}

MAX_CONFERENCE_FILE_SIZE = 10 * 1024 * 1024

ALLOWED_CONFERENCE_FILE_TYPES = {
    "application/pdf": [".pdf"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [
        ".docx"
    ],
    "application/msword": [".doc"],
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
    "application/vnd.ms-excel": [".xls"],
    "image/png": [".png"],
    "image/jpeg": [".jpg", ".jpeg"],
}

DUPLICATE_SCAN_WINDOW = config("DUPLICATE_SCAN_WINDOW", default=365 * 3, cast=days)

DUPLICATE_PAPER_COUNT_CAP = config("DUPLICATE_PAPER_COUNT_CAP", default=5000, cast=int)

DUPLICATE_TITLE_SIMILARITY_THRESHOLD = config(
    "DUPLICATE_TITLE_SIMILARITY_THRESHOLD",
    default=0.85,
    cast=float,
)

DUPLICATE_RETENTION_SUCCESSFUL = config(
    "DUPLICATE_RETENTION_SUCCESSFUL",
    default=3,
    cast=int,
)

DUPLICATE_RETENTION_FAILED = config(
    "DUPLICATE_RETENTION_FAILED",
    default=2,
    cast=int,
)

# Frontend

BRANDING_LOGO_URL = config("BRANDING_LOGO_URL", default="")

BRANDING_LOGO_ALT = config("BRANDING_LOGO_ALT", default="")

BRANDING_LOGO_HEIGHT = config("BRANDING_LOGO_HEIGHT", default=0, cast=int)

BRANDING_PARENT_URL = config("BRANDING_PARENT_URL", default="")

BRANDING_FAVICON_URL = config("BRANDING_FAVICON_URL", default="")

# Monkeypatch

monkeypatch_django_async_auth()
monkeypatch_django_ninja_openapi_csrf()
monkeypatch_django_ninja_openapi_examples()
monkeypatch_django_ninja_patch_dict()
