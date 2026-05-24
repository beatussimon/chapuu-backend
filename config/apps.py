from django.apps import AppConfig

class Config(AppConfig):
    name = 'config'

    def ready(self):
        import config.signals
