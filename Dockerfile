# 🦂 Shaula Dashboard — Dockerfile Portátil
FROM python:3.12-slim

# Evita buffers no stdout e bytecode desnecessário
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SHAULA_HOST=0.0.0.0 \
    SHAULA_PORT=5000 \
    SHAULA_VAULT_PATH=/app/vault \
    SHAULA_AUX_VAULT_PATH=/app/aux_vault \
    SHAULA_DATA_PATH=/app/data \
    SHAULA_ADMIN_PASSWORD=3884

WORKDIR /app

# Instalar dependências de sistema mínimas se necessário
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tar \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código-fonte da aplicação
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY run.py .

# Criar diretórios de volumes montáveis
RUN mkdir -p /app/vault /app/aux_vault /app/data

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5000/api/vault/tree || exit 1

ENTRYPOINT ["python", "run.py"]
