from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0036_alter_patient_age_at_first_acquisition'),
    ]

    operations = [
        migrations.AddField(
            model_name='ctexamination',
            name='retention_consent',
            field=models.CharField(
                blank=True,
                choices=[('RETAIN', 'Retain after project'), ('DELETE', 'Delete at project end')],
                db_index=True,
                default='',
                help_text='Patient authorised retention after the project ends (RETAIN), '
                          'did not (DELETE), or not declared yet (blank = delete).',
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name='ctexamination',
            name='retention_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='ctexamination',
            name='retention_updated_by',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AlterField(
            model_name='auditlog',
            name='event_type',
            field=models.CharField(
                choices=[
                    ('SUBMIT', 'Submit'),
                    ('VALIDATE_OK', 'Validation OK'),
                    ('VALIDATE_FAIL', 'Validation Failed'),
                    ('IMAGE_PUSH_OK', 'Image Push OK'),
                    ('IMAGE_PUSH_FAIL', 'Image Push Failed'),
                    ('COMPLETE', 'Job Complete'),
                    ('FAILED', 'Job Failed'),
                    ('PARTIAL', 'Job Partial Success'),
                    ('RETENTION_SET', 'Retention Consent Changed'),
                    ('STUDY_PURGED', 'Study Deleted (retention)'),
                ],
                help_text='Type of event',
                max_length=64,
            ),
        ),
    ]
