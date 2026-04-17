# -*- coding: utf-8 -*-
#
from django.urls import path

from . import views

urlpatterns = [
    path('login/', views.OAuth2AuthRequestView.as_view(), name='login'),
    path('callback/', views.OAuth2AuthCallbackView.as_view(), name='login-callback'),
    path('callback/dlt/sso/handler', views.OAuth2AuthCallbackView.as_view(), name='login-callback-sso'),
    path('callback/dlt/account', views.OAuth2AuthCallbackAccountView.as_view(), name='login-callback-account'),
    path('logout/', views.OAuth2EndSessionView.as_view(), name='logout')
]
