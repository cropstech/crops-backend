from ninja import NinjaAPI
from photomink.users.api import router as users_router
from photomink.background_remover.api import router as background_remover_router
api = NinjaAPI(
    title="PhotoMink API",
    description="API for PhotoMink services",
    version='1.0',
)

# Mount the users router at /users
api.add_router("/", users_router)
api.add_router("/background-removal/", background_remover_router)