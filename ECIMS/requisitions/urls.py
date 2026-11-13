from django.urls import path
from . import views

app_name = "requisitions"

urlpatterns = [
    path("inbound/",  views.inbound,  name="inbound"),
    path("outbound/", views.outbound, name="outbound"),
    path("damage/",   views.damage,   name="damage"),
    path("cancel/<str:kind>/<int:pk>/", views.cancel_apply, name="cancel"),
    path("review/<str:kind>/<int:pk>/", views.review_apply, name="review"),
]