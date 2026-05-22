"""
Class-based views for CT scanner profiles and CT protocols.
All views require authentication via LoginRequiredMixin.
"""

import json
from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import DeleteView, DetailView, ListView

from .models import (
    CTExamination,
    CTManufacturer,
    CTProtocol,
    CTScannerModel,
    CTScannerProfile,
    ProtocolChoiceOption,
)
from .protocol_forms import CTProtocolForm, CTScannerProfileForm


_LOGIN_URL = '/login/'
_PROTOCOL_TYPE_CHOICES = CTProtocol.PROTOCOL_TYPE_CHOICES


def _resolve_manufacturer(post_value: str) -> CTManufacturer | None:
    """Return an existing CTManufacturer by pk, or create one if value is a plain name."""
    if not post_value:
        return None
    try:
        return CTManufacturer.objects.get(pk=post_value)
    except (CTManufacturer.DoesNotExist, Exception):
        name = post_value.strip()
        if not name:
            return None
        obj, _ = CTManufacturer.objects.get_or_create(name=name)
        return obj


def _resolve_scanner_model(post_value: str, manufacturer: CTManufacturer | None) -> CTScannerModel | None:
    """Return an existing CTScannerModel by pk, or create one under manufacturer if value is a plain name."""
    if not post_value:
        return None
    try:
        return CTScannerModel.objects.get(pk=post_value)
    except (CTScannerModel.DoesNotExist, Exception):
        name = post_value.strip()
        if not name or manufacturer is None:
            return None
        obj, _ = CTScannerModel.objects.get_or_create(manufacturer=manufacturer, name=name)
        return obj


class ProtocolListView(LoginRequiredMixin, ListView):
    login_url = _LOGIN_URL
    model = CTProtocol
    template_name = "uploads/protocol_list.html"
    context_object_name = "protocols"
    paginate_by = 20

    def get_queryset(self):
        protocol_type: str = self.kwargs["protocol_type"]
        return (
            CTProtocol.objects.filter(protocol_type=protocol_type)
            .select_related("scanner__manufacturer", "scanner__scanner_model")
            .order_by("-created_at")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        protocol_type: str = self.kwargs["protocol_type"]
        context["protocol_type"] = protocol_type
        context["protocol_type_display"] = dict(CTProtocol.PROTOCOL_TYPE_CHOICES).get(
            protocol_type, protocol_type
        )
        # page_obj is already added by ListView via paginate_by; expose explicitly
        context["page_obj"] = context.get("page_obj")
        return context


class ProtocolDetailView(LoginRequiredMixin, DetailView):
    login_url = _LOGIN_URL
    model = CTProtocol
    template_name = "uploads/protocol_detail.html"
    context_object_name = "protocol"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        obj: CTProtocol = self.object  # type: ignore[assignment]
        context["protocol_type_display"] = dict(
            CTProtocol.PROTOCOL_TYPE_CHOICES
        ).get(obj.protocol_type, obj.protocol_type)

        # Resolve dose_metadata values to human-readable display names
        stored_values: list[str] = obj.dose_metadata if isinstance(obj.dose_metadata, list) else []
        if stored_values:
            option_map = dict(
                ProtocolChoiceOption.objects.filter(
                    category__key="dose_metadata",
                    value__in=stored_values,
                ).values_list("value", "display")
            )
            context["dose_metadata_display"] = [
                option_map.get(v, v) for v in stored_values
            ]
        else:
            context["dose_metadata_display"] = []
        return context


class ProtocolCreateView(LoginRequiredMixin, View):
    login_url = _LOGIN_URL
    template_name = "uploads/protocol_form.html"

    def get(self, request: HttpRequest, protocol_type: str) -> HttpResponse:
        form = CTProtocolForm(protocol_type=protocol_type)
        return render(
            request,
            self.template_name,
            {"form": form, "protocol_type": protocol_type, "is_update": False},
        )

    def post(self, request: HttpRequest, protocol_type: str) -> HttpResponse:
        form = CTProtocolForm(request.POST, protocol_type=protocol_type)
        if form.is_valid():
            protocol: CTProtocol = form.save(commit=False)
            protocol.created_by = request.user.username
            protocol.save()
            return redirect(
                reverse(
                    "protocol-detail",
                    kwargs={"protocol_type": protocol.protocol_type, "pk": str(protocol.pk)},
                )
            )
        return render(
            request,
            self.template_name,
            {"form": form, "protocol_type": protocol_type, "is_update": False},
        )


class ProtocolUpdateView(LoginRequiredMixin, View):
    login_url = _LOGIN_URL
    template_name = "uploads/protocol_form.html"

    def _get_object(self, pk: str) -> CTProtocol:
        return get_object_or_404(CTProtocol, pk=pk)

    def get(self, request: HttpRequest, protocol_type: str, pk: str) -> HttpResponse:
        obj = self._get_object(pk)
        form = CTProtocolForm(instance=obj, protocol_type=obj.protocol_type)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "protocol": obj,
                "protocol_type": obj.protocol_type,
                "is_update": True,
            },
        )

    def post(self, request: HttpRequest, protocol_type: str, pk: str) -> HttpResponse:
        obj = self._get_object(pk)
        form = CTProtocolForm(
            request.POST, instance=obj, protocol_type=obj.protocol_type
        )
        if form.is_valid():
            protocol: CTProtocol = form.save(commit=False)
            protocol.save()
            return redirect(
                reverse(
                    "protocol-detail",
                    kwargs={"protocol_type": protocol.protocol_type, "pk": str(protocol.pk)},
                )
            )
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "protocol": obj,
                "protocol_type": obj.protocol_type,
                "is_update": True,
            },
        )


class ProtocolDeleteView(LoginRequiredMixin, DeleteView):
    login_url = _LOGIN_URL
    model = CTProtocol
    template_name = "uploads/protocol_confirm_delete.html"

    def get_success_url(self) -> str:
        protocol_type: str = self.object.protocol_type  # type: ignore[union-attr]
        return reverse_lazy("protocol-list", kwargs={"protocol_type": protocol_type})


class ScannerProfileCreateView(LoginRequiredMixin, View):
    login_url = _LOGIN_URL
    template_name = "uploads/scanner_profile_form.html"

    def _protocol_type_from_request(self, request: HttpRequest) -> str:
        return (
            request.GET.get("protocol_type")
            or request.POST.get("protocol_type")
            or ""
        )

    def get(self, request: HttpRequest) -> HttpResponse:
        form = CTScannerProfileForm()
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "protocol_type": self._protocol_type_from_request(request),
            },
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        protocol_type = self._protocol_type_from_request(request)
        post = request.POST.copy()
        manufacturer = _resolve_manufacturer(post.get("manufacturer", ""))
        model = _resolve_scanner_model(post.get("scanner_model", ""), manufacturer)
        if manufacturer:
            post["manufacturer"] = str(manufacturer.pk)
        if model:
            post["scanner_model"] = str(model.pk)
        form = CTScannerProfileForm(post)
        if manufacturer and model:
            form.fields["scanner_model"].queryset = CTScannerModel.objects.filter(pk=model.pk)
        if form.is_valid():
            profile: CTScannerProfile = form.save(commit=False)
            profile.created_by = request.user.username
            profile.save()
            if protocol_type:
                return redirect(
                    reverse("protocol-create", kwargs={"protocol_type": protocol_type})
                )
            return redirect(reverse("scanner-profile-list"))
        return render(
            request,
            self.template_name,
            {"form": form, "protocol_type": protocol_type},
        )


class ScannerProfileEditView(LoginRequiredMixin, View):
    login_url = _LOGIN_URL
    template_name = "uploads/scanner_profile_form.html"

    def _get_profile(self, pk: str) -> CTScannerProfile:
        from django.shortcuts import get_object_or_404
        return get_object_or_404(CTScannerProfile, pk=pk)

    def get(self, request: HttpRequest, pk: str) -> HttpResponse:
        profile = self._get_profile(pk)
        form = CTScannerProfileForm(instance=profile)
        return render(request, self.template_name, {"form": form, "is_edit": True})

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        profile = self._get_profile(pk)
        post = request.POST.copy()
        manufacturer = _resolve_manufacturer(post.get("manufacturer", ""))
        model = _resolve_scanner_model(post.get("scanner_model", ""), manufacturer)
        if manufacturer:
            post["manufacturer"] = str(manufacturer.pk)
        if model:
            post["scanner_model"] = str(model.pk)
        form = CTScannerProfileForm(post, instance=profile)
        if manufacturer and model:
            form.fields["scanner_model"].queryset = CTScannerModel.objects.filter(pk=model.pk)
        if form.is_valid():
            form.save()
            return redirect(reverse("scanner-profile-list"))
        return render(request, self.template_name, {"form": form, "is_edit": True})


class ScannerProfileListView(LoginRequiredMixin, ListView):
    login_url = _LOGIN_URL
    model = CTScannerProfile
    template_name = "uploads/scanner_profile_list.html"
    context_object_name = "scanner_profiles"
    paginate_by = 20

    def get_queryset(self):
        return CTScannerProfile.objects.select_related(
            "manufacturer", "scanner_model"
        ).order_by("-created_at")


class ScannerModelsByManufacturerView(View):
    """Return JSON list of active scanner models for a given manufacturer_id."""

    def get(self, request: HttpRequest) -> JsonResponse:
        manufacturer_id = request.GET.get("manufacturer_id", "")
        if not manufacturer_id:
            return JsonResponse({"models": []})

        models_qs = (
            CTScannerModel.objects.filter(
                manufacturer_id=manufacturer_id,
                is_active=True,
            )
            .order_by("sort_order", "name")
            .values("id", "name")
        )
        return JsonResponse({"models": list(models_qs)})


class ProtocolsHubView(LoginRequiredMixin, View):
    """Single scanner-centred protocols page replacing the per-type tab views."""

    login_url = _LOGIN_URL
    template_name = "uploads/protocol_hub.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        scanners = (
            CTScannerProfile.objects.select_related("manufacturer", "scanner_model")
            .order_by("manufacturer__name", "scanner_model__name", "-created_at")
        )

        type_choices = list(_PROTOCOL_TYPE_CHOICES)  # [(key, label), ...]

        scanner_data: list[dict] = []
        for scanner in scanners:
            groups: list[dict] = []
            for ptype, plabel in type_choices:
                protocols = list(
                    CTProtocol.objects.filter(scanner=scanner, protocol_type=ptype)
                    .order_by("protocol_name", "age_group")
                    .values("pk", "protocol_name", "age_group", "clinical_indication",
                            "scan_type", "kvp", "contrast")
                )
                groups.append({"key": ptype, "label": plabel, "protocols": protocols})
            scanner_data.append({"scanner": scanner, "groups": groups})

        return render(request, self.template_name, {
            "scanner_data": scanner_data,
            "type_choices": type_choices,
            "manufacturers": CTManufacturer.objects.filter(is_active=True).order_by("sort_order"),
        })


class ProtocolGUIView(LoginRequiredMixin, View):
    """Clinical indication-centered protocol GUI."""

    login_url = _LOGIN_URL
    template_name = "uploads/protocol_clinical_gui.html"

    CLINICAL_ROWS = [
        {"anatomical_region": "Head", "clinical_indication": "Trauma", "iv_contrast": "Non-contrast", "comments": "Can include anatomical based protocol"},
        {"anatomical_region": "Mastoid bone/Inner Ear", "clinical_indication": "Hearing loss; congenital malformations, infection, cholesteatoma, cochlear implants", "iv_contrast": "Non-contrast", "comments": "Only dedicated mastoid bone protocol"},
        {"anatomical_region": "Chest", "clinical_indication": "Complicated and fungal infections", "iv_contrast": "Non-contrast, Contrast-enhanced", "comments": "Can be anatomical based protocol"},
        {"anatomical_region": "Chest/HRCT (Inspiration/Expiration)", "clinical_indication": "Interstitial lung diseases, small airways disease, cystic fibrosis, asthma, primary ciliary dyskinesia, chronic lung disease of prematurity", "iv_contrast": "Non-contrast", "comments": "Can be anatomical based protocol"},
        {"anatomical_region": "Abdomen", "clinical_indication": "Acute abdomen", "iv_contrast": "Contrast-enhanced", "comments": "Can be anatomical based protocol"},
        {"anatomical_region": "Neck-Chest-Abdomen", "clinical_indication": "Lymphoma", "iv_contrast": "Contrast-enhanced", "comments": "Can be anatomical based protocol"},
    ]

    PROTOCOL_TABS = {
        "PEDIATRIC_HEAD": {
            "label": "Pediatric HEAD",
            "examination_groups": ["Group 1 - Neonate", "Group 2 - Infant, Toddler and Early childhood", "Group 3 - Childhood", "Group 4 - Early Adolescence", "Group 5 - Adolescence"],
            "age_groups": ["< 5 kg", "5 kg - 15 kg", "15 kg - 30 kg", "30 kg - 50 kg", "50 kg - 80 kg"],
        },
        "PEDIATRIC_BODY": {
            "label": "Pediatric Body",
            "examination_groups": ["Group 1 - Neonate", "Group 2 - Infant, Toddler and Early childhood", "Group 3 - Childhood", "Group 4 - Early Adolescence", "Group 5 - Adolescence"],
            "age_groups": ["< 5 kg", "5 kg - 15 kg", "15 kg - 30 kg", "30 kg - 50 kg", "50 kg - 80 kg"],
        },
        "YOUNG_ADULT": {
            "label": "Young Adult",
            "examination_groups": ["Group 6 - Young Adulthood"],
            "age_groups": ["> 80 kg"],
        },
    }

    def _get_protocol_choices(self) -> dict:
        qs = ProtocolChoiceOption.objects.filter(is_active=True).select_related("category").order_by("sort_order", "display")
        choices: dict = {}
        for opt in qs:
            key = opt.category.key
            if key not in choices:
                choices[key] = []
            choices[key].append({"value": opt.value, "display": opt.display})
        return choices

    def get(self, request: HttpRequest) -> HttpResponse:
        scanners = list(
            CTScannerProfile.objects.select_related("manufacturer", "scanner_model")
            .order_by("manufacturer__name", "scanner_model__name", "-created_at")
            .values("id", "manufacturer__name", "scanner_model__name", "detector_rows", "year_of_installation", "local_protocol_note")
        )
        scanner_list = [
            {
                "id": str(s["id"]),
                "display": f"{s['manufacturer__name']} – {s['scanner_model__name']}",
                "manufacturer": s["manufacturer__name"],
                "model": s["scanner_model__name"],
                "detector_rows": s["detector_rows"] or "",
                "year": s["year_of_installation"] or "",
                "note": s["local_protocol_note"] or "",
            }
            for s in scanners
        ]
        return render(request, self.template_name, {
            "clinical_rows_json": json.dumps(self.CLINICAL_ROWS),
            "scanners_json": json.dumps(scanner_list),
            "protocol_tabs_json": json.dumps(self.PROTOCOL_TABS),
            "protocol_choices_json": json.dumps(self._get_protocol_choices()),
        })


class ProtocolSaveAPIView(LoginRequiredMixin, View):
    """AJAX endpoint: create or update a CTProtocol. Returns JSON."""

    login_url = _LOGIN_URL

    def post(self, request: HttpRequest) -> JsonResponse:
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        scanner_id = data.get("scanner_id", "")
        protocol_type = data.get("protocol_type", "")
        anatomical_region = data.get("anatomical_region", "")
        clinical_indication = data.get("clinical_indication", "")
        contrast = data.get("contrast", "")
        clinical_comments = data.get("clinical_comments", "")
        examination_group = data.get("examination_group", "")
        age_group = data.get("age_group", "")
        force_update = data.get("force_update", False)

        if not scanner_id or not protocol_type or not examination_group or not age_group:
            return JsonResponse({"error": "scanner_id, protocol_type, examination_group and age_group are required"}, status=400)

        try:
            scanner = CTScannerProfile.objects.get(pk=scanner_id)
        except CTScannerProfile.DoesNotExist:
            return JsonResponse({"error": "Scanner not found"}, status=404)

        lookup = {
            "scanner": scanner,
            "protocol_type": protocol_type,
            "anatomical_region": anatomical_region,
            "clinical_indication": clinical_indication,
            "contrast": contrast,
            "clinical_comments": clinical_comments,
            "examination_group": examination_group,
            "age_group": age_group,
        }
        existing = CTProtocol.objects.filter(**lookup).first()

        if existing and not force_update:
            return JsonResponse({
                "status": "exists",
                "id": str(existing.pk),
                "message": "A protocol entry for this Clinical Indication / Region, Examination group, and Age / weight group already exists. Click Save again to update it.",
            })

        protocol_fields = data.get("protocol_fields", {})
        protocol_data = {**lookup}
        protocol_data.update({
            "protocol_name": protocol_fields.get("protocol_name", ""),
            "scan_type": protocol_fields.get("scan_type", ""),
            "number_of_phases": protocol_fields.get("number_of_phases", ""),
            "auto_kvp_selection": protocol_fields.get("auto_kvp_selection", ""),
            "kvp": protocol_fields.get("kvp", ""),
            "auto_ma_modulation": protocol_fields.get("auto_ma_modulation", ""),
            "exposure_metric": protocol_fields.get("exposure_metric", ""),
            "mas_value": protocol_fields.get("mas_value", ""),
            "pitch": protocol_fields.get("pitch", ""),
            "rotation_time": protocol_fields.get("rotation_time", ""),
            "slice_thickness": protocol_fields.get("slice_thickness", ""),
            "scan_fov": protocol_fields.get("scan_fov", ""),
            "kernel_class": protocol_fields.get("kernel_class", ""),
            "reconstruction_algorithm": protocol_fields.get("reconstruction_algorithm", ""),
            "protocol_intent": protocol_fields.get("protocol_intent", ""),
            "dose_metadata": protocol_fields.get("dose_metadata", []),
            "notes": protocol_fields.get("notes", ""),
        })

        if existing and force_update:
            for field, value in protocol_data.items():
                if field != "scanner":
                    setattr(existing, field, value)
            existing.save()
            status = "updated"
            protocol_id = str(existing.pk)
        else:
            protocol_data["created_by"] = request.user.username
            obj = CTProtocol.objects.create(**protocol_data)
            status = "created"
            protocol_id = str(obj.pk)

        return JsonResponse({"status": status, "id": protocol_id, "message": f"Protocol successfully {status}."})


class ProtocolRecordsView(LoginRequiredMixin, View):
    """Page listing all saved protocol records."""

    login_url = _LOGIN_URL
    template_name = "uploads/protocol_records.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        qs = (
            CTProtocol.objects.select_related("scanner__manufacturer", "scanner__scanner_model")
            .order_by("-created_at")
        )
        protocol_type = request.GET.get("protocol_type", "")
        if protocol_type:
            qs = qs.filter(protocol_type=protocol_type)
        return render(request, self.template_name, {
            "protocols": qs,
            "protocol_type_choices": CTProtocol.PROTOCOL_TYPE_CHOICES,
            "selected_type": protocol_type,
        })


class ExaminationEntryView(LoginRequiredMixin, View):
    """Examination data entry page."""

    login_url = _LOGIN_URL
    template_name = "uploads/examination_entry.html"

    CLINICAL_ROWS = [
        {"anatomical_region": "Head", "clinical_indication": "Trauma"},
        {"anatomical_region": "Mastoid bone/Inner Ear", "clinical_indication": "Hearing loss; congenital malformations, infection, cholesteatoma, cochlear implants"},
        {"anatomical_region": "Chest", "clinical_indication": "Complicated and fungal infections"},
        {"anatomical_region": "Chest/HRCT (Inspiration/Expiration)", "clinical_indication": "Interstitial lung diseases, small airways disease, cystic fibrosis, asthma, primary ciliary dyskinesia, chronic lung disease of prematurity"},
        {"anatomical_region": "Abdomen", "clinical_indication": "Acute abdomen"},
        {"anatomical_region": "Neck-Chest-Abdomen", "clinical_indication": "Lymphoma"},
    ]

    ANATOMICAL_REGIONS = [
        "Head",
        "Chest",
        "Chest-Abdomen",
        "Neck-Chest-Abdomen",
        "Mastoid bone/Inner Ear",
        "Chest/HRCT (Inspiration/Expiration)",
        "Abdomen",
        "Pelvis",
        "Abdomen and pelvis",
    ]

    def _scanners_json(self) -> list:
        scanners = CTScannerProfile.objects.select_related(
            "manufacturer", "scanner_model"
        ).order_by("manufacturer__name", "scanner_model__name")
        return [
            {
                "id": str(s.pk),
                "manufacturer_id": str(s.manufacturer_id),
                "manufacturer": s.manufacturer.name,
                "model": s.scanner_model.name,
                "display": f"{s.manufacturer.name} – {s.scanner_model.name}",
                "detector_rows": s.detector_rows or "",
                "year": s.year_of_installation or "",
            }
            for s in scanners
        ]

    def _protocols_json(self) -> list:
        protocols = CTProtocol.objects.select_related(
            "scanner__manufacturer", "scanner__scanner_model"
        ).order_by("-created_at")
        return [
            {
                "id": str(p.pk),
                "display": (
                    f"{p.get_protocol_type_display()} – "
                    f"{p.anatomical_region or '—'} / {p.clinical_indication or '—'} "
                    f"({p.scanner.manufacturer.name} {p.scanner.scanner_model.name})"
                ),
                "scanner_id": str(p.scanner_id),
                "anatomical_region": p.anatomical_region,
                "clinical_indication": p.clinical_indication,
                "examination_group": p.examination_group,
                "age_group": p.age_group,
            }
            for p in protocols
        ]

    def _manufacturers_json(self) -> list:
        return [
            {"id": str(m.pk), "name": m.name}
            for m in CTManufacturer.objects.filter(is_active=True).order_by("sort_order", "name")
        ]

    def _choice_options(self, key: str) -> list[str]:
        return list(
            ProtocolChoiceOption.objects.filter(
                category__key=key, is_active=True
            ).order_by("sort_order", "display").values_list("value", flat=True)
        )

    def get(self, request: HttpRequest) -> HttpResponse:
        anatomical_options = self._choice_options("anatomical_region") or self.ANATOMICAL_REGIONS
        clinical_options = list({r["clinical_indication"] for r in self.CLINICAL_ROWS})
        clinical_options.sort()

        return render(request, self.template_name, {
            "scanners_json": json.dumps(self._scanners_json()),
            "protocols_json": json.dumps(self._protocols_json()),
            "manufacturers_json": json.dumps(self._manufacturers_json()),
            "anatomical_options_json": json.dumps(anatomical_options),
            "clinical_options_json": json.dumps(clinical_options),
            "clinical_rows_json": json.dumps(self.CLINICAL_ROWS),
        })


class ExaminationSaveAPIView(LoginRequiredMixin, View):
    """AJAX endpoint: save a CTExamination record. Returns JSON."""

    login_url = _LOGIN_URL

    def post(self, request: HttpRequest) -> JsonResponse:
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        protocol_id = data.get("protocol_id") or None
        scanner_id = data.get("scanner_id") or None
        anatomical_region = data.get("anatomical_region", "")
        clinical_indication = data.get("clinical_indication", "")
        patient_weight = data.get("patient_weight") or None
        wed = data.get("water_equivalent_diameter") or None
        patient_age = data.get("patient_age") or None
        number_of_phases = data.get("number_of_phases", 1)
        ctdi_vol = data.get("ctdi_vol_per_phase", [])
        dlp = data.get("dlp_per_phase", [])
        image_quality = data.get("image_quality", "")

        try:
            number_of_phases = int(number_of_phases)
            if number_of_phases < 1:
                raise ValueError
        except (TypeError, ValueError):
            return JsonResponse({"error": "number_of_phases must be a positive integer"}, status=400)

        if len(ctdi_vol) != number_of_phases or len(dlp) != number_of_phases:
            return JsonResponse(
                {"error": f"ctdi_vol_per_phase and dlp_per_phase must each have {number_of_phases} value(s)"},
                status=400,
            )

        protocol = None
        if protocol_id:
            try:
                protocol = CTProtocol.objects.get(pk=protocol_id)
            except CTProtocol.DoesNotExist:
                return JsonResponse({"error": "Protocol not found"}, status=404)

        scanner = None
        if scanner_id:
            try:
                scanner = CTScannerProfile.objects.get(pk=scanner_id)
            except CTScannerProfile.DoesNotExist:
                return JsonResponse({"error": "Scanner not found"}, status=404)

        exam = CTExamination.objects.create(
            protocol=protocol,
            scanner=scanner,
            anatomical_region=anatomical_region,
            clinical_indication=clinical_indication,
            patient_weight=patient_weight,
            water_equivalent_diameter=wed,
            patient_age=patient_age,
            number_of_phases=number_of_phases,
            ctdi_vol_per_phase=[float(v) if v not in (None, "") else None for v in ctdi_vol],
            dlp_per_phase=[float(v) if v not in (None, "") else None for v in dlp],
            image_quality=image_quality,
            created_by=request.user.username,
        )

        return JsonResponse({
            "status": "created",
            "id": str(exam.pk),
            "message": "Examination data saved successfully.",
        })


class ExaminationListView(LoginRequiredMixin, View):
    """Page listing all saved examination records."""

    login_url = _LOGIN_URL
    template_name = "uploads/examination_list.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        qs = (
            CTExamination.objects.select_related(
                "scanner__manufacturer", "scanner__scanner_model", "protocol"
            ).order_by("-created_at")
        )
        image_quality = request.GET.get("image_quality", "")
        if image_quality:
            qs = qs.filter(image_quality=image_quality)
        return render(request, self.template_name, {
            "examinations": qs,
            "image_quality_choices": CTExamination.IMAGE_QUALITY_CHOICES,
            "selected_quality": image_quality,
        })


class ExaminationDeleteView(LoginRequiredMixin, View):
    """Delete a single CTExamination."""

    login_url = _LOGIN_URL

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        exam = get_object_or_404(CTExamination, pk=pk)
        exam.delete()
        return redirect(reverse("examination-list"))

    def get(self, request: HttpRequest, pk: str) -> HttpResponse:
        exam = get_object_or_404(CTExamination, pk=pk)
        return render(request, "uploads/examination_confirm_delete.html", {"examination": exam})
