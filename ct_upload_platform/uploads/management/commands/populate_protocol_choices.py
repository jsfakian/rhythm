from django.core.management.base import BaseCommand

from uploads.models import (
    CTManufacturer,
    CTScannerModel,
    ProtocolChoiceCategory,
    ProtocolChoiceOption,
)


class Command(BaseCommand):
    help = "Populate CT Protocol choice options from the initial spreadsheet data"

    def handle(self, *args, **kwargs) -> None:
        self.populate_manufacturers()
        self.populate_scanner_models()
        self.populate_choice_categories()
        self.stdout.write(self.style.SUCCESS("Done."))

    def populate_manufacturers(self) -> None:
        manufacturers = [
            "Canon Medical",
            "GE HealthCare",
            "Philips",
            "Siemens Healthineers",
            "United Imaging",
            "Neusoft Medical",
            "Fujifilm / Hitachi",
            "Samsung NeuroLogica",
            "MinFound Medical",
            "Other",
        ]
        created_count = 0
        for sort_order, name in enumerate(manufacturers):
            _, created = CTManufacturer.objects.get_or_create(
                name=name,
                defaults={"sort_order": sort_order},
            )
            if created:
                created_count += 1
        self.stdout.write(
            f"  Manufacturers: {created_count} created, "
            f"{len(manufacturers) - created_count} already existed."
        )

    def populate_scanner_models(self) -> None:
        # Each entry: (manufacturer_name, list_of_model_names)
        scanner_data: list[tuple[str, list[str]]] = [
            (
                "Canon Medical",
                [
                    "Canon Aquilion ONE / GENESIS Edition",
                    "Canon Aquilion ONE / ViSION Edition",
                    "Canon Aquilion ONE / PRISM Edition",
                    "Canon Aquilion Prime",
                    "Canon Aquilion Prime SP",
                    "Canon Aquilion Lightning",
                    "Canon Aquilion Serve SP",
                    "Canon Aquilion Precision",
                    "Canon Aquilion Exceed LB",
                    "Canon Aquilion LB",
                ],
            ),
            (
                "GE HealthCare",
                [
                    "GE Revolution Apex Platform",
                    "GE Revolution CT",
                    "GE Revolution Maxima",
                    "GE Revolution Ascend",
                    "GE Revolution Frontier",
                    "GE Revolution EVO",
                    "GE Revolution ACT",
                    "GE Discovery CT750 HD",
                    "GE Optima CT660",
                    "GE LightSpeed VCT",
                    "GE BrightSpeed",
                ],
            ),
            (
                "Siemens Healthineers",
                [
                    "Siemens NAEOTOM Alpha",
                    "Siemens SOMATOM Force",
                    "Siemens SOMATOM Drive",
                    "Siemens SOMATOM Definition Flash",
                    "Siemens SOMATOM Definition Edge",
                    "Siemens SOMATOM Definition AS",
                    "Siemens SOMATOM X.cite",
                    "Siemens SOMATOM X.ceed",
                    "Siemens SOMATOM X.serve",
                    "Siemens SOMATOM go.Top",
                    "Siemens SOMATOM go.All",
                    "Siemens SOMATOM go.Up",
                    "Siemens SOMATOM go.Now",
                    "Siemens SOMATOM Perspective",
                ],
            ),
            (
                "Philips",
                [
                    "Philips Spectral CT 7500",
                    "Philips IQon Spectral CT",
                    "Philips Incisive CT",
                    "Philips CT 5300",
                    "Philips Ingenuity CT",
                    "Philips Brilliance iCT",
                    "Philips Brilliance 64",
                    "Philips Big Bore RT",
                ],
            ),
            (
                "United Imaging",
                [
                    "United Imaging uCT ATLAS",
                    "United Imaging uCT 960+",
                    "United Imaging uCT 780",
                    "United Imaging uCT 760",
                    "United Imaging uCT 550",
                    "United Imaging uCT 530",
                    "United Imaging uCT 528",
                    "United Imaging uCT 520",
                    "United Imaging uCT 510",
                ],
            ),
            (
                "Neusoft Medical",
                [
                    "Neusoft NeuViz Epoch+ CT",
                    "Neusoft NeuViz Epoch CT",
                    "Neusoft NeuViz Glory+ CT",
                    "Neusoft NeuViz Glory CT",
                    "Neusoft NeuViz Prime CT",
                    "Neusoft NeuViz 128 CT",
                    "Neusoft NeuViz ACE 128 CT",
                    "Neusoft NeuViz ACE 64e CT",
                    "Neusoft NeuViz 64 In CT",
                    "Neusoft NeuViz ACE UP CT",
                    "Neusoft NeuViz 16 Essence CT",
                    "Neusoft NeuViz 16 Classic CT",
                    "Neusoft NeuViz ACE SP CT",
                ],
            ),
            (
                "Fujifilm / Hitachi",
                [
                    "Fujifilm / Hitachi SCENARIA View",
                    "Hitachi SCENARIA",
                    "Hitachi Supria",
                    "Hitachi Supria Grande",
                ],
            ),
            (
                "Samsung NeuroLogica",
                [
                    "Samsung NeuroLogica OmniTom Elite",
                    "Samsung NeuroLogica BodyTom Elite",
                ],
            ),
            (
                "MinFound Medical",
                [
                    "MinFound ScintCare CT 16",
                    "MinFound ScintCare CT 64",
                    "MinFound ScintCare CT 128",
                ],
            ),
            (
                "Other",
                [
                    "Other: Please Specify",
                ],
            ),
        ]

        created_count = 0
        total_count = 0
        for manufacturer_name, model_names in scanner_data:
            manufacturer = CTManufacturer.objects.get(name=manufacturer_name)
            for sort_order, model_name in enumerate(model_names):
                _, created = CTScannerModel.objects.get_or_create(
                    manufacturer=manufacturer,
                    name=model_name,
                    defaults={"sort_order": sort_order},
                )
                total_count += 1
                if created:
                    created_count += 1
        self.stdout.write(
            f"  Scanner models: {created_count} created, "
            f"{total_count - created_count} already existed."
        )

    def populate_choice_categories(self) -> None:
        # Describes each category and its options.
        # Each option is either a plain string (value == display_text) or a
        # dict with explicit "value" and "display" keys for coded entries.
        # applicable_protocol_types defaults to [] when not specified.
        categories: list[dict] = [
            {
                "key": "detector_rows",
                "label": "Detector Rows / Coverage",
                "options": [
                    "16 rows",
                    "32 rows",
                    "40 mm coverage",
                    "64 rows",
                    "80 rows",
                    "128 rows",
                    "160 rows",
                    "256 rows",
                    "320 rows / 16 cm coverage",
                    "Dual source",
                    "Photon-counting CT",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "year_of_installation",
                "label": "Year of Installation",
                "options": (
                    ["Unknown"]
                    + [str(y) for y in range(2000, 2027)]
                    + ["Other: Please Specify"]
                ),
            },
            {
                "key": "protocol_name",
                "label": "Protocol Name",
                "options": [
                    "Brain non-contrast",
                    "Brain CTA",
                    "Brain perfusion",
                    "Sinuses",
                    "Temporal bone",
                    "Maxillofacial",
                    "Neck soft tissue",
                    "Cervical spine",
                    "Chest low dose",
                    "Chest routine",
                    "HRCT chest",
                    "CTPA",
                    "Cardiac calcium score",
                    "Coronary CTA",
                    "Abdomen routine",
                    "Abdomen-pelvis portal venous",
                    "Renal colic low dose",
                    "Liver multiphase",
                    "Pancreas multiphase",
                    "CT urography",
                    "Aorta CTA",
                    "Whole-body trauma",
                    "Extremity CT",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "clinical_indication_pediatric_head",
                "label": "Clinical Indication – Pediatric Head",
                "applicable_protocol_types": ["PEDIATRIC_HEAD"],
                "options": [
                    "Head trauma",
                    "Suspected intracranial haemorrhage",
                    "Hydrocephalus / VP shunt check",
                    "Seizure",
                    "Headache",
                    "Suspected stroke",
                    "Brain tumour / follow-up",
                    "Craniosynostosis",
                    "Sinusitis",
                    "Temporal bone / mastoiditis",
                    "Facial trauma",
                    "Cervical spine trauma",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "clinical_indication_pediatric_body",
                "label": "Clinical Indication – Pediatric Body",
                "applicable_protocol_types": ["PEDIATRIC_BODY"],
                "options": [
                    "Appendicitis",
                    "Abdominal pain",
                    "Trauma",
                    "Infection / abscess",
                    "Oncology staging",
                    "Oncology follow-up",
                    "Chest infection",
                    "HRCT / interstitial lung disease",
                    "Pulmonary embolism",
                    "Renal colic / urinary tract",
                    "Congenital anomaly",
                    "Vascular / CTA",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "clinical_indication_adult",
                "label": "Clinical Indication – Adult / Young Adult",
                "applicable_protocol_types": ["YOUNG_ADULT"],
                "options": [
                    "Stroke / intracranial haemorrhage",
                    "Head trauma",
                    "Pulmonary embolism",
                    "HRCT chest / ILD",
                    "Lung cancer staging",
                    "Oncology staging",
                    "Oncology follow-up",
                    "Acute abdomen",
                    "Appendicitis",
                    "Renal colic",
                    "Aortic dissection / CTA",
                    "Polytrauma",
                    "Liver lesion",
                    "Pancreas protocol",
                    "CT colonography",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "anatomical_region",
                "label": "Anatomical Region",
                "options": [
                    "Brain",
                    "Head",
                    "Head and neck",
                    "Sinuses",
                    "Temporal bone",
                    "Maxillofacial",
                    "Neck",
                    "Cervical spine",
                    "Chest",
                    "HRCT chest",
                    "Chest and upper abdomen",
                    "Abdomen",
                    "Pelvis",
                    "Abdomen and pelvis",
                    "Chest-abdomen-pelvis",
                    "Extremity",
                    "Cardiac",
                    "Vascular",
                    "Whole body / trauma",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "scan_type",
                "label": "Scan Type",
                "options": [
                    "Sequential / axial",
                    "Helical / spiral",
                    "Dynamic / perfusion",
                    "CTA",
                    "Multiphase",
                    "Low-dose",
                    "Ultra-low-dose",
                    "HRCT",
                    "Dual-energy / spectral",
                    "Cardiac gated",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "contrast",
                "label": "Contrast",
                "options": [
                    "No contrast",
                    "IV contrast only",
                    "Oral contrast only",
                    "IV + oral contrast",
                    "Rectal contrast",
                    "Arterial phase",
                    "Portal venous phase",
                    "Delayed phase",
                    "CT urography",
                    "CTA",
                    "CTPA",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "number_of_phases",
                "label": "Number of Phases",
                "options": [
                    "1",
                    "2",
                    "3",
                    "4",
                    "5",
                    ">5 / dynamic",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "auto_kvp_selection",
                "label": "Automatic kVp Selection",
                "options": [
                    "Off",
                    "Canon SUREkV",
                    "GE kV Assist",
                    "Philips DoseRight / automatic kV if available",
                    "Siemens CARE kV",
                    "Siemens CARE kV Semi",
                    "Tin filter / Sn mode",
                    "Not Available",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "kvp",
                "label": "kVp",
                "options": [
                    "70",
                    "80",
                    "90",
                    "100",
                    "110",
                    "120",
                    "130",
                    "135",
                    "140",
                    "150",
                    "Sn100",
                    "Sn110",
                    "Sn140",
                    "Sn150",
                    "Dual energy / spectral",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "auto_ma_modulation",
                "label": "Automatic mA Modulation",
                "options": [
                    "Off",
                    "Canon SUREExposure 3D",
                    "Canon Volume EC",
                    "GE Auto mA",
                    "GE Smart mA",
                    "GE Auto mA + Smart mA",
                    "GE Organ Dose Modulation",
                    "Philips DoseRight",
                    "Philips Z-DOM",
                    "Philips D-DOM",
                    "Philips 3D-DOM",
                    "Philips DoseRight 3D-DOM",
                    "Siemens CARE Dose4D",
                    "Siemens X-CARE / organ dose modulation",
                    "Siemens CARE Dose4D + X-CARE",
                    "Not Available",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "exposure_metric",
                "label": "Exposure Metric / mAs Reference",
                "options": [
                    "Fixed mAs",
                    "Effective mAs",
                    "Quality reference mAs",
                    "Reference mAs",
                    "Noise index",
                    "Standard deviation",
                    "DoseRight index",
                    "Dose modulation index",
                    "min mA / max mA",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "pitch",
                "label": "Pitch",
                "options": [
                    "N/A sequential",
                    "0.35-0.5",
                    "0.5-0.8",
                    "0.8-1.2",
                    "1.2-1.5",
                    ">1.5",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "rotation_time",
                "label": "Rotation Time (s)",
                "options": [
                    "0.25",
                    "0.28",
                    "0.33",
                    "0.35",
                    "0.4",
                    "0.5",
                    "0.6",
                    "0.75",
                    "1",
                    "1.5",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "slice_thickness",
                "label": "Slice Thickness 1st Recon (mm)",
                "options": [
                    "0.5",
                    "0.625",
                    "0.75",
                    "1",
                    "1.25",
                    "2",
                    "2.5",
                    "3",
                    "5",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "scan_fov",
                "label": "Scan Field of View",
                "options": [
                    "Small head",
                    "Head",
                    "Large head",
                    "Pediatric body",
                    "Small body",
                    "Medium body",
                    "Large body",
                    "Cardiac",
                    "Extremity",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "kernel_class",
                "label": "Generic Kernel Class",
                "options": [
                    "Very soft",
                    "Soft tissue",
                    "Standard",
                    "Detail",
                    "Lung",
                    "Bone",
                    "Edge / high-resolution",
                    "Vascular",
                    "Cardiac",
                    "Iterative kernel",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "reconstruction_algorithm",
                "label": "Reconstruction Algorithm Generic",
                "options": [
                    "Filtered back projection",
                    "Hybrid iterative reconstruction",
                    "Model-based iterative reconstruction",
                    "Deep-learning reconstruction",
                    "Spectral / monoenergetic reconstruction",
                    "Metal artefact reduction",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "protocol_intent",
                "label": "Protocol Intent / Optimization Goal",
                "options": [
                    "Routine diagnostic",
                    "Low-dose",
                    "Ultra-low-dose",
                    "High-resolution",
                    "Vascular CTA",
                    "Oncology staging",
                    "Follow-up surveillance",
                    "Trauma",
                    "Pediatric optimized",
                    "Metal artefact reduction",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "dose_metadata",
                "label": "Dose-Relevant Metadata Availability",
                "options": [
                    "CTDIvol recorded",
                    "DLP recorded",
                    "SSDE possible",
                    "Patient weight recorded",
                    "Patient height recorded",
                    "Water-equivalent diameter available",
                    "Localizer available",
                    "RDSR available",
                    "Other: Please Specify",
                ],
            },
            {
                "key": "age_group_pediatric_head",
                "label": "Age Group – Pediatric Head",
                "applicable_protocol_types": ["PEDIATRIC_HEAD"],
                "options": [
                    {"value": "lt_3m", "display": "< 3 months"},
                    {"value": "3m_1y", "display": "3 months – 1 year"},
                    {"value": "1y_6y", "display": "1 year – 6 years"},
                    {"value": "gt_6y", "display": "> 6 years"},
                ],
            },
            {
                "key": "age_group_pediatric_body",
                "label": "Weight Group – Pediatric Body",
                "applicable_protocol_types": ["PEDIATRIC_BODY"],
                "options": [
                    {"value": "lt_5kg", "display": "< 5 kg"},
                    {"value": "5_15kg", "display": "5 kg – 15 kg"},
                    {"value": "15_30kg", "display": "15 kg – 30 kg"},
                    {"value": "30_50kg", "display": "30 kg – 50 kg"},
                    {"value": "50_80kg", "display": "50 kg – 80 kg"},
                ],
            },
            {
                "key": "age_group_young_adult",
                "label": "Age/Weight Group – Young Adult",
                "applicable_protocol_types": ["YOUNG_ADULT"],
                "options": [
                    {"value": "gt_80kg", "display": "> 80 kg"},
                ],
            },
        ]

        cat_created = 0
        opt_created = 0
        opt_total = 0

        for cat_def in categories:
            protocol_types = cat_def.get("applicable_protocol_types", [])
            category, created = ProtocolChoiceCategory.objects.get_or_create(
                key=cat_def["key"],
                defaults={
                    "label": cat_def["label"],
                },
            )
            if created:
                cat_created += 1

            for sort_order, opt_def in enumerate(cat_def["options"]):
                if isinstance(opt_def, dict):
                    value = opt_def["value"]
                    display = opt_def["display"]
                else:
                    value = opt_def
                    display = opt_def

                _, opt_newly_created = ProtocolChoiceOption.objects.get_or_create(
                    category=category,
                    value=value,
                    defaults={
                        "display": display,
                        "sort_order": sort_order,
                        "is_active": True,
                        "applicable_protocol_types": protocol_types,
                    },
                )
                opt_total += 1
                if opt_newly_created:
                    opt_created += 1

        self.stdout.write(
            f"  Categories: {cat_created} created, "
            f"{len(categories) - cat_created} already existed."
        )
        self.stdout.write(
            f"  Options: {opt_created} created, "
            f"{opt_total - opt_created} already existed."
        )
