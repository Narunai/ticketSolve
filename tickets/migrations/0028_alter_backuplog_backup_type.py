from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0027_in_app_notification'),
    ]

    operations = [
        migrations.AlterField(
            model_name='backuplog',
            name='backup_type',
            field=models.CharField(
                choices=[
                    ('FULL', 'Full Backup'),
                    ('INCREMENTAL', '2-Hour Incremental'),
                    ('SYSTEM', 'System Data (No Tickets)'),
                ],
                default='FULL',
                max_length=20,
            ),
        ),
    ]
