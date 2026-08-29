"""
Tests that DRF API endpoints under /api/v1/ accept the user's existing
Django login session (not just a Bearer/Token header), so browser pages
served by the app itself (Automated Upload, My Uploads) can call them via
fetch() without requiring a separately-issued API token.
"""

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse


class SessionAuthForManifestValidationTests(TestCase):

    def setUp(self) -> None:
        self.user = User.objects.create_user("sessionuser", password="pass")

    def test_authenticated_session_can_call_validate_manifest(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.post(
            "/api/v1/uploads/validate-manifest/",
            data={"manifest": {"type": "rhythm_server_assigned_upload_manifest", "items": []}},
            content_type="application/json",
        )
        # 400 (invalid manifest content) proves the request got past
        # authentication and into view logic — not a 401.
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["valid"])

    def test_unauthenticated_session_still_rejected(self) -> None:
        resp = self.client.post(
            "/api/v1/uploads/validate-manifest/",
            data={"manifest": {}},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    @override_settings(RAW_DATA_DIR="/tmp/eutempe_test_session_auth")
    def test_authenticated_session_can_init_chunked_upload(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.post(
            "/api/v1/uploads/chunked/init/",
            data={"filename": "study.zip", "total_size": 1024},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
