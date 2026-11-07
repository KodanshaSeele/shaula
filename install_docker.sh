#!/usr/bin/env bash
# ==============================================================================
#  🦂 SHAULA DASHBOARD — Script de Instalação e Inicialização Docker
# ==============================================================================

set -e

echo "🦂 Inicializando Shaula Dashboard no Docker..."

# 1. Verificar pré-requisitos
if ! command -v docker >/dev/null 2>&1; then
    echo "❌ Erro: Docker não está instalado nesta máquina."
    echo "👉 Instale o Docker: https://docs.docker.com/engine/install/"
    exit 1
fi

COMPOSE_CMD=""
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    echo "❌ Erro: Docker Compose não encontrado."
    exit 1
fi

# 2. Criar diretórios locais caso não existam
mkdir -p vault aux_vault data

# 3. Construir e subir o container em background
echo "🔨 Construindo imagem e subindo containers..."
$COMPOSE_CMD up -d --build

# 4. Aguardar inicialização e testar
echo "⏳ Aguardando Shaula inicializar..."
sleep 3

LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "SEU_IP_LOCAL")

echo ""
echo "=============================================================================="
echo "🦂 SHAULA DASHBOARD ESTÁ OPERACIONAL NO DOCKER!"
echo "=============================================================================="
echo "🌐 Acesse no Navegador:"
echo "   - Local:        http://localhost:5000"
echo "   - Rede Local:   http://${LOCAL_IP}:5000"
echo ""
echo "🔐 Tela de Configurações & Vault Auxiliar:"
echo "   - Aba: ⚙️ Configurações"
echo "   - Senha Mestre: 3884"
echo ""
echo "📁 Diretórios Mapeados:"
echo "   - Vault Exclusivo Shaula: ./vault"
echo "   - Vault Auxiliar:         ./aux_vault"
echo "   - Dados e Agendamentos:   ./data"
echo ""
echo "🛑 Para parar: $COMPOSE_CMD down"
echo "📋 Para ver logs: $COMPOSE_CMD logs -f"
echo "=============================================================================="
