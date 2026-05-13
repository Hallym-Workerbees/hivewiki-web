from pathlib import Path
from urllib.parse import urlparse

import environ

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(
    DJANGO_DEBUG=(bool, True),
    DJANGO_LOG_JSON=(bool, True),
    DJANGO_LOG_HEALTHCHECKS=(bool, False),
    DJANGO_SESSION_COOKIE_SECURE=(bool, False),
    DJANGO_CSRF_COOKIE_SECURE=(bool, False),
    DJANGO_SECURE_SSL_REDIRECT=(bool, False),
    DJANGO_SECURE_HSTS_SECONDS=(int, 0),
    DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=(bool, False),
    DJANGO_SECURE_HSTS_PRELOAD=(bool, False),
    DJANGO_SECURE_CONTENT_TYPE_NOSNIFF=(bool, True),
    DJANGO_X_FRAME_OPTIONS=("str", "DENY"),
    DJANGO_LOG_LEVEL=("str", "INFO"),
    LOGIN_RATE_LIMIT_ATTEMPTS=(int, 5),
    LOGIN_RATE_LIMIT_WINDOW_SECONDS=(int, 600),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
DJANGO_LOG_JSON = env("DJANGO_LOG_JSON")
DJANGO_LOG_HEALTHCHECKS = env("DJANGO_LOG_HEALTHCHECKS")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
CLIENT_IP_HEADER = env("DJANGO_CLIENT_IP_HEADER", default="")
GOOGLE_OAUTH_CLIENT_ID = env("GOOGLE_OAUTH_CLIENT_ID", default="")
GOOGLE_OAUTH_CLIENT_SECRET = env("GOOGLE_OAUTH_CLIENT_SECRET", default="")
GITHUB_OAUTH_CLIENT_ID = env("GITHUB_OAUTH_CLIENT_ID", default="")
GITHUB_OAUTH_CLIENT_SECRET = env("GITHUB_OAUTH_CLIENT_SECRET", default="")
AWS_S3_UPLOAD_ACCESS_KEY_ID = env("AWS_S3_UPLOAD_ACCESS_KEY_ID", default="")
AWS_S3_UPLOAD_SECRET_ACCESS_KEY = env("AWS_S3_UPLOAD_SECRET_ACCESS_KEY", default="")
AWS_S3_UPLOAD_REGION = env("AWS_S3_UPLOAD_REGION", default="")
AWS_S3_UPLOAD_BUCKET = env("AWS_S3_UPLOAD_BUCKET", default="")
AWS_S3_UPLOAD_ENDPOINT_URL = env("AWS_S3_UPLOAD_ENDPOINT_URL", default="")
AWS_S3_UPLOAD_PUBLIC_BASE_URL = env("AWS_S3_UPLOAD_PUBLIC_BASE_URL", default="")
AWS_S3_PROFILE_UPLOAD_PREFIX = env("AWS_S3_PROFILE_UPLOAD_PREFIX", default="profiles")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "tailwind",
    "theme",
    "apps.core",
    "apps.accounts",
]

MIDDLEWARE = [
    "config.healthchecks.HealthcheckHostNormalizationMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.CurrentUserMiddleware",
    "apps.accounts.middleware.TimezoneMiddleware",
    "config.logging.RequestLoggingMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.accounts.context_processors.current_user",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST"),
        "PORT": env("POSTGRES_PORT"),
    }
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
        "KEY_PREFIX": "",
    }
}
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=60 * 60 * 24 * 14)
SESSION_COOKIE_SECURE = env("DJANGO_SESSION_COOKIE_SECURE")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = env("DJANGO_SESSION_COOKIE_SAMESITE", default="Lax")
CSRF_COOKIE_SECURE = env("DJANGO_CSRF_COOKIE_SECURE")
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = env("DJANGO_CSRF_COOKIE_SAMESITE", default="Lax")
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"
LOGIN_RATE_LIMIT_ATTEMPTS = env("LOGIN_RATE_LIMIT_ATTEMPTS")
LOGIN_RATE_LIMIT_WINDOW_SECONDS = env("LOGIN_RATE_LIMIT_WINDOW_SECONDS")
SECURE_SSL_REDIRECT = env("DJANGO_SECURE_SSL_REDIRECT")
SECURE_HSTS_SECONDS = env("DJANGO_SECURE_HSTS_SECONDS")
SECURE_HSTS_INCLUDE_SUBDOMAINS = env("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS")
SECURE_HSTS_PRELOAD = env("DJANGO_SECURE_HSTS_PRELOAD")
SECURE_CONTENT_TYPE_NOSNIFF = env("DJANGO_SECURE_CONTENT_TYPE_NOSNIFF")
X_FRAME_OPTIONS = env("DJANGO_X_FRAME_OPTIONS", default="DENY")
DJANGO_LOG_LEVEL = env("DJANGO_LOG_LEVEL")

secure_proxy_ssl_header = env("DJANGO_SECURE_PROXY_SSL_HEADER", default="")
if secure_proxy_ssl_header:
    header_name, _, header_value = secure_proxy_ssl_header.partition(",")
    if header_name and header_value:
        SECURE_PROXY_SSL_HEADER = (header_name.strip(), header_value.strip())


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "ko-kr"

TIME_ZONE = "Asia/Seoul"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

if not AWS_S3_UPLOAD_PUBLIC_BASE_URL and AWS_S3_UPLOAD_BUCKET:
    if AWS_S3_UPLOAD_ENDPOINT_URL:
        endpoint = urlparse(AWS_S3_UPLOAD_ENDPOINT_URL)
        endpoint_base = endpoint.netloc or endpoint.path
        if endpoint_base:
            AWS_S3_UPLOAD_PUBLIC_BASE_URL = (
                f"{endpoint.scheme or 'https'}://{endpoint_base}/{AWS_S3_UPLOAD_BUCKET}"
            )
    elif AWS_S3_UPLOAD_REGION:
        AWS_S3_UPLOAD_PUBLIC_BASE_URL = (
            f"https://{AWS_S3_UPLOAD_BUCKET}.s3.{AWS_S3_UPLOAD_REGION}.amazonaws.com"
        )

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_context": {
            "()": "config.logging.RequestContextFilter",
        },
        "suppress_healthcheck_access_logs": {
            "()": "config.logging.SuppressHealthcheckAccessLogsFilter",
        },
    },
    "formatters": {
        "json": {
            "()": "config.logging.JsonFormatter",
        },
        "plain": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_context", "suppress_healthcheck_access_logs"],
            "formatter": "json" if DJANGO_LOG_JSON else "plain",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": DJANGO_LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": DJANGO_LOG_LEVEL,
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console"],
            "level": DJANGO_LOG_LEVEL,
            "propagate": False,
        },
        "hivewiki.request": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["console"],
            "level": DJANGO_LOG_LEVEL,
            "propagate": False,
        },
        "gunicorn.access": {
            "handlers": ["console"],
            "level": DJANGO_LOG_LEVEL,
            "propagate": False,
        },
    },
}

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
