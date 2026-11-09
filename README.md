# ◈ Nash RAG Desk

> Dashboard minimalista de tela dupla dedicado exclusivamente a servir a RAG e Segundo Cérebro Obsidian do perfil **Nash** (`/home/kodansha/.hermes/profiles/nash/vault`).

---

## 1. Visão Geral das Telas

| Tela | Função Principal |
|---|---|
| **💻 Terminal Antigravity (Tela 1)** | Terminal interativo completo (xterm.js) conectado via WebSockets e PTY Linux diretamente ao Antigravity CLI (`agy`). Permite consultas à RAG, inspeção de notas, raciocínio passo a passo e escritas no cofre. |
| **📥 Captura Multimodal (Tela 2)** | Ingestão com atrito zero: editor de notas + dropzone de imagens (arrastar e soltar ou `Ctrl+V`). O Gemini 3.8 Flash analisa imagens, extrai dados/OCR, padroniza no modelo canônico e salva os arquivos em `assets/` e a nota em `00 - Inbox/`. |
| **🧹 Curadoria da Inbox** | Triage autônoma em lotes delimitados (NASA JPL-CP-10, máx 10 notas por ciclo): o Gemini lê notas brutas, completa metadados do Frontmatter YAML e move atomicamente para `Work/`, `03 - Knowledge/`, `Personal/` ou `People/`. |
| **📊 Memória & Status** | Telemetria do cofre: total de notas, pendências na Inbox e integridade dos ativos de mídia. |

---

## 2. Como Executar

```bash
cd /home/kodansha/nash-rag-desk
./start.sh
```

Acesse no navegador:
👉 **http://localhost:8770**

---

## 3. Governança e Diretrizes Axiomáticas Ativas

- **Loop PRVC:** Plan & Prune, Isolate & Execute, Validate (PDCA), Commit or Revert.
- **NASA JPL-CP-10:** Lotes de execução delimitados, verificação mandatória pós-escrita (*Read-Back Check*) e fail-fast.
- **Template Canônico:** Todas as notas seguem rigorosamente o modelo canônico de Nash ([`canonical-note-template.md`](file:///home/kodansha/.hermes/profiles/nash/vault/_templates/canonical-note-template.md)) com Frontmatter YAML e wikilinks Obsidian nativos (`[[Nota]]` e `![[assets/IMG_...]]`).
