from django.urls import path

from . import views

urlpatterns = [
    path('danas/', views.today, name='today'),
    path('temperature/', views.temperatures, name='temperatures'),
    path('temperature/korektivna/<int:pk>/', views.temperature_corrective, name='temperature_corrective'),
    path('alerti/', views.alerts, name='alerts'),
    path('zadaci/', views.tasks_page, name='tasks'),
    path('danas/zadatak/<int:pk>/', views.task_done, name='task_done'),
    path('higijena/', views.hygiene_list, name='hygiene_list'),
    path('higijena/danas/', views.hygiene_open_today, name='hygiene_today'),
    path('higijena/<int:pk>/', views.hygiene_detail, name='hygiene_detail'),
    path('higijena/<int:pk>/stavka/<int:line_id>/', views.hygiene_toggle, name='hygiene_toggle'),
    path('prijem/', views.receiving_list, name='receiving_list'),
    path('prijem/otvoreni/', views.receiving_open, name='receiving_open'),
    path('prijem/novi/', views.receiving_create, name='receiving_create'),
    path('prijem/<int:pk>/', views.receiving_detail, name='receiving_detail'),
]
