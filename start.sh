#!/usr/bin/env bash
# Inicia o painel Nash RAG Desk (Antigravity & Obsidian Second Brain)
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

PORT="${NASH_DESK_PORT:-8770}"
HOST="${NASH_DESK_HOST:-0.0.0.0}"

echo "=========================================================="
echo "◈ Iniciando Nash RAG Desk na porta ${PORT}..."
echo "  Vault SSoT: /home/kodansha/.hermes/profiles/nash/vault"
echo "  Agente CLI: /home/kodansha/.local/bin/agy"
echo "  URL: http://localhost:${PORT}"
echo "=========================================================="

exec python3 -m uvicorn backend.server:app --host "$HOST" --port "$PORT" --proxy-headers --forwarded-allow-ips='*'
