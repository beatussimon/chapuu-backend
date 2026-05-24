# Import pillow_avif to register AVIF support in Pillow/PIL system-wide
try:
    import pillow_avif
except ImportError:
    pass

from .celery import app as celery_app

__all__ = ('celery_app',)

# Standard Django pattern for registering signals in a project-level module
default_app_config = 'config.apps.Config'