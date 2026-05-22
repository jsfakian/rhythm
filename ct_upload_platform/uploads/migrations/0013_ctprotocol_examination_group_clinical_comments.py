from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("uploads", "0012_rename_scanner_models_to_excel_names"),
    ]

    operations = [
        migrations.AddField(
            model_name="ctprotocol",
            name="examination_group",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="ctprotocol",
            name="clinical_comments",
            field=models.CharField(blank=True, max_length=512),
        ),
    ]
