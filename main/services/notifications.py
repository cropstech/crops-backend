from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from django.utils import timezone
from notifications.signals import notify
import re
import logging

from main.models import (
    BoardFollower, UserNotificationPreference, EventType, Comment, Board, Asset,
    CustomFieldValue, EmailBatch
)

User = get_user_model()
logger = logging.getLogger(__name__)


class NotificationService:
    """Service for managing notifications and board following"""
    
    @staticmethod
    def follow_board(user, board, include_sub_boards=True, auto_followed=False):
        """Follow a board for notifications"""
        from main.models import BoardExplicitUnfollow
        
        # If user manually follows, remove any explicit unfollow record
        if not auto_followed:
            BoardExplicitUnfollow.objects.filter(user=user, board=board).delete()
        
        follower, created = BoardFollower.objects.get_or_create(
            user=user,
            board=board,
            defaults={
                'include_sub_boards': include_sub_boards,
                'auto_followed': auto_followed
            }
        )
        if not created:
            follower.include_sub_boards = include_sub_boards
            # Only update auto_followed if it's a manual follow (clear the flag)
            if not auto_followed:
                follower.auto_followed = False
            follower.save()
        return follower
    
    @staticmethod
    def unfollow_board(user, board):
        """Unfollow a board and record explicit unfollow to prevent auto re-follow"""
        from main.models import BoardExplicitUnfollow
        
        # Delete the follow relationship
        BoardFollower.objects.filter(user=user, board=board).delete()
        
        # Record explicit unfollow to prevent auto re-follow
        BoardExplicitUnfollow.objects.get_or_create(
            user=user,
            board=board
        )
    
    @staticmethod
    def get_followed_boards(user):
        """Get all boards a user is following"""
        return BoardFollower.objects.filter(user=user).select_related('board')
    
    @staticmethod
    def is_following_board(user, board):
        """Check if user is following a specific board"""
        return BoardFollower.objects.filter(user=user, board=board).exists()
    
    @staticmethod
    def has_explicitly_unfollowed(user, board):
        """Check if user has explicitly unfollowed this board (to prevent auto re-follow)"""
        from main.models import BoardExplicitUnfollow
        return BoardExplicitUnfollow.objects.filter(user=user, board=board).exists()
    
    @staticmethod
    def get_board_followers(board, include_sub_board_followers=True):
        """Get all followers of a board"""
        followers = BoardFollower.objects.filter(board=board).select_related('user')
        
        if include_sub_board_followers and board.parent:
            # Also include followers of parent boards if include_sub_boards is True
            parent_followers = BoardFollower.objects.filter(
                board=board.parent,
                include_sub_boards=True
            ).select_related('user')
            
            # Combine both querysets
            from django.db.models import Q
            all_followers = BoardFollower.objects.filter(
                Q(board=board) | 
                Q(board=board.parent, include_sub_boards=True)
            ).select_related('user').distinct()
            
            return all_followers
        
        return followers
    
    @staticmethod
    def extract_mentions(text):
        """Extract @username mentions from text"""
        mention_pattern = r'@(\w+)'
        mentions = re.findall(mention_pattern, text)
        return mentions
    
    @staticmethod
    def get_users_from_mentions(mentions):
        """Get User objects from mention usernames"""
        # Assuming users have a username field, adjust as needed
        users = []
        for mention in mentions:
            try:
                # Try to find by username first, then by email
                user = User.objects.filter(username=mention).first()
                if not user:
                    # Try email if username doesn't exist
                    user = User.objects.filter(email__icontains=mention).first()
                if user:
                    users.append(user)
            except User.DoesNotExist:
                continue
        return users
    
    @staticmethod
    def notify_comment_on_asset(comment, asset):
        """Handle notifications when a comment is added to an asset"""
        logger.info(f"Processing notifications for comment {comment.id} on asset {asset.id}")
        
        # Get the board this asset belongs to
        board_assets = asset.boardasset_set.select_related('board')
        
        for board_asset in board_assets:
            board = board_asset.board
            logger.info(f"Checking followers for board {board.id} ({board.name})")
            
            # Get followers of this board
            followers = NotificationService.get_board_followers(board)
            logger.info(f"Found {followers.count()} followers for board {board.name}")
            
            for follower in followers:
                user = follower.user
                
                # Don't notify the comment author
                if user == comment.author:
                    logger.info(f"Skipping notification for comment author {user.email}")
                    continue
                
                # Check user's notification preferences
                pref = UserNotificationPreference.get_or_create_for_user(user)
                event_pref = pref.get_preference_for_event(EventType.COMMENT_ON_FOLLOWED_BOARD_ASSET)
                
                logger.info(f"User {user.email} preference for {EventType.COMMENT_ON_FOLLOWED_BOARD_ASSET}: {event_pref}")
                
                if event_pref.get('in_app_enabled', True):
                    logger.info(f"Sending notification to {user.email} for comment on asset {asset.id}")
                    notify.send(
                        comment.author,
                        recipient=user,
                        verb='commented on',
                        action_object=comment,
                        target=asset,
                        description=f'New comment on {getattr(asset, "name", "asset")} in {board.name}',
                        data={
                            'event_type': EventType.COMMENT_ON_FOLLOWED_BOARD_ASSET,
                            'board_id': str(board.id),
                            'asset_id': str(asset.id),
                            'comment_preview': comment.text[:100]
                        }
                    )
                    logger.info(f"Notification sent successfully to {user.email}")
                else:
                    logger.info(f"User {user.email} has in-app notifications disabled for this event type")
    
    @staticmethod
    def notify_mentions(comment, mentioned_users):
        """Handle @ mention notifications"""
        for user in mentioned_users:
            # Don't notify the comment author
            if user == comment.author:
                continue
            
            pref = UserNotificationPreference.get_or_create_for_user(user)
            event_pref = pref.get_preference_for_event(EventType.MENTION_IN_COMMENT)
            
            if event_pref.get('in_app_enabled', True):
                notify.send(
                    comment.author,
                    recipient=user,
                    verb='mentioned you in a comment',
                    action_object=comment,
                    target=comment.content_object,
                    description=f'{comment.author.email} mentioned you in a comment',
                    data={
                        'event_type': EventType.MENTION_IN_COMMENT,
                        'comment_preview': comment.text[:100]
                    }
                )
    
    @staticmethod
    def notify_thread_reply(comment):
        """Handle notifications for replies to comment threads"""
        if not comment.parent:
            return
        
        # Get all participants in this thread
        participants = comment.get_thread_participants()
        
        for user in participants:
            # Don't notify the comment author
            if user == comment.author:
                continue
            
            pref = UserNotificationPreference.get_or_create_for_user(user)
            event_pref = pref.get_preference_for_event(EventType.REPLY_TO_THREAD)
            
            if event_pref.get('in_app_enabled', True):
                notify.send(
                    comment.author,
                    recipient=user,
                    verb='replied to a thread',
                    action_object=comment,
                    target=comment.content_object,
                    description=f'New reply in a thread you participated in',
                    data={
                        'event_type': EventType.REPLY_TO_THREAD,
                        'comment_preview': comment.text[:100]
                    }
                )
    
    @staticmethod
    def notify_sub_board_created(board):
        """Handle notifications when a sub-board is created"""
        if not board.parent:
            return
        
        # Get followers of the parent board
        followers = NotificationService.get_board_followers(board.parent)
        
        for follower in followers:
            user = follower.user
            
            # Only notify if they want sub-board notifications
            if not follower.include_sub_boards:
                continue
            
            pref = UserNotificationPreference.get_or_create_for_user(user)
            event_pref = pref.get_preference_for_event(EventType.SUB_BOARD_CREATED)
            
            if event_pref.get('in_app_enabled', True):
                notify.send(
                    board.created_by,  # Assuming board has created_by field
                    recipient=user,
                    verb='created a sub-board',
                    action_object=board,
                    target=board.parent,
                    description=f'New sub-board "{board.name}" created in {board.parent.name}',
                    data={
                        'event_type': EventType.SUB_BOARD_CREATED,
                        'board_id': str(board.id),
                        'parent_board_id': str(board.parent.id)
                    }
                )
    
    @staticmethod
    def notify_asset_uploaded(asset, board):
        """Handle notifications when an asset is uploaded to a followed board"""
        # Get followers of this board
        followers = NotificationService.get_board_followers(board)
        
        for follower in followers:
            user = follower.user
            
            pref = UserNotificationPreference.get_or_create_for_user(user)
            event_pref = pref.get_preference_for_event(EventType.ASSET_UPLOADED_TO_FOLLOWED_BOARD)
            
            if event_pref.get('in_app_enabled', True):
                notify.send(
                    asset.created_by,  # Use created_by instead of uploaded_by
                    recipient=user,
                    verb='uploaded an asset',
                    action_object=asset,
                    target=board,
                    description=f'New asset "{getattr(asset, "name", "asset")}" uploaded to {board.name}',
                    data={
                        'event_type': EventType.ASSET_UPLOADED_TO_FOLLOWED_BOARD,
                        'board_id': str(board.id),
                        'asset_id': str(asset.id)
                    }
                )
    
    @staticmethod
    def notify_field_change(field_value, board=None):
        """Handle notifications when a custom field value changes"""
        # If board is not provided, try to determine it from the field value
        if not board and hasattr(field_value.content_object, 'boardasset_set'):
            # This is an asset, get its boards
            board_assets = field_value.content_object.boardasset_set.select_related('board')
            boards = [ba.board for ba in board_assets]
        elif not board and isinstance(field_value.content_object, Board):
            # This is a board
            boards = [field_value.content_object]
        else:
            boards = [board] if board else []
        
        for board in boards:
            # Get followers of this board
            followers = NotificationService.get_board_followers(board)
            
            for follower in followers:
                user = follower.user
                
                pref = UserNotificationPreference.get_or_create_for_user(user)
                event_pref = pref.get_preference_for_event(EventType.FIELD_CHANGE_IN_FOLLOWED_BOARD)
                
                if event_pref.get('in_app_enabled', True):
                    target_name = getattr(field_value.content_object, 'name', None) or \
                                 getattr(field_value.content_object, 'name', 'item')
                    
                    notify.send(
                        None,  # System notification
                        recipient=user,
                        verb='changed a field value',
                        action_object=field_value,
                        target=field_value.content_object,
                        description=f'Field "{field_value.field.title}" changed on {target_name} in {board.name}',
                        data={
                            'event_type': EventType.FIELD_CHANGE_IN_FOLLOWED_BOARD,
                            'board_id': str(board.id),
                            'field_id': field_value.field.id,
                            'field_name': field_value.field.title
                        }
                    ) 