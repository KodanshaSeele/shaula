"""
Configurações do Nash RAG Desk
Dedicado exclusivamente ao cofre Obsidian de Nash.
"""
import os
import shutil
from pathlib import Path

# Caminho canônico do cofre de Nash
VAULT_PATH = Path(
    os.environ.get("NASH_VAULT_PATH", "/home/kodansha/.hermes/profiles/nash/vault")
).resolve()

# Perfil e Infraestrutura RAG de Nash (FTS5 + Chroma)
NASH_PROFILE_DIR = Path(
    os.environ.get("NASH_PROFILE_DIR", "/home/kodansha/.hermes/profiles/nash")
).resolve()
STATE_DB_PATH = NASH_PROFILE_DIR / "state.db"
CHROMA_PATH = NASH_PROFILE_DIR / "chroma"

# Suporta a pasta canônica Inbox/ (definida no AGENTS.md do cofre) com fallback para 00 - Inbox
INBOX_PATH = (VAULT_PATH / "Inbox") if (VAULT_PATH / "Inbox").exists() else (VAULT_PATH / "00 - Inbox")
ASSETS_PATH = VAULT_PATH / "assets"
TEMPLATE_PATH = VAULT_PATH / "_templates" / "canonical-note-template.md"

# CLI Antigravity
AGY_CLI = os.environ.get("AGY_CLI_PATH", "/home/kodansha/.local/bin/agy")
if not os.path.exists(AGY_CLI):
    AGY_CLI = shutil.which("agy") or AGY_CLI

PORT = int(os.environ.get("NASH_DESK_PORT", "8770"))
HOST = os.environ.get("NASH_DESK_HOST", "0.0.0.0")

# Assegura que pastas básicas existam no cofre
ASSETS_PATH.mkdir(parents=True, exist_ok=True)
INBOX_PATH.mkdir(parents=True, exist_ok=True)
