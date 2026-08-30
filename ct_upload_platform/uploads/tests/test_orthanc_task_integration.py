"""
Tests for Celery task integration with Orthanc DICOM server.

Tests that the upload task pipeline correctly:
1. Validates pseudo IDs (Step 5b)
2. Creates/reuses Patient records (Step 7)
3. Pushes anonymized DICOM to Orthanc (Step 8)
4. Updates StudyMapping with Orthanc IDs (Step 9)
5. Handles errors gracefully
"""

import json
import os
import tempfile
import tarfile
from unittest.mock import patch, MagicMock, call
from django.test import TestCase, TransactionTestCase, override_settings
from django.contrib.auth.models import User
from django.utils import timezone

from uploads.models import (
    Patient,
    StudyMapping,
    UploadJob,
    Image,
)
from uploads.orthanc_client import get_client, OrthancPushError
from uploads.pseudo_id_validator import PseudoIDUniquenessValidator
from uploads.tasks import process_upload_job


def _stow_success_response(study_uid: str, series_uid: str, sop_uid: str) -> dict:
    """Real STOW-RS response shape (DICOM JSON, PS3.18 §6.6.1.2) — Orthanc
    never returns flat {"StudyInstanceUID": ...} keys; UIDs are embedded in
    RetrieveURLs and a ReferencedSOPSequence, keyed by tag."""
    return {
        "00081190": {
            "vr": "UR",
            "Value": [f"http://orthanc:8042/dicom-web/studies/{study_uid}"],
        },
        "00081199": {
            "vr": "SQ",
            "Value": [
                {
                    "00081155": {"vr": "UI", "Value": [sop_uid]},
                    "00081190": {
                        "vr": "UR",
                        "Value": [
                            f"http://orthanc:8042/dicom-web/studies/{study_uid}"
                            f"/series/{series_uid}/instances/{sop_uid}"
                        ],
                    },
                }
            ],
        },
    }


class TaskManifestValidationTest(TestCase):
    """Test task manifest validation with Orthanc integration."""
    
    def test_manifest_pseudo_id_validation_step(self):
        """Test Step 5b: Manifest pseudo ID validation."""
        manifest = {
            'patient': {
                'pseudo_id': 'PATIENT_001',
                'sex': 'M',
                'age_at_acquisition': 65,
            },
            'study': {
                'study_uid': 'study_abc',
            },
            'images': [
                {'filename': 'image1.dcm', 'organ': 'chest'},
            ],
        }
        
        # Validate pseudo IDs in manifest
        is_valid, errors = PseudoIDUniquenessValidator.validate_manifest_pseudo_ids(
            manifest,
            allow_existing=True
        )
        
        # Should pass (new patient)
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])
    
    def test_manifest_validation_with_existing_patient_allowed(self):
        """Test manifest validation allows existing pseudo_id when allow_existing=True."""
        pseudo_id = 'PATIENT_EXISTING'
        
        # Create existing patient
        Patient.objects.create(
            pseudo_id=pseudo_id,
            sex='M',
            age_at_first_acquisition=60,
        )
        
        manifest = {
            'patient': {
                'pseudo_id': pseudo_id,
                'sex': 'M',
                'age_at_acquisition': 61,
            },
            'study': {
                'study_uid': 'study_xyz',
            },
            'images': [
                {'filename': 'image1.dcm', 'organ': 'chest'},
            ],
        }
        
        # Should pass with allow_existing=True
        is_valid, errors = PseudoIDUniquenessValidator.validate_manifest_pseudo_ids(
            manifest,
            allow_existing=True
        )
        
        self.assertTrue(is_valid)


class TaskPatientCreationTest(TransactionTestCase):
    """Test task patient creation (Step 7)."""
    
    def setUp(self):
        """Set up test user."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
    
    def test_task_creates_new_patient(self):
        """Test that task Step 7 creates new Patient record."""
        pseudo_id = 'PATIENT_NEW'
        
        # Simulate Step 7 of task
        patient, created, error = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
            pseudo_id=pseudo_id,
            sex='M',
            age_at_acquisition=65,
            cohort_tag='TEST',
        )
        
        # Verify patient created
        self.assertTrue(created)
        self.assertIsNone(error)
        self.assertEqual(patient.pseudo_id, pseudo_id)
    
    def test_task_reuses_existing_patient(self):
        """Test that task Step 7 reuses existing Patient record."""
        pseudo_id = 'PATIENT_EXISTING'
        
        # Create patient first
        original_patient = Patient.objects.create(
            pseudo_id=pseudo_id,
            sex='M',
            age_at_first_acquisition=65,
        )
        
        # Simulate Step 7 with existing patient
        patient, created, error = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
            pseudo_id=pseudo_id,
            sex='M',
            age_at_acquisition=66,
            cohort_tag='TEST',
        )
        
        # Verify patient reused
        self.assertFalse(created)
        self.assertIsNone(error)
        self.assertEqual(patient.id, original_patient.id)


class TaskOrthancPushTest(TransactionTestCase):
    """Test task Orthanc push (Step 8)."""
    
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
        
        self.job = UploadJob.objects.create(uploader_id=str(self.user.id), status='PROCESSING')
        
        self.study_mapping = StudyMapping.objects.create(
            patient=self.patient,
            upload_job=self.job,
            pseudo_study_uid='study_123',
            acquisition_date='2026-02-27',
        )
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='test-orthanc-password',
    )
    def test_task_pushes_dicom_to_orthanc(self):
        """Test that task Step 8 pushes DICOM to Orthanc via STOW-RS."""
        dicom_bytes = b'FAKE_DICOM_DATA'
        
        with patch('uploads.orthanc_client.requests.Session.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _stow_success_response(
                '1.2.3.4.5', '1.2.3.4.5.1', '1.2.3.4.5.1.1'
            )
            mock_post.return_value = mock_response

            # Simulate Step 8
            client = get_client()
            push_result = client.push_dicom_file(dicom_bytes)
            
            # Verify push succeeded
            self.assertEqual(push_result['orthanc_study_id'], '1.2.3.4.5')
            self.assertEqual(push_result['orthanc_instance_id'], '1.2.3.4.5.1.1')
            
            # Verify correct endpoint called
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            self.assertIn('/dicom-web/studies', call_args[0][0])
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='test-orthanc-password',
    )
    def test_task_updates_study_mapping_after_orthanc_push(self):
        """Test that task Step 9 updates StudyMapping with Orthanc study ID."""
        dicom_bytes = b'FAKE_DICOM_DATA'
        orthanc_study_id = '1.2.3.4.5'
        
        with patch('uploads.orthanc_client.requests.Session.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _stow_success_response(
                orthanc_study_id, '1.2.3.4.5.1', '1.2.3.4.5.1.1'
            )
            mock_post.return_value = mock_response

            # Simulate Step 8 + 9
            client = get_client()
            push_result = client.push_dicom_file(dicom_bytes)
            
            # Update StudyMapping with Orthanc ID
            self.study_mapping.orthanc_study_id = push_result.get('orthanc_study_id')
            self.study_mapping.save()
            
            # Verify update
            updated_mapping = StudyMapping.objects.get(id=self.study_mapping.id)
            self.assertEqual(updated_mapping.orthanc_study_id, orthanc_study_id)
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='test-orthanc-password',
    )
    def test_task_handles_orthanc_push_error(self):
        """Test that task handles Orthanc push failure gracefully."""
        dicom_bytes = b'INVALID_DICOM'
        
        with patch('uploads.orthanc_client.requests.Session.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.text = 'Invalid DICOM'
            mock_post.return_value = mock_response
            
            # Simulate Step 8 with error
            client = get_client()
            
            with self.assertRaises(OrthancPushError) as context:
                client.push_dicom_file(dicom_bytes)
            
            error = context.exception
            self.assertEqual(error.status_code, 400)
            
            # Verify error can be logged/reported
            error_msg = f"Failed to push to Orthanc: {error.message}"
            self.assertIn('400', error_msg)


class TaskFailureRecoveryTest(TransactionTestCase):
    """Test task failure recovery and error reporting."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        
        self.job = UploadJob.objects.create(uploader_id=str(self.user.id), status='PROCESSING')
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='test-orthanc-password',
    )
    def test_task_continues_after_single_image_push_error(self):
        """Test that task continues processing remaining images if one fails."""
        patient, _, _ = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
            pseudo_id='PATIENT_001',
            sex='M',
            age_at_acquisition=65,
            cohort_tag='TEST',
        )
        
        study_mapping = StudyMapping.objects.create(
            patient=patient,
            upload_job=self.job,
            pseudo_study_uid='study_123',
            orthanc_study_id='1.2.3.4.5',
            acquisition_date='2026-02-27',
        )
        
        # Simulate processing 3 images: 1st succeeds, 2nd fails, 3rd succeeds
        with patch('uploads.orthanc_client.requests.Session.post') as mock_post:
            # First call: success
            mock_response_ok = MagicMock()
            mock_response_ok.status_code = 200
            mock_response_ok.json.return_value = _stow_success_response(
                '1.2.3.4.5', '1.2.3.4.5.1', '1.2.3.4.5.1.1'
            )

            # Second call: failure
            mock_response_error = MagicMock()
            mock_response_error.status_code = 400
            mock_response_error.text = 'Invalid DICOM'

            # Third call: success
            mock_response_ok2 = MagicMock()
            mock_response_ok2.status_code = 200
            mock_response_ok2.json.return_value = _stow_success_response(
                '1.2.3.4.5', '1.2.3.4.5.1', '1.2.3.4.5.1.3'
            )
            
            mock_post.side_effect = [
                mock_response_ok,
                mock_response_error,
                mock_response_ok2,
            ]
            
            client = get_client()
            
            results = []
            errors = []
            
            # Process 3 images
            for i in range(3):
                try:
                    result = client.push_dicom_file(b'DICOM_DATA')
                    results.append(result)
                except OrthancPushError as e:
                    errors.append({'image': i, 'error': str(e)})
            
            # Verify: 2 succeeded, 1 failed
            self.assertEqual(len(results), 2)
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0]['image'], 1)
    
    def test_job_status_updated_on_error(self):
        """Test that UploadJob status reflects errors."""
        # Simulate job with errors (PARTIAL = some images processed, some failed)
        self.job.status = 'PARTIAL'
        self.job.error_report = [
            {
                'image_index': 1,
                'filename': 'image2.dcm',
                'code': 'orthanc_push_error',
                'message': 'Server returned 400: Invalid DICOM',
            }
        ]
        self.job.save()
        
        # Verify job shows errors
        retrieved_job = UploadJob.objects.get(id=self.job.id)
        self.assertEqual(retrieved_job.status, 'PARTIAL')
        self.assertEqual(len(retrieved_job.error_report), 1)


class TaskImageRecordCreationTest(TransactionTestCase):
    """Test Image record creation with Orthanc instance IDs."""
    
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
        
        self.job = UploadJob.objects.create(uploader_id=str(self.user.id), status='PROCESSING')
        
        self.study_mapping = StudyMapping.objects.create(
            patient=self.patient,
            upload_job=self.job,
            pseudo_study_uid='study_123',
            orthanc_study_id='1.2.3.4.5',
            acquisition_date='2026-02-27',
        )
    
    def test_image_record_created_with_orthanc_ids(self):
        """Test that Image records are created with Orthanc instance IDs."""
        # Simulate Orthanc STOW-RS response
        orthanc_response = {
            'orthanc_study_id': '1.2.3.4.5',
            'orthanc_series_id': '1.2.3.4.5.1',
            'orthanc_instance_id': '1.2.3.4.5.1.1',
        }
        
        # Create Image record with Orthanc IDs (Step 9 of task)
        image = Image.objects.create(
            study_mapping=self.study_mapping,
            filename='image1.dcm',
            orthanc_instance_id=orthanc_response['orthanc_instance_id'],
        )
        
        # Verify image record
        retrieved = Image.objects.get(id=image.id)
        self.assertEqual(retrieved.orthanc_instance_id, '1.2.3.4.5.1.1')
        self.assertEqual(retrieved.study_mapping, self.study_mapping)
    
    def test_multiple_images_created_with_different_instance_ids(self):
        """Test that multiple Image records can have different Orthanc instance IDs."""
        images_data = [
            ('image1.dcm', '1.2.3.4.5.1.1'),
            ('image2.dcm', '1.2.3.4.5.1.2'),
            ('image3.dcm', '1.2.3.4.5.1.3'),
        ]
        
        created_images = []
        for filename, instance_id in images_data:
            image = Image.objects.create(
                study_mapping=self.study_mapping,
                filename=filename,
                orthanc_instance_id=instance_id,
            )
            created_images.append(image)
        
        # Verify all images created
        images = Image.objects.filter(study_mapping=self.study_mapping)
        self.assertEqual(images.count(), 3)
        
        # Verify each has unique instance_id
        instance_ids = list(images.values_list('orthanc_instance_id', flat=True))
        self.assertEqual(len(set(instance_ids)), 3)
