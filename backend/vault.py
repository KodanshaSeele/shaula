"""
Gerenciador Exclusivo de Vault para Shaula
Suporta navegação em árvore, parsing de Markdown/Frontmatter, Wikilinks e Verificação de Integridade.
"""

import os
import re
import yaml
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from .config import VAULT_PATH, BACKUPS_DIR
from .settings_manager import settings_mgr


def safe_path(rel_path: str) -> Path:
    """Resolve o caminho relativo garantindo que permaneça estritamente dentro do vault principal ou auxiliar autorizado."""
    # Remove barras iniciais e normaliza
    clean = rel_path.strip().lstrip("/\\")

    # Se referenciar o vault auxiliar de Nashetanea
    if clean.startswith("aux_vault/") or clean.startswith("aux/"):
        aux_clean = clean.split("/", 1)[1] if "/" in clean else ""
        aux_base = settings_mgr.get_aux_path()
        full_path = (aux_base / aux_clean).resolve()
        if not str(full_path).startswith(str(aux_base)):
            raise ValueError(f"Acesso negado: tentativa de escape do vault auxiliar ({rel_path})")
        return full_path

    full_path = (VAULT_PATH / clean).resolve()
    if not str(full_path).startswith(str(VAULT_PATH)):
        raise ValueError(f"Acesso negado: tentativa de escape do vault ({rel_path})")
    return full_path


def parse_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    """Extrai cabeçalho YAML frontmatter e corpo markdown."""
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


def extract_wikilinks(text: str) -> List[tuple[str, str]]:
    """Extrai wikilinks ignorando blocos de código e inline code."""
    # Remover blocos de código cercados por ```
    no_code_blocks = re.sub(r"```[\s\S]*?```", "", text)
    # Remover código inline `...`
    no_inline_code = re.sub(r"`[^`]+`", "", no_code_blocks)
    
    matches = re.findall(r"\[\[(.*?)\]\]", no_inline_code)
    results = []
    for raw in matches:
        target = raw.split("|")[0].strip()
        if target:
            results.append((target, raw))
    return results


class VaultManager:
    def __init__(self, vault_path: Path = VAULT_PATH):
        self.vault_path = vault_path

    def get_tree(self) -> Dict[str, Any]:
        """Retorna estrutura de diretórios e arquivos do vault."""
        def walk_dir(directory: Path) -> Dict[str, Any]:
            name = directory.name if directory != self.vault_path else "root"
            items = []
            
            # Ordenar diretórios primeiro, depois arquivos
            try:
                entries = sorted(list(directory.iterdir()), key=lambda e: (not e.is_dir(), e.name.lower()))
            except Exception:
                entries = []

            for entry in entries:
                if entry.name.startswith(".") and entry.name != ".backups":
                    continue
                if entry.name == ".backups":
                    continue
                
                rel = str(entry.relative_to(self.vault_path))
                if entry.is_dir():
                    items.append(walk_dir(entry))
                elif entry.is_file() and entry.suffix.lower() in [".md", ".markdown", ".txt"]:
                    stat = entry.stat()
                    items.append({
                        "type": "file",
                        "name": entry.name,
                        "path": rel,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
            
            return {
                "type": "directory",
                "name": name,
                "path": str(directory.relative_to(self.vault_path)) if directory != self.vault_path else "",
                "children": items
            }

        root = walk_dir(self.vault_path)

        # Integrar Vault de Nashetanea na navegação em árvore se habilitado
        if settings_mgr.settings.get("aux_vault_enabled", False):
            aux_base = settings_mgr.get_aux_path()
            if aux_base.exists() and aux_base.is_dir():
                def walk_aux(directory: Path) -> Dict[str, Any]:
                    name = directory.name if directory != aux_base else "🌿 Vault Nashetanea (Auxiliar)"
                    items = []
                    try:
                        entries = sorted(list(directory.iterdir()), key=lambda e: (not e.is_dir(), e.name.lower()))
                    except Exception:
                        entries = []
                    for entry in entries:
                        if entry.name.startswith("."):
                            continue
                        rel = f"aux_vault/{entry.relative_to(aux_base)}"
                        if entry.is_dir():
                            items.append(walk_aux(entry))
                        elif entry.is_file() and entry.suffix.lower() in [".md", ".markdown", ".txt"]:
                            stat = entry.stat()
                            items.append({
                                "type": "file",
                                "name": entry.name,
                                "path": rel,
                                "size": stat.st_size,
                                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                            })
                    return {
                        "type": "directory",
                        "name": name,
                        "path": f"aux_vault/{directory.relative_to(aux_base)}" if directory != aux_base else "aux_vault",
                        "children": items
                    }
                root["children"].append(walk_aux(aux_base))

        return root

    def read_note(self, rel_path: str) -> Dict[str, Any]:
        """Lê nota e metadados com resolução inteligente estilo Obsidian."""
        path = safe_path(rel_path)
        if not path.is_file():
            # Tentar adicionar .md se não tiver
            if not rel_path.endswith(".md"):
                candidate = safe_path(f"{rel_path}.md")
                if candidate.is_file():
                    path = candidate
                    rel_path = f"{rel_path}.md"

            # Se ainda não for arquivo, buscar pelo nome do arquivo/stem em qualquer subpasta
            if not path.is_file():
                stem_target = Path(rel_path).stem.lower()
                for f in self.vault_path.rglob("*.md"):
                    if ".backups" in f.parts:
                        continue
                    if f.stem.lower() == stem_target or f.name.lower() == Path(rel_path).name.lower():
                        path = f
                        rel_path = str(f.relative_to(self.vault_path))
                        break

            # Se ainda não encontrou e o vault auxiliar estiver habilitado, buscar no vault auxiliar
            if not path.is_file() and settings_mgr.settings.get("aux_vault_enabled", False):
                aux_base = settings_mgr.get_aux_path()
                if aux_base.exists():
                    stem_target = Path(rel_path).stem.lower()
                    for f in aux_base.rglob("*.md"):
                        if f.name.startswith("."):
                            continue
                        if f.stem.lower() == stem_target or f.name.lower() == Path(rel_path).name.lower():
                            path = f
                            rel_path = f"aux_vault/{f.relative_to(aux_base)}"
                            break

        if not path.is_file():
            raise FileNotFoundError(f"Nota não encontrada: {rel_path}")

        content = path.read_text(encoding="utf-8", errors="replace")
        stat = path.stat()
        metadata, body = parse_frontmatter(content)
        
        # Extrair wikilinks ignorando código
        clean_links = [target for target, _ in extract_wikilinks(content)]

        # Extrair tags inline (#tag)
        inline_tags = set(re.findall(r"(?:^|\s)#([a-zA-Z0-9_\-]+)", body))
        meta_tags = metadata.get("tags", [])
        if isinstance(meta_tags, str):
            meta_tags = [meta_tags]
        elif not isinstance(meta_tags, list):
            meta_tags = []
        all_tags = sorted(list(inline_tags.union(set(meta_tags))))

        word_count = len(body.split())
        char_count = len(body)

        return {
            "path": rel_path,
            "filename": path.name,
            "title": metadata.get("title", path.stem),
            "metadata": metadata,
            "content": content,
            "body": body,
            "tags": all_tags,
            "wikilinks": clean_links,
            "word_count": word_count,
            "char_count": char_count,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat()
        }

    def save_note(self, rel_path: str, content: str) -> Dict[str, Any]:
        """Salva nota atualizando timestamp."""
        path = safe_path(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return self.read_note(rel_path)

    def create_note(self, rel_path: str, title: Optional[str] = None, initial_content: Optional[str] = None) -> Dict[str, Any]:
        """Cria uma nova nota garantindo extensão .md."""
        if not rel_path.endswith(".md"):
            rel_path += ".md"
        path = safe_path(rel_path)
        if path.exists():
            raise FileExistsError(f"Arquivo já existe: {rel_path}")

        note_title = title or path.stem
        if initial_content is None:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            initial_content = f"""---
title: "{note_title}"
date: "{now_str}"
tags:
  - shaula
---

# {note_title}

Digite suas notas aqui...
"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(initial_content, encoding="utf-8")
        return self.read_note(rel_path)

    def delete_note(self, rel_path: str) -> bool:
        """Deleta uma nota com segurança."""
        path = safe_path(rel_path)
        if path.is_file():
            path.unlink()
            return True
        elif path.is_dir():
            shutil.rmtree(path)
            return True
        return False

    def rename_note(self, old_rel_path: str, new_rel_path: str) -> Dict[str, Any]:
        """Renomeia ou move uma nota."""
        old_path = safe_path(old_rel_path)
        if not old_path.exists():
            raise FileNotFoundError(f"Arquivo de origem não existe: {old_rel_path}")

        if not new_rel_path.endswith(".md") and old_path.is_file():
            new_rel_path += ".md"
            
        new_path = safe_path(new_rel_path)
        new_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.rename(new_path)

        if new_path.is_file():
            return self.read_note(new_rel_path)
        return {"path": new_rel_path, "renamed": True}

    def create_folder(self, folder_rel_path: str) -> str:
        """Cria um novo diretório no vault."""
        path = safe_path(folder_rel_path)
        path.mkdir(parents=True, exist_ok=True)
        return str(path.relative_to(self.vault_path))

    def search_notes(self, query: str) -> List[Dict[str, Any]]:
        """Busca em títulos, caminhos, tags e conteúdo."""
        if not query or len(query.strip()) < 2:
            return []

        q = query.lower().strip()
        results = []
        for file_path in self.vault_path.rglob("*.md"):
            if ".backups" in file_path.parts:
                continue
            rel = str(file_path.relative_to(self.vault_path))
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            metadata, body = parse_frontmatter(content)
            title = metadata.get("title", file_path.stem)
            
            # Checar correspondência
            score = 0
            matches = []
            if q in title.lower():
                score += 10
            if q in rel.lower():
                score += 5
            
            # Buscar linhas de snippet
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if q in line.lower():
                    score += 1
                    if len(matches) < 3:
                        matches.append({"line": idx + 1, "text": line.strip()})

            if score > 0:
                results.append({
                    "path": rel,
                    "title": title,
                    "score": score,
                    "matches": matches,
                    "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                })

        # Buscar também no Vault Auxiliar de Nashetanea se habilitado
        if settings_mgr.settings.get("aux_vault_enabled", False):
            try:
                aux_base = settings_mgr.get_aux_path()
                if aux_base.exists() and aux_base.is_dir():
                    for file_path in aux_base.rglob("*.md"):
                        if file_path.name.startswith("."):
                            continue
                        rel = f"aux_vault/{file_path.relative_to(aux_base)}"
                        try:
                            content = file_path.read_text(encoding="utf-8", errors="replace")
                        except Exception:
                            continue

                        metadata, body = parse_frontmatter(content)
                        title = f"[Nash] {metadata.get('title', file_path.stem)}"

                        score = 0
                        matches = []
                        if q in title.lower():
                            score += 10
                        if q in rel.lower():
                            score += 5

                        lines = content.splitlines()
                        for idx, line in enumerate(lines):
                            if q in line.lower():
                                score += 1
                                if len(matches) < 3:
                                    matches.append({"line": idx + 1, "text": line.strip()})

                        if score > 0:
                            results.append({
                                "path": rel,
                                "title": title,
                                "score": score,
                                "matches": matches,
                                "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                            })
            except Exception:
                pass

        return sorted(results, key=lambda x: x["score"], reverse=True)

    def verify_vault_integrity(self) -> Dict[str, Any]:
        """
        Varredura completa de integridade do Vault:
        - Mapeia todas as notas existentes
        - Valida todos os wikilinks [[alvo]]
        - Detecta links quebrados (apontando para arquivos inexistentes)
        - Detecta notas órfãs (sem conexões de entrada ou saída)
        - Mapeia densidade de tags e estatísticas gerais
        """
        all_notes: Dict[str, Path] = {}
        by_stem: Dict[str, List[str]] = {}
        total_words = 0
        all_tags = set()
        outgoing_links: Dict[str, List[str]] = {}
        incoming_links: Dict[str, List[str]] = {}

        # 1. Indexar arquivos existentes
        for f in self.vault_path.rglob("*.md"):
            if ".backups" in f.parts:
                continue
            rel = str(f.relative_to(self.vault_path))
            all_notes[rel] = f
            stem = f.stem.lower()
            if stem not in by_stem:
                by_stem[stem] = []
            by_stem[stem].append(rel)
            incoming_links[rel] = []
            outgoing_links[rel] = []

        broken_links = []
        empty_notes = []

        # 2. Analisar conteúdo e conexões
        for rel, f in all_notes.items():
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            metadata, body = parse_frontmatter(content)
            words = len(body.split())
            total_words += words
            if words == 0:
                empty_notes.append(rel)

            # Tags
            inline_tags = set(re.findall(r"(?:^|\s)#([a-zA-Z0-9_\-]+)", body))
            m_tags = metadata.get("tags", [])
            if isinstance(m_tags, list):
                inline_tags.update(m_tags)
            all_tags.update(inline_tags)

            # Wikilinks
            raw_links = extract_wikilinks(content)
            for target, raw in raw_links:
                outgoing_links[rel].append(target)
                
                # Resolução flexível Obsidian
                target_clean = target.removesuffix(".md")
                matched_rel = None
                
                # Correspondência exata de caminho relativo
                exact_path = f"{target_clean}.md"
                if exact_path in all_notes:
                    matched_rel = exact_path
                elif target_clean.lower() in by_stem:
                    matched_rel = by_stem[target_clean.lower()][0]

                if matched_rel:
                    incoming_links[matched_rel].append(rel)
                else:
                    broken_links.append({
                        "source": rel,
                        "target": target,
                        "line_hint": f"[[{raw}]]"
                    })

        # 3. Detectar notas órfãs
        orphan_notes = []
        for rel in all_notes.keys():
            if not incoming_links.get(rel) and not outgoing_links.get(rel) and rel != "Shaula Home.md":
                orphan_notes.append(rel)

        return {
            "timestamp": datetime.now().isoformat(),
            "vault_path": str(self.vault_path),
            "total_notes": len(all_notes),
            "total_words": total_words,
            "total_tags": len(all_tags),
            "tags_list": sorted(list(all_tags)),
            "broken_links_count": len(broken_links),
            "broken_links": broken_links,
            "orphan_notes_count": len(orphan_notes),
            "orphan_notes": orphan_notes,
            "empty_notes_count": len(empty_notes),
            "empty_notes": empty_notes,
            "status": "HEALTHY" if len(broken_links) == 0 else "WARNING"
        }

    def resolve_broken_link(
        self,
        action: str,
        source: str,
        target: str,
        replacement: Optional[str] = None,
        target_folder: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Resolve pendências de links quebrados (segurança/integridade do Vault).
        - create_target: Cria a nota alvo ausente no Vault (na pasta especificada ou 03 - Knowledge)
        - rename_link: Substitui a referência quebrada por outro link válido na nota de origem
        - unlink: Remove a marcação [[...]] mantendo apenas o texto limpo
        - delete_link: Apaga a menção/link por completo na nota de origem
        """
        source_clean = source.strip().lstrip("/")
        source_path = (self.vault_path / source_clean).resolve()
        vault_root = self.vault_path.resolve()

        if not source_path.is_relative_to(vault_root) or not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"A nota de origem '{source}' não foi encontrada no Vault.")

        target_clean = target.removesuffix(".md").strip()
        if not target_clean:
            raise ValueError("O alvo do link não pode ser vazio.")

        # 1. CRIAR NOTA ALVO (Transmuta link quebrado em documento ativo)
        if action == "create_target":
            folder = (target_folder or "03 - Knowledge").strip("/")
            folder_dir = (self.vault_path / folder).resolve()
            folder_dir.mkdir(parents=True, exist_ok=True)

            dest_file = folder_dir / f"{target_clean}.md"
            if dest_file.exists():
                return {
                    "success": True,
                    "action": "create_target",
                    "note_path": str(dest_file.relative_to(self.vault_path)),
                    "message": f"A nota '{dest_file.name}' já existia. Link revalidado com sucesso."
                }

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            source_stem = Path(source_clean).stem
            content = f"""---
title: "{target_clean}"
date: "{now_str}"
tags:
  - knowledge
  - link_resolvido
status: ativo
---

# {target_clean}

> Nota gerada pela **Operadora do Vault Shaula** para resolver link quebrado originado em [[{source_stem}]].

## Descrição do Ativo / Registro
Ficha técnica criada no Vault de Shaula. Edite esta documentação com as especificações necessárias.

- **Origem da Referência:** [[{source_stem}]]
- **Data de Resolução:** {now_str}
"""
            dest_file.write_text(content, encoding="utf-8")
            return {
                "success": True,
                "action": "create_target",
                "note_path": str(dest_file.relative_to(self.vault_path)),
                "message": f"Nota alvo '{target_clean}' criada com sucesso em '{folder}/'!"
            }

        # 2. Ações que editam a nota de origem (rename_link, unlink, delete_link)
        orig_content = source_path.read_text(encoding="utf-8", errors="replace")
        target_esc = re.escape(target_clean)

        # Expressão regular com suporte a aliases ([[alvo|alias]]) e cabeçalhos ([[alvo#secao]])
        pattern = re.compile(rf"\[\[{target_esc}(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]", re.IGNORECASE)

        if not pattern.search(orig_content):
            # Tentar correspondência com a string exata original de target
            pattern = re.compile(rf"\[\[{re.escape(target)}(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]", re.IGNORECASE)
            if not pattern.search(orig_content):
                raise ValueError(f"O link '[[{target}]]' não foi localizado no texto de '{source}'.")

        if action == "rename_link":
            if not replacement or not replacement.strip():
                raise ValueError("O novo destino do link é obrigatório para renomear.")
            new_target = replacement.strip().removeprefix("[[").removesuffix("]]").removesuffix(".md").strip()

            def repl_rename(m):
                alias = m.group(1)
                return f"[[{new_target}|{alias}]]" if alias else f"[[{new_target}]]"

            new_content = pattern.sub(repl_rename, orig_content)
            source_path.write_text(new_content, encoding="utf-8")
            return {
                "success": True,
                "action": "rename_link",
                "message": f"Link atualizado para '[[{new_target}]]' na nota '{source}'."
            }

        elif action == "unlink":
            def repl_unlink(m):
                alias = m.group(1)
                return alias if alias else target_clean

            new_content = pattern.sub(repl_unlink, orig_content)
            source_path.write_text(new_content, encoding="utf-8")
            return {
                "success": True,
                "action": "unlink",
                "message": f"Wikilink desvinculado (convertido para texto '{target_clean}') na nota '{source}'."
            }

        elif action == "delete_link":
            new_content = pattern.sub("", orig_content)
            new_content = re.sub(r"[ \t]+", " ", new_content)
            source_path.write_text(new_content, encoding="utf-8")
            return {
                "success": True,
                "action": "delete_link",
                "message": f"Referência '[[{target}]]' apagada com sucesso da nota '{source}'."
            }

        else:
            raise ValueError(f"Ação inválida '{action}'. Ações válidas: create_target, rename_link, unlink, delete_link.")

    def backup_vault(self) -> Dict[str, Any]:
        """Cria um snapshot .tar.gz do vault na pasta .backups/"""
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"shaula_vault_{timestamp}.tar.gz"
        archive_path = BACKUPS_DIR / archive_name

        with tarfile.open(archive_path, "w:gz") as tar:
            for item in self.vault_path.iterdir():
                if item.name == ".backups":
                    continue
                tar.add(item, arcname=item.name)

        size_kb = round(archive_path.stat().st_size / 1024, 2)
        return {
            "success": True,
            "filename": archive_name,
            "path": str(archive_path),
            "size_kb": size_kb,
            "timestamp": datetime.now().isoformat()
        }


vault_mgr = VaultManager()
