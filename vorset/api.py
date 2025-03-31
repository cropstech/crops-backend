from ninja import NinjaAPI
from users.api import router as users_router
from main.api import router as main_router
from main.webhooks import router as webhook_router
from django.core.exceptions import ObjectDoesNotExist
from ninja.security import django_auth

api = NinjaAPI(
    title="vorset API",
    description="API for vorset services",
    version='1.0',
    csrf=True,
    auth=django_auth
)

# Create a separate API instance for webhooks without CSRF protection
webhook_api = NinjaAPI(
    title="Webhook API",  # Give it a distinctive title
    description="Webhooks for external services",
    version='1.0',
    csrf=False,
    docs_url="/doc",  # Explicitly set docs URL
    urls_namespace="webhooks"
)
    
api.add_router("/", main_router)
api.add_router("/users/", users_router)
webhook_api.add_router("/", webhook_router)  # Mount at root of webhook_api
