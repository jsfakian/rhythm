from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('uploads', '0026_add_is_catalogue'),
    ]

    operations = [
        migrations.CreateModel(
            name='Institution',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=256, unique=True)),
                ('site_code', models.CharField(max_length=16, unique=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
    ]
