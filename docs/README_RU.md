# certbot-dns-beget-plugin

[![CI](https://github.com/l1n-x/certbot-dns-beget-plugin/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/l1n-x/certbot-dns-beget-plugin/actions/workflows/ci.yml)

[EN](../README.md) | **RU**

Плагин для [Certbot](https://certbot.eff.org/), который получает сертификаты Let's Encrypt через DNS-проверку (dns-01) для доменов, обслуживаемых DNS [Beget](https://beget.com/). TXT-запись `_acme-challenge` создаётся и удаляется автоматически через [API Beget](https://beget.com/ru/kb/api/obshhij-princzip-raboty-s-api).

DNS-проверка позволяет получать wildcard-сертификаты (`*.example.com`) и не требует открытого 80-го порта.

## Установка

Плагин должен быть установлен в то же окружение Python, что и Certbot.

```bash
pip install certbot-dns-beget-plugin
```

Если Certbot установлен в виртуальное окружение, как в
[инструкции EFF для pip](https://certbot.eff.org/instructions?ws=other&os=pip), используйте pip
из этого окружения:

```bash
sudo /opt/certbot/bin/pip install certbot-dns-beget-plugin
```

> **Важно:** Certbot, установленный через **snap**, не видит плагины, установленные через pip: плагины
> для snap распространяются отдельными snap-пакетами. То же относится к Certbot из пакетов
> дистрибутива (`apt`, `dnf`): современные дистрибутивы не дают pip устанавливать пакеты в
> системный Python. В обоих случаях установите Certbot через pip в виртуальное окружение по
> инструкции выше.

Версию в разработке можно установить прямо с GitHub:

```bash
pip install git+https://github.com/l1n-x/certbot-dns-beget-plugin
```

Убедитесь, что Certbot видит плагин:

```bash
certbot plugins
# * dns-beget-plugin
# Description: Obtain certificates using a DNS TXT record (if you are using Beget for DNS).
```

## Настройка

1. В панели управления Beget откройте раздел **API**, включите доступ к API и задайте пароль для API.
2. Создайте файл с учётными данными, например `/etc/letsencrypt/beget.ini`:

   ```ini
   dns_beget_plugin_username = ваш_логин_beget
   dns_beget_plugin_password = пароль_для_api
   ```

3. Ограничьте доступ к файлу:

   ```bash
   chmod 600 /etc/letsencrypt/beget.ini
   ```

## Использование

```bash
certbot certonly \
  --authenticator dns-beget-plugin \
  --dns-beget-plugin-credentials /etc/letsencrypt/beget.ini \
  -d example.com \
  -d '*.example.com'
```

| Параметр | Описание |
|---|---|
| `--dns-beget-plugin-credentials` | Путь к INI-файлу с учётными данными (обязательный). |
| `--dns-beget-plugin-propagation-seconds` | Сколько секунд ждать распространения DNS-записи перед проверкой. По умолчанию `120`. |

## Продление

Certbot сохраняет параметры плагина в `/etc/letsencrypt/renewal/<домен>.conf`, поэтому
`certbot renew` использует тот же плагин и файл учётных данных без дополнительных аргументов:

```ini
authenticator = dns-beget-plugin
dns_beget_plugin_credentials = /etc/letsencrypt/beget.ini
```

Не перемещайте файл учётных данных: он должен остаться по пути, указанному при получении
сертификата. Проверьте, что продление работает:

```bash
sudo certbot renew --dry-run
```

Если Certbot установлен в `/opt/certbot` по
[инструкции EFF для pip](https://certbot.eff.org/instructions?ws=other&os=pip), продление
автоматически не настраивается. Добавьте задание cron, которое запускается дважды в день в
случайную минуту:

```bash
echo "0 0,12 * * * root /opt/certbot/bin/python -c 'import random; import time; time.sleep(random.random() * 3600)' && /opt/certbot/bin/certbot renew -q" | sudo tee -a /etc/crontab > /dev/null
```

Чтобы перезагружать веб-сервер после продления сертификата, положите скрипт в
`/etc/letsencrypt/renewal-hooks/deploy/`:

```bash
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh > /dev/null <<'SH'
#!/bin/sh
systemctl reload nginx
SH
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

## Как это работает

- Если поддомена `_acme-challenge.<домен>` на аккаунте нет, плагин создаёт его, а после проверки удаляет вместе с записями.
- Если поддомен уже есть, плагин добавляет к нему TXT-запись и после проверки удаляет только её. Существующие A, AAAA, MX и TXT-записи сохраняются, но API Beget при этом сбрасывает их TTL на 600 секунд.
- Плагин откажется менять записи, если имя делегировано через NS или CNAME, или если на нём есть записи других типов, которые API Beget не позволяет сохранить.

## Ограничения

- Новые записи обычно появляются на DNS-серверах Beget в течение минуты, поэтому стандартного ожидания в 120 секунд хватает с запасом. Если проверка не проходит из-за того, что запись не найдена, увеличьте `--dns-beget-plugin-propagation-seconds`.
- API Beget умеет только заменять все записи имени сразу. Не запускайте несколько процессов Certbot для одного домена одновременно: они могут перезаписать TXT-записи друг друга, и проверка не пройдёт.

## Разработка

Как настроить проект, запустить тесты и выпустить версию, описано в [CONTRIBUTING.md](../CONTRIBUTING.md) (на английском).

## Благодарности

Проект основан на [certbot-dns-beget-api](https://github.com/Medan-rfz/certbot-dns-beget-api) от Medan-rfz (MIT License).

## Лицензия

[MIT](../LICENSE)
