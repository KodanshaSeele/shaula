"""
Motor de Agendamento Persistente (Scheduler) para Shaula
Executa tarefas em background, mantém histórico e registra eventos no Vault.
"""

import os
import json
import time
import uuid
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from .config import SCHEDULES_FILE, HISTORY_FILE
from .vault import vault_mgr
from .verifier import verifier


DEFAULT_JOBS = [
    {
        "id": "job_system_health",
        "name": "Verificação Periódica de Saúde do Sistema",
        "action": "system_verification",
        "interval_minutes": 30,
        "enabled": True,
        "save_note": False,
        "save_log": True,
        "created_at": datetime.now().isoformat(),
        "last_run": None,
        "next_run": None,
        "status": "idle",
        "last_result": None
    },
    {
        "id": "job_vault_integrity",
        "name": "Varredura de Integridade do Vault",
        "action": "vault_integrity",
        "interval_minutes": 60,
        "enabled": True,
        "save_note": False,
        "created_at": datetime.now().isoformat(),
        "last_run": None,
        "next_run": None,
        "status": "idle",
        "last_result": None
    },
    {
        "id": "job_vault_backup",
        "name": "Backup Automatizado do Vault",
        "action": "vault_backup",
        "interval_minutes": 1440,
        "enabled": True,
        "save_note": False,
        "created_at": datetime.now().isoformat(),
        "last_run": None,
        "next_run": None,
        "status": "idle",
        "last_result": None
    }
]


class TaskScheduler:
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._history: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        """Carrega agendamentos e histórico do disco."""
        if SCHEDULES_FILE.exists():
            try:
                data = json.loads(SCHEDULES_FILE.read_text(encoding="utf-8"))
                self._jobs = {j["id"]: j for j in data}
            except Exception:
                self._jobs = {j["id"]: j for j in DEFAULT_JOBS}
        else:
            self._jobs = {j["id"]: j for j in DEFAULT_JOBS}
            self._save_jobs()

        # Garantir next_run inicial para jobs habilitados
        now_ts = time.time()
        for j in self._jobs.values():
            if j.get("enabled") and not j.get("next_run"):
                j["next_run"] = now_ts + (j.get("interval_minutes", 30) * 60)

        if HISTORY_FILE.exists():
            try:
                self._history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            except Exception:
                self._history = []

    def _save_jobs(self):
        with self._lock:
            SCHEDULES_FILE.write_text(json.dumps(list(self._jobs.values()), indent=2, ensure_ascii=False), encoding="utf-8")

    def _save_history(self):
        with self._lock:
            # Manter últimos 100 registros
            trimmed = self._history[-100:]
            HISTORY_FILE.write_text(json.dumps(trimmed, indent=2, ensure_ascii=False), encoding="utf-8")

    def start(self):
        """Inicia worker em background."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="ShaulaSchedulerThread")
        self._thread.start()

    def stop(self):
        self._running = False

    def _worker_loop(self):
        """Loop contínuo de verificação de timers."""
        while self._running:
            now_ts = time.time()
            to_execute = []

            with self._lock:
                for job in self._jobs.values():
                    if not job.get("enabled"):
                        continue
                    next_run = job.get("next_run") or 0
                    if now_ts >= next_run and job.get("status") != "running":
                        to_execute.append(job["id"])

            for jid in to_execute:
                self._execute_job(jid)

            time.sleep(5)

    def _execute_job(self, job_id: str):
        """Executa a rotina do job e registra histórico."""
        job = self._jobs.get(job_id)
        if not job:
            return

        job["status"] = "running"
        self._save_jobs()

        start_time = time.time()
        success = False
        output_msg = ""
        action = job.get("action")

        try:
            if action == "system_verification":
                res = verifier.run_full_verification(save_log=True, save_report_to_vault=False)
                success = True
                log_info = f" (Log arquivado em: {res.get('saved_log_path')})" if res.get('saved_log_path') else ""
                output_msg = f"Status Geral: {res.get('overall_status')} | Alertas: {len(res.get('alerts', []))}{log_info}"

            elif action == "vault_integrity":
                res = vault_mgr.verify_vault_integrity()
                success = True
                output_msg = f"Integridade: {res.get('status')} | {res.get('total_notes')} notas | {res.get('broken_links_count')} links quebrados"

            elif action == "vault_backup":
                res = vault_mgr.backup_vault()
                success = True
                output_msg = f"Backup concluído: {res.get('filename')} ({res.get('size_kb')} KB)"

            else:
                success = False
                output_msg = f"Ação desconhecida: {action}"

        except Exception as e:
            success = False
            output_msg = f"Erro na execução: {str(e)}"

        duration_sec = round(time.time() - start_time, 2)
        now_ts = time.time()

        job["status"] = "idle"
        job["last_run"] = datetime.now().isoformat()
        job["next_run"] = now_ts + (job.get("interval_minutes", 30) * 60)
        job["last_result"] = {
            "success": success,
            "message": output_msg,
            "duration_sec": duration_sec
        }
        self._save_jobs()

        # Registrar no histórico
        event = {
            "id": str(uuid.uuid4())[:8],
            "job_id": job_id,
            "job_name": job.get("name"),
            "action": action,
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "duration_sec": duration_sec,
            "message": output_msg
        }
        self._history.append(event)
        self._save_history()

    def list_jobs(self) -> List[Dict[str, Any]]:
        """Retorna lista de jobs com próxima execução formatada."""
        result = []
        now_ts = time.time()
        for j in self._jobs.values():
            copy = dict(j)
            next_run_ts = j.get("next_run")
            if next_run_ts:
                diff_sec = max(0, int(next_run_ts - now_ts))
                m, s = divmod(diff_sec, 60)
                h, m = divmod(m, 60)
                if h > 0:
                    copy["next_run_human"] = f"em {h}h {m}m"
                elif m > 0:
                    copy["next_run_human"] = f"em {m}m {s}s"
                else:
                    copy["next_run_human"] = f"em {s}s"
            else:
                copy["next_run_human"] = "-"
            result.append(copy)
        return sorted(result, key=lambda x: x.get("name", ""))

    def add_job(self, name: str, action: str, interval_minutes: int, save_note: bool = True) -> Dict[str, Any]:
        """Adiciona novo agendamento."""
        job_id = f"job_{str(uuid.uuid4())[:8]}"
        now_ts = time.time()
        new_job = {
            "id": job_id,
            "name": name,
            "action": action,
            "interval_minutes": max(1, interval_minutes),
            "enabled": True,
            "save_note": save_note,
            "created_at": datetime.now().isoformat(),
            "last_run": None,
            "next_run": now_ts + (interval_minutes * 60),
            "status": "idle",
            "last_result": None
        }
        self._jobs[job_id] = new_job
        self._save_jobs()
        return new_job

    def toggle_job(self, job_id: str, enabled: bool) -> Dict[str, Any]:
        """Habilita ou desabilita um job."""
        if job_id not in self._jobs:
            raise KeyError(f"Job não encontrado: {job_id}")
        job = self._jobs[job_id]
        job["enabled"] = enabled
        if enabled:
            job["next_run"] = time.time() + (job.get("interval_minutes", 30) * 60)
        self._save_jobs()
        return job

    def delete_job(self, job_id: str) -> bool:
        """Remove um agendamento."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save_jobs()
            return True
        return False

    def trigger_job(self, job_id: str) -> bool:
        """Dispara execução imediata em thread separada."""
        if job_id not in self._jobs:
            raise KeyError(f"Job não encontrado: {job_id}")
        threading.Thread(target=self._execute_job, args=(job_id,), daemon=True).start()
        return True

    def get_history(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Retorna últimos eventos de execução."""
        return list(reversed(self._history[-limit:]))


scheduler = TaskScheduler()
