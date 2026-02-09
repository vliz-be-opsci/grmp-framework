# Test Orchestrator

A Docker-based test orchestration system that runs test workers in isolated containers and combines their JUnit XML reports.

## Overview

The orchestrator:
- Reads test configurations from a YAML file
- Pulls and runs test worker containers
- Passes parameters to workers via environment variables (with `TEST_` prefix)
- Collects jUnit XML reports from workers
- Combines reports into a single output file

## Quick Start

### Local Deployment

```bash
docker-compose up
```

## Configuration

An example `tests.yaml` file is present within /config.

**Parameters:**
- `image` (required): Docker image for the test worker
- All other parameters are passed to the worker as `TEST_*` environment variables

## Output

The orchestrator creates:
- Individual test reports: `reports/{test_name}_report.xml`
- Combined report: `reports/combined_report.xml`

Individual reports are deleted after combining.

## Test Workers

Test workers must:
1. Accept parameters via `TEST_*` environment variables
2. Generate a JUnit XML report
3. Write the report to `/reports/{test_name}_report.xml`

The `TEST_NAME` environment variable contains the test name from the config.

Tests can be found [HERE](https://github.com/vliz-be-opsci/grmp-test-implementations)