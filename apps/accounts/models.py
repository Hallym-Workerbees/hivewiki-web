import uuid

from django.db import models


class OAuthProvider(models.TextChoices):
    GOOGLE = "google", "Google"
    GITHUB = "github", "GitHub"


class UserRole(models.TextChoices):
    USER = "user", "User"
    ADMIN = "admin", "Admin"


class UserStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    DELETED = "deleted", "Deleted"


class HiveUser(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=16, unique=True)
    email = models.EmailField(max_length=255, unique=True)
    role = models.CharField(
        max_length=16, choices=UserRole.choices, default=UserRole.USER
    )
    password_hash = models.CharField(max_length=512, blank=True, null=True)
    status = models.CharField(
        max_length=16, choices=UserStatus.choices, default=UserStatus.ACTIVE
    )
    profile_image = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users"
        verbose_name = "Hive user"
        verbose_name_plural = "Hive users"

    def __str__(self):
        return self.username


class OAuthAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        HiveUser,
        on_delete=models.CASCADE,
        related_name="oauth_accounts",
        db_column="user_id",
    )
    provider = models.CharField(max_length=30, choices=OAuthProvider.choices)
    provider_user_id = models.CharField(max_length=255)
    provider_email = models.EmailField(max_length=255, blank=True, null=True)
    linked_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "oauth_accounts"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_user_id"],
                name="uq_oauth_accounts_provider_user",
            )
        ]

    def __str__(self):
        return f"{self.provider}:{self.provider_user_id}"
