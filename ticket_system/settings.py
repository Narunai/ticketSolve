"""
Django settings for ticket_system project.

Production baseline: Django 5.2 LTS.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/6.0/ref/settings/
"""

import os
import sys
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file automatically if present
env_path = BASE_DIR / '.env'
if env_path.exists():
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                # Values injected by systemd/Docker take precedence over the
                # developer-only project .env file.
                os.environ.setdefault(key.strip(), val.strip())

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ('true', '1', 't', 'yes', 'on')


def env_list(name):
    return [
        value.strip()
        for value in os.environ.get(name, '').split(',')
        if value.strip()
    ]


DEBUG = env_bool('DEBUG', False)
IS_TESTING = 'test' in sys.argv
IS_PRODUCTION = not DEBUG and not IS_TESTING

SECRET_KEY = os.environ.get('SECRET_KEY', '').strip()
if not SECRET_KEY:
    if DEBUG or IS_TESTING:
        SECRET_KEY = 'django-insecure-local-development-only'
    else:
        raise ImproperlyConfigured(
            'SECRET_KEY must be provided through the VPS environment file.'
        )

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS')
if not ALLOWED_HOSTS:
    if IS_PRODUCTION:
        raise ImproperlyConfigured(
            'ALLOWED_HOSTS must be configured for production.'
        )
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]', 'testserver']

CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')

FIELD_ENCRYPTION_KEYS = env_list('FIELD_ENCRYPTION_KEYS')
if IS_PRODUCTION and not FIELD_ENCRYPTION_KEYS:
    raise ImproperlyConfigured(
        'FIELD_ENCRYPTION_KEYS must contain at least one Fernet key in production.'
    )


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'tickets',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'tickets.security.SecurityHeadersMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ticket_system.urls'

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
                'tickets.context_processors.language_processor',
                'tickets.context_processors.notification_processor',
            ],
        },
    },
]

WSGI_APPLICATION = 'ticket_system.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 12},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = os.environ.get('TIME_ZONE', 'Asia/Bangkok')

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User Model
AUTH_USER_MODEL = 'tickets.CustomUser'

AUTHENTICATION_BACKENDS = [
    'tickets.backends.EmailOrUsernameModelBackend',
]



# Auth Redirects
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# Production transport and cookie security. Nginx terminates TLS and supplies
# X-Forwarded-Proto through proxy_params.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', IS_PRODUCTION)
SESSION_COOKIE_SECURE = IS_PRODUCTION
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = int(os.environ.get('SESSION_COOKIE_AGE', 8 * 60 * 60))
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_SECURE = IS_PRODUCTION
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_HSTS_SECONDS = int(os.environ.get(
    'SECURE_HSTS_SECONDS',
    31536000 if IS_PRODUCTION else 0,
))
SECURE_HSTS_INCLUDE_SUBDOMAINS = IS_PRODUCTION
SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', IS_PRODUCTION)
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

LOGIN_THROTTLE_MAX_FAILURES = int(os.environ.get('LOGIN_THROTTLE_MAX_FAILURES', 5))
LOGIN_THROTTLE_WINDOW_SECONDS = int(os.environ.get('LOGIN_THROTTLE_WINDOW_SECONDS', 15 * 60))
LOGIN_THROTTLE_LOCK_SECONDS = int(os.environ.get('LOGIN_THROTTLE_LOCK_SECONDS', 15 * 60))
SIMPLE_PASSWORD_LOCK_SECONDS = int(os.environ.get('SIMPLE_PASSWORD_LOCK_SECONDS', 10 * 60))

# Email Configuration (Supports Console and Real Gmail SMTP Delivery)

EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', 'noreply@localhost').strip()
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '').replace(' ', '').strip()
EMAIL_SERVICE = os.environ.get('EMAIL_SERVICE', 'smtp' if EMAIL_HOST_PASSWORD else 'console').lower()

if EMAIL_SERVICE == 'smtp' and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
    EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
    EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
    DEFAULT_FROM_EMAIL = f"TicketSolve Support <{EMAIL_HOST_USER}>"
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    DEFAULT_FROM_EMAIL = f"TicketSolve Support <{EMAIL_HOST_USER}>"

# Media files configuration (for attachments)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Bound the entire request as well as each file. Files above the memory
# threshold are streamed to a temporary file by Django.
DATA_UPLOAD_MAX_MEMORY_SIZE = 60 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2_621_440
