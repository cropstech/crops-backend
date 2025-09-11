"""
Chancy worker configuration for background job processing
"""
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "crops.settings")

import django
django.setup()

from django.conf import settings
from chancy import Chancy

# Initialize Chancy with Django database
chancy_app = Chancy(settings.DATABASES["default"])

# Import the service module to make sure functions are available
# when the worker processes jobs
from main.services import s3_deletion_service
