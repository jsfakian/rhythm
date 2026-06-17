from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0017_ma_modulation_input_spec'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('institution', models.CharField(max_length=256)),
                ('department', models.CharField(blank=True, max_length=256)),
                ('professional_role', models.CharField(
                    choices=[
                        ('radiologist', 'Radiologist'),
                        ('medical_physicist', 'Medical Physicist'),
                        ('radiographer', 'Radiographer / CT Technologist'),
                        ('pacs_it', 'PACS / IT Administrator'),
                        ('research_coordinator', 'Research Coordinator'),
                        ('principal_investigator', 'Principal Investigator'),
                        ('dpo', 'Data Protection Officer'),
                        ('other', 'Other: please specify'),
                    ],
                    max_length=64,
                )),
                ('professional_role_other', models.CharField(blank=True, max_length=256)),
                ('terms_accepted', models.BooleanField(default=False)),
                ('terms_accepted_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='profile',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'indexes': [
                    models.Index(fields=['institution'], name='uploads_userprofile_inst_idx'),
                ],
            },
        ),
    ]
