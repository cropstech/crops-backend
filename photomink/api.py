from ninja import NinjaAPI
from photomink.users.api import router as users_router
from photomink.background_remover.api import router as background_remover_router
from photomink.main.api import router as main_router
from django.core.exceptions import ObjectDoesNotExist


api = NinjaAPI(
    title="PhotoMink API",
    description="API for PhotoMink services",
    version='1.0',
)

@api.exception_handler(ObjectDoesNotExist)
def handle_object_does_not_exist(request, exc):
    return api.create_response(
        request,
        {"message": "Object not found"},
        status=404,
    )
    
# api.add_router("/background-removal/", background_remover_router)
api.add_router("/", main_router)
# Mount the users router at /users
api.add_router("/", users_router)
