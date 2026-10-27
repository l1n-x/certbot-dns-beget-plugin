import os
from unittest import mock

from certbot import errors
from certbot.plugins import dns_test_common
from certbot.plugins.dns_test_common import DOMAIN
from certbot.tests import util as test_util

from certbot_dns_beget_plugin.authenticator import Authenticator
from certbot_dns_beget_plugin.client import BegetClient


class AuthenticatorTest(test_util.TempDirTestCase, dns_test_common.BaseAuthenticatorTest):
    def setUp(self) -> None:
        super().setUp()

        path = os.path.join(self.tempdir, 'file.ini')
        dns_test_common.write(
            {'dns_beget_plugin_username': 'user', 'dns_beget_plugin_password': 'secret'}, path
        )

        self.config = mock.MagicMock(
            dns_beget_plugin_credentials=path, dns_beget_plugin_propagation_seconds=0
        )  # don't wait during tests
        self.auth = Authenticator(self.config, 'dns-beget-plugin')

        self.mock_client = mock.MagicMock()
        # _get_beget_client | pylint: disable=protected-access
        self.auth._get_beget_client = mock.MagicMock(return_value=self.mock_client)

    @test_util.patch_display_util()
    def test_perform(self, unused_mock_get_utility: mock.MagicMock) -> None:
        self.auth.perform([self.achall])

        expected = [mock.call.add_txt_record('_acme-challenge.' + DOMAIN, mock.ANY)]
        self.assertEqual(expected, self.mock_client.mock_calls)

    def test_cleanup(self) -> None:
        # _attempt_cleanup | pylint: disable=protected-access
        self.auth._attempt_cleanup = True
        self.auth.cleanup([self.achall])

        expected = [mock.call.del_txt_record('_acme-challenge.' + DOMAIN, mock.ANY)]
        self.assertEqual(expected, self.mock_client.mock_calls)

    @test_util.patch_display_util()
    def test_missing_password(self, unused_mock_get_utility: mock.MagicMock) -> None:
        dns_test_common.write(
            {'dns_beget_plugin_username': 'user'}, self.config.dns_beget_plugin_credentials
        )

        with self.assertRaises(errors.PluginError):
            self.auth.perform([self.achall])

    def test_default_propagation_seconds(self) -> None:
        add = mock.MagicMock()
        Authenticator.add_parser_arguments(add)

        add.assert_any_call('propagation-seconds', type=int, default=120, help=mock.ANY)

    def test_client_is_created_from_credentials(self) -> None:
        auth = Authenticator(self.config, 'dns-beget-plugin')
        auth._setup_credentials()

        client = auth._get_beget_client()

        self.assertIsInstance(client, BegetClient)
        self.assertEqual(client._login, 'user')
        self.assertEqual(client._password, 'secret')
        self.assertIs(client, auth._get_beget_client())

    def test_client_requires_prepared_plugin(self) -> None:
        auth = Authenticator(self.config, 'dns-beget-plugin')

        with self.assertRaises(errors.Error):
            auth._get_beget_client()
