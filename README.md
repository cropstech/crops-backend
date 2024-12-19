# Photomink

A digital asset management platform with advanced collaboration features.

## Features

- Thumbnail handling for visual assets
- Version control for assets
- Custom metadata schemas per workspace
- Asset sharing capabilities
- Comments/annotations on assets

## Setup

### Installation

1. Clone the repository
2. Create a virtual environment and activate it
3. Install dependencies: `pip install -r requirements.txt`
4. Run migrations: `python manage.py migrate`

### Environment Variables

Create a `.env` file in the root directory with:



## Paddle Integration

### Syncing Data from Paddle

The project uses `django-paddle-billing` to sync data from Paddle. To sync all data from your Paddle account to your local database run:

python manage.py sync_from_paddle

This command will sync the following data:
- Addresses
- Businesses
- Products and Prices
- Discounts
- Customers
- Subscriptions
- Transactions

### Initial Setup

1. Ensure your Paddle API credentials are set in your settings:
  
PADDLE_BILLING = {
"PADDLE_API_TOKEN": "your-api-token"
"PADDLE_CLIENT_TOKEN": "your-client-token"
"PADDLE_SECRET_KEY": "your-secret-key"
"PADDLE_API_URL": "https://sandbox-api.paddle.com" # Use api.paddle.com for production
"PADDLE_SANDBOX": True # Set to False for production
"PADDLE_ACCOUNT_MODEL": "users.User"
}

2. Run the initial sync:
  
python manage.py sync_paddle

3. Set up webhooks in your Paddle dashboard to point to:

https://your-domain.com/paddle/webhook/


## Development Roadmap

To complete the implementation:

1. Authentication & Authorization
   - Create permission decorators/middleware for checking workspace access
   - Implement email sending for invitations
   - Add password validation for protected share links

2. Content Management
   - Create serializers for different content types
   - Add rate limiting for share link access
   - Implement caching for frequently accessed shared content

3. Subscription Management
   - Handle subscription lifecycle events
   - Implement feature gating based on subscription plans
   - Add usage tracking and limits
