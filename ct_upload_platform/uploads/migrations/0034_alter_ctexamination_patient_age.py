import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0033_add_data_classification'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ctexamination',
            name='patient_age',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Patient age in years; fractional values (e.g. 0.3) are allowed for infants.',
                max_digits=5,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(150),
                ],
            ),
        ),
    ]
