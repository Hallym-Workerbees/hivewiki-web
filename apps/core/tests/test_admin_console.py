from datetime import UTC, datetime

from django.contrib.auth.hashers import make_password
from django.contrib.sessions.models import Session
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
from apps.core.models import (
    IngestionJob,
    IngestionJobStatus,
    Post,
    PostStatus,
    Source,
    SourceChunk,
    SourceDocument,
    SourceDocumentFetchStatus,
    SourceDocumentWikiStatus,
    Tag,
    TagType,
    WikiDocument,
    WikiDocumentStatus,
    WikiRevision,
    WikiRevisionSource,
)


@override_settings(
    SESSION_ENGINE="django.contrib.sessions.backends.db",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "hivewiki-core-test-cache",
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

    def test_admin_dashboard_can_refresh_signals_section_with_htmx(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        self._login(admin_user)

        response = self.client.get(
            "/dashboard/admin/",
            {"section": "signals"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="admin-dashboard-signals"')
        self.assertContains(response, "운영 신호")
        self.assertNotContains(response, "<html", html=False)

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

    def test_admin_tag_management_can_refresh_tag_list_with_htmx(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        Tag.objects.create(name="온보딩", slug="온보딩", tag_type=TagType.SYSTEM)
        self._login(admin_user)

        response = self.client.get(
            "/dashboard/admin/tags/",
            {"section": "tag_list"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="admin-tags-list"')
        self.assertContains(response, "온보딩")
        self.assertNotContains(response, "<html", html=False)

    def test_admin_tag_management_returns_shell_for_htmx_tab_navigation(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        self._login(admin_user)

        response = self.client.get(
            "/dashboard/admin/tags/",
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="admin-page-shell"')
        self.assertContains(response, "태그 관리")
        self.assertNotContains(response, "<html", html=False)

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

    def test_admin_can_promote_user_to_admin(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        member_user = HiveUser.objects.create(
            username="member_user",
            email="member@example.com",
            password_hash=make_password("member-pass-123!"),
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )
        self._login(admin_user)

        response = self.client.post(
            f"/dashboard/admin/users/{member_user.id}/action/",
            {"action": "promote_admin"},
        )

        member_user.refresh_from_db()
        self.assertRedirects(response, "/dashboard/admin/users/")
        self.assertEqual(member_user.role, UserRole.ADMIN)

    def test_admin_can_suspend_user(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        member_user = HiveUser.objects.create(
            username="member_user",
            email="member@example.com",
            password_hash=make_password("member-pass-123!"),
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )
        self._login(admin_user)

        response = self.client.post(
            f"/dashboard/admin/users/{member_user.id}/action/",
            {"action": "suspend"},
        )

        member_user.refresh_from_db()
        self.assertRedirects(response, "/dashboard/admin/users/")
        self.assertEqual(member_user.status, UserStatus.SUSPENDED)

    def test_admin_user_action_rejects_unknown_action(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        member_user = HiveUser.objects.create(
            username="member_user",
            email="member@example.com",
            password_hash=make_password("member-pass-123!"),
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )
        self._login(admin_user)

        response = self.client.post(
            f"/dashboard/admin/users/{member_user.id}/action/",
            {"action": "unexpected"},
            follow=True,
        )

        member_user.refresh_from_db()
        self.assertRedirects(response, "/dashboard/admin/users/")
        self.assertEqual(member_user.role, UserRole.USER)
        self.assertEqual(member_user.status, UserStatus.ACTIVE)
        self.assertContains(response, "지원하지 않는 사용자 액션입니다.")

    def test_admin_delete_releases_email_username_and_oauth_link(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        member_user = HiveUser.objects.create(
            username="member_user",
            email="member@example.com",
            password_hash=make_password("member-pass-123!"),
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )
        OAuthAccount.objects.create(
            user=member_user,
            provider=OAuthProvider.GOOGLE,
            provider_user_id="google-member-123",
            provider_email="member@example.com",
        )
        self._login(admin_user)

        response = self.client.post(
            f"/dashboard/admin/users/{member_user.id}/action/",
            {"action": "delete"},
        )

        member_user.refresh_from_db()
        self.assertRedirects(response, "/dashboard/admin/users/")
        self.assertEqual(member_user.status, UserStatus.DELETED)
        self.assertEqual(member_user.role, UserRole.USER)
        self.assertIsNone(member_user.password_hash)
        self.assertIsNone(member_user.profile_image)
        self.assertNotEqual(member_user.email, "member@example.com")
        self.assertNotEqual(member_user.username, "member_user")
        self.assertFalse(member_user.oauth_accounts.exists())
        self.assertFalse(HiveUser.objects.filter(email="member@example.com").exists())
        self.assertFalse(HiveUser.objects.filter(username="member_user").exists())
        recreated_user = HiveUser.objects.create(
            username="member_user",
            email="member@example.com",
            password_hash=make_password("new-pass-123!"),
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )
        self.assertEqual(recreated_user.email, "member@example.com")

    def test_admin_delete_success_message_uses_original_username(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        member_user = HiveUser.objects.create(
            username="member_user",
            email="member@example.com",
            password_hash=make_password("member-pass-123!"),
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )
        self._login(admin_user)

        response = self.client.post(
            f"/dashboard/admin/users/{member_user.id}/action/",
            {"action": "delete"},
            follow=True,
        )

        self.assertRedirects(response, "/dashboard/admin/users/")
        self.assertContains(response, "member_user 사용자를 제거했습니다.")

    def test_admin_suspend_purges_user_session(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        member_user = HiveUser.objects.create(
            username="member_user",
            email="member@example.com",
            password_hash=make_password("member-pass-123!"),
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )
        member_client = self.client_class()
        member_session = member_client.session
        member_session[SESSION_USER_ID_KEY] = str(member_user.id)
        member_session.save()
        member_session_key = member_session.session_key
        member_client.get("/dashboard/")
        self._login(admin_user)

        response = self.client.post(
            f"/dashboard/admin/users/{member_user.id}/action/",
            {"action": "suspend"},
        )

        member_user.refresh_from_db()
        self.assertRedirects(response, "/dashboard/admin/users/")
        self.assertEqual(member_user.status, UserStatus.SUSPENDED)
        self.assertFalse(
            Session.objects.filter(session_key=member_session_key).exists()
        )

    def test_deleted_users_are_separated_from_primary_user_list(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        active_user = HiveUser.objects.create(
            username="active_user",
            email="active@example.com",
            password_hash=make_password("active-pass-123!"),
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )
        deleted_user = HiveUser.objects.create(
            username="deleted_user",
            email="deleted@example.com",
            password_hash=None,
            role=UserRole.USER,
            status=UserStatus.DELETED,
        )
        self._login(admin_user)

        response = self.client.get("/dashboard/admin/users/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "삭제된 계정")
        self.assertContains(response, active_user.email)
        self.assertContains(response, deleted_user.email, count=1)

    def test_admin_cannot_suspend_self(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        self._login(admin_user)

        response = self.client.post(
            f"/dashboard/admin/users/{admin_user.id}/action/",
            {"action": "suspend"},
            follow=True,
        )

        admin_user.refresh_from_db()
        self.assertRedirects(response, "/dashboard/admin/users/")
        self.assertEqual(admin_user.status, UserStatus.ACTIVE)
        self.assertContains(
            response,
            "자기 자신의 관리자 권한 제거, 비활성화, 삭제는 할 수 없습니다.",
        )

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
        self.assertContains(response, 'step="60"')
        self.assertContains(response, 'value="2026-05-02T10:30"')
        self.assertContains(response, "data-local-datetime-source=")
        self.assertContains(response, "2026-05-02T01:30+00:00")

    def test_admin_console_truncates_seconds_in_next_poll_at_input(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        source = Source.objects.create(
            name="초 단위 테스트 소스",
            target_url="https://example.com/timezone-seconds",
            enabled=True,
            poll_interval_minutes=30,
            next_poll_at=datetime(2026, 5, 2, 1, 30, 2, tzinfo=UTC),
            updated_at=timezone.now(),
        )
        self._login(admin_user)

        response = self.client.get(
            f"/dashboard/admin/sources/{source.id}/edit/",
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="2026-05-02T10:30"')
        self.assertContains(response, "2026-05-02T01:30+00:00")
        self.assertNotContains(response, "2026-05-02T01:30:02+00:00")

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

    def test_admin_can_delete_source_and_related_ingestion_records(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        source = Source.objects.create(
            name="삭제 대상 소스",
            target_url="https://example.com/remove-me",
            enabled=True,
            poll_interval_minutes=30,
            next_poll_at=timezone.now(),
            updated_at=timezone.now(),
        )
        document = SourceDocument.objects.create(
            source=source,
            canonical_url="https://example.com/remove-me/doc-1",
            title="삭제 대상 문서",
        )
        IngestionJob.objects.create(source_document=document, status="QUEUED")
        self._login(admin_user)

        response = self.client.post(
            f"/dashboard/admin/sources/{source.id}/edit/",
            {"action": "delete"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")
        self.assertFalse(Source.objects.filter(pk=source.pk).exists())
        self.assertFalse(SourceDocument.objects.filter(pk=document.pk).exists())
        self.assertEqual(IngestionJob.objects.count(), 0)

    def test_admin_can_delete_source_used_by_wiki_revision_sources(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        source = Source.objects.create(
            name="참조 중인 소스",
            target_url="https://example.com/referenced-source",
            enabled=True,
            poll_interval_minutes=30,
            next_poll_at=timezone.now(),
            updated_at=timezone.now(),
        )
        document = SourceDocument.objects.create(
            source=source,
            canonical_url="https://example.com/referenced-source/doc-1",
            title="참조 중인 문서",
        )
        source_chunk = SourceChunk.objects.create(
            source_document=document,
            chunk_index=0,
            content_text="근거 문장",
        )
        wiki_document = WikiDocument.objects.create(
            title="운영 가이드",
            slug="operations-guide",
            summary="삭제 테스트",
            status=WikiDocumentStatus.PUBLISHED,
        )
        revision = WikiRevision.objects.create(
            wiki_document=wiki_document,
            revision_number=1,
            content_markdown="본문",
        )
        wiki_document.current_revision = revision
        wiki_document.save(update_fields=["current_revision"])
        revision_source = WikiRevisionSource.objects.create(
            wiki_revision=revision,
            source_chunk=source_chunk,
            evidence_text="근거 문장",
        )
        self._login(admin_user)

        response = self.client.post(
            f"/dashboard/admin/sources/{source.id}/edit/",
            {"action": "delete"},
            HTTP_HX_REQUEST="true",
        )

        revision_source.refresh_from_db()
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")
        self.assertFalse(Source.objects.filter(pk=source.pk).exists())
        self.assertIsNone(revision_source.source_chunk)

    def test_admin_source_delete_success_message_is_rendered_on_ingestion_page(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        source = Source.objects.create(
            name="메시지 소스",
            target_url="https://example.com/message-me",
            enabled=True,
            poll_interval_minutes=30,
            next_poll_at=timezone.now(),
            updated_at=timezone.now(),
        )
        self._login(admin_user)

        self.client.post(
            f"/dashboard/admin/sources/{source.id}/edit/",
            {"action": "delete"},
            HTTP_HX_REQUEST="true",
        )
        response = self.client.get("/dashboard/admin/ingestion/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "소스 &#x27;메시지 소스&#x27;를 삭제했습니다. 연결된 수집 문서와 ingestion job도 함께 제거되었습니다.",
            html=False,
        )

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

    def test_admin_ingestion_management_can_refresh_sources_section_with_htmx(self):
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

        response = self.client.get(
            "/dashboard/admin/ingestion/",
            {"section": "sources"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="admin-ingestion-sources"')
        self.assertContains(response, "소스별 수집 현황")
        self.assertContains(response, "커뮤니티 공지")
        self.assertNotContains(response, "<html", html=False)

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

    def test_admin_ingestion_management_filters_sources_by_query_and_health(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        Source.objects.create(
            name="공지 RSS",
            target_url="https://example.com/announcements",
            enabled=True,
            poll_interval_minutes=15,
            next_poll_at=timezone.now(),
            updated_at=timezone.now(),
        )
        Source.objects.create(
            name="실패 RSS",
            target_url="https://example.com/failing",
            enabled=True,
            poll_interval_minutes=15,
            next_poll_at=timezone.now(),
            consecutive_failures=2,
            last_error_message="fetch failed",
            updated_at=timezone.now(),
        )
        self._login(admin_user)

        response = self.client.get(
            "/dashboard/admin/ingestion/",
            {
                "section": "sources",
                "source_query": "RSS",
                "source_health": "failing",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "실패 RSS")
        self.assertNotContains(response, "공지 RSS")

    def test_admin_ingestion_management_filters_documents_and_jobs_with_htmx(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        source = Source.objects.create(
            name="교내 공지",
            target_url="https://example.com/announcements",
            enabled=True,
            poll_interval_minutes=15,
            next_poll_at=timezone.now(),
            updated_at=timezone.now(),
        )
        matching_document = SourceDocument.objects.create(
            source=source,
            canonical_url="https://example.com/doc-1",
            title="장학금 공지",
            fetch_status=SourceDocumentFetchStatus.FAILED,
            wiki_status=SourceDocumentWikiStatus.REQUESTED,
        )
        other_document = SourceDocument.objects.create(
            source=source,
            canonical_url="https://example.com/doc-2",
            title="기숙사 안내",
            fetch_status=SourceDocumentFetchStatus.FETCHED,
            wiki_status=SourceDocumentWikiStatus.COMPLETED,
        )
        IngestionJob.objects.create(
            source_document=matching_document,
            status=IngestionJobStatus.FAILED,
            error_message="timeout",
        )
        other_document.ingestion_jobs.create(
            status=IngestionJobStatus.COMPLETED,
            error_message="",
        )
        self._login(admin_user)

        document_response = self.client.get(
            "/dashboard/admin/ingestion/",
            {
                "section": "recent_documents",
                "document_query": "장학금",
                "document_fetch_status": SourceDocumentFetchStatus.FAILED,
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(document_response.status_code, 200)
        self.assertContains(document_response, "장학금 공지")
        self.assertNotContains(document_response, "기숙사 안내")

        job_response = self.client.get(
            "/dashboard/admin/ingestion/",
            {
                "section": "recent_jobs",
                "job_query": "timeout",
                "job_status": IngestionJobStatus.FAILED,
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(job_response.status_code, 200)
        self.assertContains(job_response, "장학금 공지")
        self.assertNotContains(job_response, "기숙사 안내")

    def test_admin_ingestion_management_paginates_sources_panel(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        for index in range(7):
            Source.objects.create(
                name=f"소스 {index}",
                target_url=f"https://example.com/{index}",
                enabled=True,
                poll_interval_minutes=15,
                next_poll_at=timezone.now(),
                updated_at=timezone.now(),
            )
        self._login(admin_user)

        response = self.client.get(
            "/dashboard/admin/ingestion/",
            {"section": "sources", "source_page": 2},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "소스 6")
        self.assertNotContains(response, "소스 0")
        self.assertContains(response, "2 / 2")

    def test_admin_content_management_lists_posts_and_wiki_documents(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        post = Post.objects.create(
            author_user=admin_user,
            content_markdown="# 검색 개선\n관리자가 삭제 처리할 수 있는 게시글입니다.",
            status=PostStatus.PUBLISHED,
        )
        wiki_document = WikiDocument.objects.create(
            title="검색 운영 가이드",
            slug="search-ops-guide",
            summary="검색 운영 절차를 정리한 문서입니다.",
            status=WikiDocumentStatus.PUBLISHED,
        )
        revision = WikiRevision.objects.create(
            wiki_document=wiki_document,
            revision_number=1,
            content_markdown="# 검색 운영 가이드",
        )
        wiki_document.current_revision = revision
        wiki_document.save(update_fields=["current_revision", "updated_at"])
        self._login(admin_user)

        response = self.client.get("/dashboard/admin/content/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "커뮤니티 글 관리")
        self.assertContains(response, post.title)
        self.assertContains(response, "위키 문서 관리")
        self.assertContains(response, wiki_document.title)

    def test_admin_content_management_excludes_draft_posts(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        other_user = HiveUser.objects.create(
            username="member_user",
            email="member@example.com",
            password_hash=make_password("member-pass-123!"),
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )
        Post.objects.create(
            author_user=other_user,
            content_markdown="# 초안 글\n관리 화면에 보이면 안 됩니다.",
            status=PostStatus.DRAFT,
        )
        published_post = Post.objects.create(
            author_user=other_user,
            content_markdown="# 공개 글\n운영자가 볼 수 있는 게시글입니다.",
            status=PostStatus.PUBLISHED,
        )
        self._login(admin_user)

        response = self.client.get("/dashboard/admin/content/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, published_post.title)
        self.assertNotContains(response, "초안 글")
        self.assertNotContains(response, "Draft")

    def test_admin_content_management_can_refresh_posts_section_with_htmx(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        Post.objects.create(
            author_user=admin_user,
            content_markdown="# 삭제 후보\n운영자가 볼 수 있는 게시글입니다.",
            status=PostStatus.PUBLISHED,
        )
        self._login(admin_user)

        response = self.client.get(
            "/dashboard/admin/content/",
            {"section": "posts"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="admin-content-posts"')
        self.assertContains(response, "커뮤니티 글 관리")
        self.assertNotContains(response, "<html", html=False)

    def test_admin_content_management_can_filter_posts_by_search_and_tag(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        search_tag = Tag.objects.create(
            name="검색",
            slug="검색",
            tag_type=TagType.SYSTEM,
        )
        other_tag = Tag.objects.create(
            name="운영",
            slug="운영",
            tag_type=TagType.SYSTEM,
        )
        matching_post = Post.objects.create(
            author_user=admin_user,
            content_markdown="# 검색 개선 메모\n이 글만 필터되어야 합니다.",
            status=PostStatus.PUBLISHED,
        )
        matching_post.tags.add(search_tag)
        other_post = Post.objects.create(
            author_user=admin_user,
            content_markdown="# 운영 노트\n다른 태그를 가진 글입니다.",
            status=PostStatus.PUBLISHED,
        )
        other_post.tags.add(other_tag)
        self._login(admin_user)

        response = self.client.get(
            "/dashboard/admin/content/",
            {
                "section": "posts",
                "post_query": "검색",
                "post_tag": search_tag.slug,
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, matching_post.title)
        self.assertNotContains(response, other_post.title)

    def test_admin_content_management_hides_deleted_posts_by_default(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        visible_post = Post.objects.create(
            author_user=admin_user,
            content_markdown="# 공개 글\n기본 목록에 보여야 합니다.",
            status=PostStatus.PUBLISHED,
        )
        deleted_post = Post.objects.create(
            author_user=admin_user,
            content_markdown="# 삭제 글\n기본 목록에서는 숨겨져야 합니다.",
            status=PostStatus.PUBLISHED,
            deleted_at=timezone.now(),
        )
        self._login(admin_user)

        response = self.client.get("/dashboard/admin/content/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, visible_post.title)
        self.assertNotContains(response, deleted_post.title)

    def test_admin_content_management_can_show_deleted_posts_only(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        active_post = Post.objects.create(
            author_user=admin_user,
            content_markdown="# 공개 글\n삭제 전용 보기에서는 보이면 안 됩니다.",
            status=PostStatus.PUBLISHED,
        )
        deleted_post = Post.objects.create(
            author_user=admin_user,
            content_markdown="# 삭제 글\n토글을 켜면 보여야 합니다.",
            status=PostStatus.PUBLISHED,
            deleted_at=timezone.now(),
        )
        self._login(admin_user)

        response = self.client.get(
            "/dashboard/admin/content/",
            {"section": "posts", "post_visibility": "deleted"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, deleted_post.title)
        self.assertNotContains(response, active_post.title)

    def test_admin_content_management_can_show_all_posts(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        active_post = Post.objects.create(
            author_user=admin_user,
            content_markdown="# 공개 글\n전체 보기에서 보여야 합니다.",
            status=PostStatus.PUBLISHED,
        )
        deleted_post = Post.objects.create(
            author_user=admin_user,
            content_markdown="# 삭제 글\n전체 보기에서 보여야 합니다.",
            status=PostStatus.PUBLISHED,
            deleted_at=timezone.now(),
        )
        self._login(admin_user)

        response = self.client.get(
            "/dashboard/admin/content/",
            {"section": "posts", "post_visibility": "all"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, active_post.title)
        self.assertContains(response, deleted_post.title)

    def test_admin_content_management_paginates_posts(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        for index in range(7):
            Post.objects.create(
                author_user=admin_user,
                content_markdown=f"# 게시글 {index}\n페이지네이션 테스트 {index}",
                status=PostStatus.PUBLISHED,
            )
        self._login(admin_user)

        response = self.client.get(
            "/dashboard/admin/content/",
            {"section": "posts", "post_page": "2"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2 / 2")

    def test_admin_content_management_can_filter_wiki_documents_by_status(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        archived_document = WikiDocument.objects.create(
            title="보관 문서",
            slug="archived-doc",
            summary="보관된 문서",
            status=WikiDocumentStatus.ARCHIVED,
        )
        published_document = WikiDocument.objects.create(
            title="게시 문서",
            slug="published-doc",
            summary="게시된 문서",
            status=WikiDocumentStatus.PUBLISHED,
        )
        self._login(admin_user)

        response = self.client.get(
            "/dashboard/admin/content/",
            {"section": "wiki_documents", "wiki_status": WikiDocumentStatus.ARCHIVED},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, archived_document.title)
        self.assertNotContains(response, published_document.title)

    def test_admin_cannot_publish_wiki_document_without_current_revision(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        wiki_document = WikiDocument.objects.create(
            title="미완성 위키",
            slug="draft-wiki",
            summary="현재 리비전이 없는 문서입니다.",
            status=WikiDocumentStatus.ARCHIVED,
        )
        self._login(admin_user)

        response = self.client.post(
            f"/dashboard/admin/content/wiki/{wiki_document.id}/action/",
            {"action": "publish"},
            follow=True,
        )

        wiki_document.refresh_from_db()
        self.assertRedirects(response, "/dashboard/admin/content/")
        self.assertEqual(wiki_document.status, WikiDocumentStatus.ARCHIVED)
        self.assertContains(
            response, "현재 리비전이 없는 위키 문서는 게시할 수 없습니다."
        )

    def test_admin_can_delete_and_restore_post(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        post = Post.objects.create(
            author_user=admin_user,
            content_markdown="# 운영 공지\n삭제 대상 게시글입니다.",
            status=PostStatus.PUBLISHED,
        )
        self._login(admin_user)

        delete_response = self.client.post(
            f"/dashboard/admin/content/posts/{post.id}/action/",
            {"action": "delete"},
        )
        post.refresh_from_db()

        self.assertRedirects(delete_response, "/dashboard/admin/content/")
        self.assertIsNotNone(post.deleted_at)

        restore_response = self.client.post(
            f"/dashboard/admin/content/posts/{post.id}/action/",
            {"action": "restore"},
        )
        post.refresh_from_db()

        self.assertRedirects(restore_response, "/dashboard/admin/content/")
        self.assertIsNone(post.deleted_at)

    def test_admin_can_change_wiki_document_status(self):
        admin_user = HiveUser.objects.create(
            username="admin_user",
            email="admin@example.com",
            password_hash=make_password("admin-pass-123!"),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        wiki_document = WikiDocument.objects.create(
            title="운영 정책 문서",
            slug="ops-policy",
            summary="관리자가 상태를 바꿀 수 있는 위키 문서입니다.",
            status=WikiDocumentStatus.PUBLISHED,
        )
        revision = WikiRevision.objects.create(
            wiki_document=wiki_document,
            revision_number=1,
            content_markdown="# 운영 정책 문서",
        )
        wiki_document.current_revision = revision
        wiki_document.save(update_fields=["current_revision", "updated_at"])
        self._login(admin_user)

        archive_response = self.client.post(
            f"/dashboard/admin/content/wiki/{wiki_document.id}/action/",
            {"action": "archive"},
        )
        wiki_document.refresh_from_db()
        self.assertRedirects(archive_response, "/dashboard/admin/content/")
        self.assertEqual(wiki_document.status, WikiDocumentStatus.ARCHIVED)

        publish_response = self.client.post(
            f"/dashboard/admin/content/wiki/{wiki_document.id}/action/",
            {"action": "publish"},
        )
        wiki_document.refresh_from_db()
        self.assertRedirects(publish_response, "/dashboard/admin/content/")
        self.assertEqual(wiki_document.status, WikiDocumentStatus.PUBLISHED)
