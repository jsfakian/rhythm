from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0013_ctprotocol_examination_group_clinical_comments'),
    ]

    operations = [
        migrations.CreateModel(
            name='CTExamination',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('anatomical_region', models.CharField(blank=True, max_length=256)),
                ('clinical_indication', models.CharField(blank=True, max_length=512)),
                ('patient_weight', models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ('water_equivalent_diameter', models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ('patient_age', models.PositiveIntegerField(blank=True, null=True)),
                ('number_of_phases', models.PositiveIntegerField(default=1)),
                ('ctdi_vol_per_phase', models.JSONField(blank=True, default=list)),
                ('dlp_per_phase', models.JSONField(blank=True, default=list)),
                ('image_quality', models.CharField(
                    blank=True,
                    choices=[('EXCELLENT', 'Excellent'), ('GOOD', 'Good'), ('MODERATE', 'Moderate'), ('POOR', 'Poor')],
                    max_length=16,
                )),
                ('created_by', models.CharField(blank=True, max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('protocol', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='examinations',
                    to='uploads.ctprotocol',
                )),
                ('scanner', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='examinations',
                    to='uploads.ctscannerprofile',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='ctexamination',
            index=models.Index(fields=['scanner'], name='uploads_cte_scanner_idx'),
        ),
        migrations.AddIndex(
            model_name='ctexamination',
            index=models.Index(fields=['created_at'], name='uploads_cte_created_idx'),
        ),
    ]
