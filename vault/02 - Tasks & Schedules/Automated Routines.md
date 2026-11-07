---
title: "Rotinas Automatizadas e Agendamentos"
date: "2026-11-06"
tags:
  - scheduler
  - rotinas
  - automação
---

# ⏱️ Rotinas Automatizadas e Agendamentos

Documentação das tarefas automáticas gerenciadas pelo motor de agendamento de **Shaula**.

## Rotinas Padrão
1. **Health Check Periódico (30 min):** Monitora uso de memória, swap, espaço em disco e presença do processo Hermes.
2. **Integridade do Vault (60 min):** Varre todos os arquivos Markdown buscando wikilinks quebrados, links órfãos e arquivos sem frontmatter.
3. **Backup Diário do Vault (24 horas):** Compacta o conteúdo exclusivo em `.backups/shaula_vault_backup_YYYYMMDD.tar.gz`.

Ajuste ou dispare imediatamente pelo painel web de **Shaula**.
Voltar para: [[Shaula Home]]
