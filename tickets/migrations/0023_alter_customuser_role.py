from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0022_backuplog_backup_type_alter_backuplog_status_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customuser',
            name='role',
            field=models.CharField(
                choices=[
                    ('SYSTEM_ADMIN', 'System Administrator'),
                    ('SYSTEM_SUB_ADMIN', 'System Sub-Administrator'),
                    ('CLIENT_ADMIN', 'Client Administrator'),
                    ('CLIENT_STAFF', 'Client Staff'),
                    ('CLIENT_USER', 'Client User'),
                ],
                default='CLIENT_USER',
                max_length=20,
            ),
        ),
    ]
