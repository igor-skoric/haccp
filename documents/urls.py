from django.urls import path

from . import views

urlpatterns = [
    path('plan/', views.library, {'kind': 'HP'}, name='plan'),
    path('procedure/', views.library, {'kind': 'PR'}, name='procedures'),
    path('uputstva/', views.library, {'kind': 'UP'}, name='instructions'),
    path('obrasci/', views.library, {'kind': 'OB'}, name='forms'),
    path('inspekcija/', views.library, {'kind': 'IN'}, name='inspection'),
    path('dokument/<slug:code>/', views.detail, name='document'),
]
