"""
Test Bearer Token Authentication Compatibility

Verifies that the new BearerTokenAuthentication class works with both
Bearer and Token authentication formats.
"""

import json
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase, APIClient


class BearerTokenAuthenticationTest(APITestCase):
    """Test BearerTokenAuthentication with both formats."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.token = Token.objects.create(user=self.user)
        self.token_key = self.token.key
    
    def test_bearer_format_authentication(self):
        """Test authentication with Bearer format header."""
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token_key}')
        
        # Try to access an authenticated endpoint
        response = client.get('/api/v1/uploads/')
        
        # Should not get 401 Unauthorized
        self.assertNotEqual(response.status_code, 401,
                           msg="Bearer format authentication failed")
        self.assertIn(response.status_code, [200, 400],
                     msg="Expected valid response, got " + str(response.status_code))
    
    def test_token_format_authentication(self):
        """Test authentication with legacy Token format header."""
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {self.token_key}')
        
        # Try to access an authenticated endpoint
        response = client.get('/api/v1/uploads/')
        
        # Should not get 401 Unauthorized
        self.assertNotEqual(response.status_code, 401,
                           msg="Token format authentication failed")
        self.assertIn(response.status_code, [200, 400],
                     msg="Expected valid response, got " + str(response.status_code))
    
    def test_bearer_format_with_lowercase_keyword(self):
        """Test Bearer authentication with lowercase 'bearer' keyword."""
        client = APIClient()
        # Some clients might send lowercase
        client.credentials(HTTP_AUTHORIZATION=f'bearer {self.token_key}')
        
        response = client.get('/api/v1/uploads/')
        self.assertNotEqual(response.status_code, 401,
                           msg="Lowercase 'bearer' format not accepted")
    
    def test_invalid_token_rejected(self):
        """Test that invalid tokens are rejected."""
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer invalid_token_12345')
        
        response = client.get('/api/v1/uploads/')
        self.assertEqual(response.status_code, 401,
                        msg="Invalid token should be rejected")
    
    def test_missing_token_rejected(self):
        """Test that missing authentication is rejected."""
        client = APIClient()
        # No credentials at all
        
        response = client.get('/api/v1/uploads/')
        self.assertEqual(response.status_code, 401,
                        msg="Missing token should be rejected")
    
    def test_malformed_header_rejected(self):
        """Test that malformed headers are rejected."""
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='MalformedHeader')
        
        response = client.get('/api/v1/uploads/')
        self.assertEqual(response.status_code, 401,
                        msg="Malformed header should be rejected")
    
    def test_manifest_validation_with_bearer(self):
        """Test manifest validation endpoint with Bearer auth."""
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token_key}')
        
        manifest = {
            "manifest_version": "1.0",
            "upload_id": "test-123",
            "created_at": "2026-02-26T10:00:00Z",
            "patient": {"pseudo_id": "test_patient_001", "sex": "M", "age_at_acquisition": 50},
            "study": {"study_uid": "1.2.3", "acquisition_date": "2026-02-20", "contrast_used": False},
            "images": [{"filename": "img.dcm", "checksum_sha256": "a" * 64, "series_uid": "1.2.3.1", "body_part": "CHEST"}]
        }
        
        response = client.post(
            '/api/v1/uploads/validate-manifest/',
            {"manifest": manifest},
            format='json'
        )
        
        self.assertNotEqual(response.status_code, 401,
                           msg="Bearer auth failed on manifest validation")
    
    def test_manifest_validation_with_token(self):
        """Test manifest validation endpoint with Token auth."""
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {self.token_key}')
        
        manifest = {
            "manifest_version": "1.0",
            "upload_id": "test-456",
            "created_at": "2026-02-26T10:00:00Z",
            "patient": {"pseudo_id": "test_patient_002", "sex": "F", "age_at_acquisition": 35},
            "study": {"study_uid": "1.2.4", "acquisition_date": "2026-02-21", "contrast_used": True},
            "images": [{"filename": "img.dcm", "checksum_sha256": "b" * 64, "series_uid": "1.2.4.1", "body_part": "ABDOMEN"}]
        }
        
        response = client.post(
            '/api/v1/uploads/validate-manifest/',
            {"manifest": manifest},
            format='json'
        )
        
        self.assertNotEqual(response.status_code, 401,
                           msg="Token auth failed on manifest validation")
    
    def test_both_formats_access_same_data(self):
        """Test that Bearer and Token formats access the same data."""
        # Create two clients with different auth formats
        bearer_client = APIClient()
        bearer_client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token_key}')
        
        token_client = APIClient()
        token_client.credentials(HTTP_AUTHORIZATION=f'Token {self.token_key}')
        
        # Both should access the same endpoint
        bearer_response = bearer_client.get('/api/v1/uploads/')
        token_response = token_client.get('/api/v1/uploads/')
        
        # Both should succeed (or fail the same way)
        self.assertEqual(
            bearer_response.status_code, 
            token_response.status_code,
            msg="Bearer and Token formats should have same access level"
        )
    
    def test_authentication_info_in_header(self):
        """Test parsing authentication info from headers."""
        client = APIClient()
        
        # Test with Bearer
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token_key}')
        response = client.get('/api/v1/uploads/')
        self.assertNotEqual(response.status_code, 401)
        
        # Test with Token
        client.credentials(HTTP_AUTHORIZATION=f'Token {self.token_key}')
        response = client.get('/api/v1/uploads/')
        self.assertNotEqual(response.status_code, 401)
    
    def test_authentication_case_insensitive(self):
        """Test that Bearer keyword is case-insensitive."""
        client = APIClient()
        
        # Try various case combinations
        for keyword in ['Bearer', 'bearer', 'BEARER', 'BeArEr']:
            client.credentials(HTTP_AUTHORIZATION=f'{keyword} {self.token_key}')
            response = client.get('/api/v1/uploads/')
            self.assertNotEqual(response.status_code, 401,
                               msg=f"Case variation '{keyword}' failed")


if __name__ == '__main__':
    import unittest
    unittest.main()
