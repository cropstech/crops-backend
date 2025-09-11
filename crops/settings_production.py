"""
Production settings for crops project.
Optimized for Lightsail Containers deployment.
"""

from .settings import *
import dj_database_url

# Override base settings for production
# Single source of truth: respect DEBUG env, but ensure security defaults
DEBUG = env.bool('DEBUG', default=False)

# Security settings
SECRET_KEY = env('SECRET_KEY')
# Parse comma-separated values into lists for these settings
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['*.lightsail.aws', '*.amazonaws.com'])

# Database - Use PostgreSQL with connection pooling
DATABASES = {
    'default': dj_database_url.config(
        default=env('DATABASE_URL'),
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# Production CORS settings
# Expect comma-separated values in environment variables
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

# Security middleware
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Security settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
X_FRAME_OPTIONS = 'DENY'

# Force HTTPS in production
SECURE_SSL_REDIRECT = env('SECURE_SSL_REDIRECT', default=False)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Proxy headers configuration for AWS Lightsail load balancer
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PROTO = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# Cache configuration using Redis
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'crops-locmem-cache',
    }
}

# Session configuration (DB-backed sessions to avoid Redis)
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# Logging for production
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            'format': '%(asctime)s %(name)s %(levelname)s %(message)s',
            'class': 'pythonjsonlogger.jsonlogger.JsonFormatter',
        },
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': env('DJANGO_LOG_LEVEL', default='DEBUG'),
            'propagate': False,
        },
        'crops': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Email settings for production
EMAIL_BACKEND = 'django_ses.SESBackend'
AWS_SES_REGION_NAME = env('AWS_SES_REGION_NAME', default='us-east-2')
AWS_SES_REGION_ENDPOINT = f'email.{AWS_SES_REGION_NAME}.amazonaws.com'

# Performance optimizations
DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50MB

# Production-specific AWS settings
AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': 'max-age=86400',
}

# Disable browsable API in production
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

# Health check endpoint
HEALTH_CHECK_PROVIDERS = [
    'health_check.db',
    'health_check.cache',
    'health_check.storage',
]