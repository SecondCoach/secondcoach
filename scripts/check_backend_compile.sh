#!/bin/bash
set -e
python3 -m py_compile backend/*.py backend/views/*.py
echo "OK: backend compila"
