from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0030_totpdevice'),
    ]

    operations = [
        migrations.AddField(
            model_name='ctexamination',
            name='site_code',
            field=models.CharField(blank=True, default='', help_text='Institution site code of the creator, for institution-wide sharing', max_length=16),
        ),
        migrations.AddField(
            model_name='ctprotocol',
            name='site_code',
            field=models.CharField(blank=True, default='', help_text='Institution site code of the creator, for institution-wide sharing', max_length=16),
        ),
        migrations.AddField(
            model_name='ctscannerprofile',
            name='site_code',
            field=models.CharField(blank=True, default='', help_text='Institution site code of the creator, for institution-wide sharing', max_length=16),
        ),
        migrations.AddField(
            model_name='studymapping',
            name='site_code',
            field=models.CharField(blank=True, default='', help_text='Institution site code of the uploading job, for institution-wide sharing', max_length=16),
        ),
        migrations.AddField(
            model_name='uploadjob',
            name='site_code',
            field=models.CharField(blank=True, default='', help_text='Institution site code of the uploader, for institution-wide sharing', max_length=16),
        ),
        migrations.AddIndex(
            model_name='ctexamination',
            index=models.Index(fields=['site_code'], name='uploads_cte_sitecod_idx'),
        ),
        migrations.AddIndex(
            model_name='ctprotocol',
            index=models.Index(fields=['site_code'], name='uploads_ctp_sitecod_idx'),
        ),
        migrations.AddIndex(
            model_name='ctscannerprofile',
            index=models.Index(fields=['site_code'], name='uploads_cts_site_co_c05936_idx'),
        ),
        migrations.AddIndex(
            model_name='studymapping',
            index=models.Index(fields=['site_code'], name='uploads_stu_site_co_af290f_idx'),
        ),
        migrations.AddIndex(
            model_name='uploadjob',
            index=models.Index(fields=['site_code'], name='uploads_upl_site_co_1a899e_idx'),
        ),
    ]
