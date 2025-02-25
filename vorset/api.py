from ninja import NinjaAPI
from users.api import router as users_router
from main.api import router as main_router
from django.core.exceptions import ObjectDoesNotExist
from ninja.security import django_auth

api = NinjaAPI(
    title="vorset API",
    description="API for vorset services",
    version='1.0',
    csrf=True,
    auth=django_auth
)
    
api.add_router("/", main_router)
api.add_router("/users/", users_router)
