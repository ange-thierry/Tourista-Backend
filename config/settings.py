"""
Django settings for the Tourista Rwanda backend.

Values that differ between environments are read from environment variables
(optionally loaded from a `.env` file next to manage.py). See `.env.example`.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {'1', 'true', 'yes', 'on'}


def env_list(name: str, default: str = '') -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-insecure-change-me-tourista-rwanda')
DEBUG = env_bool('DJANGO_DEBUG', True)
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1]')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    # Local apps
    'core',
    'accounts',
    'listings',
    'bookings',
    'providers',
    'inquiries',
    'reviews',
    'messaging',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# SQLite by default; set the POSTGRES_* variables to use PostgreSQL instead
# (requires `pip install "psycopg[binary]"`).
if os.getenv('POSTGRES_DB'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('POSTGRES_DB'),
            'USER': os.getenv('POSTGRES_USER', 'postgres'),
            'PASSWORD': os.getenv('POSTGRES_PASSWORD', ''),
            'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
            'PORT': os.getenv('POSTGRES_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 6},
    },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Kigali'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Uploaded images (provider catalog, company photos). Served by Django in DEBUG;
# put them behind your web server / object storage in production.
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
UPLOAD_MAX_BYTES = int(os.getenv('UPLOAD_MAX_MB', '5')) * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = UPLOAD_MAX_BYTES + 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = UPLOAD_MAX_BYTES

# --- Email ------------------------------------------------------------------
# Console backend prints emails in the runserver terminal. Set EMAIL_HOST etc. for SMTP.
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND',
    'django.core.mail.backends.smtp.EmailBackend'
    if os.getenv('EMAIL_HOST')
    else 'django.core.mail.backends.console.EmailBackend',
)
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Tourista Rwanda <no-reply@tourista.rw>')
# Who receives contact-form and demo-request alerts (default: admin accounts).
STAFF_NOTIFICATION_EMAILS = env_list('STAFF_NOTIFICATION_EMAILS')
# Used to build links in emails (verify email, reset password, bookings).
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:8080')
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24  # 24 hours

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- REST framework -------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer']
    + (['rest_framework.renderers.BrowsableAPIRenderer'] if DEBUG else []),
    'DEFAULT_THROTTLE_RATES': {
        'auth': os.getenv('AUTH_THROTTLE_RATE', '30/minute'),
        'public_form': os.getenv('PUBLIC_FORM_THROTTLE_RATE', '20/hour'),
        'booking_create': os.getenv('BOOKING_THROTTLE_RATE', '30/hour'),
        'lookup': os.getenv('LOOKUP_THROTTLE_RATE', '20/hour'),
        'upload': os.getenv('UPLOAD_THROTTLE_RATE', '60/hour'),
    },
    'DEFAULT_PAGINATION_CLASS': None,
    'EXCEPTION_HANDLER': 'core.exceptions.api_exception_handler',
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=int(os.getenv('JWT_ACCESS_MINUTES', '60'))),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=int(os.getenv('JWT_REFRESH_DAYS', '7'))),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# The refresh token lives in an httpOnly cookie (not readable by JavaScript);
# the short-lived access token is kept only in memory by the frontend.
REFRESH_COOKIE_NAME = 'tourista_refresh'
REFRESH_COOKIE_PATH = '/api/auth/'
REFRESH_COOKIE_SECURE = env_bool('REFRESH_COOKIE_SECURE', not DEBUG)
# 'Lax' works when the frontend and API share a site (Vite proxy, same domain).
# Use 'None' (requires HTTPS) if the frontend is served from a different site.
REFRESH_COOKIE_SAMESITE = os.getenv('REFRESH_COOKIE_SAMESITE', 'Lax')

# --- CORS: the Vite dev server runs on :8080 ------------------------------
CORS_ALLOWED_ORIGINS = env_list(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:8080,http://127.0.0.1:8080,http://localhost:5173,http://127.0.0.1:5173',
)
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS
CORS_ALLOW_CREDENTIALS = True  # needed for the refresh-token cookie on cross-origin setups

# Password given to the seeded demo accounts (see `manage.py seed_demo`).
DEMO_PASSWORD = os.getenv('DEMO_PASSWORD', 'Tourista@2026')

# Fast password hashing for the test suite only.
if 'test' in sys.argv:
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
    EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
        key: '10000/minute' for key in REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
    }
    MEDIA_ROOT = BASE_DIR / 'media_test'

# HTTPS hardening when running in production mode.
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', True)
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv('DJANGO_HSTS_SECONDS', '0'))
