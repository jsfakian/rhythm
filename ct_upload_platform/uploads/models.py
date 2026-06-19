"""
Models for the uploads app.
No PHI (Personally Identifiable Health Information) is stored directly.
"""

import uuid
from django.db import models, transaction
from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator


class Patient(models.Model):
    """
    De-identified patient record. Stores only pseudo_id, not real patient name or DOB.
    """
    SEX_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
        ('U', 'Unknown'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pseudo_id = models.CharField(
        max_length=64,
        unique=True,
        help_text='De-identified patient identifier'
    )
    sex = models.CharField(
        max_length=1,
        choices=SEX_CHOICES,
        null=True,
        blank=True
    )
    age_at_first_acquisition = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MaxValueValidator(150)]
    )
    cohort_tag = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        help_text='Research cohort identifier'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['pseudo_id']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Patient {self.pseudo_id}"


class UploadJob(models.Model):
    """
    Tracks a bulk upload job through processing stages.
    """
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETE', 'Complete'),
        ('FAILED', 'Failed'),
        ('PARTIAL', 'Partial'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploader_id = models.CharField(
        max_length=128,
        help_text='Identifier of the user who uploaded'
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    tar_temp_path = models.CharField(
        max_length=512,
        blank=True,
        help_text='Local temp directory path where tar is extracted'
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    manifest_raw = models.JSONField(
        null=True,
        blank=True,
        help_text='Original manifest JSON for audit trail'
    )
    error_report = models.JSONField(
        null=True,
        blank=True,
        help_text='Structured list of per-image errors and warnings'
    )
    anonymization_report = models.JSONField(
        null=True,
        blank=True,
        help_text='Report on GDPR anonymization and pseudo ID generation per image'
    )

    class Meta:
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['uploader_id']),
            models.Index(fields=['submitted_at']),
        ]

    def __str__(self):
        return f"UploadJob {self.id} ({self.status})"


class StudyMapping(models.Model):
    """
    Bridge between Django's pseudonymized world and Orthanc's internal identifiers.
    Maps a study to an Orthanc StudyInstanceUID and stores metadata.
    Orthanc is the authoritative source for DICOM files.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name='study_mappings'
    )
    upload_job = models.ForeignKey(
        UploadJob,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='study_mappings'
    )
    pseudo_study_uid = models.CharField(
        max_length=256,
        unique=True,
        help_text='Pseudonymized DICOM Study Instance UID from manifest'
    )
    orthanc_study_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text='Orthanc internal UUID for this study'
    )
    acquisition_date = models.DateField(help_text='Date of image acquisition')
    clinical_indication = models.TextField(
        blank=True,
        help_text='Clinical reason for imaging'
    )
    pathology_labels = models.JSONField(
        default=list,
        blank=True,
        help_text='List of known pathology labels'
    )
    contrast_used = models.BooleanField(
        default=False,
        help_text='Whether contrast agent was used'
    )
    contrast_agent = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        help_text='Name of contrast agent used'
    )
    source_institution = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        help_text='Source hospital or imaging center'
    )
    notes = models.TextField(
        blank=True,
        help_text='Additional notes about the study'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-acquisition_date']
        indexes = [
            models.Index(fields=['pseudo_study_uid']),
            models.Index(fields=['patient']),
            models.Index(fields=['acquisition_date']),
            models.Index(fields=['orthanc_study_id']),
        ]

    def __str__(self):
        return f"StudyMapping {self.pseudo_study_uid} ({self.patient.pseudo_id})"


class Image(models.Model):
    """
    Individual DICOM image instance within a study.
    Tracks metadata and Orthanc identifiers for each image file.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    study_mapping = models.ForeignKey(
        StudyMapping,
        on_delete=models.CASCADE,
        related_name='images'
    )
    filename = models.CharField(
        max_length=256,
        help_text='Original DICOM filename'
    )
    orthanc_instance_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text='Orthanc SOPInstanceUID for this image'
    )
    sop_instance_uid = models.CharField(
        max_length=256,
        null=True,
        blank=True,
        help_text='DICOM SOPInstanceUID'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['filename']
        indexes = [
            models.Index(fields=['study_mapping']),
            models.Index(fields=['orthanc_instance_id']),
            models.Index(fields=['sop_instance_uid']),
        ]

    def __str__(self):
        return f"Image {self.filename} ({self.orthanc_instance_id})"


class Annotation(models.Model):
    """
    Annotation on an image (segmentation, bounding box, landmark, or classification).
    References an Orthanc image via SOPInstanceUID.
    """
    ANNOTATION_TYPES = [
        ('SEGMENTATION', 'Segmentation'),
        ('BOUNDING_BOX', 'Bounding Box'),
        ('LANDMARK', 'Landmark'),
        ('CLASSIFICATION', 'Classification'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    study_mapping = models.ForeignKey(
        StudyMapping,
        on_delete=models.CASCADE,
        related_name='annotations'
    )
    orthanc_instance_id = models.CharField(
        max_length=256,
        help_text='Orthanc instance UUID this annotation targets'
    )
    annotation_uid = models.CharField(
        max_length=256,
        help_text='Unique identifier for the annotation'
    )
    annotator_id = models.CharField(
        max_length=128,
        help_text='Identifier of the annotator'
    )
    annotation_date = models.DateField(
        null=True,
        blank=True,
        help_text='Date of annotation'
    )
    type = models.CharField(
        max_length=16,
        choices=ANNOTATION_TYPES,
        help_text='Type of annotation'
    )
    label = models.CharField(
        max_length=256,
        help_text='Label or description of annotation'
    )
    annotation_data = models.JSONField(
        null=True,
        blank=True,
        help_text='Inline annotation payload'
    )
    annotation_file = models.FileField(
        null=True,
        blank=True,
        help_text='Annotation file stored via Django FileStorage'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['annotation_date']
        indexes = [
            models.Index(fields=['study_mapping']),
            models.Index(fields=['annotation_uid']),
            models.Index(fields=['annotator_id']),
            models.Index(fields=['orthanc_instance_id']),
        ]

    def __str__(self):
        return f"Annotation {self.annotation_uid} ({self.type})"


class AuditLog(models.Model):
    """
    Audit trail of all pipeline events for compliance and debugging.
    """
    EVENT_TYPES = [
        ('SUBMIT', 'Submit'),
        ('VALIDATE_OK', 'Validation OK'),
        ('VALIDATE_FAIL', 'Validation Failed'),
        ('IMAGE_PUSH_OK', 'Image Push OK'),
        ('IMAGE_PUSH_FAIL', 'Image Push Failed'),
        ('COMPLETE', 'Job Complete'),
        ('FAILED', 'Job Failed'),
        ('PARTIAL', 'Job Partial Success'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    upload_job = models.ForeignKey(
        UploadJob,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    event_type = models.CharField(
        max_length=64,
        choices=EVENT_TYPES,
        help_text='Type of event'
    )
    actor_id = models.CharField(
        max_length=128,
        help_text='Pseudonymized uploader/actor'
    )
    detail = models.JSONField(
        null=True,
        blank=True,
        help_text='Event-specific payload'
    )
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['upload_job']),
            models.Index(fields=['event_type']),
            models.Index(fields=['actor_id']),
            models.Index(fields=['occurred_at']),
        ]

    def __str__(self):
        return f"AuditLog {self.event_type} at {self.occurred_at}"


class ChunkedUpload(models.Model):
    """
    Tracks a large file upload split into chunks.
    Supports resumable uploads for files > 50GB.
    """
    UPLOAD_STATUS_CHOICES = [
        ('INITIATED', 'Initiated'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploader_id = models.CharField(
        max_length=128,
        help_text='Identifier of the user uploading'
    )
    status = models.CharField(
        max_length=16,
        choices=UPLOAD_STATUS_CHOICES,
        default='INITIATED'
    )
    filename = models.CharField(
        max_length=512,
        help_text='Original filename of the uploaded file'
    )
    total_size = models.BigIntegerField(
        help_text='Total file size in bytes'
    )
    total_chunks = models.PositiveIntegerField(
        help_text='Total number of chunks'
    )
    uploaded_chunks = models.PositiveIntegerField(
        default=0,
        help_text='Number of chunks successfully uploaded'
    )
    chunk_size = models.PositiveIntegerField(
        default=10485760,  # 10MB default
        help_text='Size of each chunk in bytes'
    )
    file_hash = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        help_text='SHA256 hash of complete file for integrity verification'
    )
    temp_dir = models.CharField(
        max_length=512,
        help_text='Temporary directory path where chunks are stored'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Timestamp when upload was completed'
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Auto-delete incomplete uploads after this time'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['uploader_id']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f"ChunkedUpload {self.id} ({self.status}) - {self.filename}"

    @property
    def progress_percent(self):
        """Calculate upload progress as percentage."""
        if self.total_chunks == 0:
            return 0
        return int((self.uploaded_chunks / self.total_chunks) * 100)

    @property
    def is_complete(self):
        """Check if all chunks have been uploaded."""
        return self.uploaded_chunks == self.total_chunks

    @classmethod
    def _create_upload_job_from_chunked_upload(cls, chunked_upload, tar_path):
        """
        Create an UploadJob from a completed ChunkedUpload.

        Args:
            chunked_upload: ChunkedUpload instance
            tar_path: Path to the assembled tar file

        Returns:
            UploadJob instance
        """
        from .tasks import process_upload_job

        job = UploadJob.objects.create(
            uploader_id=chunked_upload.uploader_id,
            tar_temp_path=tar_path,
            status='PENDING'
        )

        # Enqueue processing
        process_upload_job.delay(str(job.id))

        return job


class UploadChunk(models.Model):
    """
    Individual chunk of a chunked upload.
    Tracks chunk metadata and integrity with SHA256 and CRC32 hashes.
    Supports automatic verification during upload with corruption detection and resume.
    """
    # Verification status choices
    VERIFICATION_PENDING = 'PENDING'
    VERIFICATION_VERIFIED = 'VERIFIED'
    VERIFICATION_CORRUPTED = 'CORRUPTED'
    VERIFICATION_NEEDS_REUPLOAD = 'NEEDS_REUPLOAD'
    
    VERIFICATION_STATUS_CHOICES = [
        (VERIFICATION_PENDING, 'Pending verification'),
        (VERIFICATION_VERIFIED, 'Verified successfully'),
        (VERIFICATION_CORRUPTED, 'Verification failed - corrupted'),
        (VERIFICATION_NEEDS_REUPLOAD, 'Needs reupload'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chunked_upload = models.ForeignKey(
        ChunkedUpload,
        on_delete=models.CASCADE,
        related_name='chunks'
    )
    chunk_number = models.PositiveIntegerField(
        help_text='Sequential chunk number (0-based)'
    )
    chunk_size = models.BigIntegerField(
        help_text='Actual size of this chunk in bytes'
    )
    chunk_hash = models.CharField(
        max_length=128,
        help_text='SHA256 hash of chunk for integrity verification'
    )
    chunk_crc32 = models.CharField(
        max_length=8,
        null=True,
        blank=True,
        help_text='CRC32 checksum of chunk for quick corruption detection'
    )
    file_path = models.CharField(
        max_length=512,
        help_text='Path to chunk file on disk'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    verified = models.BooleanField(
        default=False,
        help_text='Whether chunk integrity has been verified (deprecated - use verification_status)'
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default=VERIFICATION_PENDING,
        help_text='Current verification status of the chunk'
    )
    verification_error = models.TextField(
        blank=True,
        null=True,
        help_text='Error details if verification failed'
    )
    verification_timestamp = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Timestamp when verification was performed'
    )

    class Meta:
        ordering = ['chunk_number']
        indexes = [
            models.Index(fields=['chunked_upload', 'chunk_number']),
            models.Index(fields=['uploaded_at']),
            models.Index(fields=['verification_status']),
        ]
        unique_together = [['chunked_upload', 'chunk_number']]

    def __str__(self):
        return f"UploadChunk {self.chunked_upload.id} - Chunk {self.chunk_number} ({self.verification_status})"
    
    def is_verified(self):
        """Check if chunk passed verification."""
        return self.verification_status == self.VERIFICATION_VERIFIED
    
    def needs_reupload(self):
        """Check if chunk needs to be re-uploaded."""
        return self.verification_status in [self.VERIFICATION_CORRUPTED, self.VERIFICATION_NEEDS_REUPLOAD]


class ClinicalIndicationRow(models.Model):
    """
    A single row from the partner clinical indication / region table (table.xlsx).
    All protocol GUI dropdowns in Step 1 are driven by these rows.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    anatomical_region = models.CharField(max_length=256)
    clinical_indication = models.TextField()
    iv_contrast = models.CharField(max_length=256)
    comments = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'anatomical_region']
        indexes = [
            models.Index(fields=['anatomical_region']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self) -> str:
        return f"{self.anatomical_region} – {self.clinical_indication}"


class CTManufacturer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128, unique=True)
    is_active = models.BooleanField(default=True)
    is_catalogue = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self) -> str:
        return self.name


class CTManufacturerFieldOption(models.Model):
    """Manufacturer-specific allowed values for auto_kvp_selection and auto_ma_modulation."""

    FIELD_KEY_CHOICES = [
        ('auto_kvp_selection', 'Automatic kVp Selection'),
        ('auto_ma_modulation', 'Automatic mA Modulation'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manufacturer = models.ForeignKey(
        CTManufacturer,
        on_delete=models.CASCADE,
        related_name='field_options',
    )
    field_key = models.CharField(max_length=64, choices=FIELD_KEY_CHOICES)
    value = models.CharField(max_length=256)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['manufacturer__sort_order', 'field_key', 'sort_order']
        unique_together = [['manufacturer', 'field_key', 'value']]

    def __str__(self) -> str:
        return f"{self.manufacturer.name} / {self.field_key}: {self.value}"


class MaModulationInputSpec(models.Model):
    """Maps each Automatic mA Modulation value to the set of numeric inputs it requires."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ma_modulation_value = models.CharField(max_length=256, unique=True)
    # Ordered list of input-field labels, e.g. ["min mA", "max mA", "Standard Deviation"]
    input_labels = models.JSONField(default=list)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'ma_modulation_value']

    def __str__(self) -> str:
        return f"{self.ma_modulation_value} → {self.input_labels}"


class CTScannerModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manufacturer = models.ForeignKey(
        CTManufacturer,
        on_delete=models.PROTECT,
        related_name='scanner_models',
    )
    name = models.CharField(max_length=256)
    notes = models.CharField(max_length=512, blank=True)
    is_active = models.BooleanField(default=True)
    is_catalogue = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['manufacturer__name', 'sort_order', 'name']
        unique_together = [['manufacturer', 'name']]

    def __str__(self) -> str:
        return f"{self.manufacturer.name} – {self.name}"


class ProtocolChoiceCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'label']
        verbose_name_plural = 'Protocol choice categories'

    def __str__(self) -> str:
        return self.label


class ProtocolChoiceOption(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(
        ProtocolChoiceCategory,
        on_delete=models.CASCADE,
        related_name='options',
    )
    value = models.CharField(max_length=256)
    display = models.CharField(max_length=512)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    # Empty list means option applies to all protocol types.
    applicable_protocol_types = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['sort_order', 'display']
        unique_together = [['category', 'value']]

    def __str__(self) -> str:
        return f"{self.category.label}: {self.display}"


class CTScannerProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manufacturer = models.ForeignKey(
        CTManufacturer,
        on_delete=models.PROTECT,
        related_name='scanner_profiles',
    )
    scanner_model = models.ForeignKey(
        CTScannerModel,
        on_delete=models.PROTECT,
        related_name='scanner_profiles',
    )
    detector_rows = models.CharField(max_length=256, blank=True)
    year_of_installation = models.CharField(max_length=32, blank=True)
    local_protocol_note = models.TextField(blank=True)
    created_by = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"{self.manufacturer.name} {self.scanner_model.name}"


class CTProtocol(models.Model):
    PROTOCOL_TYPE_CHOICES = [
        ('PEDIATRIC_HEAD', 'Pediatric Head CT Protocols'),
        ('PEDIATRIC_BODY', 'Pediatric Body CT Protocols'),
        ('YOUNG_ADULT', 'Young Adult CT Protocols'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scanner = models.ForeignKey(
        CTScannerProfile,
        on_delete=models.PROTECT,
        related_name='protocols',
    )
    protocol_type = models.CharField(max_length=16, choices=PROTOCOL_TYPE_CHOICES)
    age_group = models.CharField(max_length=64)
    examination_group = models.CharField(max_length=128, blank=True)
    clinical_comments = models.CharField(max_length=512, blank=True)
    clinical_indication = models.CharField(max_length=512, blank=True)
    protocol_name = models.CharField(max_length=512, blank=True)
    anatomical_region = models.CharField(max_length=256, blank=True)
    scan_type = models.CharField(max_length=256, blank=True)
    contrast = models.CharField(max_length=256, blank=True)
    number_of_phases = models.CharField(max_length=64, blank=True)
    auto_kvp_selection = models.CharField(max_length=256, blank=True)
    kvp = models.CharField(max_length=64, blank=True)
    auto_ma_modulation = models.CharField(max_length=256, blank=True)
    mas_inputs = models.JSONField(default=dict, blank=True)
    pitch = models.CharField(max_length=64, blank=True)
    rotation_time = models.CharField(max_length=32, blank=True)
    slice_thickness = models.CharField(max_length=32, blank=True)
    scan_fov = models.CharField(max_length=128, blank=True)
    kernel_class = models.CharField(max_length=128, blank=True)
    reconstruction_algorithm = models.CharField(max_length=256, blank=True)
    protocol_intent = models.CharField(max_length=256, blank=True)
    dose_metadata = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['protocol_type'], name='uploads_ctp_protoco_idx'),
            models.Index(fields=['scanner'], name='uploads_ctp_scanner_idx'),
        ]

    def __str__(self) -> str:
        return f"{self.get_protocol_type_display()} – {self.age_group}"


class CTExamination(models.Model):
    IMAGE_QUALITY_CHOICES = [
        ('EXCELLENT', 'Excellent'),
        ('GOOD', 'Good'),
        ('MODERATE', 'Moderate'),
        ('POOR', 'Poor'),
    ]

    PROTOCOL_TYPE_CHOICES = [
        ('PEDIATRIC_HEAD', 'Pediatric Head'),
        ('PEDIATRIC_BODY', 'Pediatric Body'),
        ('YOUNG_ADULT', 'Young Adult'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rhythm_pseudo_id = models.CharField(max_length=64, blank=True, db_index=True,
                                        db_column='repository_study_id',
                                        help_text='Auto-generated RHYTHM repository pseudo-ID')
    protocol = models.ForeignKey(
        CTProtocol,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='examinations',
    )
    scanner = models.ForeignKey(
        CTScannerProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='examinations',
    )
    anatomical_region = models.CharField(max_length=256, blank=True)
    clinical_indication = models.CharField(max_length=512, blank=True)
    contrast = models.CharField(max_length=128, blank=True)
    protocol_type = models.CharField(
        max_length=32, choices=PROTOCOL_TYPE_CHOICES, blank=True,
    )
    examination_group = models.CharField(max_length=128, blank=True)
    patient_weight = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    water_equivalent_diameter = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    patient_age = models.PositiveIntegerField(null=True, blank=True)
    number_of_phases = models.PositiveIntegerField(default=1)
    ctdi_vol_per_phase = models.JSONField(default=list, blank=True)
    dlp_per_phase = models.JSONField(default=list, blank=True)
    image_quality = models.CharField(
        max_length=16,
        choices=IMAGE_QUALITY_CHOICES,
        blank=True,
    )
    study_set_file = models.FileField(
        upload_to='examination_study_sets/',
        null=True,
        blank=True,
        help_text='Optional compressed study set archive (zip, tar, tar.gz, etc.)',
    )
    created_by = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['scanner'], name='uploads_cte_scanner_idx'),
            models.Index(fields=['created_at'], name='uploads_cte_created_idx'),
        ]

    def __str__(self) -> str:
        return f"Exam {self.id} – {self.anatomical_region or 'unknown region'}"

    @property
    def total_dlp(self) -> float:
        return sum(float(v) for v in self.dlp_per_phase if v is not None)


class UserProfile(models.Model):
    """Extended profile for registered users — institution, role, terms acceptance."""

    PROFESSIONAL_ROLE_CHOICES = [
        ('radiologist', 'Radiologist'),
        ('medical_physicist', 'Medical Physicist'),
        ('radiographer', 'Radiographer / CT Technologist'),
        ('pacs_it', 'PACS / IT Administrator'),
        ('research_coordinator', 'Research Coordinator'),
        ('principal_investigator', 'Principal Investigator'),
        ('dpo', 'Data Protection Officer'),
        ('other', 'Other: please specify'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    institution = models.CharField(max_length=256)
    department = models.CharField(max_length=256, blank=True)
    professional_role = models.CharField(max_length=64, choices=PROFESSIONAL_ROLE_CHOICES)
    professional_role_other = models.CharField(max_length=256, blank=True)
    # Short site code assigned by the repository admin (e.g. "S001").
    # Used as the SITE segment of RHYTHM pseudo-IDs.
    site_code = models.CharField(max_length=16, blank=True, default='')
    terms_accepted = models.BooleanField(default=False)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['institution']),
            models.Index(fields=['site_code']),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} – {self.institution}"

    @classmethod
    def assign_site_code(cls, institution: str) -> str:
        """Return the canonical site code for *institution*, minting one if needed.

        Within a transaction: if any profile for the same institution already has
        a site code, that code is reused (one code per institution).  Otherwise
        the next sequential ``S001`` … ``S999`` code is assigned.

        Thread-safety: the query runs inside ``transaction.atomic()``.  Concurrent
        registrations from the *same* new institution are protected by locking the
        matching rows with ``SELECT FOR UPDATE``.  The unlikely race where two
        *different* new institutions receive the same number is handled by catching
        the ``IntegrityError`` raised by the unique index and retrying once.
        """
        normalized = institution.strip()
        with transaction.atomic():
            # Existing profiles for this institution — lock them to prevent
            # another concurrent registration from the same institution slipping
            # through without a code.
            existing_qs = (
                cls.objects
                .filter(institution__iexact=normalized)
                .exclude(site_code='')
                .select_for_update()
            )
            existing_code = existing_qs.values_list('site_code', flat=True).first()
            if existing_code:
                return existing_code

            # No code yet for this institution — compute the next free number.
            used_nums = set()
            for code in cls.objects.exclude(site_code='').values_list('site_code', flat=True):
                if len(code) >= 2 and code[0] == 'S' and code[1:].isdigit():
                    used_nums.add(int(code[1:]))

            next_num = 1
            while next_num in used_nums:
                next_num += 1

            return f"S{next_num:03d}"


class RhythmPseudoIDCounter(models.Model):
    """
    Per-prefix atomic sequence counter for RHYTHM pseudo-IDs.

    Each distinct ``RHY-{SITE}-{INDICATION}-{CONTRAST}-{GROUP}`` prefix has
    one row here.  ``last_seq`` is incremented under a ``SELECT … FOR UPDATE``
    lock so concurrent uploads never receive the same sequence number.
    """

    prefix = models.CharField(
        max_length=64,
        unique=True,
        help_text="RHY-SITE-INDICATION-CONTRAST-GROUP prefix",
    )
    last_seq = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["prefix"])]

    def __str__(self) -> str:
        return f"{self.prefix} (seq={self.last_seq})"
