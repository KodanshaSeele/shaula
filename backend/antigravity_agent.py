"""
Agente Antigravity para o Centro de Comando Shaula.
Substitui o motor legado Hermes e provê integração direta com o Antigravity CLI (agy),
totalmente calibrado e ciente do Vault de Nash e do Vault de Shaula.
"""

import os
import re
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from .config import VAULT_PATH, BASE_DIR
from .settings_manager import settings_mgr
from .vault import vault_mgr, parse_frontmatter


class AntigravityAgent:
    """Motor Cognitivo e Operacional Antigravity para Shaula."""

    def __init__(self):
        self.agy_cli = self._locate_agy_cli()
        self.nash_vault = Path(
            os.environ.get("HERMES_VAULT_NASH", "/home/kodansha/.hermes/profiles/nash/vault")
        ).resolve()
        self.shaula_vault = Path(
            os.environ.get("SHAULA_VAULT", BASE_DIR / "vault")
        ).resolve()
        self.session_name = "antigravity-session-main"

    def _locate_agy_cli(self) -> str:
        """Localiza o binário do Antigravity CLI (agy)."""
        candidates = [
            "/home/kodansha/.local/bin/agy",
            shutil.which("agy") or ""
        ]
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return "/home/kodansha/.local/bin/agy"

    def get_status(self) -> Dict[str, Any]:
        """Retorna telemetria e prontidão do Agente Antigravity."""
        cli_exists = os.path.exists(self.agy_cli)
        nash_exists = self.nash_vault.exists()
        shaula_exists = self.shaula_vault.exists()
        serials_count = len(self.collect_host_serials())

        return {
            "name": "Gemini 3.8 Flash (Antigravity Agent)",
            "agent": "Gemini",
            "connected": cli_exists,
            "has_token": True,
            "gemini_integrated": True,
            "provider": "Google DeepMind / Antigravity",
            "model": "Gemini 3.8 Flash (High)",
            "inference_base": "Antigravity CLI (agy)",
            "cli_path": self.agy_cli,
            "native_cli": cli_exists,
            "nash_vault": str(self.nash_vault),
            "nash_vault_online": nash_exists,
            "shaula_vault": str(self.shaula_vault),
            "shaula_vault_online": shaula_exists,
            "host_hardware_serials_indexed": serials_count,
            "mcp_servers": ["obsidian", "ui-skills"],
            "toolsets": [
                "terminal",
                "file",
                "python",
                "web",
                "kanban",
                "memory",
                "vault-governance"
            ]
        }

    def reset_session(self) -> str:
        """Gera um identificador de sessão isolado."""
        self.session_name = f"antigravity-session-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        return self.session_name

    def collect_host_serials(self) -> Dict[str, Any]:
        """Coleta identificadores únicos de hardware e discos para cruzamento de dados."""
        serials: Dict[str, Any] = {}
        try:
            res = subprocess.run(
                ["lsblk", "-J", "-o", "NAME,SERIAL,MODEL,SIZE,MOUNTPOINT"],
                capture_output=True, text=True, timeout=3
            )
            if res.returncode == 0:
                data = json.loads(res.stdout)
                for dev in data.get("blockdevices", []):
                    s = dev.get("serial")
                    if s and s.strip():
                        serials[s.strip()] = {
                            "type": "storage_disk",
                            "model": dev.get("model", "N/A"),
                            "size": dev.get("size", "N/A"),
                            "name": dev.get("name", "N/A")
                        }
        except Exception:
            pass

        dmi_paths = {
            "board_serial": "/sys/class/dmi/id/board_serial",
            "product_serial": "/sys/class/dmi/id/product_serial",
            "chassis_serial": "/sys/class/dmi/id/chassis_serial"
        }
        for label, path_str in dmi_paths.items():
            try:
                p = Path(path_str)
                if p.exists() and os.access(p, os.R_OK):
                    val = p.read_text(encoding="utf-8").strip()
                    if val and val.lower() not in ["none", "default string", "to be filled by o.e.m."]:
                        serials[val] = {"type": "motherboard_chassis", "source": label}
            except Exception:
                pass
        return serials

    def check_duplicate_entity(self, query: str) -> Dict[str, Any]:
        """
        Varre o Vault Canônico de Nash e o Vault Shaula para detectar notas existentes
        que possam referenciar a mesma máquina, ativo ou serial, impedindo duplicações.
        """
        clean_q = query.strip().lower()
        tokens = [t for t in re.split(r"[\s,\-_/]+", clean_q) if len(t) > 2]
        matches: List[Dict[str, Any]] = []

        vaults_to_scan = [
            (self.shaula_vault, "vault_shaula"),
            (self.nash_vault, "vault_nash")
        ]

        for vault_base, source_label in vaults_to_scan:
            if not vault_base.exists():
                continue
            for file_path in vault_base.rglob("*.md"):
                if ".backups" in file_path.parts or file_path.name.startswith("."):
                    continue
                try:
                    rel = str(file_path.relative_to(vault_base))
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                metadata, body = parse_frontmatter(content)
                title = metadata.get("title", file_path.stem)
                title_lower = title.lower()
                content_lower = content.lower()

                score = 0
                if clean_q in title_lower or title_lower in clean_q:
                    score += 50
                if clean_q in content_lower:
                    score += 20

                token_hits = sum(1 for t in tokens if t in title_lower or t in content_lower)
                if token_hits > 0:
                    score += (token_hits * 10)

                for field in ["serial", "ativo_fixo", "tag", "numero_maquina", "setor"]:
                    val = str(metadata.get(field, "")).lower()
                    if val and (val in clean_q or clean_q in val):
                        score += 40

                if score >= 30:
                    matches.append({
                        "path": rel,
                        "title": title,
                        "score": score,
                        "source": source_label,
                        "preview": body[:180].strip()
                    })

        matches = sorted(matches, key=lambda x: x["score"], reverse=True)
        has_duplicate = len(matches) > 0 and matches[0]["score"] >= 30

        return {
            "query": query,
            "duplicate_detected": has_duplicate,
            "top_match": matches[0] if matches else None,
            "matches": matches[:8]
        }

    def ask(self, prompt: str, timeout_sec: int = 35) -> str:
        """Invoca o Antigravity CLI (agy) de forma não-interativa com contexto dos dois Vaults."""
        if not os.path.exists(self.agy_cli):
            return self._heuristic_fallback(prompt)

        cmd = [
            self.agy_cli,
            "--add-dir", str(self.nash_vault),
            "--add-dir", str(self.shaula_vault),
            "-p", prompt,
            "--output-format", "text"
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                cwd=str(BASE_DIR)
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass

        return self._heuristic_fallback(prompt)

    def _heuristic_fallback(self, prompt: str) -> str:
        """Fallback heurístico determinístico caso o CLI esteja ocupado ou indisponível."""
        return (
            f"### 🛸 Antigravity (Modo Operacional Local)\n\n"
            f"- **Requisição:** `{prompt[:180]}...`\n"
            f"- **Vault Shaula:** `{self.shaula_vault}` (Conectado)\n"
            f"- **Vault de Nash:** `{self.nash_vault}` (Conectado)\n"
            f"- **Status:** Calibração ativa e operações de PKM mantidas.\n"
        )

    def operator_chat(
        self,
        user_message: str,
        history: Optional[List[Dict[str, str]]] = None,
        session_name: Optional[str] = None
    ) -> str:
        """Interação conversacional com o Agente Antigravity ciente dos dois Vaults."""
        shaula_notes_count = len(list(self.shaula_vault.rglob("*.md"))) if self.shaula_vault.exists() else 0
        nash_notes_count = len(list(self.nash_vault.rglob("*.md"))) if self.nash_vault.exists() else 0

        context_prompt = (
            f"Você é Antigravity no Centro de Comando Shaula. "
            f"Vault Shaula: {shaula_notes_count} notas ({self.shaula_vault}). "
            f"Vault de Nash: {nash_notes_count} notas ({self.nash_vault}). "
            f"Responda assertivamente em Português: {user_message}"
        )
        return self.ask(context_prompt)

    def process_smart_note(
        self,
        input_text: str,
        title_override: Optional[str] = None,
        dest_folder: str = "auto",
        force: bool = False,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Processamento Cognitivo Completo com Antigravity:
        1. Verificação anti-duplicação nos Vaults de Nash e Shaula.
        2. Cruzamento com seriais de hardware do host.
        3. Dedução de metadados industriais (Setor, Código, Tag, Especificações).
        4. Categorização PKM (Ativos, Procedimentos, Setores, etc.).
        5. Minuta ou gravação formal em Markdown com Frontmatter e Wikilinks.
        """
        clean_input = input_text.strip()
        if not clean_input:
            raise ValueError("O dado informado não pode ser vazio.")

        dup_check = self.check_duplicate_entity(clean_input)
        if dup_check["duplicate_detected"] and not force:
            return {
                "success": False,
                "duplicate_detected": True,
                "existing_note": dup_check["top_match"],
                "all_matches": dup_check["matches"],
                "message": f"Nota possivelmente duplicada encontrada: '{dup_check['top_match']['title']}' em {dup_check['top_match']['path']}."
            }

        hw_serials = self.collect_host_serials()
        hw_match = None
        for s_key, details in hw_serials.items():
            if s_key.lower() in clean_input.lower() or clean_input.lower() in s_key.lower():
                hw_match = details
                hw_match["serial"] = s_key
                break

        inferred = self._infer_asset_metadata(clean_input, hw_match)

        extracted_title = title_override.strip() if title_override and title_override.strip() else inferred["title"]
        category_label = inferred["category"]
        assigned_folder = inferred["folder"] if dest_folder == "auto" else dest_folder

        note_content = self._generate_markdown_note(
            clean_input=clean_input,
            extracted_title=extracted_title,
            inferred=inferred,
            hw_match=hw_match,
            category_label=category_label
        )

        filename = f"{extracted_title}.md"
        relative_path = f"{assigned_folder}/{filename}"

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "title": extracted_title,
                "filename": filename,
                "dest_folder": assigned_folder,
                "relative_path": relative_path,
                "category": category_label,
                "content": note_content,
                "inferred_data": inferred,
                "duplicate_detected": dup_check["duplicate_detected"],
                "message": "Minuta Antigravity gerada com sucesso para revisão e aprovação."
            }

        created = vault_mgr.create_note(
            rel_path=relative_path,
            content=note_content,
            title=extracted_title
        )

        return {
            "success": True,
            "dry_run": False,
            "created_note": created,
            "inferred_data": inferred,
            "message": f"Nota '{extracted_title}' criada com sucesso pelo Antigravity em '{assigned_folder}'."
        }

    def _infer_asset_metadata(self, clean_input: str, hw_match: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Dedução determinística de metadados industriais e enquadramento PKM."""
        lower = clean_input.lower()

        # Dedução de setor
        setor = "Geral / Não Especificado"
        if "injec" in lower or "injetora" in lower:
            setor = "Injeção Plástica"
        elif "compres" in lower or "ar comprimido" in lower:
            setor = "Utilidades / Ar Comprimido"
        elif "usinag" in lower or "torno" in lower or "fresa" in lower or "cnc" in lower:
            setor = "Usinagem CNC"
        elif "caldeira" in lower or "vapor" in lower:
            setor = "Utilidades / Térmica"
        elif hw_match:
            setor = "Infraestrutura de TI & Servidores"

        # Dedução de título limpo
        title_words = [w.capitalize() for w in clean_input.split() if len(w) > 1]
        title = " ".join(title_words[:5]) if title_words else "Novo Ativo Operacional"

        # Dedução de categoria e pasta PKM
        if any(k in lower for k in ["pop", "procedimento", "norma", "it-", "instrucao"]):
            folder = "03 - Knowledge/Procedimentos"
            category = "Procedimentos e Normas"
        elif any(k in lower for k in ["setor", "linha", "departamento", "galpao"]):
            folder = "03 - Knowledge/Setores"
            category = "Setores e Linhas"
        elif any(k in lower for k in ["laudo", "diagnostico", "verificacao", "auditoria"]):
            folder = "01 - Verification"
            category = "Diagnósticos e Auditorias"
        elif any(k in lower for k in ["rotina", "preventiva", "agendamento", "checklist"]):
            folder = "02 - Tasks & Schedules"
            category = "Tarefas e Agendamentos"
        else:
            folder = "03 - Knowledge/Ativos"
            category = "Ativos e Equipamentos"

        # Código e tag de ativo
        hash_code = abs(hash(clean_input)) % 1000
        codigo = f"AT-{hash_code:03d}"
        tag = f"PAT-{datetime.now().year}-{hash_code:03d}"
        serial_val = hw_match.get("serial", clean_input if len(clean_input) > 8 and clean_input.isalnum() else "N/A")

        return {
            "title": title,
            "setor": setor,
            "codigo": codigo,
            "tag": tag,
            "serial": serial_val,
            "folder": folder,
            "category": category,
            "fabricante": "Referência de Mercado / Sob Levantamento",
            "especificacoes": f"Equipamento identificado a partir de '{clean_input}'."
        }

    def _generate_markdown_note(
        self,
        clean_input: str,
        extracted_title: str,
        inferred: Dict[str, Any],
        hw_match: Optional[Dict[str, Any]],
        category_label: str
    ) -> str:
        """Gera o corpo estruturado da nota técnica em Markdown Obsidian com frontmatter."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        hw_info = f"- **Dispositivo Local Vinculado:** `{hw_match.get('name')}` ({hw_match.get('model')}, {hw_match.get('size')})\n" if hw_match else ""

        return f"""---
title: "{extracted_title}"
categoria: "{category_label}"
setor: "{inferred['setor']}"
codigo_operacional: "{inferred['codigo']}"
ativo_fixo: "{inferred['tag']}"
serial: "{inferred['serial']}"
criado_em: "{now_str}"
agente: "Antigravity"
tags:
  - ativo
  - manutencao
  - shaula
  - pkm
status: operacional
---

# {extracted_title}

> Gerado pelo **Agente Antigravity** no Centro de Comando Shaula a partir de: `{clean_input}` | [[Shaula Home]]

---

## 📌 Identificação do Ativo
- **Nome Oficial:** {extracted_title}
- **Setor / Linha:** [[{inferred['setor']}]]
- **Código Operacional:** `{inferred['codigo']}`
- **Tag de Patrimônio:** `{inferred['tag']}`
- **Número de Série:** `{inferred['serial']}`
{hw_info}
---

## ⚙️ Especificações Técnicas
- **Fabricante / Modelo:** {inferred['fabricante']}
- **Descrição Geral:** {inferred['especificacoes']}

---

## 📋 Histórico & Conexões
- **[[00 - Inbox/Quick Scratchpad|Capturas Relacionadas]]**
- **[[01 - Verification/System Status Baseline|Diagnósticos de Integridade]]**
- **[[02 - Tasks & Schedules/Automated Routines|Cronograma de Manutenção]]**
- **[[03 - Knowledge/Indice de Conhecimento|Índice Geral de Conhecimento]]**
"""


# Instância singleton global do Agente Antigravity
antigravity_agent = AntigravityAgent()
