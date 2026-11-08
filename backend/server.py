"""
Servidor Principal FastAPI para Shaula
Integra Vault Exclusivo, Motor de Verificação, Agendador de Tarefas e Configurações Seguras.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Body, Header, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import json
import shutil
import re
from datetime import datetime
import unicodedata

def slugify(text: str) -> str:
    """Gera slug limpo preservando caracteres sem acentos."""
    norm = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    clean = re.sub(r'[^a-zA-Z0-9_\- ]', '', norm).strip()
    return re.sub(r'\s+', '_', clean)

from .config import VAULT_PATH, STATIC_DIR, FRONTEND_DIR, ASSETS_DIR, HOST, PORT
from .vault import vault_mgr
from .verifier import verifier
from .scheduler import scheduler
from .settings_manager import settings_mgr
from .hermes_agent import hermes_agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicialização: Iniciar agendador
    scheduler.start()
    yield
    # Desligamento: Parar agendador
    scheduler.stop()


app = FastAPI(title="Shaula Command Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montar arquivos estáticos e assets de mídia
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


# Pydantic Schemas
class NoteSaveRequest(BaseModel):
    path: str
    content: str


class NoteCreateRequest(BaseModel):
    path: str
    title: Optional[str] = None
    content: Optional[str] = None


class NoteRenameRequest(BaseModel):
    old_path: str
    new_path: str


class FolderCreateRequest(BaseModel):
    path: str


class JobCreateRequest(BaseModel):
    name: str
    action: str
    interval_minutes: int
    save_note: bool = True


class JobToggleRequest(BaseModel):
    enabled: bool


class AuthRequest(BaseModel):
    password: str


class SettingsUpdateRequest(BaseModel):
    admin_password: Optional[str] = None
    aux_vault_enabled: Optional[bool] = None
    aux_vault_path: Optional[str] = None
    aux_sync_mode: Optional[str] = None
    auto_sync_interval_min: Optional[int] = None


class AuxImportRequest(BaseModel):
    aux_path: str
    dest_folder: str = "00 - Inbox"


class AuxExportRequest(BaseModel):
    shaula_path: str
    dest_folder: str = ""


class AuxSyncRequest(BaseModel):
    mode: Optional[str] = None


class HermesChatRequest(BaseModel):
    message: str
    context: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None


class HermesSerialRequest(BaseModel):
    serial: str
    title: Optional[str] = None
    folder: str = "auto"


class SmartNoteRequest(BaseModel):
    query: str
    title: Optional[str] = None
    folder: str = "auto"
    force: bool = False
    dry_run: bool = False


class ResolveBrokenLinkRequest(BaseModel):
    action: str  # 'create_target', 'rename_link', 'unlink', 'delete_link'
    source: str
    target: str
    replacement: Optional[str] = None
    target_folder: Optional[str] = "03 - Knowledge"


class DuplicateCheckRequest(BaseModel):
    query: str


def verify_auth_token(x_shaula_auth: Optional[str] = Header(None)):
    """Valida token de sessão administrativa para a tela de configurações."""
    if not x_shaula_auth or not settings_mgr.validate_token(x_shaula_auth):
        raise HTTPException(status_code=401, detail="Não autorizado. Autentique-se com a senha mestre (3884).")
    return True


# --- ROTAS DE INTERFACE ---
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Interface index.html não encontrada")
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


# --- ROTAS DO VAULT EXCLUSIVO ---
@app.get("/api/vault/tree")
async def get_vault_tree():
    return vault_mgr.get_tree()


@app.get("/api/vault/note")
async def get_note(path: str = Query(..., description="Caminho relativo da nota")):
    try:
        return vault_mgr.read_note(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Nota não encontrada")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/vault/note")
async def save_note(payload: NoteSaveRequest):
    try:
        return vault_mgr.save_note(payload.path, payload.content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/vault/create")
async def create_note(payload: NoteCreateRequest):
    try:
        return vault_mgr.create_note(payload.path, payload.title, payload.content)
    except FileExistsError:
        raise HTTPException(status_code=409, detail="Arquivo já existe")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/vault/note")
async def delete_note(path: str = Query(..., description="Caminho relativo da nota")):
    success = vault_mgr.delete_note(path)
    if not success:
        raise HTTPException(status_code=404, detail="Arquivo ou diretório não encontrado")
    return {"success": True, "path": path}


@app.post("/api/vault/rename")
async def rename_note(payload: NoteRenameRequest):
    try:
        return vault_mgr.rename_note(payload.old_path, payload.new_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/vault/folder")
async def create_folder(payload: FolderCreateRequest):
    try:
        res = vault_mgr.create_folder(payload.path)
        return {"success": True, "path": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/vault/search")
async def search_notes(q: str = Query("", description="Termo de busca")):
    return vault_mgr.search_notes(q)


@app.get("/api/vault/integrity")
async def get_vault_integrity():
    return vault_mgr.verify_vault_integrity()


@app.post("/api/vault/backup")
async def create_vault_backup():
    try:
        return vault_mgr.backup_vault()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- ROTAS DE VERIFICAÇÃO ---
@app.get("/api/verification/telemetry")
async def get_telemetry():
    hardware = verifier.get_hardware_telemetry()
    services = verifier.check_services()
    return {"hardware": hardware, "services": services}


@app.post("/api/verification/run")
async def run_verification(save_note: bool = Body(True, embed=True)):
    try:
        result = verifier.run_full_verification(save_report_to_vault=save_note)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao executar verificação: {str(e)}")


# --- ROTAS DE AGENDAMENTO (SCHEDULER) ---
@app.get("/api/scheduler/jobs")
async def get_scheduler_jobs():
    return scheduler.list_jobs()


@app.post("/api/scheduler/jobs")
async def add_scheduler_job(payload: JobCreateRequest):
    try:
        job = scheduler.add_job(
            name=payload.name,
            action=payload.action,
            interval_minutes=payload.interval_minutes,
            save_note=payload.save_note
        )
        return job
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/scheduler/jobs/{job_id}/toggle")
async def toggle_scheduler_job(job_id: str, payload: JobToggleRequest):
    try:
        return scheduler.toggle_job(job_id, payload.enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job não encontrado")


@app.post("/api/scheduler/jobs/{job_id}/run")
async def run_scheduler_job_now(job_id: str):
    try:
        scheduler.trigger_job(job_id)
        return {"success": True, "message": f"Execução do job {job_id} disparada"}
    except KeyError:
        raise HTTPException(status_code=404, detail="Job não encontrado")


@app.delete("/api/scheduler/jobs/{job_id}")
async def delete_scheduler_job(job_id: str):
    success = scheduler.delete_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return {"success": True, "job_id": job_id}


@app.get("/api/scheduler/history")
async def get_scheduler_history():
    return scheduler.get_history()


# --- ROTAS DE CONFIGURAÇÃO & VAULT AUXILIAR (PROTEGIDAS POR SENHA 3884) ---
@app.post("/api/settings/auth")
async def authenticate_admin(payload: AuthRequest):
    if settings_mgr.verify_password(payload.password):
        token = settings_mgr.generate_token()
        return {"success": True, "token": token, "message": "Autenticado com sucesso"}
    raise HTTPException(status_code=401, detail="Senha incorreta. Acesso restrito (3884).")


@app.get("/api/settings", dependencies=[Depends(verify_auth_token)])
async def get_settings():
    return settings_mgr.get_settings_safe()


@app.post("/api/settings", dependencies=[Depends(verify_auth_token)])
async def update_settings(payload: SettingsUpdateRequest):
    try:
        updates = payload.model_dump(exclude_unset=True)
        return settings_mgr.update_settings(updates)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/settings/aux/tree", dependencies=[Depends(verify_auth_token)])
async def get_aux_vault_tree():
    return settings_mgr.get_aux_tree()


@app.post("/api/settings/aux/import", dependencies=[Depends(verify_auth_token)])
async def import_from_aux(payload: AuxImportRequest):
    try:
        return settings_mgr.import_note_from_aux(payload.aux_path, payload.dest_folder)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/settings/aux/export", dependencies=[Depends(verify_auth_token)])
async def export_to_aux(payload: AuxExportRequest):
    try:
        return settings_mgr.export_note_to_aux(payload.shaula_path, payload.dest_folder)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/settings/aux/sync", dependencies=[Depends(verify_auth_token)])
async def sync_aux_vault(payload: AuxSyncRequest):
    try:
        return settings_mgr.sync_all_notes(payload.mode)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- ROTAS DO AGENTE HERMES ---
@app.get("/api/hermes/status")
async def get_hermes_status():
    return hermes_agent.get_status()


@app.get("/api/hermes/hardware-serials")
async def get_hermes_hardware_serials():
    return hermes_agent.collect_host_serials()


@app.post("/api/hermes/chat")
async def chat_with_hermes(payload: HermesChatRequest):
    try:
        reply = hermes_agent.operator_chat(payload.message, payload.history)
        return {"success": True, "reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vault/resolve-link")
async def resolve_broken_link_endpoint(payload: ResolveBrokenLinkRequest):
    try:
        result = vault_mgr.resolve_broken_link(
            action=payload.action,
            source=payload.source,
            target=payload.target,
            replacement=payload.replacement,
            target_folder=payload.target_folder
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/hermes/serial-process")
async def process_serial_with_hermes(payload: HermesSerialRequest):
    if not payload.serial or not payload.serial.strip():
        raise HTTPException(status_code=400, detail="O serial é obrigatório.")
    try:
        result = hermes_agent.process_smart_note(
            input_text=payload.serial.strip(),
            title_override=payload.title,
            dest_folder=payload.folder,
            force=True
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no processamento do serial: {str(e)}")


# --- ROTAS DE INGESTÃO INTELIGENTE DE NOTAS COM ANTI-DUPLICAÇÃO ---
@app.post("/api/smart-note/check-duplicate")
async def check_duplicate_note(payload: DuplicateCheckRequest):
    return hermes_agent.check_duplicate_entity(payload.query)


@app.post("/api/smart-note/process")
async def process_smart_note_endpoint(payload: SmartNoteRequest):
    try:
        return hermes_agent.process_smart_note(
            input_text=payload.query,
            title_override=payload.title,
            dest_folder=payload.folder,
            force=payload.force,
            dry_run=payload.dry_run
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- ROTAS DE UPLOAD DE IMAGENS (1 A 20 IMAGENS) ---
@app.post("/api/images/upload")
async def upload_images(
    files: List[UploadFile] = File(...),
    mode: str = Form("shared"),
    shared_description: Optional[str] = Form(""),
    individual_descriptions: Optional[str] = Form("[]"),
    note_title: Optional[str] = Form(""),
    dest_folder: str = Form("00 - Inbox"),
    create_note: bool = Form(True)
):
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="Nenhuma imagem enviada.")
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Limite máximo de 20 imagens excedido.")

    saved_images = []
    ts_prefix = datetime.now().strftime("%Y%m%d_%H%M%S")

    ind_desc_list = []
    try:
        if individual_descriptions:
            ind_desc_list = json.loads(individual_descriptions)
    except Exception:
        ind_desc_list = []

    for idx, f in enumerate(files):
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", f.filename or f"img_{idx}.jpg")
        final_filename = f"{ts_prefix}_{idx+1}_{clean_name}"
        dest_path = ASSETS_DIR / final_filename

        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)

        desc = ""
        if mode == "individual" and idx < len(ind_desc_list):
            desc = ind_desc_list[idx]
        elif mode == "shared":
            desc = shared_description or ""

        saved_images.append({
            "filename": final_filename,
            "original_name": f.filename,
            "path": f"assets/{final_filename}",
            "description": desc.strip()
        })

    created_note_path = None
    if create_note:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = note_title.strip() if note_title and note_title.strip() else f"Registro Fotográfico — {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        safe_note_name = slugify(title) or f"Registro_{ts_prefix}"
        rel_note_path = f"{dest_folder.rstrip('/')}/{safe_note_name}.md"

        images_markdown = []
        for i, img in enumerate(saved_images, 1):
            desc_text = f"\n> **Descrição:** {img['description']}\n" if img['description'] else ""
            images_markdown.append(f"### Imagem {i}: {img['original_name']}\n\n![{img['description']}](/assets/{img['filename']})\n{desc_text}\n---")

        joined_images = "\n\n".join(images_markdown)
        note_body = f"""---
title: "{title}"
date: "{now_str}"
tags:
  - imagens
  - galeria
  - registro
  - ativos
total_images: {len(saved_images)}
---

# 🖼️ {title}

> **Total de Registros:** `{len(saved_images)} imagens` | [[Shaula Home]]

---

{joined_images}

*Registro fotográfico catalogado no Vault Shaula.*
"""

        try:
            res = vault_mgr.create_note(rel_note_path, title, note_body)
        except FileExistsError:
            res = vault_mgr.save_note(rel_note_path, note_body)
        created_note_path = res["path"]

    return {
        "success": True,
        "count": len(saved_images),
        "note_path": created_note_path,
        "images": saved_images
    }


def run_server():
    import uvicorn
    uvicorn.run("backend.server:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    run_server()
