import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0014_ctexamination'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClinicalIndicationRow',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('anatomical_region', models.CharField(max_length=256)),
                ('clinical_indication', models.TextField()),
                ('iv_contrast', models.CharField(max_length=256)),
                ('comments', models.TextField(blank=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ['sort_order', 'anatomical_region'],
            },
        ),
        migrations.AddIndex(
            model_name='clinicalindicationrow',
            index=models.Index(fields=['anatomical_region'], name='uploads_cli_anatomi_a795e7_idx'),
        ),
        migrations.AddIndex(
            model_name='clinicalindicationrow',
            index=models.Index(fields=['is_active'], name='uploads_cli_is_acti_e0b21c_idx'),
        ),
    ]
