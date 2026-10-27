# certbot-dns-beget-plugin

[![CI](https://github.com/l1n-x/certbot-dns-beget-plugin/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/l1n-x/certbot-dns-beget-plugin/actions/workflows/ci.yml)

**EN** | [RU](https://github.com/l1n-x/certbot-dns-beget-plugin/blob/master/docs/README_RU.md)

A [Certbot](https://certbot.eff.org/) plugin that obtains Let's Encrypt certificates using the DNS challenge (dns-01) for domains served by [Beget](https://beget.com/) DNS. The `_acme-challenge` TXT record is created and removed automatically through the [Beget API](https://beget.com/ru/kb/api/obshhij-princzip-raboty-s-api).

The DNS challenge lets you obtain wildcard certificates (`*.example.com`) and does not require port 80 to be open.

## Installation

The plugin must be installed into the same Python environment as Certbot.

```bash
pip install certbot-dns-beget-plugin
```

If Certbot was installed into a virtual environment, as in the
[EFF pip instructions](https://certbot.eff.org/instructions?ws=other&os=pip), use that
environment's pip:

```bash
sudo /opt/certbot/bin/pip install certbot-dns-beget-plugin
```

> **Note:** Certbot installed with **snap** does not see plugins installed with pip: snap plugins have to
> be packaged as separate snaps. The same goes for Certbot from distribution packages (`apt`,
> `dnf`): modern distributions do not let pip install into the system Python. In both cases,
> install Certbot with pip into a virtual environment using the instructions above.

The latest development version can be installed straight from GitHub:

```bash
pip install git+https://github.com/l1n-x/certbot-dns-beget-plugin
```

Check that Certbot sees the plugin:

```bash
certbot plugins
# * dns-beget-plugin
# Description: Obtain certificates using a DNS TXT record (if you are using Beget for DNS).
```

## Configuration

1. In the Beget control panel, open the **API** section, enable API access and set an API password.
2. Create a credentials file, for example `/etc/letsencrypt/beget.ini`:

   ```ini
   dns_beget_plugin_username = your_beget_login
   dns_beget_plugin_password = your_api_password
   ```

3. Restrict access to the file:

   ```bash
   chmod 600 /etc/letsencrypt/beget.ini
   ```

## Usage

```bash
certbot certonly \
  --authenticator dns-beget-plugin \
  --dns-beget-plugin-credentials /etc/letsencrypt/beget.ini \
  -d example.com \
  -d '*.example.com'
```

| Option | Description |
|---|---|
| `--dns-beget-plugin-credentials` | Path to the INI file with credentials (required). |
| `--dns-beget-plugin-propagation-seconds` | Seconds to wait for the DNS record to propagate before validation. Default: `120`. |

## Renewal

Certbot saves the plugin options in `/etc/letsencrypt/renewal/<domain>.conf`, so `certbot renew`
uses the same plugin and credentials file without extra arguments:

```ini
authenticator = dns-beget-plugin
dns_beget_plugin_credentials = /etc/letsencrypt/beget.ini
```

Keep the credentials file at the path given when the certificate was obtained. Check that renewal
works:

```bash
sudo certbot renew --dry-run
```

If Certbot is installed in `/opt/certbot` as in the
[EFF pip instructions](https://certbot.eff.org/instructions?ws=other&os=pip), renewal is not
scheduled automatically. Add a cron job that tries twice a day at a random minute:

```bash
echo "0 0,12 * * * root /opt/certbot/bin/python -c 'import random; import time; time.sleep(random.random() * 3600)' && /opt/certbot/bin/certbot renew -q" | sudo tee -a /etc/crontab > /dev/null
```

To reload the web server after a certificate is renewed, put a script into
`/etc/letsencrypt/renewal-hooks/deploy/`:

```bash
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh > /dev/null <<'SH'
#!/bin/sh
systemctl reload nginx
SH
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

## How it works

- If the `_acme-challenge.<domain>` subdomain does not exist on the account, the plugin creates it and deletes it, together with its records, after validation.
- If the subdomain already exists, the plugin adds a TXT record to it and removes only that record after validation. Existing A, AAAA, MX and TXT records are preserved, although the Beget API resets their TTL to 600 seconds.
- The plugin refuses to change records if the name is delegated via NS or CNAME, or if it has records of other types that the Beget API cannot preserve.

## Limitations

- New records usually appear on the Beget name servers within a minute, so the default 120-second wait leaves some margin. If validation fails because the record is not found, increase `--dns-beget-plugin-propagation-seconds`.
- The Beget API can only replace all records of a name at once. Do not run several Certbot processes for the same domain at the same time: they can overwrite each other's TXT records, and validation will fail.

## Development

See [CONTRIBUTING.md](https://github.com/l1n-x/certbot-dns-beget-plugin/blob/master/CONTRIBUTING.md) for setting up the project, running the tests and releasing.

## Acknowledgements

Based on [certbot-dns-beget-api](https://github.com/Medan-rfz/certbot-dns-beget-api) by Medan-rfz (MIT License).

## License

[MIT](https://github.com/l1n-x/certbot-dns-beget-plugin/blob/master/LICENSE)
