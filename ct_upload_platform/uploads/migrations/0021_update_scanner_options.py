from django.db import migrations


def add_fujifilm_3d_modulation(apps, schema_editor):
    CTManufacturer = apps.get_model("uploads", "CTManufacturer")
    CTManufacturerFieldOption = apps.get_model("uploads", "CTManufacturerFieldOption")

    try:
        fujifilm = CTManufacturer.objects.get(name="Fujifilm / Hitachi")
    except CTManufacturer.DoesNotExist:
        return

    # Insert 3D Modulation On/Off before Intelli EC — bump sort_order of existing AEC options
    existing = CTManufacturerFieldOption.objects.filter(
        manufacturer=fujifilm, field_key="auto_ma_modulation"
    )
    # Shift sort_orders ≥ 1 up by 2 to make room (Off stays at 0)
    for opt in existing.filter(sort_order__gte=1):
        opt.sort_order += 2
        opt.save()

    CTManufacturerFieldOption.objects.get_or_create(
        manufacturer=fujifilm,
        field_key="auto_ma_modulation",
        value="3D Modulation On",
        defaults={"sort_order": 1},
    )
    CTManufacturerFieldOption.objects.get_or_create(
        manufacturer=fujifilm,
        field_key="auto_ma_modulation",
        value="3D Modulation Off",
        defaults={"sort_order": 2},
    )


def rename_united_imaging_udose(apps, schema_editor):
    CTManufacturer = apps.get_model("uploads", "CTManufacturer")
    CTManufacturerFieldOption = apps.get_model("uploads", "CTManufacturerFieldOption")
    CTProtocol = apps.get_model("uploads", "CTProtocol")

    try:
        united = CTManufacturer.objects.get(name="United Imaging")
    except CTManufacturer.DoesNotExist:
        return

    # Rename the dropdown option value
    CTManufacturerFieldOption.objects.filter(
        manufacturer=united,
        field_key="auto_ma_modulation",
        value="uDose 3D",
    ).update(value="uDose 3D Dose Modulation")

    # Keep existing protocol records consistent
    CTProtocol.objects.filter(auto_ma_modulation="uDose 3D").update(
        auto_ma_modulation="uDose 3D Dose Modulation"
    )


def update_ma_input_specs(apps, schema_editor):
    MaModulationInputSpec = apps.get_model("uploads", "MaModulationInputSpec")

    new_and_updated = [
        ("3D Modulation On",         ["Min mA", "Max mA"]),
        ("3D Modulation Off",        ["Min mA", "Max mA"]),
        ("uDose 3D",                 ["Min mA", "Max mA", "Patient size / attenuation"]),
        ("uDose 3D Dose Modulation", ["Min mA", "Max mA", "Patient size / attenuation"]),
        ("Auto ALARA mA",            ["Min mA", "Max mA", "Patient size / attenuation"]),
    ]

    for value, labels in new_and_updated:
        MaModulationInputSpec.objects.update_or_create(
            ma_modulation_value=value,
            defaults={"input_labels": labels},
        )


def reverse_changes(apps, schema_editor):
    CTManufacturer = apps.get_model("uploads", "CTManufacturer")
    CTManufacturerFieldOption = apps.get_model("uploads", "CTManufacturerFieldOption")
    CTProtocol = apps.get_model("uploads", "CTProtocol")
    MaModulationInputSpec = apps.get_model("uploads", "MaModulationInputSpec")

    try:
        fujifilm = CTManufacturer.objects.get(name="Fujifilm / Hitachi")
        CTManufacturerFieldOption.objects.filter(
            manufacturer=fujifilm,
            field_key="auto_ma_modulation",
            value__in=["3D Modulation On", "3D Modulation Off"],
        ).delete()
    except CTManufacturer.DoesNotExist:
        pass

    try:
        united = CTManufacturer.objects.get(name="United Imaging")
        CTManufacturerFieldOption.objects.filter(
            manufacturer=united,
            field_key="auto_ma_modulation",
            value="uDose 3D Dose Modulation",
        ).update(value="uDose 3D")
        CTProtocol.objects.filter(auto_ma_modulation="uDose 3D Dose Modulation").update(
            auto_ma_modulation="uDose 3D"
        )
    except CTManufacturer.DoesNotExist:
        pass

    MaModulationInputSpec.objects.filter(
        ma_modulation_value__in=["3D Modulation On", "3D Modulation Off"]
    ).delete()
    MaModulationInputSpec.objects.filter(
        ma_modulation_value__in=["uDose 3D", "uDose 3D Dose Modulation", "Auto ALARA mA"]
    ).update(input_labels=["Min mA", "Max mA"])


class Migration(migrations.Migration):

    dependencies = [
        ("uploads", "0020_examination_rhythm_id_and_profile_sitecode"),
    ]

    operations = [
        migrations.RunPython(add_fujifilm_3d_modulation, reverse_code=reverse_changes),
        migrations.RunPython(rename_united_imaging_udose, reverse_code=migrations.RunPython.noop),
        migrations.RunPython(update_ma_input_specs, reverse_code=migrations.RunPython.noop),
    ]
