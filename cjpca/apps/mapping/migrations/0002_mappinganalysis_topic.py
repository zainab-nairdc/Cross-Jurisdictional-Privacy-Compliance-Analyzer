from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mapping', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='mappinganalysis',
            name='topic',
            field=models.CharField(max_length=255, blank=True),
        ),
    ]
