from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0025_email_to_ticket_schedule_and_run_log'),
    ]

    operations = [
        migrations.CreateModel(
            name='InboundEmailRoutingRule',
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
                ('sender_email', models.EmailField(max_length=254)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'assignee',
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='inbound_email_routing_rules',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'smtp_configuration',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='inbound_routing_rules',
                        to='tickets.smtpconfiguration',
                    ),
                ),
            ],
            options={
                'ordering': ['smtp_configuration__name', 'sender_email'],
            },
        ),
        migrations.AddConstraint(
            model_name='inboundemailroutingrule',
            constraint=models.UniqueConstraint(
                fields=('smtp_configuration', 'sender_email'),
                name='unique_sender_route_per_smtp',
            ),
        ),
    ]
