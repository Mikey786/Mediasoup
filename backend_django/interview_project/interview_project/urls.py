from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/interview/', include('interview_app.urls')), # For potential HTTP endpoints
]