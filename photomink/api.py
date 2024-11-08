from ninja import NinjaAPI
from photomink.users.api import router as users_router

api = NinjaAPI(
    title="PhotoMink API",
    description="API for PhotoMink services",
    version='1.0',
)

# Mount the users router at /users
api.add_router("/", users_router)