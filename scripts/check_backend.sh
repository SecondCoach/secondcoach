#!/bin/bash
set -e
./scripts/check_backend_compile.sh
./scripts/check_backend_health.sh
echo "OK: backend listo"
