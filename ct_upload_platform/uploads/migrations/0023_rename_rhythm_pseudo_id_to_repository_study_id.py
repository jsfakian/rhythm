from django.db import migrations


class Migration(migrations.Migration):
    # No-op: the rename approach was superseded by 0024_alter_ctexamination_rhythm_pseudo_id
    # which uses SeparateDatabaseAndState to keep the Django field name as rhythm_pseudo_id
    # while the DB column is repository_study_id. Dependency is corrected so this runs
    # after the field is actually added.

    dependencies = [
        ('uploads', '0023_ctexamination_contrast_and_more'),
    ]

    operations = []
