import os

DJANGO_ENV = os.getenv("DJANGO_ENV", "dev")

if DJANGO_ENV == "prod":
    from config.settings.prod import *  # noqa: F401, F403
else:
    from config.settings.dev import *  # noqa: F401, F403
