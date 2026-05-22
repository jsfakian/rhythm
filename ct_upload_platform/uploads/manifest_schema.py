"""
Manifest JSON Schema and validation for CT upload platform.
"""

from datetime import date
from jsonschema import Draft7Validator, ValidationError, validators
import json


# JSON Schema for manifest version 1.0
MANIFEST_SCHEMA_V1 = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "title": "CT Upload Manifest Schema v1.0",
    "required": ["manifest_version", "upload_id", "created_at", "patient", "study", "images"],
    "properties": {
        "manifest_version": {
            "type": "string",
            "description": "Version of the manifest schema",
        },
        "upload_id": {
            "type": "string",
            "format": "uuid",
            "description": "Unique upload identifier (UUID)",
        },
        "created_at": {
            "type": "string",
            "format": "date-time",
            "description": "Timestamp when manifest was created (ISO 8601)",
        },
        "source_institution": {
            "type": "string",
            "description": "Source hospital or imaging center",
        },
        "study": {
            "type": "object",
            "title": "Study",
            "required": ["study_uid", "acquisition_date", "contrast_used"],
            "properties": {
                "study_uid": {
                    "type": "string",
                    "description": "DICOM Study Instance UID",
                },
                "acquisition_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Date of image acquisition (YYYY-MM-DD)",
                },
                "clinical_indication": {
                    "type": "string",
                    "description": "Clinical reason for imaging",
                },
                "pathology_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Known pathology labels",
                },
                "contrast_used": {
                    "type": "boolean",
                    "description": "Whether contrast agent was used",
                },
                "contrast_agent": {
                    "type": ["string", "null"],
                    "description": "Name of contrast agent used",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes about the study",
                },
            },
            "additionalProperties": False,
        },
        "patient": {
            "type": "object",
            "title": "Patient",
            "required": ["pseudo_id"],
            "properties": {
                "pseudo_id": {
                    "type": "string",
                    "pattern": "^[A-Za-z0-9_-]{8,64}$",
                    "description": "De-identified patient identifier",
                },
                "sex": {
                    "type": "string",
                    "enum": ["M", "F", "O", "U"],
                    "description": "Biological sex (M=Male, F=Female, O=Other, U=Unknown)",
                },
                "age_at_acquisition": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 130,
                    "description": "Patient age at time of acquisition",
                },
                "cohort_tag": {
                    "type": "string",
                    "description": "Research cohort identifier",
                },
            },
            "additionalProperties": False,
        },
        "images": {
            "type": "array",
            "minItems": 1,
            "title": "Images",
            "description": "Array of image entries",
            "items": {
                "type": "object",
                "required": [
                    "filename",
                    "checksum_sha256",
                    "series_uid",
                    "body_part",
                ],
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Original filename of the image",
                    },
                    "checksum_sha256": {
                        "type": "string",
                        "pattern": "^[a-f0-9]{64}$",
                        "description": "SHA-256 checksum of the file (hex, 64 chars)",
                    },
                    "series_uid": {
                        "type": "string",
                        "description": "DICOM Series Instance UID",
                    },
                    "series_number": {
                        "type": "integer",
                        "description": "Sequence number of series within study",
                    },
                    "instance_number": {
                        "type": "integer",
                        "description": "Instance number within series",
                    },
                    "body_part": {
                        "type": "string",
                        "enum": ["CHEST", "ABDOMEN", "PELVIS", "HEAD", "NECK", "SPINE", "EXTREMITY", "WHOLE_BODY", "OTHER"],
                        "description": "Anatomical body part examined",
                    },
                    "laterality": {
                        "type": "string",
                        "enum": ["L", "R", "B", "NA"],
                        "description": "Side of body examined (L=Left, R=Right, B=Bilateral, NA=Not Applicable)",
                    },
                    "view_plane": {
                        "type": "string",
                        "enum": ["AXIAL", "CORONAL", "SAGITTAL", "NA"],
                        "description": "Imaging plane orientation",
                    },
                    "slice_thickness_mm": {
                        "type": "number",
                        "description": "Slice thickness in millimeters",
                    },
                    "pixel_spacing_mm": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": {"type": "number"},
                        "description": "Pixel spacing as [row_spacing, column_spacing] in mm",
                    },
                    "image_dimensions": {
                        "type": "object",
                        "properties": {
                            "rows": {"type": "integer"},
                            "cols": {"type": "integer"},
                        },
                        "required": ["rows", "cols"],
                        "additionalProperties": False,
                        "description": "Image dimensions",
                    },
                    "scanner_manufacturer": {
                        "type": "string",
                        "description": "Manufacturer of imaging device",
                    },
                    "scanner_model": {
                        "type": "string",
                        "description": "Model of imaging device",
                    },
                    "kvp": {
                        "type": "number",
                        "description": "Kilovoltage peak (X-ray energy)",
                    },
                    "processing_status": {
                        "type": "string",
                        "enum": ["RAW", "PREPROCESSED", "ANNOTATED"],
                        "default": "RAW",
                        "description": "Processing status of the image",
                    },
                    "annotations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "annotation_uid": {
                                    "type": "string",
                                    "description": "Unique identifier for the annotation",
                                },
                                "type": {
                                    "type": "string",
                                    "enum": ["SEGMENTATION", "BOUNDING_BOX", "LANDMARK", "CLASSIFICATION"],
                                    "description": "Type of annotation",
                                },
                                "label": {
                                    "type": "string",
                                    "description": "Label or description",
                                },
                                "annotator_id": {
                                    "type": "string",
                                    "description": "Identifier of annotator",
                                },
                                "annotation_date": {
                                    "type": "string",
                                    "format": "date",
                                    "description": "Date of annotation",
                                },
                                "file_ref": {
                                    "type": "string",
                                    "description": "Reference to annotation file in archive",
                                },
                            },
                            "additionalProperties": False,
                        },
                        "description": "Annotations for this image",
                    },
                },
                "additionalProperties": False,
            },
        },
        "pipeline": {
            "type": "object",
            "title": "Pipeline",
            "properties": {
                "uploader_id": {
                    "type": "string",
                    "description": "Identifier of the uploader",
                },
                "upload_client_version": {
                    "type": "string",
                    "description": "Version of upload client",
                },
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}


def validate_manifest(manifest_dict) -> list[dict]:
    """
    Validate a manifest dictionary against MANIFEST_SCHEMA_V1.
    
    Performs:
    1. JSON Schema validation
    2. Checks that acquisition_date is not in the future
    3. Checks for duplicate filenames within images array
    
    Args:
        manifest_dict: Dictionary to validate
    
    Returns:
        List of error dicts with keys: field (JSON path), code (string), message (string)
        Empty list if valid.
    """
    errors = []
    
    # 1. JSON Schema validation
    validator = Draft7Validator(MANIFEST_SCHEMA_V1)
    for error in validator.iter_errors(manifest_dict):
        # Build JSON path from absolute_path
        field_path = "$." + ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "$"
        # Extract the error validator (e.g., "required", "type", "pattern", etc.)
        error_code = error.validator if error.validator else "schema_validation_error"
        errors.append({
            "field": field_path,
            "code": error_code,
            "message": error.message,
        })
    
    # Early exit if schema validation failed
    if errors:
        return errors
    
    # 2. Check acquisition_date is not in future
    try:
        study = manifest_dict.get("study", {})
        acquisition_date_str = study.get("acquisition_date")
        if acquisition_date_str:
            acquisition_date = date.fromisoformat(acquisition_date_str)
            if acquisition_date > date.today():
                errors.append({
                    "field": "$.study.acquisition_date",
                    "code": "future_date",
                    "message": f"Acquisition date {acquisition_date_str} is in the future",
                })
    except (ValueError, TypeError) as e:
        errors.append({
            "field": "$.study.acquisition_date",
            "code": "date_parse_error",
            "message": f"Could not parse acquisition_date: {str(e)}",
        })
    
    # 3. Check for duplicate filenames
    try:
        images = manifest_dict.get("images", [])
        filenames_seen = set()
        for idx, image in enumerate(images):
            filename = image.get("filename")
            if filename:
                if filename in filenames_seen:
                    errors.append({
                        "field": f"$.images[{idx}].filename",
                        "code": "duplicate_filename",
                        "message": f"Duplicate filename: {filename}",
                    })
                filenames_seen.add(filename)
    except (TypeError, AttributeError) as e:
        errors.append({
            "field": "$.images",
            "code": "images_processing_error",
            "message": f"Error processing images array: {str(e)}",
        })
    
    return errors
