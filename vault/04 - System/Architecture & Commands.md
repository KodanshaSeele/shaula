---
title: "Arquitetura e Comandos do Sistema Shaula"
date: "2026-11-06"
tags:
  - sistema
  - arquitetura
  - comandos
---

# ⚙️ Arquitetura e Comandos do Shaula

## Visão Geral Técnica
- **Porta HTTP:** 5000 (bind em `0.0.0.0`)
- **Backend:** FastAPI assíncrono com Uvicorn
- **Vault Exclusivo:** `/home/kodansha/shaula_vault`
- **Serviço Systemd:** `shaula.service`

## Comandos Administrativos
```bash
# Verificar status do serviço
sudo systemctl status shaula.service

# Reiniciar o serviço
sudo systemctl restart shaula.service

# Acompanhar logs em tempo real
journalctl -u shaula.service -f
```

## Protocolos de Integridade
- Todas as operações em notas gravam timestamps atualizados no disco.
- Backups automáticos isolados na pasta `.backups/`.
- Verificações salvam logs determinísticos em `01 - Verification/`.
