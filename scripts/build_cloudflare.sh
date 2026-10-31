#!/usr/bin/env bash
# Cloudflare Pages build entry point. Run from the repository root.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Use the stable project URL, not CF_PAGES_URL: the latter can identify an
# individual deployment. This public setting is not a secret or a credential.
if [[ -z "${SITE_URL:-}" ]]; then
  echo 'Set SITE_URL to the stable HTTPS site root in Cloudflare Pages environment variables.' >&2
  exit 1
fi

python3 -m venv .build-venv
.build-venv/bin/python -m pip install --disable-pip-version-check --requirement requirements-build.txt
.build-venv/bin/python scripts/build.py --cloudflare
.build-venv/bin/python scripts/check_site.py dist
