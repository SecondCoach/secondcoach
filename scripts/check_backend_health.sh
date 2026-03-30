#!/bin/bash
set -e
curl -fsS http://127.0.0.1:8000/health
echo ""
echo "OK: /health responde"
