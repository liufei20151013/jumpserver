# -*- coding: utf-8 -*-
#
import os

import ldap

from ..const import CONFIG, PROJECT_DIR, BASE_DIR

# OTP settings
OTP_ISSUER_NAME = CONFIG.OTP_ISSUER_NAME
OTP_VALID_WINDOW = CONFIG.OTP_VALID_WINDOW

# Auth LDAP settings
AUTH_LDAP = CONFIG.AUTH_LDAP
AUTH_LDAP_SERVER_URI = CONFIG.AUTH_LDAP_SERVER_URI
AUTH_LDAP_BIND_DN = CONFIG.AUTH_LDAP_BIND_DN
AUTH_LDAP_BIND_PASSWORD = CONFIG.AUTH_LDAP_BIND_PASSWORD
AUTH_LDAP_SEARCH_OU = CONFIG.AUTH_LDAP_SEARCH_OU
AUTH_LDAP_SEARCH_FILTER = CONFIG.AUTH_LDAP_SEARCH_FILTER
AUTH_LDAP_START_TLS = CONFIG.AUTH_LDAP_START_TLS
AUTH_LDAP_USER_ATTR_MAP = CONFIG.AUTH_LDAP_USER_ATTR_MAP
AUTH_LDAP_USER_QUERY_FIELD = 'username'
AUTH_LDAP_GLOBAL_OPTIONS = {
    ldap.OPT_X_TLS_REQUIRE_CERT: ldap.OPT_X_TLS_NEVER,
    ldap.OPT_REFERRALS: CONFIG.AUTH_LDAP_OPTIONS_OPT_REFERRALS
}
LDAP_CACERT_FILE = os.path.join(PROJECT_DIR, "data", "certs", "ldap_ca.pem")
if os.path.isfile(LDAP_CACERT_FILE):
    AUTH_LDAP_GLOBAL_OPTIONS[ldap.OPT_X_TLS_CACERTFILE] = LDAP_CACERT_FILE
LDAP_CERT_FILE = os.path.join(PROJECT_DIR, "data", "certs", "ldap_cert.pem")
if os.path.isfile(LDAP_CERT_FILE):
    AUTH_LDAP_GLOBAL_OPTIONS[ldap.OPT_X_TLS_CERTFILE] = LDAP_CERT_FILE
LDAP_KEY_FILE = os.path.join(PROJECT_DIR, "data", "certs", "ldap_cert.key")
if os.path.isfile(LDAP_KEY_FILE):
    AUTH_LDAP_GLOBAL_OPTIONS[ldap.OPT_X_TLS_KEYFILE] = LDAP_KEY_FILE
# AUTH_LDAP_GROUP_SEARCH_OU = CONFIG.AUTH_LDAP_GROUP_SEARCH_OU
# AUTH_LDAP_GROUP_SEARCH_FILTER = CONFIG.AUTH_LDAP_GROUP_SEARCH_FILTER
# AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
#    AUTH_LDAP_GROUP_SEARCH_OU, ldap.SCOPE_SUBTREE, AUTH_LDAP_GROUP_SEARCH_FILTER
# )
AUTH_LDAP_CONNECTION_OPTIONS = {
    ldap.OPT_TIMEOUT: CONFIG.AUTH_LDAP_CONNECT_TIMEOUT,
    ldap.OPT_NETWORK_TIMEOUT: CONFIG.AUTH_LDAP_CONNECT_TIMEOUT
}
AUTH_LDAP_CACHE_TIMEOUT = 1
AUTH_LDAP_ALWAYS_UPDATE_USER = True

AUTH_LDAP_SEARCH_PAGED_SIZE = CONFIG.AUTH_LDAP_SEARCH_PAGED_SIZE
AUTH_LDAP_SYNC_IS_PERIODIC = CONFIG.AUTH_LDAP_SYNC_IS_PERIODIC
AUTH_LDAP_SYNC_INTERVAL = CONFIG.AUTH_LDAP_SYNC_INTERVAL
AUTH_LDAP_SYNC_CRONTAB = CONFIG.AUTH_LDAP_SYNC_CRONTAB
AUTH_LDAP_SYNC_ORG_IDS = CONFIG.AUTH_LDAP_SYNC_ORG_IDS
AUTH_LDAP_SYNC_RECEIVERS = CONFIG.AUTH_LDAP_SYNC_RECEIVERS
AUTH_LDAP_USER_LOGIN_ONLY_IN_USERS = CONFIG.AUTH_LDAP_USER_LOGIN_ONLY_IN_USERS

# ==============================================================================
# 认证 OpenID 配置参数
# 参考: https://django-oidc-rp.readthedocs.io/en/stable/settings.html
# ==============================================================================
AUTH_OPENID = CONFIG.AUTH_OPENID
BASE_SITE_URL = CONFIG.BASE_SITE_URL
AUTH_OPENID_CLIENT_ID = CONFIG.AUTH_OPENID_CLIENT_ID
AUTH_OPENID_CLIENT_SECRET = CONFIG.AUTH_OPENID_CLIENT_SECRET
AUTH_OPENID_CLIENT_AUTH_METHOD = CONFIG.AUTH_OPENID_CLIENT_AUTH_METHOD
AUTH_OPENID_PROVIDER_ENDPOINT = CONFIG.AUTH_OPENID_PROVIDER_ENDPOINT
AUTH_OPENID_PROVIDER_AUTHORIZATION_ENDPOINT = CONFIG.AUTH_OPENID_PROVIDER_AUTHORIZATION_ENDPOINT
AUTH_OPENID_PROVIDER_TOKEN_ENDPOINT = CONFIG.AUTH_OPENID_PROVIDER_TOKEN_ENDPOINT
AUTH_OPENID_PROVIDER_JWKS_ENDPOINT = CONFIG.AUTH_OPENID_PROVIDER_JWKS_ENDPOINT
AUTH_OPENID_PROVIDER_USERINFO_ENDPOINT = CONFIG.AUTH_OPENID_PROVIDER_USERINFO_ENDPOINT
AUTH_OPENID_PROVIDER_END_SESSION_ENDPOINT = CONFIG.AUTH_OPENID_PROVIDER_END_SESSION_ENDPOINT
AUTH_OPENID_PROVIDER_SIGNATURE_ALG = CONFIG.AUTH_OPENID_PROVIDER_SIGNATURE_ALG
AUTH_OPENID_PROVIDER_SIGNATURE_KEY = CONFIG.AUTH_OPENID_PROVIDER_SIGNATURE_KEY
AUTH_OPENID_SCOPES = CONFIG.AUTH_OPENID_SCOPES
AUTH_OPENID_ID_TOKEN_MAX_AGE = CONFIG.AUTH_OPENID_ID_TOKEN_MAX_AGE
AUTH_OPENID_ID_TOKEN_INCLUDE_CLAIMS = CONFIG.AUTH_OPENID_ID_TOKEN_INCLUDE_CLAIMS
AUTH_OPENID_USE_STATE = CONFIG.AUTH_OPENID_USE_STATE
AUTH_OPENID_USE_NONCE = CONFIG.AUTH_OPENID_USE_NONCE

AUTH_OPENID_SHARE_SESSION = CONFIG.AUTH_OPENID_SHARE_SESSION
AUTH_OPENID_IGNORE_SSL_VERIFICATION = CONFIG.AUTH_OPENID_IGNORE_SSL_VERIFICATION
AUTH_OPENID_ALWAYS_UPDATE_USER = CONFIG.AUTH_OPENID_ALWAYS_UPDATE_USER
AUTH_OPENID_PKCE = CONFIG.AUTH_OPENID_PKCE
AUTH_OPENID_CODE_CHALLENGE_METHOD = CONFIG.AUTH_OPENID_CODE_CHALLENGE_METHOD
AUTH_OPENID_USER_ATTR_MAP = CONFIG.AUTH_OPENID_USER_ATTR_MAP
AUTH_OPENID_AUTH_LOGIN_URL_NAME = 'authentication:openid:login'
AUTH_OPENID_AUTH_LOGIN_CALLBACK_URL_NAME = 'authentication:openid:login-callback'
AUTH_OPENID_AUTH_LOGOUT_URL_NAME = 'authentication:openid:logout'
# Other default
AUTH_OPENID_STATE_LENGTH = 32
AUTH_OPENID_NONCE_LENGTH = 32
AUTH_OPENID_AUTHENTICATION_REDIRECT_URI = '/'
AUTH_OPENID_AUTHENTICATION_FAILURE_REDIRECT_URI = '/'
AUTH_OPENID_PROVIDER_END_SESSION_REDIRECT_URI_PARAMETER = 'post_logout_redirect_uri'
AUTH_OPENID_PROVIDER_END_SESSION_ID_TOKEN_PARAMETER = 'id_token_hint'
# ==============================================================================

# Radius Auth
AUTH_RADIUS = CONFIG.AUTH_RADIUS
AUTH_RADIUS_BACKEND = 'authentication.backends.radius.RadiusBackend'
RADIUS_SERVER = CONFIG.RADIUS_SERVER
RADIUS_PORT = CONFIG.RADIUS_PORT
RADIUS_SECRET = CONFIG.RADIUS_SECRET
# https://github.com/robgolding/django-radius/blob/develop/radiusauth/backends/radius.py#L15-L52
RADIUS_ATTRIBUTES = CONFIG.RADIUS_ATTRIBUTES

# CAS Auth
AUTH_CAS = CONFIG.AUTH_CAS
CAS_SERVER_URL = CONFIG.CAS_SERVER_URL
CAS_VERIFY_SSL_CERTIFICATE = False
CAS_LOGIN_URL_NAME = "authentication:cas:cas-login"
CAS_LOGOUT_URL_NAME = "authentication:cas:cas-logout"
CAS_LOGIN_MSG = None
CAS_LOGGED_MSG = None
CAS_IGNORE_REFERER = True
CAS_LOGOUT_COMPLETELY = CONFIG.CAS_LOGOUT_COMPLETELY
CAS_VERSION = CONFIG.CAS_VERSION
CAS_ROOT_PROXIED_AS = CONFIG.CAS_ROOT_PROXIED_AS
CAS_CHECK_NEXT = lambda _next_page: True
CAS_USERNAME_ATTRIBUTE = CONFIG.CAS_USERNAME_ATTRIBUTE
CAS_APPLY_ATTRIBUTES_TO_USER = CONFIG.CAS_APPLY_ATTRIBUTES_TO_USER
CAS_RENAME_ATTRIBUTES = CONFIG.CAS_RENAME_ATTRIBUTES
CAS_CREATE_USER = CONFIG.CAS_CREATE_USER

# SSO auth
AUTH_SSO = CONFIG.AUTH_SSO
AUTH_SSO_AUTHKEY_TTL = CONFIG.AUTH_SSO_AUTHKEY_TTL

# WECOM auth
AUTH_WECOM = CONFIG.AUTH_WECOM
WECOM_CORPID = CONFIG.WECOM_CORPID
WECOM_AGENTID = CONFIG.WECOM_AGENTID
WECOM_SECRET = CONFIG.WECOM_SECRET

# DingDing auth
AUTH_DINGTALK = CONFIG.AUTH_DINGTALK
DINGTALK_AGENTID = CONFIG.DINGTALK_AGENTID
DINGTALK_APPKEY = CONFIG.DINGTALK_APPKEY
DINGTALK_APPSECRET = CONFIG.DINGTALK_APPSECRET

# FeiShu auth
AUTH_FEISHU = CONFIG.AUTH_FEISHU
FEISHU_APP_ID = CONFIG.FEISHU_APP_ID
FEISHU_APP_SECRET = CONFIG.FEISHU_APP_SECRET
FEISHU_VERSION = CONFIG.FEISHU_VERSION

# Slack auth
AUTH_SLACK = CONFIG.AUTH_SLACK
SLACK_CLIENT_ID = CONFIG.SLACK_CLIENT_ID
SLACK_CLIENT_SECRET = CONFIG.SLACK_CLIENT_SECRET
SLACK_BOT_TOKEN = CONFIG.SLACK_BOT_TOKEN

# Saml2 auth
AUTH_SAML2 = CONFIG.AUTH_SAML2
AUTH_SAML2_PROVIDER_AUTHORIZATION_ENDPOINT = CONFIG.AUTH_SAML2_PROVIDER_AUTHORIZATION_ENDPOINT
AUTH_SAML2_AUTHENTICATION_FAILURE_REDIRECT_URI = CONFIG.AUTH_SAML2_AUTHENTICATION_FAILURE_REDIRECT_URI
AUTH_SAML2_ALWAYS_UPDATE_USER = CONFIG.AUTH_SAML2_ALWAYS_UPDATE_USER
SAML2_LOGOUT_COMPLETELY = CONFIG.SAML2_LOGOUT_COMPLETELY
SAML2_RENAME_ATTRIBUTES = CONFIG.SAML2_RENAME_ATTRIBUTES
SAML2_SP_ADVANCED_SETTINGS = CONFIG.SAML2_SP_ADVANCED_SETTINGS
SAML2_LOGIN_URL_NAME = "authentication:saml2:saml2-login"
SAML2_LOGOUT_URL_NAME = "authentication:saml2:saml2-logout"

# OAuth2 auth
AUTH_OAUTH2 = CONFIG.AUTH_OAUTH2
AUTH_OAUTH2_LOGO_PATH = CONFIG.AUTH_OAUTH2_LOGO_PATH
AUTH_OAUTH2_PROVIDER = CONFIG.AUTH_OAUTH2_PROVIDER
AUTH_OAUTH2_ALWAYS_UPDATE_USER = CONFIG.AUTH_OAUTH2_ALWAYS_UPDATE_USER
AUTH_OAUTH2_PROVIDER_AUTHORIZATION_ENDPOINT = CONFIG.AUTH_OAUTH2_PROVIDER_AUTHORIZATION_ENDPOINT
AUTH_OAUTH2_ACCESS_TOKEN_ENDPOINT = CONFIG.AUTH_OAUTH2_ACCESS_TOKEN_ENDPOINT
AUTH_OAUTH2_ACCESS_TOKEN_METHOD = CONFIG.AUTH_OAUTH2_ACCESS_TOKEN_METHOD
AUTH_OAUTH2_PROVIDER_USERINFO_ENDPOINT = CONFIG.AUTH_OAUTH2_PROVIDER_USERINFO_ENDPOINT
AUTH_OAUTH2_CLIENT_SECRET = CONFIG.AUTH_OAUTH2_CLIENT_SECRET
AUTH_OAUTH2_CLIENT_ID = CONFIG.AUTH_OAUTH2_CLIENT_ID
AUTH_OAUTH2_SCOPE = CONFIG.AUTH_OAUTH2_SCOPE
AUTH_OAUTH2_USER_ATTR_MAP = CONFIG.AUTH_OAUTH2_USER_ATTR_MAP
AUTH_OAUTH2_LOGOUT_COMPLETELY = CONFIG.AUTH_OAUTH2_LOGOUT_COMPLETELY
AUTH_OAUTH2_PROVIDER_END_SESSION_ENDPOINT = CONFIG.AUTH_OAUTH2_PROVIDER_END_SESSION_ENDPOINT
AUTH_OAUTH2_AUTH_LOGIN_CALLBACK_URL_NAME = 'authentication:oauth2:login-callback'
AUTH_OAUTH2_AUTHENTICATION_REDIRECT_URI = '/'
AUTH_OAUTH2_AUTHENTICATION_FAILURE_REDIRECT_URI = '/'
AUTH_OAUTH2_LOGOUT_URL_NAME = "authentication:oauth2:logout"

AUTH_PASSKEY = CONFIG.AUTH_PASSKEY
FIDO_SERVER_ID = CONFIG.FIDO_SERVER_ID
FIDO_SERVER_NAME = CONFIG.FIDO_SERVER_NAME
KEY_ATTACHMENT = 2  # 0 any, 1 platform, 2 cross-platform 3 none
# 临时 token
AUTH_TEMP_TOKEN = CONFIG.AUTH_TEMP_TOKEN

# Vault
VAULT_ENABLED = CONFIG.VAULT_ENABLED
VAULT_HCP_HOST = CONFIG.VAULT_HCP_HOST
VAULT_HCP_TOKEN = CONFIG.VAULT_HCP_TOKEN
VAULT_HCP_MOUNT_POINT = CONFIG.VAULT_HCP_MOUNT_POINT

# Pilla
VAULT_PILLA_AUTH_URL = CONFIG.VAULT_PILLA_AUTH_URL
VAULT_PILLA_TOKEN = CONFIG.VAULT_PILLA_TOKEN
VAULT_PILLA_PRIVATE_KEY = CONFIG.VAULT_PILLA_PRIVATE_KEY

HISTORY_ACCOUNT_CLEAN_LIMIT = CONFIG.HISTORY_ACCOUNT_CLEAN_LIMIT

# Other setting
# 这个是 User Login Private Token
TOKEN_EXPIRATION = CONFIG.TOKEN_EXPIRATION
OTP_IN_RADIUS = CONFIG.OTP_IN_RADIUS

RBAC_BACKEND = 'rbac.backends.RBACBackend'
AUTH_BACKEND_MODEL = 'authentication.backends.base.JMSModelBackend'
AUTH_BACKEND_PUBKEY = 'authentication.backends.pubkey.PublicKeyAuthBackend'
AUTH_BACKEND_LDAP = 'authentication.backends.ldap.LDAPAuthorizationBackend'
AUTH_BACKEND_OIDC_PASSWORD = 'authentication.backends.oidc.OIDCAuthPasswordBackend'
AUTH_BACKEND_OIDC_CODE = 'authentication.backends.oidc.OIDCAuthCodeBackend'
AUTH_BACKEND_RADIUS = 'authentication.backends.radius.RadiusBackend'
AUTH_BACKEND_CAS = 'authentication.backends.cas.CASBackend'
AUTH_BACKEND_SSO = 'authentication.backends.sso.SSOAuthentication'
AUTH_BACKEND_WECOM = 'authentication.backends.sso.WeComAuthentication'
AUTH_BACKEND_DINGTALK = 'authentication.backends.sso.DingTalkAuthentication'
AUTH_BACKEND_FEISHU = 'authentication.backends.sso.FeiShuAuthentication'
AUTH_BACKEND_SLACK = 'authentication.backends.sso.SlackAuthentication'
AUTH_BACKEND_AUTH_TOKEN = 'authentication.backends.sso.AuthorizationTokenAuthentication'
AUTH_BACKEND_SAML2 = 'authentication.backends.saml2.SAML2Backend'
AUTH_BACKEND_OAUTH2 = 'authentication.backends.oauth2.OAuth2Backend'
AUTH_BACKEND_TEMP_TOKEN = 'authentication.backends.token.TempTokenAuthBackend'
AUTH_BACKEND_CUSTOM = 'authentication.backends.custom.CustomAuthBackend'
AUTH_BACKEND_PASSKEY = 'authentication.backends.passkey.PasskeyAuthBackend'
AUTHENTICATION_BACKENDS = [
    # 只做权限校验
    RBAC_BACKEND,
    # 密码形式
    AUTH_BACKEND_MODEL, AUTH_BACKEND_PUBKEY, AUTH_BACKEND_LDAP, AUTH_BACKEND_RADIUS,
    # 跳转形式
    AUTH_BACKEND_CAS, AUTH_BACKEND_OIDC_PASSWORD, AUTH_BACKEND_OIDC_CODE, AUTH_BACKEND_SAML2,
    AUTH_BACKEND_OAUTH2,
    # 扫码模式
    AUTH_BACKEND_WECOM, AUTH_BACKEND_DINGTALK, AUTH_BACKEND_FEISHU, AUTH_BACKEND_SLACK,
    # Token模式
    AUTH_BACKEND_AUTH_TOKEN, AUTH_BACKEND_SSO, AUTH_BACKEND_TEMP_TOKEN,
    AUTH_BACKEND_PASSKEY
]


def get_file_md5(filepath):
    import hashlib
    # 创建md5对象
    m = hashlib.md5()
    with open(filepath, 'rb') as f:
        while True:
            data = f.read(4096)
            if not data:
                break
            # 更新md5对象
            m.update(data)
    # 返回md5对象
    return m.hexdigest()


AUTH_CUSTOM = CONFIG.AUTH_CUSTOM
AUTH_CUSTOM_FILE_MD5 = CONFIG.AUTH_CUSTOM_FILE_MD5
AUTH_CUSTOM_FILE_PATH = os.path.join(PROJECT_DIR, 'data', 'auth', 'main.py')
if AUTH_CUSTOM and AUTH_CUSTOM_FILE_MD5 == get_file_md5(AUTH_CUSTOM_FILE_PATH):
    # 自定义认证模块
    AUTHENTICATION_BACKENDS.append(AUTH_BACKEND_CUSTOM)

MFA_BACKEND_OTP = 'authentication.mfa.otp.MFAOtp'
MFA_BACKEND_RADIUS = 'authentication.mfa.radius.MFARadius'
MFA_BACKEND_SMS = 'authentication.mfa.sms.MFASms'
MFA_BACKEND_CUSTOM = 'authentication.mfa.custom.MFACustom'

MFA_BACKENDS = [MFA_BACKEND_OTP, MFA_BACKEND_RADIUS, MFA_BACKEND_SMS]

MFA_CUSTOM = CONFIG.MFA_CUSTOM
MFA_CUSTOM_FILE_MD5 = CONFIG.MFA_CUSTOM_FILE_MD5
MFA_CUSTOM_FILE_PATH = os.path.join(PROJECT_DIR, 'data', 'mfa', 'main.py')
if MFA_CUSTOM and MFA_CUSTOM_FILE_MD5 == get_file_md5(MFA_CUSTOM_FILE_PATH):
    # 自定义多因子认证模块
    MFA_BACKENDS.append(MFA_BACKEND_CUSTOM)

SMS_CUSTOM_FILE_MD5 = CONFIG.SMS_CUSTOM_FILE_MD5
SMS_CUSTOM_FILE_PATH = os.path.join(PROJECT_DIR, 'data', 'sms', 'main.py')

AUTHENTICATION_BACKENDS_THIRD_PARTY = [
    AUTH_BACKEND_OIDC_CODE, AUTH_BACKEND_CAS,
    AUTH_BACKEND_SAML2, AUTH_BACKEND_OAUTH2
]
ONLY_ALLOW_EXIST_USER_AUTH = CONFIG.ONLY_ALLOW_EXIST_USER_AUTH
ONLY_ALLOW_AUTH_FROM_SOURCE = CONFIG.ONLY_ALLOW_AUTH_FROM_SOURCE

SAML_FOLDER = os.path.join(BASE_DIR, 'authentication', 'backends', 'saml2')
