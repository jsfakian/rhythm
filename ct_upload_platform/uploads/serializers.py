"""
Serializers for the uploads app.
"""

from rest_framework import serializers
from django.conf import settings
from .models import UploadJob, StudyMapping, Patient, Annotation, AuditLog, ChunkedUpload, UploadChunk


class PatientSerializer(serializers.ModelSerializer):
    """Serializer for Patient model."""
    
    class Meta:
        model = Patient
        fields = ['id', 'pseudo_id', 'sex', 'age_at_first_acquisition', 'cohort_tag', 'created_at']
        read_only_fields = ['id', 'created_at']


class UploadJobSerializer(serializers.ModelSerializer):
    """
    Serializer for UploadJob.
    Includes image_count from ingested studies.
    """
    orthanc_study_ids = serializers.SerializerMethodField()
    image_count = serializers.SerializerMethodField()
    
    class Meta:
        model = UploadJob
        fields = ['id', 'status', 'submitted_at', 'completed_at', 'error_report', 'image_count', 'orthanc_study_ids']
        read_only_fields = ['id', 'status', 'submitted_at', 'completed_at', 'error_report']
    
    def get_orthanc_study_ids(self, obj):
        """Get list of Orthanc study IDs from study mappings in this job."""
        return list(obj.study_mappings.values_list('orthanc_study_id', flat=True))
    
    def get_image_count(self, obj):
        """Estimate image count from the error_report or stored data."""
        # This is a placeholder; actual count would come from the task completion report
        if obj.error_report and isinstance(obj.error_report, dict):
            return {
                'total': obj.error_report.get('total_images', 0),
                'ingested': obj.error_report.get('ingested_images', 0),
                'failed': obj.error_report.get('failed_images', 0),
            }
        return {'total': 0, 'ingested': 0, 'failed': 0}


class AnnotationSerializer(serializers.ModelSerializer):
    """Serializer for Annotation model."""
    
    class Meta:
        model = Annotation
        fields = ['id', 'annotation_uid', 'orthanc_instance_id', 'annotator_id', 'annotation_date', 'type', 'label', 'annotation_data', 'annotation_file']
        read_only_fields = ['id']


class StudyMappingSerializer(serializers.ModelSerializer):
    """
    Serializer for StudyMapping.
    Provides mapping data plus Orthanc references.
    """
    patient_pseudo_id = serializers.CharField(source='patient.pseudo_id', read_only=True)
    patient = PatientSerializer(read_only=True)
    annotations = AnnotationSerializer(many=True, read_only=True)
    qido_url = serializers.SerializerMethodField()
    wado_url = serializers.SerializerMethodField()
    
    class Meta:
        model = StudyMapping
        fields = [
            'id', 'pseudo_study_uid', 'orthanc_study_id', 'acquisition_date',
            'clinical_indication', 'pathology_labels', 'contrast_used', 'contrast_agent',
            'source_institution', 'notes', 'created_at',
            'patient_pseudo_id', 'patient', 'annotations',
            'qido_url', 'wado_url'
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_qido_url(self, obj):
        """Generate QIDO URL for Orthanc DICOMweb query."""
        orthanc_url = settings.ORTHANC_BASE_URL
        return f"{orthanc_url}/dicom-web/studies/{obj.orthanc_study_id}/series"
    
    def get_wado_url(self, obj):
        """Generate WADO URL for Orthanc DICOMweb retrieval."""
        orthanc_url = settings.ORTHANC_BASE_URL
        return f"{orthanc_url}/dicom-web/studies/{obj.orthanc_study_id}"


class AuditLogSerializer(serializers.ModelSerializer):
    """Serializer for AuditLog model."""
    
    class Meta:
        model = AuditLog
        fields = ['id', 'upload_job', 'event_type', 'actor_id', 'detail', 'occurred_at']
        read_only_fields = ['id', 'occurred_at']


class UploadChunkSerializer(serializers.ModelSerializer):
    """Serializer for UploadChunk model."""
    
    class Meta:
        model = UploadChunk
        fields = ['chunk_number', 'chunk_size', 'chunk_hash', 'uploaded_at', 'verified']
        read_only_fields = ['chunk_size', 'chunk_hash', 'uploaded_at', 'verified']


class ChunkedUploadSerializer(serializers.ModelSerializer):
    """
    Serializer for ChunkedUpload.
    Includes progress information and chunk list.
    """
    chunks = UploadChunkSerializer(many=True, read_only=True)
    progress_percent = serializers.ReadOnlyField()
    is_complete = serializers.ReadOnlyField()
    
    class Meta:
        model = ChunkedUpload
        fields = [
            'id', 'filename', 'status', 'total_size', 'total_chunks',
            'uploaded_chunks', 'chunk_size', 'progress_percent', 'is_complete',
            'file_hash', 'created_at', 'updated_at', 'completed_at', 'expires_at',
            'chunks'
        ]
        read_only_fields = [
            'id', 'status', 'uploaded_chunks', 'file_hash', 'temp_dir',
            'created_at', 'updated_at', 'completed_at', 'expires_at'
        ]


class ChunkedUploadInitSerializer(serializers.Serializer):
    """Serializer for initiating a chunked upload."""
    filename = serializers.CharField(max_length=512)
    total_size = serializers.IntegerField(min_value=1)
    chunk_size = serializers.IntegerField(
        default=10485760,  # 10MB
        min_value=1,
        help_text='Size of each chunk in bytes'
    )
    file_hash = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
        help_text='Expected SHA256 hash of complete file (optional)'
    )


class ChunkedUploadCompleteSerializer(serializers.Serializer):
    """Serializer for completing a chunked upload."""
    file_hash = serializers.CharField(
        max_length=128,
        help_text='SHA256 hash of the complete file for verification'
    )

class SignupSerializer(serializers.Serializer):
    """Serializer for new user registration."""
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(max_length=128, write_only=True)
    password2 = serializers.CharField(max_length=128, write_only=True, label='Confirm password')
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    institution = serializers.CharField(max_length=256)
    department = serializers.CharField(max_length=256, required=False, allow_blank=True, default='')
    professional_role = serializers.ChoiceField(choices=[
        'radiologist', 'medical_physicist', 'radiographer', 'pacs_it',
        'research_coordinator', 'principal_investigator', 'dpo', 'other',
    ])
    professional_role_other = serializers.CharField(max_length=256, required=False, allow_blank=True, default='')
    terms_accepted = serializers.BooleanField()

    def validate_username(self, value):
        from django.contrib.auth.models import User
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('A user with this username already exists.')
        return value

    def validate_email(self, value):
        from django.contrib.auth.models import User
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_terms_accepted(self, value):
        if not value:
            raise serializers.ValidationError('You must accept the terms of use to register.')
        return value

    def validate(self, data):
        if data['password'] != data['password2']:
            raise serializers.ValidationError({'password2': 'Passwords do not match.'})
        from django.contrib.auth.password_validation import validate_password
        from django.contrib.auth.models import User
        try:
            validate_password(data['password'], User())
        except Exception as exc:
            raise serializers.ValidationError({'password': list(exc.messages)})
        if data.get('professional_role') == 'other' and not data.get('professional_role_other', '').strip():
            raise serializers.ValidationError({'professional_role_other': 'Please specify your professional role.'})
        return data

    def create(self, validated_data):
        from django.contrib.auth.models import User
        from django.utils import timezone
        from .models import UserProfile
        validated_data.pop('password2')
        password = validated_data.pop('password')
        institution = validated_data.pop('institution')
        department = validated_data.pop('department', '')
        professional_role = validated_data.pop('professional_role')
        professional_role_other = validated_data.pop('professional_role_other', '')
        terms_accepted = validated_data.pop('terms_accepted')

        from .models import Institution
        inst_obj = Institution.objects.filter(name=institution).first()
        site_code = inst_obj.site_code if inst_obj else UserProfile.assign_site_code(institution)

        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=password,
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
        )
        UserProfile.objects.create(
            user=user,
            institution=institution,
            department=department,
            professional_role=professional_role,
            professional_role_other=professional_role_other,
            site_code=site_code,
            terms_accepted=terms_accepted,
            terms_accepted_at=timezone.now() if terms_accepted else None,
        )
        return user


class LoginSerializer(serializers.Serializer):
    """Serializer for user login with username and password."""
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, write_only=True)


class TokenResponseSerializer(serializers.Serializer):
    """Serializer for login response containing token and user info."""
    token = serializers.CharField()
    user_id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    is_staff = serializers.BooleanField()


class RefreshTokenSerializer(serializers.Serializer):
    """Serializer for refreshing authentication token."""
    token = serializers.CharField()