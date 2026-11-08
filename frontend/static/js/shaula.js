/**
 * Shaula Command Dashboard — Client Controller
 * Obsidian-Style UX, Live Wikilinks, Vault Management, Telemetry & Scheduler
 */

const state = {
  activeView: 'vault', // 'vault' | 'verification' | 'scheduler' | 'integrity' | 'settings'
  authToken: sessionStorage.getItem('shaula_auth_token') || null,
  currentNote: null,
  activeMode: 'split', // 'split' | 'edit' | 'preview'
  isDirty: false,
  treeData: null,
  expandedFolders: new Set(['00 - Inbox', '01 - Verification', '02 - Tasks & Schedules', '03 - Knowledge', '04 - System']),
  telemetryTimer: null,
  saveDebounce: null
};

// --- INICIALIZAÇÃO ---
document.addEventListener('DOMContentLoaded', () => {
  // Em telas pequenas (smartphones), padrão para modo preview em vez de split
  if (window.innerWidth <= 768) {
    state.activeMode = 'preview';
  }

  initActivityBar();
  initViewToggles();
  initShortcuts();
  initResponsiveListeners();

  loadVaultTree().then(() => {
    // Abrir nota principal Shaula Home se existir
    openNote('Shaula Home.md');
  });
  startTelemetryPolling();
  updateTopStats();
});

// --- CONTROLE RESPONSIVO & MOBILE ---
function initResponsiveListeners() {
  window.addEventListener('resize', () => {
    if (window.innerWidth <= 768) {
      if (state.activeMode === 'split') {
        setEditorMode('preview');
      }
    } else {
      // Se retornar para desktop, fecha drawer e backdrop
      toggleMobileSidebar(false);
    }
  });
}

function toggleMobileSidebar(force) {
  const panel = document.getElementById('sidePanel');
  const backdrop = document.getElementById('sidebarBackdrop');
  if (!panel) return;

  const isOpen = panel.classList.contains('mobile-open');
  const shouldOpen = typeof force === 'boolean' ? force : !isOpen;

  if (shouldOpen) {
    panel.classList.add('mobile-open');
    if (backdrop) backdrop.classList.add('active');
  } else {
    panel.classList.remove('mobile-open');
    if (backdrop) backdrop.classList.remove('active');
  }
}

// --- ATALHOS DE TECLADO ---
function initShortcuts() {
  document.addEventListener('keydown', (e) => {
    // Ctrl+S / Cmd+S: Salvar Nota
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      saveCurrentNote();
    }
    // Ctrl+O / Cmd+O ou Ctrl+P: Busca Rápida (Quick Switcher)
    if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'o' || e.key.toLowerCase() === 'p')) {
      e.preventDefault();
      openSearchModal();
    }
  });

  const rawEditor = document.getElementById('rawEditor');
  if (rawEditor) {
    rawEditor.addEventListener('input', () => {
      state.isDirty = true;
      updateSaveStatusBadge();
      updateStats();
      renderMarkdownLive();
    });
  }
}

// --- ACTIVITY BAR ---
function initActivityBar() {
  document.querySelectorAll('.activity-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetView = btn.dataset.view;
      if (!targetView) return;

      // Se clicar no Vault enquanto já está no Vault em smartphone, alterna gaveta
      if (targetView === 'vault' && state.activeView === 'vault' && window.innerWidth <= 768) {
        toggleMobileSidebar();
        return;
      }

      switchView(targetView);
      if (window.innerWidth <= 768) {
        toggleMobileSidebar(false);
      }
    });
  });
}

function switchView(viewName) {
  state.activeView = viewName;
  document.querySelectorAll('.activity-btn').forEach(b => b.classList.remove('active'));
  const activeBtn = document.querySelector(`.activity-btn[data-view="${viewName}"]`);
  if (activeBtn) activeBtn.classList.add('active');

  const editorWs = document.getElementById('editorWorkspace');
  const customView = document.getElementById('customViewContainer');
  const sidePanel = document.getElementById('sidePanel');

  if (viewName === 'vault') {
    sidePanel.style.display = '';
    editorWs.style.display = 'flex';
    customView.style.display = 'none';
  } else {
    toggleMobileSidebar(false);
    sidePanel.style.display = 'none';
    editorWs.style.display = 'none';
    customView.style.display = 'block';

    if (viewName === 'images') {
      renderImagesView();
    } else if (viewName === 'hermes') {
      renderHermesView();
    } else if (viewName === 'verification') {
      renderVerificationView();
    } else if (viewName === 'scheduler') {
      renderSchedulerView();
    } else if (viewName === 'integrity') {
      renderIntegrityView();
    } else if (viewName === 'settings') {
      renderSettingsView();
    }
  }
}

// --- VIEW TOGGLES (EDIT / SPLIT / PREVIEW) ---
function initViewToggles() {
  document.querySelectorAll('.toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.mode;
      setEditorMode(mode);
    });
  });
}

function setEditorMode(mode) {
  // Em smartphones, modo split não é suportado por falta de largura horizontal
  if (window.innerWidth <= 768 && mode === 'split') {
    mode = 'preview';
  }

  state.activeMode = mode;
  document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
  const activeBtn = document.querySelector(`.toggle-btn[data-mode="${mode}"]`);
  if (activeBtn) activeBtn.classList.add('active');

  const editorPane = document.getElementById('editorPane');
  const previewPane = document.getElementById('previewPane');

  if (mode === 'edit') {
    editorPane.style.display = 'flex';
    previewPane.style.display = 'none';
  } else if (mode === 'preview') {
    editorPane.style.display = 'none';
    previewPane.style.display = 'block';
  } else {
    // split
    editorPane.style.display = 'flex';
    previewPane.style.display = 'block';
  }
}

// --- VAULT TREE & ARQUIVOS ---
async function loadVaultTree() {
  try {
    const res = await fetch('/api/vault/tree');
    if (!res.ok) throw new Error('Falha ao carregar árvore do vault');
    state.treeData = await res.json();
    renderVaultTree(state.treeData);
  } catch (err) {
    showToast(`Erro na árvore: ${err.message}`, 'error');
  }
}

function renderVaultTree(tree) {
  const container = document.getElementById('vaultTree');
  if (!container) return;
  container.innerHTML = '';

  function createNode(item) {
    if (item.type === 'directory') {
      const folderDiv = document.createElement('div');
      folderDiv.className = 'tree-folder';

      const folderHeader = document.createElement('div');
      folderHeader.className = 'tree-item tree-folder-title';
      const isExpanded = state.expandedFolders.has(item.name);
      folderHeader.innerHTML = `<span>${isExpanded ? '▾ 📂' : '▸ 📁'}</span> <span>${item.name}</span>`;

      const childrenContainer = document.createElement('div');
      childrenContainer.className = 'tree-folder-children';
      childrenContainer.style.display = isExpanded ? 'block' : 'none';

      folderHeader.addEventListener('click', () => {
        if (state.expandedFolders.has(item.name)) {
          state.expandedFolders.delete(item.name);
          childrenContainer.style.display = 'none';
          folderHeader.innerHTML = `<span>▸ 📁</span> <span>${item.name}</span>`;
        } else {
          state.expandedFolders.add(item.name);
          childrenContainer.style.display = 'block';
          folderHeader.innerHTML = `<span>▾ 📂</span> <span>${item.name}</span>`;
        }
      });

      if (item.children) {
        item.children.forEach(child => {
          childrenContainer.appendChild(createNode(child));
        });
      }

      folderDiv.appendChild(folderHeader);
      folderDiv.appendChild(childrenContainer);
      return folderDiv;
    } else {
      const fileDiv = document.createElement('div');
      fileDiv.className = `tree-item ${state.currentNote && state.currentNote.path === item.path ? 'active' : ''}`;
      fileDiv.innerHTML = `<span>📄</span> <span title="${item.path}">${item.name}</span>`;
      fileDiv.addEventListener('click', () => {
        openNote(item.path);
      });
      return fileDiv;
    }
  }

  if (tree && tree.children) {
    tree.children.forEach(child => {
      container.appendChild(createNode(child));
    });
  }
}

// --- NOTAS: LEITURA, SALVAMENTO, CRIAÇÃO ---
async function openNote(notePath) {
  try {
    const res = await fetch(`/api/vault/note?path=${encodeURIComponent(notePath)}`);
    if (!res.ok) {
      if (res.status === 404) {
        // Perguntar se deseja criar nota caso seja um wikilink novo
        if (confirm(`A nota "${notePath}" não existe. Deseja criá-la agora no Vault exclusivo?`)) {
          await createNewNoteDirect(notePath);
          return;
        }
      }
      throw new Error('Nota não encontrada');
    }
    const data = await res.json();
    state.currentNote = data;
    state.isDirty = false;

    // Atualizar UI
    document.getElementById('currentNoteTitle').textContent = data.title || data.filename;
    document.getElementById('currentNotePath').textContent = data.path;
    document.getElementById('rawEditor').value = data.content;

    updateSaveStatusBadge();
    updateStats();
    renderMarkdownLive();
    renderVaultTree(state.treeData);

    // Se estiver em outra view, voltar para o vault
    if (state.activeView !== 'vault') {
      switchView('vault');
    }

    // Fechar drawer lateral e adaptar modo de visualização em smartphones
    if (window.innerWidth <= 768) {
      toggleMobileSidebar(false);
      if (state.activeMode === 'split') {
        setEditorMode('preview');
      }
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function saveCurrentNote() {
  if (!state.currentNote) return;
  const rawContent = document.getElementById('rawEditor').value;

  try {
    const res = await fetch('/api/vault/note', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: state.currentNote.path,
        content: rawContent
      })
    });
    if (!res.ok) throw new Error('Erro ao salvar no servidor');
    const updated = await res.json();
    state.currentNote = updated;
    state.isDirty = false;
    updateSaveStatusBadge();
    showToast(`Nota salva: ${updated.filename}`, 'success');
    loadVaultTree();
  } catch (err) {
    showToast(`Falha ao salvar: ${err.message}`, 'error');
  }
}

async function createNewNoteDirect(notePath) {
  try {
    const res = await fetch('/api/vault/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: notePath })
    });
    if (!res.ok) throw new Error('Erro ao criar nota');
    await loadVaultTree();
    await openNote(notePath);
    showToast(`Nota criada com sucesso!`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function promptNewNote() {
  const name = prompt('Nome da nova nota (ex: Minha Nota ou 00 - Inbox/Ideia):');
  if (!name || !name.trim()) return;
  let cleanName = name.trim();
  if (!cleanName.endsWith('.md')) cleanName += '.md';
  createNewNoteDirect(cleanName);
}

function promptNewFolder() {
  const name = prompt('Nome da nova pasta:');
  if (!name || !name.trim()) return;
  fetch('/api/vault/folder', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: name.trim() })
  })
  .then(res => res.json())
  .then(() => {
    loadVaultTree();
    showToast('Pasta criada com sucesso!', 'success');
  })
  .catch(err => showToast(`Erro ao criar pasta: ${err.message}`, 'error'));
}

async function deleteCurrentNote() {
  if (!state.currentNote) return;
  if (!confirm(`Tem certeza que deseja excluir "${state.currentNote.path}"?`)) return;

  try {
    const res = await fetch(`/api/vault/note?path=${encodeURIComponent(state.currentNote.path)}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error('Falha ao excluir');
    showToast('Nota excluída.', 'success');
    state.currentNote = null;
    await loadVaultTree();
    openNote('Shaula Home.md');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// --- RENDERIZADOR MARKDOWN & WIKILINKS OBSIDIAN ---
function renderMarkdownLive() {
  const preview = document.getElementById('markdownPreview');
  const editor = document.getElementById('rawEditor');
  if (!preview || !editor) return;

  const raw = editor.value;

  // 1. Extrair Frontmatter YAML
  let body = raw;
  let frontmatterHtml = '';
  const frontmatch = raw.match(/^---\s*\n(.*?)\n---\s*\n(.*)$/s);
  if (frontmatch) {
    const yamlBlock = frontmatch[1];
    body = frontmatch[2];

    const tagsMatch = yamlBlock.match(/tags:\s*\n((?:\s*-\s*[^\n]+\n)+)/);
    let tagPills = '';
    if (tagsMatch) {
      const tags = tagsMatch[1].split('\n')
        .map(t => t.replace(/^\s*-\s*/, '').trim())
        .filter(t => t.length > 0);
      tagPills = tags.map(t => `<span class="tag-pill">#${t}</span>`).join(' ');
    }

    frontmatterHtml = `
      <div class="frontmatter-card">
        <div class="frontmatter-title">YAML METADATA</div>
        ${tagPills ? `<div>${tagPills}</div>` : ''}
        <pre style="margin-top:6px; font-size:11px; color:#94a3b8; background:transparent; border:none; padding:0;">${escapeHtml(yamlBlock.trim())}</pre>
      </div>
    `;
  }

  // 2. Processar Imagens Wikilinks do Obsidian ![[assets/imagem.jpg]] ou ![[imagem.jpg]]
  let processed = body.replace(/!\[\[(.*?)\]\]/g, (match, p1) => {
    const parts = p1.split('|');
    let target = parts[0].trim();
    if (!target.startsWith('assets/') && !target.startsWith('/assets/')) {
      target = 'assets/' + target;
    }
    const cleanPath = target.startsWith('/') ? target : '/' + target;
    return `<div style="margin:14px 0;"><img src="${escapeHtml(cleanPath)}" style="max-width:100%; border-radius:6px; border:1px solid var(--border-color);" alt="${escapeHtml(parts[0])}"></div>`;
  });

  // 3. Processar Wikilinks [[Nota]] ou [[Nota|Texto]]
  processed = processed.replace(/\[\[(.*?)\]\]/g, (match, p1) => {
    const parts = p1.split('|');
    const target = parts[0].trim();
    const alias = parts.length > 1 ? parts[1].trim() : target;
    return `<a href="javascript:void(0)" class="wikilink" data-target="${escapeHtml(target)}">${escapeHtml(alias)}</a>`;
  });

  // 3. Processar Checklists do Obsidian
  processed = processed.replace(/^\s*-\s*\[ \]\s+(.*)$/gm, '<li style="list-style:none;">⬜ $1</li>');
  processed = processed.replace(/^\s*-\s*\[x\]\s+(.*)$/gmi, '<li style="list-style:none; color:#94a3b8; text-decoration:line-through;">☑️ $1</li>');

  // 4. Renderizar com Marked
  let parsedHtml = '';
  if (typeof marked !== 'undefined') {
    parsedHtml = marked.parse(processed);
  } else {
    parsedHtml = `<pre>${escapeHtml(processed)}</pre>`;
  }

  preview.innerHTML = frontmatterHtml + parsedHtml;

  // Ativar cliques nos wikilinks
  preview.querySelectorAll('.wikilink').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const target = link.dataset.target;
      if (target) {
        openNote(target);
      }
    });
  });
}

function updateSaveStatusBadge() {
  const badge = document.getElementById('saveStatusBadge');
  if (!badge) return;
  if (state.isDirty) {
    badge.textContent = '● Modificado (Ctrl+S para salvar)';
    badge.style.color = 'var(--accent-gold)';
  } else {
    badge.textContent = '✓ Sincronizado';
    badge.style.color = 'var(--status-green)';
  }
}

function updateStats() {
  const editor = document.getElementById('rawEditor');
  if (!editor) return;
  const text = editor.value;
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const chars = text.length;

  document.getElementById('statWords').textContent = `${words} palavras`;
  document.getElementById('statChars').textContent = `${chars} caracteres`;
}

// --- TELEMETRIA EM TEMPO REAL ---
function startTelemetryPolling() {
  pollTelemetry();
  state.telemetryTimer = setInterval(pollTelemetry, 6000);
}

async function pollTelemetry() {
  try {
    const res = await fetch('/api/verification/telemetry');
    if (!res.ok) return;
    const data = await res.json();
    updateTelemetryUI(data);
  } catch (e) {
    // Silencioso em caso de erro temporário
  }
}

function updateTelemetryUI(data) {
  const hw = data.hardware;
  const s = data.services;

  // Header status pill
  const hostStatus = document.getElementById('hostStatusPill');
  if (hostStatus) {
    const isHermesRunning = s.hermes && s.hermes.active;
    hostStatus.innerHTML = `
      <span class="dot ${isHermesRunning ? 'dot-green' : 'dot-yellow'}"></span>
      <span>Hermes: ${isHermesRunning ? 'Online' : 'Parado'} | Uptime: ${hw.uptime}</span>
    `;
  }

  // Se a view de verificação estiver aberta, atualizar os gauges
  if (state.activeView === 'verification') {
    renderTelemetryGauges(hw, s);
  }
}

async function updateTopStats() {
  try {
    const res = await fetch('/api/vault/integrity');
    if (!res.ok) return;
    const data = await res.json();
    const el = document.getElementById('vaultNotesCount');
    if (el) el.textContent = `${data.total_notes} notas no vault`;
  } catch (e) {}
}

// --- VIEW: VERIFICAÇÃO (🩺) ---
async function renderVerificationView() {
  const container = document.getElementById('customViewContainer');
  container.innerHTML = `
    <div class="full-panel-view">
      <div class="view-header-row" style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 24px;">
        <div>
          <h2 style="color:#f8fafc; font-size:22px; display:flex; align-items:center; gap:8px;">
            <span>🩺</span> Centro de Verificação Determinística
          </h2>
          <p style="color:#94a3b8; font-size:13px; margin-top:4px;">
            Diagnóstico de hardware, integridade dos serviços e relatórios de auditoria auditáveis.
          </p>
        </div>
        <button class="btn-primary" id="btnRunVerification" onclick="triggerFullVerification()">
          <span>⚡</span> Executar Verificação Completa
        </button>
      </div>

      <div class="panel-grid" id="telemetryGrid">
        <div class="stat-card">Carregando telemetria...</div>
      </div>

      <div style="margin-top:28px;">
        <h3 style="color:#f1f5f9; font-size:16px; margin-bottom:12px;">🛰️ Serviços Supervisionados</h3>
        <div class="panel-grid" id="servicesGrid"></div>
      </div>

      <div style="margin-top:28px;" id="verificationResultBox"></div>
    </div>
  `;

  // Carregar dados imediatos
  const res = await fetch('/api/verification/telemetry');
  if (res.ok) {
    const data = await res.json();
    renderTelemetryGauges(data.hardware, data.services);
  }
}

function renderTelemetryGauges(hw, s) {
  const grid = document.getElementById('telemetryGrid');
  if (!grid) return;

  grid.innerHTML = `
    <div class="stat-card">
      <div class="stat-label">Processador (CPU)</div>
      <div class="stat-value">${hw.cpu.percent}%</div>
      <div class="progress-bar">
        <div class="progress-fill" style="width: ${hw.cpu.percent}%; background: ${hw.cpu.percent > 85 ? 'var(--status-red)' : 'var(--accent-purple)'};"></div>
      </div>
      <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">
        ${hw.cpu.cores} núcleos | Load: ${hw.cpu.load_avg.join(', ')}
      </div>
    </div>

    <div class="stat-card">
      <div class="stat-label">Memória RAM</div>
      <div class="stat-value">${hw.memory.percent}%</div>
      <div class="progress-bar">
        <div class="progress-fill" style="width: ${hw.memory.percent}%; background: ${hw.memory.percent > 90 ? 'var(--status-red)' : 'var(--accent-gold)'};"></div>
      </div>
      <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">
        ${hw.memory.used_gb} GB usados de ${hw.memory.total_gb} GB (Livre: ${hw.memory.available_gb} GB)
      </div>
    </div>

    <div class="stat-card">
      <div class="stat-label">Armazenamento (Root /)</div>
      <div class="stat-value">${hw.disk.root_percent}%</div>
      <div class="progress-bar">
        <div class="progress-fill" style="width: ${hw.disk.root_percent}%; background: ${hw.disk.root_percent > 90 ? 'var(--status-red)' : 'var(--status-green)'};"></div>
      </div>
      <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">
        ${hw.disk.root_used_gb} GB / ${hw.disk.root_total_gb} GB
      </div>
    </div>

    <div class="stat-card">
      <div class="stat-label">Uptime do Host</div>
      <div class="stat-value" style="font-size:20px; font-weight:600; color:var(--accent-text, #c4b5fd);">${hw.uptime}</div>
      <div style="font-size:11px; color:var(--text-muted); margin-top:8px;">
        Ambiente estável e operacional
      </div>
    </div>
  `;

  const sGrid = document.getElementById('servicesGrid');
  if (!sGrid) return;

  sGrid.innerHTML = `
    <div class="stat-card">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-weight:600;">Hermes Gateway</span>
        <span class="pill-badge" style="background:${s.hermes.active ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)'}; color:${s.hermes.active ? 'var(--status-green)' : 'var(--status-red)'}">
          ${s.hermes.status_label}
        </span>
      </div>
      <div style="font-size:12px; color:var(--text-secondary); margin-top:6px;">
        ${s.hermes.instances} processo(s) ativo(s)
      </div>
    </div>

    <div class="stat-card">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-weight:600;">Docker / Containers</span>
        <span class="pill-badge" style="background:rgba(59, 130, 246, 0.15); color:var(--status-blue);">
          ${s.docker.status_label}
        </span>
      </div>
      <div style="font-size:12px; color:var(--text-secondary); margin-top:6px;">
        ${s.docker.containers_count} container(s) em execução
      </div>
    </div>

    <div class="stat-card">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-weight:600;">Ollama Engine</span>
        <span class="pill-badge" style="background:${s.ollama.active ? 'rgba(16, 185, 129, 0.15)' : 'rgba(100, 116, 139, 0.15)'}; color:${s.ollama.active ? 'var(--status-green)' : 'var(--text-muted)'}">
          ${s.ollama.status_label}
        </span>
      </div>
      <div style="font-size:12px; color:var(--text-secondary); margin-top:6px;">
        Porta TCP 11434
      </div>
    </div>

    <div class="stat-card">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-weight:600;">Shaula Dashboard</span>
        <span class="pill-badge" style="background:rgba(124, 58, 237, 0.15); color:var(--text-accent);">
          ONLINE :5000
        </span>
      </div>
      <div style="font-size:12px; color:var(--text-secondary); margin-top:6px;">
        Vault Exclusivo Conectado
      </div>
    </div>
  `;
}

async function triggerFullVerification() {
  const btn = document.getElementById('btnRunVerification');
  const box = document.getElementById('verificationResultBox');
  if (btn) btn.disabled = true;
  box.innerHTML = `<div class="stat-card" style="border-left:4px solid var(--accent-purple);">Executando verificação determinística e registrando em logs...</div>`;

  try {
    const res = await fetch('/api/verification/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ save_note: false, save_log: true })
    });
    if (!res.ok) throw new Error('Falha na requisição');
    const data = await res.json();

    const logLink = (data.saved_log_path || data.saved_note_path) ? `
      <div style="margin-top:10px; font-size:12px; color:var(--text-muted);">
        📋 Registro arquivado na pasta de logs: <code style="color:var(--text-accent);">${data.saved_log_path || data.saved_note_path}</code>
      </div>
    ` : '';

    box.innerHTML = `
      <div class="stat-card" style="border-left: 4px solid ${data.overall_status === 'OPTIMAL' ? 'var(--status-green)' : 'var(--status-yellow)'};">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <h4 style="font-size:15px; color:#fff;">Status Geral: ${data.overall_status}</h4>
          <span style="font-size:11px; color:var(--text-muted);">${data.timestamp}</span>
        </div>
        <div style="margin-top:8px; font-size:13px; color:var(--text-secondary);">
          ${data.alerts.length > 0 ? data.alerts.map(a => `<div>⚠️ ${a}</div>`).join('') : '<div>✅ Todos os parâmetros de telemetria e integridade estão conformes.</div>'}
        </div>
        ${logLink}
      </div>
    `;
    showToast('Verificação concluída e registrada nos logs!', 'success');
    loadVaultTree();
  } catch (err) {
    box.innerHTML = `<div class="stat-card" style="border-left:4px solid var(--status-red); color:var(--status-red);">Erro: ${err.message}</div>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

// --- VIEW: AGENDAMENTO / SCHEDULER (⏱️) ---
async function renderSchedulerView() {
  const container = document.getElementById('customViewContainer');
  container.innerHTML = `
    <div class="full-panel-view">
      <div class="view-header-row" style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 24px;">
        <div>
          <h2 style="color:#f8fafc; font-size:22px; display:flex; align-items:center; gap:8px;">
            <span>⏱️</span> Motor de Agendamento (Scheduler)
          </h2>
          <p style="color:#94a3b8; font-size:13px; margin-top:4px;">
            Rotinas automáticas recorrentes para diagnósticos, integridade e backups periódicos do Vault.
          </p>
        </div>
        <button class="btn-primary" onclick="openNewJobModal()">
          <span>➕</span> Novo Agendamento
        </button>
      </div>

      <div class="stat-card table-responsive" style="margin-bottom:24px; padding:0; overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse; font-size:13px;" id="jobsTable">
          <thead>
            <tr style="background:var(--bg-card); color:var(--text-muted); text-align:left; border-bottom:1px solid var(--border-color);">
              <th style="padding:12px 16px;">Rotina / Tarefa</th>
              <th style="padding:12px 16px;">Intervalo</th>
              <th style="padding:12px 16px;">Próxima Execução</th>
              <th style="padding:12px 16px;">Último Resultado</th>
              <th style="padding:12px 16px; text-align:right;">Ações</th>
            </tr>
          </thead>
          <tbody id="jobsTableBody">
            <tr><td colspan="5" style="padding:20px; text-align:center; color:var(--text-muted);">Carregando agendamentos...</td></tr>
          </tbody>
        </table>
      </div>

      <h3 style="color:#f1f5f9; font-size:16px; margin-bottom:12px;">📜 Histórico de Execuções Recentes</h3>
      <div id="schedulerHistoryList">Carregando histórico...</div>
    </div>
  `;

  loadSchedulerJobs();
  loadSchedulerHistory();
}

async function loadSchedulerJobs() {
  try {
    const res = await fetch('/api/scheduler/jobs');
    if (!res.ok) throw new Error('Falha ao carregar jobs');
    const jobs = await res.json();
    const tbody = document.getElementById('jobsTableBody');
    if (!tbody) return;

    if (jobs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="padding:20px; text-align:center;">Nenhum agendamento configurado.</td></tr>`;
      return;
    }

    tbody.innerHTML = jobs.map(j => {
      const isEnabled = j.enabled;
      const lastRes = j.last_result ? (j.last_result.success ? `<span style="color:var(--status-green);">✓ ${j.last_result.message}</span>` : `<span style="color:var(--status-red);">✗ ${j.last_result.message}</span>`) : '<span style="color:var(--text-muted);">-</span>';

      return `
        <tr style="border-bottom:1px solid #242428;">
          <td style="padding:12px 16px;">
            <div style="font-weight:600; color:#fff;">${j.name}</div>
            <div style="font-size:11px; color:var(--text-muted);">Ação: <code>${j.action}</code> ${j.save_note ? '(Gera Nota no Vault)' : ''}</div>
          </td>
          <td style="padding:12px 16px; color:var(--text-secondary);">${j.interval_minutes} min</td>
          <td style="padding:12px 16px; color:var(--accent-text, #a78bfa);">${j.next_run_human}</td>
          <td style="padding:12px 16px; font-size:12px;">${lastRes}</td>
          <td style="padding:12px 16px; text-align:right;">
            <button class="btn-secondary" style="display:inline-flex; padding:4px 8px; font-size:11px; margin-right:4px;" onclick="triggerJobNow('${j.id}')">⚡ Executar</button>
            <button class="btn-secondary" style="display:inline-flex; padding:4px 8px; font-size:11px; margin-right:4px;" onclick="toggleJob('${j.id}', ${!isEnabled})">${isEnabled ? 'Pausar' : 'Ativar'}</button>
            <button class="btn-secondary" style="display:inline-flex; padding:4px 8px; font-size:11px; color:var(--status-red);" onclick="deleteJob('${j.id}')">Excluir</button>
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function loadSchedulerHistory() {
  try {
    const res = await fetch('/api/scheduler/history');
    if (!res.ok) return;
    const history = await res.json();
    const list = document.getElementById('schedulerHistoryList');
    if (!list) return;

    if (history.length === 0) {
      list.innerHTML = `<div class="stat-card" style="color:var(--text-muted);">Nenhum histórico de execução registrado ainda.</div>`;
      return;
    }

    list.innerHTML = history.slice(0, 15).map(h => `
      <div class="stat-card" style="margin-bottom:8px; padding:10px 14px; display:flex; justify-content:space-between; align-items:center;">
        <div>
          <span style="font-weight:600; color:#fff; font-size:13px;">${h.job_name}</span>
          <span style="font-size:11px; color:var(--text-muted); margin-left:8px;">${h.timestamp} (${h.duration_sec}s)</span>
          <div style="font-size:12px; color:var(--text-secondary); margin-top:2px;">${h.message}</div>
        </div>
        <span class="pill-badge" style="background:${h.success ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)'}; color:${h.success ? 'var(--status-green)' : 'var(--status-red)'}; font-size:11px;">
          ${h.success ? 'SUCESSO' : 'ERRO'}
        </span>
      </div>
    `).join('');
  } catch (e) {}
}

async function triggerJobNow(jobId) {
  try {
    const res = await fetch(`/api/scheduler/jobs/${jobId}/run`, { method: 'POST' });
    if (!res.ok) throw new Error('Falha ao disparar');
    showToast('Execução iniciada em background!', 'success');
    setTimeout(() => {
      loadSchedulerJobs();
      loadSchedulerHistory();
    }, 1500);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function toggleJob(jobId, newState) {
  try {
    const res = await fetch(`/api/scheduler/jobs/${jobId}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: newState })
    });
    if (!res.ok) throw new Error('Falha ao alterar estado');
    loadSchedulerJobs();
    showToast(`Rotina ${newState ? 'ativada' : 'pausada'}.`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function deleteJob(jobId) {
  if (!confirm('Deseja excluir este agendamento?')) return;
  try {
    const res = await fetch(`/api/scheduler/jobs/${jobId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Falha ao excluir');
    loadSchedulerJobs();
    showToast('Agendamento excluído.', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function openNewJobModal() {
  const modal = document.getElementById('jobModal');
  if (modal) modal.style.display = 'flex';
}

function closeNewJobModal() {
  const modal = document.getElementById('jobModal');
  if (modal) modal.style.display = 'none';
}

async function submitNewJob() {
  const name = document.getElementById('jobNameInput').value;
  const action = document.getElementById('jobActionSelect').value;
  const interval = parseInt(document.getElementById('jobIntervalInput').value, 10);
  const saveNote = document.getElementById('jobSaveNoteCheck').checked;

  if (!name || isNaN(interval) || interval < 1) {
    alert('Preencha um nome válido e intervalo de no mínimo 1 minuto.');
    return;
  }

  try {
    const res = await fetch('/api/scheduler/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        action,
        interval_minutes: interval,
        save_note: saveNote
      })
    });
    if (!res.ok) throw new Error('Erro ao criar agendamento');
    closeNewJobModal();
    loadSchedulerJobs();
    showToast('Agendamento cadastrado com sucesso!', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// --- VIEW: INTEGRIDADE DO VAULT (🛡️) ---
async function renderIntegrityView() {
  const container = document.getElementById('customViewContainer');
  container.innerHTML = `
    <div class="full-panel-view">
      <div class="view-header-row" style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 24px;">
        <div>
          <h2 style="color:#f8fafc; font-size:22px; display:flex; align-items:center; gap:8px;">
            <span>🛡️</span> Integridade do Vault Exclusivo Shaula
          </h2>
          <p style="color:#94a3b8; font-size:13px; margin-top:4px;">
            Varredura e validação de Wikilinks [[alvo]], notas órfãs e criação de snapshots de segurança.
          </p>
        </div>
        <div class="header-action-buttons" style="display:flex; gap:10px;">
          <button class="btn-secondary" onclick="createVaultBackup()">
            <span>📦</span> Criar Backup (.tar.gz)
          </button>
          <button class="btn-primary" onclick="renderIntegrityView()">
            <span>🔄</span> Re-verificar Vault
          </button>
        </div>
      </div>

      <div id="integrityContent">Carregando auditoria do vault...</div>
    </div>
  `;

  try {
    const res = await fetch('/api/vault/integrity');
    if (!res.ok) throw new Error('Falha ao auditar vault');
    const data = await res.json();

    const content = document.getElementById('integrityContent');
    if (!content) return;

    const brokenRows = (data.broken_links || []).map((b, idx) => `
      <div class="stat-card" style="padding:12px 14px; margin-bottom:10px; border-left:4px solid var(--status-red); background:rgba(239, 68, 68, 0.06);">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:10px;">
          <div>
            <div style="font-size:13.5px; font-weight:600; color:#fff; display:flex; align-items:center; gap:8px;">
              <span>⚠️ Link Quebrado:</span>
              <code style="color:var(--status-red); background:#18181c; border:1px solid rgba(239, 68, 68, 0.3); padding:2px 8px; border-radius:4px; font-size:13px;">${escapeHtml(b.line_hint || '[[' + b.target + ']]')}</code>
            </div>
            <div style="font-size:12px; color:var(--text-secondary); margin-top:4px;">
              Origem na nota: <a href="javascript:void(0)" class="wikilink" onclick="openNote('${escapeHtml(b.source)}')">📄 ${escapeHtml(b.source)}</a>
            </div>
          </div>
          
          <div style="display:flex; flex-wrap:wrap; gap:6px;">
            <button class="btn-primary" style="font-size:11px; padding:4px 10px;" onclick="resolveBrokenLinkPrompt('create_target', '${escapeHtml(b.source)}', '${escapeHtml(b.target)}')">
              <span>➕</span> Criar Nota Alvo
            </button>
            <button class="btn-secondary" style="font-size:11px; padding:4px 10px;" onclick="resolveBrokenLinkPrompt('rename_link', '${escapeHtml(b.source)}', '${escapeHtml(b.target)}')">
              <span>✏️</span> Corrigir Link
            </button>
            <button class="btn-secondary" style="font-size:11px; padding:4px 10px;" onclick="resolveBrokenLinkPrompt('unlink', '${escapeHtml(b.source)}', '${escapeHtml(b.target)}')">
              <span>✂️</span> Desvincular
            </button>
            <button class="btn-secondary" style="font-size:11px; padding:4px 8px; color:var(--status-red);" onclick="resolveBrokenLinkPrompt('delete_link', '${escapeHtml(b.source)}', '${escapeHtml(b.target)}')">
              <span>🗑️</span> Apagar
            </button>
            <button class="btn-secondary" style="font-size:11px; padding:4px 8px;" onclick="openNote('${escapeHtml(b.source)}')">
              <span>📄</span> Ver Nota
            </button>
          </div>
        </div>
      </div>
    `).join('') || '<div style="color:var(--status-green); padding:10px 0;">✓ Nenhum wikilink quebrado detectado! Conexões 100% íntegras.</div>';

    const orphanRows = data.orphan_notes.map(o => `
      <div style="padding:6px 12px; background:rgba(245, 158, 11, 0.1); border-left:3px solid var(--accent-gold); margin-bottom:6px; border-radius:4px; font-size:13px;">
        📄 <a href="javascript:void(0)" class="wikilink" onclick="openNote('${o}')">${o}</a> (sem links de entrada ou saída)
      </div>
    `).join('') || '<div style="color:var(--text-muted);">Nenhuma nota órfã encontrada.</div>';

    content.innerHTML = `
      <div class="panel-grid">
        <div class="stat-card">
          <div class="stat-label">Total de Notas</div>
          <div class="stat-value">${data.total_notes}</div>
          <div style="font-size:11px; color:var(--text-muted);">${data.total_words} palavras indexadas</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Tags Catalogadas</div>
          <div class="stat-value" style="color:var(--accent-gold);">${data.total_tags}</div>
          <div style="font-size:11px; color:var(--text-muted);">${data.tags_list.join(', ') || 'Nenhuma'}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Links Quebrados</div>
          <div class="stat-value" style="color:${data.broken_links_count > 0 ? 'var(--status-red)' : 'var(--status-green)'};">${data.broken_links_count}</div>
          <div style="font-size:11px; color:var(--text-muted);">Estado: ${data.status}</div>
        </div>
      </div>

      <div class="stat-card" style="margin-top:20px;">
        <h4 style="font-size:15px; color:#fff; margin-bottom:12px;">🔗 Auditoria de Wikilinks</h4>
        ${brokenRows}
      </div>

      <div class="stat-card" style="margin-top:20px;">
        <h4 style="font-size:15px; color:#fff; margin-bottom:12px;">🏝️ Notas Órfãs (Sem Conexões)</h4>
        ${orphanRows}
      </div>
    `;
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function createVaultBackup() {
  try {
    showToast('Gerando backup tar.gz do Vault...', 'success');
    const res = await fetch('/api/vault/backup', { method: 'POST' });
    if (!res.ok) throw new Error('Falha no backup');
    const data = await res.json();
    showToast(`Backup criado: ${data.filename} (${data.size_kb} KB)`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// --- RESOLUÇÃO INTERATIVA DE LINKS QUEBRADOS (SEGURANÇA E INTEGRIDADE) ---
async function resolveBrokenLinkPrompt(action, source, target) {
  let replacement = null;
  let targetFolder = '03 - Knowledge/Ativos';

  if (action === 'create_target') {
    const folderChoice = prompt(
      `Criar nota alvo para resolver "[[${target}]]"?\nInforme a pasta de destino:\n(Ex: 03 - Knowledge/Ativos, 03 - Knowledge/Procedimentos, 03 - Knowledge/Setores)`,
      '03 - Knowledge/Ativos'
    );
    if (folderChoice === null) return;
    targetFolder = folderChoice.trim() || '03 - Knowledge/Ativos';
  } else if (action === 'rename_link') {
    const newTarget = prompt(
      `Digite o novo alvo do link para substituir "[[${target}]]" em "${source}":`,
      target
    );
    if (!newTarget || !newTarget.trim()) return;
    replacement = newTarget.trim();
  } else if (action === 'unlink') {
    if (!confirm(`Deseja desvincular o link "[[${target}]]" em "${source}"?\nO texto será mantido como "${target}" simples (sem colchetes), removendo a pendência de link.`)) {
      return;
    }
  } else if (action === 'delete_link') {
    if (!confirm(`Deseja APAGAR completamente a referência a "[[${target}]]" da nota "${source}"?`)) {
      return;
    }
  }

  try {
    const res = await fetch('/api/vault/resolve-link', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: action,
        source: source,
        target: target,
        replacement: replacement,
        target_folder: targetFolder
      })
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Falha ao resolver pendência');
    }
    const data = await res.json();
    showToast(data.message, 'success');

    // Recarregar árvore do vault e tela de integridade
    await loadVaultTree();
    await renderIntegrityView();

    if (action === 'create_target' && data.note_path) {
      if (confirm(`Nota "${target}" criada com sucesso! Deseja abri-la agora no editor?`)) {
        await openNote(data.note_path);
      }
    }
  } catch (err) {
    showToast(`Erro ao resolver link: ${err.message}`, 'error');
  }
}

// --- BUSCA RÁPIDA / QUICK SWITCHER ---
function openSearchModal() {
  const modal = document.getElementById('searchModal');
  if (!modal) return;
  modal.style.display = 'flex';
  const input = document.getElementById('searchModalInput');
  input.value = '';
  input.focus();
  document.getElementById('searchResults').innerHTML = '';
}

function closeSearchModal() {
  const modal = document.getElementById('searchModal');
  if (modal) modal.style.display = 'none';
}

async function handleSearchInput(e) {
  const q = e.target.value.trim();
  const resultsContainer = document.getElementById('searchResults');
  if (q.length < 2) {
    resultsContainer.innerHTML = '';
    return;
  }

  try {
    const res = await fetch(`/api/vault/search?q=${encodeURIComponent(q)}`);
    if (!res.ok) return;
    const results = await res.json();

    if (results.length === 0) {
      resultsContainer.innerHTML = '<div style="padding:16px; color:var(--text-muted); font-size:13px; text-align:center;">Nenhum resultado encontrado.</div>';
      return;
    }

    resultsContainer.innerHTML = results.map(r => `
      <div class="tree-item" style="padding:10px 14px; border-bottom:1px solid #28282c; display:flex; flex-direction:column; align-items:flex-start;" onclick="selectSearchResult('${r.path}')">
        <div style="font-weight:600; color:#fff; font-size:13px;">${r.title} <span style="font-size:11px; color:var(--text-muted); font-weight:400;">(${r.path})</span></div>
        ${r.matches.map(m => `<div style="font-size:12px; color:var(--text-secondary); margin-top:2px;">Linha ${m.line}: <em>${escapeHtml(m.text)}</em></div>`).join('')}
      </div>
    `).join('');
  } catch (err) {}
}

function selectSearchResult(path) {
  closeSearchModal();
  openNote(path);
}

// --- UTILITÁRIOS ---
function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}


// --- VIEW: CONFIGURAÇÕES & VAULT AUXILIAR (SENHA: 3884) ---
function renderSettingsView() {
  if (!state.authToken) {
    renderSettingsLogin();
  } else {
    renderSettingsDashboard();
  }
}

function renderSettingsLogin() {
  const container = document.getElementById('customViewContainer');
  container.innerHTML = `
    <div class="full-panel-view" style="display:flex; align-items:center; justify-content:center; min-height:80vh;">
      <div class="stat-card" style="width:420px; max-width:90vw; padding:28px 24px; border:1px solid #3f3f46; box-shadow: 0 16px 32px rgba(0,0,0,0.5);">
        <div style="text-align:center; margin-bottom:20px;">
          <div style="font-size:36px; margin-bottom:8px;">🔒</div>
          <h3 style="color:#fff; font-size:18px; font-weight:600;">Área Restrita — Configurações</h3>
          <p style="color:var(--text-muted); font-size:12px; margin-top:4px;">
            Digite a senha de segurança para acessar os parâmetros do sistema e do Vault Auxiliar.
          </p>
        </div>

        <div style="margin-bottom:16px;">
          <label style="display:block; font-size:11px; text-transform:uppercase; color:var(--text-muted); margin-bottom:6px; font-weight:600;">
            Senha de Acesso
          </label>
          <input type="password" id="adminPasswordInput" placeholder="Digite a senha..." style="width:100%; padding:10px 14px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:6px; color:#fff; font-size:14px; outline:none; text-align:center; letter-spacing:2px;" onkeydown="if(event.key === 'Enter') handleSettingsLogin()">
        </div>

        <button class="btn-primary" style="width:100%; justify-content:center; padding:10px;" onclick="handleSettingsLogin()">
          <span>🔓</span> Desbloquear Configurações
        </button>

        <div style="margin-top:14px; text-align:center; font-size:11px; color:var(--text-muted);">
          Chave padrão: <code>3884</code>
        </div>
      </div>
    </div>
  `;
  setTimeout(() => {
    const inp = document.getElementById('adminPasswordInput');
    if (inp) inp.focus();
  }, 100);
}

async function handleSettingsLogin() {
  const inp = document.getElementById('adminPasswordInput');
  if (!inp) return;
  const password = inp.value.trim();

  try {
    const res = await fetch('/api/settings/auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password })
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Senha incorreta');
    }
    const data = await res.json();
    state.authToken = data.token;
    sessionStorage.setItem('shaula_auth_token', data.token);
    showToast('Acesso concedido com sucesso!', 'success');
    renderSettingsDashboard();
  } catch (err) {
    showToast(err.message, 'error');
    inp.value = '';
    inp.focus();
  }
}

function handleSettingsLogout() {
  state.authToken = null;
  sessionStorage.removeItem('shaula_auth_token');
  showToast('Sessão encerrada.', 'info');
  renderSettingsLogin();
}

async function renderSettingsDashboard() {
  const container = document.getElementById('customViewContainer');
  container.innerHTML = `<div class="full-panel-view" style="padding:32px;">Carregando configurações seguras...</div>`;

  try {
    const res = await fetch('/api/settings', {
      headers: { 'X-Shaula-Auth': state.authToken }
    });
    if (res.status === 401) {
      handleSettingsLogout();
      return;
    }
    const data = await res.json();
    const stats = data.aux_vault_stats;

    container.innerHTML = `
      <div class="full-panel-view">
        <div class="view-header-row" style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 24px;">
          <div>
            <h2 style="color:#f8fafc; font-size:22px; display:flex; align-items:center; gap:8px;">
              <span>⚙️</span> Configurações & Interoperabilidade de Vaults
            </h2>
            <p style="color:#94a3b8; font-size:13px; margin-top:4px;">
              Controle de Vault Auxiliar, sincronização bidirecional e ajustes de portabilidade Docker.
            </p>
          </div>
          <button class="btn-secondary" onclick="handleSettingsLogout()">
            <span>🔒</span> Bloquear Painel
          </button>
        </div>

        <!-- Seção 1: Configuração do Vault Auxiliar -->
        <div class="stat-card" style="margin-bottom:24px; padding:20px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
            <div>
              <h3 style="color:#fff; font-size:16px; display:flex; align-items:center; gap:8px;">
                <span>📂</span> Vault Auxiliar
              </h3>
              <p style="color:var(--text-muted); font-size:12px; margin-top:2px;">
                Permite conectar notas externas (outro vault, Obsidian secundário ou volume Docker) ao Vault exclusivo Shaula.
              </p>
            </div>
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:12px; color:var(--text-secondary);">Habilitar Vault Auxiliar:</span>
              <input type="checkbox" id="auxEnabledCheck" ${data.aux_vault_enabled ? 'checked' : ''} style="transform:scale(1.2);">
            </div>
          </div>

          <div style="display:grid; grid-template-columns: 2fr 1fr; gap:16px; margin-bottom:16px;">
            <div>
              <label style="display:block; font-size:11px; text-transform:uppercase; color:var(--text-muted); margin-bottom:4px; font-weight:600;">
                Caminho do Vault Auxiliar (Host ou Container)
              </label>
              <input type="text" id="auxPathInput" value="${escapeHtml(data.aux_vault_path)}" placeholder="/app/aux_vault ou /home/kodansha/aux_vault" style="width:100%; padding:8px 12px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:6px; color:#fff; font-size:13px; outline:none;">
            </div>

            <div>
              <label style="display:block; font-size:11px; text-transform:uppercase; color:var(--text-muted); margin-bottom:4px; font-weight:600;">
                Modo de Sincronização
              </label>
              <select id="auxSyncModeSelect" style="width:100%; padding:8px 12px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:6px; color:#fff; font-size:13px; outline:none;">
                <option value="import_only" ${data.aux_sync_mode === 'import_only' ? 'selected' : ''}>Importação (Auxiliar → Shaula Inbox)</option>
                <option value="export_only" ${data.aux_sync_mode === 'export_only' ? 'selected' : ''}>Exportação (Shaula → Auxiliar)</option>
                <option value="bidirectional" ${data.aux_sync_mode === 'bidirectional' ? 'selected' : ''}>Bidirecional (Sincronização Completa)</option>
              </select>
            </div>
          </div>

          <!-- Status do Vault Auxiliar -->
          <div style="background:var(--bg-primary); border:1px solid var(--border-color); border-radius:6px; padding:12px 16px; display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
            <div>
              <div style="font-size:12px; color:#fff; font-weight:600;">
                Status: <span style="color:${stats.exists ? 'var(--status-green)' : 'var(--status-red)'};">${stats.exists ? '✓ Conectado / Acessível' : '✗ Não encontrado'}</span>
              </div>
              <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">
                Notas no auxiliar: <strong>${stats.total_notes}</strong> | Tamanho total: <strong>${stats.total_size_kb} KB</strong> | Última sinc: ${data.last_sync ? data.last_sync : 'Nunca'}
              </div>
            </div>
            <div style="display:flex; gap:8px;">
              <button class="btn-secondary" onclick="saveAuxSettings()">💾 Salvar Preferências</button>
              <button class="btn-primary" onclick="triggerAuxSync()">🔄 Sincronizar Agora</button>
            </div>
          </div>

          <!-- Navegador de Arquivos do Vault Auxiliar -->
          <div style="margin-top:16px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <span style="font-size:12px; font-weight:600; color:#fff;">Notas Disponíveis no Vault Auxiliar</span>
              <button class="icon-btn" onclick="loadAuxTree()" title="Atualizar">🔄</button>
            </div>
            <div id="auxTreeContainer" style="max-height:220px; overflow-y:auto; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:6px; padding:8px;">
              Carregando notas do vault auxiliar...
            </div>
          </div>
        </div>

        <!-- Seção 2: Portabilidade & Docker -->
        <div class="stat-card" style="margin-bottom:24px; padding:20px;">
          <h3 style="color:#fff; font-size:16px; display:flex; align-items:center; gap:8px; margin-bottom:8px;">
            <span>🐳</span> Portabilidade & Execução em Qualquer PC
          </h3>
          <p style="color:var(--text-secondary); font-size:13px; line-height:1.5; margin-bottom:12px;">
            O Shaula é 100% autossuficiente e containerizável. Para levar este dashboard para outro computador com Docker:
          </p>

          <pre style="background:#141416; padding:12px; border-radius:6px; font-size:12px; color:#a78bfa; margin-bottom:12px; overflow-x:auto;">
# No novo computador (com Docker instalado):
docker compose up -d

# Acesse no navegador:
http://localhost:5000 (ou http://IP_DO_PC:5000)
# Para configurar o Vault Auxiliar, abra Configurações (⚙️) e digite a senha 3884</pre>
        </div>

        <!-- Seção 3: Alterar Senha de Segurança -->
        <div class="stat-card" style="padding:20px;">
          <h3 style="color:#fff; font-size:16px; margin-bottom:8px;">🔑 Segurança do Painel</h3>
          <div style="display:flex; gap:12px; align-items:flex-end;">
            <div style="flex:1;">
              <label style="display:block; font-size:11px; text-transform:uppercase; color:var(--text-muted); margin-bottom:4px;">
                Alterar Senha de Acesso (Atual: 3884)
              </label>
              <input type="password" id="newAdminPasswordInput" placeholder="Nova senha..." style="width:100%; padding:8px 12px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:6px; color:#fff; font-size:13px; outline:none;">
            </div>
            <button class="btn-secondary" onclick="updateAdminPassword()">Atualizar Senha</button>
          </div>
        </div>
      </div>
    `;

    loadAuxTree();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function saveAuxSettings() {
  const enabled = document.getElementById('auxEnabledCheck').checked;
  const path = document.getElementById('auxPathInput').value.trim();
  const syncMode = document.getElementById('auxSyncModeSelect').value;

  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Shaula-Auth': state.authToken
      },
      body: JSON.stringify({
        aux_vault_enabled: enabled,
        aux_vault_path: path,
        aux_sync_mode: syncMode
      })
    });
    if (!res.ok) throw new Error('Falha ao salvar configurações');
    showToast('Preferências salvas com sucesso!', 'success');
    renderSettingsDashboard();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function triggerAuxSync() {
  showToast('Iniciando sincronização de vaults...', 'info');
  try {
    const res = await fetch('/api/settings/aux/sync', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Shaula-Auth': state.authToken
      },
      body: JSON.stringify({})
    });
    if (!res.ok) throw new Error('Falha ao sincronizar');
    const data = await res.json();
    showToast(`Sincronizado: ${data.imported_notes} importada(s), ${data.exported_notes} exportada(s)`, 'success');
    loadVaultTree();
    renderSettingsDashboard();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function loadAuxTree() {
  const container = document.getElementById('auxTreeContainer');
  if (!container) return;

  try {
    const res = await fetch('/api/settings/aux/tree', {
      headers: { 'X-Shaula-Auth': state.authToken }
    });
    if (!res.ok) throw new Error('Não foi possível ler o vault auxiliar');
    const tree = await res.json();

    function renderNode(node) {
      if (node.type === 'directory') {
        const children = (node.children || []).map(renderNode).join('');
        return `<div><div style="font-size:12px; font-weight:600; color:var(--text-muted); padding:3px 0;">📁 ${escapeHtml(node.name)}</div><div style="padding-left:14px;">${children}</div></div>`;
      } else {
        return `
          <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 6px; border-radius:4px; font-size:12px; background:var(--bg-card); margin-bottom:4px;">
            <span>📄 ${escapeHtml(node.name)}</span>
            <button class="btn-secondary" style="padding:2px 8px; font-size:11px;" onclick="importAuxNote('${escapeHtml(node.path)}')">
              📥 Importar
            </button>
          </div>
        `;
      }
    }

    if (!tree.children || tree.children.length === 0) {
      container.innerHTML = `<div style="font-size:12px; color:var(--text-muted); text-align:center; padding:12px;">Nenhuma nota encontrada no Vault Auxiliar no momento.</div>`;
    } else {
      container.innerHTML = tree.children.map(renderNode).join('');
    }
  } catch (err) {
    container.innerHTML = `<div style="font-size:12px; color:var(--status-red);">${err.message}</div>`;
  }
}

async function importAuxNote(notePath) {
  try {
    const res = await fetch('/api/settings/aux/import', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Shaula-Auth': state.authToken
      },
      body: JSON.stringify({ aux_path: notePath, dest_folder: '00 - Inbox' })
    });
    if (!res.ok) throw new Error('Falha ao importar nota');
    const data = await res.json();
    showToast(`Nota importada para ${data.destination}!`, 'success');
    loadVaultTree();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function updateAdminPassword() {
  const inp = document.getElementById('newAdminPasswordInput');
  if (!inp || !inp.value.trim()) return;
  const newPw = inp.value.trim();

  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Shaula-Auth': state.authToken
      },
      body: JSON.stringify({ admin_password: newPw })
    });
    if (!res.ok) throw new Error('Falha ao atualizar senha');
    showToast('Senha administrativa atualizada!', 'success');
    inp.value = '';
    handleSettingsLogout();
  } catch (err) {
    showToast(err.message, 'error');
  }
}


// --- AGENTE HERMES: CHAT & PROCESSAMENTO DE SERIAIS ---
let currentHermesSessionId = null;
let hermesChatHistory = [
  {
    role: 'assistant',
    text: 'Olá! Sou **Shaula**, operando no centro de comando Shaula com o perfil oficial Hermes e acesso integrado ao **Vault Shaula** e ao meu **Vault Auxiliar**.\n\nTelemetria e seriais do host sincronizados. Posso cruzar especificações de ativos, auditar links, categorizar documentos pela literatura PKM e consultar o conhecimento de ambos os cofres. Como posso ajudar agora?'
  }
];

// --- INGESTÃO INTELIGENTE COM IA & ANTI-DUPLICAÇÃO (AGENTE HERMES) ---
let duplicateDebounceTimer = null;

async function openSmartNoteModal() {
  const modal = document.getElementById('smartNoteModal');
  if (!modal) return;
  modal.style.display = 'flex';
  const inp = document.getElementById('smartNoteInput');
  inp.value = '';
  document.getElementById('smartNoteTitleInput').value = '';
  document.getElementById('smartNoteProcessStatus').style.display = 'none';
  document.getElementById('duplicateWarningBox').style.display = 'none';

  const step1 = document.getElementById('smartNoteStep1');
  const step2 = document.getElementById('smartNoteStep2');
  if (step1) step1.style.display = 'block';
  if (step2) step2.style.display = 'none';

  inp.focus();

  // Carregar atalhos de hardware detectados no host
  const pillsContainer = document.getElementById('hostSerialsPills');
  try {
    const res = await fetch('/api/hermes/hardware-serials');
    if (!res.ok) throw new Error();
    const data = await res.json();
    const entries = Object.entries(data);

    if (entries.length === 0) {
      pillsContainer.innerHTML = '<span style="font-size:11px; color:var(--text-muted);">Nenhum componente de hardware físico indexado.</span>';
    } else {
      pillsContainer.innerHTML = entries.map(([s, info]) => {
        const label = info.model ? `${info.model} (${s})` : (info.interface ? `MAC ${info.interface} (${s})` : s);
        return `
          <button type="button" class="btn-secondary" style="font-size:10.5px; padding:2px 8px; border-radius:12px; font-family:var(--font-mono);" onclick="selectHostShortcut('${escapeHtml(s)}', '${escapeHtml(info.model || '')}')">
            ${escapeHtml(label)}
          </button>
        `;
      }).join('');
    }
  } catch (e) {
    pillsContainer.innerHTML = '<span style="font-size:11px; color:var(--text-muted);">Pronto para entrada de dados.</span>';
  }
}

function selectHostShortcut(serial, model) {
  const inp = document.getElementById('smartNoteInput');
  if (inp) inp.value = serial;
  const titleInp = document.getElementById('smartNoteTitleInput');
  if (titleInp && model) titleInp.value = `Ativo ${model}`;
  debounceCheckDuplicate();
}

function closeSmartNoteModal() {
  const modal = document.getElementById('smartNoteModal');
  if (modal) modal.style.display = 'none';
}

function debounceCheckDuplicate() {
  clearTimeout(duplicateDebounceTimer);
  duplicateDebounceTimer = setTimeout(async () => {
    const inp = document.getElementById('smartNoteInput');
    if (!inp) return;
    const q = inp.value.trim();
    const warnBox = document.getElementById('duplicateWarningBox');
    const infoEl = document.getElementById('duplicateNoteInfo');
    const openBtn = document.getElementById('btnOpenExistingNote');

    if (q.length < 3) {
      warnBox.style.display = 'none';
      return;
    }

    try {
      const res = await fetch('/api/smart-note/check-duplicate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q })
      });
      if (!res.ok) return;
      const data = await res.json();

      if (data.duplicate_detected && data.top_match) {
        warnBox.style.display = 'block';
        infoEl.innerHTML = `Identificamos a nota <strong>${escapeHtml(data.top_match.title)}</strong> em <code>${escapeHtml(data.top_match.path)}</code> relacionada a este ativo/informação.`;
        openBtn.onclick = () => {
          closeSmartNoteModal();
          openNote(data.top_match.path);
        };
      } else {
        warnBox.style.display = 'none';
      }
    } catch (e) {}
  }, 400);
}

let currentDraftNote = null;

async function submitSmartNoteWorkflow(force = false) {
  const query = document.getElementById('smartNoteInput').value.trim();
  const title = document.getElementById('smartNoteTitleInput').value.trim();
  const folder = document.getElementById('smartNoteFolderSelect').value;
  const statusBox = document.getElementById('smartNoteProcessStatus');
  const btn = document.getElementById('btnSubmitSmartNote');
  const warnBox = document.getElementById('duplicateWarningBox');

  if (!query) {
    alert('Por favor, digite o nome da máquina, dado parcial ou identificador.');
    return;
  }

  statusBox.style.display = 'block';
  statusBox.innerHTML = `⏳ <strong>Operadora processando:</strong> Cruzando informações nos Vaults e construindo minuta para sua aprovação...`;
  btn.disabled = true;

  try {
    const res = await fetch('/api/smart-note/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: query,
        title: title || undefined,
        folder: folder,
        force: force,
        dry_run: true // Não grava diretamente; gera minuta para aprovação prévia do usuário!
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Falha ao processar nota inteligente');
    }

    const data = await res.json();

    if (data.duplicate_detected && !force) {
      statusBox.style.display = 'none';
      warnBox.style.display = 'block';
      const infoEl = document.getElementById('duplicateNoteInfo');
      infoEl.innerHTML = `O Vault já contém: <strong>${escapeHtml(data.existing_note.title)}</strong> (${escapeHtml(data.existing_note.path)}).`;
      document.getElementById('btnOpenExistingNote').onclick = () => {
        closeSmartNoteModal();
        openNote(data.existing_note.path);
      };
      btn.disabled = false;
      return;
    }

    // Salvar estado da minuta em aprovação
    currentDraftNote = {
      title: data.title,
      category: data.category || 'Ativos e Equipamentos',
      folder_used: data.folder_used || '03 - Knowledge/Ativos',
      safe_filename: data.safe_filename,
      rel_path: data.rel_path,
      content: data.content,
      original_query: query
    };

    // Preencher campos da tela de aprovação
    document.getElementById('approvalTitleInput').value = data.title;
    document.getElementById('approvalFolderInput').value = data.folder_used;
    document.getElementById('approvalCategoryBadge').textContent = `🏷️ ${data.category}`;
    document.getElementById('approvalDestPathLabel').textContent = data.rel_path;
    document.getElementById('approvalRawEditor').value = data.content;

    const previewPane = document.getElementById('approvalPreviewPane');
    if (previewPane) {
      previewPane.innerHTML = typeof marked !== 'undefined' ? marked.parse(data.content) : escapeHtml(data.content);
    }

    switchApprovalTab('preview');

    // Transicionar para o Passo 2 (Aprovação)
    document.getElementById('smartNoteStep1').style.display = 'none';
    document.getElementById('smartNoteStep2').style.display = 'block';
    statusBox.style.display = 'none';

  } catch (err) {
    statusBox.style.display = 'block';
    statusBox.innerHTML = `❌ <span style="color:var(--status-red);">${escapeHtml(err.message)}</span>`;
  } finally {
    btn.disabled = false;
  }
}

function switchApprovalTab(tab) {
  const btnPrev = document.getElementById('btnApprovalTabPreview');
  const btnEdit = document.getElementById('btnApprovalTabEdit');
  const panePrev = document.getElementById('approvalPreviewPane');
  const paneEdit = document.getElementById('approvalRawEditor');

  if (tab === 'preview') {
    if (btnPrev) btnPrev.classList.add('active');
    if (btnEdit) btnEdit.classList.remove('active');
    if (panePrev) panePrev.style.display = 'block';
    if (paneEdit) paneEdit.style.display = 'none';
  } else {
    if (btnEdit) btnEdit.classList.add('active');
    if (btnPrev) btnPrev.classList.remove('active');
    if (panePrev) panePrev.style.display = 'none';
    if (paneEdit) {
      paneEdit.style.display = 'block';
      paneEdit.focus();
    }
  }
}

function renderApprovalMarkdownLive() {
  if (!currentDraftNote) return;
  const editor = document.getElementById('approvalRawEditor');
  currentDraftNote.content = editor.value;
  const previewPane = document.getElementById('approvalPreviewPane');
  if (previewPane && typeof marked !== 'undefined') {
    previewPane.innerHTML = marked.parse(editor.value);
  }
}

function updateDraftFilename() {
  if (!currentDraftNote) return;
  const newTitle = document.getElementById('approvalTitleInput').value.trim();
  const newFolder = document.getElementById('approvalFolderInput').value.trim();

  currentDraftNote.title = newTitle;
  currentDraftNote.folder_used = newFolder;

  const cleanTitle = newTitle.replace(/[^a-zA-Z0-9_\- ]/g, '').trim().replace(/\s+/g, '_');
  currentDraftNote.rel_path = `${newFolder.replace(/\/+$/, '')}/${cleanTitle || 'Nota'}.md`;

  const label = document.getElementById('approvalDestPathLabel');
  if (label) label.textContent = currentDraftNote.rel_path;
}

function backToSmartNoteInput() {
  const step1 = document.getElementById('smartNoteStep1');
  const step2 = document.getElementById('smartNoteStep2');
  if (step1) step1.style.display = 'block';
  if (step2) step2.style.display = 'none';
}

async function confirmAndSaveApprovedNote() {
  if (!currentDraftNote) return;

  const btn = document.getElementById('btnApproveAndSave');
  if (btn) btn.disabled = true;

  try {
    const rawContent = document.getElementById('approvalRawEditor').value;
    const destPath = currentDraftNote.rel_path;

    const res = await fetch('/api/vault/note', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: destPath,
        content: rawContent
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Falha ao salvar nota aprovada no Vault');
    }

    closeSmartNoteModal();
    showToast(`✓ Nota aprovada e gravada com sucesso: ${destPath}`, 'success');

    // Recarregar árvore e abrir a nota aprovada no editor
    await loadVaultTree();
    await openNote(destPath);

    hermesChatHistory.push({
      role: 'user',
      text: `Aprovar e gravar nota para: "${currentDraftNote.original_query}"`
    });
    hermesChatHistory.push({
      role: 'assistant',
      text: `✅ **Nota Aprovada e Gravada no Vault!**\n- **Documento:** [[${destPath}]]\n- **Categoria PKM:** \`${currentDraftNote.category}\`\n- **Pasta:** \`${currentDraftNote.folder_used}\`\nDocumento revisado pelo usuário e persistido no Vault Shaula.`
    });

  } catch (err) {
    showToast(`Erro ao gravar nota: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}


// --- VIEW: INSERIR IMAGENS & TRIAGEM DE GALERIA (1 A 20 IMAGENS) ---
let imageUploadState = {
  mode: 'shared', // 'shared' | 'individual'
  files: [],      // array of { file, previewUrl, description }
};

function renderImagesView() {
  const container = document.getElementById('customViewContainer');
  container.innerHTML = `
    <div class="full-panel-view images-view-panel" style="display:flex; flex-direction:column; height:100%;">
      <!-- Cabeçalho -->
      <div class="view-header-row" style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border-color); padding-bottom:14px; margin-bottom:18px;">
        <div style="display:flex; align-items:center; gap:12px;">
          <div style="font-size:28px;">🖼️</div>
          <div>
            <h2 style="color:#fff; font-size:18px; font-weight:600; display:flex; align-items:center; gap:8px;">
              Inserir Imagens no Vault
              <span class="pill-badge" id="imgCountBadge" style="font-size:11px; background:rgba(124, 58, 237, 0.2); color:var(--text-accent);">
                0 / 20 imagens
              </span>
            </h2>
            <p style="color:var(--text-muted); font-size:12px;">
              Carregue até 20 imagens com descrição única compartilhada ou descrição individual para cada item.
            </p>
          </div>
        </div>

        <button class="btn-primary" id="btnUploadImages" onclick="submitImageUpload()" style="padding:10px 18px;">
          <span>🚀</span> Salvar Imagens & Criar Nota
        </button>
      </div>

      <!-- Controles de Configuração e Modo de Descrição -->
      <div class="stat-card" style="margin-bottom:18px; padding:16px 20px;">
        <div class="responsive-grid-split" style="display:grid; grid-template-columns: 2fr 1fr; gap:16px; margin-bottom:14px;">
          <div>
            <label style="display:block; font-size:11px; text-transform:uppercase; color:var(--text-muted); margin-bottom:4px; font-weight:600;">
              Título da Nota no Vault
            </label>
            <input type="text" id="imgNoteTitleInput" placeholder="Ex: Registro Fotográfico de Inspeção" style="width:100%; padding:8px 12px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:6px; color:#fff; font-size:13px; outline:none;">
          </div>
          <div>
            <label style="display:block; font-size:11px; text-transform:uppercase; color:var(--text-muted); margin-bottom:4px; font-weight:600;">
              Pasta de Destino
            </label>
            <select id="imgFolderSelect" style="width:100%; padding:8px 12px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:6px; color:#fff; font-size:13px; outline:none;">
              <option value="00 - Inbox">00 - Inbox</option>
              <option value="03 - Knowledge">03 - Knowledge</option>
              <option value="01 - Verification">01 - Verification</option>
            </select>
          </div>
        </div>

        <div class="desc-mode-options" style="display:flex; align-items:center; gap:20px; border-top:1px solid var(--border-color); padding-top:12px;">
          <span style="font-size:12px; font-weight:600; color:#fff;">Modo de Descrição:</span>
          <label style="display:flex; align-items:center; gap:6px; font-size:12.5px; cursor:pointer;">
            <input type="radio" name="descMode" value="shared" checked onchange="toggleDescMode('shared')">
            <span>Descrição Única (para todas as imagens)</span>
          </label>
          <label style="display:flex; align-items:center; gap:6px; font-size:12.5px; cursor:pointer;">
            <input type="radio" name="descMode" value="individual" onchange="toggleDescMode('individual')">
            <span>Descrição Individual (uma para cada imagem)</span>
          </label>
        </div>

        <!-- Campo de Descrição Compartilhada (exibido apenas se mode === 'shared') -->
        <div id="sharedDescBox" style="margin-top:12px;">
          <label style="display:block; font-size:11px; text-transform:uppercase; color:var(--text-muted); margin-bottom:4px; font-weight:600;">
            Descrição Geral Compartilhada
          </label>
          <textarea id="sharedDescInput" rows="2" placeholder="Digite uma descrição detalhada que será aplicada a todas as imagens do lote..." style="width:100%; padding:10px 12px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:6px; color:#fff; font-size:13px; outline:none; resize:none;"></textarea>
        </div>
      </div>

      <!-- Zona de Dropzone / Seleção de Arquivos -->
      <div id="imgDropzone" style="border:2px dashed #3f3f46; border-radius:8px; padding:24px; text-align:center; background:var(--bg-card); cursor:pointer; margin-bottom:18px; transition:border-color 0.2s;" onclick="document.getElementById('fileImagePicker').click()">
        <input type="file" id="fileImagePicker" multiple accept="image/*" style="display:none;" onchange="handleImageSelection(event)">
        <div style="font-size:32px; margin-bottom:6px;">📸</div>
        <div style="font-size:14px; font-weight:600; color:#f1f5f9;">Clique para selecionar ou arraste imagens aqui</div>
        <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">Suporta de 1 até 20 imagens (PNG, JPG, WEBP, GIF)</div>
      </div>

      <!-- Grade de Pré-visualização das Imagens -->
      <div style="flex:1; overflow-y:auto;">
        <div id="imageCardsGrid" class="image-cards-grid" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:16px;">
          <!-- Cards injetados dinamicamente -->
        </div>
      </div>
    </div>
  `;

  // Configurar drag & drop
  const dropzone = document.getElementById('imgDropzone');
  if (dropzone) {
    ['dragenter', 'dragover'].forEach(name => {
      dropzone.addEventListener(name, (e) => { e.preventDefault(); dropzone.style.borderColor = 'var(--accent-purple)'; });
    });
    ['dragleave', 'drop'].forEach(name => {
      dropzone.addEventListener(name, (e) => { e.preventDefault(); dropzone.style.borderColor = '#3f3f46'; });
    });
    dropzone.addEventListener('drop', (e) => {
      if (e.dataTransfer && e.dataTransfer.files) {
        processFilesList(Array.from(e.dataTransfer.files));
      }
    });
  }

  renderImageGrid();
}

function toggleDescMode(mode) {
  imageUploadState.mode = mode;
  const sharedBox = document.getElementById('sharedDescBox');
  if (sharedBox) {
    sharedBox.style.display = (mode === 'shared') ? 'block' : 'none';
  }
  renderImageGrid();
}

function handleImageSelection(event) {
  if (event.target && event.target.files) {
    processFilesList(Array.from(event.target.files));
  }
}

function processFilesList(newFiles) {
  const imageFiles = newFiles.filter(f => f.type.startsWith('image/'));
  if (imageFiles.length === 0) {
    showToast('Nenhuma imagem válida encontrada nos arquivos selecionados.', 'error');
    return;
  }

  const remainingSlots = 20 - imageUploadState.files.length;
  if (remainingSlots <= 0) {
    alert('Limite máximo de 20 imagens atingido.');
    return;
  }

  const toAdd = imageFiles.slice(0, remainingSlots);
  toAdd.forEach(f => {
    imageUploadState.files.push({
      file: f,
      previewUrl: URL.createObjectURL(f),
      description: ''
    });
  });

  if (imageFiles.length > remainingSlots) {
    showToast(`Adicionadas ${remainingSlots} imagens (limite máximo de 20).`, 'info');
  }

  renderImageGrid();
}

function removeImageItem(index) {
  if (imageUploadState.files[index]) {
    URL.revokeObjectURL(imageUploadState.files[index].previewUrl);
    imageUploadState.files.splice(index, 1);
    renderImageGrid();
  }
}

function updateIndividualDescription(index, val) {
  if (imageUploadState.files[index]) {
    imageUploadState.files[index].description = val;
  }
}

function renderImageGrid() {
  const grid = document.getElementById('imageCardsGrid');
  const countBadge = document.getElementById('imgCountBadge');
  if (countBadge) {
    countBadge.textContent = `${imageUploadState.files.length} / 20 imagens`;
  }
  if (!grid) return;

  if (imageUploadState.files.length === 0) {
    grid.innerHTML = `
      <div style="grid-column: 1 / -1; text-align:center; padding:40px; color:var(--text-muted); font-size:13px;">
        Nenhuma imagem carregada ainda. Selecione até 20 imagens para começar.
      </div>
    `;
    return;
  }

  const isIndividual = imageUploadState.mode === 'individual';

  grid.innerHTML = imageUploadState.files.map((item, idx) => {
    const sizeKb = Math.round(item.file.size / 1024);
    return `
      <div class="stat-card" style="padding:10px; position:relative; display:flex; flex-direction:column; gap:8px;">
        <button type="button" class="icon-btn" style="position:absolute; top:8px; right:8px; background:rgba(0,0,0,0.6); color:#fff; border-radius:50%; width:24px; height:24px;" onclick="removeImageItem(${idx})" title="Remover">✕</button>
        
        <div class="image-card-thumb" style="width:100%; height:160px; border-radius:6px; overflow:hidden; background:#121214; display:flex; align-items:center; justify-content:center;">
          <img src="${item.previewUrl}" style="max-width:100%; max-height:100%; object-fit:contain;">
        </div>

        <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; color:var(--text-muted);">
          <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:170px;" title="${escapeHtml(item.file.name)}">
            ${escapeHtml(item.file.name)}
          </span>
          <span>${sizeKb} KB</span>
        </div>

        ${isIndividual ? `
          <textarea rows="2" placeholder="Descrição individual desta imagem..." style="width:100%; padding:6px 8px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:4px; color:#fff; font-size:12px; outline:none; resize:none;" oninput="updateIndividualDescription(${idx}, this.value)">${escapeHtml(item.description)}</textarea>
        ` : ''}
      </div>
    `;
  }).join('');
}

async function submitImageUpload() {
  if (imageUploadState.files.length === 0) {
    alert('Adicione pelo menos 1 imagem para enviar.');
    return;
  }

  const btn = document.getElementById('btnUploadImages');
  btn.disabled = true;
  btn.textContent = 'Enviando...';

  const formData = new FormData();
  imageUploadState.files.forEach(item => {
    formData.append('files', item.file);
  });

  const mode = imageUploadState.mode;
  formData.append('mode', mode);

  if (mode === 'shared') {
    const sharedDesc = document.getElementById('sharedDescInput') ? document.getElementById('sharedDescInput').value : '';
    formData.append('shared_description', sharedDesc);
  } else {
    const indDescs = imageUploadState.files.map(f => f.description || '');
    formData.append('individual_descriptions', JSON.stringify(indDescs));
  }

  const titleInp = document.getElementById('imgNoteTitleInput');
  const title = titleInp ? titleInp.value.trim() : '';
  formData.append('note_title', title);

  const folderSel = document.getElementById('imgFolderSelect');
  const folder = folderSel ? folderSel.value : '00 - Inbox';
  formData.append('dest_folder', folder);
  formData.append('create_note', 'true');

  try {
    const res = await fetch('/api/images/upload', {
      method: 'POST',
      body: formData
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Falha no upload de imagens');
    }
    const data = await res.json();
    showToast(`Sucesso! ${data.count} imagem(ns) salvas em assets e nota gerada.`, 'success');

    // Limpar estado
    imageUploadState.files.forEach(f => URL.revokeObjectURL(f.previewUrl));
    imageUploadState.files = [];

    // Recarregar árvore e abrir a nota recém-criada
    await loadVaultTree();
    if (data.note_path) {
      await openNote(data.note_path);
    }
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>🚀</span> Salvar Imagens & Criar Nota';
  }
}

// --- VIEW DO AGENTE HERMES ---
async function renderHermesView() {
  const container = document.getElementById('customViewContainer');
  container.innerHTML = `
    <div class="full-panel-view hermes-view-panel" style="display:flex; flex-direction:column; height:100%;">
      <!-- Cabeçalho do Hermes -->
      <div class="view-header-row" style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border-color); padding-bottom:14px; margin-bottom:16px;">
        <div style="display:flex; align-items:center; gap:12px;">
          <div style="font-size:28px;">🤖</div>
          <div>
            <h2 style="color:#fff; font-size:18px; font-weight:600; display:flex; align-items:center; gap:8px;">
              Operadora Hermes (Perfil Shaula)
              <span class="pill-badge" id="hermesBadge" style="font-size:10px; background:rgba(124, 58, 237, 0.2); color:var(--text-accent);">Conectando...</span>
            </h2>
            <p style="color:var(--text-muted); font-size:12px;">
              Inteligência Artificial Shaula (Hermes) com total domínio do <strong>Vault Shaula</strong> (<code>./vault</code>) e do <strong>Vault Auxiliar</strong>.
            </p>
          </div>
        </div>
        <div class="header-action-buttons" style="display:flex; gap:8px;">
          <button class="btn-primary" onclick="openSmartNoteModal()">
            <span>⚡</span> Nota Inteligente
          </button>
          <button class="btn-secondary" onclick="clearHermesChat()">
            🗑️ Limpar Conversa
          </button>
        </div>
      </div>

      <!-- Atalhos Rápidos de Ação -->
      <div style="display:flex; gap:8px; margin-bottom:14px; overflow-x:auto; padding-bottom:4px;">
        <button class="btn-secondary" style="font-size:11px; padding:4px 10px; border-radius:14px; white-space:nowrap;" onclick="promptHermesWithContext('Qual é o status atual do Vault Shaula e do Vault Auxiliar de Shaula? Quantas notas temos em cada um e como estão estruturadas?')">
          📊 Status dos Vaults (Principal & Auxiliar)
        </button>
        <button class="btn-secondary" style="font-size:11px; padding:4px 10px; border-radius:14px; white-space:nowrap;" onclick="promptHermesWithContext('Audite a integridade dos Wikilinks e conexões do Vault Shaula e aponte pendências ou links quebrados.')">
          🛡️ Auditar Wikilinks e Integridade
        </button>
        <button class="btn-secondary" style="font-size:11px; padding:4px 10px; border-radius:14px; white-space:nowrap;" onclick="promptHermesWithContext('Como você, Operadora do Vault, classifica novos ativos e máquinas nas categorias da literatura de Personal Knowledge Management (PKM)?')">
          🏭 Categorização PKM de Ativos
        </button>
        <button class="btn-secondary" style="font-size:11px; padding:4px 10px; border-radius:14px; white-space:nowrap;" onclick="promptHermesWithContext('Resuma os principais tópicos da nota atualmente aberta no editor.')">
          📝 Resumir Nota Ativa
        </button>
      </div>

      <!-- Histórico de Conversa -->
      <div id="hermesChatBox" class="hermes-chat-box" style="flex:1; overflow-y:auto; background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:8px; padding:18px; display:flex; flex-direction:column; gap:16px; margin-bottom:16px;">
        <!-- Mensagens renderizadas aqui -->
      </div>

      <!-- Barra de Envio -->
      <div class="hermes-input-bar" style="display:flex; gap:10px; align-items:center;">
        <input type="text" id="hermesPromptInput" placeholder="Pergunte à Operadora sobre notas, máquinas, telemetria ou ações nos Vaults..." style="flex:1; padding:12px 16px; background:var(--bg-card); border:1px solid var(--border-color); border-radius:8px; color:#fff; font-size:13.5px; outline:none;" onkeydown="if(event.key === 'Enter') sendHermesMessage()">
        <button class="btn-primary" id="btnSendHermes" style="padding:12px 20px;" onclick="sendHermesMessage()">
          <span>Enviar</span> ➔
        </button>
      </div>
    </div>
  `;

  renderHermesChatHistory();
  updateHermesStatusBadge();
}

async function updateHermesStatusBadge() {
  try {
    const res = await fetch('/api/hermes/status');
    if (!res.ok) return;
    const data = await res.json();
    const badge = document.getElementById('hermesBadge');
    if (badge) {
      if (data.connected || data.native_cli) {
        badge.textContent = `✓ ${data.model} (Motor Nativo)`;
        badge.style.background = 'rgba(16, 185, 129, 0.15)';
        badge.style.color = 'var(--status-green)';
      } else {
        badge.textContent = `● Modo Local / Offline`;
        badge.style.background = 'rgba(245, 158, 11, 0.15)';
        badge.style.color = 'var(--accent-gold)';
      }
    }
  } catch (e) {}
}

function renderHermesChatHistory() {
  const box = document.getElementById('hermesChatBox');
  if (!box) return;

  box.innerHTML = hermesChatHistory.map((m, idx) => {
    const isUser = m.role === 'user';
    const isPending = m.isPending;
    let parsedText = '';
    if (isPending) {
      parsedText = m.text;
    } else if (typeof marked !== 'undefined') {
      parsedText = marked.parse(m.text);
    } else {
      parsedText = escapeHtml(m.text);
    }

    return `
      <div style="display:flex; gap:12px; align-items:flex-start; ${isUser ? 'flex-direction:row-reverse;' : ''}">
        <div style="width:32px; height:32px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:${isUser ? 'var(--accent-purple)' : '#2d2d30'}; font-size:16px; flex-shrink:0;">
          ${isUser ? '👤' : (isPending ? '⏳' : '🤖')}
        </div>
        <div style="max-width:80%; background:${isUser ? 'rgba(124, 58, 237, 0.15)' : 'var(--bg-card)'}; border:1px solid ${isUser ? 'rgba(124, 58, 237, 0.3)' : 'var(--border-color)'}; padding:12px 16px; border-radius:8px; font-size:13.5px; line-height:1.55; color:#f1f5f9;">
          <div class="markdown-body" style="background:transparent; padding:0;">${parsedText}</div>
          ${(!isUser && !isPending) ? `
            <div style="display:flex; gap:8px; margin-top:10px; border-top:1px solid #333; padding-top:8px;">
              <button class="btn-secondary" style="padding:2px 8px; font-size:11px;" onclick="insertTextIntoActiveEditor(${idx})">📥 Inserir na Nota Ativa</button>
              <button class="btn-secondary" style="padding:2px 8px; font-size:11px;" onclick="createNoteFromHermesResponse(${idx})">📄 Salvar como Nova Nota</button>
            </div>
          ` : ''}
        </div>
      </div>
    `;
  }).join('');

  box.scrollTop = box.scrollHeight;
}

async function sendHermesMessage() {
  const inp = document.getElementById('hermesPromptInput');
  if (!inp || !inp.value.trim()) return;
  const message = inp.value.trim();
  inp.value = '';

  hermesChatHistory.push({ role: 'user', text: message });
  const pendingIndex = hermesChatHistory.length;
  hermesChatHistory.push({
    role: 'assistant',
    text: '<span class="hermes-thinking-indicator">Shaula executando ferramentas nativas e processando raciocínio...</span>',
    isPending: true
  });
  renderHermesChatHistory();

  const btn = document.getElementById('btnSendHermes');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>Executando...</span> ⏳';
  }

  try {
    const res = await fetch('/api/hermes/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: message,
        session_id: currentHermesSessionId
      })
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Falha na resposta do Hermes');
    }
    const data = await res.json();
    if (data.session_id) {
      currentHermesSessionId = data.session_id;
    }
    hermesChatHistory[pendingIndex] = { role: 'assistant', text: data.reply };
  } catch (err) {
    hermesChatHistory[pendingIndex] = {
      role: 'assistant',
      text: `❌ **Erro ao consultar o Hermes:** ${err.message}`
    };
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<span>Enviar</span> ➔';
    }
    renderHermesChatHistory();
  }
}

function promptHermesWithContext(promptText) {
  const inp = document.getElementById('hermesPromptInput');
  if (inp) {
    inp.value = promptText;
    sendHermesMessage();
  }
}

async function clearHermesChat() {
  try {
    const res = await fetch('/api/hermes/chat/clear', { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      currentHermesSessionId = data.session_id;
    }
  } catch (e) {}
  hermesChatHistory = [
    {
      role: 'assistant',
      text: 'Conversa reiniciada. Sou **Shaula**, operando com o motor completo do Hermes e total integração aos Vaults. Em que posso atuar nas operações do sistema agora?'
    }
  ];
  renderHermesChatHistory();
  showToast('Sessão com a Operadora Hermes reiniciada.', 'info');
}

function insertTextIntoActiveEditor(msgIndex) {
  const msg = hermesChatHistory[msgIndex];
  if (!msg || !msg.text) return;

  const editor = document.getElementById('rawEditor');
  if (editor && state.currentNote) {
    editor.value += `\n\n### ☤ Nota do Agente Hermes\n${msg.text}\n`;
    state.isDirty = true;
    updateSaveStatusBadge();
    renderMarkdownLive();
    switchView('vault');
    showToast('Conteúdo inserido na nota ativa!', 'success');
  } else {
    showToast('Abra uma nota no Vault para inserir o conteúdo.', 'info');
  }
}

async function createNoteFromHermesResponse(msgIndex) {
  const msg = hermesChatHistory[msgIndex];
  if (!msg || !msg.text) return;

  const title = prompt('Título da nova nota:', 'Resposta Hermes');
  if (!title || !title.trim()) return;

  const nowStr = new Date().toISOString().replace('T', ' ').substring(0, 16);
  const content = `---
title: "${title.trim()}"
date: "${nowStr}"
tags:
  - hermes
  - assistente
---

# ${title.trim()}

> Gerado pelo **Agente Hermes** | [[Shaula Home]]

---

${msg.text}
`;

  const filename = `00 - Inbox/${title.trim().replace(/[^a-zA-Z0-9_\-]/g, '_')}.md`;
  await createNewNoteDirect(filename);
}
