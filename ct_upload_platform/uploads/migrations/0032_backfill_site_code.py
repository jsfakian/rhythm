from django.db import migrations


def _site_code_for_username(User, UserProfile, username):
    if not username:
        return ''
    profile = UserProfile.objects.filter(user__username=username).first()
    return profile.site_code if profile else ''


def backfill_site_codes(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    UserProfile = apps.get_model('uploads', 'UserProfile')
    UploadJob = apps.get_model('uploads', 'UploadJob')
    StudyMapping = apps.get_model('uploads', 'StudyMapping')
    CTScannerProfile = apps.get_model('uploads', 'CTScannerProfile')
    CTProtocol = apps.get_model('uploads', 'CTProtocol')
    CTExamination = apps.get_model('uploads', 'CTExamination')

    for job in UploadJob.objects.all():
        code = _site_code_for_username(User, UserProfile, job.uploader_id)
        if code:
            job.site_code = code
            job.save(update_fields=['site_code'])

    for mapping in StudyMapping.objects.select_related('upload_job').all():
        if mapping.upload_job_id and mapping.upload_job.site_code:
            mapping.site_code = mapping.upload_job.site_code
            mapping.save(update_fields=['site_code'])

    for model in (CTScannerProfile, CTProtocol, CTExamination):
        for obj in model.objects.all():
            code = _site_code_for_username(User, UserProfile, obj.created_by)
            if code:
                obj.site_code = code
                obj.save(update_fields=['site_code'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0031_add_site_code_fields'),
    ]

    operations = [
        migrations.RunPython(backfill_site_codes, noop_reverse),
    ]
