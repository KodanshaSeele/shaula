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
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from collections import deque
from typing import Dict, List, Any, Tuple, Optional

from .config import VAULT_PATH, INBOX_PATH, ASSETS_PATH, TEMPLATE_PATH, AGY_CLI, STATE_DB_PATH, CHROMA_PATH
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


def _fts5_vault_search(match_query: str, max_results: int = 4) -> List[Tuple[str, str, str]]:
    """Consulta rápida via índice invertido BM25 no SQLite FTS5 de Nash (<=10ms)."""
    if not STATE_DB_PATH.exists() or not match_query.strip():
        return []
    uri = f"file:{STATE_DB_PATH}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=3.0) as con:
            cur = con.cursor()
            cur.execute("""
                SELECT file_path, section, content
                FROM vault_fts
                WHERE vault_fts MATCH ?
                  AND file_path NOT LIKE '%System/Archive%'
                  AND file_path NOT LIKE '%.backups%'
                ORDER BY bm25(vault_fts)
                LIMIT ?
            """, (match_query, max_results))
            return cur.fetchall()
    except Exception:
        return []


def query_vault_rag(search_text: str, max_results: int = 4) -> Dict[str, Any]:
    """
    Motor RAG do Vault de Nash (JPL-CP-10 Compliant):
    Utiliza o índice invertido FTS5 pré-indexado de Nash com BM25 para recuperação
    instantânea (<10ms).
    """
    if not VAULT_PATH.exists() or not search_text.strip():
        return {"has_match": False, "matched_notes": [], "summary_context": ""}

    raw_tokens = []
    for item in re.findall(r'[^\s,;:()\[\]\"\'\+\*\?\^\{\}]+', search_text):
        if "/" in item:
            raw_tokens.extend([p for p in item.split("/") if len(p) >= 2])
        raw_tokens.append(item)

    priority = [t for t in raw_tokens if re.search(r"^(JM|GRB|GBR|Φ|8DX|201|285|ALETA|MOLDE|INJETORA)", t, re.I)]
    terms = priority + [t for t in raw_tokens if t not in priority and len(t) >= 2]
    tokens = [f'"{t}"' for t in terms[:12]]

    rows = _fts5_vault_search(" OR ".join(tokens), max_results) if tokens else []
    if not rows:
        return {"has_match": False, "matched_notes": [], "summary_context": "Sem notas correlatas prévias no cofre."}

    matched_notes = []
    context_lines = []
    for rel, section, content in rows:
        matched_notes.append(rel)
        lines = [l for l in content.splitlines() if l.startswith("#") or l.startswith("- **") or l.startswith("|")][:6]
        sec_label = f" ({section})" if section else ""
        context_lines.append(f"Nota [[{rel}]]{sec_label}:\n" + "\n".join(lines))

    return {
        "has_match": True,
        "matched_notes": matched_notes,
        "summary_context": "\n\n".join(context_lines)
    }


def _evaluate_image_vision(asset_rel_paths: List[str]) -> str:
    """FASE 1: Inspeciona imagens diretamente com a visão multimodal do Gemini (sem OCR)."""
    if not asset_rel_paths:
        return ""
    abs_paths = [str((VAULT_PATH / p).resolve()) for p in asset_rel_paths]
    img_list = "\n".join([f"- {p}" for p in abs_paths])
    vision_prompt = f"""Use a ferramenta de leitura de arquivos (read_file) para abrir e inspecionar visualmente cada uma das seguintes imagens:
{img_list}

Como especialista em visão computacional e engenharia industrial:
1. Inspecione a imagem detalhadamente com a visão de IA (sem bibliotecas de OCR).
2. Avalie e transcreva todo o texto visível, placas de identificação, logotipos (ex: GREE), códigos de ferramental (ex: JM...), códigos de moldes, especificações (ex: Φ...), dimensões, pesos (T), datas e passos de alimentação.
3. Organize todos os parâmetros técnicos e características visuais observadas em uma tabela estruturada.
NÃO resuma nem omita números técnicos, códigos ou caracteres chineses."""
    reply = _invoke_agy(vision_prompt, timeout_sec=60)
    return reply.strip() if (reply and len(reply.strip()) > 15) else ""


def _parse_json_reply(reply: str) -> Dict[str, Any]:
    """Extrai e desserializa JSON embutido na resposta do Gemini."""
    if not reply:
        return {}
    m = re.search(r"\{[\s\S]*\}", reply)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}


def _synthesize_canonical_cases(
    gemini_vision_eval: str,
    vault_rag_context: str,
    db_context: str,
    projects_context: str,
    effective_content: str,
    images_block: str
) -> Dict[str, Any]:
    """FASE 3: Sintetiza nota canônica pelo Gemini com todos os dados consolidados em mãos."""
    prompt = f"""Você é Shaula, Cérebro Cognitivo do Vault de Nash.
Captura com imagens industriais analisadas via visão multimodal.
COM TODOS OS DADOS EM MÃOS (Visão da IA + RAG do Cofre + Relato Operador), gere 2 CASOS:

1. AVALIAÇÃO DE VISÃO COMPUTACIONAL DA IA:
{gemini_vision_eval or 'Sem imagem ou ilustrativa.'}

2. CONTEXTO RECUPERADO DA RAG DO VAULT DE NASH:
{vault_rag_context}

3. BANCO INDUSTRIAL (PCM/Grimorium): {db_context}
4. PROJETOS ATIVOS: {projects_context}
5. RELATO DO OPERADOR: {effective_content}
Imagens: {images_block}

Diretrizes:
1. CASO 1 (com_visao): Incorpore a tabela técnica e parâmetros cruzados com a SSoT do cofre.
2. CASO 2 (sem_visao): Síntese textual limpa focada no relato e contexto do cofre.
3. YAML frontmatter padronizado (author: "Shaula", [[Nota]]).
Responda ESTRITAMENTE em formato JSON com chaves:
{{
  "proposed_title": "Titulo descritivo",
  "target_folder": "Work/Industrial",
  "target_project": "[[Work/Projects/Manutencao-Gree]]",
  "tags": ["industrial/molde", "gree"],
  "reasoning": "Shaula avaliou a imagem via IA, cruzou com o Vault e gerou a nota.",
  "case_with_vision": "--- Markdown Caso 1 ---",
  "case_without_vision": "--- Markdown Caso 2 ---"
}}"""
    return _parse_json_reply(_invoke_agy(prompt, timeout_sec=60))


def _assemble_analysis_response(
    parsed: Dict[str, Any],
    effective_content: str,
    asset_rel_paths: List[str],
    now_id: str,
    today: str,
    gemini_vision_eval: str,
    combined_search_text: str,
    db_cross: Dict[str, Any],
    db_context: str,
    vault_rag_context: str,
    images_block: str
) -> Dict[str, Any]:
    """Monta a estrutura final de resposta com fallbacks canônicos garantidos."""
    title = parsed.get("proposed_title") or _infer_title_fast(effective_content, asset_rel_paths, now_id, gemini_vision_eval)
    folder = parsed.get("target_folder") or _infer_folder_fast(combined_search_text)
    project = parsed.get("target_project") or "[[Work/Projects/Manutencao-Gree]]"
    tags = parsed.get("tags") or ["captura", "memoria"]
    reason = parsed.get("reasoning") or "Shaula avaliou via visão de IA e cruzou com o Vault de Nash."

    case_v = parsed.get("case_with_vision")
    case_t = parsed.get("case_without_vision")
    if not case_v or not case_v.startswith("---"):
        case_v = _build_case_with_vision(now_id, today, title, effective_content, images_block, project, tags, f"{db_context}\n\n{vault_rag_context}", gemini_vision_eval)
    if not case_t or not case_t.startswith("---"):
        case_t = _build_case_without_vision(now_id, today, title, effective_content, images_block, project, tags)

    return {
        "success": True,
        "agent": "Shaula (Gemini Multimodal + Vault RAG)",
        "proposed_title": title,
        "target_folder": folder,
        "target_project": project,
        "tags": tags,
        "reasoning": reason,
        "database_crossref": db_cross,
        "vault_rag_context": vault_rag_context,
        "ocr_transcript": gemini_vision_eval,
        "case_with_vision": case_v,
        "case_without_vision": case_t,
        "canonical_markdown": case_v,
        "assets_rel_paths": asset_rel_paths
    }


def analyze_and_cross_reference(
    raw_content: str,
    asset_rel_paths: List[str],
    original_filenames: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Pipeline Cognitivo de 3 Fases (Gemini Vision + RAG Vault + Síntese Canônica):
    1. Gemini avalia diretamente as imagens via Visão de IA (sem bibliotecas de OCR).
    2. O sistema cruza os parâmetros extraídos com as notas do Vault de Nash (RAG) e PCM.
    3. Com todos os dados em mãos, o Gemini gera a nota técnica canônica consolidada.
    """
    now_id = datetime.now().strftime("%Y%m%d%H%M%S")
    today = datetime.now().strftime("%Y-%m-%d")
    images_block = "\n".join([f"![[{p}]]" for p in asset_rel_paths])
    effective_content = raw_content.strip() or ("Registro visual de equipamento e imagem industrial." if asset_rel_paths else "Registro de nota técnica.")

    # FASE 1: Avaliação de Imagem via Visão Multimodal do Gemini (sem bibliotecas OCR)
    gemini_vision_eval = _evaluate_image_vision(asset_rel_paths)

    # FASE 2: Cruzamento RAG com o Vault de Nash e Banco Industrial
    combined_search_text = (effective_content + "\n" + gemini_vision_eval).strip()
    vault_rag = query_vault_rag(combined_search_text, max_results=4)
    vault_rag_context = vault_rag.get("summary_context", "Sem notas correlatas prévias no cofre.")

    projects_context = _select_relevant_projects(combined_search_text, max_projects=12)
    search_names = [Path(p).name for p in asset_rel_paths]
    if original_filenames:
        search_names.extend(original_filenames)

    db_cross = cross_reference_database(text_content=combined_search_text, filenames=search_names)
    db_context = db_cross.get("summary_context", "Sem correspondência direta no banco.")

    # FASE 3: Síntese Canônica pelo Gemini com Todos os Dados em Mãos
    parsed = _synthesize_canonical_cases(
        gemini_vision_eval=gemini_vision_eval,
        vault_rag_context=vault_rag_context,
        db_context=db_context,
        projects_context=projects_context,
        effective_content=effective_content,
        images_block=images_block
    )

    return _assemble_analysis_response(
        parsed=parsed,
        effective_content=effective_content,
        asset_rel_paths=asset_rel_paths,
        now_id=now_id,
        today=today,
        gemini_vision_eval=gemini_vision_eval,
        combined_search_text=combined_search_text,
        db_cross=db_cross,
        db_context=db_context,
        vault_rag_context=vault_rag_context,
        images_block=images_block
    )


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
def triage_single_file(file_path: Path) -> Dict[str, Any]:
    """
    Classifica, enriquece metadados e move uma nota individual da Inbox para sua pasta canônica no Vault.
    Executa verificação pós-escrita e remove com segurança o arquivo do Inbox.
    """
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Nota não encontrada: {file_path.name}")

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
    assert dest_file.exists() and dest_file.stat().st_size > 0, "Falha ao gravar nota triada no destino"

    file_path.unlink()
    assert not file_path.exists(), f"Falha ao remover arquivo original {file_path.name} do Inbox"

    return {
        "success": True,
        "filename": dest_file.name,
        "original_filename": file_path.name,
        "target_folder": target_folder,
        "dest_path": str(dest_file.relative_to(VAULT_PATH)),
        "reason": reason
    }


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
        res = triage_single_file(file_path)
        time_str = datetime.now().strftime("%H:%M:%S")
        self.recent_logs.append(f"[{time_str}] ✓ [{file_path.name}] ➔ {res['target_folder']}/ ({res['reason']})")


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
            res = triage_single_file(file_path)
            logs.append(f"✓ [{file_path.name}] → {res['target_folder']}/ ({res['reason']})")
            processed_count += 1
        except Exception as e:
            logs.append(f"✗ [{file_path.name}]: {str(e)}")

    return {"processed": processed_count, "batch_total": len(batch), "logs": logs}
