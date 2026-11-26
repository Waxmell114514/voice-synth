#!/usr/bin/env bash
# The fleet's only judge. Frozen after phase 0.4. Usage: statement/verify.sh <theorem full name>
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -I "$here/verify.py" "$@"
