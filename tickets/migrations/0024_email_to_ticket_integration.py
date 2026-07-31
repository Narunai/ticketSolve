from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0023_alter_customuser_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='smtpconfiguration',
            name='email_to_ticket_assignee',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='email_to_ticket_assignee_configurations',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='email_to_ticket_company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='email_to_ticket_smtp_configurations',
                to='tickets.company',
            ),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='email_to_ticket_creator',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='email_to_ticket_creator_configurations',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='feature_scope',
            field=models.CharField(
                choices=[
                    ('OUTBOUND_EMAIL', 'Send system email'),
                    ('EMAIL_TO_TICKET', 'Email to Ticket import'),
                    ('BOTH', 'Send email and Email to Ticket'),
                ],
                default='OUTBOUND_EMAIL',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='fetch_days_back',
            field=models.PositiveSmallIntegerField(default=7),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='filter_issue_only',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='incoming_folder',
            field=models.CharField(default='INBOX', max_length=255),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='incoming_host',
            field=models.CharField(
                blank=True,
                default='',
                help_text='IMAP host, for example imap.gmail.com',
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='incoming_port',
            field=models.PositiveIntegerField(default=993),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='issue_keywords',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Optional comma-separated subject keywords',
            ),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='last_inbound_check_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='last_inbound_error',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='mark_processed_as_read',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='smtpconfiguration',
            name='max_emails_per_fetch',
            field=models.PositiveSmallIntegerField(default=30),
        ),
        migrations.CreateModel(
            name='InboundEmailReceipt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message_id', models.CharField(max_length=512)),
                ('sender_name', models.CharField(blank=True, default='', max_length=255)),
                ('sender_email', models.EmailField(blank=True, default='', max_length=254)),
                ('subject', models.CharField(blank=True, default='', max_length=255)),
                ('status', models.CharField(
                    choices=[
                        ('IMPORTED', 'Imported'),
                        ('SKIPPED', 'Skipped'),
                        ('FAILED', 'Failed'),
                    ],
                    max_length=20,
                )),
                ('details', models.TextField(blank=True, default='')),
                ('processed_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('smtp_configuration', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='inbound_email_receipts',
                    to='tickets.smtpconfiguration',
                )),
                ('ticket', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='inbound_email_receipts',
                    to='tickets.ticket',
                )),
            ],
            options={
                'ordering': ['-processed_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='inboundemailreceipt',
            constraint=models.UniqueConstraint(
                fields=('smtp_configuration', 'message_id'),
                name='unique_inbound_message_per_smtp_config',
            ),
        ),
    ]
