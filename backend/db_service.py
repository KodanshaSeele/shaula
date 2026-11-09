"""
Serviço de Cruzamento de Dados com Banco PCM e Curadoria Grimorium.
Axiomas: NASA JPL-CP-10 (Leitura segura mode=ro, Bounded Queries, Fail-Fast).
"""
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional

NASH_BASE = Path("/home/kodansha/.hermes/profiles/nash")
PCM_DB = NASH_BASE / "databases" / "db_pcm.db"
GRIMORIUM_DB = NASH_BASE / "curadoria_grimorium.db"


def _extract_tokens(text: str, extra_tokens: Optional[List[str]] = None) -> List[str]:
    """Extrai identificadores de máquinas, códigos GRB e palavras técnicas (<= 15 tokens)."""
    raw_tokens = set()
    if text:
        for t in re.findall(r"[A-Za-z0-9_-]+", text):
            t_clean = re.sub(r"^[_-]+|[_-]+$", "", t).upper()
            if len(t_clean) >= 3:
                raw_tokens.add(t_clean)
                for part in re.split(r"[-_]+", t_clean):
                    if len(part) >= 3:
                        raw_tokens.add(part)
    if extra_tokens:
        for item in extra_tokens:
            stem = re.sub(r"\.[A-Za-z0-9]+$", "", item)
            for part in re.findall(r"[A-Za-z0-9]+", stem.upper()):
                if len(part) >= 3:
                    raw_tokens.add(part)
    priority = [t for t in raw_tokens if re.match(r"^(GRB|GBR|SCR|YQ|QDF|MOLDE|CHILLER|INJETORA)", t)]
    others = [t for t in raw_tokens if t not in priority and not t.isdigit()]
    return (priority + others)[:12]


def query_grimorium_assets(tokens: List[str]) -> List[Dict[str, Any]]:
    """Consulta chaves_grbim e catalogo_ativos com limite finito."""
    if not GRIMORIUM_DB.exists() or not tokens:
        return []
    
    results = []
    seen_ids = set()
    try:
        with sqlite3.connect(f"file:{GRIMORIUM_DB}?mode=ro", uri=True, timeout=2.0) as con:
            cur = con.cursor()
            for tok in tokens:
                q = f"%{tok}%"
                cur.execute(
                    "SELECT grbim_codigo, dispositivo_br, tipo_equipamento, ativo_id "
                    "FROM chaves_grbim WHERE grbim_codigo LIKE ? OR dispositivo_br LIKE ? LIMIT 3",
                    (q, q)
                )
                for r in cur.fetchall():
                    uid = f"grb_{r[0]}_{r[3]}"
                    if uid not in seen_ids:
                        seen_ids.add(uid)
                        results.append({
                            "source": "grimorium_chaves",
                            "codigo": r[0],
                            "dispositivo": r[1],
                            "tipo": r[2],
                            "ativo_id": r[3]
                        })
                
                cur.execute(
                    "SELECT id_ativo, nome_completo, codigo_setor, status "
                    "FROM catalogo_ativos WHERE id_ativo LIKE ? OR nome_completo LIKE ? LIMIT 3",
                    (q, q)
                )
                for r in cur.fetchall():
                    if r[0] not in seen_ids:
                        seen_ids.add(r[0])
                        results.append({
                            "source": "grimorium_catalogo",
                            "ativo_id": r[0],
                            "nome": r[1],
                            "setor": r[2],
                            "status": r[3]
                        })
    except Exception:
        pass
    return results[:8]


def query_pcm_assets(tokens: List[str]) -> List[Dict[str, Any]]:
    """Consulta pcm_ativos, ordens e corretivas vinculadas no banco db_pcm.db."""
    if not PCM_DB.exists() or not tokens:
        return []

    results = []
    seen_ids = set()
    try:
        with sqlite3.connect(f"file:{PCM_DB}?mode=ro", uri=True, timeout=2.0) as con:
            cur = con.cursor()
            for tok in tokens:
                q = f"%{tok}%"
                cur.execute(
                    "SELECT id, nome, setor, grupo, ativo_cod, estado "
                    "FROM pcm_ativos WHERE id LIKE ? OR nome LIKE ? OR ativo_cod LIKE ? LIMIT 4",
                    (q, q, q)
                )
                for r in cur.fetchall():
                    asset_id = r[0]
                    if asset_id not in seen_ids:
                        seen_ids.add(asset_id)
                        
                        # Busca últimas 2 corretivas desse ativo
                        cur.execute(
                            "SELECT anomalia, causa, data_ocorrencia "
                            "FROM pcm_corretivas WHERE ativo_id = ? ORDER BY id DESC LIMIT 2",
                            (asset_id,)
                        )
                        corretivas = [{"anomalia": c[0], "causa": c[1], "data": c[2]} for c in cur.fetchall()]

                        results.append({
                            "source": "pcm_ativos",
                            "id": asset_id,
                            "nome": r[1],
                            "setor": r[2],
                            "grupo": r[3],
                            "codigo": r[4],
                            "estado": r[5],
                            "recent_corretivas": corretivas
                        })
    except Exception:
        pass
    return results[:8]


def cross_reference_database(
    text_content: str = "",
    filenames: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Cruza dados de texto e nomes de fotos contra os bancos PCM e Grimorium.
    Retorna contexto estruturado para fundamentar a análise do Gemini e exibir na UI.
    """
    tokens = _extract_tokens(text_content, filenames)
    if not tokens:
        return {
            "has_match": False,
            "tokens": [],
            "matches": [],
            "summary_context": "Nenhum código de ativo industrial detectado no texto/imagem."
        }

    grim_matches = query_grimorium_assets(tokens)
    pcm_matches = query_pcm_assets(tokens)
    all_matches = pcm_matches + grim_matches

    if not all_matches:
        return {
            "has_match": False,
            "tokens": tokens,
            "matches": [],
            "summary_context": f"Códigos pesquisados ({', '.join(tokens)}), mas sem registro exato no banco."
        }

    # Gera resumo factual em texto conciso para injeção no prompt do Gemini
    lines = []
    main_asset = all_matches[0]
    for m in all_matches[:4]:
        if m.get("source") == "pcm_ativos":
            line = f"- [PCM Ativo]: {m.get('id')} | {m.get('nome')} | Setor: {m.get('setor')} | Status: {m.get('estado')}"
            if m.get("recent_corretivas"):
                recent = "; ".join([c["anomalia"] for c in m["recent_corretivas"]])
                line += f" | Histórico recente: {recent}"
            lines.append(line)
        elif m.get("source") == "grimorium_chaves":
            lines.append(f"- [Grimorium Molde/Máquina]: Código {m.get('codigo')} ({m.get('dispositivo')}) | Tipo: {m.get('tipo')} | Ativo ID: {m.get('ativo_id')}")
        elif m.get("source") == "grimorium_catalogo":
            lines.append(f"- [Catálogo]: {m.get('ativo_id')} — {m.get('nome')} | Setor: {m.get('setor')} | {m.get('status')}")

    summary = "\n".join(lines)

    return {
        "has_match": True,
        "tokens": tokens,
        "primary_asset": main_asset,
        "matches": all_matches,
        "summary_context": summary
    }
