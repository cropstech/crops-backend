"""
Chancy worker configuration for background job processing
"""
import os
import time
import sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "crops.settings")

import django
django.setup()

from django.conf import settings
from chancy import Chancy

def create_chancy_app():
    """Create Chancy app with retry logic for database connection"""
    
    # Try to use DATABASE_URL directly if available (production setup)
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        # Use the DATABASE_URL directly - this is what production uses
        print(f"Chancy worker using DATABASE_URL: {database_url[:30]}...")
        return Chancy(database_url)
    else:
        # Fallback to Django database config for local development
        db_config = settings.DATABASES["default"]
        print(f"Chancy worker using Django config: {db_config.get('ENGINE', 'unknown engine')}")
        
        # If it's a PostgreSQL configuration, build connection string
        if db_config['ENGINE'] == 'django.db.backends.postgresql':
            host = db_config.get('HOST', 'localhost')
            port = db_config.get('PORT', 5432)
            name = db_config['NAME']
            user = db_config['USER']
            password = db_config['PASSWORD']
            
            dsn = f"postgresql://{user}:{password}@{host}:{port}/{name}"
            print(f"Built DSN: postgresql://{user}:***@{host}:{port}/{name}")
            return Chancy(dsn)
        else:
            # For SQLite or other databases
            return Chancy(db_config)

# Create Chancy app
try:
    chancy_app = create_chancy_app()
    print("✅ Chancy worker configuration loaded successfully")
except Exception as e:
    print(f"❌ Failed to initialize Chancy worker: {e}")
    print("This worker will exit and be restarted...")
    sys.exit(1)

# Import the service module to make sure functions are available
# when the worker processes jobs
from main.services import s3_deletion_service
