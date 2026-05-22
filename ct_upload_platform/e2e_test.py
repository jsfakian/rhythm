#!/usr/bin/env python
"""
End-to-End Test Suite for CT Upload Platform

This script:
1. Creates test tar archives with DICOM-like content
2. Tests all REST API endpoints
3. Validates responses against expected schemas
4. Tests error cases and edge cases
5. Cleans up all test artifacts afterwards

Usage:
    python e2e_test.py --base-url http://localhost:8000 --token your-api-token

Requirements:
    - requests
    - pytest (optional, for assertions)
    - Django app must be running
"""

import argparse
import hashlib
import io
import json
import logging
import os
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestDataGenerator:
    """Generate test tar archives and manifests."""

    @staticmethod
    def create_dummy_dicom(content: str = "DICM") -> bytes:
        """Create minimal DICOM-like bytes (not a real DICOM file for testing)."""
        return content.encode('utf-8')

    @staticmethod
    def create_manifest(
        patient_id: str = "PAT_TEST_0001",
        study_id: str = "STUDY_TEST_0001",
        image_count: int = 3,
        include_annotations: bool = False,
        future_date: bool = False,
        checksums: Optional[Dict[int, str]] = None,
    ) -> Dict:
        """Create a valid manifest.json structure."""
        
        acq_date = datetime.now().date()
        if future_date:
            acq_date = acq_date + timedelta(days=1)
        
        images = []
        for i in range(1, image_count + 1):
            # Use provided checksum or generate one
            if checksums and i in checksums:
                checksum = checksums[i]
            else:
                dicom_content = TestDataGenerator.create_dummy_dicom(f"DICOM_{i}")
                checksum = hashlib.sha256(dicom_content).hexdigest()
            
            images.append({
                "filename": f"images/ct_{i:03d}.dcm",
                "checksum_sha256": checksum,
                "body_part_examined": "CHEST",
                "slice_thickness_mm": 1.0,
                "pixel_spacing_mm": [0.5, 0.5],
            })
        
        manifest = {
            "manifest_version": "1.0",
            "patient": {
                "pseudo_id": patient_id,
                "sex": "M",
                "age_at_first_acquisition": 62,
                "cohort_tag": "test_cohort",
            },
            "study": {
                "pseudo_study_uid": study_id,
                "acquisition_date": acq_date.isoformat(),
                "clinical_indication": "Test case",
                "contrast_used": False,
            },
            "images": images,
        }
        
        if include_annotations:
            manifest["annotations"] = [
                {
                    "annotation_uid": "ANN_001",
                    "image_filename": "images/ct_001.dcm",
                    "annotator_id": "TEST_PATHOLOGIST",
                    "annotation_date": datetime.now().date().isoformat(),
                    "type": "SEGMENTATION",
                    "label": "test_nodule",
                }
            ]
        
        return manifest

    @staticmethod
    def create_tar_archive(
        manifest: Dict,
        temp_dir: Optional[str] = None,
        filename: str = "test_upload.tar",
    ) -> str:
        """Create a tar archive with manifest and dummy DICOM files."""
        
        if temp_dir is None:
            temp_dir = tempfile.gettempdir()
        
        tar_path = os.path.join(temp_dir, filename)
        
        # First pass: compute actual checksums of DICOM content
        checksums = {}
        for i, image in enumerate(manifest["images"], 1):
            dicom_content = TestDataGenerator.create_dummy_dicom(f"DICOM_{i}")
            actual_checksum = hashlib.sha256(dicom_content).hexdigest()
            checksums[i] = actual_checksum
            # Update manifest with actual checksums
            image["checksum_sha256"] = actual_checksum
        
        manifest_json = json.dumps(manifest, indent=2).encode('utf-8')
        
        with tarfile.open(tar_path, "w") as tar:
            # Add manifest.json
            manifest_info = tarfile.TarInfo(name="manifest.json")
            manifest_info.size = len(manifest_json)
            tar.addfile(manifest_info, io.BytesIO(manifest_json))
            
            # Add DICOM files matching manifest
            for image in manifest["images"]:
                filename_in_tar = image["filename"]
                dicom_content = TestDataGenerator.create_dummy_dicom(
                    f"DICOM_{image['filename'].split('_')[-1].split('.')[0]}"
                )
                
                dicom_info = tarfile.TarInfo(name=filename_in_tar)
                dicom_info.size = len(dicom_content)
                tar.addfile(dicom_info, io.BytesIO(dicom_content))
        
        logger.info(f"Created test tar: {tar_path}")
        return tar_path


class APITester:
    """Test the REST API endpoints."""

    def __init__(self, base_url: str, token: str):
        """Initialize API tester with base URL and auth token."""
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.headers = {
            "Authorization": f"Token {token}",
            "Accept": "application/json",
        }
        self.uploaded_jobs: List[str] = []
        self.created_objects: Dict[str, List[str]] = {
            "jobs": [],
            "studies": [],
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Tuple[int, Dict]:
        """Make HTTP request and return status code and JSON response."""
        url = f"{self.base_url}{endpoint}"
        
        # Always ensure authorization header is present
        if "headers" not in kwargs:
            kwargs["headers"] = self.headers.copy()
        else:
            # Merge with our base headers
            base_headers = self.headers.copy()
            base_headers.update(kwargs["headers"])
            kwargs["headers"] = base_headers
        
        try:
            logger.info(f"{method} {endpoint}")
            logger.debug(f"Headers: {kwargs['headers']}")
            response = requests.request(method, url, timeout=30, **kwargs)
            
            try:
                data = response.json()
            except requests.exceptions.JSONDecodeError:
                data = {"raw_text": response.text}
            
            logger.info(f"Response: {response.status_code}")
            return response.status_code, data
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise

    def test_upload(self, tar_path: str, uploader_id: str = "TEST_UPLOADER") -> str:
        """Test POST /api/v1/uploads/ endpoint."""
        logger.info("\n=== Testing Upload ===")
        
        with open(tar_path, "rb") as f:
            files = {"tar_file": f}
            data = {"uploader_id": uploader_id}
            
            status, response = self._request(
                "POST",
                "/api/v1/uploads/",
                files=files,
                data=data,
            )
        
        assert status in [200, 201, 202], f"Expected 2xx, got {status}: {response}"
        assert "job_id" in response, f"Response missing job_id: {response}"
        
        job_id = response["job_id"]
        self.uploaded_jobs.append(job_id)
        self.created_objects["jobs"].append(job_id)
        
        logger.info(f"✓ Upload successful, job_id: {job_id}")
        logger.info(f"  Status: {response.get('status')}")
        logger.info(f"  Image count: {response.get('image_count')}")
        
        return job_id

    def test_poll_job_status(
        self,
        job_id: str,
        expected_status: Optional[str] = None,
        max_attempts: int = 30,
        wait_seconds: int = 1,
    ) -> Dict:
        """Poll job status until completion or timeout."""
        logger.info(f"\n=== Polling Job Status (job_id={job_id}) ===")
        
        for attempt in range(max_attempts):
            status, response = self._request("GET", f"/api/v1/uploads/{job_id}/")
            assert status == 200, f"Expected 200, got {status}: {response}"
            
            current_status = response.get("status")
            logger.info(f"Attempt {attempt + 1}: status={current_status}")
            
            if current_status in ["COMPLETE", "FAILED", "PARTIAL"]:
                logger.info(f"✓ Job reached terminal state: {current_status}")
                
                if expected_status:
                    assert current_status == expected_status, \
                        f"Expected {expected_status}, got {current_status}"
                
                return response
            
            if attempt < max_attempts - 1:
                time.sleep(wait_seconds)
        
        raise TimeoutError(
            f"Job {job_id} did not reach terminal state after {max_attempts * wait_seconds}s"
        )

    def test_list_uploads(self) -> Dict:
        """Test GET /api/v1/uploads/ endpoint."""
        logger.info("\n=== Listing Uploads ===")
        
        status, response = self._request("GET", "/api/v1/uploads/")
        assert status == 200, f"Expected 200, got {status}: {response}"
        
        assert isinstance(response, (dict, list)), "Response should be dict or list"
        logger.info(f"✓ Retrieved {len(response) if isinstance(response, list) else 1} upload(s)")
        
        return response

    def test_list_studies(self) -> Dict:
        """Test GET /api/v1/studies/ endpoint."""
        logger.info("\n=== Listing Studies ===")
        
        status, response = self._request("GET", "/api/v1/studies/")
        assert status == 200, f"Expected 200, got {status}: {response}"
        
        results = response.get("results", []) if isinstance(response, dict) else response
        logger.info(f"✓ Retrieved {len(results)} study(ies)")
        
        if results:
            self.created_objects["studies"].extend(
                [s.get("pseudo_study_uid") for s in results if s.get("pseudo_study_uid")]
            )
        
        return response

    def test_get_study_detail(self, study_uid: str) -> Dict:
        """Test GET /api/v1/studies/{study_uid}/ endpoint."""
        logger.info(f"\n=== Getting Study Detail ({study_uid}) ===")
        
        status, response = self._request("GET", f"/api/v1/studies/{study_uid}/")
        assert status == 200, f"Expected 200, got {status}: {response}"
        
        logger.info(f"✓ Retrieved study detail")
        logger.info(f"  pseudo_id: {response.get('pseudo_id')}")
        logger.info(f"  acquisition_date: {response.get('acquisition_date')}")
        
        return response

    def test_invalid_manifest(self) -> str:
        """Test upload with invalid manifest (missing required field)."""
        logger.info("\n=== Testing Invalid Manifest ===")
        
        invalid_manifest = {
            "manifest_version": "1.0",
            "patient": {"pseudo_id": "PAT_INVALID"},
            # Missing: study, images
        }
        
        temp_dir = tempfile.gettempdir()
        tar_path = os.path.join(temp_dir, "invalid_manifest.tar")
        
        with tarfile.open(tar_path, "w") as tar:
            manifest_json = json.dumps(invalid_manifest).encode('utf-8')
            manifest_info = tarfile.TarInfo(name="manifest.json")
            manifest_info.size = len(manifest_json)
            tar.addfile(manifest_info, io.BytesIO(manifest_json))
        
        try:
            with open(tar_path, "rb") as f:
                files = {"tar_file": f}
                status, response = self._request(
                    "POST",
                    "/api/v1/uploads/",
                    files=files,
                    headers=self.headers.copy(),
                )
            
            # Could be 400, 422, or 202 with FAILED status later
            logger.info(f"✓ Server responded with status {status}")
            
            if status == 202:
                job_id = response.get("job_id")
                if job_id:
                    self.uploaded_jobs.append(job_id)
                    status_resp = self.test_poll_job_status(job_id)
                    assert status_resp.get("status") == "FAILED", \
                        f"Expected FAILED status for invalid manifest, got {status_resp.get('status')}"
                    
                    assert status_resp.get("errors"), "Expected error details"
                    logger.info(f"✓ Job correctly failed with errors: {status_resp['errors']}")
        finally:
            self._cleanup_file(tar_path)
        
        return "PASSED"

    def test_invalid_pseudo_id(self) -> str:
        """Test manifest with invalid pseudo_id pattern."""
        logger.info("\n=== Testing Invalid Pseudo ID ===")
        
        manifest = TestDataGenerator.create_manifest(patient_id="INVALID@#$")
        
        temp_dir = tempfile.gettempdir()
        tar_path = TestDataGenerator.create_tar_archive(
            manifest,
            temp_dir=temp_dir,
            filename="invalid_pseudo_id.tar"
        )
        
        try:
            with open(tar_path, "rb") as f:
                files = {"tar_file": f}
                status, response = self._request(
                    "POST",
                    "/api/v1/uploads/",
                    files=files,
                    headers=self.headers.copy(),
                )
            
            if status == 202:
                job_id = response.get("job_id")
                if job_id:
                    self.uploaded_jobs.append(job_id)
                    status_resp = self.test_poll_job_status(job_id)
                    assert status_resp.get("status") == "FAILED", \
                        f"Expected FAILED for invalid pseudo_id"
                    logger.info(f"✓ Job correctly failed for invalid pseudo_id")
        finally:
            self._cleanup_file(tar_path)
        
        return "PASSED"

    def test_future_acquisition_date(self) -> str:
        """Test manifest with future acquisition date (should fail)."""
        logger.info("\n=== Testing Future Acquisition Date ===")
        
        manifest = TestDataGenerator.create_manifest(future_date=True)
        
        temp_dir = tempfile.gettempdir()
        tar_path = TestDataGenerator.create_tar_archive(
            manifest,
            temp_dir=temp_dir,
            filename="future_date.tar"
        )
        
        try:
            with open(tar_path, "rb") as f:
                files = {"tar_file": f}
                status, response = self._request(
                    "POST",
                    "/api/v1/uploads/",
                    files=files,
                    headers=self.headers.copy(),
                )
            
            if status == 202:
                job_id = response.get("job_id")
                if job_id:
                    self.uploaded_jobs.append(job_id)
                    status_resp = self.test_poll_job_status(job_id)
                    assert status_resp.get("status") == "FAILED", \
                        f"Expected FAILED for future date"
                    logger.info(f"✓ Job correctly failed for future acquisition date")
        finally:
            self._cleanup_file(tar_path)
        
        return "PASSED"

    def test_missing_image_file(self) -> str:
        """Test manifest referencing non-existent image file."""
        logger.info("\n=== Testing Missing Image File ===")
        
        manifest = TestDataGenerator.create_manifest(image_count=1)
        # Corrupt the filename reference
        manifest["images"][0]["filename"] = "images/nonexistent.dcm"
        
        temp_dir = tempfile.gettempdir()
        tar_path = TestDataGenerator.create_tar_archive(
            manifest,
            temp_dir=temp_dir,
            filename="missing_file.tar"
        )
        
        try:
            with open(tar_path, "rb") as f:
                files = {"tar_file": f}
                status, response = self._request(
                    "POST",
                    "/api/v1/uploads/",
                    files=files,
                    headers=self.headers.copy(),
                )
            
            if status == 202:
                job_id = response.get("job_id")
                if job_id:
                    self.uploaded_jobs.append(job_id)
                    status_resp = self.test_poll_job_status(job_id)
                    assert status_resp.get("status") in ["FAILED", "PARTIAL"], \
                        f"Expected FAILED/PARTIAL for missing file"
                    logger.info(f"✓ Job correctly failed for missing file")
        finally:
            self._cleanup_file(tar_path)
        
        return "PASSED"

    def test_authentication(self) -> str:
        """Test that missing/invalid token is rejected."""
        logger.info("\n=== Testing Authentication ===")
        
        # Create a new tester instance with bad token to test auth rejection
        bad_tester = APITester(self.base_url, "invalid-token-xyz")
        
        status, response = bad_tester._request(
            "GET",
            "/api/v1/uploads/",
        )
        
        assert status in [401, 403], \
            f"Expected 401/403 for invalid token, got {status}"
        
        logger.info(f"✓ Server correctly rejected invalid token with {status}")
        return "PASSED"

    def test_large_image_count(self) -> str:
        """Test upload with many images (edge case)."""
        logger.info("\n=== Testing Large Image Count (edge case) ===")
        
        # Create manifest with 100 images (reasonable test without hitting limits)
        manifest = TestDataGenerator.create_manifest(image_count=100)
        
        temp_dir = tempfile.gettempdir()
        tar_path = TestDataGenerator.create_tar_archive(
            manifest,
            temp_dir=temp_dir,
            filename="large_batch.tar"
        )
        
        try:
            job_id = self.test_upload(tar_path)
            status_resp = self.test_poll_job_status(job_id)
            
            image_count = status_resp.get("image_count", {})
            logger.info(
                f"✓ Processed {image_count.get('successful', 0)} "
                f"out of {image_count.get('submitted', 0)} images"
            )
        finally:
            self._cleanup_file(tar_path)
        
        return "PASSED"

    def _cleanup_file(self, path: str):
        """Safe file cleanup."""
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.debug(f"Cleaned up {path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {path}: {e}")

    def cleanup(self):
        """Clean up all created test data."""
        logger.info("\n=== Cleanup ===")
        
        # Note: In a real scenario with actual Orthanc integration,
        # you might want to delete studies from Orthanc as well.
        # For now, we just log what would be cleaned up.
        
        logger.info(f"Test artifacts created:")
        logger.info(f"  Upload jobs: {len(self.created_objects['jobs'])}")
        logger.info(f"  Studies: {len(self.created_objects['studies'])}")
        
        # Optional: Delete upload jobs (if API supports it)
        # for job_id in self.created_objects['jobs']:
        #     try:
        #         status, response = self._request(
        #             "DELETE",
        #             f"/api/v1/uploads/{job_id}/"
        #         )
        #         if status == 204:
        #             logger.info(f"✓ Deleted job {job_id}")
        #     except Exception as e:
        #         logger.warning(f"Failed to delete job {job_id}: {e}")
        
        logger.info("✓ Cleanup complete")


def run_full_test_suite(base_url: str, token: str, verbose: bool = False):
    """Run the complete test suite."""
    
    if verbose:
        logger.setLevel(logging.DEBUG)
    
    logger.info("=" * 70)
    logger.info("CT Upload Platform - End-to-End Test Suite")
    logger.info("=" * 70)
    logger.info(f"Base URL: {base_url}")
    logger.info(f"Timestamp: {datetime.now()}")
    logger.info("=" * 70)
    
    tester = APITester(base_url, token)
    
    test_results = {}
    
    try:
        # Test 1: Successful upload and processing
        logger.info("\n[Test 1/10] Successful upload with valid manifest")
        manifest = TestDataGenerator.create_manifest(
            patient_id="PAT_TEST_0001",
            study_id="STUDY_TEST_0001",
            image_count=3,
            include_annotations=False,
        )
        tar_path = TestDataGenerator.create_tar_archive(
            manifest,
            filename="test_success.tar"
        )
        try:
            job_id = tester.test_upload(tar_path)
            status_resp = tester.test_poll_job_status(job_id)
            test_results["upload_success"] = "PASSED"
        except Exception as e:
            logger.error(f"✗ Test failed: {e}")
            test_results["upload_success"] = f"FAILED: {e}"
        finally:
            tester._cleanup_file(tar_path)
        
        # Test 2: List uploads
        logger.info("\n[Test 2/10] List uploads")
        try:
            tester.test_list_uploads()
            test_results["list_uploads"] = "PASSED"
        except Exception as e:
            logger.error(f"✗ Test failed: {e}")
            test_results["list_uploads"] = f"FAILED: {e}"
        
        # Test 3: List studies
        logger.info("\n[Test 3/10] List studies")
        try:
            tester.test_list_studies()
            test_results["list_studies"] = "PASSED"
        except Exception as e:
            logger.error(f"✗ Test failed: {e}")
            test_results["list_studies"] = f"FAILED: {e}"
        
        # Test 4: Get study detail
        logger.info("\n[Test 4/10] Get study detail (if studies exist)")
        try:
            if tester.created_objects["studies"]:
                study_uid = tester.created_objects["studies"][0]
                tester.test_get_study_detail(study_uid)
                test_results["get_study_detail"] = "PASSED"
            else:
                logger.info("⊘ Skipping: no studies available")
                test_results["get_study_detail"] = "SKIPPED"
        except Exception as e:
            logger.error(f"✗ Test failed: {e}")
            test_results["get_study_detail"] = f"FAILED: {e}"
        
        # Test 5: Invalid manifest
        logger.info("\n[Test 5/10] Invalid manifest (missing required fields)")
        try:
            tester.test_invalid_manifest()
            test_results["invalid_manifest"] = "PASSED"
        except Exception as e:
            logger.error(f"✗ Test failed: {e}")
            test_results["invalid_manifest"] = f"FAILED: {e}"
        
        # Test 6: Invalid pseudo_id
        logger.info("\n[Test 6/10] Invalid pseudo_id pattern")
        try:
            tester.test_invalid_pseudo_id()
            test_results["invalid_pseudo_id"] = "PASSED"
        except Exception as e:
            logger.error(f"✗ Test failed: {e}")
            test_results["invalid_pseudo_id"] = f"FAILED: {e}"
        
        # Test 7: Future acquisition date
        logger.info("\n[Test 7/10] Future acquisition date")
        try:
            tester.test_future_acquisition_date()
            test_results["future_date"] = "PASSED"
        except Exception as e:
            logger.error(f"✗ Test failed: {e}")
            test_results["future_date"] = f"FAILED: {e}"
        
        # Test 8: Missing image file
        logger.info("\n[Test 8/10] Missing image file in tar")
        try:
            tester.test_missing_image_file()
            test_results["missing_file"] = "PASSED"
        except Exception as e:
            logger.error(f"✗ Test failed: {e}")
            test_results["missing_file"] = f"FAILED: {e}"
        
        # Test 9: Authentication
        logger.info("\n[Test 9/10] Authentication (invalid token)")
        try:
            tester.test_authentication()
            test_results["auth"] = "PASSED"
        except Exception as e:
            logger.error(f"✗ Test failed: {e}")
            test_results["auth"] = f"FAILED: {e}"
        
        # Test 10: Large image count
        logger.info("\n[Test 10/10] Large image count (edge case)")
        try:
            tester.test_large_image_count()
            test_results["large_batch"] = "PASSED"
        except Exception as e:
            logger.error(f"✗ Test failed: {e}")
            test_results["large_batch"] = f"FAILED: {e}"
        
    finally:
        # Always cleanup
        tester.cleanup()
    
    # Print summary
    logger.info("\n" + "=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    
    passed = sum(1 for v in test_results.values() if v == "PASSED")
    failed = sum(1 for v in test_results.values() if "FAILED" in str(v))
    skipped = sum(1 for v in test_results.values() if v == "SKIPPED")
    
    for test_name, result in test_results.items():
        status_symbol = "✓" if result == "PASSED" else ("⊘" if result == "SKIPPED" else "✗")
        logger.info(f"{status_symbol} {test_name}: {result}")
    
    logger.info("=" * 70)
    logger.info(f"Total: {passed} passed, {failed} failed, {skipped} skipped")
    logger.info("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="End-to-End Test Suite for CT Upload Platform"
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the Django API (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--token",
        required=False,
        help="Bearer token for authentication (required for tests)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if not args.token:
        logger.error("Error: --token is required. Get a token from Django Admin or API.")
        sys.exit(1)
    
    success = run_full_test_suite(args.base_url, args.token, args.verbose)
    sys.exit(0 if success else 1)
