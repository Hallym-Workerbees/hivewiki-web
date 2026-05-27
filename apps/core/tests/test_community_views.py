from unittest.mock import Mock, patch

from botocore.exceptions import CredentialRetrievalError, NoCredentialsError
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import HiveUser, UserStatus
from apps.accounts.services import SESSION_USER_ID_KEY
from apps.core.forms import PostForm
from apps.core.models import (
    Comment,
    CommentLike,
    Post,
    PostLike,
    PostStatus,
    Tag,
    TagType,
    WikiDocument,
    WikiDocumentStatus,
    WikiGenerationType,
    WikiRevision,
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
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    },
    AWS_S3_UPLOAD_ACCESS_KEY_ID="test-access-key",
    AWS_S3_UPLOAD_SECRET_ACCESS_KEY="test-secret-key",
    AWS_S3_UPLOAD_REGION="ap-northeast-2",
    AWS_S3_UPLOAD_BUCKET="hivewiki-community-images",
    AWS_S3_UPLOAD_PUBLIC_BASE_URL="https://cdn.example.com/hivewiki-community-images",
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

    def _mock_s3_presigned_post(self):
        mock_s3_client = Mock()
        mock_s3_client.generate_presigned_post.return_value = {
            "url": "https://s3.ap-northeast-2.amazonaws.com/hivewiki-community-images",
            "fields": {
                "key": "community-images/tmp/test/image.png",
                "Content-Type": "image/png",
                "policy": "encoded-policy",
                "x-amz-signature": "signature",
            },
        }
        return mock_s3_client

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
        )
        child_comment = Comment.objects.create(
            post=post,
            author_user=self.other_user,
            parent_comment=root_comment,
            content="중첩 댓글",
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
        )
        child_comment = Comment.objects.create(
            post=post,
            author_user=self.other_user,
            parent_comment=root_comment,
            content="1차 답글",
        )
        grandchild_comment = Comment.objects.create(
            post=post,
            author_user=self.user,
            parent_comment=child_comment,
            content="2차 답글",
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

    @patch("apps.accounts.services.boto3.client")
    def test_community_image_upload_prepare_returns_presigned_payload(
        self, mock_boto3_client
    ):
        mock_s3_client = self._mock_s3_presigned_post()
        mock_boto3_client.return_value = mock_s3_client

        response = self.client.post(
            "/community/image-upload/prepare/",
            {"filename": "pasted-image.png", "content_type": "image/png"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["fields"]["Content-Type"], "image/png")
        self.assertTrue(payload["public_url"].startswith("https://cdn.example.com/"))
        mock_s3_client.generate_presigned_post.assert_called_once()
        self.assertIn(
            "community-images/tmp/",
            mock_s3_client.generate_presigned_post.call_args.kwargs["Key"],
        )

    def test_community_image_upload_prepare_rejects_non_image(self):
        response = self.client.post(
            "/community/image-upload/prepare/",
            {"filename": "notes.txt", "content_type": "text/plain"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "이미지 파일만 업로드할 수 있습니다.",
        )

    @patch("apps.accounts.services.boto3.client")
    def test_community_image_upload_prepare_returns_400_when_s3_credentials_missing(
        self, mock_boto3_client
    ):
        mock_s3_client = Mock()
        mock_s3_client.generate_presigned_post.side_effect = NoCredentialsError()
        mock_boto3_client.return_value = mock_s3_client

        response = self.client.post(
            "/community/image-upload/prepare/",
            {"filename": "pasted-image.png", "content_type": "image/png"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "S3 업로드 자격 증명을 찾지 못했습니다. Pod Identity 또는 액세스 키 설정을 확인해 주세요.",
        )

    @patch("apps.accounts.services.boto3.client")
    def test_community_image_upload_prepare_returns_400_when_container_credentials_timeout(
        self, mock_boto3_client
    ):
        mock_s3_client = Mock()
        mock_s3_client.generate_presigned_post.side_effect = CredentialRetrievalError(
            provider="container-role",
            error_msg="metadata timeout",
        )
        mock_boto3_client.return_value = mock_s3_client

        response = self.client.post(
            "/community/image-upload/prepare/",
            {"filename": "pasted-image.png", "content_type": "image/png"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "S3 업로드 자격 증명을 찾지 못했습니다. Pod Identity 또는 액세스 키 설정을 확인해 주세요.",
        )

    def test_community_feed_attaches_thumbnail_from_first_markdown_image(self):
        Post.objects.create(
            author_user=self.user,
            content_markdown=(
                "![대표 이미지](https://cdn.example.com/community-images/tmp/cover.png)\n\n"
                "이미지가 있는 게시글입니다."
            ),
            status=PostStatus.PUBLISHED,
        )

        response = self.client.get("/community/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["post_items"][0].thumbnail_url,
            "https://cdn.example.com/community-images/tmp/cover.png",
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
        self.assertContains(get_response, "게시글 작성")
        self.assertContains(get_response, "수정 저장")

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

    def test_community_list_can_filter_posts_by_referenced_wiki(self):
        referenced_document = WikiDocument.objects.create(
            title="검색 운영 가이드",
            slug="search-ops-guide",
            summary="검색 운영 문서입니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        referenced_revision = WikiRevision.objects.create(
            wiki_document=referenced_document,
            revision_number=1,
            content_markdown="## 검색 운영",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        referenced_document.current_revision = referenced_revision
        referenced_document.save(update_fields=["current_revision"])

        other_document = WikiDocument.objects.create(
            title="다른 문서",
            slug="other-doc",
            summary="다른 문서입니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        other_revision = WikiRevision.objects.create(
            wiki_document=other_document,
            revision_number=1,
            content_markdown="## 다른 문서",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        other_document.current_revision = other_revision
        other_document.save(update_fields=["current_revision"])

        matched_post = Post.objects.create(
            author_user=self.user,
            content_markdown="참조된 문서가 있는 게시글",
            status=PostStatus.PUBLISHED,
        )
        matched_post.wiki_documents.add(referenced_document)

        unmatched_post = Post.objects.create(
            author_user=self.user,
            content_markdown="다른 문서를 참조하는 게시글",
            status=PostStatus.PUBLISHED,
        )
        unmatched_post.wiki_documents.add(other_document)

        response = self.client.get("/community/?wiki_slug=search-ops-guide")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "검색 운영 가이드")
        self.assertEqual(
            [post.id for post in response.context["post_items"]],
            [matched_post.id],
        )
        self.assertContains(
            response,
            "/community/?wiki_slug=search-ops-guide",
        )

    def test_published_post_is_not_restored_as_compose_draft(self):
        post = Post.objects.create(
            author_user=self.user,
            content_markdown="이미 게시된 글",
            status=PostStatus.PUBLISHED,
        )

        response = self.client.get(
            "/community/", {"compose": "1", "draft": str(post.id)}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["active_draft_post"])
        self.assertEqual(response.context["compose_initial_payload"]["draft_id"], "")
        self.assertNotContains(response, f'value="{post.id}"', html=False)

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

    def test_community_detail_prioritizes_related_posts_over_hot_posts(self):
        tag = Tag.objects.create(name="검색", slug="search", tag_type=TagType.USER)
        shared_document = WikiDocument.objects.create(
            title="검색 구조 문서",
            slug="search-structure-doc",
            summary="검색 구조를 정리한 문서입니다.",
            status=WikiDocumentStatus.PUBLISHED,
            updated_at=timezone.now(),
        )
        shared_revision = WikiRevision.objects.create(
            wiki_document=shared_document,
            revision_number=1,
            content_markdown="## 검색 구조",
            generation_type=WikiGenerationType.AI,
            generation_model="gpt-5.5",
        )
        shared_document.current_revision = shared_revision
        shared_document.save(update_fields=["current_revision"])

        current_post = Post.objects.create(
            author_user=self.user,
            content_markdown="# 검색 개선 논의\n\n검색 결과 구조를 다듬습니다.",
            status=PostStatus.PUBLISHED,
        )
        current_post.tags.add(tag)
        current_post.wiki_documents.add(shared_document)

        related_post = Post.objects.create(
            author_user=self.other_user,
            content_markdown="# 검색 UX 제안\n\n검색 구조와 필터 동선을 정리합니다.",
            status=PostStatus.PUBLISHED,
        )
        related_post.tags.add(tag)
        related_post.wiki_documents.add(shared_document)

        hot_but_unrelated_post = Post.objects.create(
            author_user=self.other_user,
            content_markdown="# 자유 주제 토론\n\n검색과 무관한 인기 글입니다.",
            status=PostStatus.PUBLISHED,
        )
        for index in range(3):
            Comment.objects.create(
                post=hot_but_unrelated_post,
                author_user=self.user,
                content=f"인기 댓글 {index}",
            )

        response = self.client.get(f"/community/{current_post.id}/")

        self.assertEqual(response.status_code, 200)
        related_posts = response.context["related_posts"]
        self.assertGreaterEqual(len(related_posts), 2)
        self.assertEqual(related_posts[0].pk, related_post.pk)
        self.assertContains(response, "연관 게시글")

    @patch("apps.core.views.notify_post_liked")
    def test_post_like_creates_notification_on_new_like(self, mock_notify_post_liked):
        post = Post.objects.create(
            author_user=self.other_user,
            content_markdown="좋아요 대상 포스트",
            status=PostStatus.PUBLISHED,
        )

        response = self.client.post(f"/community/{post.id}/like/")

        self.assertRedirects(
            response,
            f"/community/{post.id}/",
            fetch_redirect_response=False,
        )
        mock_notify_post_liked.assert_called_once_with(actor=self.user, post=post)

    @patch("apps.core.views.notify_comment_created")
    def test_comment_create_calls_notification_hook(self, mock_notify_comment_created):
        post = Post.objects.create(
            author_user=self.other_user,
            content_markdown="댓글 대상 포스트",
            status=PostStatus.PUBLISHED,
        )

        response = self.client.post(
            f"/community/{post.id}/comments/",
            {
                "parent_comment_id": "",
                "content": "새 댓글",
            },
        )

        self.assertRedirects(
            response,
            f"/community/{post.id}/#comment-list",
            fetch_redirect_response=False,
        )
        created_comment = Comment.objects.get(post=post, content="새 댓글")
        mock_notify_comment_created.assert_called_once_with(
            actor=self.user,
            post=post,
            comment=created_comment,
            parent_comment=None,
        )

    @patch("apps.core.views.notify_comment_liked")
    def test_comment_like_creates_notification_on_new_like(
        self, mock_notify_comment_liked
    ):
        post = Post.objects.create(
            author_user=self.other_user,
            content_markdown="댓글 좋아요 대상 포스트",
            status=PostStatus.PUBLISHED,
        )
        comment = Comment.objects.create(
            post=post,
            author_user=self.other_user,
            content="좋아요 대상 댓글",
        )

        response = self.client.post(f"/community/{post.id}/comments/{comment.id}/like/")

        self.assertRedirects(
            response,
            f"/community/{post.id}/#comment-{comment.id}",
            fetch_redirect_response=False,
        )
        mock_notify_comment_liked.assert_called_once_with(
            actor=self.user,
            comment=comment,
        )

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

    def test_soft_deleted_post_is_hidden_from_feed(self):
        visible_post = Post.objects.create(
            author_user=self.user,
            content_markdown="보이는 글",
            status=PostStatus.PUBLISHED,
        )
        Post.objects.create(
            author_user=self.user,
            content_markdown="숨겨진 글",
            status=PostStatus.PUBLISHED,
            deleted_at=timezone.now(),
        )

        response = self.client.get("/community/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "보이는 글")
        self.assertNotContains(response, "숨겨진 글")
        self.assertEqual(
            list(_community_visible_posts_queryset(user=self.user)),
            [visible_post],
        )

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

    def test_soft_deleted_comment_is_excluded_from_detail_count(self):
        post = Post.objects.create(
            author_user=self.user,
            content_markdown="댓글 카운트 포스트",
            status=PostStatus.PUBLISHED,
        )
        Comment.objects.create(
            post=post,
            author_user=self.user,
            content="보이는 댓글",
        )
        Comment.objects.create(
            post=post,
            author_user=self.other_user,
            content="숨겨진 댓글",
            deleted_at=timezone.now(),
        )

        response = self.client.get(f"/community/{post.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "댓글 1개")
        self.assertContains(response, "보이는 댓글")
        self.assertNotContains(response, "숨겨진 댓글")

    def test_post_form_retries_when_tag_slug_is_taken_during_create(self):
        form = PostForm()
        real_create = Tag.objects.create
        create_call_count = 0

        def create_with_race(**kwargs):
            nonlocal create_call_count
            create_call_count += 1
            if create_call_count == 1:
                real_create(
                    name="기존 검색 태그",
                    slug=kwargs["slug"],
                    tag_type=TagType.USER,
                )
                raise IntegrityError("duplicate key value violates unique constraint")
            return real_create(**kwargs)

        with patch("apps.core.forms.Tag.objects.create", side_effect=create_with_race):
            tag = form._get_or_create_tag("검색")

        self.assertEqual(tag.name, "검색")
        self.assertEqual(tag.slug, "검색-2")
