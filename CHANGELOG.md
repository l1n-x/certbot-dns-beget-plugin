# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - Unreleased

First release, based on [certbot-dns-beget-api](https://github.com/Medan-rfz/certbot-dns-beget-api).

### Added

- `dns-beget-plugin` authenticator for Certbot 2.0 and newer that completes the dns-01
  challenge through the Beget API, including wildcard certificates.
- Creates the `_acme-challenge` subdomain when it does not exist and deletes it after
  validation.
- Adds a TXT record to an existing subdomain without losing its A, AAAA, MX and TXT records,
  and removes only that record after validation.
- Refuses to change names delegated via NS or CNAME and names with records the Beget API
  cannot preserve.
- Readable error messages for Beget API errors, including validation errors.

[1.0.0]: https://github.com/l1n-x/certbot-dns-beget-plugin/releases/tag/v1.0.0
