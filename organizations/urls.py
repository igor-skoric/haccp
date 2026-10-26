from django.urls import path

from . import views

urlpatterns = [
    path('klijenti/', views.platform_clients, name='platform_clients'),
    path('klijenti/<int:pk>/', views.platform_client_detail, name='platform_client_detail'),
    path('podesavanja/', views.settings_page, name='settings'),
    path('podesavanja/konfiguracija/', views.settings_config, name='settings_config'),
    path('podesavanja/zadaci/', views.task_settings, name='task_settings'),
    path('podesavanja/<slug:section>/', views.settings_section, name='settings_section'),
]
