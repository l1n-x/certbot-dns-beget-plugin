"""DNS Authenticator for Beget."""

import logging
from collections.abc import Callable
from typing import Any

from certbot import errors
from certbot.plugins import dns_common
from certbot.plugins.dns_common import CredentialsConfiguration

from certbot_dns_beget_plugin.client import BegetClient

logger = logging.getLogger(__name__)


class Authenticator(dns_common.DNSAuthenticator):
    """DNS Authenticator for Beget

    This Authenticator uses the Beget API to fulfill a dns-01 challenge.
    """

    description = 'Obtain certificates using a DNS TXT record (if you are using Beget for DNS).'

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.credentials: CredentialsConfiguration | None = None
        self._client: BegetClient | None = None

    @classmethod
    def add_parser_arguments(
        cls, add: Callable[..., None], default_propagation_seconds: int = 120
    ) -> None:
        super().add_parser_arguments(add, default_propagation_seconds)
        add('credentials', help='Beget credentials INI file.')

    def more_info(self) -> str:
        return (
            'This plugin configures a DNS TXT record to respond to a dns-01 challenge using '
            'the Beget API.'
        )

    def _validate_credentials(self, credentials: CredentialsConfiguration) -> None:
        if not credentials.conf('username') or not credentials.conf('password'):
            raise errors.PluginError(
                f'{credentials.confobj.filename}: dns_beget_plugin_username and '
                'dns_beget_plugin_password are required. Enable API access and set an API '
                'password in the Beget control panel.'
            )

    def _setup_credentials(self) -> None:
        self.credentials = self._configure_credentials(
            'credentials',
            'Beget credentials INI file',
            {
                'username': 'Beget account login',
                'password': 'Beget API password',
            },
            self._validate_credentials,
        )

    def _perform(self, domain: str, validation_name: str, validation: str) -> None:
        self._get_beget_client().add_txt_record(validation_name, validation)

    def _cleanup(self, domain: str, validation_name: str, validation: str) -> None:
        self._get_beget_client().del_txt_record(validation_name, validation)

    def _get_beget_client(self) -> BegetClient:
        if not self.credentials:
            raise errors.Error('Plugin has not been prepared.')

        if self._client is None:
            self._client = BegetClient(
                self.credentials.conf('username') or '',
                self.credentials.conf('password') or '',
            )
        return self._client
