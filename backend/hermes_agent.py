"""
Agente Hermes Integrado ao Shaula Dashboard
Executa tarefas de inteligência, análise contextual, chat, verificação anti-duplicação
e dedução profunda de ativos/máquinas (setor, nome oficial, ativo fixo, especificações técnicas).
"""

import os
import re
import json
import psutil
import socket
import requests
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from .config import VAULT_PATH, DATA_DIR, AUX_VAULT_PATH
from .vault import vault_mgr
from .settings_manager import settings_mgr

HERMES_PROFILE_PATH = Path("/home/kodansha/arquivos/hermes/profiles/grimorium/auth.json")
CONTAINER_HOST_HERMES = Path("/host_hermes/profiles/grimorium/auth.json")
DATA_HERMES_AUTH = DATA_DIR / "hermes_auth.json"


import unicodedata

def slugify(text: str) -> str:
    norm = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    clean = re.sub(r'[^a-zA-Z0-9_\- ]', '', norm).strip()
    return re.sub(r'\s+', '_', clean)


class HermesAgent:
    def __init__(self):
        self.provider = "nous"
        self.model = os.environ.get("HERMES_MODEL", "reflection/beam-1.0-501b-a23b:free")
        self.inference_base = os.environ.get("HERMES_API_BASE", "https://inference-api.nousresearch.com/v1")
        self.access_token = os.environ.get("HERMES_TOKEN", "")
        self._load_credentials()

    def _load_credentials(self):
        """Descobre e carrega credenciais do Hermes instalado na máquina ou variáveis de ambiente."""
        if self.access_token:
            return

        candidate_paths = [
            DATA_HERMES_AUTH,
            CONTAINER_HOST_HERMES,
            HERMES_PROFILE_PATH,
            Path("/root/.hermes/profiles/grimorium/auth.json"),
            Path("/root/.hermes/auth.json")
        ]

        for p in candidate_paths:
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    nous = data.get("providers", {}).get("nous", {})
                    token = nous.get("access_token") or nous.get("agent_key")
                    if token:
                        self.access_token = token
                        self.inference_base = nous.get("inference_base_url", self.inference_base)
                        if p != DATA_HERMES_AUTH:
                            DATA_HERMES_AUTH.write_text(json.dumps(data, indent=2), encoding="utf-8")
                        break
                except Exception:
                    continue

    def get_status(self) -> Dict[str, Any]:
        """Retorna status de conexão e telemetria do Agente Hermes."""
        self._load_credentials()
        has_token = bool(self.access_token)
        connected = False

        if has_token:
            try:
                headers = {"Authorization": f"Bearer {self.access_token}"}
                r = requests.get(f"{self.inference_base}/models", headers=headers, timeout=3)
                connected = (r.status_code == 200)
            except Exception:
                connected = False

        ollama_active = False
        try:
            r = requests.get("http://127.0.0.1:11434/api/tags", timeout=1)
            ollama_active = (r.status_code == 200)
        except Exception:
            pass

        return {
            "name": "Hermes Agent",
            "connected": connected,
            "has_token": has_token,
            "provider": self.provider,
            "model": self.model,
            "inference_base": self.inference_base,
            "ollama_fallback": ollama_active,
            "host_hardware_serials_indexed": len(self.collect_host_serials())
        }

    def collect_host_serials(self) -> Dict[str, Any]:
        """Coleta seriais de hardware reais do host para cruzamento determinístico."""
        serials: Dict[str, Any] = {}

        # Discos e Armazenamento (lsblk)
        try:
            res = subprocess.run(
                ["lsblk", "-J", "-o", "NAME,MODEL,SERIAL,SIZE,TYPE"],
                capture_output=True, text=True, timeout=2
            )
            if res.returncode == 0:
                data = json.loads(res.stdout)
                for dev in data.get("blockdevices", []):
                    s = dev.get("serial")
                    if s and s.strip():
                        serials[s.strip().upper()] = {
                            "type": "Armazenamento Físico",
                            "model": dev.get("model", "N/A"),
                            "name": dev.get("name"),
                            "size": dev.get("size")
                        }
        except Exception:
            pass

        # Interfaces de Rede (MAC Address)
        try:
            for iface, addrs in psutil.net_if_addrs().items():
                for a in addrs:
                    if getattr(psutil, "AF_LINK", None) and a.family == psutil.AF_LINK and a.address:
                        mac = a.address.strip().upper()
                        if mac != "00:00:00:00:00:00":
                            serials[mac] = {
                                "type": "Interface de Rede (MAC)",
                                "interface": iface
                            }
        except Exception:
            pass

        # Machine ID
        try:
            for m_path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
                p = Path(m_path)
                if p.exists():
                    mid = p.read_text().strip().upper()
                    serials[mid] = {"type": "System Machine ID", "file": m_path}
                    break
        except Exception:
            pass

        return serials

    def check_duplicate_entity(self, query: str) -> Dict[str, Any]:
        """
        Varre o Vault Shaula e Vault Auxiliar para detectar notas existentes
        que possam referenciar a mesma máquina, ativo ou serial, impedindo duplicações.
        """
        clean_q = query.strip().lower()
        tokens = [t for t in re.split(r"[\s,\-_/]+", clean_q) if len(t) > 2]

        matches: List[Dict[str, Any]] = []

        # 1. Buscar no Vault Shaula
        for file_path in VAULT_PATH.rglob("*.md"):
            if ".backups" in file_path.parts:
                continue
            rel = str(file_path.relative_to(VAULT_PATH))
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            metadata, body = vault_mgr.read_note(rel)["metadata"], content
            title = metadata.get("title", file_path.stem)
            title_lower = title.lower()
            content_lower = content.lower()

            # Cálculo de similaridade / correspondência
            score = 0
            if clean_q in title_lower or title_lower in clean_q:
                score += 50
            if clean_q in content_lower:
                score += 20

            token_hits = sum(1 for t in tokens if t in title_lower or t in content_lower)
            if token_hits > 0:
                score += (token_hits * 10)

            # Verificar campos chave de frontmatter
            for field in ["serial", "ativo_fixo", "tag", "numero_maquina", "setor"]:
                val = str(metadata.get(field, "")).lower()
                if val and (val in clean_q or clean_q in val):
                    score += 40

            if score >= 30:
                matches.append({
                    "path": rel,
                    "title": title,
                    "score": score,
                    "source": "vault_shaula",
                    "preview": body[:180].strip()
                })

        # 2. Buscar no Vault Auxiliar
        try:
            aux_path = settings_mgr.get_aux_path()
            if aux_path.exists():
                for file_path in aux_path.rglob("*.md"):
                    if file_path.name.startswith("."):
                        continue
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    if clean_q in content.lower() or any(t in content.lower() for t in tokens):
                        matches.append({
                            "path": f"aux_vault/{file_path.name}",
                            "title": file_path.stem,
                            "score": 25,
                            "source": "vault_auxiliar",
                            "preview": content[:180].strip()
                        })
        except Exception:
            pass

        matches = sorted(matches, key=lambda x: x["score"], reverse=True)
        has_duplicate = len(matches) > 0 and matches[0]["score"] >= 30

        return {
            "duplicate_detected": has_duplicate,
            "top_match": matches[0] if matches else None,
            "matches": matches[:5]
        }

    def ask(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Executa inferência com o Hermes (Nous Research API) com fallbacks inteligentes."""
        self._load_credentials()

        sys_msg = system_prompt or (
            "Você é o Agente Hermes, inteligência artificial integrada ao Shaula Dashboard. "
            "Especialista em engenharia, catalogação técnica de ativos, equipamentos, informática e automação industrial. "
            "Responda sempre em Português de forma precisa, técnica e formatada em Markdown com suporte a [[Wikilinks]]."
        )

        # 1. Nous Research Inference API
        if self.access_token:
            try:
                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": sys_msg},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1500
                }
                r = requests.post(f"{self.inference_base}/chat/completions", headers=headers, json=payload, timeout=25)
                if r.status_code == 200:
                    data = r.json()
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "").strip()
            except Exception:
                pass

        # 2. Ollama local
        try:
            r = requests.post(
                "http://127.0.0.1:11434/api/generate",
                json={"model": "llama3.2:latest", "prompt": f"{sys_msg}\n\nUsuário: {prompt}", "stream": False},
                timeout=20
            )
            if r.status_code == 200:
                return r.json().get("response", "").strip()
        except Exception:
            pass

        # 3. Fallback Heurístico Estruturado
        return f"""
# Ficha Técnica — Registro Operacional

## Dados Identificados
- **Entrada:** {prompt[:200]}
- **Status:** Registro gerado em modo offline com heurística determinística.
- Para síntese avançada de linguagem natural, verifique a conexão com o Nous Portal em `data/hermes_auth.json`.
"""

    def process_smart_note(
        self,
        input_text: str,
        title_override: Optional[str] = None,
        dest_folder: str = "00 - Inbox",
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Processamento Cognitivo Completo:
        1. Verificação anti-duplicação no Vault Shaula e Auxiliar
        2. Cruzamento com telemetria e hardware se aplicável
        3. Dedução de informações parciais (Setor, Nome Oficial, Tag Ativo Fixo, Especificações Técnicas)
        4. Criação e abertura imediata do documento técnico formal em Markdown
        """
        clean_input = input_text.strip()
        if not clean_input:
            raise ValueError("O dado informado não pode ser vazio.")

        # 1. Checar se já existe nota duplicada
        dup_check = self.check_duplicate_entity(clean_input)
        if dup_check["duplicate_detected"] and not force:
            return {
                "success": False,
                "duplicate_detected": True,
                "existing_note": dup_check["top_match"],
                "all_matches": dup_check["matches"],
                "message": f"Nota possivelmente duplicada encontrada: '{dup_check['top_match']['title']}' em {dup_check['top_match']['path']}."
            }

        # 2. Cruzar com hardware local se contiver seriais conhecidos
        hw_serials = self.collect_host_serials()
        hw_match = None
        for s_key, details in hw_serials.items():
            if s_key.lower() in clean_input.lower() or clean_input.lower() in s_key.lower():
                hw_match = details
                hw_match["serial"] = s_key
                break

        # 3. Montar prompt de dedução técnica para o Agente Hermes
        hw_context = f"\nDados de hardware local correspondente: {json.dumps(hw_match, ensure_ascii=False)}" if hw_match else ""
        known_vault_refs = [m["title"] for m in dup_check.get("matches", [])]
        vault_context = f"\nReferências de contexto encontradas nos Vaults: {known_vault_refs}" if known_vault_refs else ""

        prompt = f"""
O usuário inseriu o seguinte dado ou descrição técnica (que pode ser parcial, informal ou um identificador):
"{clean_input}"
{hw_context}
{vault_context}

Como especialista técnico e engenheiro do Shaula Dashboard, processe essa informação:
1. Deduza ou extraia:
   - **Nome Oficial e Padronizado do Ativo/Máquina/Equipamento**
   - **Setor / Linha / Localização Fabril ou Operacional** (ex: se for injetora1 da injeção plastica -> Setor: Injeção Plástica)
   - **Número / Código Operacional da Máquina** (ex: INJ-01 / MQ-001)
   - **Tag de Ativo Fixo / Patrimônio** (ex: AT-INJ-001 / PAT-2026-001)
   - **Fabricante e Modelo Provável ou de Referência no Mercado**
   - **Especificações Técnicas Essenciais** (dimensões, capacidades, potências, pressões, vazões, etc.)
2. Elabore um documento técnico completo no padrão Obsidian Markdown contendo:
   - Frontmatter YAML com:
     title: "Nome Oficial Padronizado"
     date: "{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
     setor: "Nome do Setor"
     numero_maquina: "Código"
     ativo_fixo: "Tag Patrimonial"
     tags: [ativo, setor, equipamento, manutencao]
     status: operacional
   - Título H1 formal
   - Resumo Executivo da Identificação
   - Tabela Markdown de Especificações Técnicas
   - Componentes Críticos e Cuidados Operacionais
   - Checklist de Inspeção Preventiva / Diária (com caixas de seleção `- [ ]`)
   - Links úteis no estilo Wikilink ([[Shaula Home]], [[Setor ...]])
"""

        generated_body = self.ask(prompt)

        # Desempacotar blocos delimitadores se o modelo retornou ```markdown
        if generated_body.startswith("```markdown"):
            generated_body = generated_body[len("```markdown"):].strip()
            if generated_body.endswith("```"):
                generated_body = generated_body[:-3].strip()
        elif generated_body.startswith("```"):
            generated_body = generated_body[3:].strip()
            if generated_body.endswith("```"):
                generated_body = generated_body[:-3].strip()

        # Determinar título e nome de arquivo limpo
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        extracted_title = title_override
        if not extracted_title:
            title_match = re.search(r'title:\s*["\']?([^"\']+)["\']?', generated_body)
            if title_match:
                extracted_title = title_match.group(1).strip()
            else:
                first_h1 = re.search(r'^#\s+(.+)$', generated_body, re.MULTILINE)
                extracted_title = first_h1.group(1).strip() if first_h1 else clean_input.title()

        safe_filename = slugify(extracted_title) or f"Ativo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        rel_filename = f"{dest_folder.rstrip('/')}/{safe_filename}.md"

        # Se o modelo não gerou frontmatter, compor formalmente
        if not generated_body.startswith("---"):
            full_content = f"""---
title: "{extracted_title}"
date: "{now_str}"
tags:
  - ativo
  - equipamento
  - hermes
status: operacional
---

# {extracted_title}

> Gerado pelo **Agente Hermes** a partir de: `{clean_input}` | [[Shaula Home]]

---

{generated_body}
"""
        else:
            full_content = generated_body

        # Salvar nota no Vault
        try:
            created_note = vault_mgr.create_note(rel_filename, extracted_title, full_content)
        except FileExistsError:
            created_note = vault_mgr.save_note(rel_filename, full_content)

        return {
            "success": True,
            "duplicate_detected": False,
            "note_path": created_note["path"],
            "title": created_note["title"],
            "hardware_match": hw_match,
            "created_note": created_note
        }


hermes_agent = HermesAgent()
