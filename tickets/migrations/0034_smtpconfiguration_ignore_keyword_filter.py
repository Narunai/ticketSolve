from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0033_emaillog_ticket'),
    ]

    operations = [
        migrations.AlterField(
            model_name='smtpconfiguration',
            name='issue_keywords',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Optional comma-separated subject keywords',
                max_length=4000,
            ),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='ignore_keyword_filter_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='ignore_keywords',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Optional comma-separated subject keywords that must never create tickets',
                max_length=4000,
            ),
        ),
    ]
