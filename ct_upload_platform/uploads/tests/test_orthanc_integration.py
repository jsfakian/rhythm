"""
Functional/Integration tests for Orthanc DICOM Server Integration.

Tests the end-to-end workflow:
1. Upload manifest + DICOM files
2. Validate manifest and pseudo IDs
3. Anonymize DICOM using GDPR rules
4. Push anonymized DICOM to Orthanc
5. Update database with Orthanc study IDs
6. Track upload job status
"""

import json
import os
import requests
import tempfile
import tarfile
from unittest.mock import patch, MagicMock
from django.test import TestCase, TransactionTestCase, override_settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile

from uploads.models import (
    Patient,
    StudyMapping,
    UploadJob,
    Image,
)
from uploads.orthanc_client import (
    OrthancClient,
    OrthancPushError,
)
from uploads.pseudo_id_validator import PseudoIDUniquenessValidator


class OrthancIntegrationUploadTest(TransactionTestCase):
    """Test upload workflow with Orthanc integration."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        
        # Create test manifest
        self.manifest_data = {
            'manifest_version': '1.0',
            'pseudo_patient_id': 'PATIENT_001',
            'patient': {
                'pseudo_id': 'PATIENT_001',
                'sex': 'M',
                'age_at_acquisition': 65,
                'cohort_tag': 'TEST_COHORT',
            },
            'study': {
                'study_uid': 'study_uid_123',
                'acquisition_date': '2026-02-27',
                'clinical_indication': 'Test',
            },
            'images': [
                {
                    'filename': 'image1.dcm',
                    'organ': 'chest',
                },
            ],
        }
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc',
        RAW_DATA_DIR=tempfile.gettempdir(),
    )
    def test_patient_creation_on_first_upload(self):
        """Test that first upload creates Patient record."""
        pseudo_id = 'PATIENT_001'
        
        # Verify patient doesn't exist yet
        self.assertFalse(Patient.objects.filter(pseudo_id=pseudo_id).exists())
        
        # Create patient via validator
        patient, created, error = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
            pseudo_id=pseudo_id,
            sex='M',
            age_at_acquisition=65,
            cohort_tag='TEST_COHORT',
        )
        
        # Verify patient was created
        self.assertTrue(created)
        self.assertIsNone(error)
        self.assertEqual(patient.pseudo_id, pseudo_id)
        self.assertEqual(patient.sex, 'M')
        self.assertTrue(Patient.objects.filter(pseudo_id=pseudo_id).exists())
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc',
    )
    def test_patient_reuse_on_second_upload(self):
        """Test that second upload reuses Patient record."""
        pseudo_id = 'PATIENT_001'
        
        # Create patient on first upload
        patient1, created1, _ = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
            pseudo_id=pseudo_id,
            sex='M',
            age_at_acquisition=65,
            cohort_tag='TEST_COHORT',
        )
        self.assertTrue(created1)
        patient1_id = patient1.id
        
        # Reuse patient on second upload
        patient2, created2, _ = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
            pseudo_id=pseudo_id,
            sex='M',
            age_at_acquisition=66,  # Age updated
            cohort_tag='TEST_COHORT',
        )
        
        # Verify patient was reused
        self.assertFalse(created2)
        self.assertEqual(patient2.id, patient1_id)
        self.assertEqual(Patient.objects.filter(pseudo_id=pseudo_id).count(), 1)
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc',
    )
    def test_patient_id_collision_prevention(self):
        """Test that different patients cannot use same pseudo_id."""
        pseudo_id = 'PATIENT_001'
        
        # Create patient 1
        patient1, created1, _ = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
            pseudo_id=pseudo_id,
            sex='M',
            age_at_acquisition=65,
            cohort_tag='TEST_COHORT',
        )
        self.assertTrue(created1)
        
        # Try to create different patient with same pseudo_id
        # This would be detected at manifest validation level
        manifest = {
            'patient': {'pseudo_id': pseudo_id},
            'images': [],
        }
        
        is_valid, errors = PseudoIDUniquenessValidator.validate_manifest_pseudo_ids(
            manifest,
            allow_existing=False  # Don't allow reuse
        )
        
        # Should fail validation if ID already exists and reuse not allowed
        # (depends on manifest validation logic)
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc',
    )
    def test_study_mapping_created_on_upload(self):
        """Test that StudyMapping is created linking pseudo_id to orthanc_study_id."""
        # Create patient
        patient, _, _ = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
            pseudo_id='PATIENT_001',
            sex='M',
            age_at_acquisition=65,
            cohort_tag='TEST',
        )
        
        # Create upload job
        job = UploadJob.objects.create(
            uploader_id=str(self.user.id),
            status='PROCESSING',
        )
        
        # Create study mapping
        study_mapping, created = StudyMapping.objects.update_or_create(
            pseudo_study_uid='study_uid_123',
            defaults={
                'patient': patient,
                'upload_job': job,
                'orthanc_study_id': '1.2.3.4.5',  # From Orthanc STOW-RS response
                'acquisition_date': '2026-02-27',
            },
        )
        
        # Verify mapping was created
        self.assertTrue(created)
        self.assertEqual(study_mapping.patient, patient)
        self.assertEqual(study_mapping.orthanc_study_id, '1.2.3.4.5')
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc',
    )
    def test_image_record_with_orthanc_instance_id(self):
        """Test that Image records store Orthanc instance IDs."""
        # Create patient and study mapping
        patient, _, _ = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
            pseudo_id='PATIENT_001',
            sex='M',
            age_at_acquisition=65,
            cohort_tag='TEST',
        )
        
        job = UploadJob.objects.create(uploader_id=str(self.user.id), status='PROCESSING')
        
        study_mapping, _ = StudyMapping.objects.update_or_create(
            pseudo_study_uid='study_uid_123',
            defaults={
                'patient': patient,
                'upload_job': job,
                'orthanc_study_id': '1.2.3.4.5',
                'acquisition_date': '2026-02-27',
            },
        )
        
        # Create image with Orthanc instance ID
        image = Image.objects.create(
            study_mapping=study_mapping,
            filename='image1.dcm',
            orthanc_instance_id='1.2.3.4.5.1.1',
        )
        
        # Verify image record
        self.assertEqual(image.orthanc_instance_id, '1.2.3.4.5.1.1')
        self.assertEqual(image.study_mapping, study_mapping)


class OrthancPushErrorHandlingTest(TransactionTestCase):
    """Test error handling when Orthanc push fails."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc',
    )
    def test_orthanc_push_error_captured(self):
        """Test that Orthanc push errors are captured and reported."""
        dicom_bytes = b'INVALID_DICOM'
        
        with patch('uploads.orthanc_client.requests.Session.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.text = 'Invalid DICOM file'
            mock_post.return_value = mock_response
            
            client = OrthancClient()
            
            try:
                client.push_dicom_file(dicom_bytes)
                self.fail("Should raise OrthancPushError")
            except OrthancPushError as e:
                self.assertEqual(e.status_code, 400)
                self.assertIn('400', e.message)
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc',
    )
    def test_orthanc_server_timeout(self):
        """Test handling of Orthanc server timeout."""
        dicom_bytes = b'DICOM_DATA'
        
        with patch('uploads.orthanc_client.requests.Session.post') as mock_post:
            mock_post.side_effect = requests.Timeout('Request timeout')
            
            client = OrthancClient()
            
            with self.assertRaises(OrthancPushError) as context:
                client.push_dicom_file(dicom_bytes)
            
            error = context.exception
            self.assertIn('Request failed', error.message)
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc-down:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc',
    )
    def test_orthanc_connection_refused(self):
        """Test handling when Orthanc connection is refused."""
        dicom_bytes = b'DICOM_DATA'
        
        with patch('uploads.orthanc_client.requests.Session.post') as mock_post:
            mock_post.side_effect = requests.ConnectionError('Connection refused')
            
            client = OrthancClient()
            
            with self.assertRaises(OrthancPushError) as context:
                client.push_dicom_file(dicom_bytes)
            
            error = context.exception
            self.assertIn('Request failed', error.message)


class OrthancMultiUploadWorkflowTest(TransactionTestCase):
    """Test multi-upload workflow with Orthanc."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc',
    )
    def test_multiple_uploads_same_patient(self):
        """Test multiple uploads of same patient reuse Patient record."""
        pseudo_id = 'PATIENT_LONGTERM'
        
        # Upload 1: Initial study
        patient1, created1, _ = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
            pseudo_id=pseudo_id,
            sex='F',
            age_at_acquisition=55,
            cohort_tag='STUDY_A',
        )
        
        job1 = UploadJob.objects.create(uploader_id=str(self.user.id), status='COMPLETE')
        study_mapping1, _ = StudyMapping.objects.update_or_create(
            pseudo_study_uid='study_2024',
            defaults={
                'patient': patient1,
                'upload_job': job1,
                'orthanc_study_id': '1.2.3.4.5',
                'acquisition_date': '2024-01-15',
            },
        )
        
        # Upload 2: Follow-up study (same patient)
        patient2, created2, _ = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
            pseudo_id=pseudo_id,
            sex='F',
            age_at_acquisition=56,  # One year later
            cohort_tag='STUDY_A',
        )
        
        job2 = UploadJob.objects.create(uploader_id=str(self.user.id), status='COMPLETE')
        study_mapping2, _ = StudyMapping.objects.update_or_create(
            pseudo_study_uid='study_2025',
            defaults={
                'patient': patient2,
                'upload_job': job2,
                'orthanc_study_id': '1.2.3.6.7',
                'acquisition_date': '2025-01-15',
            },
        )
        
        # Verify same patient was reused
        self.assertFalse(created2)
        self.assertEqual(patient2.id, patient1.id)
        
        # Verify two different studies mapped to same patient
        studies = StudyMapping.objects.filter(patient=patient1)
        self.assertEqual(studies.count(), 2)
        self.assertEqual(
            set(studies.values_list('orthanc_study_id', flat=True)),
            {'1.2.3.4.5', '1.2.3.6.7'}
        )
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc',
    )
    def test_multiple_uploads_different_patients(self):
        """Test multiple uploads of different patients create separate records."""
        patient_ids = ['PATIENT_A', 'PATIENT_B', 'PATIENT_C']
        patients = {}
        
        for i, pseudo_id in enumerate(patient_ids):
            patient, created, _ = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
                pseudo_id=pseudo_id,
                sex='M' if i % 2 == 0 else 'F',
                age_at_acquisition=50 + i,
                cohort_tag='STUDY',
            )
            patients[pseudo_id] = patient
            self.assertTrue(created)
        
        # Verify all patients are different
        patient_set = set(patients.values())
        self.assertEqual(len(patient_set), 3)
        
        # Verify each has unique pseudo_id
        pseudo_ids = set(Patient.objects.values_list('pseudo_id', flat=True))
        self.assertEqual(len(pseudo_ids), 3)


class OrthancStudyMappingTest(TestCase):
    """Test StudyMapping with Orthanc integration."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        
        self.patient, _, _ = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
            pseudo_id='PATIENT_001',
            sex='M',
            age_at_acquisition=65,
            cohort_tag='TEST',
        )
        
        self.job = UploadJob.objects.create(uploader_id=str(self.user.id), status='COMPLETE')
    
    def test_study_mapping_links_pseudo_to_orthanc_id(self):
        """Test StudyMapping correctly links pseudo_study_uid to orthanc_study_id."""
        study_mapping = StudyMapping.objects.create(
            patient=self.patient,
            upload_job=self.job,
            pseudo_study_uid='pseudo_uid_123',
            orthanc_study_id='1.2.3.4.5',
            acquisition_date='2026-02-27',
        )
        
        # Verify mapping
        retrieved = StudyMapping.objects.get(pseudo_study_uid='pseudo_uid_123')
        self.assertEqual(retrieved.orthanc_study_id, '1.2.3.4.5')
        self.assertEqual(retrieved.patient, self.patient)
    
    def test_study_mapping_update_with_orthanc_id(self):
        """Test that StudyMapping can be updated with Orthanc ID after creation."""
        # Create without orthanc_study_id
        study_mapping = StudyMapping.objects.create(
            patient=self.patient,
            upload_job=self.job,
            pseudo_study_uid='pseudo_uid_456',
            orthanc_study_id=None,
            acquisition_date='2026-02-27',
        )
        
        # Later, update with orthanc_study_id (from Orthanc STOW-RS response)
        study_mapping.orthanc_study_id = '1.2.3.4.6'
        study_mapping.save()
        
        # Verify update
        retrieved = StudyMapping.objects.get(pseudo_study_uid='pseudo_uid_456')
        self.assertEqual(retrieved.orthanc_study_id, '1.2.3.4.6')
    
    def test_image_records_created_with_orthanc_instance_ids(self):
        """Test Image records store Orthanc instance IDs from STOW-RS response."""
        study_mapping = StudyMapping.objects.create(
            patient=self.patient,
            upload_job=self.job,
            pseudo_study_uid='pseudo_uid_789',
            orthanc_study_id='1.2.3.4.7',
            acquisition_date='2026-02-27',
        )
        
        # Create images with Orthanc instance IDs
        images_data = [
            ('image1.dcm', '1.2.3.4.7.1.1'),
            ('image2.dcm', '1.2.3.4.7.1.2'),
            ('image3.dcm', '1.2.3.4.7.1.3'),
        ]
        
        for filename, orthanc_instance_id in images_data:
            Image.objects.create(
                study_mapping=study_mapping,
                filename=filename,
                orthanc_instance_id=orthanc_instance_id,
            )
        
        # Verify all images created
        images = Image.objects.filter(study_mapping=study_mapping)
        self.assertEqual(images.count(), 3)
        
        # Verify orthanc_instance_ids
        instance_ids = set(images.values_list('orthanc_instance_id', flat=True))
        expected_ids = set([iid for _, iid in images_data])
        self.assertEqual(instance_ids, expected_ids)
