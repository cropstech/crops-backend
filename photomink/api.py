from ninja import NinjaAPI
from photomink.users.api import router as users_router
from photomink.background_remover.api import router as background_remover_router
from photomink.main.api import router as main_router
from django.core.exceptions import ObjectDoesNotExist
from ninja.security import django_auth

api = NinjaAPI(
    title="PhotoMink API",
    description="API for PhotoMink services",
    version='1.0',
    csrf=True,
    auth=django_auth
)
    
api.add_router("/", main_router)
api.add_router("/users/", users_router)
