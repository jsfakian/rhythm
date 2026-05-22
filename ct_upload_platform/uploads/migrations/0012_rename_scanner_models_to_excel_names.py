"""
Data migration: rename CTScannerModel entries to use the full manufacturer-prefixed
names from the Excel scanner catalogue.
"""

from django.db import migrations


# (manufacturer_name, old_model_name, new_model_name)
_RENAMES: list[tuple[str, str, str]] = [
    # Canon Medical
    ("Canon Medical", "Aquilion ONE / GENESIS Edition", "Canon Aquilion ONE / GENESIS Edition"),
    ("Canon Medical", "ONE / ViSION Edition",           "Canon Aquilion ONE / ViSION Edition"),
    ("Canon Medical", "ONE / PRISM Edition",            "Canon Aquilion ONE / PRISM Edition"),
    ("Canon Medical", "Prime",                          "Canon Aquilion Prime"),
    ("Canon Medical", "Prime SP",                       "Canon Aquilion Prime SP"),
    ("Canon Medical", "Lightning",                      "Canon Aquilion Lightning"),
    ("Canon Medical", "Serve SP",                       "Canon Aquilion Serve SP"),
    ("Canon Medical", "Precision",                      "Canon Aquilion Precision"),
    ("Canon Medical", "Exceed LB",                      "Canon Aquilion Exceed LB"),
    ("Canon Medical", "LB",                             "Canon Aquilion LB"),
    # GE HealthCare
    ("GE HealthCare", "Revolution Apex Platform", "GE Revolution Apex Platform"),
    ("GE HealthCare", "Revolution CT",            "GE Revolution CT"),
    ("GE HealthCare", "Revolution Maxima",        "GE Revolution Maxima"),
    ("GE HealthCare", "Revolution Ascend",        "GE Revolution Ascend"),
    ("GE HealthCare", "Revolution Frontier",      "GE Revolution Frontier"),
    ("GE HealthCare", "Revolution EVO",           "GE Revolution EVO"),
    ("GE HealthCare", "Revolution ACT",           "GE Revolution ACT"),
    ("GE HealthCare", "Discovery CT750 HD",       "GE Discovery CT750 HD"),
    ("GE HealthCare", "Optima CT660",             "GE Optima CT660"),
    ("GE HealthCare", "LightSpeed VCT",           "GE LightSpeed VCT"),
    ("GE HealthCare", "BrightSpeed",              "GE BrightSpeed"),
    # Siemens Healthineers
    ("Siemens Healthineers", "NAEOTOM Alpha",             "Siemens NAEOTOM Alpha"),
    ("Siemens Healthineers", "SOMATOM Force",             "Siemens SOMATOM Force"),
    ("Siemens Healthineers", "SOMATOM Drive",             "Siemens SOMATOM Drive"),
    ("Siemens Healthineers", "SOMATOM Definition Flash",  "Siemens SOMATOM Definition Flash"),
    ("Siemens Healthineers", "SOMATOM Definition Edge",   "Siemens SOMATOM Definition Edge"),
    ("Siemens Healthineers", "SOMATOM Definition AS",     "Siemens SOMATOM Definition AS"),
    ("Siemens Healthineers", "SOMATOM X.cite",            "Siemens SOMATOM X.cite"),
    ("Siemens Healthineers", "SOMATOM X.ceed",            "Siemens SOMATOM X.ceed"),
    ("Siemens Healthineers", "SOMATOM X.serve",           "Siemens SOMATOM X.serve"),
    ("Siemens Healthineers", "SOMATOM go.Top",            "Siemens SOMATOM go.Top"),
    ("Siemens Healthineers", "SOMATOM go.All",            "Siemens SOMATOM go.All"),
    ("Siemens Healthineers", "SOMATOM go.Up",             "Siemens SOMATOM go.Up"),
    ("Siemens Healthineers", "SOMATOM go.Now",            "Siemens SOMATOM go.Now"),
    ("Siemens Healthineers", "SOMATOM Perspective",       "Siemens SOMATOM Perspective"),
    # Philips
    ("Philips", "Spectral CT 7500", "Philips Spectral CT 7500"),
    ("Philips", "IQon Spectral CT", "Philips IQon Spectral CT"),
    ("Philips", "Incisive CT",      "Philips Incisive CT"),
    ("Philips", "CT 5300",          "Philips CT 5300"),
    ("Philips", "Ingenuity CT",     "Philips Ingenuity CT"),
    ("Philips", "Brilliance iCT",   "Philips Brilliance iCT"),
    ("Philips", "Brilliance 64",    "Philips Brilliance 64"),
    ("Philips", "Big Bore RT",      "Philips Big Bore RT"),
    # United Imaging
    ("United Imaging", "uCT ATLAS", "United Imaging uCT ATLAS"),
    ("United Imaging", "uCT 960+",  "United Imaging uCT 960+"),
    ("United Imaging", "uCT 780",   "United Imaging uCT 780"),
    ("United Imaging", "uCT 760",   "United Imaging uCT 760"),
    ("United Imaging", "uCT 550",   "United Imaging uCT 550"),
    ("United Imaging", "uCT 530",   "United Imaging uCT 530"),
    ("United Imaging", "uCT 528",   "United Imaging uCT 528"),
    ("United Imaging", "uCT 520",   "United Imaging uCT 520"),
    ("United Imaging", "uCT 510",   "United Imaging uCT 510"),
    # Neusoft Medical
    ("Neusoft Medical", "NeuViz Epoch+",     "Neusoft NeuViz Epoch+ CT"),
    ("Neusoft Medical", "NeuViz Epoch",      "Neusoft NeuViz Epoch CT"),
    ("Neusoft Medical", "NeuViz Glory+",     "Neusoft NeuViz Glory+ CT"),
    ("Neusoft Medical", "NeuViz Glory",      "Neusoft NeuViz Glory CT"),
    ("Neusoft Medical", "NeuViz Prime",      "Neusoft NeuViz Prime CT"),
    ("Neusoft Medical", "NeuViz 128",        "Neusoft NeuViz 128 CT"),
    ("Neusoft Medical", "NeuViz ACE 128",    "Neusoft NeuViz ACE 128 CT"),
    ("Neusoft Medical", "NeuViz ACE 64e",    "Neusoft NeuViz ACE 64e CT"),
    ("Neusoft Medical", "NeuViz 64 In",      "Neusoft NeuViz 64 In CT"),
    ("Neusoft Medical", "NeuViz ACE UP",     "Neusoft NeuViz ACE UP CT"),
    ("Neusoft Medical", "NeuViz 16 Essence", "Neusoft NeuViz 16 Essence CT"),
    ("Neusoft Medical", "NeuViz 16 Classic", "Neusoft NeuViz 16 Classic CT"),
    ("Neusoft Medical", "NeuViz ACE SP",     "Neusoft NeuViz ACE SP CT"),
    # Fujifilm / Hitachi
    ("Fujifilm / Hitachi", "SCENARIA View",  "Fujifilm / Hitachi SCENARIA View"),
    ("Fujifilm / Hitachi", "SCENARIA",       "Hitachi SCENARIA"),
    ("Fujifilm / Hitachi", "Supria",         "Hitachi Supria"),
    ("Fujifilm / Hitachi", "Supria Grande",  "Hitachi Supria Grande"),
    # Samsung NeuroLogica
    ("Samsung NeuroLogica", "OmniTom Elite", "Samsung NeuroLogica OmniTom Elite"),
    ("Samsung NeuroLogica", "BodyTom Elite", "Samsung NeuroLogica BodyTom Elite"),
    # MinFound Medical
    ("MinFound Medical", "ScintCare CT 16",  "MinFound ScintCare CT 16"),
    ("MinFound Medical", "ScintCare CT 64",  "MinFound ScintCare CT 64"),
    ("MinFound Medical", "ScintCare CT 128", "MinFound ScintCare CT 128"),
]


def rename_scanner_models(apps, schema_editor):
    CTManufacturer = apps.get_model("uploads", "CTManufacturer")
    CTScannerModel = apps.get_model("uploads", "CTScannerModel")

    for mfr_name, old_name, new_name in _RENAMES:
        try:
            mfr = CTManufacturer.objects.get(name=mfr_name)
        except CTManufacturer.DoesNotExist:
            continue
        CTScannerModel.objects.filter(manufacturer=mfr, name=old_name).update(name=new_name)


def reverse_rename_scanner_models(apps, schema_editor):
    CTManufacturer = apps.get_model("uploads", "CTManufacturer")
    CTScannerModel = apps.get_model("uploads", "CTScannerModel")

    for mfr_name, old_name, new_name in _RENAMES:
        try:
            mfr = CTManufacturer.objects.get(name=mfr_name)
        except CTManufacturer.DoesNotExist:
            continue
        CTScannerModel.objects.filter(manufacturer=mfr, name=new_name).update(name=old_name)


class Migration(migrations.Migration):

    dependencies = [
        ("uploads", "0011_ct_protocol_models"),
    ]

    operations = [
        migrations.RunPython(
            rename_scanner_models,
            reverse_code=reverse_rename_scanner_models,
        ),
    ]
