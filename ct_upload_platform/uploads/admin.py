"""
Admin configuration for the uploads app.
"""

from django.contrib import admin
from .models import (
    Patient, UploadJob, StudyMapping, Annotation, AuditLog,
    ClinicalIndicationRow,
    CTManufacturer, CTScannerModel, ProtocolChoiceCategory,
    ProtocolChoiceOption, CTScannerProfile, CTProtocol,
)


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('pseudo_id', 'sex', 'age_at_first_acquisition', 'cohort_tag', 'created_at')
    list_filter = ('sex', 'cohort_tag', 'created_at')
    search_fields = ('pseudo_id',)
    readonly_fields = ('id', 'created_at')
    fields = ('id', 'pseudo_id', 'sex', 'age_at_first_acquisition', 'cohort_tag', 'created_at')


@admin.register(UploadJob)
class UploadJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'uploader_id', 'status', 'submitted_at', 'completed_at')
    list_filter = ('status', 'submitted_at')
    search_fields = ('uploader_id', 'id')
    readonly_fields = ('id', 'submitted_at')
    fields = ('id', 'uploader_id', 'status', 'tar_temp_path', 'submitted_at', 'completed_at', 'manifest_raw', 'error_report')


@admin.register(StudyMapping)
class StudyMappingAdmin(admin.ModelAdmin):
    list_display = ('pseudo_study_uid', 'patient', 'acquisition_date', 'orthanc_study_id', 'created_at')
    list_filter = ('acquisition_date', 'contrast_used', 'created_at')
    search_fields = ('pseudo_study_uid', 'patient__pseudo_id', 'orthanc_study_id')
    readonly_fields = ('id', 'created_at')
    fields = ('id', 'patient', 'upload_job', 'pseudo_study_uid', 'orthanc_study_id', 'acquisition_date', 'clinical_indication', 'pathology_labels', 'contrast_used', 'contrast_agent', 'source_institution', 'notes', 'created_at')


@admin.register(Annotation)
class AnnotationAdmin(admin.ModelAdmin):
    list_display = ('annotation_uid', 'study_mapping', 'type', 'label', 'annotator_id', 'annotation_date')
    list_filter = ('type', 'annotation_date')
    search_fields = ('annotation_uid', 'label', 'annotator_id', 'orthanc_instance_id')
    readonly_fields = ('id', 'created_at')
    fields = ('id', 'study_mapping', 'orthanc_instance_id', 'annotation_uid', 'annotator_id', 'annotation_date', 'type', 'label', 'annotation_data', 'annotation_file', 'created_at')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'actor_id', 'occurred_at', 'upload_job')
    list_filter = ('event_type', 'occurred_at')
    search_fields = ('actor_id', 'upload_job__id')
    readonly_fields = ('id', 'occurred_at')
    fields = ('id', 'upload_job', 'event_type', 'actor_id', 'detail', 'occurred_at')


@admin.register(ClinicalIndicationRow)
class ClinicalIndicationRowAdmin(admin.ModelAdmin):
    list_display = ('anatomical_region', 'clinical_indication', 'iv_contrast', 'sort_order', 'is_active')
    list_filter = ('anatomical_region', 'is_active')
    search_fields = ('anatomical_region', 'clinical_indication', 'comments')
    readonly_fields = ('id',)
    ordering = ('sort_order', 'anatomical_region')


@admin.register(CTManufacturer)
class CTManufacturerAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'sort_order')
    list_filter = ('is_active',)
    search_fields = ('name',)
    readonly_fields = ('id',)


class CTScannerModelInline(admin.TabularInline):
    model = CTScannerModel
    extra = 0
    fields = ('name', 'notes', 'is_active', 'sort_order')


@admin.register(CTScannerModel)
class CTScannerModelAdmin(admin.ModelAdmin):
    list_display = ('name', 'manufacturer', 'is_active', 'sort_order')
    list_filter = ('manufacturer', 'is_active')
    search_fields = ('name', 'manufacturer__name')
    readonly_fields = ('id',)


class ProtocolChoiceOptionInline(admin.TabularInline):
    model = ProtocolChoiceOption
    extra = 0
    fields = ('value', 'display', 'sort_order', 'is_active', 'applicable_protocol_types')


@admin.register(ProtocolChoiceCategory)
class ProtocolChoiceCategoryAdmin(admin.ModelAdmin):
    list_display = ('label', 'key', 'sort_order')
    search_fields = ('key', 'label')
    readonly_fields = ('id',)
    inlines = [ProtocolChoiceOptionInline]


@admin.register(ProtocolChoiceOption)
class ProtocolChoiceOptionAdmin(admin.ModelAdmin):
    list_display = ('display', 'value', 'category', 'sort_order', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('value', 'display', 'category__key')
    readonly_fields = ('id',)


@admin.register(CTScannerProfile)
class CTScannerProfileAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'manufacturer', 'scanner_model', 'detector_rows', 'year_of_installation', 'created_by', 'created_at')
    list_filter = ('manufacturer', 'created_at')
    search_fields = ('manufacturer__name', 'scanner_model__name', 'created_by')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(CTProtocol)
class CTProtocolAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'scanner', 'protocol_type', 'age_group', 'protocol_name', 'created_by', 'created_at')
    list_filter = ('protocol_type', 'created_at')
    search_fields = ('protocol_name', 'clinical_indication', 'created_by')
    readonly_fields = ('id', 'created_at', 'updated_at')
