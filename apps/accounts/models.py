import uuid

from django.db import models


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
