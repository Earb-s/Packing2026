from django.urls import path

from .views import index, manual_psd_window, theory

urlpatterns = [
    path("", index, name="index"),
    path("theory/", theory, name="theory"),
    path("manual-psd/", manual_psd_window, name="manual_psd_window"),
]
