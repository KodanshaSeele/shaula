"""
Motor de Verificação Determinística do Sistema e Serviços para Shaula
Coleta telemetria em tempo real e gera relatórios formais em Markdown no Vault.
"""

import os
import time
import shutil
import psutil
import socket
import subprocess
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from .config import VAULT_PATH
from .vault import vault_mgr


def check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """Verifica se uma porta TCP está respondendo."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def get_uptime_str() -> str:
    """Retorna string legível de uptime do sistema."""
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    delta = datetime.now() - boot_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


class SystemVerifier:
    def __init__(self):
        pass

    def get_hardware_telemetry(self) -> Dict[str, Any]:
        """Coleta CPU, RAM, Swap e Disco."""
        # CPU
        cpu_pct = psutil.cpu_percent(interval=0.2)
        cpu_count = psutil.cpu_count(logical=True)
        try:
            load1, load5, load15 = os.getloadavg()
        except Exception:
            load1, load5, load15 = 0.0, 0.0, 0.0

        # RAM
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # Disk
        disk_root = psutil.disk_usage("/")
        try:
            disk_home = psutil.disk_usage("/home/kodansha")
        except Exception:
            disk_home = disk_root

        return {
            "uptime": get_uptime_str(),
            "cpu": {
                "percent": cpu_pct,
                "cores": cpu_count,
                "load_avg": [round(load1, 2), round(load5, 2), round(load15, 2)]
            },
            "memory": {
                "total_gb": round(mem.total / (1024**3), 2),
                "used_gb": round(mem.used / (1024**3), 2),
                "available_gb": round(mem.available / (1024**3), 2),
                "percent": mem.percent
            },
            "swap": {
                "total_gb": round(swap.total / (1024**3), 2),
                "used_gb": round(swap.used / (1024**3), 2),
                "percent": swap.percent
            },
            "disk": {
                "root_total_gb": round(disk_root.total / (1024**3), 2),
                "root_used_gb": round(disk_root.used / (1024**3), 2),
                "root_free_gb": round(disk_root.free / (1024**3), 2),
                "root_percent": disk_root.percent,
                "home_total_gb": round(disk_home.total / (1024**3), 2),
                "home_used_gb": round(disk_home.used / (1024**3), 2),
                "home_free_gb": round(disk_home.free / (1024**3), 2),
                "home_percent": disk_home.percent,
            }
        }

    def check_services(self) -> Dict[str, Any]:
        """Inspeciona estado dos serviços e bots essenciais."""
        services = {}

        # 1. Hermes Gateway & Processos
        hermes_procs = []
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = " ".join(proc.info["cmdline"] or [])
                if "hermes" in cmdline.lower() and "grep" not in cmdline:
                    hermes_procs.append({
                        "pid": proc.info["pid"],
                        "name": proc.info["name"],
                        "summary": cmdline[:120]
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        services["hermes"] = {
            "name": "Hermes Agent & Gateway",
            "active": len(hermes_procs) > 0,
            "instances": len(hermes_procs),
            "details": hermes_procs,
            "status_label": "RUNNING" if len(hermes_procs) > 0 else "STOPPED"
        }

        # 2. Ollama
        ollama_active = check_port("127.0.0.1", 11434)
        services["ollama"] = {
            "name": "Ollama LLM Engine",
            "active": ollama_active,
            "port": 11434,
            "status_label": "RUNNING" if ollama_active else "INACTIVE"
        }

        # 3. Docker / Szurubooru
        docker_containers = []
        try:
            res = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}|{{.Status}}|{{.Image}}"],
                capture_output=True, text=True, timeout=3
            )
            if res.returncode == 0:
                for line in res.stdout.strip().splitlines():
                    if line:
                        parts = line.split("|")
                        if len(parts) >= 3:
                            docker_containers.append({
                                "name": parts[0],
                                "status": parts[1],
                                "image": parts[2]
                            })
        except Exception:
            pass

        services["docker"] = {
            "name": "Docker & Containers",
            "active": len(docker_containers) > 0,
            "containers_count": len(docker_containers),
            "containers": docker_containers,
            "status_label": "RUNNING" if len(docker_containers) > 0 else "NO CONTAINERS"
        }

        # 4. Shaula Dashboard
        services["shaula"] = {
            "name": "Shaula Command Dashboard",
            "active": True,
            "port": 5000,
            "status_label": "ONLINE"
        }

        return services

    def run_full_verification(self, save_report_to_vault: bool = True) -> Dict[str, Any]:
        """Executa verificação determinística e gera documento Markdown formal."""
        timestamp = datetime.now()
        ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        file_ts = timestamp.strftime("%Y%m%d_%H%M%S")

        telemetry = self.get_hardware_telemetry()
        services = self.check_services()
        vault_integrity = vault_mgr.verify_vault_integrity()

        # Determinar status geral
        alerts = []
        if telemetry["memory"]["percent"] > 90:
            alerts.append(f"Uso de memória elevado: {telemetry['memory']['percent']}%")
        if telemetry["disk"]["root_percent"] > 90:
            alerts.append(f"Disco raiz com pouco espaço: {telemetry['disk']['root_percent']}%")
        if not services["hermes"]["active"]:
            alerts.append("Hermes Gateway não foi detectado em execução.")
        if vault_integrity["broken_links_count"] > 0:
            alerts.append(f"{vault_integrity['broken_links_count']} wikilink(s) quebrado(s) no vault.")

        overall_status = "CRITICAL" if any("elevado" in a or "pouco espaço" in a for a in alerts) else ("WARNING" if alerts else "OPTIMAL")

        report_data = {
            "timestamp": ts_str,
            "overall_status": overall_status,
            "alerts": alerts,
            "telemetry": telemetry,
            "services": services,
            "vault": vault_integrity
        }

        saved_path = None
        if save_report_to_vault:
            report_md = self._render_report_markdown(report_data)
            rel_file = f"01 - Verification/Verificacao_{file_ts}.md"
            vault_mgr.create_note(rel_file, f"Verificação {ts_str}", report_md)
            saved_path = rel_file

        report_data["saved_note_path"] = saved_path
        return report_data

    def _render_report_markdown(self, data: Dict[str, Any]) -> str:
        """Gera o Markdown com links Obsidian e formatação técnica."""
        t = data["telemetry"]
        s = data["services"]
        v = data["vault"]
        alerts = data["alerts"]

        alerts_md = "\n".join([f"- ⚠️ **{a}**" for a in alerts]) if alerts else "- ✅ Nenhum alerta crítico detectado."

        docker_rows = "\n".join([f"| `{c['name']}` | {c['status']} | `{c['image']}` |" for c in s["docker"]["containers"]]) or "| *Nenhum container* | - | - |"

        return f"""---
title: "Relatório de Verificação — {data['timestamp']}"
date: "{data['timestamp']}"
tags:
  - verificação
  - diagnostico
  - telemetria
status: {data['overall_status']}
---

# 🩺 Relatório de Verificação Determinística — Shaula

> **Data de Execução:** {data['timestamp']}  
> **Estado Geral:** `{data['overall_status']}`  
> **Uptime do Host:** `{t['uptime']}`  
> **Vault:** [[Shaula Home]]

---

## 🚨 Alertas & Observações
{alerts_md}

---

## 💻 Telemetria de Hardware

| Recurso | Utilização | Detalhes |
| :--- | :--- | :--- |
| **CPU** | `{t['cpu']['percent']}%` | {t['cpu']['cores']} Núcleos (Load: `{t['cpu']['load_avg']}`) |
| **RAM** | `{t['memory']['percent']}%` | `{t['memory']['used_gb']} GB` / `{t['memory']['total_gb']} GB` (Livre: `{t['memory']['available_gb']} GB`) |
| **Swap** | `{t['swap']['percent']}%` | `{t['swap']['used_gb']} GB` / `{t['swap']['total_gb']} GB` |
| **Disco (/)** | `{t['disk']['root_percent']}%` | `{t['disk']['root_used_gb']} GB` / `{t['disk']['root_total_gb']} GB` |
| **Disco (/home)** | `{t['disk']['home_percent']}%` | `{t['disk']['home_used_gb']} GB` / `{t['disk']['home_total_gb']} GB` |

---

## 🛰️ Serviços & Processos

| Serviço | Status | Porta/Instâncias |
| :--- | :--- | :--- |
| **Hermes Gateway** | `{s['hermes']['status_label']}` | {s['hermes']['instances']} processo(s) ativo(s) |
| **Ollama Engine** | `{s['ollama']['status_label']}` | Porta 11434 |
| **Docker (Total)** | `{s['docker']['status_label']}` | {s['docker']['containers_count']} container(s) |
| **Shaula Dashboard** | `{s['shaula']['status_label']}` | Porta 5000 |

### Containers Docker Ativos
| Container | Status | Imagem |
| :--- | :--- | :--- |
{docker_rows}

---

## 🗄️ Integridade do Vault Exclusivo

- **Total de Notas:** `{v['total_notes']}`
- **Total de Palavras:** `{v['total_words']}`
- **Total de Tags:** `{v['total_tags']}`
- **Wikilinks Quebrados:** `{v['broken_links_count']}`
- **Notas Órfãs:** `{v['orphan_notes_count']}`

---
*Relatório gerado automaticamente pelo núcleo Shaula.*
"""


verifier = SystemVerifier()
