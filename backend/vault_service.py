"""
Serviço de manipulação e governança do cofre de Nash.
Adere estritamente às normas JPL-CP-10 e Loop PRVC (Grounding, Fail-Fast e Read-Back Verification).
"""
import os
import re
import yaml
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

from .config import VAULT_PATH, INBOX_PATH, ASSETS_PATH, TEMPLATE_PATH


def safe_vault_path(rel_path: str) -> Path:
    """Valida e resolve caminho garantindo que não escape do cofre de Nash."""
    clean = rel_path.strip().lstrip("/\\")
    target = (VAULT_PATH / clean).resolve()
    if not str(target).startswith(str(VAULT_PATH)):
        raise ValueError(f"Acesso negado: tentativa de escape do cofre ({rel_path})")
    return target


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Separa Frontmatter YAML e corpo do Markdown."""
    pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
    match = re.match(pattern, content, re.DOTALL)
    if match:
        yaml_text, body = match.groups()
        try:
            data = yaml.safe_load(yaml_text) or {}
            if isinstance(data, dict):
                return data, body
        except Exception:
            pass
    return {}, content


import io
from PIL import Image, ImageOps

def sanitize_and_process_image(
    file_bytes: bytes,
    max_dim: int = 1920,
    target_quality: int = 75,
    max_bytes: int = 1024 * 1024
) -> Tuple[bytes, int, int]:
    """
    Sanitiza e otimiza a imagem conforme especificação:
    1. Formato estrito: JPEG (.jpg)
    2. Resolução HD: dimensão máxima 1920px mantendo proporção
    3. Qualidade: 75%
    4. Remoção total de metadados EXIF/GPS por segurança e higiene
    5. Teto rígido: <= 1 MB (1048576 bytes)
    Retorna: (jpeg_bytes, width, height)
    """
    assert len(file_bytes) > 0, "Arquivo de imagem vazio"
    
    # Carrega imagem e normaliza orientação EXIF antes de remover metadados
    raw_img = Image.open(io.BytesIO(file_bytes))
    img = ImageOps.exif_transpose(raw_img)
    
    # Converte para RGB (elimina canal alpha e remove metadados EXIF nativamente)
    img = img.convert("RGB")
    
    # Redimensiona para HD (máximo 1920 na maior dimensão)
    if max(img.width, img.height) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        
    # Primeira compressão com 75% de qualidade
    out_buf = io.BytesIO()
    quality = target_quality
    img.save(out_buf, format="JPEG", quality=quality, optimize=True)
    res_bytes = out_buf.getvalue()
    
    # Se ainda exceder 1 MB, reduz qualidade ou dimensão iterativamente
    while len(res_bytes) > max_bytes and quality > 30:
        quality -= 8
        out_buf = io.BytesIO()
        img.save(out_buf, format="JPEG", quality=quality, optimize=True)
        res_bytes = out_buf.getvalue()
        
    if len(res_bytes) > max_bytes:
        # Reduz dimensões pela metade se qualidade sozinha não bastar
        img.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        out_buf = io.BytesIO()
        img.save(out_buf, format="JPEG", quality=70, optimize=True)
        res_bytes = out_buf.getvalue()
        
    return res_bytes, img.width, img.height


def save_asset(file_bytes: bytes, original_filename: str) -> Tuple[Path, str, str, Dict[str, Any]]:
    """
    Sanitiza, converte para JPG HD (75%, <=1MB) e grava em assets/
    Retorna: (caminho_absoluto, caminho_relativo, sha256_hash, metadata_dict)
    """
    assert len(file_bytes) > 0, "Arquivo de imagem vazio"
    
    # Executa sanitização estrita via script Pillow
    sanitized_bytes, w, h = sanitize_and_process_image(file_bytes)
    
    sha256 = hashlib.sha256(sanitized_bytes).hexdigest()
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_name = f"IMG_{now_str}_{sha256[:8]}.jpg"
    
    target_path = ASSETS_PATH / clean_name
    target_path.write_bytes(sanitized_bytes)
    
    # Read-back verification pós-escrita
    assert target_path.exists(), "Falha ao gravar arquivo em assets"
    assert target_path.stat().st_size == len(sanitized_bytes), "Discrepância de tamanho pós-gravação"
    assert target_path.stat().st_size <= 1024 * 1024, "Arquivo excedeu o teto de 1 MB após compressão"
    
    rel_path = f"assets/{clean_name}"
    meta = {
        "filename": clean_name,
        "width": w,
        "height": h,
        "size_bytes": len(sanitized_bytes),
        "size_kb": round(len(sanitized_bytes) / 1024, 1),
        "sha256": sha256,
        "format": "JPEG (HD, 75%)"
    }
    return target_path, rel_path, sha256, meta


def write_note_safely(rel_path: str, content: str) -> Path:
    """
    Escreve nota com verificação mandatória pós-escrita (Read-Back Check).
    """
    target = safe_vault_path(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    
    # Read-back check
    read_back = target.read_text(encoding="utf-8")
    assert read_back == content, f"Read-back check falhou para {rel_path}"
    return target


def list_projects() -> List[Dict[str, str]]:
    """Lista projetos ativos na pasta Work/Projects."""
    projects_dir = VAULT_PATH / "Work" / "Projects"
    results = []
    if not projects_dir.exists():
        return results
    for f in sorted(projects_dir.glob("*.md")):
        if f.name.startswith("."):
            continue
        results.append({
            "name": f.stem,
            "wikilink": f"[[Work/Projects/{f.stem}]]",
            "path": str(f.relative_to(VAULT_PATH))
        })
    return results


def list_inbox_pending(limit: int = 50) -> List[Dict[str, Any]]:
    """Lista notas pendentes na pasta 00 - Inbox."""
    results = []
    if not INBOX_PATH.exists():
        return results
        
    md_files = sorted(INBOX_PATH.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in md_files[:limit]:
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            meta, body = parse_frontmatter(content)
            title = meta.get("title") or p.stem
            tags = meta.get("tags") or []
            status = meta.get("status", "captured")
            created = meta.get("created", "")
            
            # Preview primeiras 3 linhas do corpo
            body_lines = [l.strip() for l in body.splitlines() if l.strip()]
            preview = " ".join(body_lines[:3])[:200]
            
            # Detecta imagens anexadas
            images = re.findall(r"!\[\[(.*?)\]\]", content)
            
            results.append({
                "filename": p.name,
                "title": title,
                "status": status,
                "tags": tags if isinstance(tags, list) else [str(tags)],
                "created": str(created),
                "preview": preview,
                "images_count": len(images),
                "images": images,
                "size_bytes": p.stat().st_size,
                "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            })
        except Exception:
            continue
    return results


def safe_inbox_path(filename: str) -> Path:
    """Valida que o arquivo pertence estritamente à pasta INBOX_PATH."""
    clean_name = os.path.basename(filename.strip())
    if not clean_name.endswith(".md"):
        clean_name += ".md"
    target = (INBOX_PATH / clean_name).resolve()
    if not str(target).startswith(str(INBOX_PATH.resolve())):
        raise ValueError(f"Acesso negado: tentativa de escape da Inbox ({filename})")
    return target


def get_inbox_note(filename: str) -> Dict[str, Any]:
    """Obtém detalhes completos de uma nota específica na Inbox para edição ou inspeção."""
    target = safe_inbox_path(filename)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"Nota não encontrada no Inbox: {filename}")

    content = target.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_frontmatter(content)
    title = meta.get("title") or target.stem
    tags = meta.get("tags") or []
    status = meta.get("status", "captured")
    created = meta.get("created", "")
    updated = meta.get("updated", "")
    images = re.findall(r"!\[\[(.*?)\]\]", content)

    return {
        "filename": target.name,
        "title": title,
        "status": status,
        "tags": tags if isinstance(tags, list) else [str(tags)],
        "created": str(created),
        "updated": str(updated),
        "frontmatter": meta,
        "content": content,
        "body": body,
        "images": images,
        "size_bytes": target.stat().st_size,
        "mtime": datetime.fromtimestamp(target.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    }


def update_inbox_note(filename: str, content: str, new_filename: Optional[str] = None) -> Dict[str, Any]:
    """
    Atualiza o conteúdo de uma nota na Inbox com Read-Back Check mandatório (PRVC/JPL-CP-10).
    Permite também renomear o arquivo se new_filename for informado.
    """
    assert len(content.strip()) > 0, "O conteúdo da nota não pode ser vazio."
    target = safe_inbox_path(filename)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"Nota de origem não existe: {filename}")

    dest = target
    if new_filename and new_filename.strip():
        new_clean = os.path.basename(new_filename.strip())
        if not new_clean.endswith(".md"):
            new_clean += ".md"
        dest_candidate = safe_inbox_path(new_clean)
        if dest_candidate.resolve() != target.resolve() and dest_candidate.exists():
            raise FileExistsError(f"Já existe uma nota com o nome '{new_clean}' no Inbox.")
        dest = dest_candidate

    dest.write_text(content, encoding="utf-8")
    read_back = dest.read_text(encoding="utf-8")
    assert read_back == content, f"Read-back check falhou ao atualizar {dest.name}"

    if dest.resolve() != target.resolve() and target.exists():
        target.unlink()
        assert not target.exists(), f"Falha ao remover arquivo legado pós-renomeação: {target.name}"

    return get_inbox_note(dest.name)


def delete_inbox_note(filename: str) -> bool:
    """
    Remove com segurança uma nota do Inbox antes da ingestão no cofre.
    Preserva cópia de segurança em .backups/trash e executa verificação pós-exclusão.
    """
    target = safe_inbox_path(filename)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"Nota não encontrada no Inbox: {filename}")

    # Preserva backup de segurança em .backups/trash
    trash_dir = VAULT_PATH / ".backups" / "trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = trash_dir / f"{target.stem}_{timestamp}{target.suffix}"
    backup_path.write_text(target.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

    target.unlink()
    assert not target.exists(), f"Read-back check falhou: arquivo {filename} ainda existe após exclusão"
    return True


def get_vault_stats() -> Dict[str, Any]:
    """Coleta métricas rápidas de saúde do cofre."""
    total_notes = sum(1 for p in VAULT_PATH.rglob("*.md") if not p.name.startswith(".") and ".backups" not in p.parts)
    inbox_notes = sum(1 for p in INBOX_PATH.glob("*.md") if not p.name.startswith("."))
    assets_count = sum(1 for p in ASSETS_PATH.glob("*") if p.is_file() and not p.name.startswith("."))
    
    return {
        "vault_name": "Nash Obsidian Vault",
        "vault_path": str(VAULT_PATH),
        "total_notes": total_notes,
        "inbox_pending": inbox_notes,
        "assets_count": assets_count,
        "status": "healthy"
    }
