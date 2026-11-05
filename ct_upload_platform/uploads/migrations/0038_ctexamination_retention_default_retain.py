from django.db import migrations, models


class Migration(migrations.Migration):
    """New examinations default to RETAIN (was: blank = not declared).

    Schema-only: Django applies field defaults in Python, so this changes no
    database rows. Existing rows were set to RETAIN separately on 2026-11-05
    (audited as RETENTION_SET by admin-bulk-default).
    """

    dependencies = [
        ('uploads', '0037_ctexamination_retention_consent'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ctexamination',
            name='retention_consent',
            field=models.CharField(
                blank=True,
                choices=[('RETAIN', 'Retain after project'), ('DELETE', 'Delete at project end')],
                db_index=True,
                default='RETAIN',
                help_text='Keep after the project ends (RETAIN, the default) or delete at project end (DELETE).',
                max_length=8,
            ),
        ),
    ]
