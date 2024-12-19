from django.apps import AppConfig



class MainConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'main'
    label = 'main'

    def ready(self):
        from django.apps import apps
        print("Models in main app:", [m.__name__ for m in apps.get_app_config('main').get_models()])
        from . import signals  # This will connect all the signal handlers
