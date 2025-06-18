from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from main.models import Board, Comment, Asset, WorkspaceMember
from main.services.notifications import NotificationService
from django.contrib.contenttypes.models import ContentType

User = get_user_model()


class Command(BaseCommand):
    help = 'Auto-follow boards for existing users based on their activity'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be followed without actually creating follows',
        )
        parser.add_argument(
            '--workspace-id',
            type=str,
            help='Only process users in a specific workspace',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        workspace_id = options.get('workspace_id')
        
        # Get users to process
        if workspace_id:
            users = User.objects.filter(
                workspacemember__workspace_id=workspace_id
            ).distinct()
            self.stdout.write(f"Processing users in workspace {workspace_id}...")
        else:
            users = User.objects.all()
            self.stdout.write(f"Processing all {users.count()} users...")
        
        total_follows = 0
        
        for user in users:
            user_follows = 0
            
            # 1. Role-based auto-follow for workspace members
            workspace_members = WorkspaceMember.objects.filter(user=user)
            if workspace_id:
                workspace_members = workspace_members.filter(workspace_id=workspace_id)
            
            for member in workspace_members:
                workspace = member.workspace
                role = member.role
                
                boards_to_follow = []
                
                if role == WorkspaceMember.Role.ADMIN:
                    # Admins follow all boards
                    boards_to_follow = list(workspace.boards.all())
                elif role in [WorkspaceMember.Role.EDITOR, WorkspaceMember.Role.COMMENTER]:
                    # Others follow root boards
                    boards_to_follow = list(workspace.boards.filter(parent=None))
                
                for board in boards_to_follow:
                    if not NotificationService.is_following_board(user, board):
                        if dry_run:
                            self.stdout.write(f"  Would follow '{board.name}' for {user.email} (role: {role})")
                            user_follows += 1
                        else:
                            NotificationService.follow_board(
                                user=user,
                                board=board,
                                include_sub_boards=(role == WorkspaceMember.Role.ADMIN)
                            )
                            self.stdout.write(f"  Followed '{board.name}' for {user.email} (role: {role})")
                            user_follows += 1
            
            # 2. Activity-based auto-follow
            
            # Follow boards where user has commented on assets
            asset_content_type = ContentType.objects.get_for_model(Asset)
            commented_asset_ids = Comment.objects.filter(
                author=user,
                content_type=asset_content_type
            ).values_list('object_id', flat=True).distinct()
            
            for asset_id in commented_asset_ids:
                try:
                    asset = Asset.objects.get(id=asset_id)
                    if workspace_id and str(asset.workspace_id) != workspace_id:
                        continue
                        
                    # Get boards containing this asset
                    board_assets = asset.boardasset_set.select_related('board')
                    for board_asset in board_assets:
                        board = board_asset.board
                        if not NotificationService.is_following_board(user, board):
                            if dry_run:
                                self.stdout.write(f"  Would follow '{board.name}' for {user.email} (commented on asset)")
                                user_follows += 1
                            else:
                                NotificationService.follow_board(
                                    user=user,
                                    board=board,
                                    include_sub_boards=False
                                )
                                self.stdout.write(f"  Followed '{board.name}' for {user.email} (commented on asset)")
                                user_follows += 1
                except Asset.DoesNotExist:
                    continue
            
            # Follow boards where user has commented directly
            board_content_type = ContentType.objects.get_for_model(Board)
            commented_board_ids = Comment.objects.filter(
                author=user,
                content_type=board_content_type
            ).values_list('object_id', flat=True).distinct()
            
            for board_id in commented_board_ids:
                try:
                    board = Board.objects.get(id=board_id)
                    if workspace_id and str(board.workspace_id) != workspace_id:
                        continue
                        
                    if not NotificationService.is_following_board(user, board):
                        if dry_run:
                            self.stdout.write(f"  Would follow '{board.name}' for {user.email} (commented on board)")
                            user_follows += 1
                        else:
                            NotificationService.follow_board(
                                user=user,
                                board=board,
                                include_sub_boards=False
                            )
                            self.stdout.write(f"  Followed '{board.name}' for {user.email} (commented on board)")
                            user_follows += 1
                except Board.DoesNotExist:
                    continue
            
            # Follow boards where user has uploaded assets
            uploaded_assets = Asset.objects.filter(created_by=user)
            if workspace_id:
                uploaded_assets = uploaded_assets.filter(workspace_id=workspace_id)
            
            for asset in uploaded_assets:
                board_assets = asset.boardasset_set.select_related('board')
                for board_asset in board_assets:
                    board = board_asset.board
                    if not NotificationService.is_following_board(user, board):
                        if dry_run:
                            self.stdout.write(f"  Would follow '{board.name}' for {user.email} (uploaded asset)")
                            user_follows += 1
                        else:
                            NotificationService.follow_board(
                                user=user,
                                board=board,
                                include_sub_boards=False
                            )
                            self.stdout.write(f"  Followed '{board.name}' for {user.email} (uploaded asset)")
                            user_follows += 1
            
            if user_follows > 0:
                total_follows += user_follows
                if dry_run:
                    self.stdout.write(f"User {user.email}: {user_follows} boards would be followed")
                else:
                    self.stdout.write(f"User {user.email}: {user_follows} boards followed")
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"DRY RUN: Would create {total_follows} board follows")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Successfully created {total_follows} board follows")
            ) 