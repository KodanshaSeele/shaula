# 🦂 Shaula Dashboard — Guia de Instalação Docker

O **Shaula (λ Scorpii)** é um centro de comando estilo Obsidian para gerenciamento de notas em Markdown, verificação de saúde do sistema e agendamento de rotinas.

Este pacote é **100% portátil** e pronto para ser executado em qualquer computador (Linux, Windows com WSL/Docker Desktop ou macOS).

---

## 🚀 Instalação Rápida (Em Outro PC)

### 1. Pré-requisitos
* Docker instalado ([Guia oficial de instalação do Docker](https://docs.docker.com/engine/install/))
* Docker Compose disponível

### 2. Passo a Passo
Basta copiar esta pasta (`shaula/`) para o outro computador (via pendrive, SCP ou git) e executar:

```bash
cd shaula

# Opção 1: Executar script automático de inicialização
./install_docker.sh

# Opção 2: Ou diretamente via docker compose
docker compose up -d --build
```

Após o comando, o dashboard estará ativo imediatamente em:
👉 **[http://localhost:5000](http://localhost:5000)** (ou pelo IP da máquina na rede local: `http://IP_DO_PC:5000`)

---

## ⚙️ Tela de Configurações & Vault Auxiliar

No menu lateral esquerdo (Activity Bar), clique no ícone **⚙️ Configurações**.

1. **Autenticação de Segurança:**
   * **Senha de Acesso:** `3884`
   * Uma vez autenticado, a sessão é liberada no navegador.

2. **Como Funciona o Vault Auxiliar:**
   * O **Vault Shaula** (`./vault`) permanece exclusivo e blindado.
   * O **Vault Auxiliar** (`./aux_vault`) permite conectar outro vault Obsidian que você já possua no computador.
   * Na tela de configurações você pode:
     * **Ativar/Desativar** o Vault Auxiliar.
     * Mudar o caminho da pasta montada.
     * **Importar notas avulsas** do Vault Auxiliar para o Inbox do Shaula em 1 clique.
     * **Sincronizar em lote** (Importação, Exportação ou Bidirecional).

---

## 📂 Estrutura de Pastas Portátil

```text
shaula/
├── Dockerfile                  <- Definição do container Docker
├── docker-compose.yml          <- Orquestração e volumes
├── install_docker.sh           <- Script de inicialização automática
├── requirements.txt            <- Dependências Python (FastAPI, Uvicorn, etc.)
├── run.py                      <- Ponto de entrada da aplicação
├── backend/                    <- Código do servidor (API, Vault, Verifier, Scheduler)
├── frontend/                   <- Interface web Obsidian (HTML, CSS, JS)
├── vault/                      <- Volume do Vault Exclusivo Shaula
├── aux_vault/                  <- Volume do Vault Auxiliar
└── data/                       <- Configurações, agendamentos e histórico persistidos
```

---

## 🛠️ Comandos Úteis do Docker

```bash
# Ver status dos containers
docker compose ps

# Ver logs em tempo real
docker compose logs -f

# Parar o serviço
docker compose down

# Reiniciar o serviço
docker compose restart
```
