# Vorset

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


## Notification System

The platform includes a comprehensive notification system that allows users to receive notifications for various events like comments, mentions, and board activity.

### Notification Preferences

Each user has a single notification preference record that contains settings for all event types. The system supports:

- **In-app notifications** - Displayed within the application
- **Email notifications** - Sent via email with configurable batching
- **Event types**:
  - New comments on assets in followed boards
  - @ mentions in comments
  - Replies to threads you've started or participated in
  - New sub-boards created in followed boards
  - New items uploaded to followed boards
  - Custom field changes in followed boards

### Management Commands

#### Create Default Notification Preferences

To ensure all users have notification preferences set up (required for notifications to work):

```bash
# Preview what would be created/updated
python manage.py create_default_notification_preferences --dry-run

# Actually create/update notification preferences for all users
python manage.py create_default_notification_preferences
```

**When to run this command:**
- After adding new users to ensure they have notification preferences
- During initial setup to create preferences for existing users
- After adding new event types to the system
- As part of deployment process when notification system changes are made

The command will:
- Create notification preferences for users who don't have any
- Update existing preferences to include any new event types with default settings
- Preserve existing user customizations while adding missing event types

#### Smart Auto-Follow System

The notification system includes a smart auto-follow feature that automatically follows boards based on user activity and role. This ensures users receive relevant notifications without having to manually follow every board they interact with.

**How Auto-Follow Works:**

*Role-Based Auto-Follow* (applies when users join workspaces):
- **Admins**: Automatically follow all boards in the workspace (including sub-boards)
- **Editors/Commenters**: Automatically follow root/main boards only

*Activity-Based Auto-Follow* (applies during user interactions):
- **Comment on Assets**: Auto-follow boards containing commented assets
- **Comment on Boards**: Auto-follow the board being commented on
- **Upload Assets**: Auto-follow boards where assets are uploaded
- **Upload Folders**: Auto-follow boards created during folder upload

**Explicit Unfollow Protection:**

The system respects user choices when they explicitly unfollow boards:
- **Manual Unfollow**: When users manually unfollow a board, the system records this as an "explicit unfollow"
- **Auto-Follow Prevention**: Auto-follow will not re-follow boards that users have explicitly unfollowed
- **Manual Re-Follow**: Users can manually follow the board again, which clears the explicit unfollow record
- **Clean Data**: Only active follows are stored in the main table; explicit unfollows are tracked separately

#### Auto-Follow Based on Activity Management Command

To retroactively apply smart auto-follow for existing users based on their past activity:

```bash
# Preview what boards would be followed for all users
python manage.py auto_follow_based_on_activity --dry-run

# Apply auto-follow for all users based on their activity
python manage.py auto_follow_based_on_activity

# Process only users in a specific workspace
python manage.py auto_follow_based_on_activity --workspace-id WORKSPACE_UUID

# Preview for specific workspace
python manage.py auto_follow_based_on_activity --workspace-id WORKSPACE_UUID --dry-run
```

**When to run this command:**
- During initial setup after implementing the notification system
- When onboarding existing workspaces that have historical activity
- After importing data from legacy systems
- When you want to retroactively apply auto-follow logic to existing users

The command will analyze user activity and automatically follow boards where users have:
- Commented on assets or boards
- Uploaded assets to boards
- Been assigned workspace roles (admins follow all boards, others follow root boards)

**Important**: This command respects explicit unfollows - it won't re-follow boards that users have manually unfollowed.

### API Endpoints

- `GET /notification-preferences` - Get user's notification preferences
- `PUT /notification-preferences` - Update user's notification preferences
- `GET /notifications` - Get user's notifications
- `POST /notifications/{id}/mark-read` - Mark notification as read
- `POST /notifications/mark-all-read` - Mark all notifications as read
- `POST /workspaces/{workspace_id}/boards/{board_id}/follow` - Follow a board
- `DELETE /workspaces/{workspace_id}/boards/{board_id}/follow` - Unfollow a board
- `GET /workspaces/{workspace_id}/followed-boards` - Get user's followed boards

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
