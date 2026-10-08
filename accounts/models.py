from urllib.parse import quote

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models

from core.constants import PROVIDER_ROLES, UserRole


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('An email address is required.')
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', UserRole.ADMIN)
        extra_fields.setdefault('name', 'Administrator')
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Platform account. Signs in with email; `role` selects the dashboard."""

    username = None
    first_name = None
    last_name = None

    email = models.EmailField('email address', unique=True)
    name = models.CharField(max_length=150)
    role = models.CharField(max_length=32, choices=UserRole.choices, default=UserRole.TOURIST)
    avatar = models.CharField(max_length=500, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email_verified = models.BooleanField(default=False)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        ordering = ['email']

    def __str__(self):
        return f'{self.name or self.email} ({self.role})'

    @property
    def is_provider(self) -> bool:
        return self.role in PROVIDER_ROLES

    @property
    def is_platform_admin(self) -> bool:
        return self.role == UserRole.ADMIN or self.is_superuser

    @property
    def avatar_url(self) -> str:
        return self.avatar or f'https://api.dicebear.com/7.x/avataaars/svg?seed={quote(self.email)}'
