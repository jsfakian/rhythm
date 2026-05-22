"""
URL patterns for the uploads app.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UploadView,
    UploadJobDetailView,
    StudyListView,
    StudyDetailView,
    LoginView,
    LoginPageView,
    SignupView,
)
from .chunked_upload_views import (
    ChunkedUploadInitView,
    ChunkedUploadChunkView,
    ChunkedUploadCompleteView,
    ChunkedUploadProgressView,
    ChunkedUploadCancelView,
    ManifestValidationView,
    ChunkVerificationView,
    UploadProgressView,
)
from .protocol_views import ScannerModelsByManufacturerView
from .protocol_api_views import (
    CTManufacturerViewSet,
    CTScannerModelViewSet,
    ProtocolChoiceCategoryViewSet,
    CTScannerProfileViewSet,
    CTProtocolViewSet,
)

_router = DefaultRouter()
_router.register('manufacturers', CTManufacturerViewSet, basename='manufacturer')
_router.register('scanner-models', CTScannerModelViewSet, basename='scanner-model')
_router.register('protocol-choices', ProtocolChoiceCategoryViewSet, basename='protocol-choice')
_router.register('scanner-profiles', CTScannerProfileViewSet, basename='scanner-profile-api')
_router.register('protocols-api', CTProtocolViewSet, basename='protocol-api')

app_name = 'uploads'

urlpatterns = [
    # Authentication endpoints
    # POST /api/v1/auth/login/ - Login with username/password and get token
    path('auth/login/', LoginView.as_view(), name='login'),
    # POST /api/v1/auth/signup/ - Register a new user and get token
    path('auth/signup/', SignupView.as_view(), name='signup'),
    
    # Upload endpoints - Start with most specific paths first
    
    # POST /api/v1/uploads/ - Create upload
    # GET /api/v1/uploads/ - List uploads
    path('uploads/', UploadView.as_view(), name='upload-list-create'),
    
    # Manifest validation endpoint (MUST come before job_id pattern)
    # POST /api/v1/uploads/validate-manifest/ - Validate manifest.json before upload (EARLY VALIDATION)
    path('uploads/validate-manifest/', ManifestValidationView.as_view(), name='validate-manifest'),
    
    # Chunked upload endpoints (MUST come before job_id pattern)
    # POST /api/v1/uploads/chunked/init/ - Initialize chunked upload
    path('uploads/chunked/init/', ChunkedUploadInitView.as_view(), name='chunked-upload-init'),
    
    # POST /api/v1/uploads/chunked/<session_id>/chunk/ - Upload chunk
    path('uploads/chunked/<str:session_id>/chunk/', ChunkedUploadChunkView.as_view(), name='chunked-upload-chunk'),
    
    # POST /api/v1/uploads/chunked/<session_id>/complete/ - Complete upload
    path('uploads/chunked/<str:session_id>/complete/', ChunkedUploadCompleteView.as_view(), name='chunked-upload-complete'),
    
    # GET /api/v1/uploads/chunked/<session_id>/progress/ - Get progress
    path('uploads/chunked/<str:session_id>/progress/', ChunkedUploadProgressView.as_view(), name='chunked-upload-progress'),
    
    # GET /api/v1/uploads/chunked/<session_id>/status/ - Get detailed status for resume (with chunk verification info)
    path('uploads/chunked/<str:session_id>/status/', UploadProgressView.as_view(), name='chunked-upload-status'),
    
    # POST /api/v1/uploads/chunked/<session_id>/verify/ - Verify chunks (CORRUPTION DETECTION)
    path('uploads/chunked/<str:session_id>/verify/', ChunkVerificationView.as_view(), name='chunk-verify'),
    
    # DELETE /api/v1/uploads/chunked/<session_id>/ - Cancel upload
    path('uploads/chunked/<str:session_id>/', ChunkedUploadCancelView.as_view(), name='chunked-upload-cancel'),
    
    # GET /api/v1/uploads/{job_id}/ - Get upload details (MUST come after static paths)
    # DELETE /api/v1/uploads/{job_id}/ - Delete upload (admin only)
    path('uploads/<str:job_id>/', UploadJobDetailView.as_view(), name='upload-detail'),
    
    # Study endpoints
    # GET /api/v1/studies/ - List studies with filters
    path('studies/', StudyListView.as_view(), name='study-list'),
    
    # GET /api/v1/studies/{pseudo_study_uid}/ - Get study details
    path('studies/<str:study_uid>/', StudyDetailView.as_view(), name='study-detail'),

    # GET /api/v1/scanners/models/?manufacturer_id=<id> - cascade dropdown (used by JS)
    path(
        'scanners/models/',
        ScannerModelsByManufacturerView.as_view(),
        name='scanner-models-by-manufacturer',
    ),

    # REST API router (DRF ViewSets)
    path('', include(_router.urls)),
]
