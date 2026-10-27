import logging

import pytest
import requests
from certbot import errors

from certbot_dns_beget_plugin.client import BegetClient
from fake_beget import FakeBeget

NAME = '_acme-challenge.example.com'
# Beget puts this TXT record on every new subdomain.
SPF = 'v=spf1 redirect=beget.com'


@pytest.fixture
def api() -> FakeBeget:
    fake = FakeBeget()
    fake.add_domain('example.com')
    return fake


@pytest.fixture
def client(api: FakeBeget) -> BegetClient:
    beget = BegetClient(api.login, api.password)
    beget._session.post = api  # type: ignore[method-assign]
    return beget


def _subdomain_names(api: FakeBeget) -> list[str]:
    return sorted(fqdn for fqdn, _ in api.subdomains.values())


def test_add_and_delete_creates_and_removes_subdomain(api: FakeBeget, client: BegetClient) -> None:
    client.add_txt_record(NAME, 'token')

    assert _subdomain_names(api) == [NAME]
    assert api.txt_values(NAME) == [SPF, 'token']

    client.del_txt_record(NAME, 'token')

    assert _subdomain_names(api) == []


def test_domain_and_wildcard_share_name(api: FakeBeget, client: BegetClient) -> None:
    # certbot -d example.com -d *.example.com: two values for one name
    client.add_txt_record(NAME, 'token1')
    client.add_txt_record(NAME, 'token2')
    assert api.txt_values(NAME) == [SPF, 'token1', 'token2']

    client.del_txt_record(NAME, 'token1')
    assert api.txt_values(NAME) == [SPF, 'token2']

    client.del_txt_record(NAME, 'token2')
    assert _subdomain_names(api) == []


def test_existing_subdomain_is_kept_with_its_records(api: FakeBeget, client: BegetClient) -> None:
    domain_id = next(iter(api.domains))
    api.add_subdomain(NAME, domain_id)
    api.records[NAME] = {
        'A': [{'ttl': 600, 'address': '192.0.2.5'}],
        'MX': [
            {'ttl': 300, 'exchange': 'mx1.beget.com.', 'preference': 10},
            {'ttl': 300, 'exchange': 'mx2.beget.com.', 'preference': 20},
        ],
        'TXT': [{'ttl': 300, 'txtdata': 'v=spf1 -all'}],
    }

    client.add_txt_record(NAME, 'token')
    assert api.txt_values(NAME) == ['v=spf1 -all', 'token']

    client.del_txt_record(NAME, 'token')

    assert _subdomain_names(api) == [NAME]
    # changeRecords does not accept a TTL and resets it to 600.
    assert api.records[NAME] == {
        'A': [{'ttl': 600, 'address': '192.0.2.5'}],
        'MX': [
            {'ttl': 600, 'exchange': 'mx1.beget.com.', 'preference': 10},
            {'ttl': 600, 'exchange': 'mx2.beget.com.', 'preference': 20},
        ],
        'TXT': [{'ttl': 600, 'txtdata': 'v=spf1 -all'}],
    }


def test_aaaa_records_are_kept(api: FakeBeget, client: BegetClient) -> None:
    api.add_subdomain(NAME, next(iter(api.domains)))
    api.records[NAME]['AAAA'] = [{'ttl': 600, 'address': '2001:db8::1'}]

    client.add_txt_record(NAME, 'token')
    client.del_txt_record(NAME, 'token')

    assert api.records[NAME]['AAAA'] == [{'ttl': 600, 'address': '2001:db8::1'}]


def test_txt_value_with_quotes_is_sent_back_as_returned(
    api: FakeBeget, client: BegetClient
) -> None:
    # getData escapes quotes, and changeRecords accepts the escaped form unchanged.
    api.add_subdomain(NAME, next(iter(api.domains)))
    api.records[NAME]['TXT'] = [{'ttl': 600, 'txtdata': 'a\\"b'}]

    client.add_txt_record(NAME, 'token')

    assert api.txt_values(NAME) == ['a\\"b', 'token']


def test_documented_record_format_is_accepted(api: FakeBeget, client: BegetClient) -> None:
    domain_id = next(iter(api.domains))
    api.add_subdomain(NAME, domain_id)
    api.records[NAME] = {
        'DNS': [{'value': 'ns1.beget.ru', 'priority': 10}],
        'DNS_IP': [{'value': None, 'priority': 10}],
        'A': [{'value': '192.0.2.5', 'priority': '0'}],
        'TXT': [{'value': '', 'priority': 0}],
    }

    client.add_txt_record(NAME, 'token')

    _, _, args = api.calls[-1]
    assert args['records'] == {
        'A': [{'priority': 10, 'value': '192.0.2.5'}],
        'TXT': [{'priority': 10, 'value': 'token'}],
    }


def test_www_alias_created_with_subdomain_is_removed(api: FakeBeget, client: BegetClient) -> None:
    api.create_www_alias = True

    client.add_txt_record(NAME, 'token')
    assert _subdomain_names(api) == [NAME, 'www.' + NAME]

    client.del_txt_record(NAME, 'token')
    assert _subdomain_names(api) == []


def test_www_alias_deleted_with_subdomain_does_not_fail_cleanup(
    api: FakeBeget, client: BegetClient, caplog: pytest.LogCaptureFixture
) -> None:
    api.create_www_alias = True
    api.cascade_www_alias = True

    client.add_txt_record(NAME, 'token')
    with caplog.at_level(logging.WARNING):
        client.del_txt_record(NAME, 'token')

    assert _subdomain_names(api) == []
    assert caplog.text == ''


@pytest.mark.parametrize(
    'name, expected_subdomain, expected_domain',
    [
        ('_acme-challenge.example.com', '_acme-challenge', 'example.com'),
        ('_acme-challenge.a.b.example.com', '_acme-challenge.a.b', 'example.com'),
        ('_acme-challenge.shop.example.com', '_acme-challenge', 'shop.example.com'),
    ],
)
def test_longest_matching_domain_is_used(
    api: FakeBeget, client: BegetClient, name: str, expected_subdomain: str, expected_domain: str
) -> None:
    api.add_domain('shop.example.com')
    api.add_domain('notexample.com')

    client.add_txt_record(name, 'token')

    args = next(a for url, _, a in api.calls if url.endswith('addSubdomainVirtual'))
    assert args['subdomain'] == expected_subdomain
    assert api.domains[args['domain_id']] == expected_domain


def test_unknown_domain(api: FakeBeget, client: BegetClient) -> None:
    with pytest.raises(errors.PluginError, match='Unable to find a domain'):
        client.add_txt_record('_acme-challenge.notexample.com', 'token')


def test_credentials_are_not_sent_in_url(api: FakeBeget, client: BegetClient) -> None:
    client.add_txt_record(NAME, 'token')

    for url, data, _ in api.calls:
        assert api.password not in url
        assert data['passwd'] == api.password


def test_auth_error(api: FakeBeget, client: BegetClient) -> None:
    api.password = 'other'
    with pytest.raises(errors.PluginError, match=r'Auth failed \[AUTH_ERROR\]'):
        client.add_txt_record(NAME, 'token')


def test_method_error(api: FakeBeget, client: BegetClient) -> None:
    api.fail_methods['domain/addSubdomainVirtual'] = {
        'status': 'success',
        'answer': {
            'status': 'error',
            'errors': [{'error_code': 'LIMIT_ERROR', 'error_text': 'Too many requests'}],
        },
    }
    with pytest.raises(errors.PluginError, match=r'Too many requests \[LIMIT_ERROR\]'):
        client.add_txt_record(NAME, 'token')


def test_change_records_returning_false(api: FakeBeget, client: BegetClient) -> None:
    api.fail_methods['dns/changeRecords'] = {
        'status': 'success',
        'answer': {'status': 'success', 'result': False},
    }
    with pytest.raises(errors.PluginError, match='refused to change'):
        client.add_txt_record(NAME, 'token')


def test_network_error(client: BegetClient) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise requests.ConnectionError('boom')

    client._session.post = fail  # type: ignore[assignment]

    with pytest.raises(errors.PluginError, match='Error communicating with the Beget API'):
        client.add_txt_record(NAME, 'token')


def test_input_data_is_always_sent(api: FakeBeget, client: BegetClient) -> None:
    client.add_txt_record(NAME, 'token')

    for _, data, _ in api.calls:
        assert 'input_data' in data


def test_non_json_response(api: FakeBeget, client: BegetClient) -> None:
    client._session.post = (  # type: ignore[assignment]
        lambda *args, **kwargs: api._text_response('Cannot parse the JSON input params')
    )

    with pytest.raises(errors.PluginError, match=r"non-JSON.*'Cannot parse the JSON input params'"):
        client.add_txt_record(NAME, 'token')


def test_cleanup_after_failed_perform_does_nothing(api: FakeBeget, client: BegetClient) -> None:
    api.fail_methods['domain/getSubdomainList'] = {
        'status': 'error',
        'error_text': 'down',
        'error_code': 'INCORRECT_REQUEST',
    }
    with pytest.raises(errors.PluginError):
        client.add_txt_record(NAME, 'token')
    calls_before_cleanup = len(api.calls)

    client.del_txt_record(NAME, 'token')

    assert len(api.calls) == calls_before_cleanup


def test_cleanup_removes_subdomain_if_adding_txt_failed(
    api: FakeBeget, client: BegetClient
) -> None:
    api.fail_methods['dns/changeRecords'] = {
        'status': 'success',
        'answer': {
            'status': 'error',
            'errors': [{'error_code': 'METHOD_FAILED', 'error_text': 'fail'}],
        },
    }
    with pytest.raises(errors.PluginError):
        client.add_txt_record(NAME, 'token')
    assert _subdomain_names(api) == [NAME]

    client.del_txt_record(NAME, 'token')

    assert _subdomain_names(api) == []


def test_cleanup_removes_subdomain_if_listing_failed_after_creating_it(
    api: FakeBeget, client: BegetClient
) -> None:
    add_subdomain = api._domain_addSubdomainVirtual

    def add_and_break_listing(subdomain: str, domain_id: int) -> int:
        result = add_subdomain(subdomain, domain_id)
        api.fail_methods['domain/getSubdomainList'] = {
            'status': 'error',
            'error_text': 'down',
            'error_code': 'INCORRECT_REQUEST',
        }
        return result

    api._domain_addSubdomainVirtual = add_and_break_listing  # type: ignore[method-assign]
    with pytest.raises(errors.PluginError):
        client.add_txt_record(NAME, 'token')
    assert _subdomain_names(api) == [NAME]

    del api.fail_methods['domain/getSubdomainList']
    client.del_txt_record(NAME, 'token')

    assert _subdomain_names(api) == []


def test_same_value_added_twice_is_kept_until_last_cleanup(
    api: FakeBeget, client: BegetClient
) -> None:
    api.add_subdomain(NAME, next(iter(api.domains)))

    client.add_txt_record(NAME, 'token')
    client.add_txt_record(NAME, 'token')
    assert api.txt_values(NAME) == ['token']

    client.del_txt_record(NAME, 'token')
    assert api.txt_values(NAME) == ['token']

    client.del_txt_record(NAME, 'token')
    assert api.txt_values(NAME) == []


def test_delegated_name_is_refused(api: FakeBeget, client: BegetClient) -> None:
    api.add_subdomain(NAME, next(iter(api.domains)))
    api.set_types[NAME] = 3

    with pytest.raises(errors.PluginError, match='NS or CNAME'):
        client.add_txt_record(NAME, 'token')


def test_unsupported_record_type_is_not_dropped(api: FakeBeget, client: BegetClient) -> None:
    api.add_subdomain(NAME, next(iter(api.domains)))
    api.records[NAME]['CAA'] = [{'ttl': 600, 'flags': 0, 'tag': 'issue', 'value': 'ca.test'}]

    with pytest.raises(errors.PluginError, match='CAA records'):
        client.add_txt_record(NAME, 'token')
    assert not any(url.endswith('changeRecords') for url, _, _ in api.calls)


def test_more_than_ten_txt_records(api: FakeBeget, client: BegetClient) -> None:
    # The API accepted 50 TXT records per name when probed.
    api.add_subdomain(NAME, next(iter(api.domains)))
    api.records[NAME]['TXT'] = [{'ttl': 600, 'txtdata': str(i)} for i in range(10)]

    client.add_txt_record(NAME, 'token')

    assert api.txt_values(NAME)[-1] == 'token'


def test_structured_validation_error_is_readable(api: FakeBeget, client: BegetClient) -> None:
    with pytest.raises(errors.PluginError, match=r'failed: Empty txt record; Value must'):
        client.add_txt_record(NAME, '')


def test_structured_error_without_messages(api: FakeBeget, client: BegetClient) -> None:
    api.fail_methods['domain/getSubdomainList'] = {
        'status': 'success',
        'answer': {
            'status': 'error',
            'errors': [{'error_code': 'METHOD_FAILED', 'error_text': {'type': 'SOME_TYPE'}}],
        },
    }

    with pytest.raises(errors.PluginError, match=r'failed: SOME_TYPE \[METHOD_FAILED\]'):
        client.add_txt_record(NAME, 'token')


def test_cleanup_errors_are_logged_not_raised(
    api: FakeBeget, client: BegetClient, caplog: pytest.LogCaptureFixture
) -> None:
    client.add_txt_record(NAME, 'token')
    api.fail_methods['domain/deleteSubdomain'] = {
        'status': 'error',
        'error_text': 'down',
        'error_code': 'INCORRECT_REQUEST',
    }

    with caplog.at_level(logging.WARNING):
        client.del_txt_record(NAME, 'token')

    assert 'Failed to clean up' in caplog.text


def test_cleanup_without_perform_does_nothing(api: FakeBeget, client: BegetClient) -> None:
    client.del_txt_record(NAME, 'token')
    assert api.calls == []


def test_existing_subdomain_list_is_fetched_once(api: FakeBeget, client: BegetClient) -> None:
    client.add_txt_record(NAME, 'token')

    listings = [url for url, _, _ in api.calls if url.endswith('getSubdomainList')]
    # One check before creating the subdomain, one to find aliases created with it.
    assert len(listings) == 2


@pytest.mark.parametrize(
    'body, message',
    [
        (['not', 'a', 'dict'], 'unexpected response'),
        ({'status': 'success', 'answer': None}, 'failed: unknown error'),
    ],
)
def test_malformed_response(
    api: FakeBeget, client: BegetClient, body: object, message: str
) -> None:
    client._session.post = lambda *args, **kwargs: api._response(body)  # type: ignore[assignment]

    with pytest.raises(errors.PluginError, match=message):
        client.add_txt_record(NAME, 'token')


def test_account_without_domains(api: FakeBeget, client: BegetClient) -> None:
    api.fail_methods['domain/getList'] = {
        'status': 'success',
        'answer': {'status': 'success', 'result': None},
    }

    with pytest.raises(errors.PluginError, match=r'domains on the account: none'):
        client.add_txt_record(NAME, 'token')
