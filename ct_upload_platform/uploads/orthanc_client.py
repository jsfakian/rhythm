"""
Thin client for communicating with Orthanc DICOM server.
Uses STOW-RS for DICOM push and DICOMweb endpoints for queries.
"""

import requests
from django.conf import settings
from io import BytesIO


class OrthancPushError(Exception):
    """Raised when pushing DICOM to Orthanc fails."""
    def __init__(self, message, status_code, response_body):
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message)


class OrthancQueryError(Exception):
    """Raised when querying Orthanc fails."""
    def __init__(self, message, status_code, response_body):
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message)


class OrthancClient:
    """Client for interacting with Orthanc REST and DICOMweb APIs."""
    
    def __init__(self):
        """Initialize Orthanc client with shared session and auth."""
        self.base_url = settings.ORTHANC_BASE_URL
        self.session = requests.Session()
        
        # Configure authentication if credentials are provided
        if settings.ORTHANC_USERNAME and settings.ORTHANC_PASSWORD:
            self.session.auth = (settings.ORTHANC_USERNAME, settings.ORTHANC_PASSWORD)
        
        self.session.timeout = 30  # 30-second timeout
    
    def push_dicom_file(self, dicom_bytes: bytes) -> dict:
        """
        Push a single DICOM file to Orthanc via STOW-RS.
        
        Args:
            dicom_bytes: Serialized DICOM file as bytes
        
        Returns:
            dict with keys: orthanc_study_id, orthanc_series_id, orthanc_instance_id
        
        Raises:
            OrthancPushError: If the push fails
        """
        url = f"{self.base_url}/dicom-web/studies"
        
        # Build multipart/related body with DICOM content
        boundary = "boundary_dicom_upload"
        
        multipart_body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/dicom\r\n"
            f"Content-Length: {len(dicom_bytes)}\r\n"
            f"\r\n"
        ).encode('utf-8')
        
        multipart_body += dicom_bytes
        multipart_body += f"\r\n--{boundary}--\r\n".encode('utf-8')
        
        headers = {
            'Content-Type': f'multipart/related; type="application/dicom"; boundary="{boundary}"'
        }
        
        try:
            response = self.session.post(url, data=multipart_body, headers=headers)
            
            if not (200 <= response.status_code < 300):
                raise OrthancPushError(
                    f"STOW-RS push failed with status {response.status_code}",
                    response.status_code,
                    response.text
                )
            
            # Parse STOW-RS response (typically JSON)
            try:
                response_data = response.json()
            except Exception:
                response_data = {}
            
            # Extract UIDs from response
            # Orthanc returns StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID
            result = {
                'orthanc_study_id': response_data.get('StudyInstanceUID', ''),
                'orthanc_series_id': response_data.get('SeriesInstanceUID', ''),
                'orthanc_instance_id': response_data.get('SOPInstanceUID', ''),
            }
            
            return result
        
        except requests.RequestException as e:
            raise OrthancPushError(
                f"Request failed: {str(e)}",
                getattr(e.response, 'status_code', 0),
                getattr(e.response, 'text', '')
            )
    
    def get_study_series(self, orthanc_study_id: str) -> list:
        """
        Query Orthanc for all series in a study.
        
        Args:
            orthanc_study_id: Orthanc Study Instance UID
        
        Returns:
            List of series objects from QIDO-RS
        
        Raises:
            OrthancQueryError: If the query fails
        """
        url = f"{self.base_url}/dicom-web/studies/{orthanc_study_id}/series"
        
        try:
            response = self.session.get(url)
            
            if response.status_code != 200:
                raise OrthancQueryError(
                    f"QIDO-RS series query failed with status {response.status_code}",
                    response.status_code,
                    response.text
                )
            
            return response.json()
        
        except requests.RequestException as e:
            raise OrthancQueryError(
                f"Request failed: {str(e)}",
                getattr(e.response, 'status_code', 0),
                getattr(e.response, 'text', '')
            )
    
    def get_study_instances(self, orthanc_study_id: str) -> list:
        """
        Query Orthanc for all instances in a study.
        
        Args:
            orthanc_study_id: Orthanc Study Instance UID
        
        Returns:
            List of instance objects from QIDO-RS
        
        Raises:
            OrthancQueryError: If the query fails
        """
        url = f"{self.base_url}/dicom-web/studies/{orthanc_study_id}/instances"
        
        try:
            response = self.session.get(url)
            
            if response.status_code != 200:
                raise OrthancQueryError(
                    f"QIDO-RS instances query failed with status {response.status_code}",
                    response.status_code,
                    response.text
                )
            
            return response.json()
        
        except requests.RequestException as e:
            raise OrthancQueryError(
                f"Request failed: {str(e)}",
                getattr(e.response, 'status_code', 0),
                getattr(e.response, 'text', '')
            )
    
    def health_check(self) -> bool:
        """
        Check if Orthanc is reachable and healthy.
        
        Returns:
            True if Orthanc responds with 200, False otherwise
        """
        url = f"{self.base_url}/system"
        
        try:
            response = self.session.get(url)
            return response.status_code == 200
        except Exception:
            return False


# Singleton instance for module-level usage
_client_instance = None


def get_client() -> OrthancClient:
    """Get or create the singleton OrthancClient instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = OrthancClient()
    return _client_instance
