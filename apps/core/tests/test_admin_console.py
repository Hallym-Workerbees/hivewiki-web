from datetime import UTC, datetime

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import (
    HiveUser,
    OAuthAccount,
    OAuthProvider,
    UserRole,
    UserStatus,
)
from apps.accounts.services import SESSION_USER_ID_KEY
from apps.core.models import Source, Tag, TagType


@override_settings(
    SESSION_ENGINE="django.contrib.sessions.backends.db",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "hivewiki-core-test-cache",
        }
    },
)
class AdminConsoleTests(TestCase):
    def _login(self, user):
        session = self.client.session
        session[SESSION_USER_ID_KEY] = str(user.id)
        session.save()

    def test_admin_console_requires_login(self):
        response = self.client.get("/dashboard/admin/")

        self.assertRedirects(response, "/auth/login/?next=%2Fdashboard%2Fadmin%2F")

    def test_admin_console_rejects_non_admin_user(self):
        user = HiveUser.objects.create(
            username="member_user",
            email="member@example.com",
            password_hash=make_password("member-pass-123!"),
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )
        self._login(user)

        response = self.client.get("/dashboard/admin/")

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "관리자만 접근할 수 있습니다.", status_code=403)

    def test_admin_console_renders_existing_tags_and_sources(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        Tag.objects.create(name="온보딩", slug="온보딩", tag_type=TagType.SYSTEM)
        Source.objects.create(
            name="커뮤니티 공지",
            target_url="https://example.com/announcements",
            enabled=True,
            poll_interval_minutes=15,
            next_poll_at=timezone.now(),
            updated_at=timezone.now(),
        )
        self._login(admin_user)

        response = self.client.get("/dashboard/admin/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "운영 상태를 한 화면에서 점검합니다.")
        self.assertContains(response, "유저 관리")
        self.assertContains(response, "데이터 수집")

    def test_admin_can_create_tag_with_generated_slug(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        self._login(admin_user)

        response = self.client.post(
            "/dashboard/admin/tags/",
            {
                "name": "디자인 시스템",
                "slug": "",
                "tag_type": TagType.SYSTEM,
            },
        )

        saved_tag = Tag.objects.get(name="디자인 시스템")
        self.assertRedirects(response, "/dashboard/admin/tags/")
        self.assertEqual(saved_tag.slug, "디자인-시스템")
        self.assertEqual(saved_tag.tag_type, TagType.SYSTEM)

    def test_admin_tag_management_lists_tags(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        Tag.objects.create(name="온보딩", slug="온보딩", tag_type=TagType.SYSTEM)
        self._login(admin_user)

        response = self.client.get("/dashboard/admin/tags/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "태그 생성")
        self.assertContains(response, "온보딩")

    def test_admin_user_management_shows_oauth_connection_status(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        oauth_user = HiveUser.objects.create(
            username="oauth_user",
            email="oauth@example.com",
            password_hash=make_password("oauth-pass-123!"),
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )
        OAuthAccount.objects.create(
            user=oauth_user,
            provider=OAuthProvider.GITHUB,
            provider_user_id="github-123",
            provider_email="oauth@example.com",
            last_login_at=timezone.now(),
        )
        self._login(admin_user)

        response = self.client.get("/dashboard/admin/users/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OAuth 연동")
        self.assertContains(response, "GITHUB")
        self.assertContains(response, "미연동")

    def test_admin_can_open_tag_edit_modal(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        tag = Tag.objects.create(
            name="사용자 태그",
            slug="사용자-태그",
            tag_type=TagType.USER,
        )
        self._login(admin_user)

        response = self.client.get(
            f"/dashboard/admin/tags/{tag.id}/edit/",
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "사용자 태그 수정")
        self.assertContains(response, "data-admin-modal")

    def test_admin_console_renders_next_poll_at_with_datetime_source(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        source = Source.objects.create(
            name="시간대 테스트 소스",
            target_url="https://example.com/timezone",
            enabled=True,
            poll_interval_minutes=30,
            next_poll_at=datetime(2026, 5, 2, 1, 30, tzinfo=UTC),
            updated_at=timezone.now(),
        )
        self._login(admin_user)

        response = self.client.get(
            f"/dashboard/admin/sources/{source.id}/edit/",
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-local-datetime-input="true"')
        self.assertContains(response, "data-local-datetime-source=")

    def test_admin_can_change_existing_tag_type(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        tag = Tag.objects.create(
            name="사용자 태그",
            slug="사용자-태그",
            tag_type=TagType.USER,
        )
        self._login(admin_user)

        response = self.client.post(
            f"/dashboard/admin/tags/{tag.id}/edit/",
            {
                "name": "사용자 태그",
                "slug": "사용자-태그",
                "tag_type": TagType.SYSTEM,
            },
            HTTP_HX_REQUEST="true",
        )

        tag.refresh_from_db()
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")
        self.assertEqual(tag.tag_type, TagType.SYSTEM)

    def test_admin_can_create_source(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        self._login(admin_user)

        response = self.client.post(
            "/dashboard/admin/ingestion/",
            {
                "name": "교내 공지 RSS",
                "target_url": "https://example.com/rss",
                "enabled": "on",
                "poll_interval_minutes": "45",
                "next_poll_at": "2026-05-02T10:30",
            },
        )

        source = Source.objects.get(name="교내 공지 RSS")
        self.assertRedirects(response, "/dashboard/admin/ingestion/")
        self.assertEqual(source.target_url, "https://example.com/rss")
        self.assertTrue(source.enabled)
        self.assertEqual(source.poll_interval_minutes, 45)

    def test_admin_ingestion_management_shows_verbose_status(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        Source.objects.create(
            name="커뮤니티 공지",
            target_url="https://example.com/announcements",
            enabled=True,
            poll_interval_minutes=15,
            next_poll_at=timezone.now(),
            updated_at=timezone.now(),
        )
        self._login(admin_user)

        response = self.client.get("/dashboard/admin/ingestion/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "소스별 수집 현황")
        self.assertContains(response, "커뮤니티 공지")
        self.assertContains(response, "최근 수집 문서")
        self.assertContains(response, "Healthy")

    def test_admin_ingestion_management_marks_failing_sources(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        Source.objects.create(
            name="실패 소스",
            target_url="https://example.com/failing",
            enabled=True,
            poll_interval_minutes=15,
            next_poll_at=timezone.now(),
            consecutive_failures=2,
            last_error_message="fetch failed",
            updated_at=timezone.now(),
        )
        self._login(admin_user)

        response = self.client.get("/dashboard/admin/ingestion/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Failing")
        self.assertContains(response, "실패 소스")

    def test_admin_ingestion_management_marks_disabled_sources_as_paused(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        Source.objects.create(
            name="중지 소스",
            target_url="https://example.com/paused",
            enabled=False,
            poll_interval_minutes=15,
            next_poll_at=timezone.now(),
            updated_at=timezone.now(),
        )
        self._login(admin_user)

        response = self.client.get("/dashboard/admin/ingestion/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Paused")
        self.assertContains(response, "중지 소스")
