from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0002_registration_slot_seat'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramuser',
            name='participation_days',
            field=models.PositiveSmallIntegerField(choices=[(1, '1_day'), (2, '2_days')], default=2),
        ),
    ]
