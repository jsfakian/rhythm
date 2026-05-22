from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

try:
    from django_filters.rest_framework import DjangoFilterBackend
except ImportError:
    DjangoFilterBackend = None  # type: ignore[assignment,misc]

from .models import (
    CTManufacturer,
    CTScannerModel,
    CTScannerProfile,
    CTProtocol,
    ProtocolChoiceCategory,
    ProtocolChoiceOption,
)
from .protocol_serializers import (
    CTManufacturerSerializer,
    CTScannerModelSerializer,
    CTScannerProfileSerializer,
    CTProtocolSerializer,
    ProtocolChoiceCategorySerializer,
    ProtocolChoiceOptionSerializer,
)

# Build a filter-backend list that excludes None when django_filters is absent.
_DJANGO_FILTER_BACKENDS = [DjangoFilterBackend] if DjangoFilterBackend is not None else []


class CTManufacturerViewSet(viewsets.ModelViewSet):
    queryset = CTManufacturer.objects.filter(is_active=True).order_by("sort_order", "name")
    serializer_class = CTManufacturerSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]

    @action(detail=True, methods=["get"], url_path="models")
    def scanner_models(self, request: Request, pk: str | None = None) -> Response:
        """Return all active scanner models belonging to this manufacturer."""
        manufacturer = self.get_object()
        qs = CTScannerModel.objects.filter(
            manufacturer=manufacturer, is_active=True
        ).order_by("sort_order", "name")
        serializer = CTScannerModelSerializer(qs, many=True)
        return Response(serializer.data)


class CTScannerModelViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        CTScannerModel.objects.filter(is_active=True)
        .select_related("manufacturer")
        .order_by("sort_order", "name")
    )
    serializer_class = CTScannerModelSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "manufacturer__name"]

    def get_queryset(self):
        qs = super().get_queryset()
        manufacturer_id = self.request.query_params.get("manufacturer")
        if manufacturer_id:
            qs = qs.filter(manufacturer_id=manufacturer_id)
        return qs


class ProtocolChoiceCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProtocolChoiceCategory.objects.prefetch_related("options").order_by(
        "sort_order", "label"
    )
    serializer_class = ProtocolChoiceCategorySerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"], url_path=r"by-key/(?P<key>[^/.]+)")
    def by_key(self, request: Request, key: str | None = None) -> Response:
        """Return a single category looked up by its unique key."""
        try:
            category = ProtocolChoiceCategory.objects.prefetch_related("options").get(key=key)
        except ProtocolChoiceCategory.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(category)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="options")
    def options(self, request: Request, pk: str | None = None) -> Response:
        """
        Return options for a category, optionally narrowed by protocol_type.

        ?protocol_type=PEDIATRIC_HEAD returns options whose applicable_protocol_types
        is empty (applies to all) OR contains the requested type.
        """
        category = self.get_object()
        qs = ProtocolChoiceOption.objects.filter(
            category=category, is_active=True
        ).order_by("sort_order", "display")

        protocol_type = request.query_params.get("protocol_type")
        if protocol_type:
            # Keep options with an empty list (all types) or the requested type present.
            qs = [
                opt
                for opt in qs
                if not opt.applicable_protocol_types
                or protocol_type in opt.applicable_protocol_types
            ]

        serializer = ProtocolChoiceOptionSerializer(qs, many=True)
        return Response(serializer.data)


class CTScannerProfileViewSet(viewsets.ModelViewSet):
    queryset = (
        CTScannerProfile.objects.select_related("manufacturer", "scanner_model")
        .order_by("-created_at")
    )
    serializer_class = CTScannerProfileSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer: CTScannerProfileSerializer) -> None:
        serializer.save(created_by=self.request.user.username)


class CTProtocolViewSet(viewsets.ModelViewSet):
    queryset = (
        CTProtocol.objects.select_related(
            "scanner__manufacturer", "scanner__scanner_model"
        ).order_by("-created_at")
    )
    serializer_class = CTProtocolSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["protocol_name", "clinical_indication", "anatomical_region"]
    ordering_fields = ["created_at", "protocol_name", "protocol_type"]

    def get_queryset(self):
        qs = super().get_queryset()
        protocol_type = self.request.query_params.get("protocol_type")
        if protocol_type:
            qs = qs.filter(protocol_type=protocol_type)
        scanner_id = self.request.query_params.get("scanner")
        if scanner_id:
            qs = qs.filter(scanner_id=scanner_id)
        return qs

    def perform_create(self, serializer: CTProtocolSerializer) -> None:
        serializer.save(created_by=self.request.user.username)

    @action(detail=False, methods=["get"], url_path=r"by-type/(?P<ptype>[^/.]+)")
    def by_type(self, request: Request, ptype: str | None = None) -> Response:
        """Return all protocols matching a specific protocol_type value."""
        valid_types = {choice[0] for choice in CTProtocol.PROTOCOL_TYPE_CHOICES}
        if ptype not in valid_types:
            return Response(
                {
                    "detail": f"Invalid protocol type '{ptype}'. "
                    f"Valid choices: {sorted(valid_types)}."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        qs = self.get_queryset().filter(protocol_type=ptype)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)
