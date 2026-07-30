from django.urls import path

from . import views

# Mounted under /accounts/ in the project urls.py.
# PoC: no roles, no MFA, no user management — just a GET-friendly logout.
# login / password_change / password_reset come from django.contrib.auth.urls.
urlpatterns = [
    path('logout/', views.GetAwareLogoutView.as_view(), name='logout'),
    # Admin operations dashboard (login-required). Its view existed but was
    # never routed, so every template linking to it 500'd on NoReverseMatch.
    path('monitoring/', views.SystemMonitoringView.as_view(), name='system-monitoring'),
]
