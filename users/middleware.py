import logging
from django.utils.deprecation import MiddlewareMixin
from .utils import get_client_ip

logger = logging.getLogger(__name__)

class AuthLoggingMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.path.startswith('/api/auth/'):
            logger.info(f"Auth request to {request.path} from {get_client_ip(request)}") 