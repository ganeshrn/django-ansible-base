# Generated by Django 4.2.8 on 2024-04-21 16:39

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dab_authentication', '0009_alter_authenticatoruser_provider_and_more'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='authenticatoruser',
            unique_together={('provider', 'uid')},
        ),
    ]
