import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")

DEBUG = os.environ.get("DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "core",
    "taxonomy",
    "products",
    "classification",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation."
        "UserAttributeSimilarityValidator",
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MAX_UPLOAD_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "10"))
ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".xlsx"}

AI_MODEL_NAME = os.environ.get("AI_MODEL_NAME", "gemini-3.5-flash-lite")
AI_REQUEST_TIMEOUT = int(os.environ.get("AI_REQUEST_TIMEOUT", "30"))
# Client-side requests-per-minute cap shared by all worker threads.
# Set to 0 to disable pacing. Gemini free tier allows 15 RPM for
# gemini-*-flash-lite models; raise this if you upgrade to a paid plan.
AI_RATE_LIMIT_RPM = int(os.environ.get("AI_RATE_LIMIT_RPM", "15"))
AI_RETRY_MAX_ATTEMPTS = int(os.environ.get("AI_RETRY_MAX_ATTEMPTS", "3"))
AI_RETRY_BASE_DELAY = float(os.environ.get("AI_RETRY_BASE_DELAY", "2.0"))
CLASSIFICATION_CONFIDENCE_THRESHOLD = int(
    os.environ.get("CLASSIFICATION_CONFIDENCE_THRESHOLD", "70")
)
CLASSIFICATION_CONCURRENCY_LIMIT = int(
    os.environ.get("CLASSIFICATION_CONCURRENCY_LIMIT", "5")
)

TAXONOMY_CACHE_TTL = int(os.environ.get("TAXONOMY_CACHE_TTL", "3600"))

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "classification-cache",
    }
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "EXCEPTION_HANDLER": "config.exception_handlers.custom_exception_handler",
}

CORS_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS", "http://localhost:5173"
).split(",")
CORS_ALLOW_CREDENTIALS = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "classification": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "products": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
