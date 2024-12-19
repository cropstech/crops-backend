from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import BaseUserManager
from django.utils import timezone
from .fields import LowercaseEmailField
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.utils.crypto import get_random_string
from datetime import timedelta


class UserManager(BaseUserManager):

    def _create_user(self, email, password, is_staff, is_superuser, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address')
        now = timezone.now()
        email = self.normalize_email(email)
        user = self.model(
            email=email,
            is_staff=is_staff, 
            is_active=True,
            is_superuser=is_superuser, 
            last_login=now,
            date_joined=now, 
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password, **extra_fields):
        return self._create_user(email, password, False, False, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        user=self._create_user(email, password, True, True, **extra_fields)
        return user


class CustomUser(AbstractUser):
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    email = LowercaseEmailField(unique=True, blank=False, max_length=254, verbose_name="email address")
    is_active = models.BooleanField(default=True)
    is_admin = models.BooleanField(default=False)
    beta_access = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    verification_token = models.CharField(max_length=100, null=True, blank=True)
    verification_token_created = models.DateTimeField(null=True, blank=True)
    verification_email_sent_count = models.IntegerField(default=0)
    last_verification_email_sent = models.DateTimeField(null=True, blank=True)
    password_reset_token = models.CharField(max_length=100, null=True, blank=True)
    password_reset_token_created = models.DateTimeField(null=True, blank=True)
    new_email = models.EmailField(null=True, blank=True)
    new_email_token = models.CharField(max_length=100, null=True, blank=True)
    new_email_token_created = models.DateTimeField(null=True, blank=True)
    # objects = UserManager()
    EMAIL_FIELD = "email"
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()


    def __str__(self):
        return self.first_name + " " + self.last_name
    
    class Meta:
        ordering = ('-date_joined', )

    @classmethod
    def is_valid_email(cls, email):
        try:
            validate_email(email)
            return True
        except ValidationError:
            return False

    def generate_verification_token(self):
        self.verification_token = get_random_string(64)
        self.verification_token_created = timezone.now()
        self.save()
        return self.verification_token

    def can_send_verification_email(self):
        """Check if user can send another verification email"""
        max_emails = 5
        cooldown_hours = 24
        
        # If no previous emails sent, allow it
        if not self.last_verification_email_sent:
            return True

        time_since_last = timezone.now() - self.last_verification_email_sent
        hours_since_last = time_since_last.total_seconds() / 3600

        # If 24 hours have passed, reset counter and allow
        if hours_since_last >= cooldown_hours:
            self.verification_email_sent_count = 0
            self.save()
            return True

        # If within 24 hours, check if under max limit
        if self.verification_email_sent_count and self.verification_email_sent_count >= max_emails:
            return False

        return True

    def is_verification_token_valid(self):
        if not self.verification_token or not self.verification_token_created:
            return False
        
        # Token expires after 24 hours
        return (timezone.now() - self.verification_token_created) < timedelta(hours=24)

    def generate_token(self, token_type='verification'):
        token = get_random_string(64)
        if token_type == 'password_reset':
            self.password_reset_token = token
            self.password_reset_token_created = timezone.now()
        elif token_type == 'email_change':
            self.new_email_token = token
            self.new_email_token_created = timezone.now()
        self.save()
        return token