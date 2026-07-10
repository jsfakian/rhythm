from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0027_add_institution_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='email_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='email_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='verification_email_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
