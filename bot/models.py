from django.db import models


class TelegramUser(models.Model):
    telegram_id = models.BigIntegerField(unique=True, db_index=True)
    username = models.CharField(max_length=255, null=True, blank=True)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255, null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    language = models.CharField(max_length=10, default="ru")
    step = models.CharField(
        max_length=50,
        default="start"
    )
    is_vip = models.BooleanField(default=False)
    is_blocked = models.BooleanField(default=False)
    # === Гибкие данные ===
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self):
        return f"{self.first_name} ({self.telegram_id})"
    
class Registration(models.Model):
    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name="registrations"
    )

    booking_id = models.CharField(max_length=255, unique=True)

    game = models.CharField(max_length=255)
    master = models.CharField(max_length=255)

    place_number = models.IntegerField()

    day = models.IntegerField()
    line = models.IntegerField()

    time_start = models.TimeField()
    time_end = models.TimeField()

    is_paid = models.BooleanField(default=False)

    created_at = models.DateTimeField()

    class Meta:
        verbose_name = "Регистрация"
        verbose_name_plural = "Регистрации"

    def __str__(self):
        return f"{self.booking_id} - {self.user.first_name}"