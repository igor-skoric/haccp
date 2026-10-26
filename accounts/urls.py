from django.urls import path

from . import views

urlpatterns = [
    path('prijava/', views.HaccpLoginView.as_view(), name='login'),
    path('odjava/', views.HaccpLogoutView.as_view(), name='logout'),
    path('registracija/', views.register, name='register'),
    path('view-as/<int:user_id>/', views.view_as_start, name='view_as_start'),
    path('view-as/stop/', views.view_as_stop, name='view_as_stop'),
]
