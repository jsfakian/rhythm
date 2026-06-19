from django.db import migrations, models


class Migration(migrations.Migration):
    """
    The DB column was created as 'repository_study_id' by an earlier migration.
    The Django model field is 'rhythm_pseudo_id'. This migration reconciles the
    two by recording db_column='repository_study_id' in Django's state only —
    no SQL is needed because the column already has the correct name in the DB.
    """

    dependencies = [
        ('uploads', '0023_ctexamination_contrast_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='ctexamination',
                    name='rhythm_pseudo_id',
                    field=models.CharField(
                        blank=True,
                        db_column='repository_study_id',
                        db_index=True,
                        help_text='Auto-generated RHYTHM repository pseudo-ID',
                        max_length=64,
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
