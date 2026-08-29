"""
Unit tests for Orthanc DICOM Server Client.

Tests the orthanc_client module which handles:
- STOW-RS push (upload DICOM to Orthanc)
- QIDO-RS query (search for studies/series)
- WADO-RS retrieve (get DICOM instances)
- Health checks
- Error handling
"""

import json
import requests
from unittest.mock import patch, MagicMock, Mock
from django.test import TestCase, override_settings
from django.conf import settings

from uploads.orthanc_client import (
    OrthancClient,
    get_client,
    OrthancPushError,
    OrthancQueryError,
)


class OrthancClientInitTest(TestCase):
    """Test OrthancClient initialization."""
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc'
    )
    def test_client_initialization(self):
        """Test that OrthancClient initializes with correct settings."""
        client = OrthancClient()
        
        self.assertEqual(client.base_url, 'http://orthanc:8042')
        self.assertEqual(client.session.auth, ('orthanc', 'orthanc'))
        self.assertEqual(client.session.timeout, 30)
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc-prod:8042',
        ORTHANC_USERNAME='admin',
        ORTHANC_PASSWORD='secured'
    )
    def test_client_with_custom_credentials(self):
        """Test client initialization with custom credentials."""
        client = OrthancClient()
        
        self.assertEqual(client.base_url, 'http://orthanc-prod:8042')
        self.assertEqual(client.session.auth, ('admin', 'secured'))
    
    def test_singleton_client_instance(self):
        """Test that get_client() returns singleton instance."""
        client1 = get_client()
        client2 = get_client()
        
        self.assertIs(client1, client2)


class OrthancPushDicomTest(TestCase):
    """Test STOW-RS DICOM push functionality."""
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc'
    )
    def test_push_dicom_success(self):
        """Test successful DICOM push to Orthanc.

        The response body is real STOW-RS DICOM JSON (PS3.18 §6.6.1.2) —
        tag-keyed, with UIDs embedded in RetrieveURLs — not the flat
        {"StudyInstanceUID": ...} shape Orthanc never actually sends.
        """
        dicom_bytes = b'\x00' * 1000  # Mock DICOM data

        with patch('uploads.orthanc_client.requests.Session.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "00081190": {
                    "vr": "UR",
                    "Value": ["http://orthanc:8042/dicom-web/studies/1.2.3.4.5"],
                },
                "00081199": {
                    "vr": "SQ",
                    "Value": [
                        {
                            "00081150": {"vr": "UI", "Value": ["1.2.840.10008.5.1.4.1.1.2"]},
                            "00081155": {"vr": "UI", "Value": ["1.2.3.4.5.1.1"]},
                            "00081190": {
                                "vr": "UR",
                                "Value": [
                                    "http://orthanc:8042/dicom-web/studies/1.2.3.4.5"
                                    "/series/1.2.3.4.5.1/instances/1.2.3.4.5.1.1"
                                ],
                            },
                        }
                    ],
                },
            }
            mock_post.return_value = mock_response
            
            client = OrthancClient()
            result = client.push_dicom_file(dicom_bytes)
            
            # Verify correct endpoint was called
            call_args = mock_post.call_args
            self.assertIn('/dicom-web/studies', call_args[0][0])
            
            # Verify result contains UIDs
            self.assertEqual(result['orthanc_study_id'], '1.2.3.4.5')
            self.assertEqual(result['orthanc_series_id'], '1.2.3.4.5.1')
            self.assertEqual(result['orthanc_instance_id'], '1.2.3.4.5.1.1')
            
            # Verify headers
            headers = call_args[1]['headers']
            self.assertEqual(headers['Content-Type'], 'multipart/related; type="application/dicom"; boundary="boundary_dicom_upload"')
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc'
    )
    def test_push_dicom_server_error(self):
        """Test DICOM push fails with server error."""
        dicom_bytes = b'\x00' * 1000
        
        with patch('uploads.orthanc_client.requests.Session.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = 'Internal Server Error'
            mock_post.return_value = mock_response
            
            client = OrthancClient()
            
            with self.assertRaises(OrthancPushError) as context:
                client.push_dicom_file(dicom_bytes)
            
            error = context.exception
            self.assertEqual(error.status_code, 500)
            self.assertIn('500', error.message)
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc'
    )
    def test_push_dicom_connection_error(self):
        """Test DICOM push fails with connection error."""
        dicom_bytes = b'\x00' * 1000
        
        with patch('uploads.orthanc_client.requests.Session.post') as mock_post:
            mock_post.side_effect = requests.ConnectionError('Connection refused')
            
            client = OrthancClient()
            
            with self.assertRaises(OrthancPushError) as context:
                client.push_dicom_file(dicom_bytes)
            
            error = context.exception
            self.assertIn('Request failed', error.message)
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc'
    )
    def test_push_dicom_missing_response_data(self):
        """An unparseable/empty response body means we can't confirm the
        instance was actually referenced by Orthanc — treat that as a
        failure (raise) rather than silently reporting fabricated success
        with empty UIDs, since the HTTP status alone doesn't guarantee the
        instance was accepted (STOW-RS allows 2xx with FailedSOPSequence)."""
        dicom_bytes = b'\x00' * 1000

        with patch('uploads.orthanc_client.requests.Session.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.side_effect = ValueError('Invalid JSON')
            mock_post.return_value = mock_response

            client = OrthancClient()

            with self.assertRaises(OrthancPushError):
                client.push_dicom_file(dicom_bytes)

    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc'
    )
    def test_push_dicom_failed_sop_sequence_raises(self):
        """A STOW-RS response can be HTTP 200 yet report the (only)
        instance as failed via FailedSOPSequence — this must raise, not
        report a fake success."""
        dicom_bytes = b'\x00' * 1000

        with patch('uploads.orthanc_client.requests.Session.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "00081198": {
                    "vr": "SQ",
                    "Value": [{"00081150": {"vr": "UI", "Value": ["1.2.840.10008.5.1.4.1.1.2"]}}],
                },
            }
            mock_post.return_value = mock_response

            client = OrthancClient()

            with self.assertRaises(OrthancPushError):
                client.push_dicom_file(dicom_bytes)


class OrthancQueryTest(TestCase):
    """Test QIDO-RS query functionality."""
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc'
    )
    def test_get_study_series_success(self):
        """Test successful series query from Orthanc."""
        series_data = [
            {
                'SeriesInstanceUID': '1.2.3.4.5.1',
                'SeriesNumber': '1',
                'Modality': 'CT',
            },
            {
                'SeriesInstanceUID': '1.2.3.4.5.2',
                'SeriesNumber': '2',
                'Modality': 'CT',
            },
        ]
        
        with patch('uploads.orthanc_client.requests.Session.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = series_data
            mock_get.return_value = mock_response
            
            client = OrthancClient()
            result = client.get_study_series('1.2.3.4.5')
            
            # Verify correct endpoint
            call_args = mock_get.call_args
            self.assertIn('1.2.3.4.5', call_args[0][0])
            self.assertIn('/series', call_args[0][0])
            
            # Verify result
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]['SeriesInstanceUID'], '1.2.3.4.5.1')
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc'
    )
    def test_get_study_series_not_found(self):
        """Test series query fails when study not found."""
        with patch('uploads.orthanc_client.requests.Session.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.text = 'Study not found'
            mock_get.return_value = mock_response
            
            client = OrthancClient()
            
            with self.assertRaises(OrthancQueryError) as context:
                client.get_study_series('nonexistent_study')
            
            error = context.exception
            self.assertEqual(error.status_code, 404)
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc'
    )
    def test_get_study_instances_success(self):
        """Test successful instances query from Orthanc."""
        instances_data = [
            {
                'SOPInstanceUID': '1.2.3.4.5.1.1',
                'SOPClassUID': '1.2.840.10008.5.1.4.1.1.2',
            },
            {
                'SOPInstanceUID': '1.2.3.4.5.1.2',
                'SOPClassUID': '1.2.840.10008.5.1.4.1.1.2',
            },
        ]
        
        with patch('uploads.orthanc_client.requests.Session.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = instances_data
            mock_get.return_value = mock_response
            
            client = OrthancClient()
            result = client.get_study_instances('1.2.3.4.5')
            
            # Verify correct endpoint
            call_args = mock_get.call_args
            self.assertIn('1.2.3.4.5', call_args[0][0])
            self.assertIn('/instances', call_args[0][0])
            
            # Verify result
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]['SOPInstanceUID'], '1.2.3.4.5.1.1')


class OrthancHealthCheckTest(TestCase):
    """Test Orthanc health check functionality."""
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc'
    )
    def test_health_check_success(self):
        """Test successful health check."""
        with patch('uploads.orthanc_client.requests.Session.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            client = OrthancClient()
            result = client.health_check()
            
            self.assertTrue(result)
            
            # Verify correct endpoint
            call_args = mock_get.call_args
            self.assertIn('/system', call_args[0][0])
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc'
    )
    def test_health_check_failure(self):
        """Test health check when Orthanc unreachable."""
        with patch('uploads.orthanc_client.requests.Session.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_get.return_value = mock_response
            
            client = OrthancClient()
            result = client.health_check()
            
            self.assertFalse(result)
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc'
    )
    def test_health_check_connection_error(self):
        """Test health check with connection error."""
        with patch('uploads.orthanc_client.requests.Session.get') as mock_get:
            mock_get.side_effect = Exception('Connection refused')
            
            client = OrthancClient()
            result = client.health_check()
            
            self.assertFalse(result)


class OrthancMultipartBodyTest(TestCase):
    """Test DICOM multipart/related body construction."""
    
    @override_settings(
        ORTHANC_BASE_URL='http://orthanc:8042',
        ORTHANC_USERNAME='orthanc',
        ORTHANC_PASSWORD='orthanc'
    )
    def test_multipart_body_format(self):
        """Test that multipart/related body is correctly formatted."""
        dicom_bytes = b'DICM_DATA'

        with patch('uploads.orthanc_client.requests.Session.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "00081199": {
                    "vr": "SQ",
                    "Value": [
                        {"00081155": {"vr": "UI", "Value": ["1.2.3.4.5.1.1"]}}
                    ],
                },
            }
            mock_post.return_value = mock_response
            
            client = OrthancClient()
            client.push_dicom_file(dicom_bytes)
            
            # Get the body that was sent
            call_args = mock_post.call_args
            body = call_args[1]['data']
            
            # Verify multipart format
            self.assertIn(b'--boundary_dicom_upload', body)
            self.assertIn(b'Content-Type: application/dicom', body)
            self.assertIn(b'Content-Length: 9', body)  # len('DICM_DATA')
            self.assertIn(dicom_bytes, body)
            self.assertIn(b'--boundary_dicom_upload--', body)
