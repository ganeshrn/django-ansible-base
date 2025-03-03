from unittest.mock import MagicMock, Mock

import pytest
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist, FieldError, ValidationError
from django.test.utils import override_settings
from django.utils.http import urlencode
from rest_framework.exceptions import ParseError, PermissionDenied

from ansible_base.authentication.models import Authenticator, AuthenticatorMap
from ansible_base.authentication.views import AuthenticatorViewSet
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rest_filters.rest_framework.field_lookup_backend import FieldLookupBackend
from test_app import models


def test_filters_related():
    field_lookup = FieldLookupBackend()
    lookup = '__'.join(['created_by', 'pk'])
    field, new_lookup = field_lookup.get_field_from_lookup(Authenticator, lookup)


def test_filters_no_lookup():
    field_lookup = FieldLookupBackend()
    with pytest.raises(ParseError):
        _, _ = field_lookup.get_field_from_lookup(Authenticator, '')


def test_invalid_filter_key():
    field_lookup = FieldLookupBackend()
    # FieldDoesNotExist is caught and converted to ParseError by filter_queryset
    with pytest.raises(FieldDoesNotExist) as excinfo:
        field_lookup.value_to_python(Authenticator, 'created_by.gibberish', 'foo')
    assert 'has no field named' in str(excinfo)


@pytest.mark.parametrize(u"empty_value", [u'', ''])
def test_empty_in(empty_value):
    field_lookup = FieldLookupBackend()
    with pytest.raises(ValueError) as excinfo:
        field_lookup.value_to_python(Authenticator, 'created_by__username__in', empty_value)
    assert 'empty value for __in' in str(excinfo.value)


@pytest.mark.parametrize(u"valid_value", [u'foo', u'foo,'])
def test_valid_in(valid_value):
    field_lookup = FieldLookupBackend()
    value, new_lookup, _ = field_lookup.value_to_python(Authenticator, 'created_by__username__in', valid_value)
    assert 'foo' in value


def test_invalid_field():
    invalid_field = u"ヽヾ"
    field_lookup = FieldLookupBackend()
    with pytest.raises(ValueError) as excinfo:
        field_lookup.value_to_python(Authenticator, invalid_field, 'foo')
    assert 'is not an allowed field name. Must be ascii encodable.' in str(excinfo.value)


def test_valid_iexact():
    field_lookup = FieldLookupBackend()
    value, new_lookup, _ = field_lookup.value_to_python(Authenticator, 'created_by__username__iexact', 'foo')
    assert 'foo' in value


def test_invalid_iexact():
    field_lookup = FieldLookupBackend()
    with pytest.raises(ValueError) as excinfo:
        field_lookup.value_to_python(Authenticator, 'id__iexact', '1')
    assert 'is not a text field and cannot be filtered by case-insensitive search' in str(excinfo.value)


@pytest.mark.parametrize('lookup_suffix', ['', 'contains', 'startswith', 'in'])
def test_filter_on_password_field(lookup_suffix):
    # Make the type field of Authenticator a PASSWORD_FIELD
    setattr(Authenticator, 'PASSWORD_FIELDS', ('type'))
    field_lookup = FieldLookupBackend()
    lookup = '__'.join(filter(None, ['type', lookup_suffix]))
    with pytest.raises(PermissionDenied) as excinfo:
        field, new_lookup = field_lookup.get_field_from_lookup(Authenticator, lookup)
    assert 'not allowed' in str(excinfo.value)


@pytest.mark.parametrize(
    'model, query',
    [
        (Authenticator, 'configuration__icontains'),
    ],
)
def test_filter_sensitive_fields_and_relations(model, query):
    field_lookup = FieldLookupBackend()
    with pytest.raises(PermissionDenied) as excinfo:
        field, new_lookup = field_lookup.get_field_from_lookup(model, query)
    assert 'not allowed' in str(excinfo.value)


@pytest.mark.parametrize(
    'value,result',
    (
        (1, 1),
        (None, None),
        ('none', None),
        ('null', None),
        (-1, -1),
    ),
)
def test_to_python_related(value, result):
    field_lookup = FieldLookupBackend()
    assert field_lookup.to_python_related(value) == result


def test_to_python_related_exception():
    field_lookup = FieldLookupBackend()
    with pytest.raises(ValueError):
        field_lookup.to_python_related('random')


def test_value_to_python_for_field_boolean_field():
    field_lookup = FieldLookupBackend()
    assert field_lookup.value_to_python_for_field(Authenticator._meta.get_field('remove_users'), True) is True


def test_value_to_python_for_field_fk_field_exception():
    field_lookup = FieldLookupBackend()
    with pytest.raises(ParseError):
        field_lookup.value_to_python_for_field(AuthenticatorMap._meta.get_field('authenticator'), True)


@pytest.mark.parametrize("exception", ((ValidationError("")), (FieldError(""))))
def test_filter_queryset_exception(exception):
    filter = FieldLookupBackend()
    request = MagicMock()
    request.query_params.lists = Mock(side_effect=exception)

    with pytest.raises(ParseError):
        filter.filter_queryset(request, Authenticator.objects.all(), AuthenticatorViewSet)


@pytest.mark.parametrize(
    "query",
    (
        (()),
        ((('page_size', [10]),)),
        ((('id__int', [10]),)),
        ((('or__id', [10]),)),
        ((('not__id', [10]),)),
        ((('chain__id', [10]),)),
        ((('authenticator__search', ['find_me']),)),
        ((('authenticator__search', ['find_me,also_me']),)),
    ),
)
def test_filter_queryset(query):
    filter = FieldLookupBackend()
    request = MagicMock()
    iterator = MagicMock()
    iterator.__iter__.return_value = query
    request.query_params.lists.return_value = iterator

    filter.filter_queryset(request, AuthenticatorMap.objects.all(), AuthenticatorViewSet)


def test_filter_jsonfield_as_text(admin_api_client):
    models.City.objects.create(name='city', extra_data={'mayor': 'John Doe', 'radius': 10, 'elevation': 1000, 'is_capital': True})
    url = get_relative_url('city-list')

    # negative test, backwards compatibility doesn't allow this case
    # JSONField isn't treated as structured data, but as a text blob
    query_params = {'extra_data__mayor__icontains': 'John Doe'}
    response = admin_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 400
    assert 'No related model for field mayor' in str(response.data['detail'])

    # positive test, treating JSONField as a text blob
    query_params = {'extra_data__icontains': '"mayor": "John Doe"'}
    response = admin_api_client.get(url + '?' + urlencode(query_params))
    assert response.status_code == 200
    assert response.data['count'] == 1


def test_filter_unexpected_field(admin_api_client):
    url = get_relative_url('organization-list')
    response = admin_api_client.get(url, data={'foofield': 'bar'})
    assert response.status_code == 400, response.data


def test_app_ignore_field(admin_api_client):
    base_list = tuple(settings.ANSIBLE_BASE_REST_FILTERS_RESERVED_NAMES)
    with override_settings(ANSIBLE_BASE_REST_FILTERS_RESERVED_NAMES=base_list + ('foofield',)):
        url = get_relative_url('organization-list')
        response = admin_api_client.get(url, data={'foofield': 'bar'})
        assert response.status_code == 200, response.data


def test_view_level_ignore_field(admin_api_client):
    """See CowViewSet definition which corresponds to expectations of this test"""
    url = get_relative_url('cow-list')
    response = admin_api_client.get(url, data={'cud': 'chew'})
    assert response.status_code == 200, response.data

    # Make sure that normal function is not disrupted by this customization
    response = admin_api_client.get(url, data={'foofield': 'bar'})
    assert response.status_code == 400, response.data
