from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0005_telegramuser_web_user_id_and_participation_days_selected'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramuser',
            name='paid_participation_days',
            field=models.PositiveSmallIntegerField(
                choices=[(0, 'not_paid'), (1, '1_day_paid'), (2, '2_days_paid')],
                default=0,
            ),
        ),
    ]
