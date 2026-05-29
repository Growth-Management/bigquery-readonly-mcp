#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 https://<cloud-run-url>" >&2
  exit 2
fi

base_url="${1%/}"
curl -fsS "${base_url}/healthz"
echo
