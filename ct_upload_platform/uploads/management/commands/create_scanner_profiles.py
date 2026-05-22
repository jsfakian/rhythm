"""
Create one CTScannerProfile per CTScannerModel entry in the catalogue.
Safe to run multiple times — skips models that already have a profile.
"""

from django.core.management.base import BaseCommand

from uploads.models import CTScannerModel, CTScannerProfile


class Command(BaseCommand):
    help = "Create a scanner profile for every scanner model in the catalogue"

    def handle(self, *args, **kwargs) -> None:
        models_qs = CTScannerModel.objects.filter(is_active=True).select_related("manufacturer")
        created = 0
        skipped = 0
        for model in models_qs:
            exists = CTScannerProfile.objects.filter(
                manufacturer=model.manufacturer,
                scanner_model=model,
            ).exists()
            if exists:
                skipped += 1
                continue
            CTScannerProfile.objects.create(
                manufacturer=model.manufacturer,
                scanner_model=model,
                created_by="system",
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created {created} scanner profiles, skipped {skipped} already existing."
        ))
