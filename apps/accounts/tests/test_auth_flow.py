from unittest.mock import patch

from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.accounts.models import HiveUser, OAuthAccount, OAuthProvider, UserStatus
from apps.accounts.services import SESSION_USER_ID_KEY


@override_settings(
    SESSION_ENGINE="django.contrib.sessions.backends.db",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "hivewiki-test-cache",
        }
    },
    GOOGLE_OAUTH_CLIENT_ID="google-client-id",
    GOOGLE_OAUTH_CLIENT_SECRET="google-client-secret",
    GITHUB_OAUTH_CLIENT_ID="github-client-id",
    GITHUB_OAUTH_CLIENT_SECRET="github-client-secret",
)
class AuthFlowTests(TestCase):
    SIGNUP_PASSWORD = "".join(["Strong", "Pass", "123"])
    LOGIN_PASSWORD = "".join(["test", "pass", "123!"])
    OLD_PASSWORD = "".join(["old", "pass", "123!"])
    NEW_PASSWORD = "".join(["new", "pass", "123!"])
    RIGHT_PASSWORD = "".join(["right", "pass", "123!"])

    def setUp(self):
        cache.clear()

    def _login(self, user):
        session = self.client.session
        session[SESSION_USER_ID_KEY] = str(user.id)
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
        self._login(user)

        response = self.client.get("/me/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "profile_user")
        self.assertContains(response, "profile@example.com")
        self.assertContains(response, "https://example.com/avatar.png")

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

    def test_logout_requires_post(self):
        response = self.client.get("/auth/logout/")

        self.assertEqual(response.status_code, 405)

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
                "username_hint": "oauthuser",
            },
            "",
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
        self.assertFalse(user.profile_image)
        self.assertEqual(self.client.session[SESSION_USER_ID_KEY], str(user.id))

    @patch("apps.accounts.views.exchange_oauth_code_for_profile")
    def test_github_oauth_callback_links_existing_user(self, mock_exchange):
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
                "username_hint": "octocat",
            },
            "/me/",
        )

        response = self.client.get(
            "/auth/oauth/github/callback/",
            {"code": "auth-code", "state": "test-state"},
        )

        self.assertRedirects(response, "/me/")
        oauth_account = OAuthAccount.objects.get(
            provider=OAuthProvider.GITHUB,
            provider_user_id="github-user-456",
        )
        self.assertEqual(oauth_account.user_id, user.id)
        user.refresh_from_db()
        self.assertFalse(user.profile_image)
        self.assertEqual(self.client.session[SESSION_USER_ID_KEY], str(user.id))
