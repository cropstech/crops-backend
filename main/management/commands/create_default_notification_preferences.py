from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from main.models import UserNotificationPreference

User = get_user_model()


class Command(BaseCommand):
    help = 'Create default notification preferences for all users'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without actually creating preferences',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        users = User.objects.all()
        total_users = users.count()
        
        self.stdout.write(f"Processing {total_users} users...")
        
        created_count = 0
        for user in users:
            if dry_run:
                # Check if user already has preferences
                has_preferences = UserNotificationPreference.objects.filter(user=user).exists()
                if not has_preferences:
                    created_count += 1
                    self.stdout.write(f"Would create notification preferences for {user.email}")
            else:
                # Actually create the preferences
                preference, created = UserNotificationPreference.objects.get_or_create(
                    user=user,
                    defaults={
                        'event_preferences': UserNotificationPreference.get_default_preferences(),
                        'email_frequency': 5
                    }
                )
                
                if created:
                    created_count += 1
                    self.stdout.write(f"Created notification preferences for {user.email}")
                else:
                    # Update existing preferences to include any new event types
                    current_prefs = preference.event_preferences
                    default_prefs = UserNotificationPreference.get_default_preferences()
                    
                    updated = False
                    for event_type, default_settings in default_prefs.items():
                        if event_type not in current_prefs:
                            current_prefs[event_type] = default_settings
                            updated = True
                    
                    if updated:
                        preference.event_preferences = current_prefs
                        preference.save()
                        self.stdout.write(f"Updated notification preferences for {user.email}")
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"DRY RUN: Would create {created_count} notification preferences")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Successfully processed {total_users} users, created/updated {created_count} notification preferences")
            ) 