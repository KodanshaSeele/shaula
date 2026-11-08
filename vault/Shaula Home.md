---
title: "Shaula Dashboard — Centro de Comando"
date: "2026-11-06"
tags:
  - shaula
  - dashboard
  - vault-exclusive
  - scorpio
status: ativo
---

# 🦂 Shaula (λ Scorpii) — Centro de Comando & Vault

> **Shaula** (*a estrela do ferrão do escorpião*) é a interface unificada de verificação, agendamento de rotinas e gestão de conhecimento.
> Este vault é **exclusivo** para operações, diagnósticos, tarefas e documentações técnicas gerenciadas por este dashboard.

---

## 🧭 Navegação Rápida do Vault

- 📥 **Inbox & Notas Rápidas:** [[00 - Inbox/Quick Scratchpad]]
- 🩺 **Diagnósticos & Verificação:** [[01 - Verification/System Status Baseline]]
- ⏱️ **Agendamentos & Tarefas:** [[02 - Tasks & Schedules/Automated Routines]]
- 📚 **Base de Conhecimento:** [[03 - Knowledge/Indice de Conhecimento]]
- ⚙️ **Configuração & Sistema:** [[04 - System/Architecture & Commands]]

---

## ⚡ Funções Principais

### 1. Verificação Determinística
- Monitoramento de recursos do host: CPU, RAM, Disco e Uptime.
- Supervisão de processos e serviços essenciais:
  - **Gemini / Antigravity Agent** (Gemini 3.8 Flash High)
  - **Docker & Containers**
  - **Ollama LLM Host**
- Geração automática de relatórios de verificação em Markdown diretamente em `01 - Verification/`.

### 2. Agendador em Tempo Real (Scheduler)
- Tarefas recorrentes configuráveis:
  - Verificação de integridade do Vault (links órfãos e tags).
  - Diagnóstico periódico de hardware e serviços.
  - Backup automatizado do Vault em `.backups/`.
- Execução sob demanda (*Run Now*) e logs em tempo real.

### 3. Editor & Gestor de Conhecimento Obsidian
- Criação e alteração instantânea de notas Markdown.
- Suporte a **Wikilinks** (`[[...]]`) interativos e clicáveis (ex: [[03 - Knowledge/Indice de Conhecimento]]).
- Suporte a frontmatter YAML, callouts, checklist de tarefas e tags.

---

## 📋 Checklist Inicial do Sistema

- [x] Limpeza e desativação de serviços legados quebrados
- [x] Inicialização do Vault exclusivo Shaula
- [x] Configuração do motor de verificação de telemetria
- [x] Inicialização do agendador em background
- [ ] Criar primeira rotina de backup periódico
- [ ] Explorar criação de notas com wikilinks

---
*Shaula v1.0.0 — Operando sob paradigma determinístico e auditável.*
