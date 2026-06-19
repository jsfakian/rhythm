from django.db import migrations, models


class Migration(migrations.Migration):
    # The is_catalogue column was added to the DB outside the migration chain.
    # SeparateDatabaseAndState syncs Django's model state without issuing any SQL.

    dependencies = [
        ('uploads', '0025_merge_leaves'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='ctmanufacturer',
                    name='is_catalogue',
                    field=models.BooleanField(default=False),
                ),
                migrations.AddField(
                    model_name='ctscannermodel',
                    name='is_catalogue',
                    field=models.BooleanField(default=False),
                ),
            ],
            database_operations=[],
        ),
    ]
