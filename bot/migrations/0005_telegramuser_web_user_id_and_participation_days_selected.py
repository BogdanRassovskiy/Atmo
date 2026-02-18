from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0004_telegramuser_registration_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramuser',
            name='web_user_id',
            field=models.UUIDField(blank=True, db_index=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='telegramuser',
            name='participation_days_selected',
            field=models.BooleanField(default=False),
        ),
    ]
