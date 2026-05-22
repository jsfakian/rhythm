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
    ProtocolChoiceOption,
)

_BLANK_CHOICE = [("", "--- Select ---")]

# Map protocol_type value → category key for age_group
_AGE_GROUP_KEY: dict[str, str] = {
    "PEDIATRIC_HEAD": "age_group_pediatric_head",
    "PEDIATRIC_BODY": "age_group_pediatric_body",
    "YOUNG_ADULT": "age_group_young_adult",
}

# Map protocol_type value → category key for clinical_indication
_CLINICAL_INDICATION_KEY: dict[str, str] = {
    "PEDIATRIC_HEAD": "clinical_indication_pediatric_head",
    "PEDIATRIC_BODY": "clinical_indication_pediatric_body",
    "YOUNG_ADULT": "clinical_indication_adult",
}

# CTProtocol CharField fields whose choices come from a same-named category key
_SIMPLE_CHOICE_FIELDS = [
    "protocol_name",
    "anatomical_region",
    "scan_type",
    "contrast",
    "number_of_phases",
    "auto_kvp_selection",
    "kvp",
    "auto_ma_modulation",
    "exposure_metric",
    "pitch",
    "rotation_time",
    "slice_thickness",
    "scan_fov",
    "kernel_class",
    "reconstruction_algorithm",
    "protocol_intent",
]


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


class CTProtocolForm(forms.ModelForm):
    dose_metadata = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple(),
        required=False,
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
            "clinical_indication",
            "protocol_name",
            "anatomical_region",
            "scan_type",
            "contrast",
            "number_of_phases",
            "auto_kvp_selection",
            "kvp",
            "auto_ma_modulation",
            "exposure_metric",
            "mas_value",
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

        # age_group
        age_key = _AGE_GROUP_KEY.get(protocol_type or "", "age_group_pediatric_head")
        age_choices = _get_choice_options(age_key, protocol_type)
        self.fields["age_group"] = forms.ChoiceField(
            choices=age_choices,
            widget=forms.Select(attrs={"class": "form-control"}),
        )

        # clinical_indication
        ind_key = _CLINICAL_INDICATION_KEY.get(
            protocol_type or "", "clinical_indication_pediatric_head"
        )
        ind_choices = _get_choice_options(ind_key, protocol_type)
        self.fields["clinical_indication"] = forms.ChoiceField(
            choices=ind_choices,
            required=False,
            widget=forms.Select(attrs={"class": "form-control"}),
        )

        # Simple single-select CharField fields
        for field_name in _SIMPLE_CHOICE_FIELDS:
            choices = _get_choice_options(field_name, protocol_type)
            self.fields[field_name] = forms.ChoiceField(
                choices=choices,
                required=False,
                widget=forms.Select(attrs={"class": "form-control"}),
            )

        # mas_value: free-text CharField (not in SIMPLE_CHOICE_FIELDS), apply form-control
        self.fields["mas_value"].widget = forms.TextInput(
            attrs={"class": "form-control"}
        )

        # dose_metadata: MultipleChoiceField backed by JSONField
        dose_choices = _get_choice_options("dose_metadata", protocol_type)
        # Strip the blank sentinel — checkboxes don't need it
        dose_choices_clean = [
            (v, d) for v, d in dose_choices if v != ""
        ]
        self.fields["dose_metadata"].choices = dose_choices_clean

        # Pre-populate dose_metadata initial from existing JSONField value
        instance = kwargs.get("instance")
        if instance and isinstance(instance.dose_metadata, list):
            self.fields["dose_metadata"].initial = instance.dose_metadata

    def clean_dose_metadata(self) -> list[str]:
        return list(self.cleaned_data.get("dose_metadata") or [])
