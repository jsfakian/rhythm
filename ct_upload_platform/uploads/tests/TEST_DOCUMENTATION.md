# Unit Tests Documentation

This document describes the comprehensive unit tests for the CT Upload Platform, covering file management, API functionality, and the new authentication and access control features.

## Test Files Overview

### Core Feature Tests

#### 1. `test_file_manager.py` - File Management Utilities

Tests for the file manager utility module (`uploads/file_manager.py`).

**Test Class: `FileManagerTestCase`**

Tests the core file management functions:

- **`test_ensure_directory_exists_creates_dir`** - Verifies that `ensure_directory_exists()` creates directories
- **`test_ensure_directory_exists_with_existing_dir`** - Verifies idempotency with existing directories
- **`test_get_raw_data_user_dir_creates_user_directory`** - Tests creation of `raw_data/{uploader_id}/`
- **`test_get_raw_data_user_dir_with_multiple_users`** - Tests multiple user directories
- **`test_get_processed_data_job_dir_creates_job_directory`** - Tests creation of `processed_data/{job_id}/`
- **`test_get_all_raw_data_users_returns_user_list`** - Tests listing all users in raw_data
- **`test_get_all_raw_data_users_empty_directory`** - Tests empty directory handling
- **`test_get_all_raw_data_users_nonexistent_directory`** - Tests nonexistent directory handling
- **`test_get_user_tar_files_returns_tar_list`** - Tests retrieving tar files for a user
- **`test_get_user_tar_files_filters_non_tar_files`** - Tests filtering non-tar files
- **`test_get_job_processed_files_returns_all_files`** - Tests retrieving all processed files
- **`test_delete_job_processed_data_removes_directory`** - Tests deletion of job directories
- **`test_delete_job_processed_data_nonexistent_directory`** - Tests deletion of nonexistent directories
- **`test_delete_user_raw_data_removes_directory`** - Tests deletion of user directories
- **`test_delete_user_raw_data_nonexistent_directory`** - Tests deletion of nonexistent user directories
- **`test_get_directory_size_calculates_total`** - Tests directory size calculation
- **`test_get_directory_size_empty_directory`** - Tests size of empty directories
- **`test_get_directory_size_nonexistent_directory`** - Tests size of nonexistent directories
- **`test_get_directory_size_nested_files`** - Tests recursive size calculation

**Total: 19 tests**

#### 2. `test_upload_file_storage.py` - Upload & Task File Storage

Integration tests for the upload API and task processing with the new file storage.

**Test Class: `UploadFileStorageTestCase`**

Tests the upload API's file storage behavior:

- **`test_upload_saves_to_raw_data_user_directory`** - Verifies uploaded tars are saved to `raw_data/{uploader_id}/`
- **`test_upload_preserves_tar_file_name_structure`** - Tests UUID naming of tar files
- **`test_multiple_uploads_from_same_user_all_in_same_directory`** - Tests multiple uploads stay in same user directory

**Test Class: `TaskProcessingFileLocationTestCase`**

Tests the task processing behavior with file directories:

- **`test_task_extracts_to_processed_data_job_directory`** - Verifies tar extraction to `processed_data/{job_id}/`
- **`test_processed_data_cleanup_on_failure`** - Tests deletion of processed_data on task failure
- **`test_raw_data_tar_file_never_deleted`** - Verifies tar files in raw_data are never auto-deleted
- **`test_processed_data_preserved_on_success`** - Tests preservation of processed_data on success

**Test Class: `UploadJobTarPathTestCase`**

Tests the UploadJob model's tar_temp_path field:

- **`test_upload_job_stores_raw_data_path`** - Verifies that UploadJob stores the correct raw_data path

**Total: 10 tests**

### Authentication & Authorization Tests

#### 3. `test_authentication.py` - NEW: Authentication, Access Control & User Management

Comprehensive tests for the new authentication system.

**Test Class: `IPWhitelistMiddlewareTestCase`**

Tests IP-based access restrictions:

- **`test_no_whitelist_allows_all_ips`** - When IP_WHITELIST not set, all IPs allowed
- **`test_whitelist_allows_matching_ip`** - Whitelisted IPs are allowed
- **`test_whitelist_blocks_unmatched_ip`** - Non-whitelisted IPs get 403 Forbidden
- **`test_whitelist_single_ip`** - Single IP whitelist works correctly
- **`test_whitelist_exempts_login_endpoint`** - `/api/v1/auth/login/` accessible from any IP
- **`test_whitelist_with_x_forwarded_for_header`** - X-Forwarded-For header properly checked for proxied requests

**Test Class: `LoginAPITestCase`**

Tests REST API login endpoint:

- **`test_login_with_valid_credentials`** - Valid username/password returns token
- **`test_login_with_invalid_password`** - Wrong password returns 401 Unauthorized
- **`test_login_with_invalid_username`** - Non-existent user returns 401 Unauthorized
- **`test_login_missing_username`** - Missing username returns 400 Bad Request
- **`test_login_missing_password`** - Missing password returns 400 Bad Request
- **`test_login_returns_token_with_full_user_info`** - Response includes user details
- **`test_token_can_be_used_for_api_access`** - Returned token works for API authentication
- **`test_login_endpoint_accessible_without_auth`** - Login endpoint requires no authentication

**Test Class: `LoginPageTestCase`**

Tests web-based login page:

- **`test_login_page_accessible`** - `/login/` page loads successfully
- **`test_authenticated_user_redirected_from_login`** - Already logged-in users redirected

**Test Class: `CreateUserManagementCommandTestCase`**

Tests user creation management command:

- **`test_create_user_with_valid_arguments`** - Command creates user with username and email
- **`test_create_user_with_full_details`** - Command accepts first_name and last_name
- **`test_create_user_with_staff_privileges`** - `--is-staff` flag grants staff role
- **`test_create_user_with_superuser_privileges`** - `--is-superuser` flag grants superuser role
- **`test_create_user_generates_random_password`** - Command generates secure random password
- **`test_create_user_duplicate_username_fails`** - Duplicate username raises exception
- **`test_create_user_duplicate_email_fails`** - Duplicate email raises exception
- **`test_create_user_missing_required_arguments`** - Missing required args raises exception
- **`test_create_user_password_length_configurable`** - `--password-length` option respected
- **`test_create_user_without_email_flag`** - `--no-email` flag skips email sending

**Test Class: `TokenAuthenticationTestCase`**

Tests token-based API authentication:

- **`test_bearer_token_authentication`** - Bearer token format works
- **`test_token_format_authentication`** - Legacy Token format still works
- **`test_invalid_token_rejected`** - Invalid token returns 401
- **`test_missing_token_rejected`** - Request without token returns 401
- **`test_malformed_auth_header_rejected`** - Malformed header returns 401

**Test Class: `UserPermissionsTestCase`**

Tests user permissions and access control:

- **`test_authenticated_user_can_access_uploads`** - Authenticated user accesses endpoints
- **`test_staff_user_has_is_staff_flag`** - Staff user info includes is_staff=True

**Total: 42 tests**

### API & Integration Tests

#### 4. Other Test Files

- **`test_api.py`** - Basic API endpoint tests
- **`test_bearer_authentication.py`** - Bearer token authentication compatibility
- **`test_chunked_upload.py`** - Chunked upload functionality
- **`test_chunked_upload_resilience.py`** - Chunked upload resilience
- **`test_manifest_validator.py`** - Manifest validation
- **`test_orthanc_client.py`** - Orthanc client interactions
- **`test_orthanc_integration.py`** - Orthanc integration
- **`test_auto_verification.py`** - Automatic verification
- **`test_pseudo_id_uniqueness.py`** - Pseudo ID uniqueness validation

## Test Coverage Summary

| Feature | Test File | Coverage |
|---------|-----------|----------|
| IP Whitelist | test_authentication.py | ✓ 6 tests - Single IPs, CIDR ranges, X-Forwarded-For, exemptions |
| Login API | test_authentication.py | ✓ 8 tests - Valid/invalid credentials, missing fields, response format |
| Login Page | test_authentication.py | ✓ 2 tests - Page accessibility, redirect on auth |
| User Creation | test_authentication.py | ✓ 10 tests - Role assignment, duplicates, password generation, email |
| Token Auth | test_authentication.py | ✓ 5 tests - Bearer format, Token format, invalid/missing tokens |
| Permissions | test_authentication.py | ✓ 2 tests - Authenticated access, staff flags |
| File Management | test_file_manager.py | ✓ 19 tests - Directory creation, listing, sizing, cleanup |
| File Storage | test_upload_file_storage.py | ✓ 10 tests - Upload paths, cleanup behavior, preservation |
| Bearer Auth | test_bearer_authentication.py | ✓ Tests Bearer/Token format compatibility |
| Manifest Validation | test_manifest_validator.py | ✓ Tests manifest JSON schema validation |
| DICOM Processing | test_api.py | ✓ Tests DICOM validation and anonymization |
| Chunked Uploads | test_chunked_upload*.py | ✓ Tests resumable large file uploads |

**Total: 91+ tests**

## Running the Tests

### Run All Tests
```bash
# Using make (Docker)
make test

# Using Django
python manage.py test --keepdb
```

### Run Authentication Tests Only
```bash
# All authentication tests
python manage.py test uploads.tests.test_authentication --keepdb

# Specific test class
python manage.py test uploads.tests.test_authentication.IPWhitelistMiddlewareTestCase --keepdb

# Specific test method
python manage.py test uploads.tests.test_authentication.LoginAPITestCase.test_login_with_valid_credentials --keepdb
```

### Run File Management Tests
```bash
python manage.py test uploads.tests.test_file_manager --keepdb
python manage.py test uploads.tests.test_upload_file_storage --keepdb
```

### Run With Coverage Report
```bash
# Install coverage
pip install coverage

# Run with coverage
coverage run --source='uploads' manage.py test --keepdb
coverage report
coverage html  # Generates HTML report
```

### Specific Test Examples

```bash
# IP Whitelist Tests
python manage.py test uploads.tests.test_authentication.IPWhitelistMiddlewareTestCase --keepdb

# Login API Tests
python manage.py test uploads.tests.test_authentication.LoginAPITestCase --keepdb

# User Creation Tests
python manage.py test uploads.tests.test_authentication.CreateUserManagementCommandTestCase --keepdb

# Bearer Token Tests
python manage.py test uploads.tests.test_authentication.TokenAuthenticationTestCase --keepdb
```

## Test Configuration

Tests use the following settings:
- Test database: Separate in-memory SQLite (by default) or preserved with `--keepdb`
- Fixtures: Created in each test's `setUp()` method
- Mocking: Used sparingly; mostly integration tests
- Email backend: Console backend (emails printed to stdout during tests)

## Debugging Tests

### Verbose Output
```bash
python manage.py test uploads.tests.test_authentication --keepdb -v 2
```

### Stop on First Failure
```bash
python manage.py test uploads.tests.test_authentication --keepdb --failfast
```

### Run Single Test in Python Shell
```bash
python manage.py shell
>>> from uploads.tests.test_authentication import LoginAPITestCase
>>> import unittest
>>> suite = unittest.TestLoader().loadTestsFromTestCase(LoginAPITestCase)
>>> unittest.TextTestRunner(verbosity=2).run(suite)
```

## Test Maintenance

- **Keep tests isolated**: Each test should be independent
- **Use setUp/tearDown**: Initialize fixtures in setUp()
- **Clear descriptions**: Test names should indicate what's being tested
- **Avoid timing dependencies**: Don't rely on specific timestamps
- **Mock external services**: Use `@patch` decorator for external APIs
- **Test edge cases**: Test both happy path and error conditions

### Option 3: Using Coverage (Measure Code Coverage)
```bash
coverage run --source='uploads' manage.py test uploads.tests --keepdb
coverage report -m
coverage html  # Generate HTML report
```

## Test Design Principles

1. **Isolation**: Each test uses temporary directories that are cleaned up after execution
2. **Mocking**: Settings are mocked using `@override_settings` to use test directories
3. **Fixtures**: Common setup/teardown logic in `setUp()` and `tearDown()` methods
4. **Real File Operations**: Tests actually create and delete files to verify real behavior
5. **Edge Cases**: Tests cover nonexistent directories, empty directories, and nested structures

## Key Test Scenarios

### File Manager Tests
- Creating directories with various path structures
- Listing files across multiple users and jobs
- Calculating directory sizes recursively
- Deleting directories with error handling
- Handling nonexistent paths gracefully

### Upload Storage Tests
- Verifying tar files are saved to user-specific raw_data directories
- Ensuring multiple uploads from the same user go to the same location
- Confirming UUID naming of uploaded files (not original names)
- Testing UploadJob model stores correct paths

### Task Processing Tests
- Extraction targets job-specific processed_data directories
- Processed data deletion on failure
- Processed data preservation on success
- Raw tar files never auto-deleted after upload

## Expected Test Results

All tests should pass with the implemented feature:
- ✓ 19 file manager utility tests
- ✓ 10 upload/task integration tests
- **Total: 29 tests**

## Integration with CI/CD

These tests are designed to be run:
- In Docker containers via `make test` (production)
- Locally via Django test runner during development
- In CI/CD pipelines before deployment

Tests use `--keepdb` flag to reuse test database across test runs for faster execution.

## Future Test Enhancements

Potential additions:
1. Performance tests for large directory scans
2. Concurrent upload tests (race conditions)
3. Disk space monitoring tests
4. Cleanup scheduling tests
5. Secure deletion tests (overwriting with random data)
6. Encryption tests (if filesystem-level encryption is added)
