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
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from .config import VAULT_PATH, DATA_DIR, AUX_VAULT_PATH, NASH_PROFILE_PATH
from .vault import vault_mgr
from .settings_manager import settings_mgr

NASH_PROFILE_DIR = NASH_PROFILE_PATH
HERMES_PROFILE_PATH = NASH_PROFILE_DIR / "auth.json"
CONTAINER_HOST_HERMES = Path("/host_hermes/profiles/nash/auth.json")
DATA_HERMES_AUTH = DATA_DIR / "hermes_auth.json"


import unicodedata

def slugify(text: str) -> str:
    norm = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    clean = re.sub(r'[^a-zA-Z0-9_\- ]', '', norm).strip()
    return re.sub(r'\s+', '_', clean)


class HermesAgent:
    def __init__(self):
        self.profile = "nash"
        self.session_name = "shaula_dashboard"
        self.provider = "nous"
        self.model = os.environ.get("HERMES_MODEL", "reflection/beam-1.0-501b-a23b:free")
        self.inference_base = os.environ.get("HERMES_API_BASE", "https://inference-api.nousresearch.com/v1")
        self.access_token = os.environ.get("HERMES_TOKEN", "")
        self.nous_disabled = False
        self._load_credentials()

    def _load_credentials(self, force: bool = False):
        """Descobre e carrega credenciais do Hermes perfil Shaula."""
        if self.access_token and not force:
            return

        candidate_paths = [
            HERMES_PROFILE_PATH,
            DATA_HERMES_AUTH,
            CONTAINER_HOST_HERMES,
            Path("/root/.hermes/profiles/nash/auth.json"),
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
                            try:
                                DATA_HERMES_AUTH.write_text(json.dumps(data, indent=2), encoding="utf-8")
                            except Exception:
                                pass
                        break
                except Exception:
                    continue

    def refresh_token(self) -> bool:
        """Invoca o Hermes CLI com HERMES_HOME no perfil Shaula para renovar o token da Nous."""
        cli_candidates = [
            "/home/kodansha/.hermes/hermes-agent/.venv/bin/hermes",
            shutil.which("hermes")
        ]
        for cli in cli_candidates:
            if cli and Path(cli).is_file():
                try:
                    env = dict(os.environ, HERMES_HOME=str(NASH_PROFILE_DIR))
                    res = subprocess.run([cli, "auth", "refresh", "nous"], env=env, capture_output=True, text=True, timeout=15)
                    if res.returncode == 0:
                        self.nous_disabled = False
                        self.access_token = ""
                        self._load_credentials(force=True)
                        return True
                except Exception:
                    pass
        return False

    def get_status(self) -> Dict[str, Any]:
        """Retorna status de conexão e telemetria do Agente Hermes no perfil Shaula."""
        self._load_credentials()
        has_token = bool(self.access_token)
        connected = False

        if has_token:
            try:
                headers = {"Authorization": f"Bearer {self.access_token}"}
                r = requests.get(f"{self.inference_base}/models", headers=headers, timeout=3)
                if r.status_code == 200:
                    connected = True
                elif r.status_code in [401, 403]:
                    # Tentar auto-refresh
                    if self.refresh_token():
                        headers = {"Authorization": f"Bearer {self.access_token}"}
                        r2 = requests.get(f"{self.inference_base}/models", headers=headers, timeout=3)
                        connected = (r2.status_code == 200)
            except Exception:
                connected = False

        ollama_active = False
        try:
            r = requests.get("http://127.0.0.1:11434/api/tags", timeout=1)
            ollama_active = (r.status_code == 200)
        except Exception:
            pass

        mcp_servers_list = []
        try:
            cfg_path = NASH_PROFILE_DIR / "config.yaml"
            if cfg_path.exists():
                import yaml
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                servers = cfg.get("mcp_servers", {})
                if isinstance(servers, dict):
                    for s_name, s_cfg in servers.items():
                        if isinstance(s_cfg, dict) and s_cfg.get("enabled", True):
                            mcp_servers_list.append(s_name)
        except Exception:
            pass

        return {
            "name": "Hermes Agent (Terminal Nativo - Perfil Shaula)",
            "profile": self.profile,
            "connected": connected,
            "has_token": has_token,
            "provider": self.provider,
            "model": self.model,
            "inference_base": self.inference_base,
            "ollama_fallback": ollama_active,
            "host_hardware_serials_indexed": len(self.collect_host_serials()),
            "native_cli": True,
            "mcp_servers": mcp_servers_list,
            "toolsets": ["terminal", "file", "python", "web", "kanban", "memory"]
        }

    def reset_session(self) -> str:
        """Reinicia a sessão de conversação gerando novo identificador."""
        self.session_name = f"shaula_dash_{str(uuid.uuid4())[:8]}"
        return self.session_name

    def run_native_agent(self, query: str, session_name: Optional[str] = None, timeout_sec: int = 120) -> Dict[str, Any]:
        """
        Executa o Agente Hermes nativo com motor completo de ferramentas (terminal, arquivos,
        python, web, kanban, memória, etc.) sem abrir emulador de terminal no navegador.
        Reproduz integralmente as capacidades do terminal Hermes sob o perfil de Shaula.
        """
        cli_candidates = [
            "/home/kodansha/.hermes/hermes-agent/.venv/bin/hermes",
            shutil.which("hermes")
        ]
        hermes_cli = next((c for c in cli_candidates if c and Path(c).is_file()), None)
        if not hermes_cli:
            raise FileNotFoundError("Binário do Hermes Agent CLI não encontrado no sistema.")

        s_name = session_name or self.session_name
        cmd = [
            hermes_cli,
            "chat",
            "-c", s_name,
            "--create-if-missing",
            "--query-file", "-",
            "--oneshot",
            "-Q",
            "--format", "stream-json",
            "--yolo",
            "--source", "shaula"
        ]

        env = dict(os.environ, HERMES_HOME=str(NASH_PROFILE_DIR))

        try:
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd="/home/kodansha/shaula"
            )
            if proc.stdin:
                proc.stdin.write(query)
                proc.stdin.close()
        except Exception as e:
            return {
                "success": False,
                "error": f"Falha ao iniciar processo do Hermes: {str(e)}",
                "reply": f"❌ Erro ao iniciar processo Hermes nativo: {str(e)}",
                "tools": []
            }

        tools_used = []
        text_chunks = []
        result_text = ""
        captured_session_id = ""

        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    ev_type = ev.get("type")
                    if ev_type == "tool_use":
                        tools_used.append({
                            "tool": ev.get("name"),
                            "input": ev.get("input"),
                            "timestamp": ev.get("timestamp")
                        })
                    elif ev_type == "tool_result":
                        tool_name = ev.get("name")
                        target_tool = None
                        for t in reversed(tools_used):
                            if t.get("tool") == tool_name and "output" not in t:
                                target_tool = t
                                break
                        if not target_tool and tools_used:
                            target_tool = tools_used[-1]
                        if target_tool is not None:
                            target_tool["output"] = ev.get("output")
                            target_tool["is_error"] = ev.get("is_error", False)
                            target_tool["duration_ms"] = ev.get("duration_ms", 0)
                    elif ev_type == "text":
                        text_chunks.append(ev.get("text", ""))
                    elif ev_type == "result":
                        result_text = ev.get("text", "")
                        captured_session_id = ev.get("session_id", "")
                except Exception:
                    pass

            proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            proc.kill()
            return {
                "success": False,
                "error": f"Execução do Hermes excedeu o timeout de {timeout_sec}s.",
                "reply": f"⚠️ A execução da tarefa pelo Hermes excedeu o tempo limite ({timeout_sec}s).",
                "tools": tools_used
            }

        final_reply = (result_text or "".join(text_chunks)).strip()
        if not final_reply and proc.returncode != 0:
            stderr_out = proc.stderr.read()
            final_reply = f"Erro na execução do Hermes (exit code {proc.returncode}): {stderr_out[:300]}"
        elif not final_reply and tools_used:
            final_reply = "Ação concluída com sucesso com as ferramentas executadas acima."

        if captured_session_id:
            self.session_name = captured_session_id

        # Formatar as execuções de ferramentas para apresentação rica em Markdown no chat
        formatted_reply = final_reply
        if tools_used:
            tool_sections = []
            for t in tools_used:
                t_name = t.get("tool", "ferramenta")
                t_inp = t.get("input", {})
                if isinstance(t_inp, dict):
                    inp_items = []
                    for k, v in t_inp.items():
                        val_str = str(v).replace("\n", " ")
                        if len(val_str) > 120:
                            val_str = val_str[:115] + "..."
                        inp_items.append(f"**{k}:** `{val_str}`")
                    inp_str = " | ".join(inp_items) if inp_items else "{}"
                else:
                    inp_str = f"`{str(t_inp)}`"

                raw_out = t.get("output", "")
                display_out = raw_out
                if isinstance(raw_out, str) and raw_out.strip().startswith("{") and raw_out.strip().endswith("}"):
                    try:
                        p_out = json.loads(raw_out)
                        if isinstance(p_out, dict) and "output" in p_out:
                            display_out = p_out.get("output", "")
                            if p_out.get("error"):
                                display_out += f"\nErro: {p_out['error']}"
                    except Exception:
                        pass

                display_out_str = str(display_out).strip()
                if len(display_out_str) > 1200:
                    display_out_str = display_out_str[:1180] + "\n... [saída truncada]"

                dur_str = f" ({t.get('duration_ms', 0)}ms)" if t.get("duration_ms") else ""
                status_icon = "❌" if t.get("is_error") else "✓"

                tool_sections.append(
                    f"**🔧 `{t_name}`** {status_icon}{dur_str}\n"
                    f"- **Parâmetros:** {inp_str}\n"
                    f"- **Saída:**\n```text\n{display_out_str}\n```"
                )

            tool_summary_md = (
                f"<details class=\"hermes-tool-actions\">\n"
                f"<summary>🛠️ <strong>Ações do Agente Hermes</strong> ({len(tools_used)} ferramenta(s) executada(s))</summary>\n\n"
                + "\n\n---\n\n".join(tool_sections) +
                f"\n\n</details>\n\n"
            )
            formatted_reply = f"{tool_summary_md}{final_reply}"

        return {
            "success": proc.returncode == 0 or bool(final_reply),
            "reply": formatted_reply,
            "raw_text": final_reply,
            "tools": tools_used,
            "session_id": captured_session_id or s_name
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
        Varre o Vault Nashetanea e Vault Shaula para detectar notas existentes
        que possam referenciar a mesma máquina, ativo ou serial, impedindo duplicações.
        """
        clean_q = query.strip().lower()
        tokens = [t for t in re.split(r"[\s,\-_/]+", clean_q) if len(t) > 2]

        matches: List[Dict[str, Any]] = []

        # 1. Buscar no Vault Nashetanea
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
                    "source": "vault_nashetanea",
                    "preview": body[:180].strip()
                })

        # 2. Buscar no Vault Shaula
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
        if self.access_token and not self.nous_disabled:
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
                    "max_tokens": 1200
                }
                r = requests.post(f"{self.inference_base}/chat/completions", headers=headers, json=payload, timeout=25)
                if r.status_code == 200:
                    data = r.json()
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "").strip()
                elif r.status_code in [401, 402, 403]:
                    # Tentar renovação automática via Hermes CLI no perfil nash
                    if self.refresh_token():
                        try:
                            headers["Authorization"] = f"Bearer {self.access_token}"
                            r_retry = requests.post(f"{self.inference_base}/chat/completions", headers=headers, json=payload, timeout=25)
                            if r_retry.status_code == 200:
                                data = r_retry.json()
                                choices = data.get("choices", [])
                                if choices:
                                    return choices[0].get("message", {}).get("content", "").strip()
                        except Exception:
                            pass
                    self.nous_disabled = True
            except Exception:
                pass

        # 2. Ollama local (usando modelos reais instalados no host)
        for ollama_model in ["qwen2.5:3b", "qwen2.5:1.5b", "gemma2:2b", "phi3:mini"]:
            try:
                r = requests.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={
                        "model": ollama_model,
                        "prompt": f"{sys_msg}\n\nUsuário: {prompt}",
                        "stream": False,
                        "options": {"temperature": 0.2, "num_predict": 750}
                    },
                    timeout=20
                )
                if r.status_code == 200:
                    resp = r.json().get("response", "").strip()
                    if resp:
                        return resp
            except Exception:
                continue

        # 3. Fallback Heurístico Estruturado da Operadora
        return f"""### ☤ Shaula (Perfil Hermes Nash - Modo Operacional Local)

- **Requisição:** `{prompt[:180]}...`
- **Vault Principal (`{VAULT_PATH}`):** Conectado e supervisionado.
- **Vault Shaula (aux) (`{settings_mgr.get_aux_path()}`):** Conectado e integrado.
- **Status:** Operações de categorização, integridade e criação de notas mantidas via motor determinístico.
"""

    def process_smart_note(
        self,
        input_text: str,
        title_override: Optional[str] = None,
        dest_folder: str = "auto",
        force: bool = False,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Processamento Cognitivo Completo:
        1. Verificação anti-duplicação no Vault Nashetanea e Shaula
        2. Cruzamento com telemetria e hardware se aplicável
        3. Dedução de informações parciais (Setor, Nome Oficial, Tag Ativo Fixo, Especificações Técnicas)
        4. Avaliação e categorização automática da pasta de destino com base na literatura PKM
        5. Criação e abertura imediata do documento técnico formal em Markdown
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

        # 3. Montar prompt de dedução técnica para a Operadora Hermes
        hw_context = f"\nDados de hardware local correspondente: {json.dumps(hw_match, ensure_ascii=False)}" if hw_match else ""
        known_vault_refs = [m["title"] for m in dup_check.get("matches", [])]
        vault_context = f"\nReferências de contexto encontradas nos Vaults: {known_vault_refs}" if known_vault_refs else ""

        prompt = f"""
O usuário inseriu o seguinte dado ou descrição técnica (que pode ser parcial, informal ou um identificador):
"{clean_input}"
{hw_context}
{vault_context}

Como especialista técnico, engenheiro e OPERADORA DO VAULT SHAULA, processe essa informação com rigor:
1. Deduza ou extraia:
   - **Nome Oficial e Padronizado do Ativo/Máquina/Equipamento**
   - **Setor / Linha / Localização Fabril ou Operacional** (ex: se for injetora1 da injeção plastica -> Setor: Injeção Plástica)
   - **Número / Código Operacional da Máquina** (ex: INJ-01 / MQ-001)
   - **Tag de Ativo Fixo / Patrimônio** (ex: AT-INJ-001 / PAT-2026-001)
   - **Fabricante e Modelo Provável ou de Referência no Mercado**
   - **Especificações Técnicas Essenciais** (dimensões, capacidades, potências, pressões, vazões, etc.)
2. Avalie e defina a PASTA DE DESTINO e CATEGORIA da nota seguindo os conceitos consolidados da literatura de Personal Knowledge Management (PARA, Johnny Decimal e taxonomia Obsidian):
   - Para máquinas fabris, equipamentos industriais, componentes, TI e hardware:
     categoria: "Ativos e Equipamentos"
     pasta_destino: "03 - Knowledge/Ativos"
   - Para procedimentos operacionais padrão (POP), instruções de trabalho (IT), manuais e normas:
     categoria: "Procedimentos e Normas"
     pasta_destino: "03 - Knowledge/Procedimentos"
   - Para setores industriais, departamentos, linhas produtivas ou utilidades:
     categoria: "Setores e Linhas"
     pasta_destino: "03 - Knowledge/Setores"
   - Para laudos, vistorias, diagnósticos, medições técnicas e auditorias:
     categoria: "Diagnósticos e Auditorias"
     pasta_destino: "01 - Verification"
   - Para rotinas periódicas, cronogramas de manutenção preventiva e checklists:
     categoria: "Tarefas e Agendamentos"
     pasta_destino: "02 - Tasks & Schedules"
   - Para anotações breves preliminares não categorizadas:
     categoria: "Captura Rápida"
     pasta_destino: "00 - Inbox"
3. Elabore um documento técnico completo no padrão Obsidian Markdown contendo:
   - Frontmatter YAML com:
     title: "Nome Oficial Padronizado"
     date: "{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
     setor: "Nome do Setor"
     numero_maquina: "Código"
     ativo_fixo: "Tag Patrimonial"
     categoria: "Nome da Categoria Escolhida"
     pasta_destino: "Pasta Escolhida"
     tags: [ativo, setor, equipamento, manutencao]
     status: operacional
   - Título H1 formal
   - Resumo Executivo da Identificação e Localização
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

        # 4. Avaliar pasta de destino segundo a literatura ou escolha do usuário
        chosen_folder = dest_folder.strip() if dest_folder else "auto"
        detected_category = "Ativos e Equipamentos"

        folder_match = re.search(r'pasta_destino:\s*["\']?([^"\']+)["\']?', generated_body)
        cat_match = re.search(r'categoria:\s*["\']?([^"\']+)["\']?', generated_body)
        if cat_match:
            detected_category = cat_match.group(1).strip()

        if chosen_folder.lower() in ["auto", "", "none", "auto-detectar"]:
            if folder_match and folder_match.group(1).strip():
                chosen_folder = folder_match.group(1).strip()
            else:
                # Classificação heurística complementar
                inp_lower = (clean_input + " " + extracted_title).lower()
                if any(w in inp_lower for w in ["pop", "procedimento", "norma", "manual", "instrucao", "guia"]):
                    chosen_folder = "03 - Knowledge/Procedimentos"
                    detected_category = "Procedimentos e Normas"
                elif any(w in inp_lower for w in ["setor", "linha", "departamento", "galpao", "utilidades"]):
                    chosen_folder = "03 - Knowledge/Setores"
                    detected_category = "Setores e Linhas"
                elif any(w in inp_lower for w in ["laudo", "inspecao", "teste", "diagnostico", "auditoria", "verificacao"]):
                    chosen_folder = "01 - Verification"
                    detected_category = "Diagnósticos e Auditorias"
                elif any(w in inp_lower for w in ["cronograma", "rotina", "preventiva", "agendamento"]):
                    chosen_folder = "02 - Tasks & Schedules"
                    detected_category = "Tarefas e Agendamentos"
                else:
                    chosen_folder = "03 - Knowledge/Ativos"
                    detected_category = "Ativos e Equipamentos"

        # Garantir diretório de destino criado
        target_dir = VAULT_PATH / chosen_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        rel_filename = f"{chosen_folder.rstrip('/')}/{safe_filename}.md"

        # Se o modelo não gerou frontmatter, compor formalmente
        if not generated_body.startswith("---"):
            full_content = f"""---
title: "{extracted_title}"
date: "{now_str}"
categoria: "{detected_category}"
pasta_destino: "{chosen_folder}"
tags:
  - ativo
  - equipamento
  - hermes
status: operacional
---

# {extracted_title}

> Gerado pela **Operadora do Vault Nashetanea** a partir de: `{clean_input}` | [[Shaula Home]]

---

{generated_body}
"""
        else:
            full_content = generated_body

        # Se for modo de simulação / rascunho para aprovação prévia, retorna sem gravar
        if dry_run:
            return {
                "success": True,
                "duplicate_detected": False,
                "title": extracted_title,
                "category": detected_category,
                "folder_used": chosen_folder,
                "safe_filename": safe_filename,
                "rel_path": rel_filename,
                "content": full_content,
                "hardware_match": hw_match
            }

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
            "category": detected_category,
            "folder_used": chosen_folder,
            "hardware_match": hw_match,
            "created_note": created_note
        }

    def operator_chat(self, user_message: str, history: Optional[List[Dict[str, str]]] = None, session_name: Optional[str] = None) -> str:
        """
        Interação de Chat com o Agente Hermes Nativo no perfil Shaula.
        Executa o motor real com todas as ferramentas nativas (terminal, arquivos,
        python, web, memória, kanban) reproduzindo a mesma capacidade do terminal Hermes.
        """
        try:
            target_session = session_name or self.session_name
            res = self.run_native_agent(user_message, session_name=target_session)
            if res.get("reply"):
                return res["reply"]
        except Exception:
            pass

        return self._fallback_chat(user_message)

    def _fallback_chat(self, user_message: str) -> str:
        """Fallback contextual direto de inferência caso o processo nativo falhe."""
        self._load_credentials()

        # Coletar estatísticas reais do Vault Principal
        vault_files = [f for f in VAULT_PATH.rglob("*.md") if ".backups" not in f.parts]
        vault_notes_count = len(vault_files)

        # Coletar estatísticas reais do Vault Shaula
        aux_path = settings_mgr.get_aux_path()
        aux_notes_count = 0
        aux_status = "Desativado ou Inexistente"
        if aux_path.exists():
            aux_files = [f for f in aux_path.rglob("*.md") if not f.name.startswith(".")]
            aux_notes_count = len(aux_files)
            aux_status = f"Ativo em '{aux_path}' ({aux_notes_count} notas)"

        # Coletar telemetria do Host
        try:
            cpu_pct = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            mem_used_gb = round(mem.used / (1024**3), 1)
            mem_total_gb = round(mem.total / (1024**3), 1)
            disk = psutil.disk_usage("/")
            disk_pct = disk.percent
        except Exception:
            cpu_pct = 0
            mem_used_gb = 0
            mem_total_gb = 0
            disk_pct = 0

        serials_count = len(self.collect_host_serials())

        system_prompt = f"""Você é NASHETANEA (NASH) — Matriz Orquestradora, Copiloto Técnico de Manutenção Industrial e Curadora de Governança de Dados, atuando no Centro de Comando e Dashboard Shaula com o perfil oficial Hermes 'nash' (~/.hermes/profiles/nash).

CONSCIÊNCIA SISTÊMICA OBRIGATÓRIA:
1. IDENTIDADE E POSTURA: Você opera como Shaula no ecossistema Shaula. Sua linguagem é profissional, técnica, assertiva, precisa e livre de rodeios, introduções prolixas ou clichês. Você tem controle e supervisão ativa de documentações técnicas, fichas de máquinas/ativos, tarefas recorrentes e auditorias de integridade.
2. VAULT PRINCIPAL EXCLUSIVO DO SHAULA:
   - Caminho: `{VAULT_PATH}`
   - Total de Notas: {vault_notes_count} documentos
   - Estrutura de Diretórios Categóricos: [00 - Inbox, 01 - Verification, 02 - Tasks & Schedules, 03 - Knowledge (Ativos, Procedimentos, Setores), 04 - System]
   - Este vault é exclusivo do Shaula e sincronizável via Git.
3. VAULT CANÔNICO DE NASHETANEA (INTEGRAÇÃO E INTEROPERABILIDADE):
   - Caminho: `{aux_path}`
   - Estado: {aux_status}
   - Total de Notas Disponíveis: {aux_notes_count}
   - Função: Consulta, leitura direta na árvore, importação, exportação e sincronização contínua entre os ambientes.
4. TELEMETRIA DO HOST E HARDWARE:
   - CPU: {cpu_pct}% | RAM: {mem_used_gb} GB usados de {mem_total_gb} GB | Disco Root: {disk_pct}%
   - Dispositivos de hardware/seriais indexados no host: {serials_count} identificadores.

INSTRUÇÕES DE RESPOSTA:
- Responda sempre em Português.
- Use formatação Markdown rica e inclua [[Wikilinks]] sempre que mencionar notas existentes, ativos ou conceitos técnicos de ambos os Vaults.
- Se o usuário perguntar sobre o sistema, notas, equipamentos ou arquitetura, demonstre total domínio do Vault Nashetanea e do Vault Shaula.
- Ao sugerir criação de notas, oriente sobre a categorização correta baseada na literatura técnica de Personal Knowledge Management (PKM)."""

        return self.ask(user_message, system_prompt=system_prompt)


hermes_agent = HermesAgent()
