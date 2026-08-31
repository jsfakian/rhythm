"""
GDPR-strict DICOM anonymization validator.

Validates that uploaded DICOM files comply with GDPR-strict anonymization
rules defined in GDPR-strict.json. Does not modify files, only validates
them.

GDPR-strict.json's source of truth is the authoritative anonymization
tool at https://github.com/jsfakian/dicom_anonymization
(GDPR-strict_explicit.json there). That tool's own validator compares an
*original* (pre-anonymization) DICOM against the *anonymized* one, using a
salted deterministic derivation to verify e.g. that a PSEUDOUID tag was
generated correctly from the real PatientID. This platform only ever
receives the already-anonymized file — the original never leaves the
submitting institution, by design (see the PHI boundary in CLAUDE.md) — so
it cannot replicate that comparison. What it validates instead, per tag,
given only the anonymized file:

    null ("remove")   -> the tag must be absent or empty.
    "KEEP"            -> no check; presence/value can't be judged without
                         the original, and KEEP means the tool intentionally
                         preserves this tag's value as-is.
    "PSEUDOUID"       -> the tag must be present and non-empty (the actual
                         deterministic derivation can't be verified without
                         the original PatientID and the anonymizer's salt).

Any other/legacy directive is treated the same as "KEEP" (no enforceable
check without the original file).
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import pydicom
from django.conf import settings

logger = logging.getLogger(__name__)


class GDPRValidationError(Exception):
    """Raised when a DICOM file fails GDPR anonymization validation."""

    def __init__(self, code: str, message: str, details: Optional[Dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class GDPRConfig:
    """Loads and manages GDPR-strict.json configuration."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = getattr(
                settings,
                'GDPR_STRICT_CONFIG_PATH',
                './GDPR-strict.json'
            )

        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load and parse GDPR-strict.json configuration."""
        try:
            config_file = Path(self.config_path)
            if not config_file.exists():
                raise FileNotFoundError(f"GDPR config not found at {self.config_path}")

            with open(config_file, 'r') as f:
                config = json.load(f)

            logger.info(f"Loaded GDPR config from {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"Failed to load GDPR config: {e}")
            raise

    def __getitem__(self, key: str) -> Any:
        """Get a config value."""
        return self.config.get(key)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value with default."""
        return self.config.get(key, default)


class GDPRAnonymizationValidator:
    """Validates DICOM files against GDPR-strict anonymization rules.

    Iterates every per-tag rule in GDPR-strict.json rather than a
    hand-picked subset — see module docstring for what each directive
    means given we only see the anonymized file, never the original.
    """

    # Top-level profile-wide flags, not per-DICOM-tag rules — skipped when
    # iterating the config for per-tag checks and consulted individually.
    PROFILE_FLAGS = {"KeepPrivateTags", "PixelBlackout", "RetainStudyDate", "Private attributes"}

    # A handful of tags get a specific, descriptive error code instead of
    # the generic phi_tag_present / pseudo_tag_missing every other
    # tag uses — these are the ones other code (StudyMapping/Image
    # creation, error-report display) has historically keyed off of.
    _MISSING_CODE_OVERRIDES = {
        'PatientID': 'patient_id_present',  # PatientID's directive is null (must be absent)
        'StudyInstanceUID': 'study_uid_missing',
        'SeriesInstanceUID': 'series_uid_missing',
    }

    # GDPR-strict.json marks ~19 tags PSEUDOUID, but most of them (SOP
    # Instance UID variants used only in DIMSE messaging, Template
    # Extension UIDs, Synchronization Frame of Reference, etc.) simply
    # don't exist in an ordinary stored CT slice — they're relevant to
    # other SOP classes/contexts. Only these two are Type 1 (mandatory)
    # for a CT Image IOD and are already guaranteed present upstream
    # (tasks.py's archive scan only keeps files with a StudyInstanceUID).
    # Every other PSEUDOUID tag is checked only if present — absence is
    # fine, but a present-yet-blank value indicates a broken anonymization
    # pass.
    _PSEUDOUID_REQUIRED = {'StudyInstanceUID', 'SeriesInstanceUID'}

    def __init__(self, gdpr_config: Optional[GDPRConfig] = None, pseudo_id: Optional[str] = None):
        """
        Initialize validator.

        Args:
            gdpr_config: GDPRConfig instance. If None, loads from default path.
            pseudo_id: Accepted for API compatibility with older callers.
                Not used: the authoritative tool's PatientID rule is now
                "must be absent", so there is nothing to match against.
        """
        self.gdpr_config = gdpr_config or GDPRConfig()
        self.pseudo_id = pseudo_id
        self.validation_errors: List[Dict[str, Any]] = []

    def validate_file(
        self,
        file_path: str,
        pseudo_id: Optional[str] = None
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Validate that a DICOM file is properly anonymized.

        Args:
            file_path: Path to DICOM file
            pseudo_id: Accepted for API compatibility; see __init__.

        Returns:
            Tuple of (is_valid, error_list)
            where error_list contains dicts with 'code', 'field', 'message'
        """
        self.validation_errors = []

        if pseudo_id:
            self.pseudo_id = pseudo_id

        try:
            ds = pydicom.dcmread(file_path, stop_before_pixels=True)
        except Exception as e:
            self.validation_errors.append({
                'code': 'dicom_read_error',
                'field': 'file',
                'message': f'Failed to read DICOM file: {str(e)}'
            })
            return False, self.validation_errors

        # Run validation checks
        self._check_tag_rules(ds)
        self._check_private_tags(ds)
        self._check_overlay_data(ds)
        self._check_curve_data(ds)
        self._check_audio_data(ds)

        is_valid = len(self.validation_errors) == 0
        return is_valid, self.validation_errors

    def _check_tag_rules(self, ds: pydicom.Dataset) -> None:
        """Apply every per-tag rule in GDPR-strict.json to the dataset."""
        for keyword, action in self.gdpr_config.config.items():
            if keyword in self.PROFILE_FLAGS:
                continue

            present = hasattr(ds, keyword)
            value = getattr(ds, keyword, None) if present else None
            has_value = present and value is not None and str(value).strip() != ''

            # PatientID is the one tag with two legitimate, opposite
            # expectations depending on the caller: v2/Manual Entry never
            # writes to the file and passes pseudo_id=None, so PatientID's
            # configured directive (null — must be absent, per the
            # authoritative anonymization tool) applies as-is. The v1
            # pipeline, by contrast, actually inserts its own
            # organ-specific pseudo-ID into PatientID during anonymization
            # and passes it explicitly here to verify that write — for that
            # caller only, presence-and-match is exactly what "properly
            # anonymized" means, overriding the null directive.
            if keyword == 'PatientID' and self.pseudo_id:
                patient_id = str(value).strip() if has_value else ''
                if patient_id != self.pseudo_id:
                    self.validation_errors.append({
                        'code': 'patient_id_mismatch',
                        'field': 'PatientID',
                        'message': f'PatientID must be "{self.pseudo_id}" (found: "{patient_id}")',
                    })
                continue

            if action is None:
                if has_value:
                    self.validation_errors.append({
                        'code': self._MISSING_CODE_OVERRIDES.get(keyword, 'phi_tag_present'),
                        'field': keyword,
                        'message': f'{keyword} must be removed (found: {str(value)[:50]})',
                    })
                continue

            if isinstance(action, str) and action.strip().upper() == 'PSEUDOUID':
                if keyword in self._PSEUDOUID_REQUIRED:
                    if not has_value:
                        self.validation_errors.append({
                            'code': self._MISSING_CODE_OVERRIDES.get(keyword, 'pseudo_tag_missing'),
                            'field': keyword,
                            'message': f'{keyword} must be present and pseudonymized',
                        })
                elif present and not has_value:
                    # Present but blank — the anonymizer emptied it instead
                    # of substituting a pseudonymized value. Absence
                    # entirely is fine; this tag may not apply to this SOP
                    # class/context at all.
                    self.validation_errors.append({
                        'code': 'pseudo_tag_blank',
                        'field': keyword,
                        'message': f'{keyword} is present but blank — must be pseudonymized or absent',
                    })
                continue

            # "KEEP" and any other/legacy directive: nothing we can verify
            # without the original file. Not an error either way.

    def _check_private_tags(self, ds: pydicom.Dataset) -> None:
        """Verify private-tag handling matches the KeepPrivateTags flag."""
        keep_private_tags = bool(self.gdpr_config.get('KeepPrivateTags', False))
        if keep_private_tags:
            return

        private_tags_found = []
        for tag in ds.keys():
            # Private tags have odd group numbers
            if tag.group % 2 == 1:
                private_tags_found.append(f"({tag.group:04X},{tag.elem:04X})")

        if private_tags_found:
            self.validation_errors.append({
                'code': 'private_tags_present',
                'field': 'private_tags',
                'message': f'Private tags must be removed (found {len(private_tags_found)}): {", ".join(private_tags_found[:5])}'
            })

    def _check_overlay_data(self, ds: pydicom.Dataset) -> None:
        """Verify no overlay data is present (Overlay Data: null)."""
        overlay_count = 0
        for tag in ds.keys():
            # Overlay data is in the 60xx range
            if tag.group >= 0x6000 and tag.group <= 0x60FF:
                overlay_count += 1

        if overlay_count > 0:
            self.validation_errors.append({
                'code': 'overlay_data_present',
                'field': 'overlay',
                'message': f'Overlay data must be removed (found {overlay_count} overlay tags)'
            })

    def _check_curve_data(self, ds: pydicom.Dataset) -> None:
        """Verify no curve data is present (Curve Data: null)."""
        curve_count = 0
        for tag in ds.keys():
            # Curve data is in the 50xx range
            if tag.group >= 0x5000 and tag.group <= 0x50FF:
                curve_count += 1

        if curve_count > 0:
            self.validation_errors.append({
                'code': 'curve_data_present',
                'field': 'curve',
                'message': f'Curve data must be removed (found {curve_count} curve tags)'
            })

    def _check_audio_data(self, ds: pydicom.Dataset) -> None:
        """Verify no audio/waveform data is present."""
        audio_tags = [0x5400, 0x5402, 0x5409]  # Audio tags
        audio_count = 0

        for tag in ds.keys():
            if tag.group in audio_tags:
                audio_count += 1

        if audio_count > 0:
            self.validation_errors.append({
                'code': 'audio_data_present',
                'field': 'audio',
                'message': f'Audio/waveform data must be removed (found {audio_count} tags)'
            })


def validate_gdpr_anonymization(
    file_path: str,
    pseudo_id: Optional[str] = None
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Convenience function to validate a DICOM file.

    Args:
        file_path: Path to DICOM file
        pseudo_id: Accepted for API compatibility; see
            GDPRAnonymizationValidator.__init__.

    Returns:
        Tuple of (is_valid, error_list)
    """
    try:
        validator = GDPRAnonymizationValidator(pseudo_id=pseudo_id)
        return validator.validate_file(file_path, pseudo_id)
    except Exception as e:
        logger.error(f"GDPR validation failed for {file_path}: {e}", exc_info=True)
        return False, [{'code': 'validation_error', 'message': str(e)}]
