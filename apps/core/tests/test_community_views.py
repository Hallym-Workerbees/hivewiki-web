from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import HiveUser, UserStatus
from apps.accounts.services import SESSION_USER_ID_KEY
from apps.core.models import Comment, CommentStatus, Post, PostStatus
from apps.core.views import _community_visible_posts_queryset


@override_settings(
    SESSION_ENGINE="django.contrib.sessions.backends.db",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "hivewiki-community-test-cache",
        }
    },
)
class CommunityViewTests(TestCase):
    def setUp(self):
        self.user = HiveUser.objects.create(
            username="community_user",
            email="community@example.com",
            status=UserStatus.ACTIVE,
        )
        self.other_user = HiveUser.objects.create(
            username="other_user",
            email="other@example.com",
            status=UserStatus.ACTIVE,
        )
        session = self.client.session
        session[SESSION_USER_ID_KEY] = str(self.user.id)
        session.save()

    def test_nested_reply_validation_error_keeps_reply_branch_visible(self):
        post = Post.objects.create(
            author_user=self.user,
            content_markdown="루트 포스트",
            status=PostStatus.PUBLISHED,
        )
        root_comment = Comment.objects.create(
            post=post,
            author_user=self.user,
            content="최상위 댓글",
            status=CommentStatus.PUBLISHED,
        )
        child_comment = Comment.objects.create(
            post=post,
            author_user=self.other_user,
            parent_comment=root_comment,
            content="중첩 댓글",
            status=CommentStatus.PUBLISHED,
        )

        response = self.client.post(
            f"/community/{post.id}/comments/",
            {
                "parent_comment_id": str(child_comment.id),
                "content": "   ",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "댓글 내용을 입력해 주세요.")
        self.assertContains(response, "최상위 댓글")
        self.assertContains(response, "중첩 댓글")
        self.assertContains(
            response,
            f'<input type="hidden" name="parent_comment_id" value="{child_comment.id}">',
            html=True,
        )

    def test_comment_children_endpoint_renders_nested_replies(self):
        post = Post.objects.create(
            author_user=self.user,
            content_markdown="댓글 확장 포스트",
            status=PostStatus.PUBLISHED,
        )
        root_comment = Comment.objects.create(
            post=post,
            author_user=self.user,
            content="루트 댓글",
            status=CommentStatus.PUBLISHED,
        )
        child_comment = Comment.objects.create(
            post=post,
            author_user=self.other_user,
            parent_comment=root_comment,
            content="1차 답글",
            status=CommentStatus.PUBLISHED,
        )
        grandchild_comment = Comment.objects.create(
            post=post,
            author_user=self.user,
            parent_comment=child_comment,
            content="2차 답글",
            status=CommentStatus.PUBLISHED,
        )

        response = self.client.get(
            f"/community/{post.id}/comments/{child_comment.id}/children/",
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2차 답글")
        self.assertContains(
            response,
            f'id="comment-children-{grandchild_comment.id}"',
        )

    def test_community_list_paginates_with_stable_ordering(self):
        created_at = timezone.now()
        created_posts = []
        for index in range(11):
            created_posts.append(
                Post.objects.create(
                    author_user=self.user,
                    content_markdown=f"피드 게시글 {index}",
                    status=PostStatus.PUBLISHED,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )

        expected_ids = list(
            _community_visible_posts_queryset(user=self.user).values_list(
                "id", flat=True
            )
        )

        first_page_response = self.client.get("/community/")
        second_page_response = self.client.get(
            "/community/?page=2",
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(first_page_response.status_code, 200)
        self.assertEqual(second_page_response.status_code, 200)

        first_page_ids = [post.id for post in first_page_response.context["post_items"]]
        second_page_ids = [
            post.id for post in second_page_response.context["post_items"]
        ]

        self.assertEqual(len(first_page_ids), 10)
        self.assertEqual(len(second_page_ids), 1)
        self.assertFalse(set(first_page_ids) & set(second_page_ids))
        self.assertEqual(first_page_ids + second_page_ids, expected_ids)
