"""
Tests for institution-wide data sharing.

Colleagues who share a UserProfile.site_code get full read/write access to
each other's scanners, protocols, examinations, and upload jobs. Different
institutions (different site_code) cannot see each other's data. Superusers
still bypass scoping entirely, and profile-less users fall back to
legacy created_by/uploader_id-only visibility.
"""

import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from uploads.models import (
    CTExamination,
    CTManufacturer,
    CTProtocol,
    CTScannerModel,
    CTScannerProfile,
    UploadJob,
    UserProfile,
)


def _make_user_with_site_code(username, site_code, institution='Test Hospital'):
    user = User.objects.create_user(username, f'{username}@example.com', 'pass12345')
    UserProfile.objects.create(
        user=user, institution=institution,
        professional_role='radiologist', terms_accepted=True,
        site_code=site_code,
    )
    return user


def _make_scanner(created_by='', site_code=''):
    mfr, _ = CTManufacturer.objects.get_or_create(name='Siemens Healthineers', defaults={'sort_order': 1})
    mdl, _ = CTScannerModel.objects.get_or_create(
        manufacturer=mfr, name='Somatom Force Test', defaults={'sort_order': 0}
    )
    return CTScannerProfile.objects.create(
        manufacturer=mfr, scanner_model=mdl,
        detector_rows='192', year_of_installation='2021',
        created_by=created_by, site_code=site_code,
    )


class ScannerProfileInstitutionScopingTests(TestCase):
    """DRF API (CTScannerProfileViewSet) and GUI (ScannerProfileListView etc) scoping."""

    def setUp(self):
        self.alice = _make_user_with_site_code('alice', 'S001')
        self.bob = _make_user_with_site_code('bob', 'S001')  # same institution as alice
        self.carol = _make_user_with_site_code('carol', 'S002')  # different institution

        self.scanner = _make_scanner(created_by='alice', site_code='S001')

        self.alice_token, _ = Token.objects.get_or_create(user=self.alice)
        self.bob_token, _ = Token.objects.get_or_create(user=self.bob)
        self.carol_token, _ = Token.objects.get_or_create(user=self.carol)

    def _api_client(self, token):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        return client

    def test_same_institution_sees_colleagues_scanner_in_api_list(self):
        resp = self._api_client(self.bob_token).get('/api/v1/scanner-profiles/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [s['id'] for s in resp.data['results']]
        self.assertIn(str(self.scanner.pk), ids)

    def test_different_institution_cannot_see_scanner_in_api_list(self):
        resp = self._api_client(self.carol_token).get('/api/v1/scanner-profiles/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [s['id'] for s in resp.data['results']]
        self.assertNotIn(str(self.scanner.pk), ids)

    def test_same_institution_can_update_colleagues_scanner_via_api(self):
        resp = self._api_client(self.bob_token).patch(
            f'/api/v1/scanner-profiles/{self.scanner.pk}/',
            {'local_protocol_note': 'Updated by bob'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_different_institution_gets_404_on_colleagues_scanner(self):
        resp = self._api_client(self.carol_token).get(f'/api/v1/scanner-profiles/{self.scanner.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_site_code_is_not_client_writable(self):
        resp = self._api_client(self.alice_token).post(
            '/api/v1/scanner-profiles/',
            {
                'manufacturer': str(self.scanner.manufacturer_id),
                'scanner_model': str(self.scanner.scanner_model_id),
                'detector_rows': '64',
                'year_of_installation': '2020',
                'site_code': 'S999',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['site_code'], 'S001')

    def test_same_institution_gui_list_shows_colleagues_scanner(self):
        gui_client = Client()
        gui_client.force_login(self.bob)
        resp = gui_client.get(reverse('scanner-profile-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.scanner, list(resp.context['scanner_profiles']))

    def test_different_institution_gui_list_hides_scanner(self):
        gui_client = Client()
        gui_client.force_login(self.carol)
        resp = gui_client.get(reverse('scanner-profile-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.scanner, list(resp.context['scanner_profiles']))

    def test_same_institution_can_edit_colleagues_scanner_via_gui(self):
        gui_client = Client()
        gui_client.force_login(self.bob)
        resp = gui_client.get(reverse('scanner-profile-edit', kwargs={'pk': str(self.scanner.pk)}))
        self.assertEqual(resp.status_code, 200)

    def test_different_institution_cannot_edit_scanner_via_gui(self):
        gui_client = Client()
        gui_client.force_login(self.carol)
        resp = gui_client.get(reverse('scanner-profile-edit', kwargs={'pk': str(self.scanner.pk)}))
        self.assertEqual(resp.status_code, 404)

    def test_different_institution_cannot_delete_scanner_via_gui(self):
        gui_client = Client()
        gui_client.force_login(self.carol)
        resp = gui_client.get(reverse('scanner-profile-delete', kwargs={'pk': str(self.scanner.pk)}))
        self.assertEqual(resp.status_code, 404)

    def test_superuser_sees_all_institutions_scanner(self):
        admin = User.objects.create_user('admin_scope', 'admin@example.com', 'pass12345', is_staff=True, is_superuser=True)
        admin_token, _ = Token.objects.get_or_create(user=admin)
        resp = self._api_client(admin_token).get(f'/api/v1/scanner-profiles/{self.scanner.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class ProtocolInstitutionScopingTests(TestCase):
    """CTProtocol API/GUI scoping mirrors CTScannerProfile."""

    def setUp(self):
        self.alice = _make_user_with_site_code('palice', 'S010')
        self.bob = _make_user_with_site_code('pbob', 'S010')
        self.carol = _make_user_with_site_code('pcarol', 'S020')

        self.scanner = _make_scanner(created_by='palice', site_code='S010')
        self.protocol = CTProtocol.objects.create(
            scanner=self.scanner, protocol_type='PEDIATRIC_HEAD',
            age_group='lt_3m', created_by='palice', site_code='S010',
        )

        self.alice_token, _ = Token.objects.get_or_create(user=self.alice)
        self.bob_token, _ = Token.objects.get_or_create(user=self.bob)
        self.carol_token, _ = Token.objects.get_or_create(user=self.carol)

    def _api_client(self, token):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        return client

    def test_same_institution_can_update_protocol(self):
        resp = self._api_client(self.bob_token).patch(
            f'/api/v1/protocols-api/{self.protocol.pk}/',
            {'protocol_name': 'Updated by bob'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_different_institution_cannot_access_protocol(self):
        resp = self._api_client(self.carol_token).get(f'/api/v1/protocols-api/{self.protocol.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_different_institution_cannot_delete_protocol(self):
        resp = self._api_client(self.carol_token).delete(f'/api/v1/protocols-api/{self.protocol.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(CTProtocol.objects.filter(pk=self.protocol.pk).exists())

    def test_same_institution_gui_detail_view_visible(self):
        gui_client = Client()
        gui_client.force_login(self.bob)
        resp = gui_client.get(reverse(
            'protocol-detail', kwargs={'protocol_type': 'PEDIATRIC_HEAD', 'pk': str(self.protocol.pk)}
        ))
        self.assertEqual(resp.status_code, 200)

    def test_different_institution_gui_detail_view_404s(self):
        gui_client = Client()
        gui_client.force_login(self.carol)
        resp = gui_client.get(reverse(
            'protocol-detail', kwargs={'protocol_type': 'PEDIATRIC_HEAD', 'pk': str(self.protocol.pk)}
        ))
        self.assertEqual(resp.status_code, 404)


class ExaminationInstitutionScopingTests(TestCase):
    """CTExamination GUI scoping — list and delete."""

    def setUp(self):
        self.alice = _make_user_with_site_code('ealice', 'S030')
        self.bob = _make_user_with_site_code('ebob', 'S030')
        self.carol = _make_user_with_site_code('ecarol', 'S040')

        self.scanner = _make_scanner(created_by='ealice', site_code='S030')
        self.exam = CTExamination.objects.create(
            scanner=self.scanner, anatomical_region='Head', clinical_indication='Trauma',
            patient_weight='12.5', patient_age=4, number_of_phases=1,
            ctdi_vol_per_phase=[3.0], dlp_per_phase=[50.0], image_quality='GOOD',
            created_by='ealice', site_code='S030',
        )

    def test_same_institution_sees_exam_in_list(self):
        client = Client()
        client.force_login(self.bob)
        resp = client.get(reverse('examination-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.exam, list(resp.context['examinations']))

    def test_different_institution_does_not_see_exam_in_list(self):
        client = Client()
        client.force_login(self.carol)
        resp = client.get(reverse('examination-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.exam, list(resp.context['examinations']))

    def test_different_institution_cannot_delete_exam(self):
        client = Client()
        client.force_login(self.carol)
        resp = client.post(reverse('examination-delete', kwargs={'pk': str(self.exam.pk)}))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(CTExamination.objects.filter(pk=self.exam.pk).exists())

    def test_same_institution_can_delete_colleagues_exam(self):
        client = Client()
        client.force_login(self.bob)
        resp = client.post(reverse('examination-delete', kwargs={'pk': str(self.exam.pk)}))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(CTExamination.objects.filter(pk=self.exam.pk).exists())


class UploadJobInstitutionScopingTests(TestCase):
    """UploadJob API scoping — list, detail, delete."""

    def setUp(self):
        self.alice = _make_user_with_site_code('ualice', 'S050')
        self.bob = _make_user_with_site_code('ubob', 'S050')
        self.carol = _make_user_with_site_code('ucarol', 'S060')

        self.job = UploadJob.objects.create(uploader_id='ualice', site_code='S050', status='PENDING')

        self.alice_token, _ = Token.objects.get_or_create(user=self.alice)
        self.bob_token, _ = Token.objects.get_or_create(user=self.bob)
        self.carol_token, _ = Token.objects.get_or_create(user=self.carol)

    def _api_client(self, token):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        return client

    def test_same_institution_can_view_colleagues_job(self):
        resp = self._api_client(self.bob_token).get(f'/api/v1/uploads/{self.job.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_different_institution_cannot_view_job(self):
        resp = self._api_client(self.carol_token).get(f'/api/v1/uploads/{self.job.id}/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_same_institution_sees_job_in_list(self):
        resp = self._api_client(self.bob_token).get('/api/v1/uploads/')
        job_ids = [j['id'] for j in resp.data['results']]
        self.assertIn(str(self.job.id), job_ids)

    def test_different_institution_does_not_see_job_in_list(self):
        resp = self._api_client(self.carol_token).get('/api/v1/uploads/')
        job_ids = [j['id'] for j in resp.data['results']]
        self.assertNotIn(str(self.job.id), job_ids)

    def test_same_institution_can_delete_colleagues_pending_job(self):
        resp = self._api_client(self.bob_token).delete(f'/api/v1/uploads/{self.job.id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_different_institution_cannot_delete_job(self):
        resp = self._api_client(self.carol_token).delete(f'/api/v1/uploads/{self.job.id}/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(UploadJob.objects.filter(id=self.job.id).exists())


class ProfileLessUserFallbackTests(TestCase):
    """Users with no UserProfile/site_code fall back to legacy owner-only visibility."""

    def setUp(self):
        self.user = User.objects.create_user('nosite', 'nosite@example.com', 'pass12345')
        self.other = User.objects.create_user('otherowner', 'other@example.com', 'pass12345')
        self.token, _ = Token.objects.get_or_create(user=self.user)

    def test_profile_less_user_only_sees_own_jobs(self):
        own_job = UploadJob.objects.create(uploader_id='nosite', status='PENDING')
        other_job = UploadJob.objects.create(uploader_id='otherowner', status='PENDING')

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        resp = client.get('/api/v1/uploads/')
        job_ids = [j['id'] for j in resp.data['results']]
        self.assertIn(str(own_job.id), job_ids)
        self.assertNotIn(str(other_job.id), job_ids)


class AdminUserCreationRequiresInstitutionTests(TestCase):
    """UserCreateAPIView must collect an institution and assign a site_code."""

    def setUp(self):
        self.admin = User.objects.create_user(
            'super_uc', 'super@example.com', 'pass12345', is_staff=True, is_superuser=True,
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def test_create_without_institution_rejected(self):
        resp = self.client.post(
            reverse('user-create-api'),
            data=json.dumps({'username': 'newbie', 'password': 'longpassword1'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('nstitution', resp.json()['error'])
        self.assertFalse(User.objects.filter(username='newbie').exists())

    def test_create_with_institution_assigns_site_code(self):
        resp = self.client.post(
            reverse('user-create-api'),
            data=json.dumps({
                'username': 'newbie2',
                'password': 'longpassword1',
                'institution': 'Brand New Hospital',
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data['institution'], 'Brand New Hospital')
        self.assertTrue(data['site_code'])

        user = User.objects.get(username='newbie2')
        self.assertEqual(user.profile.site_code, data['site_code'])

    def test_two_users_same_institution_share_site_code(self):
        resp1 = self.client.post(
            reverse('user-create-api'),
            data=json.dumps({
                'username': 'colleague1', 'password': 'longpassword1',
                'institution': 'Shared Hospital',
            }),
            content_type='application/json',
        )
        resp2 = self.client.post(
            reverse('user-create-api'),
            data=json.dumps({
                'username': 'colleague2', 'password': 'longpassword1',
                'institution': 'Shared Hospital',
            }),
            content_type='application/json',
        )
        self.assertEqual(resp1.json()['site_code'], resp2.json()['site_code'])
