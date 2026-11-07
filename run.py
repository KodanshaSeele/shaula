#!/usr/bin/env python3
"""
Ponto de Entrada de Inicialização do Shaula Dashboard
"""

import sys
import os
from pathlib import Path

# Adiciona o diretório base do Shaula ao sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import uvicorn
from backend.config import HOST, PORT

if __name__ == "__main__":
    uvicorn.run("backend.server:app", host=HOST, port=PORT, log_level="info")
