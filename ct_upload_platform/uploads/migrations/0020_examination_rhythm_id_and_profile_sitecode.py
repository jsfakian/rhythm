from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0019_rhythmpseudoidcounter'),
    ]

    operations = [
        # CTExamination: add rhythm_pseudo_id, contrast, protocol_type, examination_group
        migrations.AddField(
            model_name='ctexamination',
            name='rhythm_pseudo_id',
            field=models.CharField(blank=True, db_index=True, default='',
                                   help_text='Auto-generated RHYTHM repository pseudo-ID', max_length=64),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='ctexamination',
            name='contrast',
            field=models.CharField(blank=True, default='', max_length=128),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='ctexamination',
            name='protocol_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('PEDIATRIC_HEAD', 'Pediatric Head'),
                    ('PEDIATRIC_BODY', 'Pediatric Body'),
                    ('YOUNG_ADULT', 'Young Adult'),
                ],
                default='',
                max_length=32,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='ctexamination',
            name='examination_group',
            field=models.CharField(blank=True, default='', max_length=128),
            preserve_default=False,
        ),
        # UserProfile: add site_code
        migrations.AddField(
            model_name='userprofile',
            name='site_code',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
    ]
