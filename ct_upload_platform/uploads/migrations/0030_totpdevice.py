import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('uploads', '0029_rename_uploads_rhyc_prefix_idx_uploads_rhy_prefix_a82960_idx_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='TOTPDevice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('secret', models.CharField(max_length=64)),
                ('confirmed', models.BooleanField(default=False)),
                ('confirmed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='totp_device', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
