"""
Study set ZIPs are served only through login- and institution-checked
views, never as public /media/ files.
"""

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from uploads.models import CTExamination, UserProfile


def _user(username: str, site_code: str = "S001", **kwargs) -> User:
    user = User.objects.create_user(username, f"{username}@example.com", "pass12345", **kwargs)
    if site_code is not None:
        UserProfile.objects.create(
            user=user, institution="Test Hospital", professional_role="radiologist",
            terms_accepted=True, site_code=site_code,
        )
    return user


def _exam_with_zip(site_code: str = "S001", created_by: str = "someone") -> CTExamination:
    exam = CTExamination.objects.create(
        rhythm_pseudo_id=f"RHY-{site_code}-HEADTRAUMA-NC-PH-G3-000001", site_code=site_code,
        anatomical_region="Head", clinical_indication="Trauma", image_quality="GOOD",
        created_by=created_by,
    )
    exam.study_set_file.save("RHY-study.zip", ContentFile(b"PK\x05\x06" + b"\0" * 18))
    return exam


class ExaminationStudySetDownloadTests(TestCase):
    def setUp(self) -> None:
        self.exam = _exam_with_zip(site_code="S001")
        self.url = reverse("examination-study-set-download", args=[self.exam.pk])

    def test_anonymous_is_sent_to_login(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"))

    def test_same_institution_user_downloads_the_zip(self) -> None:
        self.client.force_login(_user("colleague", site_code="S001"))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(b"".join(response.streaming_content).startswith(b"PK"))

    def test_other_institution_user_gets_404(self) -> None:
        self.client.force_login(_user("outsider", site_code="S004"))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_user_without_institution_can_only_get_their_own(self) -> None:
        self.client.force_login(_user("someone", site_code=None))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.client.force_login(_user("stranger", site_code=None))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_staff_can_download_any_institution(self) -> None:
        self.client.force_login(_user("admin", site_code="S004", is_staff=True))
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_exam_without_file_is_404(self) -> None:
        exam = CTExamination.objects.create(rhythm_pseudo_id="RHY-NOFILE", site_code="S001")
        self.client.force_login(_user("colleague", site_code="S001"))
        url = reverse("examination-study-set-download", args=[exam.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_malformed_id_is_404(self) -> None:
        self.client.force_login(_user("colleague", site_code="S001"))
        self.assertEqual(self.client.get("/examinations/not-a-uuid/study-set/").status_code, 404)

    def test_examination_list_links_to_the_checked_view_not_media(self) -> None:
        self.client.force_login(_user("colleague", site_code="S001"))
        response = self.client.get(reverse("examination-list"))
        self.assertContains(response, self.url)
        self.assertNotContains(response, "/media/examination_study_sets/")


class ExaminationDeleteRemovesStudySetTests(TestCase):
    def test_deleting_an_examination_removes_its_zip(self) -> None:
        exam = _exam_with_zip(site_code="S001")
        storage, name = exam.study_set_file.storage, exam.study_set_file.name
        self.assertTrue(storage.exists(name))
        self.client.force_login(_user("colleague", site_code="S001"))
        response = self.client.post(reverse("examination-delete", kwargs={"pk": str(exam.pk)}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CTExamination.objects.filter(pk=exam.pk).exists())
        self.assertFalse(storage.exists(name))

    def test_other_institution_cannot_delete_or_remove_the_zip(self) -> None:
        exam = _exam_with_zip(site_code="S001")
        storage, name = exam.study_set_file.storage, exam.study_set_file.name
        self.client.force_login(_user("outsider", site_code="S004"))
        response = self.client.post(reverse("examination-delete", kwargs={"pk": str(exam.pk)}))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(storage.exists(name))

    def test_deleting_an_examination_without_a_file_still_works(self) -> None:
        exam = CTExamination.objects.create(rhythm_pseudo_id="RHY-NOFILE", site_code="S001")
        self.client.force_login(_user("colleague", site_code="S001"))
        response = self.client.post(reverse("examination-delete", kwargs={"pk": str(exam.pk)}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CTExamination.objects.filter(pk=exam.pk).exists())
