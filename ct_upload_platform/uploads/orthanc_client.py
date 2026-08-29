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


# DICOM tags used in a STOW-RS response (PS3.18 §6.6.1.2), keyed the way
# Orthanc (and DICOMweb servers generally) render DICOM JSON: group+element
# as an 8-digit hex string, each with {"vr": ..., "Value": [...]}.
_TAG_RETRIEVE_URL = "00081190"        # RetrieveURL
_TAG_REFERENCED_SOP_SEQUENCE = "00081199"   # ReferencedSOPSequence (succeeded instances)
_TAG_FAILED_SOP_SEQUENCE = "00081198"       # FailedSOPSequence
_TAG_REFERENCED_SOP_INSTANCE_UID = "00081155"  # ReferencedSOPInstanceUID


def _tag_value(dicom_json: dict, tag: str):
    """Return the first Value entry for *tag* in a DICOM JSON object, or None."""
    values = (dicom_json or {}).get(tag, {}).get("Value")
    return values[0] if values else None


def _uid_from_retrieve_url(url: str, segment: str) -> str:
    """Extract the UID following *segment* in a DICOMweb retrieve URL, e.g.
    segment="series" on ".../studies/S/series/SE/instances/I" -> "SE"."""
    if not url:
        return ""
    parts = url.rstrip("/").split("/")
    try:
        return parts[parts.index(segment) + 1]
    except (ValueError, IndexError):
        return ""


def _stow_response_has_failure(response_data: dict) -> bool:
    """True if the STOW-RS response's FailedSOPSequence is non-empty — the
    HTTP status can still be 2xx even when the (only) instance we sent
    failed, per the DICOM STOW-RS spec's partial-success semantics."""
    failed = (response_data or {}).get(_TAG_FAILED_SOP_SEQUENCE, {}).get("Value")
    return bool(failed)


def _parse_stow_response(response_data: dict) -> dict:
    """Parse a STOW-RS (DICOM JSON, PS3.18) response into the flat
    orthanc_study_id / orthanc_series_id / orthanc_instance_id shape the
    rest of the app expects, extracting UIDs from the response's
    RetrieveURLs rather than assuming (nonexistent) flat top-level keys
    like "StudyInstanceUID"."""
    result = {"orthanc_study_id": "", "orthanc_series_id": "", "orthanc_instance_id": ""}

    study_url = _tag_value(response_data, _TAG_RETRIEVE_URL)
    if study_url:
        result["orthanc_study_id"] = _uid_from_retrieve_url(study_url, "studies")

    referenced = (response_data or {}).get(_TAG_REFERENCED_SOP_SEQUENCE, {}).get("Value") or []
    if referenced:
        entry = referenced[0]
        result["orthanc_instance_id"] = _tag_value(entry, _TAG_REFERENCED_SOP_INSTANCE_UID) or ""
        instance_url = _tag_value(entry, _TAG_RETRIEVE_URL)
        if instance_url:
            result["orthanc_series_id"] = _uid_from_retrieve_url(instance_url, "series")
            if not result["orthanc_instance_id"]:
                result["orthanc_instance_id"] = _uid_from_retrieve_url(instance_url, "instances")

    return result


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

            # Parse STOW-RS response (DICOM JSON per PS3.18, not flat keys)
            try:
                response_data = response.json()
            except Exception:
                response_data = {}

            if _stow_response_has_failure(response_data):
                raise OrthancPushError(
                    "STOW-RS reported the instance as failed (FailedSOPSequence present)",
                    response.status_code,
                    response.text
                )

            result = _parse_stow_response(response_data)
            if not result['orthanc_instance_id']:
                raise OrthancPushError(
                    "STOW-RS response did not reference the pushed instance "
                    "(no ReferencedSOPSequence entry)",
                    response.status_code,
                    response.text
                )

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
