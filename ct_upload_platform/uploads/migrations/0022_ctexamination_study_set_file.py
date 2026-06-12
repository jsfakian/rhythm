from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0021_update_scanner_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='ctexamination',
            name='study_set_file',
            field=models.FileField(
                blank=True,
                help_text='Optional compressed study set archive (zip, tar, tar.gz, etc.)',
                null=True,
                upload_to='examination_study_sets/',
            ),
        ),
    ]
