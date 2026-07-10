"""
Views for the uploads app implementing REST API endpoints and upload UI.
"""

import logging
import os
import shutil
import uuid
from io import BytesIO
from pathlib import Path

import magic
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from .auth import build_auth_response
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.db.models import Q, Count, Prefetch
from django.shortcuts import redirect
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from rest_framework import viewsets, status, views
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.response import Response

from .models import UploadJob, StudyMapping, Annotation
from .serializers import (
    UploadJobSerializer, StudyMappingSerializer, AnnotationSerializer,
    LoginSerializer, TokenResponseSerializer, SignupSerializer
)
from .tasks import process_upload_job
from .file_manager import get_raw_data_user_dir

# Configure logging
logger = logging.getLogger(__name__)


class StandardResultsSetPagination(PageNumberPagination):
    """Standard pagination class for list endpoints."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class UploadView(views.APIView):
    """Handle tar file uploads and list uploaded jobs."""
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    
    def post(self, request):
        """
        Upload a tar file and create an UploadJob.
        
        Expected fields:
        - tar_file (required): tar or tar.gz file
        - uploader_id (optional): user identifier, defaults to request.user.username
        """
        # Get the tar file and uploader_id from request
        tar_file = request.FILES.get('tar_file')
        uploader_id = request.data.get('uploader_id', request.user.username)
        
        if not tar_file:
            return Response(
                {'error': 'tar_file is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate file size
        file_size_mb = tar_file.size / (1024 * 1024)
        if file_size_mb > settings.MAX_UPLOAD_SIZE_MB:
            return Response(
                {
                    'error': f'File size {file_size_mb:.2f}MB exceeds maximum {settings.MAX_UPLOAD_SIZE_MB}MB',
                    'code': 'file_too_large'
                },
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            )
        
        # Validate file is a tar by checking magic bytes
        tar_file.seek(0)
        file_header = tar_file.read(512)
        tar_file.seek(0)
        
        # Check for tar/gzip magic bytes
        is_tar = file_header[257:262] == b'ustar'  # TAR magic
        is_gzip = file_header[:2] == b'\x1f\x8b'  # GZIP magic
        
        if not (is_tar or is_gzip):
            # Try python-magic if available
            try:
                mime_type = magic.from_buffer(file_header, mime=True)
                if mime_type not in ['application/x-tar', 'application/gzip', 'application/x-gzip']:
                    return Response(
                        {'error': 'File must be a tar or tar.gz archive', 'code': 'invalid_file_type'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as e:
                logger.error(f"Magic check failed: {e}")
                return Response(
                    {'error': 'Unable to validate file type', 'code': 'validation_error'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Save tar to raw_data directory organized by user
        try:
            # Get raw_data/{uploader_id} directory (creates if doesn't exist)
            raw_data_dir = get_raw_data_user_dir(uploader_id)
            
            # Save tar file with UUID name
            tar_filename = f"{uuid.uuid4()}.tar"
            tar_local_path = raw_data_dir / tar_filename
            
            tar_file.seek(0)
            with open(tar_local_path, 'wb') as f:
                f.write(tar_file.read())
            
        except Exception as e:
            logger.error(f"Failed to save tar to local storage: {e}")
            return Response(
                {'error': f'Failed to save upload: {str(e)}', 'code': 'upload_failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Create UploadJob
        try:
            job = UploadJob.objects.create(
                uploader_id=uploader_id,
                tar_temp_path=str(tar_local_path),
                status='PENDING'
            )
            
            # Enqueue the processing task
            process_upload_job.delay(str(job.id))
            
            # Return 202 Accepted with job details
            return Response(
                {
                    'job_id': str(job.id),
                    'status': job.status,
                    'poll_url': f'/api/v1/uploads/{job.id}/',
                },
                status=status.HTTP_202_ACCEPTED
            )
        except Exception as e:
            logger.error(f"Failed to create upload job: {e}")
            # Clean up the uploaded file on error
            try:
                os.unlink(tar_local_path)
            except Exception:
                pass
            return Response(
                {'error': f'Failed to create upload job: {str(e)}', 'code': 'creation_failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def get(self, request):
        """
        Return paginated list of UploadJob.
        Admin sees all, non-admin users see only their own.
        """
        if request.user.is_staff:
            jobs = UploadJob.objects.all()
        else:
            jobs = UploadJob.objects.filter(uploader_id=request.user.username)
        
        jobs = jobs.order_by('-submitted_at')
        
        # Paginate
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(jobs, request)
        if page is not None:
            serializer = UploadJobSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = UploadJobSerializer(jobs, many=True)
        return Response(serializer.data)


class UploadJobDetailView(views.APIView):
    """Get details of a specific upload job or delete it."""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, job_id):
        """Return UploadJobSerializer for the given job."""
        try:
            job = UploadJob.objects.get(id=job_id)
        except UploadJob.DoesNotExist:
            return Response(
                {'error': 'Upload job not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check permissions: only accessible by job's uploader or admin
        if not (request.user.is_staff or request.user.username == job.uploader_id):
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = UploadJobSerializer(job)
        return Response(serializer.data)
    
    def delete(self, request, job_id):
        """
        Delete an upload job (admin only).
        - Admin only
        - Cancels PENDING jobs, deletes tar from local filesystem
        - Returns 204
        """
        # Check admin permission
        if not request.user.is_staff:
            return Response(
                {'error': 'Only administrators can delete upload jobs'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            job = UploadJob.objects.get(id=job_id)
        except UploadJob.DoesNotExist:
            return Response(
                {'error': 'Upload job not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Only allow deletion of PENDING jobs
        if job.status != 'PENDING':
            return Response(
                {'error': f'Cannot delete job with status {job.status}. Only PENDING jobs can be deleted.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Delete tar from local filesystem
        if job.tar_temp_path:
            try:
                tar_path = Path(job.tar_temp_path)
                if tar_path.exists():
                    os.unlink(tar_path)
            except Exception as e:
                logger.error(f"Failed to delete tar file {job.tar_temp_path}: {e}")
                # Continue with deletion even if file delete fails
        
        # Delete the job
        job.delete()
        
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudyListView(views.APIView):
    """List studies with filtering and pagination."""
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    
    def get(self, request):
        """
        Return paginated list of Studies.
        Filterable by: pseudo_id, acquisition_date_from, acquisition_date_to, cohort_tag
        Ordered by acquisition_date desc
        """
        studies = StudyMapping.objects.select_related('patient').prefetch_related('annotations')
        
        # Apply filters
        pseudo_id = request.query_params.get('pseudo_id')
        if pseudo_id:
            studies = studies.filter(patient__pseudo_id=pseudo_id)
        
        acquisition_date_from = request.query_params.get('acquisition_date_from')
        if acquisition_date_from:
            studies = studies.filter(acquisition_date__gte=acquisition_date_from)
        
        acquisition_date_to = request.query_params.get('acquisition_date_to')
        if acquisition_date_to:
            studies = studies.filter(acquisition_date__lte=acquisition_date_to)
        
        cohort_tag = request.query_params.get('cohort_tag')
        if cohort_tag:
            studies = studies.filter(cohort_tag=cohort_tag)
        
        # Order by acquisition_date descending
        studies = studies.order_by('-acquisition_date')
        
        # Paginate
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(studies, request)
        if page is not None:
            serializer = StudyMappingSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = StudyMappingSerializer(studies, many=True)
        return Response(serializer.data)


class StudyDetailView(views.APIView):
    """Get details of a specific study."""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, study_uid):
        """Return StudyMappingSerializer for the given pseudo_study_uid."""
        try:
            study = StudyMapping.objects.select_related('patient').prefetch_related(
                'annotations'
            ).get(pseudo_study_uid=study_uid)
        except StudyMapping.DoesNotExist:
            return Response(
                {'error': 'Study not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = StudyMappingSerializer(study)
        return Response(serializer.data)


class UploadIndexView(TemplateView):
    """Serve the upload UI at the root path."""
    template_name = 'uploads/index.html'
    
    def get_context_data(self, **kwargs):
        """Add context for the template."""
        context = super().get_context_data(**kwargs)
        context['max_upload_size_mb'] = settings.MAX_UPLOAD_SIZE_MB
        return context

class UploadAdvancedView(LoginRequiredMixin, TemplateView):
    """Serve the advanced multi-page upload UI."""
    login_url = '/login/'
    template_name = 'uploads/advanced.html'

    def get_context_data(self, **kwargs):
        """Add context for the template."""
        context = super().get_context_data(**kwargs)
        context['max_upload_size_mb'] = settings.MAX_UPLOAD_SIZE_MB
        return context


class HomeView(LoginRequiredMixin, TemplateView):
    """Landing page shown after login — prompts user to pick a section from the sidebar."""
    login_url = '/login/'
    template_name = 'uploads/home.html'


class LoginView(views.APIView):
    """
    API endpoint for user login.
    
    POST /api/v1/auth/login/
    Body: {"username": "...", "password": "..."}
    Response: {"token": "...", "user_id": 1, "username": "...", ...}
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Authenticate user and return token."""
        serializer = LoginSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(
                {'error': 'Invalid request', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        username = serializer.validated_data.get('username')
        password = serializer.validated_data.get('password')
        
        user = authenticate(username=username, password=password)

        if not user:
            # authenticate() also returns None for a correct password on an
            # inactive (pending-verification) account — check separately so we
            # can give those users an accurate message.
            unverified = User.objects.filter(username=username, is_active=False).first()
            if unverified and unverified.check_password(password):
                logger.warning(f"Login blocked for unverified account: {username}")
                return Response(
                    {'error': 'Your account is pending verification. An administrator must verify your email before you can sign in.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            logger.warning(f"Login failed for user: {username}")
            return Response(
                {'error': 'Invalid username or password'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Get or create token
        token, created = Token.objects.get_or_create(user=user)

        # Create a Django session so session-authenticated views work too
        auth_login(request, user)

        logger.info(f"User logged in: {username}")
        
        return Response(TokenResponseSerializer(build_auth_response(user, token)).data, status=status.HTTP_200_OK)


class LoginPageView(TemplateView):
    """Serve the login page."""
    template_name = 'uploads/login.html'
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        """Redirect to main page if already logged in."""
        if request.user.is_authenticated:
            return redirect('/')
        return super().get(request, *args, **kwargs)


class SignupView(views.APIView):
    """
    API endpoint for user registration.

    POST /api/v1/auth/signup/
    Body: {"username": "...", "email": "...", "password": "...", "password2": "..."}
    Response: {"token": "...", "user_id": 1, "username": "...", ...}
    """
    permission_classes = [AllowAny]

    def post(self, request):
        """Register a new user pending admin-triggered email verification."""
        serializer = SignupSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {'error': 'Invalid request', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = serializer.save()

        logger.info(f"New user registered (pending verification): {user.username}")

        return Response(
            {
                'username': user.username,
                'email': user.email,
                'message': (
                    'Account created. An administrator will verify your account and '
                    'email you a confirmation link before you can sign in.'
                ),
            },
            status=status.HTTP_201_CREATED,
        )


class SignupPageView(TemplateView):
    """Serve the signup page."""
    template_name = 'uploads/signup.html'
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        """Redirect to main page if already logged in."""
        if request.user.is_authenticated:
            return redirect('/')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from .models import Institution
        ctx = super().get_context_data(**kwargs)
        ctx['institutions'] = list(Institution.objects.values('name', 'site_code'))
        return ctx


class LogoutView(View):
    def get(self, request):
        auth_logout(request)
        return redirect('/login/')

    def post(self, request):
        auth_logout(request)
        return redirect('/login/')


class VerifyEmailView(TemplateView):
    """Activate an account when the user visits their emailed verification link."""
    template_name = 'uploads/email_verified.html'
    permission_classes = [AllowAny]

    def get(self, request, uidb64, token, *args, **kwargs):
        from django.utils.encoding import force_str
        from django.utils.http import urlsafe_base64_decode
        from .tokens import email_verification_token

        verified = False
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is not None and email_verification_token.check_token(user, token):
            user.is_active = True
            user.save(update_fields=['is_active'])
            profile = getattr(user, 'profile', None)
            if profile is not None:
                profile.email_verified = True
                profile.email_verified_at = timezone.now()
                profile.save(update_fields=['email_verified', 'email_verified_at'])
            logger.info(f"Email verified, account activated: {user.username}")
            verified = True

        return self.render_to_response({'verified': verified})
