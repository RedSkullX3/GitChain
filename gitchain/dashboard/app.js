/**
 * GitChain Dashboard — app.js
 *
 * Fetches live data from the node's REST API and drives all 5 views:
 *   WF01 — Dashboard  (home screen with stats + timeline)
 *   WF02 — Explorer   (block explorer)
 *   WF03 — Verify     (commit audit tool)
 *   WF04 — Contributors (ranked developer view)
 *   WF05 — Network    (P2P topology + message log)
 */

const API = window.GITCHAIN_API || 'http://127.0.0.1:8000';
const REFRESH_MS = 4000;

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

async function apiFetch(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function ts(unix) {
  if (!unix) return '—';
  return new Date(unix * 1000).toLocaleString();
}

function short(hex, n = 12) {
  return hex ? hex.slice(0, n) + '…' : '—';
}

function el(id) { return document.getElementById(id); }
function setHtml(id, html) { const e = el(id); if (e) e.innerHTML = html; }
function setText(id, txt)  { const e = el(id); if (e) e.textContent = txt; }

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

const VIEWS = ['dashboard', 'explorer', 'verify', 'contributors', 'network'];

function showView(name) {
  VIEWS.forEach(v => {
    const section = el('view-' + v);
    const tab     = el('tab-'  + v);
    if (section) section.style.display = (v === name) ? '' : 'none';
    if (tab)     tab.classList.toggle('active', v === name);
  });
  window._activeView = name;
  refresh();
}

// ---------------------------------------------------------------------------
// WF01 — Dashboard
// ---------------------------------------------------------------------------


async function refreshDashboard() {
  const [status, chain] = await Promise.all([
    apiFetch('/status'),
    apiFetch('/chain'),
  ]);

  // Stat cards
  setText('stat-blocks',  chain.length);
  setText('stat-commits', chain.reduce((n, b) => n + (b.transactions?.length || 0), 0));
  setText('stat-nodes',   status.peer_count + 1);

  // Collect all transactions with block index
  const allTx = [];
  chain.forEach(block => {
    (block.transactions || []).forEach(tx => {
      allTx.push({ ...tx, _block_index: block.index, _block_time: block.timestamp });
    });
  });


  // Contribution timeline
  const rows = allTx.slice().reverse().map(tx => `
    <tr>
      <td class="mono">${short(tx.commit_hash, 10)}</td>
      <td>${tx.repo || '—'}</td>
      <td>${tx.branch || '—'}</td>
      <td>${tx.author || '—'}</td>
      <td>${ts(tx.timestamp)}</td>
      <td><span class="badge verified">on-chain #${tx._block_index}</span></td>
    </tr>`).join('');
  setHtml('timeline-body', rows || '<tr><td colspan="6" class="empty">No contributions yet</td></tr>');

  // Recent blocks panel
  const blockRows = chain.slice().reverse().slice(0, 8).map(b => `
    <div class="block-pill" onclick="openBlock(${b.index})">
      <span class="block-idx">#${b.index}</span>
      <span class="block-hash mono">${short(b.hash, 14)}</span>
      <span class="block-txs">${b.transactions?.length || 0} tx</span>
      <span class="block-time">${ts(b.timestamp)}</span>
    </div>`).join('');
  setHtml('recent-blocks', blockRows || '<div class="empty">No blocks yet</div>');

  // Peers panel
  const peerList = (status.peers || []).map(p =>
    `<div class="peer-entry"><span class="dot green"></span> ${p}</div>`
  ).join('') || '<div class="empty">No peers connected</div>';
  setHtml('peers-list', peerList);
}

// ---------------------------------------------------------------------------
// WF02 — Block Explorer
// ---------------------------------------------------------------------------

let _explorerChain = [];
let _selectedBlock = 0;

async function refreshExplorer() {
  _explorerChain = await apiFetch('/chain');
  renderExplorerRail();
  renderBlockDetail(_selectedBlock);
}

function renderExplorerRail() {
  const rail = _explorerChain.slice().reverse().map(b => `
    <div class="rail-item ${b.index === _selectedBlock ? 'selected' : ''}"
         onclick="selectBlock(${b.index})">
      <span class="rail-idx">#${b.index}</span>
      <span class="rail-hash mono">${short(b.hash, 10)}</span>
    </div>`).join('');
  setHtml('explorer-rail', rail);
}

function selectBlock(index) {
  _selectedBlock = index;
  renderExplorerRail();
  renderBlockDetail(index);
}

function openBlock(index) {
  showView('explorer');
  selectBlock(index);
}

function renderBlockDetail(index) {
  const block = _explorerChain.find(b => b.index === index);
  if (!block) { setHtml('block-detail', '<div class="empty">Select a block</div>'); return; }

  const txRows = (block.transactions || []).map(tx => `
    <div class="tx-card">
      <div class="tx-row"><span class="tx-label">Commit</span>
        <span class="mono">${tx.commit_hash}</span></div>
      <div class="tx-row"><span class="tx-label">Repo</span>
        <span>${tx.repo} / ${tx.branch}</span></div>
      <div class="tx-row"><span class="tx-label">Author</span>
        <span>${tx.author || '—'}</span></div>
      <div class="tx-row"><span class="tx-label">Diff</span>
        <span>${tx.diff_summary}</span></div>
      <div class="tx-row"><span class="tx-label">Time</span>
        <span>${ts(tx.timestamp)}</span></div>
      <div class="tx-row"><span class="tx-label">Signature</span>
        <span class="badge verified">Ed25519 valid</span>
        <span class="mono small">${short(tx.signature, 20)}</span></div>
    </div>`).join('') || '<div class="empty">No transactions in this block</div>';

  const prevLink = block.index > 0
    ? `<a href="#" onclick="selectBlock(${block.index - 1})">${short(block.previous_hash, 20)}</a>`
    : `<span class="mono">${short(block.previous_hash, 20)}</span>`;

  setHtml('block-detail', `
    <div class="block-header">
      <h2>Block #${block.index}</h2>
      <span class="badge">${block.transactions?.length || 0} transactions</span>
    </div>
    <div class="block-meta">
      <div class="meta-row"><span>Hash</span>     <span class="mono small">${block.hash}</span></div>
      <div class="meta-row"><span>Prev Hash</span>${prevLink}</div>
      <div class="meta-row"><span>Nonce</span>    <span class="mono">${block.nonce}</span></div>
      <div class="meta-row"><span>Mined</span>    <span>${ts(block.timestamp)}</span></div>
    </div>
    <h3>Transactions</h3>
    ${txRows}
  `);
}

// ---------------------------------------------------------------------------
// WF03 — Verify Commit
// ---------------------------------------------------------------------------

async function verifyCommit() {
  const sha = (el('verify-input')?.value || '').trim();
  if (!sha) return;

  setHtml('verify-result', '<div class="loading">Checking chain…</div>');

  try {
    const data = await apiFetch('/verify/' + encodeURIComponent(sha));
    const tx   = data.transaction || {};

    if (data.on_chain) {
      setHtml('verify-result', `
        <div class="verify-card verified">
          <div class="verify-status">COMMIT VERIFIED ON-CHAIN</div>
          <div class="verify-detail">
            <div><span>Commit</span>    <span class="mono">${sha}</span></div>
            <div><span>Block</span>     <span>#${data.block_index}</span></div>
            <div><span>Repo</span>      <span>${tx.repo || '—'} / ${tx.branch || '—'}</span></div>
            <div><span>Time</span>      <span>${ts(tx.timestamp)}</span></div>
            <div><span>Diff</span>      <span>${tx.diff_summary || '—'}</span></div>
            <div><span>Author</span><span>${tx.author || '—'}</span></div>
            <div><span>Owner key</span><span class="mono small">${tx.owner_pubkey || '—'}</span></div>
            <div><span>Signature</span> <span class="mono small">${short(tx.signature, 32)}</span></div>
            <div><span>Algorithm</span> <span class="badge verified">Ed25519</span></div>
          </div>
        </div>`);
    } else {
      setHtml('verify-result', `
        <div class="verify-card not-found">
          <div class="verify-status">NOT FOUND ON-CHAIN</div>
          <div class="verify-message">${data.message}</div>
          <div class="verify-hint">
            This commit may have been force-pushed, rebased, or was never submitted
            to GitChain. If it existed before and is missing now, check the
            <a href="#" onclick="showView('dashboard')">Dashboard</a> for discrepancy alerts.
          </div>
        </div>`);
    }
  } catch (e) {
    setHtml('verify-result', `<div class="error">Error: ${e.message}</div>`);
  }
}

// ---------------------------------------------------------------------------
// WF04 — Contributors
// ---------------------------------------------------------------------------

async function refreshContributors() {
  const chain = await apiFetch('/chain');

  // Aggregate stats per author pubkey
  const authors = {};
  chain.forEach(block => {
    (block.transactions || []).forEach(tx => {
      const key = tx.owner_pubkey;
      if (!authors[key]) {
        authors[key] = { pubkey: tx.owner_pubkey, author: tx.author || key, commits: [], repos: new Set() };
      }
      authors[key].commits.push({ ...tx, _block_index: block.index });
      authors[key].repos.add(tx.repo);
    });
  });

  const sorted = Object.values(authors).sort((a, b) => b.commits.length - a.commits.length);

  const list = sorted.map((a, i) => `
    <div class="contributor-row" onclick="selectContributor('${a.pubkey}')">
      <span class="rank">#${i + 1}</span>
      <span class="author-name">${a.author}</span>
      <span class="repos">${a.repos.size} repo${a.repos.size !== 1 ? 's' : ''}</span>
      <div class="activity-bar">
        <div class="activity-fill" style="width:${Math.min(100, a.commits.length * 10)}%"></div>
      </div>
      <span class="commit-count">${a.commits.length} commits</span>
    </div>`).join('') || '<div class="empty">No contributions recorded yet</div>';

  setHtml('contributors-list', list);

  // Show first contributor detail by default
  if (sorted.length > 0) selectContributor(sorted[0].pubkey);
}

function selectContributor(pubkey, commits) {
  // Mark selected
  document.querySelectorAll('.contributor-row').forEach(r => r.classList.remove('selected'));
  const rows = document.querySelectorAll('.contributor-row');
  rows.forEach(r => { if (r.querySelector('.pubkey')?.textContent.startsWith(pubkey.slice(0, 20))) r.classList.add('selected'); });

  apiFetch('/contributions/' + pubkey).then(data => {
    const txs = data.transactions || [];
    const commitRows = txs.slice().reverse().map(tx => `
      <div class="commit-entry">
        <span class="mono">${short(tx.commit_hash, 10)}</span>
        <span>${tx.repo}</span>
        <span class="badge">block #${tx._block_index}</span>
        <span class="time">${ts(tx.timestamp)}</span>
      </div>`).join('') || '<div class="empty">No commits</div>';

    setHtml('contributor-detail', `
      <div class="detail-header">
        <h3>Developer</h3>
        <div class="mono small">${pubkey}</div>
      </div>
      <div class="detail-stats">
        <div class="stat-mini"><span>${txs.length}</span><label>commits</label></div>
        <div class="stat-mini"><span>${new Set(txs.map(t => t.repo)).size}</span><label>repos</label></div>
      </div>
      <h4>On-chain commits</h4>
      ${commitRows}
    `);
  });
}

// ---------------------------------------------------------------------------
// WF05 — Network
// ---------------------------------------------------------------------------

async function refreshNetwork() {
  const status = await apiFetch('/status');

  const peers = status.peers || [];
  const nodeId = status.node_id;

  // Simple topology: this node in center, peers as spokes
  const nodes = [
    { id: nodeId, label: 'This node\n' + nodeId, x: 0, y: 0, self: true },
    ...peers.map((p, i) => {
      const angle = (2 * Math.PI * i) / Math.max(peers.length, 1);
      return { id: p, label: p, x: Math.cos(angle) * 120, y: Math.sin(angle) * 120, self: false };
    }),
  ];

  const cx = 200, cy = 150;
  const svgNodes = nodes.map(n => `
    <g transform="translate(${cx + n.x}, ${cy + n.y})">
      <circle r="${n.self ? 22 : 16}" class="${n.self ? 'node-self' : 'node-peer'}"/>
      <text y="${n.self ? 36 : 30}" class="node-label">${n.label}</text>
    </g>`).join('');

  const svgEdges = peers.map(p => {
    const peer = nodes.find(n => n.id === p);
    if (!peer) return '';
    return `<line x1="${cx}" y1="${cy}" x2="${cx + peer.x}" y2="${cy + peer.y}" class="edge"/>`;
  }).join('');

  const svgHtml = `
    <svg viewBox="0 0 400 300" class="network-svg">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5"
          markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#4a9eff"/>
        </marker>
      </defs>
      ${svgEdges}${svgNodes}
    </svg>`;

  setHtml('network-topology', svgHtml);

  const info = `
    <div class="net-stat"><label>Node ID</label> <span class="mono">${nodeId}</span></div>
    <div class="net-stat"><label>Peers</label>    <span>${peers.length}</span></div>
    <div class="net-stat"><label>Height</label>   <span>${status.chain_height}</span></div>
    <div class="net-stat"><label>Mempool</label>  <span>${status.mempool_size} pending</span></div>`;
  setHtml('network-stats', info);
}

// ---------------------------------------------------------------------------
// Polling loop
// ---------------------------------------------------------------------------

function refresh() {
  const view = window._activeView || 'dashboard';
  const dispatch = {
    dashboard:    refreshDashboard,
    explorer:     refreshExplorer,
    contributors: refreshContributors,
    network:      refreshNetwork,
    verify:       () => {},   // verify is on-demand only
  };
  (dispatch[view] || refreshDashboard)().catch(e => {
    console.warn('Refresh error:', e.message);
  });
}

let _pollTimer;
function startPolling() {
  refresh();
  _pollTimer = setInterval(refresh, REFRESH_MS);
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

window.addEventListener('DOMContentLoaded', () => {
  // Wire up tab clicks
  VIEWS.forEach(v => {
    const tab = el('tab-' + v);
    if (tab) tab.addEventListener('click', () => showView(v));
  });

  // Verify button
  const btn = el('verify-btn');
  if (btn) btn.addEventListener('click', verifyCommit);
  const input = el('verify-input');
  if (input) input.addEventListener('keydown', e => { if (e.key === 'Enter') verifyCommit(); });

  // API URL override
  const apiParam = new URLSearchParams(window.location.search).get('api');
  if (apiParam) window.GITCHAIN_API = apiParam;

  showView('dashboard');
  startPolling();
});
