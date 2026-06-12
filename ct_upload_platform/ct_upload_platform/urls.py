"""
URL configuration for ct_upload_platform project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from uploads.views import UploadIndexView, UploadAdvancedView, LoginPageView, SignupPageView, LogoutView
from uploads.user_management_views import (
    UserManagementView,
    UserCreateAPIView,
    UserUpdateAPIView,
    UserDeleteAPIView,
)
from uploads.file_management_views import FileManagerView, StudySetDownloadView
from uploads.protocol_views import (
    ProtocolListView,
    ProtocolDetailView,
    ProtocolCreateView,
    ProtocolUpdateView,
    ProtocolDeleteView,
    ProtocolsHubView,
    ScannerProfileListView,
    ScannerProfileCreateView,
    ScannerModelsByManufacturerView,
    ScannerProfileEditView,
    ProtocolGUIView,
    ProtocolSaveAPIView,
    ProtocolRecordsView,
    ExaminationEntryView,
    ExaminationSaveAPIView,
    ExaminationListView,
    ExaminationDeleteView,
    JSONValidatorView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', LoginPageView.as_view(), name='login-page'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('signup/', SignupPageView.as_view(), name='signup-page'),
    path('', UploadAdvancedView.as_view(), name='index'),
    path('upload/', UploadAdvancedView.as_view(), name='upload'),
    path('json-validator/', JSONValidatorView.as_view(), name='json-validator'),
    path('simple/', UploadIndexView.as_view(), name='simple'),
    path('api/v1/', include('uploads.urls')),

    # Examination UI pages
    path('examinations/', ExaminationListView.as_view(), name='examination-list'),
    path('examinations/entry/', ExaminationEntryView.as_view(), name='examination-entry'),
    path('examinations/api/save/', ExaminationSaveAPIView.as_view(), name='examination-save-api'),
    path('examinations/<str:pk>/delete/', ExaminationDeleteView.as_view(), name='examination-delete'),

    # Protocol UI pages (human-facing; not under api/v1/)
    # Order matters: fixed paths before parameterised catch-alls.
    path('protocols/', ProtocolsHubView.as_view(), name='protocols-hub'),
    path('protocols/gui/', ProtocolGUIView.as_view(), name='protocol-gui'),
    path('protocols/records/', ProtocolRecordsView.as_view(), name='protocol-records'),
    path('protocols/api/save/', ProtocolSaveAPIView.as_view(), name='protocol-save-api'),
    path('protocols/<str:protocol_type>/create/', ProtocolCreateView.as_view(), name='protocol-create'),
    path('protocols/<str:protocol_type>/<str:pk>/edit/', ProtocolUpdateView.as_view(), name='protocol-update'),
    path('protocols/<str:protocol_type>/<str:pk>/delete/', ProtocolDeleteView.as_view(), name='protocol-delete'),
    path('protocols/<str:protocol_type>/<str:pk>/', ProtocolDetailView.as_view(), name='protocol-detail'),
    path('protocols/<str:protocol_type>/', ProtocolListView.as_view(), name='protocol-list'),
    path('scanners/', ScannerProfileListView.as_view(), name='scanner-profile-list'),
    path('scanners/create/', ScannerProfileCreateView.as_view(), name='scanner-profile-create'),
    path('scanners/models/', ScannerModelsByManufacturerView.as_view(), name='scanner-models-by-manufacturer'),
    path('scanners/<str:pk>/edit/', ScannerProfileEditView.as_view(), name='scanner-profile-edit'),

    # User management (superuser only)
    path('users/', UserManagementView.as_view(), name='user-management'),
    path('users/api/create/', UserCreateAPIView.as_view(), name='user-create-api'),
    path('users/api/<int:user_id>/update/', UserUpdateAPIView.as_view(), name='user-update-api'),
    path('users/api/<int:user_id>/delete/', UserDeleteAPIView.as_view(), name='user-delete-api'),

    # File manager (superuser only)
    path('file-manager/', FileManagerView.as_view(), name='file-manager'),
    path('file-manager/download/<str:exam_id>/', StudySetDownloadView.as_view(), name='study-set-download'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
