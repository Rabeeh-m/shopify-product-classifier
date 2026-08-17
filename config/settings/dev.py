import os

from config.settings.base import *  # noqa: F401, F403

DEBUG = os.environ.get("DEBUG", "True").lower() in ("true", "1", "yes")

INSTALLED_APPS += [  # noqa: F405
    "debug_toolbar",
]

MIDDLEWARE += [  # noqa: F405
    "debug_toolbar.middleware.DebugToolbarMiddleware",
]

INTERNAL_IPS = ["127.0.0.1"]

DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": lambda _request: DEBUG,
    "IS_RUNNING_TESTS": False,
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}
