#!/usr/bin/env bash
# ==============================================================================
#  🦂 SHAULA — Empacotador Portátil para Transferência entre PCs
# ==============================================================================

set -e

SOURCE_DIR="/home/kodansha/shaula"
DEST_TAR="/home/kodansha/shaula_portable.tar.gz"
DEST_ZIP="/home/kodansha/shaula_portable.zip"

echo "📦 Compactando pacote portátil do Shaula..."

cd /home/kodansha

# Criar arquivo .tar.gz excluindo arquivos desnecessários
tar --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    -czf "$DEST_TAR" shaula/

# Criar .zip se o comando zip existir
if command -v zip >/dev/null 2>&1; then
    zip -q -r "$DEST_ZIP" shaula/ -x "*/__pycache__/*" "*/.git/*"
fi

SIZE_TAR=$(du -h "$DEST_TAR" | cut -f1)

echo "✅ Pacote gerado com sucesso!"
echo "   - Arquivo TAR.GZ: $DEST_TAR ($SIZE_TAR)"
if [ -f "$DEST_ZIP" ]; then
    SIZE_ZIP=$(du -h "$DEST_ZIP" | cut -f1)
    echo "   - Arquivo ZIP:    $DEST_ZIP ($SIZE_ZIP)"
fi
echo ""
echo "🚀 Para levar a outro PC:"
echo "   1. Copie '$DEST_TAR' (ou '$DEST_ZIP') para o outro computador."
echo "   2. Descompacte: tar -xzf shaula_portable.tar.gz"
echo "   3. Entre na pasta: cd shaula"
echo "   4. Execute: ./install_docker.sh"
echo "=============================================================================="
