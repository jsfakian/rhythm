from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0022_ctexamination_study_set_file'),
    ]

    operations = [
        migrations.RenameField(
            model_name='ctexamination',
            old_name='rhythm_pseudo_id',
            new_name='repository_study_id',
        ),
    ]
