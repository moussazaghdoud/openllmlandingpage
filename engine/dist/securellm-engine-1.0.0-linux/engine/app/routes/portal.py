"""Customer admin portal — workspace-scoped self-service UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.auth import require_workspace
from app.models import (
    PPITermsResponse, PPITermsUpdate,
    PortalWorkspaceInfo, SubKeyCreate, SubKeyCreated, SubKeyResponse,
)
from app.storage import KVStore, get_store
from app import workspace as ws_ops

router = APIRouter(tags=["portal"])


# ── Portal API (workspace-scoped) ────────────────────────

@router.get("/portal/api/workspace", response_model=PortalWorkspaceInfo)
async def portal_workspace(
    ws_id: str = Depends(require_workspace),
    store: KVStore = Depends(get_store),
):
    ws = await ws_ops.get_workspace(store, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    stats = await ws_ops.get_stats(store, ws_id)
    return PortalWorkspaceInfo(**ws, stats=stats)


@router.get("/portal/api/ppi-terms", response_model=PPITermsResponse)
async def portal_get_ppi(
    ws_id: str = Depends(require_workspace),
    store: KVStore = Depends(get_store),
):
    terms = await ws_ops.get_ppi_terms(store, ws_id)
    return PPITermsResponse(terms=terms)


@router.put("/portal/api/ppi-terms", response_model=PPITermsResponse)
async def portal_set_ppi(
    body: PPITermsUpdate,
    ws_id: str = Depends(require_workspace),
    store: KVStore = Depends(get_store),
):
    terms = await ws_ops.set_ppi_terms(store, ws_id, body.terms)
    return PPITermsResponse(terms=terms)


@router.get("/portal/api/stats")
async def portal_stats(
    ws_id: str = Depends(require_workspace),
    store: KVStore = Depends(get_store),
):
    return await ws_ops.get_stats(store, ws_id)


@router.get("/portal/api/llm")
async def portal_llm(
    ws_id: str = Depends(require_workspace),
    store: KVStore = Depends(get_store),
):
    ws = await ws_ops.get_workspace(store, ws_id)
    if not ws or not ws.get("llm"):
        return {"configured": False}
    return ws["llm"]


@router.get("/portal/api/keys", response_model=list[SubKeyResponse])
async def portal_list_keys(
    ws_id: str = Depends(require_workspace),
    store: KVStore = Depends(get_store),
):
    keys = await ws_ops.list_api_keys(store, ws_id)
    return [SubKeyResponse(label=k["label"], prefix=k["prefix"], created_at=k["created_at"]) for k in keys]


@router.post("/portal/api/keys", response_model=SubKeyCreated)
async def portal_create_key(
    body: SubKeyCreate,
    ws_id: str = Depends(require_workspace),
    store: KVStore = Depends(get_store),
):
    result = await ws_ops.create_sub_api_key(store, ws_id, body.label)
    return SubKeyCreated(**result)


@router.delete("/portal/api/keys/{prefix}")
async def portal_revoke_key(
    prefix: str,
    ws_id: str = Depends(require_workspace),
    store: KVStore = Depends(get_store),
):
    ok = await ws_ops.revoke_api_key(store, ws_id, prefix + "...")
    if not ok:
        raise HTTPException(404, "Key not found")
    return {"revoked": True}


@router.post("/portal/api/test/anonymize")
async def portal_test_anonymize(
    body: dict,
    ws_id: str = Depends(require_workspace),
    store: KVStore = Depends(get_store),
):
    from app.engine.pipeline import PrivacyPipeline
    text = body.get("text", "")
    if not text:
        raise HTTPException(400, "Text is required")
    pipeline = await PrivacyPipeline.for_workspace(store, ws_id)
    anonymized_text, mapping_id = await pipeline.anonymize(text)
    await ws_ops.increment_stats(store, ws_id)
    return {"anonymized_text": anonymized_text, "mapping_id": mapping_id}


# ── Portal HTML ──────────────────────────────────────────

@router.get("/portal", response_class=HTMLResponse)
async def portal_page():
    return PORTAL_HTML


PORTAL_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SecureLLM — Customer Portal</title>
<style>
:root {
  --bg: #0f1117; --surface: #1a1d27; --surface2: #232733; --border: #2e3345;
  --text: #e1e4ed; --text2: #8b90a0;
  --accent: #6c5ce7; --accent2: #a29bfe;
  --green: #00b894; --red: #e17055; --orange: #fdcb6e; --blue: #74b9ff;
  --radius: 10px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }
.header { background:var(--surface); border-bottom:1px solid var(--border); padding:16px 32px; display:flex; align-items:center; justify-content:space-between; }
.header h1 { font-size:20px; font-weight:600; }
.header h1 span { color:var(--accent2); }
.header .sub { color:var(--text2); font-size:13px; margin-left:12px; }
.auth-bar { background:var(--surface2); padding:12px 32px; display:flex; align-items:center; gap:12px; border-bottom:1px solid var(--border); }
.auth-bar input { flex:1; max-width:500px; background:var(--surface); border:1px solid var(--border); color:var(--text); padding:8px 12px; border-radius:6px; font-size:13px; font-family:'SF Mono',monospace; }
.auth-bar input:focus { outline:none; border-color:var(--accent); }
.auth-bar label { color:var(--text2); font-size:13px; }
.container { max-width:1200px; margin:0 auto; padding:24px 32px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px; margin-bottom:32px; }
.card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:20px; }
.card h3 { font-size:13px; color:var(--text2); text-transform:uppercase; letter-spacing:.5px; margin-bottom:8px; }
.card .value { font-size:28px; font-weight:700; }
.card .sub { font-size:12px; color:var(--text2); margin-top:4px; }
.section { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); margin-bottom:24px; }
.section-header { padding:16px 20px; border-bottom:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; }
.section-header h2 { font-size:16px; font-weight:600; }
.section-body { padding:20px; }
table { width:100%; border-collapse:collapse; }
th { text-align:left; font-size:12px; color:var(--text2); text-transform:uppercase; letter-spacing:.5px; padding:8px 12px; border-bottom:1px solid var(--border); }
td { padding:12px; border-bottom:1px solid var(--border); font-size:14px; }
tr:last-child td { border-bottom:none; }
.btn { padding:8px 16px; border-radius:6px; font-size:13px; font-weight:500; border:none; cursor:pointer; transition:all .15s; }
.btn-primary { background:var(--accent); color:#fff; }
.btn-primary:hover { background:var(--accent2); }
.btn-danger { background:transparent; color:var(--red); border:1px solid var(--red); }
.btn-danger:hover { background:rgba(225,112,85,.1); }
.btn-sm { padding:5px 10px; font-size:12px; }
.btn-ghost { background:transparent; color:var(--accent2); border:1px solid var(--border); }
.btn-ghost:hover { border-color:var(--accent2); }
.badge { padding:4px 10px; border-radius:20px; font-size:12px; font-weight:500; }
.badge-green { background:rgba(0,184,148,.15); color:var(--green); }
.badge-orange { background:rgba(253,203,110,.15); color:var(--orange); }
.form-row { display:flex; gap:12px; margin-bottom:12px; flex-wrap:wrap; }
.form-group { display:flex; flex-direction:column; gap:4px; flex:1; min-width:180px; }
.form-group label { font-size:12px; color:var(--text2); }
.form-group input,.form-group textarea { background:var(--bg); border:1px solid var(--border); color:var(--text); padding:8px 12px; border-radius:6px; font-size:13px; font-family:inherit; }
.form-group input:focus,.form-group textarea:focus { outline:none; border-color:var(--accent); }
textarea { resize:vertical; min-height:80px; }
.mono { font-family:'SF Mono','Fira Code',monospace; font-size:12px; background:var(--bg); padding:2px 6px; border-radius:4px; }
.modal-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.6); z-index:100; align-items:center; justify-content:center; }
.modal-overlay.active { display:flex; }
.modal { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); width:500px; max-width:95vw; }
.modal-header { padding:16px 20px; border-bottom:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; }
.modal-header h2 { font-size:16px; }
.modal-close { background:none; border:none; color:var(--text2); font-size:20px; cursor:pointer; }
.modal-body { padding:20px; }
.modal-footer { padding:12px 20px; border-top:1px solid var(--border); display:flex; justify-content:flex-end; gap:8px; }
.test-result { background:var(--bg); border:1px solid var(--border); border-radius:6px; padding:12px; font-size:13px; white-space:pre-wrap; word-break:break-all; margin-top:8px; min-height:60px; }
.placeholder-ppi { color:var(--orange); font-weight:600; }
.placeholder-pii { color:var(--blue); font-weight:600; }
.toast { position:fixed; bottom:24px; right:24px; background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:12px 20px; font-size:13px; z-index:200; animation:slideIn .3s; }
.toast.error { border-color:var(--red); } .toast.success { border-color:var(--green); }
@keyframes slideIn { from{transform:translateY(20px);opacity:0}to{transform:translateY(0);opacity:1} }
.empty { text-align:center; padding:40px; color:var(--text2); }
.tag { display:inline-flex; align-items:center; gap:6px; background:var(--surface2); border:1px solid var(--border); border-radius:6px; padding:4px 10px; font-size:13px; margin:3px; }
.tag button { background:none; border:none; color:var(--text2); cursor:pointer; font-size:14px; padding:0 2px; }
.tag button:hover { color:var(--red); }
.info-row { display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid var(--border); font-size:14px; }
.info-row:last-child { border-bottom:none; }
.info-label { color:var(--text2); }
</style>
</head>
<body>

<div class="header">
  <div style="display:flex;align-items:center">
    <h1><span>Secure</span>LLM</h1>
    <span class="sub">Customer Portal</span>
  </div>
  <span id="wsName" style="color:var(--text2);font-size:14px"></span>
</div>

<div class="auth-bar">
  <label>API Key</label>
  <input type="password" id="apiKeyInput" placeholder="Enter your workspace API key (slm_...)" />
  <button class="btn btn-primary btn-sm" onclick="connect()">Connect</button>
</div>

<div class="container" id="main" style="display:none">

  <!-- Overview -->
  <div class="grid">
    <div class="card"><h3>Anonymizations</h3><div class="value" id="statCount">0</div><div class="sub" id="statLast">never</div></div>
    <div class="card"><h3>PPI Terms</h3><div class="value" id="statPPI">0</div></div>
    <div class="card"><h3>API Keys</h3><div class="value" id="statKeys">1</div></div>
    <div class="card"><h3>LLM</h3><div class="value" id="statLLM" style="font-size:16px">—</div></div>
  </div>

  <!-- PPI Terms -->
  <div class="section">
    <div class="section-header">
      <h2>PPI Terms</h2>
      <div style="display:flex;gap:8px">
        <button class="btn btn-ghost btn-sm" onclick="toggleBulkEdit()">Bulk Edit</button>
      </div>
    </div>
    <div class="section-body">
      <div class="form-row" style="margin-bottom:16px">
        <div class="form-group" style="flex:3"><input id="newTerm" placeholder="Add a proprietary term..." /></div>
        <button class="btn btn-primary btn-sm" onclick="addTerm()" style="align-self:flex-end;height:36px">Add</button>
      </div>
      <div id="termsDisplay"></div>
      <div id="bulkEdit" style="display:none">
        <textarea id="bulkTerms" style="width:100%;min-height:200px" placeholder="One term per line..."></textarea>
        <div style="margin-top:8px;display:flex;gap:8px">
          <button class="btn btn-primary btn-sm" onclick="saveBulk()">Save</button>
          <button class="btn btn-ghost btn-sm" onclick="toggleBulkEdit()">Cancel</button>
        </div>
      </div>
    </div>
  </div>

  <!-- API Keys -->
  <div class="section">
    <div class="section-header">
      <h2>API Keys</h2>
      <button class="btn btn-primary btn-sm" onclick="openModal('keyModal')">+ New Key</button>
    </div>
    <div class="section-body" id="keysBody"></div>
  </div>

  <!-- LLM Config (read-only) -->
  <div class="section">
    <div class="section-header"><h2>LLM Configuration</h2></div>
    <div class="section-body" id="llmBody">
      <p style="color:var(--text2)">Loading...</p>
    </div>
  </div>

  <!-- Live Test -->
  <div class="section">
    <div class="section-header"><h2>Live Anonymization Test</h2></div>
    <div class="section-body">
      <div class="form-row">
        <div class="form-group">
          <label>Input Text</label>
          <textarea id="testInput" placeholder="John Smith from ALE deployed OmniSwitch 6900. Email: john@acme.com"></textarea>
        </div>
      </div>
      <button class="btn btn-primary" onclick="runTest()">Anonymize</button>
      <div id="testOutput" class="test-result" style="display:none"></div>
    </div>
  </div>
</div>

<!-- Create Key Modal -->
<div class="modal-overlay" id="keyModal">
  <div class="modal">
    <div class="modal-header">
      <h2>Create API Key</h2>
      <button class="modal-close" onclick="closeModal('keyModal')">&times;</button>
    </div>
    <div class="modal-body">
      <div class="form-group"><label>Label</label><input id="keyLabel" placeholder="e.g. production, staging, ci-pipeline" /></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="closeModal('keyModal')">Cancel</button>
      <button class="btn btn-primary" onclick="createKey()">Create</button>
    </div>
  </div>
</div>

<!-- Key Created Modal -->
<div class="modal-overlay" id="keyCreatedModal">
  <div class="modal">
    <div class="modal-header"><h2>Key Created</h2><button class="modal-close" onclick="closeModal('keyCreatedModal')">&times;</button></div>
    <div class="modal-body">
      <p style="margin-bottom:12px;color:var(--text2);font-size:14px">Save this key — it won't be shown again.</p>
      <div style="display:flex;align-items:center;gap:8px;background:var(--bg);padding:12px;border-radius:6px;border:1px solid var(--border)">
        <code id="createdKeyValue" class="mono" style="flex:1;word-break:break-all"></code>
        <button style="background:none;border:none;color:var(--text2);cursor:pointer" onclick="navigator.clipboard.writeText(document.getElementById('createdKeyValue').textContent);toast('Copied!','success')">copy</button>
      </div>
    </div>
    <div class="modal-footer"><button class="btn btn-primary" onclick="closeModal('keyCreatedModal')">Done</button></div>
  </div>
</div>

<script>
const B = window.location.origin;
let apiKey = '';
let ppiTerms = [];
let bulkMode = false;

function hdr() { return { 'X-API-Key': apiKey, 'Content-Type': 'application/json' }; }
function toast(m, t='') { const e=document.createElement('div'); e.className='toast '+t; e.textContent=m; document.body.appendChild(e); setTimeout(()=>e.remove(),3000); }
function openModal(id) { document.getElementById(id).classList.add('active'); }
function closeModal(id) { document.getElementById(id).classList.remove('active'); }
function esc(s) { const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }

async function connect() {
  apiKey = document.getElementById('apiKeyInput').value.trim();
  if (!apiKey) return toast('Enter your API key','error');
  try {
    const r = await fetch(B+'/portal/api/workspace', {headers:hdr()});
    if (!r.ok) return toast('Invalid API key','error');
    document.getElementById('main').style.display='block';
    await loadAll();
    toast('Connected','success');
  } catch(e) { toast('Error: '+e.message,'error'); }
}

async function loadAll() {
  await Promise.all([loadWorkspace(), loadPPI(), loadKeys(), loadLLM()]);
}

async function loadWorkspace() {
  const r = await fetch(B+'/portal/api/workspace', {headers:hdr()});
  const ws = await r.json();
  document.getElementById('wsName').textContent = ws.name;
  document.getElementById('statCount').textContent = ws.stats.anon_count;
  document.getElementById('statLast').textContent = ws.stats.last_used ? new Date(ws.stats.last_used).toLocaleString() : 'never';
  document.getElementById('statPPI').textContent = ws.ppi_term_count;
  if (ws.llm && ws.llm.configured) {
    document.getElementById('statLLM').innerHTML = '<span class="badge badge-green">'+esc(ws.llm.provider)+'</span>';
  } else {
    document.getElementById('statLLM').innerHTML = '<span class="badge badge-orange">none</span>';
  }
}

// PPI Terms
async function loadPPI() {
  const r = await fetch(B+'/portal/api/ppi-terms', {headers:hdr()});
  const d = await r.json();
  ppiTerms = d.terms;
  renderTerms();
}

function renderTerms() {
  const el = document.getElementById('termsDisplay');
  if (ppiTerms.length === 0) { el.innerHTML='<p style="color:var(--text2)">No custom terms. Add proprietary terms that should be anonymized.</p>'; return; }
  el.innerHTML = ppiTerms.map(t => `<span class="tag">${esc(t)}<button onclick="deleteTerm('${esc(t)}')">&times;</button></span>`).join('');
  document.getElementById('statPPI').textContent = ppiTerms.length;
}

async function addTerm() {
  const inp = document.getElementById('newTerm');
  const term = inp.value.trim();
  if (!term) return;
  if (ppiTerms.includes(term)) return toast('Term already exists','error');
  ppiTerms.push(term);
  await savePPI();
  inp.value = '';
}

async function deleteTerm(term) {
  ppiTerms = ppiTerms.filter(t => t !== term);
  await savePPI();
}

async function savePPI() {
  await fetch(B+'/portal/api/ppi-terms', {method:'PUT', headers:hdr(), body:JSON.stringify({terms:ppiTerms})});
  renderTerms();
}

function toggleBulkEdit() {
  bulkMode = !bulkMode;
  document.getElementById('bulkEdit').style.display = bulkMode ? 'block' : 'none';
  document.getElementById('termsDisplay').style.display = bulkMode ? 'none' : 'block';
  if (bulkMode) document.getElementById('bulkTerms').value = ppiTerms.join('\n');
}

async function saveBulk() {
  ppiTerms = document.getElementById('bulkTerms').value.split('\n').map(s=>s.trim()).filter(Boolean);
  await savePPI();
  toggleBulkEdit();
  toast('Terms saved','success');
}

document.getElementById('newTerm').addEventListener('keydown', e => { if(e.key==='Enter') addTerm(); });

// API Keys
async function loadKeys() {
  const r = await fetch(B+'/portal/api/keys', {headers:hdr()});
  const keys = await r.json();
  document.getElementById('statKeys').textContent = keys.length + 1; // +1 for primary
  const el = document.getElementById('keysBody');
  if (keys.length === 0) { el.innerHTML='<p style="color:var(--text2)">No additional keys. Your primary key is in use. Create sub-keys for different environments.</p>'; return; }
  let html = '<table><thead><tr><th>Label</th><th>Key Prefix</th><th>Created</th><th>Actions</th></tr></thead><tbody>';
  keys.forEach(k => {
    html += `<tr><td>${esc(k.label)}</td><td><span class="mono">${esc(k.prefix)}</span></td><td>${new Date(k.created_at).toLocaleDateString()}</td><td><button class="btn btn-danger btn-sm" onclick="revokeKey('${esc(k.prefix.replace('...','')).replace(/'/g,"\\'")}')">Revoke</button></td></tr>`;
  });
  html += '</tbody></table>';
  el.innerHTML = html;
}

async function createKey() {
  const label = document.getElementById('keyLabel').value.trim();
  if (!label) return toast('Label required','error');
  const r = await fetch(B+'/portal/api/keys', {method:'POST', headers:hdr(), body:JSON.stringify({label})});
  const d = await r.json();
  if (!r.ok) return toast(d.detail||'Error','error');
  closeModal('keyModal');
  document.getElementById('createdKeyValue').textContent = d.api_key;
  openModal('keyCreatedModal');
  document.getElementById('keyLabel').value = '';
  await loadKeys();
}

async function revokeKey(prefix) {
  if (!confirm('Revoke this key? Any client using it will lose access.')) return;
  await fetch(B+'/portal/api/keys/'+encodeURIComponent(prefix), {method:'DELETE', headers:hdr()});
  await loadKeys();
  toast('Key revoked','success');
}

// LLM Config
async function loadLLM() {
  const r = await fetch(B+'/portal/api/llm', {headers:hdr()});
  const d = await r.json();
  const el = document.getElementById('llmBody');
  if (!d.configured) {
    el.innerHTML = '<p style="color:var(--text2)">No LLM configured. Contact your administrator to set up an LLM provider.</p>';
    return;
  }
  el.innerHTML = `
    <div class="info-row"><span class="info-label">Provider</span><span>${esc(d.provider)}</span></div>
    <div class="info-row"><span class="info-label">Upstream URL</span><span class="mono">${esc(d.upstream_url)}</span></div>
    <div class="info-row"><span class="info-label">Default Model</span><span class="mono">${esc(d.default_model||'—')}</span></div>
    <div class="info-row"><span class="info-label">Status</span><span class="badge badge-green">configured</span></div>
    <p style="color:var(--text2);font-size:12px;margin-top:12px">Contact your administrator to change LLM configuration.</p>
  `;
}

// Live Test
async function runTest() {
  const text = document.getElementById('testInput').value.trim();
  if (!text) return toast('Enter text','error');
  const out = document.getElementById('testOutput');
  out.style.display='block';
  out.innerHTML='<span style="color:var(--text2)">Anonymizing...</span>';
  try {
    const r = await fetch(B+'/portal/api/test/anonymize', {method:'POST', headers:hdr(), body:JSON.stringify({text})});
    const d = await r.json();
    if (!r.ok) { out.innerHTML='<span style="color:var(--red)">'+esc(d.detail||'Error')+'</span>'; return; }
    let h = esc(d.anonymized_text)
      .replace(/\[PRODUCT_\d+\]/g, '<span class="placeholder-ppi">$&</span>')
      .replace(/&lt;[A-Z_]+_\d+&gt;/g, '<span class="placeholder-pii">$&</span>');
    out.innerHTML = `<div style="margin-bottom:8px"><strong>Anonymized:</strong></div>${h}<div style="margin-top:12px;font-size:12px;color:var(--text2)">Mapping ID: <span class="mono">${esc(d.mapping_id)}</span></div>`;
    await loadWorkspace(); // refresh stats
  } catch(e) { out.innerHTML='<span style="color:var(--red)">'+esc(e.message)+'</span>'; }
}

document.getElementById('apiKeyInput').addEventListener('keydown', e => { if(e.key==='Enter') connect(); });
</script>
</body>
</html>
"""
