import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0015_clinicalindicationrow'),
    ]

    operations = [
        migrations.CreateModel(
            name='CTManufacturerFieldOption',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('field_key', models.CharField(choices=[('auto_kvp_selection', 'Automatic kVp Selection'), ('auto_ma_modulation', 'Automatic mA Modulation')], max_length=64)),
                ('value', models.CharField(max_length=256)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('manufacturer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='field_options', to='uploads.ctmanufacturer')),
            ],
            options={
                'ordering': ['manufacturer__sort_order', 'field_key', 'sort_order'],
                'unique_together': {('manufacturer', 'field_key', 'value')},
            },
        ),
    ]
