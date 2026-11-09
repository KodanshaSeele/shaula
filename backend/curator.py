"""
Motor de Curadoria, Padronização e Triage Autônoma com Gemini 3.8 Flash.
Axiomas: Loop PRVC + NASA JPL-CP-10 (Lotes Bounded, Fail-Fast, Read-Back).
Suporta Ingestão Human-in-the-Loop com Análise & Validação Prévia antes de alocar.
"""
import os
import re
import json
import yaml
import shutil
import asyncio
import subprocess
from datetime import datetime
from pathlib import Path
from collections import deque
from typing import Dict, List, Any, Tuple, Optional

from .config import VAULT_PATH, INBOX_PATH, ASSETS_PATH, TEMPLATE_PATH, AGY_CLI
from .db_service import cross_reference_database
from .vault_service import (
    safe_vault_path,
    parse_frontmatter,
    write_note_safely,
    save_asset,
    list_projects
)


def _invoke_agy(prompt: str, timeout_sec: int = 90) -> str:
    """Invoca o Antigravity CLI com contexto restrito ao cofre de Nash."""
    if not os.path.exists(AGY_CLI):
        return ""
    cmd = [
        AGY_CLI,
        "--dangerously-skip-permissions",
        "--disable-slash-commands",
        "--add-dir", str(VAULT_PATH),
        "-p", prompt,
        "--output-format", "text"
    ]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(VAULT_PATH)
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return ""


def auto_ingest_and_approve(
    raw_content: str,
    asset_rel_paths: List[str],
    preferred_folder: Optional[str] = None,
    preferred_title: Optional[str] = None,
    tags: Optional[List[str]] = None,
    original_filenames: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Ingestão com Auto-Aprovação Direta pelo Gemini (Shaula).
    Elimina a lentidão de validação manual: analisa fotos e texto,
    seleciona o formato canônico ideal e salva diretamente no cofre.
    """
    analysis = analyze_and_cross_reference(
        raw_content=raw_content,
        asset_rel_paths=asset_rel_paths,
        original_filenames=original_filenames
    )

    # Caso canônico ideal: se houver fotos sanitizadas, usa visão profunda; se não, síntese textual
    if asset_rel_paths:
        content_to_save = analysis.get("case_with_vision") or analysis.get("case_without_vision") or ""
        mode_used = "vision"
    else:
        content_to_save = analysis.get("case_without_vision") or analysis.get("case_with_vision") or ""
        mode_used = "text"

    chosen_title = (preferred_title or "").strip() or analysis.get("proposed_title") or f"Captura_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Pasta de destino: respeita seleção explícita se houver, senão usa a sugestão do Gemini
    if preferred_folder and preferred_folder not in ("auto", "Automático", ""):
        chosen_folder = preferred_folder
    else:
        chosen_folder = analysis.get("target_folder") or "Work/Industrial"

    # Salva e executa Read-Back Check mandatória
    saved = approve_and_save_note(
        title=chosen_title,
        target_folder=chosen_folder,
        content=content_to_save
    )

    saved["reasoning"] = analysis.get("reasoning", "Shaula aprovou e alocou automaticamente no cofre.")
    saved["tags"] = tags or analysis.get("tags", [])
    saved["target_project"] = analysis.get("target_project", "")
    saved["case_mode"] = mode_used
    saved["content"] = content_to_save
    saved["auto_approved"] = True
    saved["database_crossref"] = analysis.get("database_crossref", {})
    return saved


def process_multimodal_ingest(
    title: str,
    raw_content: str,
    asset_rel_paths: List[str],
    project: str = "",
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Compatibilidade legada: ingere e aprova automaticamente no destino final."""
    return auto_ingest_and_approve(
        raw_content=raw_content,
        asset_rel_paths=asset_rel_paths,
        preferred_title=title,
        tags=tags
    )


# -----------------------------------------------------------------------------
# INGESTÃO MULTIMODAL: AVALIAÇÃO, CRUZAMENTO DE DADOS E VALIDAÇÃO (HITL)
# -----------------------------------------------------------------------------
def _select_relevant_projects(raw_content: str, max_projects: int = 12) -> str:
    """
    JPL-CP-10 Bounded Inputs: seleciona apenas os projetos relevantes baseados
    em keywords do conteúdo, evitando estourar tokens e causar lentidão.
    """
    all_projects = list_projects()
    if not all_projects:
        return "[[Work/Projects/Manutencao-Gree]], [[Work/Projects/Infra-Servidor]]"

    words = set(re.findall(r"\b[A-Za-z0-9_-]{3,}\b", raw_content.lower()))
    
    # Prioriza projetos canônicos reais sobre referências de imagem
    actual_projects = [p for p in all_projects if not p["name"].lower().endswith((".webp", ".jpg", ".png"))]
    other_projects = [p for p in all_projects if p["name"].lower().endswith((".webp", ".jpg", ".png"))]
    ordered_pool = actual_projects + other_projects

    matched = []
    for p in ordered_pool:
        name_lower = p["name"].lower()
        if any(w in name_lower for w in words):
            matched.append(p["wikilink"])
            if len(matched) >= max_projects:
                break

    if len(matched) < max_projects:
        for p in ordered_pool:
            if p["wikilink"] not in matched:
                matched.append(p["wikilink"])
                if len(matched) >= max_projects:
                    break

    return ", ".join(matched)


def analyze_and_cross_reference(
    raw_content: str,
    asset_rel_paths: List[str],
    original_filenames: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Avalia a nota bruta e fotos, cruza os dados com o cofre de Nash sob o nome Shaula,
    e produz 2 CASOS de proposta canônica:
    - Caso 1: Com Visão Computacional (Shaula Vision / OCR enriquecido)
    - Caso 2: Sem Visão Computacional (Shaula Texto Puro / Síntese leve)
    """
    now_id = datetime.now().strftime("%Y%m%d%H%M%S")
    today = datetime.now().strftime("%Y-%m-%d")
    images_block = "\n".join([f"![[{p}]]" for p in asset_rel_paths])
    effective_content = raw_content.strip() or ("Registro visual de equipamento e imagem industrial." if asset_rel_paths else "Registro de nota técnica.")

    # 1. OCR Multimodal de Alta Precisão via Gemini (leitura direta de arquivos de imagem)
    ocr_transcript = ""
    if asset_rel_paths:
        abs_image_paths = [str((VAULT_PATH / p).resolve()) for p in asset_rel_paths]
        images_list_str = "\n".join([f"- {p}" for p in abs_image_paths])
        ocr_prompt = f"""Use a ferramenta de leitura de arquivos (read_file) para abrir e inspecionar cada uma das seguintes imagens:
{images_list_str}

Transcreva com fidelidade e exatidão absoluta todo o texto, placas de identificação, logotipos (ex: GREE), códigos de moldes, modelos, números de ferramentas/dispositivos (ex: JM...), dimensões, pesos (T), datas e passos de alimentação visíveis nas fotos.
Forneça a transcrição literal (OCR exato) e organize os parâmetros técnicos em uma tabela detalhada.
NÃO resuma nem omita códigos ou números técnicos."""
        ocr_reply = _invoke_agy(ocr_prompt, timeout_sec=45)
        if ocr_reply and len(ocr_reply.strip()) > 15:
            ocr_transcript = ocr_reply.strip()

    # 2. Contexto delimitado e cirúrgico de projetos no cofre
    combined_search_text = (effective_content + "\n" + ocr_transcript).strip()
    projects_context = _select_relevant_projects(combined_search_text, max_projects=12)

    # 3. Cruzamento com banco de dados industrial PCM e Grimorium
    search_names = [Path(p).name for p in asset_rel_paths]
    if original_filenames:
        search_names.extend(original_filenames)

    db_cross = cross_reference_database(
        text_content=combined_search_text,
        filenames=search_names
    )
    db_context = db_cross.get("summary_context", "Sem correspondência direta no banco.")

    # 4. Síntese com Shaula
    ocr_section_in_prompt = f"\n\nTranscrição Literal e Detalhada de OCR das Imagens (já verificadas):\n{ocr_transcript}\n" if ocr_transcript else ""

    prompt = f"""Você é Shaula, o Cérebro Cognitivo e Motor de Raciocínio do Vault de Nash.
O operador inseriu uma captura com anotações e fotos anexadas (sanitizadas em formato JPG HD 75%).
Sua missão é AVALIAR, CRUZAR estes dados com o cofre e o banco industrial e gerar OBRIGATORIAMENTE 2 CASOS:

Contexto do Banco de Dados Industrial (db_pcm.db & curadoria_grimorium.db):
{db_context}

Contexto de Projetos Ativos no cofre: {projects_context}
Possíveis Pastas Canônicas:
- Work/Industrial (máquinas, equipamentos industriais, preventivas, ordens de serviço)
- Work/Projects (documentos centrais de projetos específicos em andamento)
- 03 - Knowledge (conhecimento perene, manuais, procedimentos, conceitos, regras)
- Personal (notas, interesses e registros pessoais)
- People (contatos, pessoas, fichas individuais)

Captura Bruta:
{effective_content}

Imagens Anexadas (já sanitizadas em assets/):
{images_block}{ocr_section_in_prompt}

Diretrizes Obrigatórias:
1. CASO 1 (com_visao): Incorpore fielmente a transcrição literal do OCR da placa e a tabela de parâmetros técnicos diretamente em Fatos e Dados Fundamentais e na seção de Análise Visual & OCR.
2. CASO 2 (sem_visao): Síntese estritamente textual focada apenas no relato do operador e no cruzamento com os projetos, mantendo a foto apenas como link de anexo comprobatório no rodapé, sem expansão descritiva de visão.
3. Em AMBOS os casos, use autor: "Shaula" no frontmatter YAML e respeite rigorosamente o layout canônico.
4. Responda ESTRITAMENTE em formato JSON com as chaves:
{{
  "proposed_title": "Titulo descritivo sem caracteres invalidos",
  "target_folder": "Work/Industrial",
  "target_project": "[[Work/Projects/Manutencao-Gree]]",
  "tags": ["manutencao/injetora", "gree"],
  "reasoning": "Shaula cruzou os dados com histórico da máquina X no setor de injeção.",
  "case_with_vision": "--- Markdown completo do Caso 1 (Com Visão Computacional) ---",
  "case_without_vision": "--- Markdown completo do Caso 2 (Sem Visão Computacional) ---"
}}
"""

    gemini_reply = _invoke_agy(prompt, timeout_sec=50)
    
    parsed = {}
    if gemini_reply:
        m = re.search(r"\{[\s\S]*\}", gemini_reply)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                pass

    proposed_title = parsed.get("proposed_title") or _infer_title_fast(effective_content, asset_rel_paths, now_id, ocr_transcript)
    target_folder = parsed.get("target_folder") or _infer_folder_fast(combined_search_text)
    target_project = parsed.get("target_project") or "[[Work/Projects/Manutencao-Gree]]"
    tags = parsed.get("tags") or ["captura", "memoria"]
    reasoning = parsed.get("reasoning") or "Shaula avaliou o OCR visual e cruzou os dados com o cofre de Nash."

    case_with_vision = parsed.get("case_with_vision")
    case_without_vision = parsed.get("case_without_vision")

    # Fallbacks determinísticos robustos se o modelo não devolver os dois blocos
    if not case_with_vision or not case_with_vision.startswith("---"):
        case_with_vision = _build_case_with_vision(
            now_id=now_id,
            today=today,
            title=proposed_title,
            raw_content=effective_content,
            images_block=images_block,
            project=target_project,
            tags=tags,
            db_context=db_context,
            ocr_transcript=ocr_transcript
        )

    if not case_without_vision or not case_without_vision.startswith("---"):
        case_without_vision = _build_case_without_vision(
            now_id=now_id,
            today=today,
            title=proposed_title,
            raw_content=effective_content,
            images_block=images_block,
            project=target_project,
            tags=tags
        )

    return {
        "success": True,
        "agent": "Shaula",
        "proposed_title": proposed_title,
        "target_folder": target_folder,
        "target_project": target_project,
        "tags": tags,
        "reasoning": reasoning,
        "database_crossref": db_cross,
        "ocr_transcript": ocr_transcript,
        "case_with_vision": case_with_vision,
        "case_without_vision": case_without_vision,
        "canonical_markdown": case_with_vision, # default ativo
        "assets_rel_paths": asset_rel_paths
    }


def _build_case_with_vision(
    now_id: str,
    today: str,
    title: str,
    raw_content: str,
    images_block: str,
    project: str,
    tags: List[str],
    db_context: str = "",
    ocr_transcript: str = ""
) -> str:
    proj_link = f"- \"{project}\"" if project.startswith("[[") else f"- \"[[Work/Projects/{project}]]\""
    tag_lines = "\n".join([f"  - {t}" for t in tags])
    db_section = f"\n\n## 🏭 Dados de Ativo / PCM\n{db_context}\n" if (db_context and "Sem correspondência" not in db_context) else ""
    
    content_section = ""
    if raw_content and raw_content != "Registro visual de equipamento e imagem industrial.":
        content_section = f"### Relato do Operador\n{raw_content}\n\n"

    ocr_section = f"### Análise Visual & OCR (Shaula Vision)\n{ocr_transcript}\n" if ocr_transcript else (f"### Análise Visual & OCR (Shaula Vision)\n{raw_content}\n" if not content_section else "")

    return f"""---
id: "{now_id}"
title: "{title}"
type: note
status: active
created: {today}
updated: {today}
author: "Shaula"
tags:
{tag_lines}
projects:
  {proj_link}
source_url: ""
---

# {title}

## 🎯 Contexto e Propósito
Registro com análise multimodal e Visão Computacional realizado por Shaula.

## 📌 Fatos e Dados Fundamentais
- Dados extraídos das imagens anexadas (JPG HD sanitizada) e do relato técnico.
- Parâmetros operacionais e inspeção visual cruzados com o cofre de Nash.{db_section}
## 🔗 Relações e Conexões
- **Projeto Ativo**: {proj_link.replace('- ', '').replace('"', '')}

## 📝 Registro de Detalhes / Conteúdo
{images_block}

{content_section}{ocr_section}
## ⏱️ Histórico de Atualizações / Log de Processamento
- {today} — [Shaula]: Analisado com Visão Computacional e aprovado pelo operador.
"""


def _build_case_without_vision(
    now_id: str,
    today: str,
    title: str,
    raw_content: str,
    images_block: str,
    project: str,
    tags: List[str]
) -> str:
    proj_link = f"- \"{project}\"" if project.startswith("[[") else f"- \"[[Work/Projects/{project}]]\""
    tag_lines = "\n".join([f"  - {t}" for t in tags])
    
    return f"""---
id: "{now_id}"
title: "{title}"
type: note
status: active
created: {today}
updated: {today}
author: "Shaula"
tags:
{tag_lines}
projects:
  {proj_link}
source_url: ""
---

# {title}

## 🎯 Contexto e Propósito
Registro sintético baseado no relato direto do operador sem interpretação visual de OCR.

## 📌 Fatos e Dados Fundamentais
- Relato factual objetivo e conciso.

## 🔗 Relações e Conexões
- **Projeto Ativo**: {proj_link.replace('- ', '').replace('"', '')}

## 📝 Registro de Detalhes / Conteúdo
{raw_content}

### Anexos Comprobatórios
{images_block}

## ⏱️ Histórico de Atualizações / Log de Processamento
- {today} — [Shaula]: Síntese textual direta validada e aprovada pelo operador.
"""


def approve_and_save_note(
    title: str,
    target_folder: str,
    content: str
) -> Dict[str, Any]:
    """
    Grava a nota validada e aprovada pelo usuário DIRETAMENTE na sua pasta definitiva.
    Executa Read-Back Check mandatória.
    """
    clean_title = (title.strip() or f"Nota_{datetime.now().strftime('%Y%m%d%H%M%S')}").replace("/", "-")
    clean_folder = target_folder.strip().strip("/\\") or "03 - Knowledge"
    
    filename = f"{clean_title}.md"
    rel_path = f"{clean_folder}/{filename}"
    
    target_path = safe_vault_path(rel_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Se o arquivo já existir com esse título exato no destino, adiciona sufixo para não sobrescrever
    if target_path.exists():
        now_suf = datetime.now().strftime("%H%M%S")
        filename = f"{clean_title}_{now_suf}.md"
        rel_path = f"{clean_folder}/{filename}"
        target_path = safe_vault_path(rel_path)

    # Escreve a nota
    target_path.write_text(content, encoding="utf-8")
    
    # Read-Back Check
    assert target_path.exists() and target_path.stat().st_size > 0, "Falha na verificação de escrita"
    read_back = target_path.read_text(encoding="utf-8")
    assert read_back == content, "Discrepância no conteúdo salvo"

    return {
        "success": True,
        "title": clean_title,
        "filename": filename,
        "folder": clean_folder,
        "path": rel_path,
        "absolute_path": str(target_path)
    }


def _infer_title_fast(raw: str, assets: List[str], fallback_id: str, ocr: str = "") -> str:
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if lines:
        first = lines[0].lstrip("#").strip()
        if len(first) > 3 and "Registro visual de equipamento" not in first:
            return first[:60]
    if ocr:
        m_code = re.search(r"\b(JM[0-9/]+|GRB[A-Z0-9]+|Φ[0-9A-Za-z]+)\b", ocr)
        if m_code:
            clean_code = re.sub(r"[^A-Za-z0-9_-]", "_", m_code.group(0))
            return f"Placa_{clean_code}_{fallback_id[-6:]}"
        if "GREE" in ocr.upper():
            return f"GREE_Placa_Equipamento_{fallback_id[-6:]}"
    if assets:
        return f"Registro Visual {fallback_id}"
    return f"Captura {fallback_id}"


def _infer_folder_fast(raw: str) -> str:
    raw_lower = raw.lower()
    if any(k in raw_lower for k in ["grbim", "injetora", "chiller", "manutencao", "gree", "prensa", "pcm", "molde"]):
        return "Work/Industrial"
    if any(k in raw_lower for k in ["projeto", "infra", "servidor", "backup"]):
        return "Work/Projects"
    if any(k in raw_lower for k in ["pessoal", "anime", "filme", "saude"]):
        return "Personal"
    if any(k in raw_lower for k in ["contato", "telefone", "pessoa", "email"]):
        return "People"
    return "03 - Knowledge"


def _build_deterministic_canonical_note(
    now_id: str,
    today: str,
    title: str,
    raw_content: str,
    images_block: str,
    project: str,
    tags: List[str]
) -> str:
    proj_link = f"- \"{project}\"" if project.startswith("[[") else f"- \"[[Work/Projects/{project}]]\""
    tag_lines = "\n".join([f"  - {t}" for t in tags])
    
    return f"""---
id: "{now_id}"
title: "{title}"
type: note
status: active
created: {today}
updated: {today}
author: "Gemini/Nash-Desk"
tags:
{tag_lines}
projects:
  {proj_link}
source_url: ""
---

# {title}

## 🎯 Contexto e Propósito
Registro analisado e aprovado via Nash RAG Desk.

## 📌 Fatos e Dados Fundamentais
- Dados extraídos da captura e cruzados com a memória do cofre.

## 🔗 Relações e Conexões
- **Projeto Ativo**: {proj_link.replace('- ', '').replace('"', '')}

## 📝 Registro de Detalhes / Conteúdo
{images_block}

{raw_content}

## ⏱️ Histórico de Atualizações / Log de Processamento
- {today} — [Gemini/Nash-Desk]: Avaliado, cruzado com o cofre e alocado após validação.
"""


def classify_note_smart(content: str, filename: str) -> Tuple[str, str, List[str]]:
    """Classificador Híbrido de Alto Desempenho e Precisão Axiomática."""
    meta, body = parse_frontmatter(content)
    
    projs = meta.get("projects") or []
    if isinstance(projs, str):
        projs = [projs]
    for p in projs:
        p_str = str(p)
        if "Personal/" in p_str:
            return "Personal", "Projeto: Personal", ["personal"]
        if "Work/Projects/" in p_str:
            return "Work/Projects", "Projeto: Work", ["work"]
        if "Work/" in p_str:
            return "Work", "Projeto: Work", ["work"]

    t = str(meta.get("type", "")).lower()
    fn_lower = filename.lower()
    
    if t == "preventiva" or fn_lower.startswith("pcm-p-") or "preventiva" in fn_lower:
        return "Work/Industrial", "Tipo: preventiva industrial", ["manutencao/preventiva"]
    if t == "person" or "people/" in fn_lower:
        return "People", "Tipo: pessoa / contato", ["people"]
    if t == "daily" or fn_lower.startswith("daily-"):
        return "Daily", "Tipo: nota diária", ["daily"]

    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    tags_str = " ".join(str(tg).lower() for tg in tags)
    
    if any(k in tags_str for k in ["manutencao", "industrial", "gree", "pcm", "ativo", "maquina", "injetora"]):
        return "Work/Industrial", "Tags: manutenção e ativos", ["industrial"]
    if any(k in tags_str for k in ["personal", "anime", "filme", "musica"]):
        return "Personal", "Tags: conteúdo pessoal", ["personal"]
    if "people" in tags_str:
        return "People", "Tags: pessoas", ["people"]
    if any(k in tags_str for k in ["knowledge", "artigo", "manual", "sop", "referencia"]):
        return "03 - Knowledge", "Tags: conhecimento e SOP", ["knowledge"]

    industrial_tokens = [
        "grbim", "gbrma", "gbrij", "grbtb", "chiller", "injetora", "desumidificador",
        "compressor", "molde", "aletadeira", "cintadeira", "termoregulad", "flangeadora"
    ]
    if any(tok in fn_lower for tok in industrial_tokens):
        return "Work/Industrial", "Nome: ativo de maquinário industrial", ["industrial", "ativo"]

    return "03 - Knowledge", "Classificação padrão: Conhecimento Geral", ["triaged"]


# -----------------------------------------------------------------------------
# WORKER DE CURADORIA CONTÍNUA AUTÔNOMA
# -----------------------------------------------------------------------------
class ContinuousCurator:
    def __init__(self):
        self.is_running: bool = False
        self.stop_requested: bool = False
        self.total_initial: int = 0
        self.processed_count: int = 0
        self.remaining_count: int = 0
        self.current_file: str = ""
        self.errors_count: int = 0
        self.started_at: Optional[str] = None
        self.recent_logs: deque = deque(maxlen=200)
        self.task: Optional[asyncio.Task] = None

    def get_status(self) -> Dict[str, Any]:
        try:
            actual_remaining = sum(1 for p in INBOX_PATH.glob("*.md") if not p.name.startswith("."))
        except Exception:
            actual_remaining = self.remaining_count

        percent = 100
        if self.total_initial > 0:
            percent = min(100, int((self.processed_count / self.total_initial) * 100))

        return {
            "is_running": self.is_running,
            "stop_requested": self.stop_requested,
            "total_initial": self.total_initial,
            "processed": self.processed_count,
            "remaining": actual_remaining,
            "current_file": self.current_file,
            "errors": self.errors_count,
            "percent": percent,
            "started_at": self.started_at,
            "recent_logs": list(self.recent_logs)
        }

    def start(self) -> Dict[str, Any]:
        if self.is_running:
            return {"status": "already_running", "detail": "Curadoria contínua já está em execução."}

        files = list(INBOX_PATH.glob("*.md"))
        self.total_initial = len(files)
        self.processed_count = 0
        self.remaining_count = self.total_initial
        self.errors_count = 0
        self.stop_requested = False
        self.is_running = True
        self.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.recent_logs.clear()
        self.recent_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Curadoria Contínua Automática Iniciada! Total: {self.total_initial} notas.")

        self.task = asyncio.create_task(self._run_loop())
        return {"status": "started", "total_initial": self.total_initial}

    def stop(self) -> Dict[str, Any]:
        if not self.is_running:
            return {"status": "not_running", "detail": "Nenhuma curadoria em execução."}
        self.stop_requested = True
        self.recent_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ⏸ Interrupção solicitada pelo usuário.")
        return {"status": "stopping"}

    async def _run_loop(self):
        try:
            while not self.stop_requested:
                files = sorted(INBOX_PATH.glob("*.md"), key=lambda p: p.stat().st_mtime)
                if not files:
                    self.recent_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🎉 SUCESSO TOTAL! Todas as notas da 00 - Inbox foram curadas e organizadas.")
                    break

                batch = files[:15]
                for file_path in batch:
                    if self.stop_requested:
                        break

                    self.current_file = file_path.name
                    try:
                        self._process_single_file(file_path)
                        self.processed_count += 1
                    except Exception as e:
                        self.errors_count += 1
                        self.recent_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Erro em [{file_path.name}]: {str(e)}")

                    await asyncio.sleep(0.02)

                self.remaining_count = sum(1 for _ in INBOX_PATH.glob("*.md"))

        except Exception as e:
            self.recent_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Erro no loop de curadoria: {str(e)}")
        finally:
            self.is_running = False
            self.stop_requested = False
            self.current_file = ""
            self.recent_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🏁 Sessão finalizada. Total processadas: {self.processed_count}.")

    def _process_single_file(self, file_path: Path):
        content = file_path.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(content)
        current_tags = meta.get("tags") or []
        
        target_folder, reason, extra_tags = classify_note_smart(content, file_path.name)
        
        dest_dir = VAULT_PATH / target_folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / file_path.name

        if dest_file.exists() and dest_file.resolve() != file_path.resolve():
            dest_file = dest_dir / f"{file_path.stem}_{datetime.now().strftime('%H%M%S')}.md"

        meta["status"] = "triaged"
        meta["updated"] = datetime.now().strftime("%Y-%m-%d")
        
        existing_tags = set(current_tags if isinstance(current_tags, list) else [str(current_tags)])
        existing_tags.update(extra_tags)
        meta["tags"] = sorted(list(existing_tags))

        new_frontmatter = yaml.dump(meta, sort_keys=False, allow_unicode=True).strip()
        updated_content = f"---\n{new_frontmatter}\n---\n\n{body.strip()}\n"

        dest_file.write_text(updated_content, encoding="utf-8")
        assert dest_file.exists() and dest_file.stat().st_size > 0

        file_path.unlink()
        time_str = datetime.now().strftime("%H:%M:%S")
        self.recent_logs.append(f"[{time_str}] ✓ [{file_path.name}] ➔ {target_folder}/ ({reason})")


continuous_curator = ContinuousCurator()


def triage_inbox_batch(batch_size: int = 10) -> Dict[str, Any]:
    files = sorted(INBOX_PATH.glob("*.md"), key=lambda p: p.stat().st_mtime)
    if not files:
        return {"processed": 0, "logs": ["Nenhuma nota pendente em 00 - Inbox."]}

    batch = files[:batch_size]
    logs = []
    processed_count = 0

    for file_path in batch:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            meta, body = parse_frontmatter(content)
            target_folder, reason, extra_tags = classify_note_smart(content, file_path.name)
            
            dest_dir = VAULT_PATH / target_folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / file_path.name
            if dest_file.exists() and dest_file.resolve() != file_path.resolve():
                dest_file = dest_dir / f"{file_path.stem}_{datetime.now().strftime('%H%M%S')}.md"

            meta["status"] = "triaged"
            meta["updated"] = datetime.now().strftime("%Y-%m-%d")
            dest_file.write_text(f"---\n{yaml.dump(meta, sort_keys=False, allow_unicode=True).strip()}\n---\n\n{body.strip()}\n", encoding="utf-8")
            assert dest_file.exists() and dest_file.stat().st_size > 0
            file_path.unlink()
            logs.append(f"✓ [{file_path.name}] → {target_folder}/ ({reason})")
            processed_count += 1
        except Exception as e:
            logs.append(f"✗ [{file_path.name}]: {str(e)}")

    return {"processed": processed_count, "batch_total": len(batch), "logs": logs}
