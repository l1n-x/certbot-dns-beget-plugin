"""In-memory imitation of the Beget API methods used by the plugin.

Response formats follow what the real API returned when probed in October 2026.
"""

import itertools
import json
from typing import Any
from unittest import mock

# Records Beget puts on a new subdomain created by domain/addSubdomainVirtual.
DEFAULT_SUBDOMAIN_RECORDS = {
    'A': [{'ttl': 300, 'address': '192.0.2.1'}],
    'TXT': [{'ttl': 300, 'txtdata': 'v=spf1 redirect=beget.com'}],
    'MX': [
        {'ttl': 300, 'exchange': 'mx1.beget.com.', 'preference': 10},
        {'ttl': 300, 'exchange': 'mx2.beget.com.', 'preference': 20},
    ],
}

# dns/changeRecords sets this TTL on every record it writes.
CHANGED_RECORD_TTL = 600


class MethodFailed(Exception):
    """Makes the fake answer with a METHOD_FAILED error."""

    def __init__(self, error_text: Any) -> None:
        super().__init__(error_text)
        self.error_text = error_text


class FakeBeget:
    """Behaves like ``requests.Session.post`` against https://api.beget.com/api/."""

    def __init__(self, login: str = 'user', password: str = 'secret') -> None:
        self.login = login
        self.password = password
        self._ids = itertools.count(1000)
        self.domains: dict[int, str] = {}
        self.subdomains: dict[int, tuple[str, int]] = {}
        # fqdn -> records in the raw format dns/getData really returns
        self.records: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self.set_types: dict[str, int] = {}
        self.create_www_alias = False
        # Delete the "www." alias together with its subdomain.
        self.cascade_www_alias = False
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.fail_methods: dict[str, dict[str, Any]] = {}

    def add_domain(self, fqdn: str) -> int:
        domain_id = next(self._ids)
        self.domains[domain_id] = fqdn
        self.records[fqdn] = {'A': [{'ttl': 600, 'address': '192.0.2.1'}]}
        return domain_id

    def add_subdomain(self, fqdn: str, domain_id: int) -> int:
        subdomain_id = next(self._ids)
        self.subdomains[subdomain_id] = (fqdn, domain_id)
        self.records[fqdn] = {'A': [{'ttl': 600, 'address': '192.0.2.1'}]}
        return subdomain_id

    def txt_values(self, fqdn: str) -> list[str]:
        return [r['txtdata'] for r in self.records.get(fqdn, {}).get('TXT', [])]

    def __call__(self, url: str, data: dict[str, Any], timeout: int) -> mock.Mock:
        method = url.split('/api/', 1)[1]
        if data.get('input_format') == 'json' and 'input_data' not in data:
            # The real API answers with plain text here.
            return self._text_response('Cannot parse the JSON input params')
        args = json.loads(data['input_data']) if 'input_data' in data else {}
        self.calls.append((url, data, args))

        if data['login'] != self.login or data['passwd'] != self.password:
            return self._response(
                {'status': 'error', 'error_text': 'Auth failed', 'error_code': 'AUTH_ERROR'}
            )
        if method in self.fail_methods:
            return self._response(self.fail_methods[method])

        try:
            result = getattr(self, '_' + method.replace('/', '_'))(**args)
        except MethodFailed as e:
            return self._response(
                {
                    'status': 'success',
                    'answer': {
                        'status': 'error',
                        'errors': [{'error_code': 'METHOD_FAILED', 'error_text': e.error_text}],
                    },
                }
            )
        return self._response(
            {'status': 'success', 'answer': {'status': 'success', 'result': result}}
        )

    @staticmethod
    def _response(body: dict[str, Any]) -> mock.Mock:
        response = mock.Mock()
        response.json.return_value = body
        response.text = json.dumps(body)
        return response

    @staticmethod
    def _text_response(text: str) -> mock.Mock:
        response = mock.Mock()
        response.json.side_effect = json.JSONDecodeError('Expecting value', text, 0)
        response.text = text
        return response

    def _domain_getList(self) -> list[dict[str, Any]]:
        return [{'id': i, 'fqdn': f} for i, f in self.domains.items()]

    def _domain_getSubdomainList(self) -> list[dict[str, Any]]:
        return [{'id': i, 'fqdn': f, 'domain_id': d} for i, (f, d) in self.subdomains.items()]

    def _domain_addSubdomainVirtual(self, subdomain: str, domain_id: int) -> int:
        if domain_id not in self.domains:
            raise MethodFailed('Failed to add subdomain')
        fqdn = f'{subdomain}.{self.domains[domain_id]}'
        subdomain_id = self.add_subdomain(fqdn, domain_id)
        self.records[fqdn] = json.loads(json.dumps(DEFAULT_SUBDOMAIN_RECORDS))
        if self.create_www_alias:
            self.add_subdomain('www.' + fqdn, domain_id)
        return subdomain_id

    def _domain_deleteSubdomain(self, id: int) -> bool:  # pylint: disable=redefined-builtin
        if id not in self.subdomains:
            raise MethodFailed('Failed to delete subdomain')
        fqdn, _ = self.subdomains.pop(id)
        del self.records[fqdn]
        if self.cascade_www_alias:
            for alias_id, (alias, _) in list(self.subdomains.items()):
                if alias == 'www.' + fqdn:
                    self._domain_deleteSubdomain(alias_id)
        return True

    def _dns_getData(self, fqdn: str) -> dict[str, Any]:
        if fqdn not in self.records:
            raise MethodFailed('Failed to get DNS records')
        return {
            'fqdn': fqdn,
            'set_type': self.set_types.get(fqdn, 1),
            'records': {'DNS': [], 'DNS_IP': [], **self.records[fqdn]},
        }

    def _dns_changeRecords(self, fqdn: str, records: dict[str, Any]) -> bool:
        if fqdn not in self.records:
            raise MethodFailed('Failed to change DNS records')
        ttl = CHANGED_RECORD_TTL
        raw: dict[str, list[dict[str, Any]]] = {}
        for record_type, entries in records.items():
            for entry in entries:
                assert set(entry) == {'priority', 'value'}, entry
            if record_type in ('A', 'AAAA'):
                raw[record_type] = [{'ttl': ttl, 'address': e['value']} for e in entries]
            elif record_type == 'MX':
                raw['MX'] = [
                    {'ttl': ttl, 'exchange': e['value'] + '.', 'preference': e['priority']}
                    for e in entries
                ]
            elif record_type == 'TXT':
                if any(e['value'] == '' for e in entries):
                    raise MethodFailed(
                        {
                            'type': 'INVALID_DATA_SINGLE',
                            'message': [
                                {'code': 15, 'errorText': 'Empty txt record'},
                                {
                                    'code': 17,
                                    'errorText': 'Value must contain only printable '
                                    'characters, not control',
                                },
                            ],
                        }
                    )
                raw['TXT'] = [{'ttl': ttl, 'txtdata': e['value']} for e in entries]
            else:
                raise AssertionError(f'unexpected record type {record_type}')
        self.records[fqdn] = raw
        return True
