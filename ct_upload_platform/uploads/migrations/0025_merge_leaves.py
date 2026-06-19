from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0021_update_scanner_options'),
        ('uploads', '0024_alter_ctexamination_rhythm_pseudo_id'),
        ('uploads', '0024_ctprotocol_tissue_of_interest_strength'),
    ]
    # 0021 → separate chain from 0020
    # 0024_alter → 0023_contrast_and_more → 0022
    # 0024_ctprotocol → 0023_rename (no-op) → 0023_contrast_and_more → 0022

    operations = [
    ]
