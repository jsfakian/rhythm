"""
URL configuration for ct_upload_platform project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include, reverse_lazy
from uploads.views import (
    UploadIndexView, UploadAdvancedView, HomeView, LoginPageView, SignupPageView, LogoutView,
    VerifyEmailView,
)
from uploads.forms import InactiveAllowedPasswordResetForm
from uploads.user_management_views import (
    UserManagementView,
    UserCreateAPIView,
    UserUpdateAPIView,
    UserDeleteAPIView,
)
from uploads.file_management_views import FileManagerView, StudySetDownloadView
from uploads.twofactor_views import (
    SecuritySettingsView,
    TOTPSetupInitiateView,
    TOTPSetupConfirmView,
)
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
    ScannerProfileDeleteView,
    ProtocolGUIView,
    ProtocolSaveAPIView,
    ProtocolRecordsView,
    ExaminationEntryView,
    ExaminationSaveAPIView,
    ExaminationListView,
    ExaminationDeleteView,
    JSONValidatorView,
    UploadJobListView,
    UploadJobDeleteView,
    AutomatedUploadView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', LoginPageView.as_view(), name='login-page'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('signup/', SignupPageView.as_view(), name='signup-page'),

    # Signup email verification (admin-triggered send from User Management)
    path('verify-email/<uidb64>/<token>/', VerifyEmailView.as_view(), name='verify-email'),

    # Password reset flow (built-in Django auth views, custom templates)
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='uploads/password_reset.html',
            email_template_name='uploads/password_reset_email.txt',
            subject_template_name='uploads/password_reset_subject.txt',
            success_url=reverse_lazy('password-reset-done'),
            form_class=InactiveAllowedPasswordResetForm,
        ),
        name='password-reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(template_name='uploads/password_reset_done.html'),
        name='password-reset-done',
    ),
    path(
        'password-reset/confirm/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='uploads/password_reset_confirm.html',
            success_url=reverse_lazy('password-reset-complete'),
        ),
        name='password-reset-confirm',
    ),
    path(
        'password-reset/complete/',
        auth_views.PasswordResetCompleteView.as_view(template_name='uploads/password_reset_complete.html'),
        name='password-reset-complete',
    ),

    path('', HomeView.as_view(), name='index'),
    path('upload/', UploadAdvancedView.as_view(), name='upload'),
    path('json-validator/', JSONValidatorView.as_view(), name='json-validator'),
    path('simple/', UploadIndexView.as_view(), name='simple'),
    path('api/v1/', include('uploads.urls')),

    # Examination UI pages
    path('examinations/', ExaminationListView.as_view(), name='examination-list'),
    path('examinations/entry/', ExaminationEntryView.as_view(), name='examination-entry'),
    path('examinations/api/save/', ExaminationSaveAPIView.as_view(), name='examination-save-api'),
    path('examinations/<str:pk>/delete/', ExaminationDeleteView.as_view(), name='examination-delete'),

    # My Uploads (bulk/automated upload job tracking)
    path('my-uploads/', UploadJobListView.as_view(), name='upload-job-list'),
    path('my-uploads/<str:pk>/delete/', UploadJobDeleteView.as_view(), name='upload-job-delete'),

    # Automated (bulk batch) upload
    path('automated-upload/', AutomatedUploadView.as_view(), name='automated-upload'),

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
    path('scanners/<str:pk>/delete/', ScannerProfileDeleteView.as_view(), name='scanner-profile-delete'),

    # User management (superuser only)
    path('users/', UserManagementView.as_view(), name='user-management'),
    path('users/api/create/', UserCreateAPIView.as_view(), name='user-create-api'),
    path('users/api/<int:user_id>/update/', UserUpdateAPIView.as_view(), name='user-update-api'),
    path('users/api/<int:user_id>/delete/', UserDeleteAPIView.as_view(), name='user-delete-api'),

    # File manager (superuser only)
    path('file-manager/', FileManagerView.as_view(), name='file-manager'),
    path('file-manager/download/<str:exam_id>/', StudySetDownloadView.as_view(), name='study-set-download'),

    # Self-service security settings (2FA)
    path('account/security/', SecuritySettingsView.as_view(), name='security-settings'),
    path('account/security/2fa/setup/', TOTPSetupInitiateView.as_view(), name='totp-setup-initiate'),
    path('account/security/2fa/confirm/', TOTPSetupConfirmView.as_view(), name='totp-setup-confirm'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
