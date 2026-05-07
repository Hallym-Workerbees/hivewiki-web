from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import HiveUser, UserStatus
from apps.accounts.services import SESSION_USER_ID_KEY
from apps.core.models import (
    Comment,
    CommentLike,
    CommentStatus,
    Post,
    PostLike,
    PostStatus,
)
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

    def test_author_can_edit_own_post(self):
        post = Post.objects.create(
            author_user=self.user,
            content_markdown="기존 본문",
            status=PostStatus.PUBLISHED,
        )

        get_response = self.client.get(f"/community/{post.id}/edit/")
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "내 게시글 다듬기")

        post_response = self.client.post(
            f"/community/{post.id}/edit/",
            {
                "draft_id": str(post.id),
                "body_markdown": "수정된 본문",
                "tag_names": "수정, 공유",
                "status": PostStatus.PUBLISHED,
            },
        )

        self.assertRedirects(post_response, f"/community/{post.id}/")
        post.refresh_from_db()
        self.assertEqual(post.body_markdown, "수정된 본문")
        self.assertEqual(
            list(post.tags.order_by("name").values_list("name", flat=True)),
            ["공유", "수정"],
        )

    def test_author_can_edit_own_comment(self):
        post = Post.objects.create(
            author_user=self.user,
            content_markdown="댓글 수정 포스트",
            status=PostStatus.PUBLISHED,
        )
        comment = Comment.objects.create(
            post=post,
            author_user=self.user,
            content="기존 댓글",
            status=CommentStatus.PUBLISHED,
        )

        get_response = self.client.get(
            f"/community/{post.id}/comments/{comment.id}/edit/"
        )
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "수정 저장")
        self.assertContains(get_response, "기존 댓글")

        post_response = self.client.post(
            f"/community/{post.id}/comments/{comment.id}/edit/",
            {
                "content": "수정된 댓글",
                "parent_comment_id": "",
            },
        )

        self.assertRedirects(
            post_response, f"/community/{post.id}/#comment-{comment.id}"
        )
        comment.refresh_from_db()
        self.assertEqual(comment.content, "수정된 댓글")

    def test_anonymous_user_can_read_community_but_not_see_drafts_in_feed(self):
        published_post = Post.objects.create(
            author_user=self.user,
            content_markdown="공개 게시글",
            status=PostStatus.PUBLISHED,
        )
        Post.objects.create(
            author_user=self.user,
            content_markdown="임시 게시글",
            status=PostStatus.DRAFT,
        )

        self.client.session.flush()

        list_response = self.client.get("/community/")
        detail_response = self.client.get(f"/community/{published_post.id}/")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(list_response, "공개 게시글")
        self.assertNotContains(list_response, "임시 게시글")
        self.assertContains(detail_response, "로그인하고 댓글 쓰기")

    def test_user_can_toggle_post_like(self):
        post = Post.objects.create(
            author_user=self.other_user,
            content_markdown="좋아요 테스트 글",
            status=PostStatus.PUBLISHED,
        )

        like_response = self.client.post(
            f"/community/{post.id}/like/",
            {"next": f"/community/{post.id}/"},
        )
        self.assertRedirects(like_response, f"/community/{post.id}/")
        self.assertTrue(PostLike.objects.filter(post=post, user=self.user).exists())

        unlike_response = self.client.post(
            f"/community/{post.id}/like/",
            {"next": f"/community/{post.id}/"},
        )
        self.assertRedirects(unlike_response, f"/community/{post.id}/")
        self.assertFalse(PostLike.objects.filter(post=post, user=self.user).exists())

    def test_user_can_toggle_comment_like(self):
        post = Post.objects.create(
            author_user=self.other_user,
            content_markdown="댓글 좋아요 테스트 글",
            status=PostStatus.PUBLISHED,
        )
        comment = Comment.objects.create(
            post=post,
            author_user=self.other_user,
            content="좋아요 받을 댓글",
            status=CommentStatus.PUBLISHED,
        )

        like_response = self.client.post(
            f"/community/{post.id}/comments/{comment.id}/like/",
            {"next": f"/community/{post.id}/#comment-{comment.id}"},
        )
        self.assertRedirects(
            like_response, f"/community/{post.id}/#comment-{comment.id}"
        )
        self.assertTrue(
            CommentLike.objects.filter(comment=comment, user=self.user).exists()
        )
