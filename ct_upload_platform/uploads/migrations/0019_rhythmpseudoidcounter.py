from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0018_userprofile'),
    ]

    operations = [
        migrations.CreateModel(
            name='RhythmPseudoIDCounter',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('prefix', models.CharField(
                    max_length=64,
                    unique=True,
                    help_text='RHY-SITE-INDICATION-CONTRAST-GROUP prefix',
                )),
                ('last_seq', models.PositiveIntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'indexes': [
                    models.Index(fields=['prefix'], name='uploads_rhyc_prefix_idx'),
                ],
            },
        ),
    ]
