"""Tests against the real Beget API.

They change DNS records on the account, so they only run when started by hand with a
credentials file in the same format as for certbot:

    BEGET_CREDENTIALS=beget.ini BEGET_TEST_DOMAIN=example.com pytest tests/integration_test.py

Only subdomains with random names under BEGET_TEST_DOMAIN are touched, and they are
deleted afterwards.
"""

import os
import secrets
from collections.abc import Iterator

import pytest
from certbot import errors
from configobj import ConfigObj

from certbot_dns_beget_plugin.client import BegetClient

CREDENTIALS = os.environ.get('BEGET_CREDENTIALS')
DOMAIN = os.environ.get('BEGET_TEST_DOMAIN')

if not CREDENTIALS or not DOMAIN:
    pytest.skip(
        'manual run only: set BEGET_CREDENTIALS to the credentials INI file and '
        'BEGET_TEST_DOMAIN to a domain on the account',
        allow_module_level=True,
    )


@pytest.fixture
def client() -> BegetClient:
    conf = ConfigObj(CREDENTIALS)
    return BegetClient(conf['dns_beget_plugin_username'], conf['dns_beget_plugin_password'])


@pytest.fixture
def name(client: BegetClient) -> Iterator[str]:
    name = f'_acme-challenge-test-{secrets.token_hex(4)}.{DOMAIN}'
    yield name
    # Safety net in case a test failed before cleaning up.
    for subdomain_id in _subdomain_ids(client, name):
        client._call('domain/deleteSubdomain', {'id': subdomain_id})


def _subdomain_ids(client: BegetClient, name: str) -> list[int]:
    return [
        int(s['id'])
        for s in client._list_subdomains()
        if s['fqdn'] == name or s['fqdn'].endswith('.' + name)
    ]


def _txt_values(client: BegetClient, name: str) -> list[str]:
    return [r['value'] for r in client._get_basic_records(name).get('TXT', [])]


def test_new_subdomain_is_created_and_removed(client: BegetClient, name: str) -> None:
    client.add_txt_record(name, 'token1')
    client.add_txt_record(name, 'token2')
    assert {'token1', 'token2'} <= set(_txt_values(client, name))

    client.del_txt_record(name, 'token1')
    txt = _txt_values(client, name)
    assert 'token1' not in txt
    assert 'token2' in txt

    client.del_txt_record(name, 'token2')
    assert _subdomain_ids(client, name) == []


def test_existing_subdomain_keeps_its_records(client: BegetClient, name: str) -> None:
    domain, domain_id = client._find_domain(name)
    client._call(
        'domain/addSubdomainVirtual',
        {'subdomain': name[: -len(domain) - 1], 'domain_id': domain_id},
    )
    client._change_records(
        name,
        {
            'A': [{'priority': 10, 'value': '192.0.2.1'}],
            'AAAA': [{'priority': 10, 'value': '2001:db8::1'}],
            'MX': [{'priority': 10, 'value': 'mx.example.com'}],
            'TXT': [{'priority': 10, 'value': 'keep "me"'}],
        },
    )
    before = client._get_basic_records(name)

    client.add_txt_record(name, 'token')
    assert 'token' in _txt_values(client, name)
    client.del_txt_record(name, 'token')

    assert client._get_basic_records(name) == before
    assert _subdomain_ids(client, name) != []


def test_validation_error_is_readable(client: BegetClient, name: str) -> None:
    with pytest.raises(errors.PluginError, match='Empty txt record'):
        client.add_txt_record(name, '')
