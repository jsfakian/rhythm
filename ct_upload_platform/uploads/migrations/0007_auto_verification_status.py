# Generated migration for automatic chunk verification during upload

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0006_uploadchunk_chunk_crc32'),
    ]

    operations = [
        migrations.AddField(
            model_name='uploadchunk',
            name='verification_status',
            field=models.CharField(
                choices=[
                    ('PENDING', 'Pending verification'),
                    ('VERIFIED', 'Verified successfully'),
                    ('CORRUPTED', 'Verification failed - corrupted'),
                    ('NEEDS_REUPLOAD', 'Needs reupload'),
                ],
                default='PENDING',
                help_text='Current verification status of the chunk',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='uploadchunk',
            name='verification_error',
            field=models.TextField(
                blank=True,
                null=True,
                help_text='Error details if verification failed',
            ),
        ),
        migrations.AddField(
            model_name='uploadchunk',
            name='verification_timestamp',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='Timestamp when verification was performed',
            ),
        ),
        migrations.AlterField(
            model_name='uploadchunk',
            name='verified',
            field=models.BooleanField(
                default=False,
                help_text='Whether chunk integrity has been verified (deprecated - use verification_status)',
            ),
        ),
        migrations.AddIndex(
            model_name='uploadchunk',
            index=models.Index(fields=['verification_status'], name='uploads_upl_verifi_idx'),
        ),
    ]
