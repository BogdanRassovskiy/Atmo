from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bot", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="registration",
            name="seat_id",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="registration",
            name="slot_id",
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
    ]
