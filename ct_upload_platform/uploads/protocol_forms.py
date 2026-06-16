"""
Forms for CT scanner profiles and CT protocols.
Choice options are loaded from the database at form instantiation time.
"""

from django import forms

from .models import (
    CTManufacturer,
    CTScannerModel,
    CTScannerProfile,
    CTProtocol,
    ClinicalIndicationRow,
    ProtocolChoiceOption,
)

_BLANK_CHOICE = [("", "--- Select ---")]

# Map protocol_type value → category key for age_group
_AGE_GROUP_KEY: dict[str, str] = {
    "PEDIATRIC_HEAD": "age_group_pediatric_head",
    "PEDIATRIC_BODY": "age_group_pediatric_body",
    "YOUNG_ADULT": "age_group_young_adult",
}

# Map protocol_type value → category key for examination_group
_EXAMINATION_GROUP_KEY: dict[str, str] = {
    "PEDIATRIC_HEAD": "examination_group_pediatric_head",
    "PEDIATRIC_BODY": "examination_group_pediatric_body",
    "YOUNG_ADULT": "examination_group_young_adult",
}

# Map protocol_type value → category key for clinical_indication
_CLINICAL_INDICATION_KEY: dict[str, str] = {
    "PEDIATRIC_HEAD": "clinical_indication_pediatric_head",
    "PEDIATRIC_BODY": "clinical_indication_pediatric_body",
    "YOUNG_ADULT": "clinical_indication_adult",
}

# CTProtocol CharField fields whose choices come from a same-named category key
_SIMPLE_CHOICE_FIELDS = [
    # protocol_name handled separately as free-text
    # anatomical_region, clinical_indication, contrast driven by ClinicalIndicationRow
    # auto_kvp_selection and auto_ma_modulation handled separately (manufacturer-specific)
    # pitch handled separately as free-text number input (GUI stores arbitrary decimals)
    "scan_type",
    "number_of_phases",
    "kvp",
    "rotation_time",
    "slice_thickness",
    "scan_fov",
    "kernel_class",
    "reconstruction_algorithm",
    "protocol_intent",
]

# Fields whose allowed values are manufacturer-specific (loaded by JS at runtime).
# Any submitted string is accepted — no server-side choice validation.
_MANUFACTURER_SPECIFIC_FIELDS = ["auto_kvp_selection", "auto_ma_modulation"]


def _get_display_as_value_options(
    category_key: str,
    protocol_type: str | None = None,
) -> list[tuple[str, str]]:
    """
    Like _get_choice_options but uses display text as both the stored value and
    the visible label.  Used for fields where the GUI saves display strings
    (e.g. age_group, examination_group) so the edit form pre-selects correctly.
    """
    raw = _get_choice_options(category_key, protocol_type)
    return _BLANK_CHOICE + [(d, d) for _, d in raw if _]


def _clinical_anatomical_region_options() -> list[tuple[str, str]]:
    values = (
        ClinicalIndicationRow.objects.filter(is_active=True)
        .values_list("anatomical_region", flat=True)
        .distinct()
        .order_by("anatomical_region")
    )
    return _BLANK_CHOICE + [(v, v) for v in values if v]


def _clinical_indication_options() -> list[tuple[str, str]]:
    values = (
        ClinicalIndicationRow.objects.filter(is_active=True)
        .values_list("clinical_indication", flat=True)
        .distinct()
        .order_by("clinical_indication")
    )
    return _BLANK_CHOICE + [(v, v) for v in values if v]


def _clinical_iv_contrast_options() -> list[tuple[str, str]]:
    raw = (
        ClinicalIndicationRow.objects.filter(is_active=True)
        .values_list("iv_contrast", flat=True)
    )
    unique_vals = sorted({s.strip() for row in raw for s in row.split(",") if s.strip()})
    return _BLANK_CHOICE + [(v, v) for v in unique_vals]


def _get_choice_options(
    category_key: str,
    protocol_type: str | None = None,
) -> list[tuple[str, str]]:
    """
    Return (value, display) tuples for the given ProtocolChoiceCategory key.

    When protocol_type is given, only options whose applicable_protocol_types
    list contains that value (or whose list is empty, meaning all types) are
    returned.  A blank sentinel is always prepended.
    """
    qs = ProtocolChoiceOption.objects.filter(
        category__key=category_key,
        is_active=True,
    ).order_by("sort_order", "display")

    tuples: list[tuple[str, str]] = []
    for opt in qs:
        apt = opt.applicable_protocol_types  # list or empty
        if protocol_type and apt and protocol_type not in apt:
            continue
        tuples.append((opt.value, opt.display))

    return _BLANK_CHOICE + tuples


def _add_form_control(widget: forms.Widget) -> None:
    """Mutate a widget to include the Bootstrap form-control CSS class."""
    existing = widget.attrs.get("class", "")
    classes = f"{existing} form-control".strip() if existing else "form-control"
    widget.attrs["class"] = classes


class CTScannerProfileForm(forms.ModelForm):
    manufacturer = forms.ModelChoiceField(
        queryset=CTManufacturer.objects.filter(is_active=True).order_by(
            "sort_order", "name"
        ),
        empty_label="Select manufacturer",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    scanner_model = forms.ModelChoiceField(
        queryset=CTScannerModel.objects.none(),
        empty_label="Select model",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    detector_rows = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    year_of_installation = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    local_protocol_note = forms.CharField(
        required=False,
        label="Site-specific acquisition notes",
        help_text="Any notes about how this scanner is locally configured or used at your site (e.g. non-standard defaults, site-specific adjustments).",
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4}),
    )

    class Meta:
        model = CTScannerProfile
        fields = [
            "manufacturer",
            "scanner_model",
            "detector_rows",
            "year_of_installation",
            "local_protocol_note",
        ]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["detector_rows"].choices = _get_choice_options("detector_rows")
        self.fields["year_of_installation"].choices = _get_choice_options(
            "year_of_installation"
        )
        # Append "Other: Please Specify" to manufacturer choices so users can
        # register a manufacturer that is not yet in the catalogue.
        mfr_choices = list(self.fields["manufacturer"].choices)
        mfr_choices.append(("Other: Please Specify", "Other: Please Specify"))
        self.fields["manufacturer"].widget.choices = mfr_choices
        # When editing an existing profile, pre-populate scanner models for the
        # saved manufacturer so the current value is a valid choice.
        if self.instance and self.instance.pk and self.instance.manufacturer_id:
            self.fields["scanner_model"].queryset = CTScannerModel.objects.filter(
                manufacturer_id=self.instance.manufacturer_id,
                is_active=True,
            ).order_by("sort_order", "name")


_PROTOCOL_APPROACH_CHOICES = [
    ("", "--- Select ---"),
    ("Indication-specific protocol", "Indication-specific protocol"),
    ("Anatomical protocol", "Anatomical protocol"),
]


class CTProtocolForm(forms.ModelForm):
    dose_metadata = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple(),
        required=False,
    )
    clinical_comments = forms.ChoiceField(
        choices=_PROTOCOL_APPROACH_CHOICES,
        required=False,
        label="Protocol approach",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4}),
    )

    class Meta:
        model = CTProtocol
        fields = [
            "scanner",
            "protocol_type",
            "age_group",
            "examination_group",
            "clinical_indication",
            "clinical_comments",
            "protocol_name",
            "anatomical_region",
            "scan_type",
            "contrast",
            "number_of_phases",
            "auto_kvp_selection",
            "kvp",
            "auto_ma_modulation",
            "mas_inputs",
            "pitch",
            "rotation_time",
            "slice_thickness",
            "scan_fov",
            "kernel_class",
            "reconstruction_algorithm",
            "protocol_intent",
            "dose_metadata",
            "notes",
        ]

    def __init__(
        self,
        *args: object,
        protocol_type: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.protocol_type = protocol_type

        # scanner FK
        self.fields["scanner"].queryset = CTScannerProfile.objects.select_related(
            "manufacturer", "scanner_model"
        ).all()
        _add_form_control(self.fields["scanner"].widget)

        # protocol_type — hidden when pre-determined from URL
        if protocol_type:
            self.fields["protocol_type"].widget = forms.HiddenInput()
            self.fields["protocol_type"].initial = protocol_type
        else:
            _add_form_control(self.fields["protocol_type"].widget)

        # age_group — stored as display string (matches what the GUI saves)
        age_key = _AGE_GROUP_KEY.get(protocol_type or "", "age_group_pediatric_head")
        age_choices = _get_display_as_value_options(age_key, protocol_type)
        self.fields["age_group"] = forms.ChoiceField(
            choices=age_choices,
            widget=forms.Select(attrs={"class": "form-control"}),
        )

        # examination_group — stored as display string
        exam_key = _EXAMINATION_GROUP_KEY.get(
            protocol_type or "", "examination_group_pediatric_head"
        )
        exam_choices = _get_display_as_value_options(exam_key, protocol_type)
        self.fields["examination_group"] = forms.ChoiceField(
            choices=exam_choices,
            required=False,
            widget=forms.Select(attrs={"class": "form-control"}),
        )

        # anatomical_region, clinical_indication, contrast — driven by ClinicalIndicationRow
        self.fields["anatomical_region"] = forms.ChoiceField(
            choices=_clinical_anatomical_region_options(),
            required=False,
            widget=forms.Select(attrs={"class": "form-control", "id": "id_anatomical_region"}),
        )
        self.fields["clinical_indication"] = forms.ChoiceField(
            choices=_clinical_indication_options(),
            required=False,
            widget=forms.Select(attrs={"class": "form-control", "id": "id_clinical_indication"}),
        )
        self.fields["contrast"] = forms.ChoiceField(
            choices=_clinical_iv_contrast_options(),
            required=False,
            widget=forms.Select(attrs={"class": "form-control", "id": "id_contrast"}),
        )

        # Simple single-select CharField fields
        for field_name in _SIMPLE_CHOICE_FIELDS:
            choices = _get_choice_options(field_name, protocol_type)
            # If editing and the stored value is not in the standard options list,
            # add it so the select pre-selects correctly.
            if self.instance and self.instance.pk:
                current_val = getattr(self.instance, field_name, "")
                if current_val and current_val not in {v for v, _ in choices}:
                    choices = list(choices) + [(current_val, current_val)]
            self.fields[field_name] = forms.ChoiceField(
                choices=choices,
                required=False,
                widget=forms.Select(attrs={"class": "form-control"}),
            )

        # pitch: free-text number input — GUI stores arbitrary decimals, not the
        # range-bucket values in ProtocolChoiceOption.
        self.fields["pitch"] = forms.CharField(
            required=False,
            widget=forms.NumberInput(attrs={
                "class": "form-control",
                "min": "0", "max": "3", "step": "0.01",
                "placeholder": "e.g. 0.98",
            }),
        )

        # Manufacturer-specific fields: options are loaded by JS.
        # Seed choices with the current instance value so the select pre-selects
        # correctly on page load before JS runs; accept any submitted value.
        for field_name in _MANUFACTURER_SPECIFIC_FIELDS:
            current_val = getattr(self.instance, field_name, "") if self.instance and self.instance.pk else ""
            choices = _BLANK_CHOICE[:]
            if current_val:
                choices.append((current_val, current_val))
            f = forms.ChoiceField(
                choices=choices,
                required=False,
                widget=forms.Select(attrs={"class": "form-control"}),
            )
            f.valid_value = lambda v: True  # noqa: E731 — accept any string
            self.fields[field_name] = f

        # protocol_name: free-text so saved values round-trip correctly
        self.fields["protocol_name"].widget = forms.TextInput(
            attrs={"class": "form-control"}
        )
        self.fields["protocol_name"].required = False

        # clinical_comments: free-text
        self.fields["clinical_comments"].widget = forms.Textarea(
            attrs={"class": "form-control", "rows": 3}
        )
        self.fields["clinical_comments"].required = False

        # mas_inputs: managed by JS; rendered as a hidden JSON field
        import json as _json
        instance = kwargs.get("instance")
        initial_json = _json.dumps(instance.mas_inputs if instance else {})
        self.fields["mas_inputs"].widget = forms.HiddenInput(
            attrs={"id": "id_mas_inputs"}
        )
        self.fields["mas_inputs"].initial = initial_json

        # dose_metadata: MultipleChoiceField backed by JSONField
        dose_choices = _get_choice_options("dose_metadata", protocol_type)
        # Strip the blank sentinel — checkboxes don't need it
        dose_choices_clean = [
            (v, d) for v, d in dose_choices if v != ""
        ]
        self.fields["dose_metadata"].choices = dose_choices_clean

        # Pre-populate dose_metadata initial from existing JSONField value
        if instance and isinstance(instance.dose_metadata, list):
            self.fields["dose_metadata"].initial = instance.dose_metadata

    def clean_mas_inputs(self) -> dict:
        import json as _json
        raw = self.cleaned_data.get("mas_inputs") or "{}"
        if isinstance(raw, dict):
            return raw
        try:
            value = _json.loads(raw)
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}

    def clean_dose_metadata(self) -> list[str]:
        return list(self.cleaned_data.get("dose_metadata") or [])
