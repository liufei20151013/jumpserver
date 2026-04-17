from django.conf import settings
from django.contrib import auth
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _
from django.views import View
from rest_framework.views import APIView

from authentication.decorators import pre_save_next_to_session, redirect_to_pre_save_next_after_auth
from authentication.mixins import authenticate
from authentication.utils import build_absolute_uri
from authentication.views.mixins import FlashMessageMixin
from common.utils import get_logger
from dlt.models import DltAccount

from users.permissions import permissions
from rest_framework.response import Response
from rest_framework import status

logger = get_logger(__file__)


class OAuth2AuthRequestView(View):

    @pre_save_next_to_session()
    def get(self, request):
        log_prompt = "Process OAuth2 GET requests: {}"
        logger.debug(log_prompt.format('Start'))

        request_params = request.GET.dict()
        request_params.pop('next', None)
        query = urlencode(request_params)
        redirect_uri = build_absolute_uri(
            request, path=reverse(settings.AUTH_OAUTH2_AUTH_LOGIN_CALLBACK_URL_NAME)
        )
        redirect_uri = f"{redirect_uri}?{query}"

        query_dict = {
            'client_id': settings.AUTH_OAUTH2_CLIENT_ID,
            'response_type': 'code',
            # 'scope': settings.AUTH_OAUTH2_SCOPE,
            'redirect_uri': redirect_uri
        }

        if '?' in settings.AUTH_OAUTH2_PROVIDER_AUTHORIZATION_ENDPOINT:
            separator = '&'
        else:
            separator = '?'
        redirect_url = '{url}{separator}{query}'.format(
            url=settings.AUTH_OAUTH2_PROVIDER_AUTHORIZATION_ENDPOINT,
            separator=separator,
            query=urlencode(query_dict)
        )
        logger.debug(log_prompt.format('Redirect login url'))
        logger.debug('authorize_url: {}'.format(redirect_url))
        return HttpResponseRedirect(redirect_url)


class OAuth2AuthCallbackView(View, FlashMessageMixin):
    http_method_names = ['get', ]

    @redirect_to_pre_save_next_after_auth
    def get(self, request):
        """ Processes GET requests. """
        log_prompt = "Process GET requests [OAuth2AuthCallbackView]: {}"
        logger.debug(log_prompt.format('Start'))
        callback_params = request.GET

        if 'code' in callback_params:
            logger.debug(log_prompt.format('Process authenticate'))
            user = authenticate(code=callback_params['code'], request=request)

            if user:
                logger.debug(log_prompt.format('Login: {}'.format(user)))
                auth.login(self.request, user)
                logger.debug(log_prompt.format('Redirect'))
                return HttpResponseRedirect(settings.AUTH_OAUTH2_AUTHENTICATION_REDIRECT_URI)
            else:
                if getattr(request, 'error_message', ''):
                    response = self.get_failed_response('/', title=_('OAuth2 Error'), msg=request.error_message)
                    return response

        logger.debug(log_prompt.format('Redirect'))
        redirect_url = settings.AUTH_OAUTH2_PROVIDER_END_SESSION_ENDPOINT or '/'
        return HttpResponseRedirect(redirect_url)


class OAuth2AuthCallbackAccountView(APIView):
    permission_classes = [permissions.AllowAny]

    """
        先把登录通上的用户组织ID与堡垒机组织备注先绑定，再去登录通上添加用户到应用内，触发 /dlt/account 同步用户数据到堡垒机
    """
    def post(self, request):
        logger.debug('save dlt accounts start')
        logger.debug(request)
        logger.debug('dlt datas: {}'.format(request.data))
        request_data = request.data
        if request_data:
            action_type = request_data.get('actionType', '')
            if (action_type == 'Add' or action_type == 'Modify' or action_type == 'ParticularChanges' or
                    action_type == 'Disable' or action_type == 'Enable'):
                for account in request_data['accountList']:
                    logger.debug('dlt account: {}, action_type: {}'.format(account, action_type))
                    cn = account.get('cn', '')
                    uid = account.get('uid', '')
                    org = account.get('org', '')
                    org_full_name = account.get('orgFullName', '')
                    email = account.get('email', '')
                    mobile = account.get('mobile', '')
                    account_status = account.get('status', '')

                    defaults = {
                        'cn': cn,
                        'uid': uid,
                        'org': org,
                        'org_full_name': org_full_name,
                        'email': email,
                        'mobile': mobile,
                        'status': account_status,
                        'action_type': action_type
                    }

                    account, created = DltAccount.objects.get_or_create(
                        uid=uid,
                        defaults=defaults
                    )

                    if not created:
                        account.cn = cn
                        account.uid = uid
                        account.org = org
                        account.org_full_name = org_full_name
                        account.email = email
                        account.mobile = mobile
                        account.status = account_status
                        account.action_type = action_type
                        account.date_updated = timezone.now()
                        account.save(update_fields=["cn", "uid", "org", "org_full_name", "email", "mobile",
                                                    "status", "action_type", "date_updated"])

            elif action_type == 'Delete' or action_type == 'ReclaimAccount':
                # 统一身份认证那边删除用户，堡垒机不删除只禁用，需要保留审计数据
                for account in request_data['accountList']:
                    logger.debug('dlt account: {}, action_type: {}'.format(account, action_type))
                    uid = account.get('uid', '')
                    account_list = DltAccount.objects.filter(uid=uid)
                    if account_list.exists():
                        account_list.update(status='0', action_type=action_type, date_updated=timezone.now())
            logger.debug('save dlt accounts end')
        return Response({"msg": "success"}, status=status.HTTP_200_OK)


class OAuth2EndSessionView(View):
    http_method_names = ['get', 'post', ]

    def get(self, request):
        """ Processes GET requests. """
        log_prompt = "Process GET requests [OAuth2EndSessionView]: {}"
        logger.debug(log_prompt.format('Start'))
        return self.post(request)

    def post(self, request):
        """ Processes POST requests. """
        log_prompt = "Process POST requests [OAuth2EndSessionView]: {}"
        logger.debug(log_prompt.format('Start'))

        logout_url = settings.LOGOUT_REDIRECT_URL or '/'

        # Log out the current user.
        if request.user.is_authenticated:
            logger.debug(log_prompt.format('Log out the current user: {}'.format(request.user)))
            auth.logout(request)

            logout_url = settings.AUTH_OAUTH2_PROVIDER_END_SESSION_ENDPOINT
            if settings.AUTH_OAUTH2_LOGOUT_COMPLETELY and logout_url:
                logger.debug(log_prompt.format('Log out OAUTH2 platform user session synchronously'))
                return HttpResponseRedirect(logout_url)

        logger.debug(log_prompt.format('Redirect'))
        return HttpResponseRedirect(logout_url)
