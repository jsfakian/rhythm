# Generated migration for adding CRC32 field to UploadChunk

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0002_add_chunked_upload_support'),
    ]

    operations = [
        migrations.AddField(
            model_name='uploadchunk',
            name='chunk_crc32',
            field=models.CharField(
                blank=True,
                help_text='CRC32 checksum of chunk for quick corruption detection',
                max_length=8,
                null=True
            ),
        ),
    ]
