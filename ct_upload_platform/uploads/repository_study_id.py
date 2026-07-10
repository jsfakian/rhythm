"""
RHYTHM repository study ID generator.

Format: RHY-{SITE}-{INDICATION}-{CONTRAST}-{GROUP}-{SEQ:06d}

Example: RHY-S001-HEADTRAUMA-NC-PH-G4-000123
"""

import re
import logging
from django.db import transaction

logger = logging.getLogger(__name__)

# --- Mapping tables (mirrors the JS constants) ---

INDICATION_CODES: dict[str, str] = {
    "Head / Trauma": "HEADTRAUMA",
    "Mastoid bone/Inner Ear / Hearing loss; congenital malformations, infection, cholesteatoma, cochlear implants": "MASTOID",
    "Chest / Complicated infections": "CHESTCOMP",
    "Chest / Fungal infections": "CHESTFUNG",
    (
        "Chest/HRCT (Inspiration/Expiration) / Interstitial lung diseases, small airways disease, "
        "cystic fibrosis, asthma, primary ciliary dyskinesia, chronic lung disease of prematurity"
    ): "HRCTILD",
    "Abdomen / Acute abdomen": "ACUTEABD",
    "Neck-Chest-Abdomen / Lymphoma": "LYMPHOMA",
    "Chest-Abdomen / Tumor staging & follow-up (Wilms tumor, neuroblastoma, other)": "CHESTABD",
}

CONTRAST_CODES: dict[str, str] = {
    "Non-contrast": "NC",
    "Contrast-enhanced": "CE",
    "Non-contrast, Contrast-enhanced": "MIX",
}

_PEDIATRIC_HEAD_GROUPS: dict[str, str] = {
    "Group 1": "PH-G1",
    "Group 2": "PH-G2",
    "Group 3": "PH-G3",
    "Group 4": "PH-G4",
}

_PEDIATRIC_BODY_GROUPS: dict[str, str] = {
    "Group 1": "PB-G1",
    "Group 2": "PB-G2",
    "Group 3": "PB-G3",
    "Group 4": "PB-G4",
    "Group 5": "PB-G5",
}

# Compiled pattern for validating a fully-formed RHY ID
_RHY_PATTERN = re.compile(
    r'^RHY-[A-Z0-9]+-[A-Z]+-(?:NC|CE|MIX)-(?:PH|PB|YA)-G\d+-\d{6}$'
)


def get_patient_group_code(protocol_type: str, examination_group: str) -> str:
    """Map (protocol_type, examination_group) to a patient-group code."""
    if protocol_type == "PEDIATRIC_HEAD":
        for key, code in _PEDIATRIC_HEAD_GROUPS.items():
            if key in examination_group:
                return code
    elif protocol_type == "PEDIATRIC_BODY":
        for key, code in _PEDIATRIC_BODY_GROUPS.items():
            if key in examination_group:
                return code
    elif protocol_type == "YOUNG_ADULT":
        return "YA-G6"
    return "UNK"


def _build_prefix(
    site_code: str,
    indication_code: str,
    contrast_code: str,
    group_code: str,
) -> str:
    return f"RHY-{site_code}-{indication_code}-{contrast_code}-{group_code}"


def generate_repository_study_id(
    site_code: str,
    clinical_indication: str,
    contrast: str,
    protocol_type: str,
    examination_group: str,
) -> str:
    """
    Generate a globally unique RHYTHM repository study ID.

    Resolves the four human-readable values to their codes, builds the
    prefix, and assigns the next sequence number for that prefix under a
    database row-lock so concurrent uploads cannot collide.

    Args:
        site_code:           Submitting institution code, e.g. ``"S001"``.
        clinical_indication: Full clinical-indication string from the form.
        contrast:            Contrast string from the form.
        protocol_type:       One of ``PEDIATRIC_HEAD``, ``PEDIATRIC_BODY``,
                             or ``YOUNG_ADULT``.
        examination_group:   Examination-group string from the form,
                             e.g. ``"Group 4 – Childhood"``.

    Returns:
        A string like ``"RHY-S001-HEADTRAUMA-NC-PH-G4-000123"``.
    """
    from .models import RhythmPseudoIDCounter

    indication_code = INDICATION_CODES.get(clinical_indication, "OTHER")
    contrast_code = CONTRAST_CODES.get(contrast, "UNK")
    group_code = get_patient_group_code(protocol_type, examination_group)
    prefix = _build_prefix(site_code, indication_code, contrast_code, group_code)

    with transaction.atomic():
        counter, _ = RhythmPseudoIDCounter.objects.get_or_create(
            prefix=prefix,
            defaults={"last_seq": 0},
        )
        # Re-fetch with a row-level lock so concurrent calls for the same
        # prefix are serialised at the database level.
        counter = RhythmPseudoIDCounter.objects.select_for_update().get(pk=counter.pk)
        counter.last_seq += 1
        counter.save(update_fields=["last_seq", "updated_at"])
        seq = counter.last_seq

    study_id = f"{prefix}-{seq:06d}"
    logger.info("Generated repository study ID: %s", study_id)
    return study_id


def is_repository_study_id(value: str) -> bool:
    """Return True if *value* matches the canonical RHY format."""
    return bool(_RHY_PATTERN.match(value))
