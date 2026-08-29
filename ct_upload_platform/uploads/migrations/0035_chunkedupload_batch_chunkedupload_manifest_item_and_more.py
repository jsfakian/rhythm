import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0034_alter_ctexamination_patient_age'),
    ]

    operations = [
        migrations.AddField(
            model_name='chunkedupload',
            name='batch',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Batch identifier grouping this upload with sibling items from the same automated-upload manifest submission, if any.',
                max_length=128,
            ),
        ),
        migrations.AddField(
            model_name='chunkedupload',
            name='manifest_item',
            field=models.JSONField(
                blank=True,
                help_text="The corresponding item entry from a v2 (server-assigned batch) manifest, carried through to the UploadJob created on completion so process_upload_job() knows this archive's metadata without needing an embedded manifest.json.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='ctexamination',
            name='upload_job',
            field=models.ForeignKey(
                blank=True,
                help_text="Async GDPR-validation/Orthanc-ingestion job processing this examination's study_set_file, if any. Null for examinations created before this pipeline existed or with no study set file.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='examinations',
                to='uploads.uploadjob',
            ),
        ),
        migrations.AddIndex(
            model_name='chunkedupload',
            index=models.Index(fields=['batch'], name='uploads_chu_batch_a8badd_idx'),
        ),
    ]
