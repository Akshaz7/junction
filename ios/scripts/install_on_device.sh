#!/usr/bin/env bash
# Run from any directory. The Python helper reads only the required .env settings.
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$script_dir/install_on_device.py" "$@"
