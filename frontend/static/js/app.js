// Nash RAG Desk - Mobile & Accessibility Controller
let term = null;
let fitAddon = null;
let ws = null;
let selectedImages = [];

// Resolução de Base Path dinâmica (suporta / ou /desk/ no túnel)
function getBasePath() {
  let p = window.location.pathname;
  if (!p.endsWith("/")) {
    p += "/";
  }
  return p;
}
const BASE_PATH = getBasePath();

// Níveis de Tamanho para Acessibilidade (Independentes)
const FONT_SIZES = [15, 17, 19, 22, 25, 28];
const ICON_SIZES = [20, 24, 28, 34, 40];
let currentFontIdx = 1; // default 17px
let currentIconIdx = 1; // default 24px
let isTouchComfortable = true;

document.addEventListener("DOMContentLoaded", () => {
  initAccessibility();
  initTabs();
  initStats();
  initProjects();
  initIngest();
  initTriage();
  initTerminal();

  // Polling periódico de métricas
  setInterval(initStats, 15000);
});

// -----------------------------------------------------------------------------
// ACESSIBILIDADE VISUAL (SEM ÓCULOS) - LETRAS E ÍCONES INDEPENDENTES
// -----------------------------------------------------------------------------
function initAccessibility() {
  // Carrega do localStorage
  const savedFont = parseInt(localStorage.getItem("nash_font_size"), 10);
  const savedIcon = parseInt(localStorage.getItem("nash_icon_size"), 10);
  const savedTouch = localStorage.getItem("nash_touch_comfort");

  if (!isNaN(savedFont)) {
    const idx = FONT_SIZES.indexOf(savedFont);
    if (idx !== -1) currentFontIdx = idx;
  }
  if (!isNaN(savedIcon)) {
    const idx = ICON_SIZES.indexOf(savedIcon);
    if (idx !== -1) currentIconIdx = idx;
  }
  if (savedTouch !== null) {
    isTouchComfortable = savedTouch === "true";
  }

  applyAccessibility();

  // Controles de Letra
  document.getElementById("btn-font-dec")?.addEventListener("click", () => {
    if (currentFontIdx > 0) {
      currentFontIdx--;
      applyAccessibility();
    }
  });

  document.getElementById("btn-font-inc")?.addEventListener("click", () => {
    if (currentFontIdx < FONT_SIZES.length - 1) {
      currentFontIdx++;
      applyAccessibility();
    }
  });

  // Controles de Ícone
  document.getElementById("btn-icon-dec")?.addEventListener("click", () => {
    if (currentIconIdx > 0) {
      currentIconIdx--;
      applyAccessibility();
    }
  });

  document.getElementById("btn-icon-inc")?.addEventListener("click", () => {
    if (currentIconIdx < ICON_SIZES.length - 1) {
      currentIconIdx++;
      applyAccessibility();
    }
  });

  // Controle de Toque
  document.getElementById("btn-touch-toggle")?.addEventListener("click", () => {
    isTouchComfortable = !isTouchComfortable;
    applyAccessibility();
  });

  // Botão ⚙️ no Header
  document.getElementById("btn-quick-settings")?.addEventListener("click", () => {
    switchTab("view-settings");
  });
}

function applyAccessibility() {
  const fontSize = FONT_SIZES[currentFontIdx];
  const iconSize = ICON_SIZES[currentIconIdx];
  const touchTarget = isTouchComfortable ? 54 : 46;

  document.documentElement.style.setProperty("--base-font-size", `${fontSize}px`);
  document.documentElement.style.setProperty("--base-icon-size", `${iconSize}px`);
  document.documentElement.style.setProperty("--touch-target", `${touchTarget}px`);

  // Labels
  const valFont = document.getElementById("val-font-size");
  const valIcon = document.getElementById("val-icon-size");
  const descFont = document.getElementById("label-font-desc");
  const descIcon = document.getElementById("label-icon-desc");
  const btnTouch = document.getElementById("btn-touch-toggle");

  if (valFont) valFont.innerText = `${fontSize}px`;
  if (valIcon) valIcon.innerText = `${iconSize}px`;

  if (descFont) {
    const labels = ["Compacto", "Normal", "Grande", "Muito Grande", "Gigante", "Máximo"];
    descFont.innerText = labels[currentFontIdx] || `${fontSize}px`;
  }
  if (descIcon) {
    const labels = ["Pequeno", "Normal", "Grande", "Muito Grande", "Gigante"];
    descIcon.innerText = labels[currentIconIdx] || `${iconSize}px`;
  }
  if (btnTouch) {
    btnTouch.innerText = isTouchComfortable ? "Amplo (Fácil)" : "Padrão";
  }

  // Persiste
  localStorage.setItem("nash_font_size", fontSize);
  localStorage.setItem("nash_icon_size", iconSize);
  localStorage.setItem("nash_touch_comfort", isTouchComfortable);

  // Redimensiona terminal se ativo
  if (term) {
    term.options.fontSize = fontSize - 2;
    if (fitAddon) {
      setTimeout(() => fitAddon.fit(), 50);
    }
  }
}

// -----------------------------------------------------------------------------
// BOTTOM NAVIGATION
// -----------------------------------------------------------------------------
function initTabs() {
  const navItems = document.querySelectorAll(".nav-item");

  navItems.forEach(item => {
    item.addEventListener("click", () => {
      const target = item.dataset.target;
      switchTab(target);
    });
  });
}

let termHeartbeatInterval = null;
let termReconnectTimer = null;

function switchTab(targetId) {
  const navItems = document.querySelectorAll(".nav-item");
  const views = document.querySelectorAll(".screen-view");

  navItems.forEach(item => {
    item.classList.toggle("active", item.dataset.target === targetId);
  });

  views.forEach(view => {
    const isActive = view.id === targetId;
    view.classList.toggle("active", isActive);
    if (isActive) {
      if (targetId === "view-terminal") {
        if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
          connectTerminalWs();
        }
        if (fitAddon && term) {
          setTimeout(() => {
            fitAddon.fit();
            sendResize();
            term.focus();
          }, 80);
        }
      }
      if (targetId === "view-triage") {
        loadInbox();
      }
    }
  });
}

// -----------------------------------------------------------------------------
// TELA 1: TERMINAL & TOOLBAR MOBILE
// -----------------------------------------------------------------------------
function initTerminal() {
  const container = document.getElementById("terminal-box");
  if (!container) return;

  const currentFont = FONT_SIZES[currentFontIdx] - 2;

  term = new Terminal({
    cursorBlink: true,
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: currentFont,
    theme: {
      background: "#000000",
      foreground: "#f4f4f5",
      cursor: "#a78bfa",
      selectionBackground: "rgba(167, 139, 250, 0.3)",
      black: "#18181b",
      red: "#ef4444",
      green: "#10b981",
      yellow: "#f59e0b",
      blue: "#3b82f6",
      magenta: "#a855f7",
      cyan: "#06b6d4",
      white: "#fafafa"
    }
  });

  fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  if (typeof WebLinksAddon !== "undefined") {
    term.loadAddon(new WebLinksAddon.WebLinksAddon());
  }

  term.open(container);
  fitAddon.fit();

  connectTerminalWs();

  window.addEventListener("resize", () => {
    if (fitAddon && term) {
      fitAddon.fit();
      sendResize();
    }
  });

  // Mobile Virtual Toolbar
  document.querySelectorAll(".tool-key").forEach(btn => {
    btn.addEventListener("click", () => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const key = btn.dataset.key;
      const cmd = btn.dataset.cmd;

      if (cmd) {
        ws.send(cmd);
      } else if (key === "ESC") {
        ws.send("\x1b");
      } else if (key === "TAB") {
        ws.send("\t");
      } else if (key === "CTRL_C") {
        ws.send("\x03");
      } else if (key === "UP") {
        ws.send("\x1b[A");
      } else if (key === "DOWN") {
        ws.send("\x1b[B");
      }
      term.focus();
    });
  });

  document.getElementById("btn-clear-term")?.addEventListener("click", () => {
    term.clear();
  });
}

function connectTerminalWs() {
  if (termReconnectTimer) {
    clearTimeout(termReconnectTimer);
    termReconnectTimer = null;
  }
  if (termHeartbeatInterval) {
    clearInterval(termHeartbeatInterval);
    termHeartbeatInterval = null;
  }

  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const cleanBase = BASE_PATH.replace(/\/+$/, "");
  const wsUrl = `${proto}//${window.location.host}${cleanBase}/ws/terminal`;

  term.writeln("\x1b[35m◈ Conectando ao Antigravity PTY (Nash Vault)...\x1b[0m\r\n");
  ws = new WebSocket(wsUrl);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    term.writeln("\x1b[32m✔ Antigravity Ativo. Cofre: /home/kodansha/.hermes/profiles/nash/vault\x1b[0m\r\n");
    sendResize();

    // Heartbeat de 15s para manter o túnel do Tailscale Funnel / proxy ativo
    termHeartbeatInterval = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, 15000);
  };

  ws.onmessage = (event) => {
    if (typeof event.data === "string") {
      // Intercepta mensagens de heartbeat e controle sem poluir a tela do xterm
      if (event.data.startsWith("{") && event.data.includes('"type"')) {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "ping") {
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: "pong" }));
            }
            return;
          } else if (msg.type === "pong") {
            return;
          }
        } catch (e) {
          // Não é JSON de controle, prossegue escrevendo no terminal
        }
      }
      term.write(event.data);
    } else {
      const bytes = new Uint8Array(event.data);
      term.write(bytes);
    }
  };

  ws.onclose = () => {
    if (termHeartbeatInterval) {
      clearInterval(termHeartbeatInterval);
      termHeartbeatInterval = null;
    }
    term.writeln("\r\n\x1b[33m◈ Conexão com terminal pausada. Reconectando em 2s...\x1b[0m\r\n");

    if (termReconnectTimer) clearTimeout(termReconnectTimer);
    termReconnectTimer = setTimeout(() => {
      const activeTab = document.querySelector(".screen-view.active");
      if (activeTab && activeTab.id === "view-terminal") {
        connectTerminalWs();
      }
    }, 2500);
  };

  ws.onerror = () => {
    term.writeln("\r\n\x1b[31m✖ Erro no WebSocket do Terminal.\x1b[0m\r\n");
  };

  if (!term._hasDataHandler) {
    term.onData((data) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(data);
      }
    });
    term._hasDataHandler = true;
  }

  const container = document.getElementById("terminal-box");
  if (container && !container._hasClickListener) {
    container.addEventListener("click", () => {
      if (!ws || ws.readyState === WebSocket.CLOSED) {
        connectTerminalWs();
      }
    });
    container._hasClickListener = true;
  }
}

function sendResize() {
  if (ws && ws.readyState === WebSocket.OPEN && term) {
    ws.send(JSON.stringify({
      type: "resize",
      cols: term.cols,
      rows: term.rows
    }));
  }
}

// -----------------------------------------------------------------------------
// TELA 2: INGESTÃO MULTIMODAL & CÂMERA MOBILE
// -----------------------------------------------------------------------------
// -----------------------------------------------------------------------------
// TELA 2: INGESTÃO MULTIMODAL (SHAULA DUAL-CASE: VISÃO vs TEXTO PURO)
// -----------------------------------------------------------------------------
let analysisResult = null;
let activeCaseMode = "vision"; // "vision" ou "text"

function initIngest() {
  const cameraInput = document.getElementById("camera-input");
  const galleryInput = document.getElementById("gallery-input");
  const gallery = document.getElementById("image-gallery");
  const btnAnalyze = document.getElementById("btn-analyze-ingest");
  const statusMsg = document.getElementById("ingest-status-msg");
  const valCard = document.getElementById("validation-card");
  const btnApprove = document.getElementById("btn-approve-note");
  const btnDiscard = document.getElementById("btn-discard-validation");
  const btnCaseVision = document.getElementById("btn-case-vision");
  const btnCaseText = document.getElementById("btn-case-text");
  const valAssetsMeta = document.getElementById("val-assets-meta");
  const imgModal = document.getElementById("image-modal");
  const btnCloseModal = document.getElementById("btn-close-modal");
  const modalImgSrc = document.getElementById("modal-image-src");
  const btnQuickFull = document.getElementById("btn-quick-full");
  const btnQuickPhoto = document.getElementById("btn-quick-photo");
  const btnQuickNote = document.getElementById("btn-quick-note");
  const noteContentEl = document.getElementById("note-content");

  // Seletor Rápido de Ação (Imagem + Nota / Apenas Imagem / Apenas Nota)
  function setQuickMode(mode) {
    btnQuickFull?.classList.toggle("active", mode === "full");
    btnQuickPhoto?.classList.toggle("active", mode === "photo");
    btnQuickNote?.classList.toggle("active", mode === "note");

    if (mode === "full") {
      if (noteContentEl) noteContentEl.placeholder = "Descreva a ocorrência, parâmetros e anexe fotos para análise visual e cruzamento com o banco...";
    } else if (mode === "photo") {
      if (noteContentEl) noteContentEl.placeholder = "(Opcional) Observações complementares sobre as fotos ou deixe em branco para análise visual direta no banco...";
      if (selectedImages.length === 0) {
        galleryInput?.click();
      }
    } else if (mode === "note") {
      if (noteContentEl) noteContentEl.placeholder = "O que você deseja registrar? Descreva observações, parâmetros, medições, dúvidas ou ideias...";
    }
    updateIngestButtonLabel();
  }

  btnQuickFull?.addEventListener("click", () => setQuickMode("full"));
  btnQuickPhoto?.addEventListener("click", () => setQuickMode("photo"));
  btnQuickNote?.addEventListener("click", () => setQuickMode("note"));

  function updateIngestButtonLabel() {
    if (!btnAnalyze || btnAnalyze.disabled) return;
    const content = noteContentEl ? noteContentEl.value.trim() : "";
    const hasImages = selectedImages.length > 0;

    if (hasImages && content) {
      btnAnalyze.innerHTML = "<span>🔍 Avaliar Imagem + Nota (OCR & Banco) & Revisar</span>";
    } else if (hasImages && !content) {
      btnAnalyze.innerHTML = "<span>🔍 Avaliar Imagem (OCR & Banco) & Revisar</span>";
    } else if (!hasImages && content) {
      btnAnalyze.innerHTML = "<span>📝 Avaliar Nota & Revisar</span>";
    } else {
      btnAnalyze.innerHTML = "<span>🔍 Avaliar com Gemini (OCR & Banco) & Revisar</span>";
    }
  }

  noteContentEl?.addEventListener("input", updateIngestButtonLabel);

  // Fechar Modal
  btnCloseModal?.addEventListener("click", () => {
    imgModal?.classList.remove("open");
  });
  imgModal?.addEventListener("click", (e) => {
    if (e.target === imgModal) imgModal.classList.remove("open");
  });

  // Câmera e Galeria
  cameraInput?.addEventListener("change", (e) => {
    if (e.target.files) addFiles(e.target.files);
  });

  galleryInput?.addEventListener("change", (e) => {
    if (e.target.files) addFiles(e.target.files);
  });

  function addFiles(files) {
    for (let i = 0; i < files.length; i++) {
      if (files[i].type.startsWith("image/")) {
        selectedImages.push(files[i]);
      }
    }
    renderGallery();
  }

  function renderGallery() {
    if (!gallery) return;
    gallery.innerHTML = "";
    selectedImages.forEach((file, idx) => {
      const div = document.createElement("div");
      div.className = "gallery-thumb";

      const img = document.createElement("img");
      img.src = URL.createObjectURL(file);
      img.title = "Clique para ampliar";
      img.onclick = () => {
        if (modalImgSrc && imgModal) {
          modalImgSrc.src = img.src;
          imgModal.classList.add("open");
        }
      };

      const del = document.createElement("button");
      del.className = "del-btn";
      del.innerHTML = "✕";
      del.onclick = (e) => {
        e.stopPropagation();
        selectedImages.splice(idx, 1);
        renderGallery();
      };

      div.appendChild(img);
      div.appendChild(del);
      gallery.appendChild(div);
    });
    updateIngestButtonLabel();
  }

  // Toggle entre Caso 1 (Visão) e Caso 2 (Texto Puro)
  btnCaseVision?.addEventListener("click", () => {
    if (!analysisResult) return;
    activeCaseMode = "vision";
    btnCaseVision.classList.add("active");
    btnCaseText.classList.remove("active");
    document.getElementById("val-markdown").value = analysisResult.case_with_vision || "";
  });

  btnCaseText?.addEventListener("click", () => {
    if (!analysisResult) return;
    activeCaseMode = "text";
    btnCaseText.classList.add("active");
    btnCaseVision.classList.remove("active");
    document.getElementById("val-markdown").value = analysisResult.case_without_vision || "";
  });

  // 1. Processar Ingestão (Avaliação de OCR & Cruzamento com Banco - Aprovação Humana Obrigatória)
  btnAnalyze?.addEventListener("click", async () => {
    const content = document.getElementById("note-content").value.trim();

    if (!content && selectedImages.length === 0) {
      showToast("Digite observações ou anexe uma foto.");
      return;
    }

    const targetFolder = document.getElementById("capture-target-folder")?.value || "auto";

    btnAnalyze.disabled = true;
    btnAnalyze.innerHTML = "<span>⏳ Shaula transcrevendo OCR & cruzando com banco...</span>";
    statusMsg.innerText = "Transcrevendo texto da imagem com Gemini e cruzando com o banco...";

    const formData = new FormData();
    formData.append("content", content);
    selectedImages.forEach(img => formData.append("images", img));

    try {
      const res = await fetch(BASE_PATH + "api/ingest/analyze", {
        method: "POST",
        body: formData
      });
      const data = await res.json();

      if (res.ok && data.success) {
        analysisResult = data;
        activeCaseMode = (selectedImages.length > 0) ? "vision" : "text";

        // Atualiza campos de validação
        document.getElementById("val-title").value = data.proposed_title || "";
        document.getElementById("val-reasoning-text").innerText = data.reasoning || "Shaula cruzou os dados com o cofre de Nash.";
        document.getElementById("val-markdown").value = (activeCaseMode === "vision" ? data.case_with_vision : data.case_without_vision) || data.canonical_markdown || "";

        // Reset do toggle de casos
        if (activeCaseMode === "vision") {
          btnCaseVision?.classList.add("active");
          btnCaseText?.classList.remove("active");
        } else {
          btnCaseText?.classList.add("active");
          btnCaseVision?.classList.remove("active");
        }

        // Informações da Mídia Sanitizada
        if (valAssetsMeta) {
          if (data.assets_metadata && data.assets_metadata.length > 0) {
            valAssetsMeta.style.display = "inline-flex";
            const metas = data.assets_metadata.map(m => `📷 ${m.filename} (${m.width}x${m.height} • ${m.size_kb} KB • ${m.format})`).join(" | ");
            valAssetsMeta.innerText = metas;
          } else {
            valAssetsMeta.style.display = "none";
          }
        }

        // Cruzamento com Banco de Dados PCM & Grimorium na Validação
        const valDbBox = document.getElementById("val-db-crossref-box");
        const valDbText = document.getElementById("val-db-crossref-text");
        if (valDbBox && valDbText) {
          if (data.database_crossref && data.database_crossref.has_match) {
            valDbBox.style.display = "block";
            valDbText.innerText = data.database_crossref.summary_context || "Ativo identificado no banco.";
          } else if (data.database_crossref && data.database_crossref.summary_context) {
            valDbBox.style.display = "block";
            valDbText.innerText = data.database_crossref.summary_context;
          } else {
            valDbBox.style.display = "none";
          }
        }

        // Seleciona destino proposto
        const folderSelect = document.getElementById("val-target-folder");
        const fToSet = (targetFolder !== "auto") ? targetFolder : data.target_folder;
        if (folderSelect && fToSet) {
          for (let opt of folderSelect.options) {
            if (opt.value.toLowerCase() === fToSet.toLowerCase() || fToSet.toLowerCase().includes(opt.value.toLowerCase())) {
              folderSelect.value = opt.value;
              break;
            }
          }
        }

        valCard.style.display = "flex";
        valCard.scrollIntoView({ behavior: "smooth", block: "start" });
        statusMsg.innerText = "✔ Avaliação e OCR concluídos. Confira os dados e aprove abaixo para gravar.";
      } else {
        showToast("Erro na avaliação: " + (data.detail || "Falha"));
        statusMsg.innerText = "Erro ao avaliar.";
      }
    } catch (err) {
      showToast("Erro de conexão: " + err.message);
      statusMsg.innerText = "Erro de conexão.";
    } finally {
      btnAnalyze.disabled = false;
      updateIngestButtonLabel();
    }
  });

  // Fechar card de sucesso
  document.getElementById("btn-dismiss-saved")?.addEventListener("click", () => {
    const successCard = document.getElementById("saved-success-card");
    if (successCard) successCard.style.display = "none";
  });

  // 2. Aprovar e Alocar no Destino Final (Aprovação Humana Mandatória)
  btnApprove?.addEventListener("click", async () => {
    const title = document.getElementById("val-title").value.trim();
    const targetFolder = document.getElementById("val-target-folder").value;
    const markdownContent = document.getElementById("val-markdown").value;

    if (!title) {
      showToast("Informe o título da nota.");
      return;
    }

    btnApprove.disabled = true;
    btnApprove.innerHTML = "<span>⏳ Shaula gravando no cofre...</span>";

    try {
      const res = await fetch(BASE_PATH + "api/ingest/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title,
          target_folder: targetFolder,
          content: markdownContent
        })
      });
      const data = await res.json();

      if (res.ok && data.success) {
        const modeLabel = activeCaseMode === "vision" ? "Com Visão" : "Sem Visão";
        showToast(`🎉 Nota aprovada (${modeLabel}) e gravada em ${data.folder}!`);

        // Exibe card de sucesso com resumo e dados do cruzamento
        const successCard = document.getElementById("saved-success-card");
        if (successCard) {
          document.getElementById("saved-note-title").innerText = data.title || title;
          document.getElementById("saved-note-path").innerText = `📄 ${data.path}`;
          document.getElementById("saved-reasoning-text").innerText = (analysisResult && analysisResult.reasoning) || "Nota conferida e aprovada pelo operador.";
          document.getElementById("saved-note-preview").innerText = markdownContent || "";

          const metaBox = document.getElementById("saved-assets-meta");
          if (metaBox) {
            if (analysisResult && analysisResult.assets_metadata && analysisResult.assets_metadata.length > 0) {
              metaBox.style.display = "inline-flex";
              metaBox.innerText = analysisResult.assets_metadata.map(m => `📷 ${m.filename} (${m.width}x${m.height} • ${m.size_kb} KB • ${m.format})`).join(" | ");
            } else {
              metaBox.style.display = "none";
            }
          }

          // Bloco de Cruzamento com Banco de Dados PCM & Grimorium
          const dbBox = document.getElementById("saved-db-crossref-box");
          const dbText = document.getElementById("saved-db-crossref-text");
          if (dbBox && dbText) {
            if (analysisResult && analysisResult.database_crossref && analysisResult.database_crossref.has_match) {
              dbBox.style.display = "block";
              dbText.innerText = analysisResult.database_crossref.summary_context || "Ativo identificado no banco.";
            } else if (analysisResult && analysisResult.database_crossref && analysisResult.database_crossref.summary_context) {
              dbBox.style.display = "block";
              dbText.innerText = analysisResult.database_crossref.summary_context;
            } else {
              dbBox.style.display = "none";
            }
          }

          successCard.style.display = "flex";
          successCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
        
        document.getElementById("note-content").value = "";
        selectedImages = [];
        renderGallery();
        valCard.style.display = "none";
        statusMsg.innerText = `✔ Alocada com sucesso em ${data.path}`;
        analysisResult = null;
        
        initStats();
      } else {
        showToast("Erro ao gravar: " + (data.detail || "Falha"));
      }
    } catch (err) {
      showToast("Erro de conexão: " + err.message);
    } finally {
      btnApprove.disabled = false;
      btnApprove.innerHTML = "<span>✔ Aprovar & Alocar no Destino Final</span>";
    }
  });

  // 3. Descartar / Recomeçar
  btnDiscard?.addEventListener("click", () => {
    valCard.style.display = "none";
    analysisResult = null;
    statusMsg.innerText = "Avaliação descartada. Digite uma nova anotação.";
    document.getElementById("capture-card").scrollIntoView({ behavior: "smooth" });
  });
}

// -----------------------------------------------------------------------------
// TELA 3: CURADORIA DA INBOX (CONTÍNUA SOB DEMANDA ATÉ O FIM)
// -----------------------------------------------------------------------------
let triagePollTimer = null;
let isCuratorActive = false;

function initTriage() {
  const btnToggle = document.getElementById("btn-toggle-triage");
  const btnSingle = document.getElementById("btn-single-batch-triage");

  // Iniciar / Pausar Curadoria Contínua
  btnToggle?.addEventListener("click", async () => {
    if (isCuratorActive) {
      // Solicita parada
      btnToggle.disabled = true;
      btnToggle.innerHTML = "<span>⏳ Interrompendo...</span>";
      try {
        await fetch(BASE_PATH + "api/triage/stop", { method: "POST" });
        showToast("Interrupção solicitada.");
      } catch (e) {
        showToast("Erro ao pausar: " + e.message);
      } finally {
        btnToggle.disabled = false;
      }
    } else {
      // Inicia até o fim
      btnToggle.disabled = true;
      btnToggle.innerHTML = "<span>⏳ Iniciando motor de curadoria...</span>";
      try {
        const res = await fetch(BASE_PATH + "api/triage/start", { method: "POST" });
        const data = await res.json();
        showToast(`Curadoria iniciada! Total: ${data.total_initial} notas.`);
        startTriagePolling();
      } catch (e) {
        showToast("Erro ao iniciar: " + e.message);
      } finally {
        btnToggle.disabled = false;
      }
    }
  });

  // Executar Apenas 1 Lote (10 notas)
  btnSingle?.addEventListener("click", async () => {
    btnSingle.disabled = true;
    btnSingle.innerHTML = "<span>⏳ Processando lote de 10...</span>";
    const logBox = document.getElementById("triage-log-box");
    logBox.innerText += `\n[${new Date().toLocaleTimeString()}] Executando 1 lote isolado...\n`;

    try {
      const res = await fetch(BASE_PATH + "api/triage/run-single", { method: "POST" });
      const data = await res.json();
      if (data.logs) {
        data.logs.forEach(l => logBox.innerText += `${l}\n`);
      }
      showToast(`Processadas ${data.processed} notas.`);
      loadInbox();
      initStats();
      syncTriageStatus();
    } catch (err) {
      logBox.innerText += `Erro: ${err.message}\n`;
    } finally {
      btnSingle.disabled = false;
      btnSingle.innerHTML = "<span>⚡ Executar Apenas 1 Lote (10 notas)</span>";
    }
  });

  // Primeira checagem de status ao carregar
  syncTriageStatus();
}

function startTriagePolling() {
  if (triagePollTimer) clearInterval(triagePollTimer);
  triagePollTimer = setInterval(syncTriageStatus, 1200);
}

function stopTriagePolling() {
  if (triagePollTimer) {
    clearInterval(triagePollTimer);
    triagePollTimer = null;
  }
}

async function syncTriageStatus() {
  try {
    const res = await fetch(BASE_PATH + "api/triage/status");
    const data = await res.json();

    isCuratorActive = data.is_running;

    // Elementos da UI
    const badge = document.getElementById("triage-status-badge");
    const btnToggle = document.getElementById("btn-toggle-triage");
    const remCount = document.getElementById("triage-remaining-count");
    const procCount = document.getElementById("triage-processed-count");
    const pctLabel = document.getElementById("triage-percent-label");
    const pBar = document.getElementById("triage-progress-bar");
    const curFile = document.getElementById("triage-current-file");
    const logBox = document.getElementById("triage-log-box");

    if (remCount) remCount.innerText = data.remaining;
    if (procCount) procCount.innerText = data.processed;
    if (pctLabel) pctLabel.innerText = `${data.percent}%`;
    if (pBar) pBar.style.width = `${data.percent}%`;

    if (data.is_running) {
      if (badge) {
        badge.innerHTML = "● Curadoria Automática Ativa";
        badge.style.background = "rgba(16, 185, 129, 0.2)";
        badge.style.color = "#34d399";
        badge.style.borderColor = "rgba(16, 185, 129, 0.4)";
        badge.classList.add("pulse-active");
      }
      if (btnToggle) {
        btnToggle.innerHTML = "<span>⏸ Pausar / Interromper Curadoria</span>";
        btnToggle.style.background = "#dc2626"; // Vermelho de parada
      }
      if (curFile) {
        curFile.innerText = data.current_file ? `Processando: ${data.current_file}` : "Analisando lote de notas...";
      }
      if (!triagePollTimer) {
        startTriagePolling();
      }
    } else {
      if (badge) {
        if (data.remaining === 0 && data.processed > 0) {
          badge.innerHTML = "✔ Inbox 100% Limpa";
          badge.style.background = "rgba(16, 185, 129, 0.25)";
          badge.style.color = "#34d399";
        } else {
          badge.innerHTML = "⚪ Parado";
          badge.style.background = "rgba(161, 161, 170, 0.15)";
          badge.style.color = "var(--text-muted)";
          badge.style.borderColor = "rgba(161, 161, 170, 0.3)";
        }
        badge.classList.remove("pulse-active");
      }
      if (btnToggle) {
        btnToggle.innerHTML = "<span>▶ Iniciar Curadoria Automática (Até o Fim)</span>";
        btnToggle.style.background = "var(--accent)";
      }
      if (curFile) {
        curFile.innerText = data.remaining === 0 ? "Inbox totalmente limpa e organizada!" : "Pronto para iniciar sob demanda.";
      }
      stopTriagePolling();
    }

    // Atualiza logs recentes
    if (logBox && data.recent_logs && data.recent_logs.length > 0) {
      logBox.innerText = data.recent_logs.join("\n");
      logBox.scrollTop = logBox.scrollHeight;
    }

    // Atualiza badge de navegação
    const navBadge = document.getElementById("nav-inbox-badge");
    if (navBadge) {
      navBadge.innerText = data.remaining;
      navBadge.style.display = data.remaining > 0 ? "flex" : "none";
    }

  } catch (e) {}
}

async function loadInbox() {
  const container = document.getElementById("inbox-cards-list");
  if (!container) return;
  container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 1.5rem;">Carregando notas pendentes...</div>`;

  try {
    const res = await fetch(BASE_PATH + "api/inbox");
    const notes = await res.json();

    const badge = document.getElementById("inbox-count-badge");
    if (badge) badge.innerText = notes.length;

    if (!notes || notes.length === 0) {
      container.innerHTML = `<div style="text-align: center; color: var(--success); padding: 2rem;">🎉 Nenhuma nota pendente na Inbox!</div>`;
      return;
    }

    container.innerHTML = "";
    notes.forEach(n => {
      const card = document.createElement("div");
      card.className = "inbox-item-card";

      const tagsHtml = (n.tags || []).slice(0, 3).map(t => `<span class="tag-pill" style="padding: 2px 8px; font-size: 0.7rem;">#${escapeHtml(t)}</span>`).join(" ");

      card.innerHTML = `
        <div class="inbox-item-header">
          <div class="inbox-item-title">${escapeHtml(n.title)}</div>
          <span class="status-badge" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24; border-color: rgba(245, 158, 11, 0.3);">
            ${escapeHtml(n.status)}
          </span>
        </div>
        <div class="inbox-item-preview">${escapeHtml(n.preview)}</div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px;">
          <div style="display: flex; gap: 4px; flex-wrap: wrap;">${tagsHtml}</div>
          <span style="font-family: var(--font-mono); font-size: 0.72rem; color: var(--text-muted);">${n.mtime.split(" ")[0]}</span>
        </div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    container.innerHTML = `<div style="color: var(--danger); text-align: center;">Falha ao carregar inbox.</div>`;
  }
}

// -----------------------------------------------------------------------------
// METRICAS & PROJETOS
// -----------------------------------------------------------------------------
async function initStats() {
  try {
    const res = await fetch(BASE_PATH + "api/stats");
    const stats = await res.json();
    document.getElementById("stat-total-notes").innerText = stats.total_notes;
    document.getElementById("stat-inbox-pending").innerText = stats.inbox_pending;
    document.getElementById("stat-assets-count").innerText = stats.assets_count;

    const navBadge = document.getElementById("nav-inbox-badge");
    if (navBadge) {
      navBadge.innerText = stats.inbox_pending;
      navBadge.style.display = stats.inbox_pending > 0 ? "flex" : "none";
    }
  } catch (e) {}
}

async function initProjects() {
  try {
    const res = await fetch(BASE_PATH + "api/projects");
    const projects = await res.json();
    const select = document.getElementById("project-select");
    if (!select) return;

    select.innerHTML = '<option value="">Sem projeto específico (Geral)</option>';
    projects.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.wikilink;
      opt.innerText = p.name;
      select.appendChild(opt);
    });
  } catch (e) {}
}

function showToast(msg) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.innerText = msg;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 3200);
}

function escapeHtml(text) {
  if (!text) return "";
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
