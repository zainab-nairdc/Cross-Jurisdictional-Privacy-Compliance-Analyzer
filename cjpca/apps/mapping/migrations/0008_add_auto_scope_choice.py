from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mapping', '0007_gap_assigned_at_gap_assigned_by_gap_assigned_to_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mappinganalysis',
            name='scope_mode',
            field=models.CharField(
                choices=[
                    ('auto',     'Auto-route from policy'),
                    ('full',     'All topics'),
                    ('topics',   'Selected topics'),
                    ('specific', 'Specific articles'),
                ],
                default='full',
                max_length=20,
            ),
        ),
    ]
