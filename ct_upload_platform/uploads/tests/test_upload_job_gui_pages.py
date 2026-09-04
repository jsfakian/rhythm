"""
Tests for the re-enabled "My Uploads" / "Automated Upload" / "Manifest
Validator" GUI pages (protocol_views.UploadJobListView, UploadJobDeleteView,
AutomatedUploadView, JSONValidatorView) and their sidebar entries.
"""

import os
import tempfile

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from uploads.models import CTExamination, UploadJob


class UploadJobListViewTests(TestCase):

    def setUp(self) -> None:
        self.user = User.objects.create_user("uploaduser", password="pass")
        self.client.force_login(self.user)

    def test_redirects_when_unauthenticated(self) -> None:
        self.client.logout()
        resp = self.client.get(reverse("upload-job-list"))
        self.assertIn(resp.status_code, (302, 301))

    def test_page_returns_200(self) -> None:
        resp = self.client.get(reverse("upload-job-list"))
        self.assertEqual(resp.status_code, 200)

    def test_page_title_is_my_uploads(self) -> None:
        resp = self.client.get(reverse("upload-job-list"))
        self.assertIn(b"My Uploads", resp.content)

    def test_own_job_listed(self) -> None:
        UploadJob.objects.create(uploader_id="uploaduser", status="PENDING")
        resp = self.client.get(reverse("upload-job-list"))
        self.assertContains(resp, "Pending")

    def test_other_users_job_not_listed_without_site_code(self) -> None:
        UploadJob.objects.create(uploader_id="someoneelse", status="PENDING")
        resp = self.client.get(reverse("upload-job-list"))
        self.assertEqual(len(resp.context["jobs"]), 0)

    def test_status_filter(self) -> None:
        UploadJob.objects.create(uploader_id="uploaduser", status="PENDING")
        UploadJob.objects.create(uploader_id="uploaduser", status="COMPLETE")
        resp = self.client.get(reverse("upload-job-list"), {"status": "COMPLETE"})
        self.assertEqual(len(resp.context["jobs"]), 1)
        self.assertEqual(resp.context["jobs"][0].status, "COMPLETE")

    def test_manifest_ref_and_filename_shown(self) -> None:
        UploadJob.objects.create(
            uploader_id="uploaduser",
            status="PENDING",
            manifest_raw={"ref": "ROW0001", "filename": "study.zip", "batch": "S001-BATCH001"},
        )
        resp = self.client.get(reverse("upload-job-list"))
        self.assertContains(resp, "ROW0001")
        self.assertContains(resp, "study.zip")
        self.assertContains(resp, "S001-BATCH001")


class UploadJobDeleteViewTests(TestCase):

    def setUp(self) -> None:
        self.user = User.objects.create_user("deleteuser", password="pass")
        self.client.force_login(self.user)

    def test_confirm_page_returns_200(self) -> None:
        job = UploadJob.objects.create(uploader_id="deleteuser", status="PENDING")
        resp = self.client.get(reverse("upload-job-delete", kwargs={"pk": str(job.pk)}))
        self.assertEqual(resp.status_code, 200)

    def test_deletes_pending_job(self) -> None:
        job = UploadJob.objects.create(uploader_id="deleteuser", status="PENDING")
        resp = self.client.post(reverse("upload-job-delete", kwargs={"pk": str(job.pk)}))
        self.assertRedirects(resp, reverse("upload-job-list"))
        self.assertFalse(UploadJob.objects.filter(pk=job.pk).exists())

    def test_refuses_to_delete_non_pending_job(self) -> None:
        job = UploadJob.objects.create(uploader_id="deleteuser", status="COMPLETE")
        resp = self.client.post(reverse("upload-job-delete", kwargs={"pk": str(job.pk)}))
        self.assertRedirects(resp, reverse("upload-job-list"))
        self.assertTrue(UploadJob.objects.filter(pk=job.pk).exists())

    def test_other_users_job_returns_404_without_site_code(self) -> None:
        job = UploadJob.objects.create(uploader_id="someoneelse", status="PENDING")
        resp = self.client.get(reverse("upload-job-delete", kwargs={"pk": str(job.pk)}))
        self.assertEqual(resp.status_code, 404)

    def test_deletes_orphaned_archive_file(self) -> None:
        """A bulk/automated-upload job has no CTExamination — its staging
        archive is genuinely orphaned once the job is deleted, and should
        be removed from disk."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tar")
        tmp.write(b"fake archive contents")
        tmp.close()
        job = UploadJob.objects.create(
            uploader_id="deleteuser", status="PENDING", tar_temp_path=tmp.name
        )
        try:
            resp = self.client.post(reverse("upload-job-delete", kwargs={"pk": str(job.pk)}))
            self.assertRedirects(resp, reverse("upload-job-list"))
            self.assertFalse(os.path.exists(tmp.name))
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def test_preserves_archive_file_referenced_by_examination(self) -> None:
        """Regression: for a job queued by Manual Exam Entry, tar_temp_path
        IS exam.study_set_file.path — the same file the CTExamination still
        references for download. Deleting a PENDING job must not unlink
        that file out from under the examination."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tar")
        tmp.write(b"fake archive contents")
        tmp.close()
        job = UploadJob.objects.create(
            uploader_id="deleteuser", status="PENDING", tar_temp_path=tmp.name
        )
        CTExamination.objects.create(upload_job=job)
        try:
            resp = self.client.post(reverse("upload-job-delete", kwargs={"pk": str(job.pk)}))
            self.assertRedirects(resp, reverse("upload-job-list"))
            self.assertFalse(UploadJob.objects.filter(pk=job.pk).exists())
            self.assertTrue(os.path.exists(tmp.name))
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)


class AutomatedUploadViewTests(TestCase):

    def setUp(self) -> None:
        self.user = User.objects.create_user("automateduser", password="pass")
        self.client.force_login(self.user)

    def test_redirects_when_unauthenticated(self) -> None:
        self.client.logout()
        resp = self.client.get(reverse("automated-upload"))
        self.assertIn(resp.status_code, (302, 301))

    def test_page_returns_200(self) -> None:
        resp = self.client.get(reverse("automated-upload"))
        self.assertEqual(resp.status_code, 200)

    def test_page_contains_manifest_and_zip_inputs(self) -> None:
        resp = self.client.get(reverse("automated-upload"))
        self.assertIn(b'id="inp_manifest"', resp.content)
        self.assertIn(b'id="inp_zips"', resp.content)

    def test_page_links_to_manifest_generator_tool_repo(self) -> None:
        """Partners need the manifest generator tool (py source, Windows
        .exe, and manifest template) before they can use this page at all —
        it must link to where those are published."""
        resp = self.client.get(reverse("automated-upload"))
        self.assertContains(
            resp,
            'href="https://github.com/jsfakian/rhythm/tree/main/create_rhythm_service_manifest_gui_with_uid"',
        )


class ManifestValidatorPageTests(TestCase):

    def setUp(self) -> None:
        self.user = User.objects.create_user("validatoruser", password="pass")
        self.client.force_login(self.user)

    def test_page_returns_200(self) -> None:
        resp = self.client.get(reverse("json-validator"))
        self.assertEqual(resp.status_code, 200)

    def test_page_title_is_manifest_validator(self) -> None:
        resp = self.client.get(reverse("json-validator"))
        self.assertIn(b"Manifest Validator", resp.content)

    def test_page_has_validate_as_manifest_button(self) -> None:
        resp = self.client.get(reverse("json-validator"))
        self.assertIn(b"Validate as Manifest", resp.content)


class SidebarUploadLinksTests(TestCase):
    """The three previously-disabled sidebar entries must now be real,
    clickable links pointing at the new pages."""

    def setUp(self) -> None:
        self.user = User.objects.create_user("sidebaruser", password="pass")
        self.client.force_login(self.user)

    def test_automated_upload_link_enabled(self) -> None:
        resp = self.client.get(reverse("upload-job-list"))
        self.assertContains(resp, 'href="/automated-upload/"')
        self.assertNotContains(resp, "Coming soon")

    def test_manifest_validator_link_enabled(self) -> None:
        resp = self.client.get(reverse("upload-job-list"))
        self.assertContains(resp, 'href="/json-validator/"')

    def test_my_uploads_link_enabled(self) -> None:
        resp = self.client.get(reverse("upload-job-list"))
        self.assertContains(resp, 'href="/my-uploads/"')
