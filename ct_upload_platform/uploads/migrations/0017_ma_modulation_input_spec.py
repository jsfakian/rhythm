import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0016_ctmanufacturer_field_options'),
    ]

    operations = [
        migrations.CreateModel(
            name='MaModulationInputSpec',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('ma_modulation_value', models.CharField(max_length=256, unique=True)),
                ('input_labels', models.JSONField(default=list)),
                ('sort_order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'ordering': ['sort_order', 'ma_modulation_value'],
            },
        ),
        migrations.RemoveField(
            model_name='ctprotocol',
            name='exposure_metric',
        ),
        migrations.RemoveField(
            model_name='ctprotocol',
            name='mas_value',
        ),
        migrations.AddField(
            model_name='ctprotocol',
            name='mas_inputs',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
