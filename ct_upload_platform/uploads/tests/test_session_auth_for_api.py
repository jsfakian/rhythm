"""
Tests that DRF API endpoints under /api/v1/ accept the user's existing
Django login session (not just a Bearer/Token header), so browser pages
served by the app itself (Automated Upload, My Uploads) can call them via
fetch() without requiring a separately-issued API token.
"""

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
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

    @override_settings(RAW_DATA_DIR="/tmp/test_session_auth")
    def test_authenticated_session_can_init_chunked_upload(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.post(
            "/api/v1/uploads/chunked/init/",
            data={"filename": "study.zip", "total_size": 1024},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

    @override_settings(RAW_DATA_DIR="/tmp/test_session_auth_chunk")
    def test_authenticated_session_can_upload_a_chunk(self) -> None:
        """Regression test: under SessionAuthentication, Django's CSRF check
        (_check_token) accesses request.POST first, which — via DRF's
        default parsers — consumes the body stream for any
        JSON/form/multipart content type, breaking a later request.body
        read (RawPostDataException / 500), and raises UnsupportedMediaType
        (415) outright for content types with no registered parser at all
        (e.g. application/zip, the archive's real MIME type). Only Bearer
        token auth (no CSRF check) avoided this. ChunkedUploadChunkView's
        RawBinaryParser + request.data (not request.body) fixes both.

        Django's default test Client disables CSRF enforcement entirely
        (_dont_enforce_csrf_checks), which DRF's SessionAuthentication.
        enforce_csrf() respects too — so this test would pass even without
        the fix unless CSRF is genuinely turned on and exercised for real,
        via enforce_csrf_checks=True with a real token cookie + header.
        """
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        # Prime the CSRF cookie via a real page that renders {{ csrf_token }}
        # for an authenticated user (/login/ redirects once logged in and
        # never sets it).
        csrf_client.get("/automated-upload/")
        csrf_token = csrf_client.cookies["csrftoken"].value

        init_resp = csrf_client.post(
            "/api/v1/uploads/chunked/init/",
            data={"filename": "study.zip", "total_size": 4, "chunk_size": 10485760},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(init_resp.status_code, 201, init_resp.content)
        session_id = init_resp.json()["session_id"]

        import hashlib
        chunk_bytes = b"data"
        chunk_hash = hashlib.sha256(chunk_bytes).hexdigest()
        resp = csrf_client.post(
            f"/api/v1/uploads/chunked/{session_id}/chunk/?chunk_number=0&chunk_hash={chunk_hash}",
            data=chunk_bytes,
            content_type="application/zip",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(resp.status_code, 202, resp.content)
        self.assertEqual(resp.json()["uploaded_chunks"], 1)
