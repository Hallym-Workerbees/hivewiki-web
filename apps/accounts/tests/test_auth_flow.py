from unittest.mock import patch

from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.accounts.models import HiveUser, OAuthAccount, OAuthProvider, UserStatus
from apps.accounts.services import (
    SESSION_USER_ID_KEY,
    TIMEZONE_SESSION_KEY,
    read_pending_oauth_confirmation,
)


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
        self._login(user)

        response = self.client.get("/me/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "profile_user")
        self.assertContains(response, "profile@example.com")
        self.assertContains(response, "https://example.com/avatar.png")
        self.assertContains(response, "비밀번호 변경")
        self.assertContains(response, "Google 연결")

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
        self.assertFalse(user.profile_image)
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
        self.assertTrue(
            OAuthAccount.objects.filter(
                user=user,
                provider=OAuthProvider.GOOGLE,
                provider_user_id="google-link-123",
            ).exists()
        )

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
