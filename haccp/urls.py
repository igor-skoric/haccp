from django.contrib import admin
from django.urls import include, path

admin.site.site_header = 'HACCP'
admin.site.site_title = 'HACCP'
admin.site.index_title = 'Administracija'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('nalog/', include('accounts.urls')),
    path('', include('organizations.urls')),
    path('', include('ops.urls')),
    path('', include('documents.urls')),
    path('', include('core.urls')),
]
