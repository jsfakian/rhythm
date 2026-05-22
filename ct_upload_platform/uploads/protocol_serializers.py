from rest_framework import serializers

from .models import (
    CTManufacturer,
    CTScannerModel,
    ProtocolChoiceCategory,
    ProtocolChoiceOption,
    CTScannerProfile,
    CTProtocol,
)


class CTManufacturerSerializer(serializers.ModelSerializer):
    class Meta:
        model = CTManufacturer
        fields = ["id", "name", "is_active", "sort_order"]
        read_only_fields = ["id"]


class CTScannerModelSerializer(serializers.ModelSerializer):
    manufacturer_name = serializers.SerializerMethodField()

    class Meta:
        model = CTScannerModel
        fields = [
            "id",
            "manufacturer",
            "manufacturer_name",
            "name",
            "notes",
            "is_active",
            "sort_order",
        ]
        read_only_fields = ["id", "manufacturer_name"]

    def get_manufacturer_name(self, obj: CTScannerModel) -> str:
        return obj.manufacturer.name


class ProtocolChoiceOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProtocolChoiceOption
        fields = ["id", "value", "display", "sort_order", "is_active", "applicable_protocol_types"]


class ProtocolChoiceCategorySerializer(serializers.ModelSerializer):
    options = ProtocolChoiceOptionSerializer(many=True, read_only=True)

    class Meta:
        model = ProtocolChoiceCategory
        fields = ["id", "key", "label", "description", "sort_order", "options"]


class CTScannerProfileSerializer(serializers.ModelSerializer):
    manufacturer_name = serializers.SerializerMethodField()
    scanner_model_name = serializers.SerializerMethodField()

    class Meta:
        model = CTScannerProfile
        fields = [
            "id",
            "manufacturer",
            "manufacturer_name",
            "scanner_model",
            "scanner_model_name",
            "detector_rows",
            "year_of_installation",
            "local_protocol_note",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "manufacturer_name",
            "scanner_model_name",
        ]

    def get_manufacturer_name(self, obj: CTScannerProfile) -> str:
        return obj.manufacturer.name

    def get_scanner_model_name(self, obj: CTScannerProfile) -> str:
        return obj.scanner_model.name


class CTProtocolSerializer(serializers.ModelSerializer):
    scanner_display = serializers.SerializerMethodField()
    protocol_type_display = serializers.SerializerMethodField()

    class Meta:
        model = CTProtocol
        fields = [
            "id",
            "scanner",
            "scanner_display",
            "protocol_type",
            "protocol_type_display",
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
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "scanner_display",
            "protocol_type_display",
        ]

    def get_scanner_display(self, obj: CTProtocol) -> str:
        return str(obj.scanner)

    def get_protocol_type_display(self, obj: CTProtocol) -> str:
        return obj.get_protocol_type_display()
