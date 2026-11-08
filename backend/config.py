"""
Configurações Globais do Shaula Dashboard
Tudo encapsulado e auto-suficiente dentro do repositório para total sincronização Git e portabilidade Docker.
"""

import os
from pathlib import Path

# Raiz do projeto (tudo encapsulado aqui para sincronização Git)
BASE_DIR = Path(__file__).resolve().parent.parent

# Perfil Hermes Nashetanea e Vaults
NASH_PROFILE_PATH = Path(os.environ.get("HERMES_PROFILE_PATH", "/home/kodansha/.hermes/profiles/nash")).resolve()
NASH_VAULT_PATH = NASH_PROFILE_PATH / "vault"

# Caminhos padrão relativos ao repositório ou sistema integrado
VAULT_PATH = Path(os.environ.get("SHAULA_VAULT_PATH", BASE_DIR / "vault")).resolve()
AUX_VAULT_PATH = Path(os.environ.get("SHAULA_AUX_VAULT_PATH", NASH_VAULT_PATH if NASH_VAULT_PATH.exists() else BASE_DIR / "aux_vault")).resolve()
DATA_DIR = Path(os.environ.get("SHAULA_DATA_PATH", BASE_DIR / "data")).resolve()
LOGS_DIR = Path(os.environ.get("SHAULA_LOGS_PATH", BASE_DIR / "logs")).resolve()
VERIFICATION_LOGS_DIR = LOGS_DIR / "verification"

STATIC_DIR = BASE_DIR / "frontend" / "static"
FRONTEND_DIR = BASE_DIR / "frontend"
ASSETS_DIR = VAULT_PATH / "assets"

SCHEDULES_FILE = DATA_DIR / "schedules.json"
HISTORY_FILE = DATA_DIR / "history.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
BACKUPS_DIR = VAULT_PATH / ".backups"

# Parâmetros de Retenção Inteligente de Logs
MAX_LOG_FILES = int(os.environ.get("SHAULA_MAX_LOG_FILES", 30))
MAX_LOG_AGE_DAYS = int(os.environ.get("SHAULA_MAX_LOG_AGE_DAYS", 3))
MAX_LOG_SIZE_MB = int(os.environ.get("SHAULA_MAX_LOG_SIZE_MB", 10))

HOST = os.environ.get("SHAULA_HOST", "0.0.0.0")
PORT = int(os.environ.get("SHAULA_PORT", 5000))
ADMIN_PASSWORD = os.environ.get("SHAULA_ADMIN_PASSWORD", "3884")
SECRET_KEY = os.environ.get("SHAULA_SECRET_KEY", "shaula-scorpio-3884-portable")

# Garantir existência de diretórios essenciais
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
VAULT_PATH.mkdir(parents=True, exist_ok=True)
AUX_VAULT_PATH.mkdir(parents=True, exist_ok=True)
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
VERIFICATION_LOGS_DIR.mkdir(parents=True, exist_ok=True)
