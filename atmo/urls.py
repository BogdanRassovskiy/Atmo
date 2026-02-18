from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from bot.views import telegram_webhook
from bot.views import *

urlpatterns = [
    path("admin/", admin.site.urls),
    path("webhook/atmo/", telegram_webhook),
    path("api/weblink/", weblink),
    path("api/bookings", bookings_collection),
    path("api/bookings/", bookings_collection),
    path("api/bookings/profile", bookings_profile),
    path("api/bookings/profile/", bookings_profile),
    path("api/bookings/seats-all", bookings_seats_all),
    path("api/bookings/seats-all/", bookings_seats_all),
    path("api/bookings/seats/<str:slot_id>", bookings_seats),
    path("api/bookings/seats/<str:slot_id>/", bookings_seats),
    path("api/bookings/<str:booking_id>", booking_detail),
    path("api/bookings/<str:booking_id>/", booking_detail),
    path("", atmafest_app),
    path("fest-admin", atmafest_app),
    path("fest-admin/", atmafest_app),
]

# Раздача статики в режиме разработки
if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()