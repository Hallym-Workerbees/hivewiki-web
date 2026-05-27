import uuid

from django.db import models

from apps.core.models import PostgresEnumField


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


class NotificationType(models.TextChoices):
    POST_LIKED = "post_liked", "Post liked"
    COMMENT_LIKED = "comment_liked", "Comment liked"
    POST_COMMENTED = "post_commented", "Post commented"
    COMMENT_REPLIED = "comment_replied", "Comment replied"


class NotificationTargetType(models.TextChoices):
    POST = "post", "Post"
    COMMENT = "comment", "Comment"


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        HiveUser,
        on_delete=models.CASCADE,
        related_name="notifications",
        db_column="user_id",
    )
    notification_type = PostgresEnumField(
        max_length=40,
        enum_type="notification_type",
        choices=NotificationType.choices,
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, null=True)
    target_type = PostgresEnumField(
        max_length=40,
        enum_type="notification_target_type",
        choices=NotificationTargetType.choices,
        blank=True,
        null=True,
    )
    target_id = models.UUIDField(blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["user", "-created_at", "-id"],
                name="notifications_user_created_idx",
            ),
            models.Index(
                fields=["user", "is_read", "-created_at"],
                name="notifications_user_unread_idx",
            ),
        ]

    def __str__(self):
        return self.title
