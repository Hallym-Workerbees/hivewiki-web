from collections.abc import Iterable

from django.db import connections
from django.db.models import QuerySet
from django.db.utils import OperationalError, ProgrammingError
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Comment, Post

from .models import (
    HiveUser,
    Notification,
    NotificationTargetType,
    NotificationType,
)


def notification_table_exists(using: str = "default") -> bool:
    connection = connections[using]
    try:
        return Notification._meta.db_table in connection.introspection.table_names()
    except (OperationalError, ProgrammingError):
        return False


def get_notifications_for_user(user: HiveUser) -> QuerySet[Notification]:
    if not notification_table_exists():
        return Notification.objects.none()
    return Notification.objects.filter(user=user).order_by("-created_at", "-id")


def get_unread_notification_count(user: HiveUser | None) -> int:
    if user is None or not notification_table_exists():
        return 0
    return get_notifications_for_user(user).filter(is_read=False).count()


def create_notification(
    *,
    user: HiveUser,
    notification_type: NotificationType,
    title: str,
    body: str = "",
    target_type: NotificationTargetType | None = None,
    target_id=None,
):
    if not notification_table_exists():
        return None
    return Notification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title[:255],
        body=body or None,
        target_type=target_type,
        target_id=target_id,
    )


def mark_notification_read(notification: Notification) -> None:
    if not notification_table_exists() or notification.is_read:
        return
    notification.is_read = True
    notification.read_at = timezone.now()
    notification.save(update_fields=["is_read", "read_at"])


def mark_all_notifications_read(user: HiveUser) -> None:
    if not notification_table_exists():
        return
    get_notifications_for_user(user).filter(is_read=False).update(
        is_read=True,
        read_at=timezone.now(),
    )


def attach_notification_targets(
    notifications: Iterable[Notification],
) -> list[Notification]:
    notifications = list(notifications)
    post_ids = [
        notification.target_id
        for notification in notifications
        if notification.target_type == NotificationTargetType.POST
        and notification.target_id is not None
    ]
    comment_ids = [
        notification.target_id
        for notification in notifications
        if notification.target_type == NotificationTargetType.COMMENT
        and notification.target_id is not None
    ]
    posts_by_id = {
        post.id: post
        for post in Post.objects.filter(id__in=post_ids).only(
            "id",
            "title_cache",
            "summary_cache",
        )
    }
    comments_by_id = {
        comment.id: comment
        for comment in Comment.objects.filter(id__in=comment_ids)
        .select_related("post")
        .only(
            "id",
            "post_id",
            "post__id",
            "post__title_cache",
            "post__summary_cache",
        )
    }

    for notification in notifications:
        notification.target_url = _build_notification_target_url(
            notification,
            comments_by_id=comments_by_id,
        )
        notification.target_title = _build_notification_target_title(
            notification,
            posts_by_id=posts_by_id,
            comments_by_id=comments_by_id,
        )
    return notifications


def notify_post_liked(*, actor: HiveUser, post: Post) -> None:
    recipient = post.author_user
    if recipient is None or recipient.pk == actor.pk:
        return
    create_notification(
        user=recipient,
        notification_type=NotificationType.POST_LIKED,
        title=f"{actor.username}님이 회원님의 게시글을 좋아합니다.",
        body=post.title or post.summary,
        target_type=NotificationTargetType.POST,
        target_id=post.id,
    )


def notify_comment_liked(*, actor: HiveUser, comment: Comment) -> None:
    recipient = comment.author_user
    if recipient is None or recipient.pk == actor.pk:
        return
    create_notification(
        user=recipient,
        notification_type=NotificationType.COMMENT_LIKED,
        title=f"{actor.username}님이 회원님의 댓글을 좋아합니다.",
        body=_trim_notification_body(comment.content),
        target_type=NotificationTargetType.COMMENT,
        target_id=comment.id,
    )


def notify_comment_created(
    *,
    actor: HiveUser,
    post: Post,
    comment: Comment,
    parent_comment: Comment | None = None,
) -> None:
    recipients: list[tuple[HiveUser, NotificationType, str]] = []
    if parent_comment and parent_comment.author_user_id not in {None, actor.pk}:
        recipients.append(
            (
                parent_comment.author_user,
                NotificationType.COMMENT_REPLIED,
                f"{actor.username}님이 회원님의 댓글에 답글을 남겼습니다.",
            )
        )
    if post.author_user_id not in {None, actor.pk} and (
        parent_comment is None or post.author_user_id != parent_comment.author_user_id
    ):
        recipients.append(
            (
                post.author_user,
                NotificationType.POST_COMMENTED,
                f"{actor.username}님이 회원님의 게시글에 댓글을 남겼습니다.",
            )
        )

    for recipient, notification_type, title in recipients:
        create_notification(
            user=recipient,
            notification_type=notification_type,
            title=title,
            body=_trim_notification_body(comment.content),
            target_type=NotificationTargetType.COMMENT,
            target_id=comment.id,
        )


def _build_notification_target_url(
    notification: Notification,
    *,
    comments_by_id: dict,
) -> str:
    if notification.target_id is None:
        return ""
    if notification.target_type == NotificationTargetType.POST:
        return reverse("community_detail", kwargs={"post_id": notification.target_id})
    if notification.target_type == NotificationTargetType.COMMENT:
        comment = comments_by_id.get(notification.target_id)
        if comment is None:
            return ""
        return (
            reverse("community_detail", kwargs={"post_id": comment.post_id})
            + f"#comment-{comment.id}"
        )
    return ""


def _build_notification_target_title(
    notification: Notification,
    *,
    posts_by_id: dict,
    comments_by_id: dict,
) -> str:
    if notification.target_id is None:
        return ""
    if notification.target_type == NotificationTargetType.POST:
        post = posts_by_id.get(notification.target_id)
        if post is None:
            return ""
        return post.title or post.summary or "제목 없는 게시글"
    if notification.target_type == NotificationTargetType.COMMENT:
        comment = comments_by_id.get(notification.target_id)
        if comment is None:
            return ""
        return comment.post.title or comment.post.summary or "제목 없는 게시글"
    return ""


def _trim_notification_body(body: str, limit: int = 120) -> str:
    normalized = " ".join((body or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."
