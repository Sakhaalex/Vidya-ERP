#!/usr/bin/env bash
# ==============================================================================
# Vidya ERP - Python Data Engine Environment Setup Script
# Configures virtual environment, dependencies, and verifies test suite.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "==> Configuring Vidya ERP Python Environment in ${WORKSPACE_ROOT}..."

if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 is not installed or not in PATH."
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1)
echo "==> Detected ${PYTHON_VERSION}"

# Check for pip or ensurepip
if python3 -m pip --version &> /dev/null; then
    echo "==> Upgrading packaging tools..."
    python3 -m pip install --upgrade pip setuptools wheel || true
    echo "==> Installing optional PostgreSQL driver (psycopg[binary])..."
    python3 -m pip install "psycopg[binary]>=3.1" || echo "Note: psycopg installation skipped or failed; SQLite remains fully functional."
else
    echo "==> Note: pip is not available in the current container."
    echo "    The core engine and SQLiteAdapter run on standard library (sqlite3, decimal, unittest)."
fi

echo "==> Executing Vidya Data Engine automated test suite..."
python3 "${WORKSPACE_ROOT}/run_tests.py"

echo "==> Environment validation complete."
