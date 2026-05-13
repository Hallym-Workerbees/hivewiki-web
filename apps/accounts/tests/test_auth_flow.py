from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import HiveUser, OAuthAccount, OAuthProvider, UserStatus
from apps.accounts.services import (
    SESSION_USER_ID_KEY,
    TIMEZONE_SESSION_KEY,
    read_pending_oauth_confirmation,
)
from apps.core.models import (
    Comment,
    CommentLike,
    Post,
    PostBookmark,
    PostLike,
    PostStatus,
)


@override_settings(
    SESSION_ENGINE="django.contrib.sessions.backends.db",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "hivewiki-test-cache",
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
    GOOGLE_OAUTH_CLIENT_ID="google-client-id",
    GOOGLE_OAUTH_CLIENT_SECRET="google-client-secret",
    GITHUB_OAUTH_CLIENT_ID="github-client-id",
    GITHUB_OAUTH_CLIENT_SECRET="github-client-secret",
    AWS_S3_UPLOAD_ACCESS_KEY_ID="test-access-key",
    AWS_S3_UPLOAD_SECRET_ACCESS_KEY="test-secret-key",
    AWS_S3_UPLOAD_REGION="ap-northeast-2",
    AWS_S3_UPLOAD_BUCKET="hivewiki-profile-images",
    AWS_S3_UPLOAD_PUBLIC_BASE_URL="https://cdn.example.com/hivewiki-profile-images",
)
class AuthFlowTests(TestCase):
    SIGNUP_PASSWORD = "".join(["Strong", "Pass", "123"])
    LOGIN_PASSWORD = "".join(["test", "pass", "123!"])
    OLD_PASSWORD = "".join(["old", "pass", "123!"])
    NEW_PASSWORD = "".join(["new", "pass", "123!"])
    RIGHT_PASSWORD = "".join(["right", "pass", "123!"])

    def setUp(self):
        cache.clear()

    def _mock_s3_presigned_post(self):
        mock_s3_client = Mock()
        mock_s3_client.generate_presigned_post.return_value = {
            "url": "https://s3.ap-northeast-2.amazonaws.com/hivewiki-profile-images",
            "fields": {
                "key": "profiles/test/avatar.png",
                "Content-Type": "image/png",
                "policy": "encoded-policy",
                "x-amz-signature": "signature",
            },
        }
        return mock_s3_client

    def _login(self, user):
        session = self.client.session
        session[SESSION_USER_ID_KEY] = str(user.id)
        session.save()

    def _set_timezone(self, timezone_name: str):
        session = self.client.session
        session[TIMEZONE_SESSION_KEY] = timezone_name
        session.save()

    def test_signup_creates_user_and_logs_in(self):
        response = self.client.post(
            "/auth/signup/",
            {
                "username": "hive_user",
                "email": "member@example.com",
                "password": self.SIGNUP_PASSWORD,
                "password_confirm": self.SIGNUP_PASSWORD,
            },
        )

        self.assertRedirects(response, "/dashboard/")
        user = HiveUser.objects.get(email="member@example.com")
        self.assertEqual(user.username, "hive_user")
        self.assertEqual(user.status, UserStatus.ACTIVE)
        self.assertTrue(check_password(self.SIGNUP_PASSWORD, user.password_hash))
        self.assertEqual(self.client.session[SESSION_USER_ID_KEY], str(user.id))

    def test_login_succeeds_with_existing_user(self):
        user = HiveUser.objects.create(
            username="existing_user",
            email="existing@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )

        response = self.client.post(
            "/auth/login/",
            {
                "email": "existing@example.com",
                "password": self.LOGIN_PASSWORD,
            },
        )

        self.assertRedirects(response, "/dashboard/")
        self.assertEqual(self.client.session[SESSION_USER_ID_KEY], str(user.id))

    def test_login_rejects_invalid_password(self):
        HiveUser.objects.create(
            username="existing_user",
            email="existing@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )

        response = self.client.post(
            "/auth/login/",
            {
                "email": "existing@example.com",
                "password": "wrong-password",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "이메일 또는 비밀번호가 올바르지 않습니다.")
        self.assertNotIn(SESSION_USER_ID_KEY, self.client.session)

    def test_login_rejects_suspended_user_with_admin_contact_message(self):
        HiveUser.objects.create(
            username="suspended_user",
            email="suspended@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.SUSPENDED,
        )

        response = self.client.post(
            "/auth/login/",
            {
                "email": "suspended@example.com",
                "password": self.LOGIN_PASSWORD,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "이 계정은 비활성화되어 로그인할 수 없습니다. 관리자에게 문의해 주세요.",
        )
        self.assertNotIn(SESSION_USER_ID_KEY, self.client.session)

    def test_protected_page_redirects_to_login_with_next_parameter(self):
        response = self.client.get("/dashboard/")

        self.assertRedirects(response, "/auth/login/?next=%2Fdashboard%2F")

    def test_login_honors_safe_next_parameter(self):
        user = HiveUser.objects.create(
            username="existing_user",
            email="existing@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )

        response = self.client.post(
            "/auth/login/?next=/community/",
            {
                "email": "existing@example.com",
                "password": self.LOGIN_PASSWORD,
                "next": "/community/",
            },
        )

        self.assertRedirects(response, "/community/")
        self.assertEqual(self.client.session[SESSION_USER_ID_KEY], str(user.id))

    def test_mypage_shows_current_user_profile(self):
        user = HiveUser.objects.create(
            username="profile_user",
            email="profile@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
            profile_image="https://example.com/avatar.png",
        )
        post = Post.objects.create(
            author_user=user,
            content_markdown="# 첫 글\n\n프로필 테스트용 글입니다.",
        )
        Comment.objects.create(
            post=post,
            author_user=user,
            content="첫 댓글",
        )
        PostLike.objects.create(post=post, user=user)
        self._login(user)

        response = self.client.get("/me/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "profile_user")
        self.assertContains(response, "profile@example.com")
        self.assertContains(response, "https://example.com/avatar.png")
        self.assertContains(response, "작성 글")
        self.assertContains(response, "작성 댓글")
        self.assertContains(response, "받은 좋아요")
        self.assertContains(response, "첫 글")
        self.assertContains(response, "비밀번호 변경")
        self.assertContains(response, "Google 연결")

    def test_mypage_liked_comments_page_links_to_comment_anchor(self):
        user = HiveUser.objects.create(
            username="liked_c_user",
            email="liked-comment@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        post = Post.objects.create(
            author_user=user,
            content_markdown="# 댓글 대상 글\n\n본문입니다.",
        )
        comment = Comment.objects.create(
            post=post,
            author_user=user,
            content="좋아요한 댓글입니다.",
        )
        CommentLike.objects.create(comment=comment, user=user)
        self._login(user)

        response = self.client.get("/me/likes/comments/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f"{post.get_absolute_url()}?comment={comment.id}#comment-{comment.id}",
        )

    def test_mypage_authored_posts_page_paginates(self):
        user = HiveUser.objects.create(
            username="paginated_user",
            email="paginated@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        for index in range(21):
            Post.objects.create(
                author_user=user,
                content_markdown=f"# 글 {index}\n\n본문 {index}",
            )
        self._login(user)

        first_page = self.client.get("/me/posts/")
        second_page = self.client.get("/me/posts/?page=2")

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(second_page.status_code, 200)
        self.assertContains(first_page, "1 / 2")
        self.assertContains(second_page, "2 / 2")

    def test_mypage_hides_liked_posts_that_are_not_community_visible(self):
        user = HiveUser.objects.create(
            username="liked_vis_user",
            email="liked-visibility@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        author = HiveUser.objects.create(
            username="other_author",
            email="other-author@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        published_post = Post.objects.create(
            author_user=author,
            content_markdown="# 공개 글\n\n보이는 글입니다.",
        )
        hidden_draft_post = Post.objects.create(
            author_user=author,
            content_markdown="# 숨김 초안\n\n보이면 안 됩니다.",
            status=PostStatus.DRAFT,
        )
        PostLike.objects.create(post=hidden_draft_post, user=user)
        PostLike.objects.create(post=published_post, user=user)
        self._login(user)

        response = self.client.get("/me/likes/posts/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "공개 글")
        self.assertNotContains(response, "숨김 초안")

    def test_mypage_preview_orders_liked_and_bookmarked_posts_by_action_time(self):
        user = HiveUser.objects.create(
            username="action_order",
            email="action-order@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        author = HiveUser.objects.create(
            username="feed_author",
            email="feed-author@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        older_post = Post.objects.create(
            author_user=author,
            content_markdown="# 먼저 쓴 글\n\n오래된 게시글입니다.",
        )
        newer_post = Post.objects.create(
            author_user=author,
            content_markdown="# 나중에 쓴 글\n\n새 게시글입니다.",
        )
        earlier_like = PostLike.objects.create(post=newer_post, user=user)
        later_like = PostLike.objects.create(post=older_post, user=user)
        earlier_bookmark = PostBookmark.objects.create(post=newer_post, user=user)
        later_bookmark = PostBookmark.objects.create(post=older_post, user=user)
        current_time = timezone.now()
        PostLike.objects.filter(pk=earlier_like.pk).update(
            created_at=current_time - timedelta(minutes=2)
        )
        PostLike.objects.filter(pk=later_like.pk).update(
            created_at=current_time - timedelta(minutes=1)
        )
        PostBookmark.objects.filter(pk=earlier_bookmark.pk).update(
            created_at=current_time - timedelta(minutes=2)
        )
        PostBookmark.objects.filter(pk=later_bookmark.pk).update(
            created_at=current_time - timedelta(minutes=1)
        )
        self._login(user)

        response = self.client.get("/me/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertLess(content.find("먼저 쓴 글"), content.find("나중에 쓴 글"))

    def test_profile_edit_updates_current_user(self):
        user = HiveUser.objects.create(
            username="profile_user",
            email="profile@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        self._login(user)

        response = self.client.post(
            "/me/profile/",
            {
                "username": "renamed_user",
                "email": "renamed@example.com",
                "profile_image": "https://example.com/updated.png",
            },
        )

        self.assertRedirects(response, "/me/")
        user.refresh_from_db()
        self.assertEqual(user.username, "renamed_user")
        self.assertEqual(user.email, "renamed@example.com")
        self.assertEqual(user.profile_image, "https://example.com/updated.png")

    @patch("apps.accounts.services.boto3.client")
    def test_profile_image_upload_prepare_returns_presigned_payload(
        self, mock_boto3_client
    ):
        user = HiveUser.objects.create(
            username="upload_user",
            email="upload@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        self._login(user)
        mock_s3_client = self._mock_s3_presigned_post()
        mock_boto3_client.return_value = mock_s3_client

        response = self.client.post(
            "/me/profile/image-upload/prepare/",
            {"filename": "avatar.png"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("upload_url", payload)
        self.assertIn("fields", payload)
        self.assertEqual(payload["fields"]["Content-Type"], "image/png")
        self.assertTrue(payload["public_url"].startswith("https://cdn.example.com/"))
        mock_boto3_client.assert_called_once_with(
            "s3",
            region_name="ap-northeast-2",
            aws_access_key_id="test-access-key",
            aws_secret_access_key="test-secret-key",
        )
        mock_s3_client.generate_presigned_post.assert_called_once()

    def test_profile_image_upload_prepare_rejects_non_image(self):
        user = HiveUser.objects.create(
            username="upload_user",
            email="upload@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        self._login(user)

        response = self.client.post(
            "/me/profile/image-upload/prepare/",
            {"filename": "notes.txt"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "이미지 파일만 업로드할 수 있습니다.",
        )

    def test_password_change_updates_hash_and_allows_new_login(self):
        user = HiveUser.objects.create(
            username="password_user",
            email="password@example.com",
            password_hash=make_password(self.OLD_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        self._login(user)

        response = self.client.post(
            "/me/password/",
            {
                "current_password": self.OLD_PASSWORD,
                "new_password": self.NEW_PASSWORD,
                "new_password_confirm": self.NEW_PASSWORD,
            },
        )

        self.assertRedirects(response, "/me/")
        user.refresh_from_db()
        self.assertTrue(check_password(self.NEW_PASSWORD, user.password_hash))

        self.client.post("/auth/logout/")
        login_response = self.client.post(
            "/auth/login/",
            {
                "email": "password@example.com",
                "password": self.NEW_PASSWORD,
            },
        )
        self.assertRedirects(login_response, "/dashboard/")

    def test_password_change_rejects_wrong_current_password(self):
        user = HiveUser.objects.create(
            username="password_user",
            email="password@example.com",
            password_hash=make_password(self.OLD_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        self._login(user)

        response = self.client.post(
            "/me/password/",
            {
                "current_password": "wrongpass123!",
                "new_password": self.NEW_PASSWORD,
                "new_password_confirm": self.NEW_PASSWORD,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "현재 비밀번호가 올바르지 않습니다.")

    def test_password_login_still_works_after_oauth_is_connected(self):
        user = HiveUser.objects.create(
            username="oauth_locked",
            email="oauthlocked@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        OAuthAccount.objects.create(
            user=user,
            provider=OAuthProvider.GOOGLE,
            provider_user_id="google-user-locked",
            provider_email="oauthlocked@example.com",
        )

        response = self.client.post(
            "/auth/login/",
            {
                "email": "oauthlocked@example.com",
                "password": self.LOGIN_PASSWORD,
            },
        )

        self.assertRedirects(response, "/dashboard/")
        self.assertEqual(self.client.session[SESSION_USER_ID_KEY], str(user.id))

    def test_password_login_is_blocked_for_oauth_only_account(self):
        HiveUser.objects.create(
            username="oauth_only",
            email="oauthonly@example.com",
            password_hash=None,
            status=UserStatus.ACTIVE,
        )
        OAuthAccount.objects.create(
            user=HiveUser.objects.get(email="oauthonly@example.com"),
            provider=OAuthProvider.GOOGLE,
            provider_user_id="google-user-oauth-only",
            provider_email="oauthonly@example.com",
        )

        response = self.client.post(
            "/auth/login/",
            {
                "email": "oauthonly@example.com",
                "password": self.LOGIN_PASSWORD,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "이 계정은 OAuth 로그인만 사용할 수 있습니다.")
        self.assertNotIn(SESSION_USER_ID_KEY, self.client.session)

    def test_password_change_redirects_when_oauth_is_connected(self):
        user = HiveUser.objects.create(
            username="oauth_only_user",
            email="oauthonly@example.com",
            password_hash=None,
            status=UserStatus.ACTIVE,
        )
        OAuthAccount.objects.create(
            user=user,
            provider=OAuthProvider.GITHUB,
            provider_user_id="github-oauth-only",
            provider_email="oauthonly@example.com",
        )
        self._login(user)

        response = self.client.get("/me/password/")

        self.assertRedirects(response, "/me/")

    def test_mypage_keeps_password_change_when_password_is_still_set(self):
        user = HiveUser.objects.create(
            username="linked_user",
            email="linked@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        OAuthAccount.objects.create(
            user=user,
            provider=OAuthProvider.GITHUB,
            provider_user_id="github-linked-user",
            provider_email="linked@example.com",
        )
        self._login(user)

        response = self.client.get("/me/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "현재는 이메일/비밀번호 로그인과 OAuth 로그인을 함께 사용할 수 있습니다.",
        )
        self.assertContains(response, 'href="/me/password/"')

    def test_logout_requires_post(self):
        response = self.client.get("/auth/logout/")

        self.assertEqual(response.status_code, 405)

    def test_set_timezone_stores_browser_timezone_in_session(self):
        response = self.client.post(
            "/auth/timezone/",
            {
                "timezone": "America/Los_Angeles",
            },
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            self.client.session[TIMEZONE_SESSION_KEY],
            "America/Los_Angeles",
        )

    def test_set_timezone_rejects_invalid_timezone(self):
        response = self.client.post(
            "/auth/timezone/",
            {
                "timezone": "Not/A_Real_Timezone",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(TIMEZONE_SESSION_KEY, self.client.session)

    def test_current_timezone_is_reflected_in_rendered_page(self):
        self._set_timezone("America/Los_Angeles")

        response = self.client.get("/")

        self.assertContains(response, 'data-current-timezone="America/Los_Angeles"')

    def test_login_preserves_browser_timezone_in_session(self):
        self._set_timezone("America/Los_Angeles")
        HiveUser.objects.create(
            username="timezone_user",
            email="timezone@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )

        response = self.client.post(
            "/auth/login/",
            {
                "email": "timezone@example.com",
                "password": self.LOGIN_PASSWORD,
            },
        )

        self.assertRedirects(response, "/dashboard/")
        self.assertEqual(
            self.client.session[TIMEZONE_SESSION_KEY],
            "America/Los_Angeles",
        )

    @override_settings(
        LOGIN_RATE_LIMIT_ATTEMPTS=2,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS=600,
    )
    def test_login_rate_limit_blocks_repeated_failed_attempts(self):
        HiveUser.objects.create(
            username="limited_user",
            email="limited@example.com",
            password_hash=make_password(self.RIGHT_PASSWORD),
            status=UserStatus.ACTIVE,
        )

        first_response = self.client.post(
            "/auth/login/",
            {
                "email": "limited@example.com",
                "password": "wrongpass-1",
            },
            REMOTE_ADDR="127.0.0.1",
        )
        second_response = self.client.post(
            "/auth/login/",
            {
                "email": "limited@example.com",
                "password": "wrongpass-2",
            },
            REMOTE_ADDR="127.0.0.1",
        )
        blocked_response = self.client.post(
            "/auth/login/",
            {
                "email": "limited@example.com",
                "password": self.RIGHT_PASSWORD,
            },
            REMOTE_ADDR="127.0.0.1",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(blocked_response.status_code, 200)
        self.assertContains(
            blocked_response,
            "로그인 시도가 너무 많습니다. 약 10분 후 다시 시도해 주세요.",
        )

    def test_login_page_renders_oauth_buttons_when_configured(self):
        response = self.client.get("/auth/login/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Google로 계속하기")
        self.assertContains(response, "GitHub로 계속하기")

    @patch("apps.accounts.views.exchange_oauth_code_for_profile")
    def test_google_oauth_callback_creates_user_and_logs_in(self, mock_exchange):
        session = self.client.session
        session["oauth_state"] = {
            "provider": OAuthProvider.GOOGLE,
            "state": "test-state",
            "next_url": "",
        }
        session.save()
        mock_exchange.return_value = (
            {
                "provider_user_id": "google-user-123",
                "email": "oauth@example.com",
                "provider_email": "oauth@example.com",
                "profile_image": "https://example.com/google-avatar.png",
                "username_hint": "oauthuser",
            },
            {
                "provider": OAuthProvider.GOOGLE,
                "state": "test-state",
                "next_url": "",
                "action": "login",
                "link_user_id": "",
            },
        )

        response = self.client.get(
            "/auth/oauth/google/callback/",
            {"code": "auth-code", "state": "test-state"},
        )

        self.assertRedirects(response, "/dashboard/")
        user = HiveUser.objects.get(email="oauth@example.com")
        oauth_account = OAuthAccount.objects.get(
            provider=OAuthProvider.GOOGLE,
            provider_user_id="google-user-123",
        )
        self.assertEqual(oauth_account.user_id, user.id)
        self.assertEqual(user.profile_image, "https://example.com/google-avatar.png")
        self.assertEqual(self.client.session[SESSION_USER_ID_KEY], str(user.id))
        messages = list(response.wsgi_request._messages)
        self.assertTrue(
            any("소셜 로그인이 완료되었습니다." in str(message) for message in messages)
        )
        self.assertFalse(
            any(
                "보안을 위해 비밀번호 기반 로그인은 중지합니다." in str(message)
                for message in messages
            )
        )

    @patch("apps.accounts.views.exchange_oauth_code_for_profile")
    def test_oauth_callback_rejects_suspended_user_with_admin_contact_message(
        self, mock_exchange
    ):
        user = HiveUser.objects.create(
            username="oauth_suspended",
            email="oauth-suspended@example.com",
            password_hash=None,
            status=UserStatus.SUSPENDED,
        )
        OAuthAccount.objects.create(
            user=user,
            provider=OAuthProvider.GOOGLE,
            provider_user_id="google-suspended-123",
            provider_email="oauth-suspended@example.com",
        )
        session = self.client.session
        session["oauth_state"] = {
            "provider": OAuthProvider.GOOGLE,
            "state": "test-state",
            "next_url": "",
        }
        session.save()
        mock_exchange.return_value = (
            {
                "provider_user_id": "google-suspended-123",
                "email": "oauth-suspended@example.com",
                "provider_email": "oauth-suspended@example.com",
                "username_hint": "oauthsuspended",
            },
            {
                "provider": OAuthProvider.GOOGLE,
                "state": "test-state",
                "next_url": "",
                "action": "login",
                "link_user_id": "",
            },
        )

        response = self.client.get(
            "/auth/oauth/google/callback/",
            {"code": "auth-code", "state": "test-state"},
            follow=True,
        )

        self.assertRedirects(response, "/auth/login/")
        self.assertContains(
            response,
            "이 계정은 비활성화되어 로그인할 수 없습니다. 관리자에게 문의해 주세요.",
        )
        self.assertNotIn(SESSION_USER_ID_KEY, self.client.session)

    @patch("apps.accounts.views.exchange_oauth_code_for_profile")
    def test_github_oauth_callback_requires_confirmation_for_existing_user(
        self, mock_exchange
    ):
        user = HiveUser.objects.create(
            username="existing_user",
            email="existing@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        session = self.client.session
        session["oauth_state"] = {
            "provider": OAuthProvider.GITHUB,
            "state": "test-state",
            "next_url": "/me/",
        }
        session.save()
        mock_exchange.return_value = (
            {
                "provider_user_id": "github-user-456",
                "email": "existing@example.com",
                "provider_email": "existing@example.com",
                "profile_image": "https://example.com/github-avatar.png",
                "username_hint": "octocat",
            },
            {
                "provider": OAuthProvider.GITHUB,
                "state": "test-state",
                "next_url": "/me/",
                "action": "login",
                "link_user_id": "",
            },
        )

        response = self.client.get(
            "/auth/oauth/github/callback/",
            {"code": "auth-code", "state": "test-state"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "기존 계정에 연결할까요?")
        self.assertContains(response, "existing@example.com")
        self.assertFalse(
            OAuthAccount.objects.filter(
                provider=OAuthProvider.GITHUB,
                provider_user_id="github-user-456",
            ).exists()
        )
        pending_confirmation = read_pending_oauth_confirmation(
            self.client.session["pending_oauth_confirm"]
        )
        self.assertEqual(pending_confirmation["user_id"], str(user.id))

    @patch("apps.accounts.views.exchange_oauth_code_for_profile")
    def test_confirm_existing_oauth_link_logs_in_and_preserves_password(
        self, mock_exchange
    ):
        user = HiveUser.objects.create(
            username="existing_user",
            email="existing@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        session = self.client.session
        session["oauth_state"] = {
            "provider": OAuthProvider.GITHUB,
            "state": "test-state",
            "next_url": "/me/",
        }
        session.save()
        mock_exchange.return_value = (
            {
                "provider_user_id": "github-user-456",
                "email": "existing@example.com",
                "provider_email": "existing@example.com",
                "profile_image": "https://example.com/github-avatar.png",
                "username_hint": "octocat",
            },
            {
                "provider": OAuthProvider.GITHUB,
                "state": "test-state",
                "next_url": "/me/",
                "action": "login",
                "link_user_id": "",
            },
        )

        callback_response = self.client.get(
            "/auth/oauth/github/callback/",
            {"code": "auth-code", "state": "test-state"},
        )

        self.assertEqual(callback_response.status_code, 200)

        confirm_response = self.client.post(
            "/auth/oauth/confirm-existing/",
            {"decision": "confirm"},
        )

        self.assertRedirects(confirm_response, "/me/")
        oauth_account = OAuthAccount.objects.get(
            provider=OAuthProvider.GITHUB,
            provider_user_id="github-user-456",
        )
        self.assertEqual(oauth_account.user_id, user.id)
        user.refresh_from_db()
        self.assertTrue(check_password(self.LOGIN_PASSWORD, user.password_hash))
        self.assertEqual(user.profile_image, "https://example.com/github-avatar.png")
        self.assertEqual(self.client.session[SESSION_USER_ID_KEY], str(user.id))
        self.assertNotIn("pending_oauth_confirm", self.client.session)
        messages = list(confirm_response.wsgi_request._messages)
        self.assertTrue(
            any("소셜 로그인이 완료되었습니다." in str(message) for message in messages)
        )

    @patch("apps.accounts.views.exchange_oauth_code_for_profile")
    def test_cancel_existing_oauth_link_preserves_next_url(self, mock_exchange):
        HiveUser.objects.create(
            username="existing_user",
            email="existing@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        session = self.client.session
        session["oauth_state"] = {
            "provider": OAuthProvider.GITHUB,
            "state": "test-state",
            "next_url": "/community/",
        }
        session.save()
        mock_exchange.return_value = (
            {
                "provider_user_id": "github-user-456",
                "email": "existing@example.com",
                "provider_email": "existing@example.com",
                "username_hint": "octocat",
            },
            {
                "provider": OAuthProvider.GITHUB,
                "state": "test-state",
                "next_url": "/community/",
                "action": "login",
                "link_user_id": "",
            },
        )

        callback_response = self.client.get(
            "/auth/oauth/github/callback/",
            {"code": "auth-code", "state": "test-state"},
        )

        self.assertEqual(callback_response.status_code, 200)

        cancel_response = self.client.post(
            "/auth/oauth/confirm-existing/",
            {"decision": "cancel"},
        )

        self.assertRedirects(cancel_response, "/auth/login/?next=%2Fcommunity%2F")
        self.assertFalse(
            OAuthAccount.objects.filter(
                provider=OAuthProvider.GITHUB,
                provider_user_id="github-user-456",
            ).exists()
        )
        self.assertNotIn("pending_oauth_confirm", self.client.session)

    @patch("apps.accounts.views.exchange_oauth_code_for_profile")
    def test_oauth_link_callback_links_current_user_and_preserves_password(
        self, mock_exchange
    ):
        user = HiveUser.objects.create(
            username="link_target",
            email="link@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        self._login(user)
        session = self.client.session
        session["oauth_state"] = {
            "provider": OAuthProvider.GOOGLE,
            "state": "link-state",
            "next_url": "/me/",
            "action": "link",
            "link_user_id": str(user.id),
        }
        session.save()
        mock_exchange.return_value = (
            {
                "provider_user_id": "google-link-123",
                "email": "link@example.com",
                "provider_email": "link@example.com",
                "profile_image": "https://example.com/google-link-avatar.png",
                "username_hint": "linkuser",
            },
            {
                "provider": OAuthProvider.GOOGLE,
                "state": "link-state",
                "next_url": "/me/",
                "action": "link",
                "link_user_id": str(user.id),
            },
        )

        response = self.client.get(
            "/auth/oauth/google/callback/",
            {"code": "auth-code", "state": "link-state"},
        )

        self.assertRedirects(response, "/me/")
        user.refresh_from_db()
        self.assertTrue(check_password(self.LOGIN_PASSWORD, user.password_hash))
        self.assertEqual(
            user.profile_image,
            "https://example.com/google-link-avatar.png",
        )
        self.assertTrue(
            OAuthAccount.objects.filter(
                user=user,
                provider=OAuthProvider.GOOGLE,
                provider_user_id="google-link-123",
            ).exists()
        )

    @patch("apps.accounts.views.exchange_oauth_code_for_profile")
    def test_oauth_login_does_not_overwrite_existing_profile_image(self, mock_exchange):
        user = HiveUser.objects.create(
            username="oauth_user",
            email="oauth@example.com",
            password_hash=None,
            status=UserStatus.ACTIVE,
            profile_image="https://example.com/existing-avatar.png",
        )
        OAuthAccount.objects.create(
            user=user,
            provider=OAuthProvider.GOOGLE,
            provider_user_id="google-user-123",
            provider_email="oauth@example.com",
        )
        session = self.client.session
        session["oauth_state"] = {
            "provider": OAuthProvider.GOOGLE,
            "state": "test-state",
            "next_url": "",
        }
        session.save()
        mock_exchange.return_value = (
            {
                "provider_user_id": "google-user-123",
                "email": "oauth@example.com",
                "provider_email": "oauth@example.com",
                "profile_image": "https://example.com/google-avatar.png",
                "username_hint": "oauthuser",
            },
            {
                "provider": OAuthProvider.GOOGLE,
                "state": "test-state",
                "next_url": "",
                "action": "login",
                "link_user_id": "",
            },
        )

        response = self.client.get(
            "/auth/oauth/google/callback/",
            {"code": "auth-code", "state": "test-state"},
        )

        self.assertRedirects(response, "/dashboard/")
        user.refresh_from_db()
        self.assertEqual(user.profile_image, "https://example.com/existing-avatar.png")

    @patch("apps.accounts.views.exchange_oauth_code_for_profile")
    def test_oauth_link_callback_rejects_different_email(self, mock_exchange):
        user = HiveUser.objects.create(
            username="link_target",
            email="link@example.com",
            password_hash=make_password(self.LOGIN_PASSWORD),
            status=UserStatus.ACTIVE,
        )
        self._login(user)
        session = self.client.session
        session["oauth_state"] = {
            "provider": OAuthProvider.GITHUB,
            "state": "link-state",
            "next_url": "/me/",
            "action": "link",
            "link_user_id": str(user.id),
        }
        session.save()
        mock_exchange.return_value = (
            {
                "provider_user_id": "github-link-123",
                "email": "other@example.com",
                "provider_email": "other@example.com",
                "username_hint": "otheruser",
            },
            {
                "provider": OAuthProvider.GITHUB,
                "state": "link-state",
                "next_url": "/me/",
                "action": "link",
                "link_user_id": str(user.id),
            },
        )

        response = self.client.get(
            "/auth/oauth/github/callback/",
            {"code": "auth-code", "state": "link-state"},
        )

        self.assertRedirects(response, "/me/")
        self.assertFalse(
            OAuthAccount.objects.filter(
                user=user,
                provider=OAuthProvider.GITHUB,
            ).exists()
        )
