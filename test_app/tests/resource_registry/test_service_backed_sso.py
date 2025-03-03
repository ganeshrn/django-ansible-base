from unittest import mock

import jwt
import pytest
from social_django.models import UserSocialAuth
from social_django.storage import BaseDjangoStorage
from social_django.strategy import DjangoStrategy

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.resource_registry.resource_server import get_resource_server_config
from ansible_base.resource_registry.utils.auth_code import get_user_auth_code
from ansible_base.resource_registry.utils.service_backed_sso_pipeline import redirect_to_resource_server


def _validate_auth_code(auth_code, user):
    cfg = get_resource_server_config()

    data = jwt.decode(
        auth_code,
        cfg["SECRET_KEY"],
        algorithms=cfg["JWT_ALGORITHM"],
        required=["iss", "exp"],
    )

    assert data["username"] == user.username
    assert data["sub"] == str(user.resource.ansible_id)

    return data


@pytest.fixture
def patched_load_strategy():
    def _get_strat():
        return DjangoStrategy(storage=BaseDjangoStorage())

    with mock.patch("ansible_base.resource_registry.utils.sso_provider.load_strategy", _get_strat) as get_strat:
        yield get_strat


@pytest.fixture
def authenticator_user(user, github_authenticator):
    AuthenticatorUser.objects.create(provider=github_authenticator, user=user, uid="my_uid")

    return user, user.authenticator_users.first()


@pytest.fixture
def social_user(user, patched_load_strategy):
    UserSocialAuth.objects.create(provider="github", user=user, uid="my_uid")

    return user, user.social_auth.first()


@pytest.mark.django_db
def test_user_auth_code_generation_social_auth(social_user):
    user, social = social_user
    auth_code = get_user_auth_code(user)
    data = _validate_auth_code(auth_code, user)
    assert data["sso_uid"] is None
    assert data["sso_backend"] is None

    auth_code = get_user_auth_code(user, social_user=social)
    data = _validate_auth_code(auth_code, user)

    assert data["sso_uid"] == "my_uid"
    assert data["sso_backend"] == social.provider
    assert data["sso_server"] == "https://github.com/login/oauth/authorize"


@pytest.mark.django_db
def test_user_auth_code_generation_dab(authenticator_user):
    user, social = authenticator_user
    auth_code = get_user_auth_code(user)
    data = _validate_auth_code(auth_code, user)
    assert data["sso_uid"] is None
    assert data["sso_backend"] is None

    auth_code = get_user_auth_code(user, social_user=social)
    data = _validate_auth_code(auth_code, user)

    assert data["sso_uid"] == "my_uid"
    assert data["sso_backend"] == social.provider.slug
    assert data["sso_server"] == "https://github.com/login/oauth/authorize"


@pytest.mark.django_db
def test_auth_code_pipeline(settings, social_user):
    settings.ENABLE_SERVICE_BACKED_SSO = True

    user, social = social_user

    response = {
        "sub": "my_uid",
        "preferred_username": "123123123123123",
    }
    resp = redirect_to_resource_server(user=user, social=social, response=response)

    auth_code = resp.url.split("?auth_code=")[1]

    data = _validate_auth_code(auth_code, user)

    assert data["sso_uid"] == "my_uid"
    assert data["sso_backend"] == social.provider
    assert data["sso_server"] == "https://github.com/login/oauth/authorize"
    assert data["oidc_alt_key"] == "123123123123123"


@pytest.mark.django_db
def test_auth_code_pipeline_resource_server_unset(social_user, settings):
    settings.ENABLE_SERVICE_BACKED_SSO = False

    user, social = social_user

    response = {
        "sub": "my_uid",
        "preferred_username": "123123123123123",
    }
    resp = redirect_to_resource_server(user=user, social=social, response=response)
    assert resp is None


@pytest.mark.django_db
def test_auth_code_pipeline_dab(authenticator_user, settings):
    settings.ENABLE_SERVICE_BACKED_SSO = True

    user, social = authenticator_user

    response = {
        "sub": "123123123123123",
        "preferred_username": "my_uid",
    }
    resp = redirect_to_resource_server(user=user, social=social, response=response)

    auth_code = resp.url.split("?auth_code=")[1]

    data = _validate_auth_code(auth_code, user)

    assert data["sso_uid"] == "my_uid"
    assert data["sso_backend"] == social.provider.slug
    assert data["sso_server"] == "https://github.com/login/oauth/authorize"
    assert data["oidc_alt_key"] == "123123123123123"


@pytest.mark.django_db
def test_auth_code_pipeline_no_social(user, settings):
    settings.ENABLE_SERVICE_BACKED_SSO = True

    resp = redirect_to_resource_server(user=user)

    auth_code = resp.url.split("?auth_code=")[1]

    data = _validate_auth_code(auth_code, user)

    assert data["sso_uid"] is None
    assert data["sso_backend"] is None
    assert data["sso_server"] is None


@pytest.mark.django_db
def test_auth_code_pipeline_not_authed(settings):
    settings.ENABLE_SERVICE_BACKED_SSO = True

    assert redirect_to_resource_server(user=None, social=None) is None
