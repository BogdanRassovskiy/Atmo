from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0003_telegramuser_participation_days'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramuser',
            name='registration_number',
            field=models.BigIntegerField(blank=True, db_index=True, null=True, unique=True),
        ),
    ]
