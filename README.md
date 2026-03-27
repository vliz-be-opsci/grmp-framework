# GRMP Framework

A Docker-based test orchestration system that runs test containers in isolation, collects their JUnit XML reports, and combines them into a single output file.

## Overview

The orchestrator reads test configurations from YAML files, pulls and runs test containers via the Docker API, and combines their individual JUnit XML reports into a single `combined_report.xml`.

The orchestrator is intentionally minimal in scope. It is responsible for:

- Reading and merging test configuration YAML files
- Pulling and running test containers
- Translating config parameters into environment variables for each container
- Collecting and combining JUnit XML reports

It is **not** responsible for:

- Deciding what constitutes a test pass or failure — that is the test container's responsibility
- Validating the contents of test reports — it trusts the containers to produce valid JUnit XML
- Retry logic for failed tests
- Creating GitHub issues, pushing reports to branches, or any other CI/CD workflow logic

Test implementations can be found [here](https://github.com/vliz-be-opsci/grmp-test-implementations).

---

## Quick Start

### Local Deployment

```bash
docker-compose up
```

A minimal `docker-compose.yml` should mount a config directory and a reports directory:

```yaml
services:
  orchestrator:
    image: ghcr.io/vliz-be-opsci/grmp-framework:main
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./my-config:/config:ro
      - ./reports:/reports:rw
    environment:
      - REPORTS_HOST_PATH=./reports
```

Example YAML configuration files are provided in `/config`.

---

## Configuration

The orchestrator recursively scans its config directory for all `.yaml` and `.yml` files and merges them into a single combined configuration. Each file may define one or more named tests under a `tests:` key.

### Example configuration file

```yaml
tests:
  my-resource-check:
    image: ghcr.io/vliz-be-opsci/grmp-tests/resource-availability:latest
    config:
      urls:
        - https://example.com
      timeout: 10
      check-https-availability: true

  my-cert-check:
    image: ghcr.io/vliz-be-opsci/grmp-tests/check-certificate:latest
    config:
      urls:
        - https://example.com
      certificate-expiry-days: 30
      api-key: !secret my_api_key
```

### Config parameters

| Parameter | Description |
| --- | --- |
| `image` | (required) Docker image for the test container |
| `create-issue` | Passed to the container as `SPECIAL_CREATE_ISSUE` — intended for use by downstream workflow tooling (default: `false`) |
| All other parameters | Passed to the container as `TEST_*` environment variables |

### Duplicate test names

If the same test name appears in multiple YAML files it is automatically renamed to `name(2)`, `name(3)` etc. with a warning. Names are treated as opaque strings — `my-test-2` is not considered a variant of `my-test`.

---

## Environment Variables

### Variables the orchestrator reads

| Variable | Description |
| --- | --- |
| `CONFIG_DIR` | Path to the config directory (default: `/config`) |
| `REPORTS_HOST_PATH` | Host path of the reports directory, used for Docker volume mounts. If not set, the orchestrator attempts to detect it from its own container mounts, falling back to the absolute path of the reports directory |
| `SECRET_*` | Secrets to be forwarded to test containers (see [Secrets](#secrets)) |

The orchestrator also reads the following variables when running in a GitHub Actions environment, using them to construct full provenance URLs (see [Provenance](#provenance)):

| Variable | Description |
| --- | --- |
| `GITHUB_SERVER_URL` | GitHub server URL (e.g. `https://github.com`) |
| `GITHUB_REPOSITORY` | Repository in `owner/repo` format |
| `GITHUB_SHA` | The commit SHA of the current run |
| `CONFIG_DIRECTORY` | The repo-relative path of the mounted config directory |

### Variables passed to test containers

| Variable | Description |
| --- | --- |
| `TS_NAME` | The test name from the config file |
| `TEST_*` | All config parameters (key uppercased, `TEST_` prefix added) |
| `SPECIAL_SOURCE_FILE` | The provenance string for the config file that defined this test |
| `SPECIAL_CREATE_ISSUE` | Whether issue creation is enabled (`true` / `false`) |
| `SECRET_*` | Secrets resolved from the orchestrator's own environment |

---

## Provenance

Each test container receives a `SPECIAL_SOURCE_FILE` environment variable identifying the config file that produced it. When the GitHub Actions environment variables listed above are present, this is a full `github.com` blob URL pointing to the exact commit:

```
https://github.com/org/repo/blob/abc123def/configs/my-config.yaml
```

When running locally it falls back to the path of the config file relative to the config directory:

```
external_test_resources/my-config.yaml
```

---

## Secrets

Config values can reference secrets using the `!secret` YAML tag:

```yaml
config:
  api-key: !secret my_api_key
```

The orchestrator looks up `SECRET_MY_API_KEY` in its own environment and passes it to the test container under the same name. If the secret is not found in the orchestrator's environment, an empty string is passed and a warning is printed. Secret values are never logged — only their key names appear in the output.

Secret reference names must start with a letter and contain only letters, digits, and underscores (`[A-Z][A-Z0-9_]*`). An invalid name raises an error at config load time.

---

## Output

The orchestrator produces:

- `reports/{test_name}_report.xml` — individual JUnit XML report per test (deleted after combining)
- `reports/combined_report.xml` — all test suites merged into a single report

---

## Test Container Contract

Test containers must:

1. Accept parameters via `TEST_*` environment variables
2. Read `TS_NAME` for the test suite name
3. Write a JUnit XML report to `/reports/{TS_NAME}_report.xml`

Beyond these hard requirements, the following conventions are recommended:

- **`SPECIAL_SOURCE_FILE`** — it is strongly recommended to include this as a `provenance` suite-level property in the JUnit report. This makes the report self-describing and allows downstream tooling to trace results back to the exact config file that produced them.

- **`SPECIAL_CREATE_ISSUE`** — containers may optionally include this as a `create-issue` suite-level property. Downstream tooling such as [grmp-demo](https://github.com/vliz-be-opsci/grmp-demo) can use this property to automatically create GitHub issues for failing suites. Whether to include it depends on whether such tooling is in use.

- **`SECRET_*`** — these values must **never** be included in suite properties or any part of the JUnit report, as they may contain sensitive credentials. They are intended purely for runtime use within the container — for example, passing an API key to authenticate requests to the resource under test.