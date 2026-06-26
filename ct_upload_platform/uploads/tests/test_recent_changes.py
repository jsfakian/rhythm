"""
Manual verification tests for all recent changes:

1. Signup: new UserProfile fields (institution, department, role, terms, site_code)
2. UserProfile.assign_site_code: auto-assignment and reuse logic
3. CTExamination: new fields (repository_study_id, contrast, protocol_type, examination_group)
4. ExaminationSaveAPIView: protocol_id optional, repository_study_id generated on save
5. populate_protocol_choices: new manufacturer field options and MaModulationInputSpecs
"""

import json

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, Client
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from uploads.models import (
    CTExamination,
    CTManufacturer,
    CTManufacturerFieldOption,
    CTScannerModel,
    CTScannerProfile,
    MaModulationInputSpec,
    UserProfile,
)

SIGNUP_URL = '/api/v1/auth/signup/'
EXAM_SAVE_URL = '/examinations/api/save/'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_signup(**overrides):
    base = {
        'username': 'testuser',
        'email': 'test@example.com',
        'password': 'StrongPass99!',
        'password2': 'StrongPass99!',
        'institution': 'University Hospital Athens',
        'professional_role': 'radiologist',
        'terms_accepted': True,
    }
    base.update(overrides)
    return base


def _make_scanner(username='testuser'):
    mfr, _ = CTManufacturer.objects.get_or_create(name='GE HealthCare', defaults={'sort_order': 1})
    mdl, _ = CTScannerModel.objects.get_or_create(
        manufacturer=mfr, name='Revolution CT Test', defaults={'sort_order': 0}
    )
    return CTScannerProfile.objects.create(
        manufacturer=mfr, scanner_model=mdl,
        detector_rows='64', year_of_installation='2020',
        created_by=username,
    )


# ===========================================================================
# 1. Signup with new profile fields
# ===========================================================================

class SignupNewFieldsTest(TestCase):
    """Signup API now requires institution, professional_role, and terms_accepted."""

    def setUp(self):
        self.client = APIClient()

    # --- happy path ---

    def test_signup_with_full_profile_creates_user_and_profile(self):
        resp = self.client.post(SIGNUP_URL, _valid_signup(), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username='testuser')
        self.assertTrue(hasattr(user, 'profile'))
        self.assertEqual(user.profile.institution, 'University Hospital Athens')
        self.assertEqual(user.profile.professional_role, 'radiologist')
        self.assertTrue(user.profile.terms_accepted)
        self.assertIsNotNone(user.profile.terms_accepted_at)

    def test_signup_stores_department_when_provided(self):
        resp = self.client.post(
            SIGNUP_URL,
            _valid_signup(department='Radiology Department'),
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.get(username='testuser').profile.department, 'Radiology Department')

    def test_signup_department_optional(self):
        payload = _valid_signup()
        payload.pop('department', None)
        resp = self.client.post(SIGNUP_URL, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.get(username='testuser').profile.department, '')

    def test_signup_role_other_stores_free_text(self):
        resp = self.client.post(
            SIGNUP_URL,
            _valid_signup(professional_role='other', professional_role_other='CT Application Specialist'),
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        profile = User.objects.get(username='testuser').profile
        self.assertEqual(profile.professional_role, 'other')
        self.assertEqual(profile.professional_role_other, 'CT Application Specialist')

    def test_signup_assigns_site_code_automatically(self):
        resp = self.client.post(SIGNUP_URL, _valid_signup(), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        site_code = User.objects.get(username='testuser').profile.site_code
        self.assertTrue(site_code.startswith('S'), f"Expected S-code, got {site_code!r}")
        self.assertTrue(site_code[1:].isdigit(), f"Non-numeric suffix: {site_code!r}")

    # --- validation errors ---

    def test_signup_without_institution_rejected(self):
        payload = _valid_signup()
        del payload['institution']
        resp = self.client.post(SIGNUP_URL, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('institution', resp.json().get('details', {}))

    def test_signup_without_professional_role_rejected(self):
        payload = _valid_signup()
        del payload['professional_role']
        resp = self.client.post(SIGNUP_URL, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_signup_terms_not_accepted_rejected(self):
        resp = self.client.post(
            SIGNUP_URL, _valid_signup(terms_accepted=False), format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        details = resp.json().get('details', {})
        self.assertIn('terms_accepted', details)

    def test_signup_role_other_without_text_rejected(self):
        resp = self.client.post(
            SIGNUP_URL,
            _valid_signup(professional_role='other', professional_role_other=''),
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_signup_all_seven_role_choices_accepted(self):
        roles = [
            'radiologist', 'medical_physicist', 'radiographer',
            'pacs_it', 'research_coordinator', 'principal_investigator', 'dpo',
        ]
        for i, role in enumerate(roles):
            resp = self.client.post(
                SIGNUP_URL,
                _valid_signup(username=f'u{i}', email=f'u{i}@x.com', professional_role=role),
                format='json',
            )
            self.assertEqual(
                resp.status_code, status.HTTP_201_CREATED,
                f"Role {role!r} was rejected: {resp.json()}",
            )


# ===========================================================================
# 2. UserProfile.assign_site_code auto-assignment
# ===========================================================================

class SiteCodeAssignmentTest(TestCase):
    """UserProfile.assign_site_code must mint sequential codes per institution."""

    def _make_profile(self, institution, username='u'):
        user = User.objects.create_user(username, f'{username}@x.com', 'pass')
        code = UserProfile.assign_site_code(institution)
        UserProfile.objects.create(
            user=user, institution=institution,
            professional_role='radiologist', terms_accepted=True,
            site_code=code,
        )
        return code

    def test_first_institution_gets_s001(self):
        code = self._make_profile('Hospital Alpha', 'u1')
        self.assertEqual(code, 'S001')

    def test_second_institution_gets_s002(self):
        self._make_profile('Hospital Alpha', 'u1')
        code = self._make_profile('Hospital Beta', 'u2')
        self.assertEqual(code, 'S002')

    def test_third_institution_gets_s003(self):
        self._make_profile('Hospital Alpha', 'u1')
        self._make_profile('Hospital Beta', 'u2')
        code = self._make_profile('Hospital Gamma', 'u3')
        self.assertEqual(code, 'S003')

    def test_same_institution_reuses_existing_code(self):
        code1 = self._make_profile('University Hospital Athens', 'u1')
        code2 = self._make_profile('University Hospital Athens', 'u2')
        self.assertEqual(code1, code2)

    def test_same_institution_case_insensitive(self):
        code1 = self._make_profile('University Hospital Athens', 'u1')
        code2 = UserProfile.assign_site_code('university hospital athens')
        self.assertEqual(code1, code2)

    def test_same_institution_with_leading_trailing_spaces(self):
        code1 = self._make_profile('Hospital Alpha', 'u1')
        code2 = UserProfile.assign_site_code('  Hospital Alpha  ')
        self.assertEqual(code1, code2)

    def test_different_institutions_get_different_codes(self):
        code1 = self._make_profile('Hospital A', 'u1')
        code2 = self._make_profile('Hospital B', 'u2')
        self.assertNotEqual(code1, code2)

    def test_code_format_is_s_plus_three_digits(self):
        code = self._make_profile('New Hospital', 'u1')
        self.assertRegex(code, r'^S\d{3}$')

    def test_multiple_users_same_institution_all_have_same_code(self):
        self.client = APIClient()
        for i in range(3):
            resp = self.client.post(
                SIGNUP_URL,
                _valid_signup(
                    username=f'staff{i}',
                    email=f'staff{i}@hospital.com',
                    institution='Athens General Hospital',
                ),
                format='json',
            )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        codes = list(
            UserProfile.objects
            .filter(institution__iexact='Athens General Hospital')
            .values_list('site_code', flat=True)
        )
        self.assertEqual(len(set(codes)), 1, f"Got different codes: {codes}")


# ===========================================================================
# 3. CTExamination new model fields
# ===========================================================================

class CTExaminationNewFieldsTest(TestCase):
    """repository_study_id, contrast, protocol_type, examination_group fields."""

    def test_repository_study_id_field_exists_and_defaults_blank(self):
        exam = CTExamination.objects.create(
            anatomical_region='Head', clinical_indication='Trauma',
            number_of_phases=1, ctdi_vol_per_phase=[3.0], dlp_per_phase=[50.0],
        )
        self.assertEqual(exam.rhythm_pseudo_id, '')

    def test_repository_study_id_stored_and_retrieved(self):
        pid = 'RHY-S001-HEADTRAUMA-NC-PH-G4-000001'
        exam = CTExamination.objects.create(
            rhythm_pseudo_id=pid,
            anatomical_region='Head', clinical_indication='Trauma',
            number_of_phases=1, ctdi_vol_per_phase=[3.0], dlp_per_phase=[50.0],
        )
        exam.refresh_from_db()
        self.assertEqual(exam.rhythm_pseudo_id, pid)

    def test_contrast_field_stored(self):
        exam = CTExamination.objects.create(
            contrast='Non-contrast',
            number_of_phases=1, ctdi_vol_per_phase=[3.0], dlp_per_phase=[50.0],
        )
        exam.refresh_from_db()
        self.assertEqual(exam.contrast, 'Non-contrast')

    def test_protocol_type_field_stored(self):
        exam = CTExamination.objects.create(
            protocol_type='PEDIATRIC_HEAD',
            number_of_phases=1, ctdi_vol_per_phase=[3.0], dlp_per_phase=[50.0],
        )
        exam.refresh_from_db()
        self.assertEqual(exam.protocol_type, 'PEDIATRIC_HEAD')

    def test_examination_group_field_stored(self):
        exam = CTExamination.objects.create(
            examination_group='Group 4 – Childhood',
            number_of_phases=1, ctdi_vol_per_phase=[3.0], dlp_per_phase=[50.0],
        )
        exam.refresh_from_db()
        self.assertEqual(exam.examination_group, 'Group 4 – Childhood')

    def test_all_protocol_type_choices_accepted(self):
        for ptype, _ in CTExamination.PROTOCOL_TYPE_CHOICES:
            exam = CTExamination.objects.create(
                protocol_type=ptype,
                number_of_phases=1, ctdi_vol_per_phase=[3.0], dlp_per_phase=[50.0],
            )
            exam.refresh_from_db()
            self.assertEqual(exam.protocol_type, ptype)


# ===========================================================================
# 4. ExaminationSaveAPIView
# ===========================================================================

class ExaminationSaveAPIViewTest(TestCase):
    """ExaminationSaveAPIView: protocol_id optional, repository_study_id generated."""

    def setUp(self):
        self.user = User.objects.create_user('examuser', 'exam@x.com', 'pass')
        UserProfile.objects.create(
            user=self.user, institution='Test Hospital',
            professional_role='radiologist', terms_accepted=True,
            site_code='S099',
        )
        # ExaminationSaveAPIView uses LoginRequiredMixin (Django session auth)
        self.client = Client()
        self.client.force_login(self.user)
        self.scanner = _make_scanner('examuser')
        # Ensure clinical indication rows exist
        from uploads.models import ClinicalIndicationRow
        ClinicalIndicationRow.objects.get_or_create(
            anatomical_region='Head',
            clinical_indication='Trauma',
            defaults={'iv_contrast': 'Non-contrast', 'sort_order': 0, 'is_active': True},
        )

    def _valid_payload(self, **overrides):
        base = {
            'scanner_id': str(self.scanner.pk),
            'anatomical_region': 'Head',
            'clinical_indication': 'Trauma',
            'contrast': 'Non-contrast',
            'protocol_type': 'PEDIATRIC_HEAD',
            'examination_group': 'Group 4 – Childhood',
            'patient_weight': '12.5',
            'patient_age': 6,
            'number_of_phases': 1,
            'ctdi_vol_per_phase': [3.5],
            'dlp_per_phase': [55.0],
            'image_quality': 'GOOD',
        }
        base.update(overrides)
        return base

    def _post(self, payload):
        return self.client.post(
            EXAM_SAVE_URL, json.dumps(payload), content_type='application/json'
        )

    # --- happy path ---

    def test_save_creates_examination_record(self):
        resp = self._post(self._valid_payload())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'created')
        self.assertEqual(CTExamination.objects.count(), 1)

    def test_save_without_protocol_id_succeeds(self):
        """protocol_id is now optional."""
        payload = self._valid_payload()
        payload.pop('protocol_id', None)
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        exam = CTExamination.objects.get()
        self.assertIsNone(exam.protocol)

    def test_save_generates_repository_study_id(self):
        resp = self._post(self._valid_payload())
        data = resp.json()
        self.assertIn('repository_study_id', data)
        pid = data['repository_study_id']
        self.assertTrue(pid.startswith('RHY-'), f"Unexpected ID format: {pid!r}")

    def test_repository_study_id_stored_on_examination(self):
        resp = self._post(self._valid_payload())
        exam = CTExamination.objects.get()
        self.assertEqual(exam.rhythm_pseudo_id, resp.json()['repository_study_id'])

    def test_rhythm_id_contains_site_code(self):
        resp = self._post(self._valid_payload())
        self.assertIn('S099', resp.json()['repository_study_id'])

    def test_rhythm_id_contains_indication_code(self):
        resp = self._post(self._valid_payload())
        self.assertIn('HEADTRAUMA', resp.json()['repository_study_id'])

    def test_rhythm_id_contains_contrast_code(self):
        resp = self._post(self._valid_payload())
        self.assertIn('-NC-', resp.json()['repository_study_id'])

    def test_rhythm_id_contains_group_code(self):
        resp = self._post(self._valid_payload())
        self.assertIn('PH-G4', resp.json()['repository_study_id'])

    def test_sequence_increments_for_same_prefix(self):
        r1 = self._post(self._valid_payload())
        r2 = self._post(self._valid_payload())
        id1 = r1.json()['repository_study_id']
        id2 = r2.json()['repository_study_id']
        self.assertNotEqual(id1, id2)
        seq1 = int(id1.rsplit('-', 1)[-1])
        seq2 = int(id2.rsplit('-', 1)[-1])
        self.assertEqual(seq2 - seq1, 1)

    def test_contrast_stored_on_examination(self):
        self._post(self._valid_payload())
        exam = CTExamination.objects.get()
        self.assertEqual(exam.contrast, 'Non-contrast')

    def test_protocol_type_stored_on_examination(self):
        self._post(self._valid_payload())
        exam = CTExamination.objects.get()
        self.assertEqual(exam.protocol_type, 'PEDIATRIC_HEAD')

    def test_examination_group_stored_on_examination(self):
        self._post(self._valid_payload())
        exam = CTExamination.objects.get()
        self.assertEqual(exam.examination_group, 'Group 4 – Childhood')

    # --- validation errors ---

    def test_missing_protocol_type_rejected(self):
        payload = self._valid_payload()
        del payload['protocol_type']
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Protocol type', resp.json()['error'])

    def test_missing_examination_group_rejected(self):
        payload = self._valid_payload()
        del payload['examination_group']
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Examination group', resp.json()['error'])

    def test_missing_scanner_rejected(self):
        payload = self._valid_payload()
        del payload['scanner_id']
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 400)

    def test_unauthenticated_request_rejected(self):
        self.client.logout()
        resp = self._post(self._valid_payload())
        self.assertIn(resp.status_code, [302, 401, 403])

    def test_young_adult_group_code_in_id(self):
        resp = self._post(self._valid_payload(
            protocol_type='YOUNG_ADULT',
            examination_group='Group 6 – Young Adulthood',
        ))
        self.assertIn('YA-G6', resp.json()['repository_study_id'])

    def test_pediatric_body_group_code_in_id(self):
        resp = self._post(self._valid_payload(
            protocol_type='PEDIATRIC_BODY',
            examination_group='Group 3 – Childhood',
        ))
        self.assertIn('PB-G3', resp.json()['repository_study_id'])


# ===========================================================================
# 5. populate_protocol_choices: new manufacturer field options
# ===========================================================================

class PopulateProtocolChoicesNewManufacturersTest(TestCase):
    """New manufacturers must get their auto_kvp and auto_ma field options seeded."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command('populate_protocol_choices', verbosity=0)

    def _kvp_options(self, mfr_name):
        return list(
            CTManufacturerFieldOption.objects
            .filter(manufacturer__name=mfr_name, field_key='auto_kvp_selection')
            .values_list('value', flat=True)
        )

    def _ma_options(self, mfr_name):
        return list(
            CTManufacturerFieldOption.objects
            .filter(manufacturer__name=mfr_name, field_key='auto_ma_modulation')
            .values_list('value', flat=True)
        )

    # Fujifilm / Hitachi
    def test_fujifilm_kvp_options_seeded(self):
        opts = self._kvp_options('Fujifilm / Hitachi')
        self.assertIn('Auto kV', opts)
        self.assertIn('Off', opts)

    def test_fujifilm_ma_options_seeded(self):
        opts = self._ma_options('Fujifilm / Hitachi')
        self.assertIn('Intelli EC', opts)
        self.assertIn('Intelli EC Plus', opts)

    # MinFound Medical
    def test_minfound_kvp_options_seeded(self):
        opts = self._kvp_options('MinFound Medical')
        self.assertIn('Off', opts)
        self.assertIn('Not Available', opts)

    def test_minfound_ma_options_seeded(self):
        opts = self._ma_options('MinFound Medical')
        self.assertIn('imA Intelligent mA Modulation', opts)
        self.assertIn('imA Intelligent Dose Control', opts)

    # Neusoft Medical
    def test_neusoft_kvp_options_seeded(self):
        opts = self._kvp_options('Neusoft Medical')
        self.assertIn('AutoKV – Soft Tissue', opts)
        self.assertIn('AutoKV – Bone', opts)
        self.assertIn('AutoKV – Patient Size', opts)

    def test_neusoft_ma_options_seeded(self):
        opts = self._ma_options('Neusoft Medical')
        self.assertIn('DoseRight', opts)
        self.assertIn('DoseSave Level', opts)

    # Samsung NeuroLogica
    def test_samsung_kvp_options_seeded(self):
        opts = self._kvp_options('Samsung NeuroLogica')
        self.assertIn('Auto kV', opts)
        self.assertIn('Off', opts)

    def test_samsung_ma_options_seeded(self):
        opts = self._ma_options('Samsung NeuroLogica')
        self.assertIn('AEC', opts)

    # United Imaging
    def test_united_imaging_kvp_options_seeded(self):
        opts = self._kvp_options('United Imaging')
        self.assertIn('Auto kV', opts)
        self.assertIn('Off', opts)

    def test_united_imaging_ma_options_seeded(self):
        opts = self._ma_options('United Imaging')
        self.assertIn('uDose 3D Dose Modulation', opts)
        self.assertIn('Auto ALARA mA', opts)

    # Pre-existing manufacturers still intact
    def test_canon_still_has_kvp_options(self):
        opts = self._kvp_options('Canon Medical')
        self.assertIn('Sure kV', opts)

    def test_siemens_still_has_ma_options(self):
        opts = self._ma_options('Siemens Healthineers')
        self.assertIn('CareDose4D', opts)

    # New MaModulationInputSpecs
    def test_intelli_ec_input_spec_seeded(self):
        spec = MaModulationInputSpec.objects.filter(ma_modulation_value='Intelli EC').first()
        self.assertIsNotNone(spec)
        self.assertIn('Noise SD target', spec.input_labels)
        self.assertIn('Min mA', spec.input_labels)
        self.assertIn('Max mA', spec.input_labels)

    def test_intelli_ec_plus_input_spec_seeded(self):
        spec = MaModulationInputSpec.objects.filter(ma_modulation_value='Intelli EC Plus').first()
        self.assertIsNotNone(spec)
        self.assertIn('Noise SD target', spec.input_labels)

    def test_ima_modulation_input_spec_seeded(self):
        spec = MaModulationInputSpec.objects.filter(
            ma_modulation_value='imA Intelligent mA Modulation'
        ).first()
        self.assertIsNotNone(spec)
        self.assertIn('min mA', spec.input_labels)

    def test_dossave_level_input_spec_seeded(self):
        spec = MaModulationInputSpec.objects.filter(ma_modulation_value='DoseSave Level').first()
        self.assertIsNotNone(spec)
        self.assertIn('DoseSave Level', spec.input_labels)
        self.assertIn('min mA', spec.input_labels)

    def test_aec_input_spec_seeded(self):
        spec = MaModulationInputSpec.objects.filter(ma_modulation_value='AEC').first()
        self.assertIsNotNone(spec)
        self.assertIn('Desired noise level', spec.input_labels)

    def test_udose_3d_input_spec_seeded(self):
        spec = MaModulationInputSpec.objects.filter(ma_modulation_value='uDose 3D').first()
        self.assertIsNotNone(spec)
        self.assertIn('min mA', spec.input_labels)

    def test_auto_alara_input_spec_seeded(self):
        spec = MaModulationInputSpec.objects.filter(ma_modulation_value='Auto ALARA mA').first()
        self.assertIsNotNone(spec)
        self.assertIn('min mA', spec.input_labels)

    def test_idempotent_second_run_does_not_duplicate(self):
        call_command('populate_protocol_choices', verbosity=0)
        count = CTManufacturerFieldOption.objects.filter(
            manufacturer__name='Fujifilm / Hitachi', field_key='auto_kvp_selection', value='Auto kV'
        ).count()
        self.assertEqual(count, 1)


# ===========================================================================
# 6. repository_study_id.py pure-logic sanity checks
# ===========================================================================

class RhythmPseudoIdLogicTest(TestCase):
    """Verify the helper functions in repository_study_id.py."""

    def setUp(self):
        from uploads.repository_study_id import (
            INDICATION_CODES,
            CONTRAST_CODES,
            get_patient_group_code,
            is_repository_study_id,
        )
        self.INDICATION_CODES = INDICATION_CODES
        self.CONTRAST_CODES = CONTRAST_CODES
        self.get_group = get_patient_group_code
        self.is_valid = is_repository_study_id

    def test_all_six_mono_indications_have_codes(self):
        expected_keys = [
            'Head / Trauma',
            'Mastoid bone/Inner Ear / Hearing loss; congenital malformations, infection, cholesteatoma, cochlear implants',
            'Chest / Complicated and fungal infections',
            (
                'Chest/HRCT (Inspiration/Expiration) / Interstitial lung diseases, small airways disease, '
                'cystic fibrosis, asthma, primary ciliary dyskinesia, chronic lung disease of prematurity'
            ),
            'Abdomen / Acute abdomen',
            'Neck-Chest-Abdomen / Lymphoma',
        ]
        for key in expected_keys:
            self.assertIn(key, self.INDICATION_CODES, f"Missing INDICATION_CODE for: {key!r}")

    def test_contrast_codes_cover_all_row_values(self):
        for val in ('Non-contrast', 'Contrast-enhanced', 'Non-contrast, Contrast-enhanced'):
            self.assertIn(val, self.CONTRAST_CODES)

    def test_pediatric_head_group_codes(self):
        for num, expected in [('1', 'PH-G1'), ('2', 'PH-G2'), ('3', 'PH-G3'), ('4', 'PH-G4')]:
            code = self.get_group('PEDIATRIC_HEAD', f'Group {num} – something')
            self.assertEqual(code, expected)

    def test_pediatric_body_group_codes(self):
        for num in range(1, 6):
            code = self.get_group('PEDIATRIC_BODY', f'Group {num} – something')
            self.assertEqual(code, f'PB-G{num}')

    def test_young_adult_group_code(self):
        code = self.get_group('YOUNG_ADULT', 'Group 6 – Young Adulthood')
        self.assertEqual(code, 'YA-G6')

    def test_is_repository_study_id_valid(self):
        self.assertTrue(self.is_valid('RHY-S001-HEADTRAUMA-NC-PH-G4-000123'))
        self.assertTrue(self.is_valid('RHY-S099-LYMPHOMA-CE-YA-G6-000001'))

    def test_is_repository_study_id_rejects_malformed(self):
        self.assertFalse(self.is_valid(''))
        self.assertFalse(self.is_valid('S001-HEADTRAUMA-NC-PH-G4-000001'))
        self.assertFalse(self.is_valid('RHY-S001-HEADTRAUMA-NC-PH-G4'))
        self.assertFalse(self.is_valid('RHY-S001-HEADTRAUMA-NC-PH-G4-ABC'))
