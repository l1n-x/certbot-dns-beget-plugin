"""Thin client for the parts of the Beget hosting API used by the plugin.

API reference:
  * https://beget.com/ru/kb/api/obshhij-princzip-raboty-s-api
  * https://beget.com/ru/kb/api/funkczii-dlya-raboty-s-domenami
  * https://beget.com/ru/kb/api/funkczii-upravleniya-dns
"""

import json
import logging
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import requests
from certbot import errors
from certbot.plugins import dns_common

logger = logging.getLogger(__name__)

BASE_API_URL = 'https://api.beget.com/api/'
DEFAULT_TIMEOUT = 30

# dns/getData "set_type": 1 means the name is served by A/AAAA/MX/TXT records.
# 2 (NS) and 3 (CNAME) delegate the name elsewhere, so a TXT record cannot be added.
SET_TYPE_BASIC = 1

# Record group accepted by dns/changeRecords together with TXT. The whole group is
# replaced on every call, so every record of these types must be sent back.
BASIC_RECORD_TYPES = ('A', 'AAAA', 'MX', 'TXT')

# Record types reported by dns/getData that do not belong to the basic group and
# must not be sent back in it.
IGNORED_RECORD_TYPES = ('DNS', 'DNS_IP')

# dns/getData is documented to return {"value", "priority"}, but in practice it returns
# the raw zone fields. Map those to the {"value", "priority"} form changeRecords accepts.
_VALUE_KEYS = ('value', 'address', 'txtdata', 'exchange')
_PRIORITY_KEYS = ('priority', 'preference')


class BegetApiError(errors.PluginError):
    """Error reported by the Beget API or raised while talking to it."""


@dataclass
class _Challenge:
    """Plugin state for a single validation name."""

    fqdn: str
    # Subdomain ids created by the plugin and therefore removed on cleanup.
    created_subdomain_ids: list[int] = field(default_factory=list)
    # TXT values added by the plugin that are not cleaned up yet.
    pending_values: list[str] = field(default_factory=list)


class BegetClient:
    """Encapsulates all communication with the Beget API."""

    def __init__(self, login: str, password: str, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._login = login
        self._password = password
        self._timeout = timeout
        self._session = requests.Session()
        self._domains: dict[str, int] | None = None
        self._challenges: dict[str, _Challenge] = {}

    def add_txt_record(self, record_name: str, record_content: str) -> None:
        """
        Add a TXT record, creating the subdomain that holds it if necessary.

        :param str record_name: The record name (typically beginning with '_acme-challenge.').
        :param str record_content: The record content (typically the challenge validation).
        :raises certbot.errors.PluginError: if an error occurs communicating with the Beget API
        """
        fqdn = _normalize(record_name)
        challenge = self._challenges.setdefault(fqdn, _Challenge(fqdn))

        if not challenge.created_subdomain_ids:
            subdomains = self._list_subdomains()
            if not any(_normalize(s['fqdn']) == fqdn for s in subdomains):
                self._create_subdomain(challenge, subdomains)

        records = self._get_basic_records(fqdn)
        txt_records = records.setdefault('TXT', [])
        if any(r['value'] == record_content for r in txt_records):
            logger.debug('TXT record %s with this value already exists', fqdn)
        else:
            txt_records.append({'priority': _next_priority(txt_records), 'value': record_content})
            self._change_records(fqdn, records)
            logger.debug('Added TXT record to %s', fqdn)

        challenge.pending_values.append(record_content)

    def del_txt_record(self, record_name: str, record_content: str) -> None:
        """
        Delete a TXT record added by :meth:`add_txt_record`.

        Removes only the record with the given content. If the plugin created the
        subdomain and no other challenge still uses it, the subdomain is deleted.

        Failures are logged, but not raised.

        :param str record_name: The record name (typically beginning with '_acme-challenge.').
        :param str record_content: The record content (typically the challenge validation).
        """
        fqdn = _normalize(record_name)
        challenge = self._challenges.get(fqdn)
        if challenge is None:
            logger.debug('No TXT record for %s was added by this run, nothing to clean up', fqdn)
            return

        # The value is not pending if add_txt_record failed before adding it.
        added = record_content in challenge.pending_values
        if added:
            challenge.pending_values.remove(record_content)

        try:
            if challenge.created_subdomain_ids and not challenge.pending_values:
                # Deleting the subdomain also deletes its records. Aliases go first in
                # case Beget removes them together with the subdomain itself.
                while challenge.created_subdomain_ids:
                    subdomain_id = challenge.created_subdomain_ids[-1]
                    self._call('domain/deleteSubdomain', {'id': subdomain_id})
                    challenge.created_subdomain_ids.pop()
                del self._challenges[fqdn]
                logger.debug('Deleted subdomain %s', fqdn)
                return

            if not added:
                logger.debug('TXT record %s was not added, nothing to clean up', fqdn)
                return

            if record_content in challenge.pending_values:
                logger.debug('TXT record %s with this value is still in use', fqdn)
                return

            records = self._get_basic_records(fqdn)
            txt_records = records.get('TXT', [])
            remaining = [r for r in txt_records if r['value'] != record_content]
            if len(remaining) != len(txt_records):
                records['TXT'] = remaining
                self._change_records(fqdn, records)
                logger.debug('Deleted TXT record from %s', fqdn)
        except errors.PluginError as e:
            logger.warning('Failed to clean up TXT record %s: %s', fqdn, e)

    def _find_domain(self, fqdn: str) -> tuple[str, int]:
        """Find the account domain the name belongs to, preferring the longest match."""
        if self._domains is None:
            self._domains = {
                _normalize(d['fqdn']): int(d['id']) for d in self._call('domain/getList') or []
            }

        for guess in dns_common.base_domain_name_guesses(fqdn):
            if guess != fqdn and guess in self._domains:
                return guess, self._domains[guess]

        raise errors.PluginError(
            f'Unable to find a domain for {fqdn} on the Beget account '
            f'(domains on the account: {", ".join(sorted(self._domains)) or "none"})'
        )

    def _list_subdomains(self) -> list[dict[str, Any]]:
        return self._call('domain/getSubdomainList') or []

    def _create_subdomain(self, challenge: _Challenge, existing: list[dict[str, Any]]) -> None:
        """Create the subdomain and record ids of every subdomain it brought along."""
        fqdn = challenge.fqdn
        domain, domain_id = self._find_domain(fqdn)
        before = {int(s['id']) for s in existing}

        subdomain_id = int(
            self._call(
                'domain/addSubdomainVirtual',
                {
                    'subdomain': fqdn[: -len(domain) - 1],
                    'domain_id': domain_id,
                },
            )
        )
        # Record the id right away so that cleanup removes the subdomain even if
        # the calls below fail.
        challenge.created_subdomain_ids.append(subdomain_id)
        logger.debug('Created subdomain %s (id %d)', fqdn, subdomain_id)

        # Beget may create a "www." alias along with the subdomain; it has to go too.
        for s in self._list_subdomains():
            sid = int(s['id'])
            if (
                sid not in before
                and sid != subdomain_id
                and _normalize(s['fqdn']) in (fqdn, 'www.' + fqdn)
            ):
                challenge.created_subdomain_ids.append(sid)

    def _get_basic_records(self, fqdn: str) -> dict[str, list[dict[str, Any]]]:
        """Return the current A/AAAA/MX/TXT records of a name in the changeRecords format."""
        data = self._call('dns/getData', {'fqdn': fqdn})

        set_type = int(data.get('set_type') or SET_TYPE_BASIC)
        if set_type != SET_TYPE_BASIC:
            raise errors.PluginError(
                f'{fqdn} is configured with NS or CNAME records on Beget, '
                'a TXT record cannot be added to it'
            )

        records: dict[str, list[dict[str, Any]]] = {}
        for record_type, entries in (data.get('records') or {}).items():
            if record_type in IGNORED_RECORD_TYPES or not entries:
                continue
            if record_type not in BASIC_RECORD_TYPES:
                # changeRecords replaces the whole record set. Sending it without this
                # type could delete it, so refuse rather than risk losing records.
                raise errors.PluginError(
                    f'{fqdn} has {record_type} records that this plugin cannot preserve; '
                    'refusing to modify the DNS records'
                )
            converted = [_to_change_format(record_type, e) for e in entries]
            # getData reports a name without records of a type as one record with an
            # empty value. Sending it back would create an empty record.
            converted = [r for r in converted if r['value'] != '']
            if not converted:
                continue
            if record_type != 'MX':
                # Only MX priorities carry meaning. getData usually omits priorities for
                # other types, so number them to keep them unique as the API requires.
                for i, record in enumerate(converted, 1):
                    record['priority'] = i * 10
            records[record_type] = converted
        return records

    def _change_records(self, fqdn: str, records: dict[str, list[dict[str, Any]]]) -> None:
        records = {k: v for k, v in records.items() if v}
        if not self._call('dns/changeRecords', {'fqdn': fqdn, 'records': records}):
            raise BegetApiError(f'Beget API refused to change DNS records of {fqdn}')

    def _call(self, method: str, data: dict[str, Any] | None = None) -> Any:
        """
        Call an API method and return its "result".

        Credentials are sent in the POST body, never in the URL, so they do not end up
        in certbot's debug log.
        """
        payload = {
            'login': self._login,
            'passwd': self._password,
            'input_format': 'json',
            'output_format': 'json',
            # With input_format=json the API answers "Cannot parse the JSON input params"
            # in plain text if input_data is missing, even for methods without arguments.
            'input_data': json.dumps(data or {}),
        }

        try:
            response = self._session.post(
                BASE_API_URL + method, data=payload, timeout=self._timeout
            )
            response.raise_for_status()
        except requests.RequestException as e:
            raise BegetApiError(f'Error communicating with the Beget API ({method}): {e}') from e

        try:
            body = response.json()
        except ValueError as e:
            raise BegetApiError(
                f'Beget API returned a non-JSON response ({method}): '
                f'{response.text.strip()[:200]!r}'
            ) from e

        if not isinstance(body, dict):
            raise BegetApiError(f'Beget API returned an unexpected response ({method}): {body!r}')

        if body.get('status') != 'success':
            raise BegetApiError(
                f'Beget API error ({method}): {body.get("error_text") or "unknown error"} '
                f'[{body.get("error_code") or "?"}]'
            )

        answer = body.get('answer')
        if not isinstance(answer, dict):
            answer = {}
        if answer.get('status') != 'success':
            details = (
                '; '.join(
                    f'{_error_text(e)} [{e.get("error_code")}]' for e in answer.get('errors') or []
                )
                or 'unknown error'
            )
            raise BegetApiError(f'Beget API method {method} failed: {details}')

        return answer.get('result')


def _normalize(name: str) -> str:
    return name.rstrip('.').lower()


def _error_text(error: dict[str, Any]) -> str:
    """
    Return the text of an API error.

    dns/changeRecords reports validation errors as an object, e.g.
    {"type": "INVALID_DATA_SINGLE", "message": [{"errorText": "Empty txt record", ...}]}.
    """
    text = error.get('error_text')
    if isinstance(text, dict):
        messages = [m.get('errorText') for m in text.get('message') or [] if isinstance(m, dict)]
        return '; '.join(str(m) for m in messages if m) or str(text.get('type') or text)
    return str(text)


def _to_change_format(record_type: str, entry: dict[str, Any]) -> dict[str, Any]:
    value = next((entry[k] for k in _VALUE_KEYS if entry.get(k) is not None), None)
    priority = next((entry[k] for k in _PRIORITY_KEYS if entry.get(k) is not None), 0)
    if value is None:
        raise errors.PluginError(f'Unrecognized {record_type} record format: {entry!r}')
    if record_type == 'MX':
        value = str(value).rstrip('.')
    return {'priority': int(priority), 'value': value}


def _next_priority(records: list[dict[str, Any]]) -> int:
    return max((r['priority'] for r in records), default=0) + 10
