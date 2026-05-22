import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0010_alter_studymapping_orthanc_study_id'),
    ]

    operations = [
        # 1. CTManufacturer
        migrations.CreateModel(
            name='CTManufacturer',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('name', models.CharField(max_length=128, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'ordering': ['sort_order', 'name'],
            },
        ),
        # 2. CTScannerModel
        migrations.CreateModel(
            name='CTScannerModel',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('manufacturer', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='scanner_models',
                    to='uploads.ctmanufacturer',
                )),
                ('name', models.CharField(max_length=256)),
                ('notes', models.CharField(blank=True, max_length=512)),
                ('is_active', models.BooleanField(default=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'ordering': ['manufacturer__name', 'sort_order', 'name'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='ctscannermodel',
            unique_together={('manufacturer', 'name')},
        ),
        # 3. ProtocolChoiceCategory
        migrations.CreateModel(
            name='ProtocolChoiceCategory',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('key', models.CharField(max_length=64, unique=True)),
                ('label', models.CharField(max_length=128)),
                ('description', models.TextField(blank=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'verbose_name_plural': 'Protocol choice categories',
                'ordering': ['sort_order', 'label'],
            },
        ),
        # 4. ProtocolChoiceOption
        migrations.CreateModel(
            name='ProtocolChoiceOption',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('category', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='options',
                    to='uploads.protocolchoicecategory',
                )),
                ('value', models.CharField(max_length=256)),
                ('display', models.CharField(max_length=512)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
                ('applicable_protocol_types', models.JSONField(blank=True, default=list)),
            ],
            options={
                'ordering': ['sort_order', 'display'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='protocolchoiceoption',
            unique_together={('category', 'value')},
        ),
        # 5. CTScannerProfile
        migrations.CreateModel(
            name='CTScannerProfile',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('manufacturer', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='scanner_profiles',
                    to='uploads.ctmanufacturer',
                )),
                ('scanner_model', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='scanner_profiles',
                    to='uploads.ctscannermodel',
                )),
                ('detector_rows', models.CharField(blank=True, max_length=256)),
                ('year_of_installation', models.CharField(blank=True, max_length=32)),
                ('local_protocol_note', models.TextField(blank=True)),
                ('created_by', models.CharField(blank=True, max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        # 6. CTProtocol
        migrations.CreateModel(
            name='CTProtocol',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('scanner', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='protocols',
                    to='uploads.ctscannerprofile',
                )),
                ('protocol_type', models.CharField(
                    choices=[
                        ('PEDIATRIC_HEAD', 'Pediatric Head CT Protocols'),
                        ('PEDIATRIC_BODY', 'Pediatric Body CT Protocols'),
                        ('YOUNG_ADULT', 'Young Adult CT Protocols'),
                    ],
                    max_length=16,
                )),
                ('age_group', models.CharField(max_length=64)),
                ('clinical_indication', models.CharField(blank=True, max_length=512)),
                ('protocol_name', models.CharField(blank=True, max_length=512)),
                ('anatomical_region', models.CharField(blank=True, max_length=256)),
                ('scan_type', models.CharField(blank=True, max_length=256)),
                ('contrast', models.CharField(blank=True, max_length=256)),
                ('number_of_phases', models.CharField(blank=True, max_length=64)),
                ('auto_kvp_selection', models.CharField(blank=True, max_length=256)),
                ('kvp', models.CharField(blank=True, max_length=64)),
                ('auto_ma_modulation', models.CharField(blank=True, max_length=256)),
                ('exposure_metric', models.CharField(blank=True, max_length=256)),
                ('mas_value', models.CharField(blank=True, max_length=128)),
                ('pitch', models.CharField(blank=True, max_length=64)),
                ('rotation_time', models.CharField(blank=True, max_length=32)),
                ('slice_thickness', models.CharField(blank=True, max_length=32)),
                ('scan_fov', models.CharField(blank=True, max_length=128)),
                ('kernel_class', models.CharField(blank=True, max_length=128)),
                ('reconstruction_algorithm', models.CharField(blank=True, max_length=256)),
                ('protocol_intent', models.CharField(blank=True, max_length=256)),
                ('dose_metadata', models.JSONField(blank=True, default=list)),
                ('notes', models.TextField(blank=True)),
                ('created_by', models.CharField(blank=True, max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='ctprotocol',
            index=models.Index(fields=['protocol_type'], name='uploads_ctp_protoco_idx'),
        ),
        migrations.AddIndex(
            model_name='ctprotocol',
            index=models.Index(fields=['scanner'], name='uploads_ctp_scanner_idx'),
        ),
    ]
