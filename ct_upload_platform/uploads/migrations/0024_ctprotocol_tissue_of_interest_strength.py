from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0023_rename_rhythm_pseudo_id_to_repository_study_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='ctprotocol',
            name='tissue_of_interest',
            field=models.CharField(blank=True, max_length=256),
        ),
        migrations.AddField(
            model_name='ctprotocol',
            name='strength',
            field=models.CharField(blank=True, max_length=128),
        ),
    ]
