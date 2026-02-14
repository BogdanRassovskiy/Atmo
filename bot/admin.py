from django.contrib import admin
from .models import TelegramUser, Registration


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ['telegram_id', 'username', 'first_name', 'last_name', 'phone', 'is_vip', 'is_blocked', 'created_at']
    list_filter = ['is_vip', 'is_blocked', 'language', 'created_at']
    search_fields = ['telegram_id', 'username', 'first_name', 'last_name', 'phone']
    readonly_fields = ['telegram_id', 'created_at', 'updated_at']
    fieldsets = (
        ('Основная информация', {
            'fields': ('telegram_id', 'username', 'first_name', 'last_name', 'phone')
        }),
        ('Настройки', {
            'fields': ('language', 'step', 'is_vip', 'is_blocked')
        }),
        ('Дополнительно', {
            'fields': ('meta', 'created_at', 'updated_at')
        }),
    )


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ['booking_id', 'user', 'game', 'master', 'place_number', 'day', 'line', 'time_start', 'time_end', 'is_paid', 'created_at']
    list_filter = ['is_paid', 'game', 'master', 'day', 'line', 'created_at']
    search_fields = ['booking_id', 'user__username', 'user__first_name', 'user__phone', 'game', 'master']
    readonly_fields = ['created_at']
    autocomplete_fields = ['user']
    fieldsets = (
        ('Бронирование', {
            'fields': ('booking_id', 'user', 'is_paid')
        }),
        ('Игра', {
            'fields': ('game', 'master', 'place_number')
        }),
        ('Расписание', {
            'fields': ('day', 'line', 'time_start', 'time_end')
        }),
        ('Дополнительно', {
            'fields': ('created_at',)
        }),
    )
