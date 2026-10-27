# Contributing

Bug reports and pull requests are welcome. For larger changes, please open an issue first to
discuss what you would like to change.

## Setup

Install the project together with the development tools (pytest, pytest-cov, Ruff):

```bash
poetry install
```

Or with pip (requires pip 25.1 or newer):

```bash
pip install -e . --group dev
```

## Checks

Prefix each command with `poetry run` when using Poetry:

```bash
ruff check            # lint
ruff format           # format the code
pytest                # tests with a coverage report, 90% threshold
```

CI runs the same checks on Python 3.10–3.14 and against the minimum supported versions of
Certbot and requests.

## Tests

Unit tests talk to `tests/fake_beget.py`, an in-memory imitation of the Beget API. Its response
formats follow what the real API returns, which is not always what the Beget documentation
says. If you find a difference, update the fake together with the code.

### Integration tests

`tests/integration_test.py` runs against the real Beget API and changes DNS records on the
account, so it is skipped unless started by hand with a credentials file in the same format as
for Certbot:

```bash
BEGET_CREDENTIALS=beget.ini BEGET_TEST_DOMAIN=example.com pytest tests/integration_test.py
```

The tests only create subdomains with random names under `BEGET_TEST_DOMAIN` and delete them
afterwards. `beget.ini` in the project root is ignored by git; keep real credentials out of
commits.

## Changelog

Describe user-visible changes in the `Unreleased` section of `CHANGELOG.md`.

## Releasing

1. Update `version` in `pyproject.toml` and turn the `Unreleased` section of `CHANGELOG.md`
   into a section for that version.
2. Commit, then push a tag with the same version:

   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

The `Release` workflow runs the checks, makes sure the tag matches the version, and publishes
the package to PyPI.
