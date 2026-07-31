from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def create_default_email_schedule(apps, schema_editor):
    schedule_model = apps.get_model('tickets', 'EmailToTicketSchedule')
    schedule_model.objects.get_or_create(
        singleton_key=True,
        defaults={
            'is_active': True,
            'interval_minutes': 10,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0024_email_to_ticket_integration'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailToTicketSchedule',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'singleton_key',
                    models.BooleanField(default=True, editable=False, unique=True),
                ),
                ('is_active', models.BooleanField(default=True)),
                (
                    'interval_minutes',
                    models.PositiveSmallIntegerField(
                        choices=[
                            (10, '10 minutes'),
                            (20, '20 minutes'),
                            (30, '30 minutes (half an hour)'),
                            (60, '1 hour'),
                        ],
                        default=10,
                    ),
                ),
                ('last_run_at', models.DateTimeField(blank=True, null=True)),
                (
                    'last_scheduled_run_at',
                    models.DateTimeField(blank=True, null=True),
                ),
                ('last_status', models.CharField(blank=True, default='', max_length=20)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'updated_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='updated_email_to_ticket_schedules',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name='EmailToTicketRunLog',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'trigger',
                    models.CharField(
                        choices=[('TIMER', 'Timer'), ('MANUAL', 'Manual')],
                        max_length=10,
                    ),
                ),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('RUNNING', 'Running'),
                            ('SUCCESS', 'Success'),
                            ('PARTIAL', 'Partial success'),
                            ('SKIPPED', 'Skipped'),
                            ('FAILED', 'Failed'),
                        ],
                        default='RUNNING',
                        max_length=20,
                    ),
                ),
                ('mailbox_count', models.PositiveIntegerField(default=0)),
                ('found_count', models.PositiveIntegerField(default=0)),
                ('imported_count', models.PositiveIntegerField(default=0)),
                ('skipped_count', models.PositiveIntegerField(default=0)),
                ('duplicate_count', models.PositiveIntegerField(default=0)),
                ('failed_count', models.PositiveIntegerField(default=0)),
                ('duration_ms', models.PositiveIntegerField(default=0)),
                ('details', models.TextField(blank=True, default='')),
                (
                    'started_at',
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                (
                    'actor',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='email_to_ticket_run_logs',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'schedule',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='run_logs',
                        to='tickets.emailtoticketschedule',
                    ),
                ),
            ],
            options={
                'ordering': ['-started_at'],
                'indexes': [
                    models.Index(
                        fields=['-started_at'],
                        name='email_run_started_idx',
                    ),
                    models.Index(
                        fields=['status'],
                        name='email_run_status_idx',
                    ),
                ],
            },
        ),
        migrations.RunPython(
            create_default_email_schedule,
            migrations.RunPython.noop,
        ),
    ]
