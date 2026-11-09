"""
Servidor FastAPI e WebSocket PTY para Nash RAG Desk.
Integra Terminal Antigravity Interativo e Ingestão Multimodal.
"""
import os
import pty
import time
import re
import sqlite3
import fcntl
import termios
import struct
import asyncio
import subprocess
import json
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel
from .config import VAULT_PATH, AGY_CLI, HOST, PORT, STATE_DB_PATH, CHROMA_PATH
from .vault_service import (
    save_asset,
    list_projects,
    list_inbox_pending,
    get_vault_stats
)
from .curator import (
    process_multimodal_ingest,
    auto_ingest_and_approve,
    analyze_and_cross_reference,
    approve_and_save_note,
    triage_inbox_batch,
    continuous_curator
)

class ApproveNoteIn(BaseModel):
    title: str
    target_folder: str
    content: str

class RagTestIn(BaseModel):
    query: str

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"

app = FastAPI(title="Nash RAG Desk", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# TERMINAL PTY & WEBSOCKET ENGINE
# -----------------------------------------------------------------------------
def _setup_pty_process(cmd: List[str], env: dict, cwd: str, rows: int = 28, cols: int = 110):
    master_fd, slave_fd = pty.openpty()
    os.set_blocking(master_fd, False)
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
    except Exception:
        pass

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            cwd=cwd,
            env=env
        )
    finally:
        os.close(slave_fd)
    return master_fd, proc


def _handle_pty_control(master_fd: int, raw_text: str) -> bool:
    """Interpreta comandos de controle (redimensionamento e keepalive ping/pong)."""
    if raw_text.startswith("{") and ("resize" in raw_text or "ping" in raw_text or "pong" in raw_text):
        try:
            pl = json.loads(raw_text)
            msg_type = pl.get("type")
            if msg_type == "resize":
                r = int(pl.get("rows", 28))
                c = int(pl.get("cols", 110))
                winsize = struct.pack("HHHH", r, c, 0, 0)
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                return True
            elif msg_type in ("ping", "pong"):
                return True
        except Exception:
            pass
    return False


@app.websocket("/ws/terminal")
@app.websocket("/desk/ws/terminal")
async def terminal_websocket(websocket: WebSocket):
    """Ponte WebSocket bidirecional resiliente com Antigravity CLI e shell Linux sob PTY."""
    await websocket.accept()

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    env["LANG"] = "en_US.UTF-8"
    env["NASH_VAULT_PATH"] = str(VAULT_PATH)

    # Shell resiliente em loop: se o agy for interrompido, não mata a conexão do terminal
    cmd = [
        "/bin/bash",
        "-c",
        f'cd "{VAULT_PATH}" && while true; do "{AGY_CLI}" --dangerously-skip-permissions --add-dir "{VAULT_PATH}"; echo -e "\\r\\n\\x1b[33m◈ Sessão do Antigravity concluída. Pressione ENTER para reiniciar ou digite bash para shell puro...\\x1b[0m"; read -r ans || sleep 1; if [ "$ans" = "bash" ] || [ "$ans" = "sh" ]; then /bin/bash -i; fi; done'
    ]

    master_fd, proc = _setup_pty_process(cmd=cmd, env=env, cwd=str(VAULT_PATH))
    loop = asyncio.get_running_loop()
    closed = False

    def on_pty_read():
        nonlocal closed
        if closed:
            return
        try:
            data = os.read(master_fd, 4096)
            if not data:
                return
            async def _send():
                try:
                    await websocket.send_bytes(data)
                except Exception:
                    pass
            asyncio.create_task(_send())
        except (BlockingIOError, InterruptedError):
            pass
        except Exception:
            closed = True

    loop.add_reader(master_fd, on_pty_read)

    # Heartbeat periódico a cada 15s para evitar que proxies (Tailscale/Funnel) fechem a conexão por inatividade
    async def _heartbeat_loop():
        while not closed:
            try:
                await asyncio.sleep(15)
                if not closed:
                    await websocket.send_text(json.dumps({"type": "ping"}))
            except Exception:
                break

    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    try:
        while not closed and proc.poll() is None:
            msg = await websocket.receive()
            if "text" in msg:
                text = msg["text"]
                if not _handle_pty_control(master_fd, text):
                    os.write(master_fd, text.encode("utf-8", errors="ignore"))
            elif "bytes" in msg:
                os.write(master_fd, msg["bytes"])
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        closed = True
        try:
            heartbeat_task.cancel()
        except Exception:
            pass
        try:
            loop.remove_reader(master_fd)
        except Exception:
            pass
        try:
            os.close(master_fd)
        except Exception:
            pass
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=1.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# -----------------------------------------------------------------------------
# REST APIS (MÉTRICAS, PROJETOS, INBOX, CURADORIA)
# -----------------------------------------------------------------------------
@app.get("/api/stats")
@app.get("/desk/api/stats")
def get_stats():
    return get_vault_stats()


@app.get("/api/projects")
@app.get("/desk/api/projects")
def get_projects():
    return list_projects()


@app.get("/api/inbox")
@app.get("/desk/api/inbox")
def get_inbox():
    return list_inbox_pending()


@app.post("/api/ingest/analyze")
@app.post("/desk/api/ingest/analyze")
async def analyze_note_endpoint(
    content: str = Form(""),
    images: List[UploadFile] = File([])
):
    """
    Avalia a nota bruta e imagens sob a persona Shaula, cruza dados com o cofre de Nash (RAG)
    e retorna 2 propostas (com visão computacional e sem visão computacional) para validação.
    """
    try:
        asset_rel_paths = []
        assets_meta = []
        for img in images:
            if not img.filename:
                continue
            data = await img.read()
            if data:
                _, rel_path, _, meta = save_asset(data, img.filename)
                asset_rel_paths.append(rel_path)
                assets_meta.append(meta)

        orig_names = [img.filename for img in images if img.filename]
        result = analyze_and_cross_reference(
            raw_content=content,
            asset_rel_paths=asset_rel_paths,
            original_filenames=orig_names
        )
        result["assets_metadata"] = assets_meta
        return JSONResponse(content=result, status_code=200)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/assets/{filename}")
@app.get("/desk/api/assets/{filename}")
@app.head("/api/assets/{filename}")
@app.head("/desk/api/assets/{filename}")
def serve_vault_asset(filename: str):
    """Serve imagens sanitizadas da pasta assets/ de forma segura e cirúrgica."""
    clean = Path(filename).name
    asset_file = (VAULT_PATH / "assets" / clean).resolve()
    if not str(asset_file).startswith(str(VAULT_PATH / "assets")):
        raise HTTPException(status_code=403, detail="Acesso negado: fora do diretório de assets")
    if not asset_file.exists():
        raise HTTPException(status_code=404, detail="Imagem não encontrada no cofre")
    return FileResponse(asset_file, media_type="image/jpeg")


@app.post("/api/ingest/auto")
@app.post("/desk/api/ingest/auto")
async def auto_ingest_endpoint(
    content: str = Form(""),
    target_folder: str = Form("auto"),
    title: str = Form(""),
    images: List[UploadFile] = File([])
):
    """
    Ingestão com Aprovação Automática Direta pelo Gemini (Shaula).
    Processa, analisa, formata canonicamente e aloca no destino sem interrupção nem lentidão.
    """
    try:
        asset_rel_paths = []
        assets_meta = []
        for img in images:
            if not img.filename:
                continue
            data = await img.read()
            if data:
                _, rel_path, _, meta = save_asset(data, img.filename)
                asset_rel_paths.append(rel_path)
                assets_meta.append(meta)

        orig_names = [img.filename for img in images if img.filename]
        result = auto_ingest_and_approve(
            raw_content=content,
            asset_rel_paths=asset_rel_paths,
            preferred_folder=target_folder,
            preferred_title=title,
            original_filenames=orig_names
        )
        result["assets_metadata"] = assets_meta
        return JSONResponse(content=result, status_code=200)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ingest/approve")
@app.post("/desk/api/ingest/approve")
async def approve_note_endpoint(payload: ApproveNoteIn):
    """
    Grava a nota validada e aprovada pelo usuário DIRETAMENTE na pasta final definitiva.
    """
    try:
        result = approve_and_save_note(
            title=payload.title,
            target_folder=payload.target_folder,
            content=payload.content
        )
        return JSONResponse(content=result, status_code=200)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ingest")
@app.post("/desk/api/ingest")
async def ingest_multimodal_note(
    title: str = Form(""),
    content: str = Form(""),
    project: str = Form(""),
    target_folder: str = Form("auto"),
    tags: str = Form(""),
    images: List[UploadFile] = File([])
):
    """Ingere nota e imagens anexadas com aprovação automática direta."""
    try:
        asset_rel_paths = []
        assets_meta = []
        for img in images:
            if not img.filename:
                continue
            data = await img.read()
            if data:
                _, rel_path, _, meta = save_asset(data, img.filename)
                asset_rel_paths.append(rel_path)
                assets_meta.append(meta)

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] or ["captura"]
        orig_names = [img.filename for img in images if img.filename]

        result = auto_ingest_and_approve(
            raw_content=content,
            asset_rel_paths=asset_rel_paths,
            preferred_folder=target_folder,
            preferred_title=title,
            tags=tag_list,
            original_filenames=orig_names
        )
        result["assets_metadata"] = assets_meta
        return JSONResponse(content=result, status_code=200)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/triage/start")
@app.post("/desk/api/triage/start")
async def start_continuous_triage():
    """Inicia a curadoria contínua sob demanda até o fim da Inbox."""
    res = continuous_curator.start()
    return JSONResponse(content=res, status_code=200)


@app.post("/api/triage/stop")
@app.post("/desk/api/triage/stop")
async def stop_continuous_triage():
    """Pausa / Interrompe a curadoria contínua."""
    res = continuous_curator.stop()
    return JSONResponse(content=res, status_code=200)


@app.get("/api/triage/status")
@app.get("/desk/api/triage/status")
async def get_triage_status():
    """Retorna o progresso e telemetria da curadoria contínua."""
    res = continuous_curator.get_status()
    return JSONResponse(content=res, status_code=200)


@app.post("/api/triage/run")
@app.post("/desk/api/triage/run")
@app.post("/api/triage/run-single")
@app.post("/desk/api/triage/run-single")
def run_triage():
    """Aciona um lote isolado de 10 notas."""
    try:
        res = triage_inbox_batch(batch_size=10)
        return JSONResponse(content=res, status_code=200)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rag/config")
@app.get("/desk/api/rag/config")
def get_rag_config():
    """Retorna o estado e caminhos canônicos da infraestrutura RAG de Nash."""
    fts_count = 0
    if STATE_DB_PATH.exists():
        try:
            with sqlite3.connect(f"file:{STATE_DB_PATH}?mode=ro", uri=True, timeout=2.0) as con:
                cur = con.cursor()
                cur.execute("SELECT count(*) FROM vault_fts")
                row = cur.fetchone()
                fts_count = row[0] if row else 0
        except Exception:
            pass

    chroma_count = 0
    if CHROMA_PATH.exists():
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            col = client.get_collection("vault_sync_gree")
            chroma_count = col.count()
        except Exception:
            pass

    return {
        "vault_path": str(VAULT_PATH),
        "vault_status": "conectado" if VAULT_PATH.exists() else "ausente",
        "state_db_path": str(STATE_DB_PATH),
        "state_db_status": "indexado" if STATE_DB_PATH.exists() else "ausente",
        "fts_chunks": fts_count,
        "chroma_path": str(CHROMA_PATH),
        "chroma_status": "ativo" if CHROMA_PATH.exists() else "ausente",
        "chroma_chunks": chroma_count,
        "active_model": "Gemini 3.8 Flash (Multimodal Vision & Reasoning via AGY)",
        "cli_path": str(AGY_CLI),
        "hybrid_algorithm": "Reciprocal Rank Fusion (RRF k=60) + BM25 Fast-Path",
        "databases": [
            "db_pcm.db (PCM & Equipamentos Industriais)",
            "curadoria_grimorium.db (Mapeamento & Vocabulário Técnico)"
        ]
    }


@app.post("/api/rag/test")
@app.post("/desk/api/rag/test")
def test_rag_query(payload: RagTestIn):
    """Testa a busca RAG no FTS5 de Nash e retorna latência em milissegundos."""
    query = (payload.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Consulta vazia.")

    t0 = time.perf_counter()
    raw_tokens = []
    for item in re.findall(r'[^\s,;:()\[\]\"\'\+\*\?\^\{\}]+', query):
        if "/" in item:
            raw_tokens.extend([p for p in item.split("/") if len(p) >= 2])
        raw_tokens.append(item)

    priority = [t for t in raw_tokens if re.search(r"^(JM|GRB|GBR|Φ|8DX|201|285|ALETA|MOLDE|INJETORA)", t, re.I)]
    terms = priority + [t for t in raw_tokens if t not in priority and len(t) >= 2]
    tokens = [f'"{t}"' for t in terms[:12]]
    match_query = " OR ".join(tokens) if tokens else f'"{query}"'

    results = []
    if STATE_DB_PATH.exists():
        try:
            with sqlite3.connect(f"file:{STATE_DB_PATH}?mode=ro", uri=True, timeout=3.0) as con:
                cur = con.cursor()
                cur.execute("""
                    SELECT file_path, section, content, bm25(vault_fts) as rank
                    FROM vault_fts
                    WHERE vault_fts MATCH ?
                      AND file_path NOT LIKE '%System/Archive%'
                      AND file_path NOT LIKE '%.backups%'
                    ORDER BY rank
                    LIMIT 6
                """, (match_query,))
                for fp, sec, cont, score in cur.fetchall():
                    snippet = " ".join([l.strip() for l in cont.splitlines() if l.strip()][:3])
                    results.append({
                        "file_path": fp,
                        "section": sec or "Raiz",
                        "score": round(-float(score), 2),
                        "snippet": snippet[:250]
                    })
        except Exception:
            pass

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "query": query,
        "latency_ms": elapsed_ms,
        "engine": "Nash FTS5 BM25 Inverted Index (Fast-Path)",
        "count": len(results),
        "results": results
    }


# -----------------------------------------------------------------------------
# FRONTEND ESTÁTICO
# -----------------------------------------------------------------------------
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.mount("/desk/static", StaticFiles(directory=str(STATIC_DIR)), name="desk_static")


@app.get("/")
@app.get("/desk")
@app.get("/desk/")
@app.head("/")
@app.head("/desk")
@app.head("/desk/")
def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Nash RAG Desk Backend Ativo"}
