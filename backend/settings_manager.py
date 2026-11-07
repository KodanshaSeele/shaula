"""
Gerenciador de Configurações e Vault Auxiliar para Shaula
Autenticação protegida por senha (3884) e interoperabilidade com Vault Auxiliar.
"""

import os
import json
import time
import hmac
import shutil
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from .config import SETTINGS_FILE, ADMIN_PASSWORD, SECRET_KEY, VAULT_PATH, AUX_VAULT_PATH


DEFAULT_SETTINGS = {
    "admin_password": ADMIN_PASSWORD,
    "aux_vault_enabled": False,
    "aux_vault_path": str(AUX_VAULT_PATH),
    "aux_sync_mode": "import_only",  # 'import_only', 'export_only', 'bidirectional'
    "auto_sync_interval_min": 0,
    "last_sync": None
}


class SettingsManager:
    def __init__(self):
        self.settings: Dict[str, Any] = {}
        self._load()

    def _load(self):
        if SETTINGS_FILE.exists():
            try:
                self.settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except Exception:
                self.settings = dict(DEFAULT_SETTINGS)
        else:
            self.settings = dict(DEFAULT_SETTINGS)
            self._save()

        # Garantir chaves essenciais
        for k, v in DEFAULT_SETTINGS.items():
            if k not in self.settings:
                self.settings[k] = v

    def _save(self):
        SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2, ensure_ascii=False), encoding="utf-8")

    def verify_password(self, password: str) -> bool:
        """Verifica se a senha fornecida confere com a configurada (padrão 3884)."""
        current_pw = self.settings.get("admin_password") or ADMIN_PASSWORD
        return hmac.compare_digest(str(password).strip(), str(current_pw).strip())

    def generate_token(self) -> str:
        """Gera token de sessão autenticada com validade de 24h."""
        ts = int(time.time())
        current_pw = self.settings.get("admin_password") or ADMIN_PASSWORD
        payload = f"{ts}:{current_pw}"
        sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return f"{ts}.{sig}"

    def validate_token(self, token: str) -> bool:
        """Valida integridade e expiração do token de sessão."""
        if not token or "." not in token:
            return False
        try:
            ts_str, sig = token.split(".", 1)
            ts = int(ts_str)
            # Expira após 24 horas (86400 segundos)
            if time.time() - ts > 86400:
                return False
            current_pw = self.settings.get("admin_password") or ADMIN_PASSWORD
            expected_sig = hmac.new(SECRET_KEY.encode(), f"{ts}:{current_pw}".encode(), hashlib.sha256).hexdigest()
            return hmac.compare_digest(sig, expected_sig)
        except Exception:
            return False

    def get_settings_safe(self) -> Dict[str, Any]:
        """Retorna configurações sem expor a senha diretamente em claro."""
        copy = dict(self.settings)
        copy["admin_password_set"] = bool(self.settings.get("admin_password"))
        copy.pop("admin_password", None)
        copy["aux_vault_stats"] = self.get_aux_stats()
        return copy

    def update_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Atualiza preferências administrativas."""
        if "admin_password" in updates and updates["admin_password"]:
            self.settings["admin_password"] = str(updates["admin_password"]).strip()

        if "aux_vault_enabled" in updates:
            self.settings["aux_vault_enabled"] = bool(updates["aux_vault_enabled"])

        if "aux_vault_path" in updates and updates["aux_vault_path"]:
            p = Path(updates["aux_vault_path"]).expanduser().resolve()
            p.mkdir(parents=True, exist_ok=True)
            self.settings["aux_vault_path"] = str(p)

        if "aux_sync_mode" in updates:
            self.settings["aux_sync_mode"] = updates["aux_sync_mode"]

        if "auto_sync_interval_min" in updates:
            self.settings["auto_sync_interval_min"] = int(updates["auto_sync_interval_min"])

        self._save()
        return self.get_settings_safe()

    # --- GERENCIAMENTO DO VAULT AUXILIAR ---
    def get_aux_path(self) -> Path:
        path_str = self.settings.get("aux_vault_path") or str(AUX_VAULT_PATH)
        p = Path(path_str).expanduser().resolve()
        return p

    def get_aux_stats(self) -> Dict[str, Any]:
        """Inspeciona diretório do Vault Auxiliar."""
        p = self.get_aux_path()
        exists = p.exists()
        is_dir = p.is_dir() if exists else False
        readable = os.access(p, os.R_OK) if exists else False
        writable = os.access(p, os.W_OK) if exists else False

        total_notes = 0
        total_size_kb = 0
        if exists and is_dir and readable:
            try:
                for f in p.rglob("*.md"):
                    if not f.name.startswith("."):
                        total_notes += 1
                        total_size_kb += round(f.stat().st_size / 1024, 2)
            except Exception:
                pass

        return {
            "path": str(p),
            "exists": exists,
            "is_directory": is_dir,
            "readable": readable,
            "writable": writable,
            "total_notes": total_notes,
            "total_size_kb": round(total_size_kb, 2),
            "enabled": self.settings.get("aux_vault_enabled", False)
        }

    def get_aux_tree(self) -> Dict[str, Any]:
        """Retorna estrutura de diretórios do Vault Auxiliar."""
        aux_path = self.get_aux_path()
        if not aux_path.exists() or not aux_path.is_dir():
            return {"type": "directory", "name": "aux_vault", "path": "", "children": [], "error": "Diretório não encontrado"}

        def walk_dir(directory: Path) -> Dict[str, Any]:
            items = []
            try:
                entries = sorted(list(directory.iterdir()), key=lambda e: (not e.is_dir(), e.name.lower()))
            except Exception:
                entries = []

            for entry in entries:
                if entry.name.startswith("."):
                    continue
                rel = str(entry.relative_to(aux_path))
                if entry.is_dir():
                    items.append(walk_dir(entry))
                elif entry.is_file() and entry.suffix.lower() in [".md", ".markdown", ".txt"]:
                    items.append({
                        "type": "file",
                        "name": entry.name,
                        "path": rel,
                        "size": entry.stat().st_size,
                        "modified": datetime.fromtimestamp(entry.stat().st_mtime).isoformat()
                    })

            return {
                "type": "directory",
                "name": directory.name if directory != aux_path else "aux_root",
                "path": str(directory.relative_to(aux_path)) if directory != aux_path else "",
                "children": items
            }

        return walk_dir(aux_path)

    def import_note_from_aux(self, aux_rel_path: str, dest_folder: str = "00 - Inbox") -> Dict[str, Any]:
        """Copia uma nota do Vault Auxiliar para o Vault do Shaula."""
        aux_path = self.get_aux_path()
        src_file = (aux_path / aux_rel_path.lstrip("/\\")).resolve()
        if not src_file.is_file():
            raise FileNotFoundError(f"Arquivo não encontrado no Vault Auxiliar: {aux_rel_path}")

        dest_dir = (VAULT_PATH / dest_folder.lstrip("/\\")).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / src_file.name

        shutil.copy2(src_file, dest_file)
        return {
            "success": True,
            "source": aux_rel_path,
            "destination": str(dest_file.relative_to(VAULT_PATH))
        }

    def export_note_to_aux(self, shaula_rel_path: str, dest_folder: str = "") -> Dict[str, Any]:
        """Exporta uma nota do Shaula para o Vault Auxiliar."""
        src_file = (VAULT_PATH / shaula_rel_path.lstrip("/\\")).resolve()
        if not src_file.is_file():
            raise FileNotFoundError(f"Arquivo não encontrado no Vault Shaula: {shaula_rel_path}")

        aux_path = self.get_aux_path()
        dest_dir = (aux_path / dest_folder.lstrip("/\\")).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / src_file.name

        shutil.copy2(src_file, dest_file)
        return {
            "success": True,
            "source": shaula_rel_path,
            "destination": str(dest_file.relative_to(aux_path))
        }

    def sync_all_notes(self, mode: Optional[str] = None) -> Dict[str, Any]:
        """Sincroniza notas entre Vault Shaula e Vault Auxiliar."""
        sync_mode = mode or self.settings.get("aux_sync_mode", "import_only")
        aux_path = self.get_aux_path()
        if not aux_path.exists():
            raise FileNotFoundError("Vault Auxiliar não configurado ou inacessível.")

        imported_count = 0
        exported_count = 0

        # Importação (Auxiliar -> Shaula)
        if sync_mode in ["import_only", "bidirectional"]:
            inbox_dir = VAULT_PATH / "00 - Inbox"
            inbox_dir.mkdir(parents=True, exist_ok=True)
            for aux_file in aux_path.rglob("*.md"):
                if aux_file.name.startswith("."):
                    continue
                dest_file = inbox_dir / aux_file.name
                # Se não existir ou se o auxiliar for mais recente
                if not dest_file.exists() or aux_file.stat().st_mtime > dest_file.stat().st_mtime:
                    shutil.copy2(aux_file, dest_file)
                    imported_count += 1

        # Exportação (Shaula -> Auxiliar)
        if sync_mode in ["export_only", "bidirectional"]:
            for shaula_file in VAULT_PATH.rglob("*.md"):
                if shaula_file.name.startswith(".") or ".backups" in shaula_file.parts:
                    continue
                # Manter estrutura de pastas relativas no auxiliar
                rel_path = shaula_file.relative_to(VAULT_PATH)
                dest_file = aux_path / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                if not dest_file.exists() or shaula_file.stat().st_mtime > dest_file.stat().st_mtime:
                    shutil.copy2(shaula_file, dest_file)
                    exported_count += 1

        now_str = datetime.now().isoformat()
        self.settings["last_sync"] = now_str
        self._save()

        return {
            "success": True,
            "mode": sync_mode,
            "imported_notes": imported_count,
            "exported_notes": exported_count,
            "timestamp": now_str
        }


settings_mgr = SettingsManager()
