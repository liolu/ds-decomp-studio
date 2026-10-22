"use strict";
const $ = (s, e = document) => e.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const fmt = n => Number(n || 0).toLocaleString("fr-FR");
const hex = n => "0x" + Number(n).toString(16).padStart(8, "0");
const ago = t => { if (!t) return ""; const s = Date.now() / 1000 - t; return s < 90 ? "a l'instant" : s < 5400 ? Math.round(s / 60) + " min" : s < 172800 ? Math.round(s / 3600) + " h" : Math.round(s / 86400) + " j"; };
const TABS = [["games", "Jeux"], ["game", "Travailler"], ["queue", "Queue"], ["engine", "Engine map"], ["progress", "Progression"], ["settings", "Reglages"]];
const ST = {free: "libre", claimed: "pris", expired: "expire", done: "termine", queued: "en attente", running: "en cours",
  failed: "echec", stopped: "arrete", interrupted: "interrompu", cancelled: "annule"};
let O = null, G = null, J = [], tab = location.hash.slice(1) || "games", sub = "blocks";
let fLevel = null, fState = "open", fnLevel = "", fnQuery = "", fnState = "todo", fnKind = "", openLog = null;
let dState = "todo", dSection = "", dModule = "", dQuery = "";
let gSort = (() => { try { return JSON.parse(localStorage.getItem("gSort")) || ["pct", -1]; } catch (e) { return ["pct", -1]; } })();
const G_SORTS = {title: g => g.title.toLowerCase(), studio: g => (g.studio || "~").toLowerCase(), rom: g => g.rom.ok ? 0 : 1,
  functions: g => g.functions, matched: g => g.matched, pct: g => g.pct_code, left: g => g.functions - g.matched, github: g => g.remote ? 0 : 1};
const ASC_FIRST = ["title", "studio", "rom", "github"];
function setSort(k, dir) {
  gSort = [k, dir || (gSort[0] === k ? -gSort[1] : ASC_FIRST.includes(k) ? 1 : -1)];
  try { localStorage.setItem("gSort", JSON.stringify(gSort)); } catch (e) {}
  render();
}
const th = (k, label, cls = "") => `<th class="sort ${cls} ${gSort[0] === k ? "on" : ""}" onclick="setSort('${k}')">${label}${gSort[0] === k ? (gSort[1] > 0 ? " &#9650;" : " &#9660;") : ""}</th>`;

async function api(path, body) {
  try {
    const r = await fetch("/api/" + path, body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const d = await r.json();
    if (d && d.error) toast(d.error, true);
    if (d && d.warning) toast(d.warning, true);
    return d;
  } catch (e) { toast("Serveur injoignable : " + e, true); return {error: String(e)}; }
}
function toast(msg, err) {
  const t = document.createElement("div"); t.className = "toast" + (err ? " err" : ""); t.textContent = msg;
  $("#toasts").appendChild(t); setTimeout(() => t.remove(), err ? 9000 : 4500);
}
function modal(html) { $("#modalbody").innerHTML = html; $("#modal").classList.add("on"); }
$("#modal").onclick = e => { if (e.target.id === "modal") $("#modal").classList.remove("on"); };
const closeModal = () => $("#modal").classList.remove("on");
const LV = n => O.levels[n] || {label: "?"};
const JD = k => (O.jobdefs && O.jobdefs[k]) || {label: k, desc: "(redemarre le studio pour cette tache)"};
const portNote = p => p.game.startsWith("donor:") ? "decomp externe " + esc(p.game.slice(6)) + " (" + esc(p.name) + ")" : p.game.startsWith("clone:") ? "clone de " + esc(p.name) + " (meme code dans ce jeu)" : "copier depuis " + esc(p.game);
const game = () => O && O.settings.active_game;
const pctBar = p => `<div class="pct"><div class="bar"><i style="width:${Math.min(p, 100)}%"></i></div><b>${p.toFixed(2)}%</b></div>`;

function tabs() {
  $("#tabs").innerHTML = TABS.map(([k, l]) => `<button class="${k === tab ? "on" : ""}" onclick="go('${k}')">${l}</button>`).join("");
}
function go(t) { tab = t; location.hash = t; tabs(); render(); }

// fresh: after an action that adds or removes a game (else the server answers from its background-refreshed list)
async function loadOverview(fresh) { const o = await api("overview" + (fresh ? "?fresh=1" : "")); if (o && !o.error) O = o; }
async function loadXP() {
  const x = await api("xp"); if (!x || x.error) return;
  $("#lvl").textContent = x.level; $("#rank").textContent = x.rank;
  $("#xptxt").textContent = `${fmt(x.xp_in_level)} / ${fmt(x.xp_needed)} XP`;
  $("#xpbar").style.width = (100 * x.xp_in_level / x.xp_needed) + "%";
  window.XP = x;
}
async function selectGame(id) {
  await api("settings", {active_game: id}); O.settings.active_game = id; G = null; fLevel = null; go("game");
}

async function render() {
  if (!O) return;
  const v = $("#view");
  try {
    if (tab === "games") v.innerHTML = viewGames();
    else if (tab === "game") { v.innerHTML = await viewGame(); afterGame(); }
    else if (tab === "queue") v.innerHTML = await viewQueue();
    else if (tab === "engine") v.innerHTML = await viewEngine();
    else if (tab === "progress") v.innerHTML = viewProgress();
    else if (tab === "settings") v.innerHTML = viewSettings();
  } catch (e) { v.innerHTML = `<div class="card">Erreur d'affichage : ${esc(e)}</div>`; console.error(e); }
}

// ---------------- Jeux ----------------
function viewGames() {
  const gs = O.games, tot = gs.reduce((a, g) => a + g.functions, 0), got = gs.reduce((a, g) => a + g.matched, 0);
  const live = O.queue.filter(c => !c.expired).length;
  let h = `<div class="kpis"><div class="kpi"><b>${gs.length}</b><span>jeux</span></div>
    <div class="kpi"><b>${fmt(got)}</b><span>fonctions matchees / ${fmt(tot)}</span></div>
    <div class="kpi"><b>${gs.filter(g => g.remote).length}</b><span>sur GitHub</span></div>
    <div class="kpi"><b>${live}</b><span>blocs en cours</span></div></div>`;
  const behind = gs.filter(g => g.tools_behind && g.tools_behind.length).length;
  h += `<div class="card"><h3>Mes jeux</h3><p class="hint">Clique sur un jeu pour travailler dessus. "Retirer" le range dans projets/_archive (rien n'est supprime).</p>
  <div class="btns" style="margin-bottom:8px"><button class="btn small" title="${esc(JD('progress').desc)}" onclick="api('run',{id:'progress'}).then(r=>r.n&&toast('Publication de l'avancement lancee (onglet Queue)'))">Publier l'avancement sur GitHub</button>
    <span class="hint">README de chaque jeu publie + tableau de tous les jeux dans ds-decomp-studio</span></div>
  ${behind ? `<div class="btns" style="margin-bottom:8px"><span class="tag ko">${behind} jeux ont des outils en retard sur rayman-rr (auto_match...)</span>
    <button class="btn small" onclick="api('run',{id:'sync_all'}).then(r=>r.n&&toast('Mise a jour des outils lancee (onglet Queue)'))">Tout mettre a jour</button></div>` : ""}
  <div class="btns" style="margin-bottom:8px"><span class="hint">Trier par</span>
    <select onchange="setSort(this.value, ASC_FIRST.includes(this.value) ? 1 : -1)">${[["pct", "% de code matche"], ["matched", "fonctions matchees"], ["left", "fonctions restantes"], ["functions", "taille (fonctions)"], ["title", "nom"], ["studio", "studio"], ["rom", "etat ROM"], ["github", "GitHub"]].map(([k, l]) => `<option value="${k}" ${gSort[0] === k ? "selected" : ""}>${l}</option>`).join("")}</select>
    <button class="btn small sec" onclick="setSort(gSort[0], -gSort[1])">${gSort[1] > 0 ? "croissant &#9650;" : "decroissant &#9660;"}</button></div>
  <table><tr>${th("title", "Jeu")}${th("studio", "Studio")}${th("rom", "Etat ROM")}${th("matched", "Fonctions", "num")}${th("pct", "Code matche")}${th("github", "GitHub")}<th></th></tr>`;
  const key = G_SORTS[gSort[0]] || G_SORTS.pct;
  const order = (a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * gSort[1] || a.title.localeCompare(b.title); };
  for (const g of [...gs].sort(order)) {
    h += `<tr class="click" onclick="selectGame('${g.id}')"><td><b>${esc(g.title)}</b> ${g.id === game() ? '<span class="tag ok">actif</span>' : ""}<div class="hint">${esc(g.id)} &middot; ${esc(g.code)} ${esc(g.version || "")}</div></td>
      <td class="hint">${esc(g.studio)}</td>
      <td>${g.rom.ok ? '<span class="tag ok">ROM OK</span>' : `<span class="tag ko" title="${esc(g.rom.note)}">${esc(g.rom.note || "KO")}</span>`}</td>
      <td class="num">${fmt(g.matched)} / ${fmt(g.functions)}${g.modules > 1 ? `<div class="hint">${g.modules} modules</div>` : ""}</td><td>${pctBar(g.pct_code)}${g.modules > 1 ? `<div class="hint">module principal : ${g.pct_main.toFixed(2)} %</div>` : ""}</td>
      <td>${g.remote ? `<a class="tag gh" href="${esc(g.remote.replace(/\.git$/, ""))}" target="_blank" onclick="event.stopPropagation()">GitHub</a>` : '<span class="hint">local</span>'}</td>
      <td onclick="event.stopPropagation()"><button class="btn small sec" onclick="archiveGame('${g.id}')">Retirer</button></td></tr>`;
  }
  h += `</table></div><div class="split"><div class="card"><h3>Ajouter un jeu (depuis une ROM)</h3>
    <p class="hint">Mets la ROM (.nds, dumpee de ta cartouche) dans <code>decomp ds/roms/</code>, puis clique sur Charger.</p>
    <button class="btn sec" onclick="loadRoms()">Charger les ROMs sans projet</button><div id="roms"></div></div>
    <div class="card"><h3>Prendre un jeu publie sur GitHub</h3>
    <p class="hint">Clone le repo d'un jeu (le tien ou celui d'un ami) dans projets/. Il faut ensuite la ROM.</p>
    <div class="btns"><input id="cloneurl" placeholder="https://github.com/proprietaire/jeu-decomp" style="flex:1;min-width:240px"><button class="btn" onclick="cloneGame()">Cloner</button></div>
    <button class="btn sec small" style="margin-top:8px" onclick="loadGithub()">Voir les jeux publies (topic ds-decomp-studio)</button><div id="ghlist"></div>
    ${O.archived.length ? `<h3 style="margin-top:14px">Archives</h3>` + O.archived.map(a => `<div class="btns" style="margin:4px 0"><span>${esc(a)}</span><button class="btn small sec" onclick="restoreGame('${esc(a)}')">Remettre</button></div>`).join("") : ""}
    </div></div>`;
  return h;
}
async function archiveGame(id) {
  if (!confirm(`Retirer ${id} du studio ? Le dossier est deplace dans projets/_archive (recuperable).`)) return;
  const r = await api("archive", {game: id}); if (r.ok) { toast("Jeu archive"); await loadOverview(true); render(); }
}
async function restoreGame(n) { const r = await api("restore", {name: n}); if (r.ok) { toast("Jeu remis"); await loadOverview(true); render(); } }
async function loadRoms() {
  $("#roms").innerHTML = '<p class="hint">Lecture des ROMs...</p>';
  const r = await api("roms");
  $("#roms").innerHTML = !r.roms || !r.roms.length ? '<p class="hint">Aucune ROM sans projet.</p>' :
    `<table>${r.roms.map(x => `<tr><td>${esc(x.rom)}<div class="hint">${esc(x.code)} &middot; ${x.mb} Mo</div></td><td><input value="${esc(x.slug)}" id="slug-${esc(x.code)}" size="18"></td>
      <td><button class="btn small" onclick="addGame('${esc(x.code)}', ${JSON.stringify(x.rom).replace(/"/g, "&quot;")})">Ajouter</button></td></tr>`).join("")}</table>`;
}
async function addGame(code, rom) {
  const slug = $("#slug-" + code).value.trim();
  const r = await api("run", {id: "new_project", params: {slug, rom}});
  if (r.n) toast(`Creation de ${slug} lancee (onglet Queue pour suivre)`);
}
async function cloneGame() {
  const r = await api("clone", {url: $("#cloneurl").value});
  if (r.ok) { toast(`${r.game} clone. ${r.next}`); await loadOverview(true); render(); }
}
async function loadGithub() {
  $("#ghlist").innerHTML = '<p class="hint">Recherche...</p>';
  const r = await api("github");
  $("#ghlist").innerHTML = (r.repos || []).map(x => `<div class="btns" style="margin:4px 0"><a href="${esc(x.url)}" target="_blank">${esc(x.fullName)}</a>
    <button class="btn small sec" onclick="$('#cloneurl').value='${esc(x.url)}'">choisir</button></div>`).join("") || '<p class="hint">Aucun repo trouve.</p>';
}

// ---------------- Travailler (jeu actif) ----------------
async function viewGame() {
  if (!game()) return `<div class="card empty">Choisis d'abord un jeu dans l'onglet <a href="#games" onclick="go('games')">Jeux</a>.</div>`;
  G = await api("game?id=" + encodeURIComponent(game()));
  if (G.error) return `<div class="card">${esc(G.error)}</div>`;
  const g = G.game, opts = O.games.map(x => `<option value="${x.id}" ${x.id === g.id ? "selected" : ""}>${esc(x.title)}</option>`).join("");
  let h = `<div class="card"><div class="btns" style="justify-content:space-between">
    <div><h2 style="margin:0"><select style="font-size:17px;font-weight:700" onchange="selectGame(this.value)">${opts}</select></h2>
    <span class="hint">${esc(g.id)} &middot; ${esc(g.code)} ${esc(g.version)} &middot; ${esc(g.studio)} &middot;
    ${g.rom.ok ? '<span class="tag ok">ROM OK</span>' : `<span class="tag ko">${esc(g.rom.note)}</span>`}
    ${g.remote ? `<a class="tag gh" target="_blank" href="${esc(g.remote.replace(/\.git$/, ""))}">GitHub</a>
      <a class="tag" target="_blank" title="Page ByteMatch du jeu. Pas encore listee ? Bouton ajouter : choisir le depot, le rapport est publie automatiquement par la CI (artefact ${esc(g.code || g.version)}_report, job Publier l'avancement)" href="https://bytematch.dev/${esc(g.remote.replace(/^.*github\.com[:/]/, "").replace(/\.git$/, ""))}">ByteMatch</a>
      <a class="tag" target="_blank" title="Ajouter ce depot sur ByteMatch (une fois) : la CI y publie le rapport a chaque avancement" href="https://bytematch.dev/manage/new">+ ByteMatch</a>` : '<span class="tag">local</span>'}</span></div>
    <div style="min-width:260px">${pctBar(g.pct_code)}<div class="hint" style="text-align:right">${fmt(g.matched)} / ${fmt(g.functions)} fonctions${g.modules > 1 ? ` (${g.modules} modules, principal ${g.pct_main.toFixed(2)} %)` : ""}</div>
    ${G.data && G.data.bytes ? `<div class="hint" style="text-align:right"><a href="#game" onclick="sub='data';render();return false">donnees ${G.data.pct.toFixed(2)} %</a> : ${fmt(G.data.matched)} / ${fmt(G.data.symbols)} symboles (.data, .rodata, .bss)</div>` : ""}
    ${g.left_manual ? `<div class="hint" style="text-align:right"><a href="#game" onclick="sub='functions';fnKind='manual';render();return false">${fmt(g.left_manual)} a faire a la main</a> (Thumb, overlays, ITCM : pas d'outil auto)</div>` : ""}</div></div>
    ${G.misses && (G.misses.misses || G.misses.won_here) ? `<div class="hint" style="margin-top:8px" title="base des essais rates (missdb.sqlite) : chaque C qui compile sans matcher (Qwen, hunt, Claude, editeur, auto-match) est rejoue sur les fonctions non matchees de tous les jeux">Essais rates gardes : <b>${fmt(G.misses.misses)}</b> (${fmt(G.misses.functions)} fonctions, ${fmt(G.misses.replayable)} rejouables) &middot; matchs gagnes ici grace aux essais rates : <b>${fmt(G.misses.won_here)}</b> &middot; donnes aux autres jeux : <b>${fmt(G.misses.given)}</b></div>` : ""}
    <h3 style="margin-top:12px">Taches machine sur ce jeu</h3><div class="btns">
    ${["moulinette", "auto", "ghidra", "wb_commit", "names", "regroup", "cleanup", "progress", "verify", "culprits", "build", "dis", "status", "permute", "misses"].map(k => `<button class="btn small ${k === "moulinette" ? "" : "sec"}" title="${esc(JD(k).desc)}" onclick="runJob('${k}')">${esc(JD(k).label)}</button>`).join("")}
    ${g.tools_behind && g.tools_behind.length ? `<button class="btn small" style="background:#b45309" title="${esc(g.tools_behind.join(", "))}" onclick="runJob('sync_tools',{})">Mettre a jour les outils (${g.tools_behind.length} en retard)</button>` : '<span class="tag ok">outils a jour</span>'}
    ${g.remote ? "" : `<button class="btn small green" onclick="publishGame()">Publier sur GitHub</button>`}
    </div></div>`;
  h += `<div class="levels">` + O.levels.map(l => {
    const p = G.per_level[l.n] || {blocks: 0, free: 0, claimed: 0, done: 0, left: 0};
    return `<div class="level L${l.n} ${fLevel === l.n ? "on" : ""}" onclick="setLevel(${l.n})"><b class="c${l.n}">${esc(l.label)}</b>
      <div class="n">${fmt(p.left)}</div><div class="hint">fonctions restantes &middot; ${p.free} blocs libres, ${p.claimed} pris</div>
      <div class="hint">${esc(l.hint)}</div></div>`;
  }).join("") + `</div>`;
  h += `<nav style="margin-bottom:12px">${[["blocks", "Blocs de 50"], ["functions", "Fonctions par difficulte"], ["data", "Donnees"], ["map", "Carte memoire"]].map(([k, l]) =>
    `<button class="${sub === k ? "on" : ""}" onclick="sub='${k}';render()">${l}</button>`).join("")}</nav><div id="sub"></div>`;
  return h;
}
function afterGame() { if (!G || G.error) return; if (sub === "blocks") subBlocks(); else if (sub === "functions") subFunctions(); else if (sub === "data") subData(); else subMap(); }
function setLevel(n) { fLevel = fLevel === n ? null : n; fnLevel = fLevel === null ? "" : String(fLevel); render(); }

function subBlocks() {
  const bl = G.blocks.filter(b => (fLevel === null || b.level === fLevel) &&
    (fState === "all" || (fState === "open" ? b.state !== "done" : fState === "mine" ? b.claim && b.claim.who === O.settings.who : b.state === fState)));
  let h = `<div class="card"><div class="btns" style="margin-bottom:10px">
    <select onchange="fState=this.value;subBlocks()">${[["open", "Non termines"], ["free", "Libres"], ["claimed", "Pris"], ["mine", "Les miens"], ["done", "Termines"], ["all", "Tous"]].map(([k, l]) => `<option value="${k}" ${fState === k ? "selected" : ""}>${l}</option>`).join("")}</select>
    <span class="hint">${bl.length} blocs ${fLevel !== null ? "niveau " + esc(LV(fLevel).label) : ""} &middot; generation ${G.generation}</span>
    <span style="flex:1"></span>
    <button class="btn" onclick="claimNext()">Prendre le prochain bloc ${fLevel !== null ? esc(LV(fLevel).label) : "le plus facile"}</button>
    <button class="btn sec" onclick="qwenDialog(null)">Agents Qwen sur plusieurs blocs</button>
    <button class="btn sec" title="les fonctions que Qwen a laissees a 1-3 instructions pres (build/qwen_auto/hard.json), avec le modele de la file difficile (Reglages)" onclick="runJob('qwen',{hard:true})">Qwen sur la file difficile</button>
    <button class="btn sec" onclick="rebuildBlocks()" title="Refait les blocs avec les fonctions restantes. Les blocs pris ne bougent pas.">Recalculer les blocs</button></div>
    <div class="blocks">`;
  for (const b of bl) {
    const c = b.claim, mine = c && c.who === O.settings.who;
    h += `<div class="block L${b.level} ${b.state}"><div class="top"><span class="id">${b.id}</span><span class="state ${b.state}">${ST[b.state]}</span></div>
      <div><b class="c${b.level}">${esc(LV(b.level).label)}</b> &middot; ${b.left}/${b.count} restantes &middot; ${fmt(b.left_bytes)} octets</div>
      <div class="bar"><i style="width:${100 * (b.count - b.left) / Math.max(b.count, 1)}%"></i></div>
      <div class="hint">${hex(b.addr[0])} - ${hex(b.addr[1])}</div>
      ${c ? `<div class="hint">${esc(c.who)} (${esc(O.kinds[c.kind] || c.kind)}) &middot; ${ago(c.touched)}${c.note ? " &middot; " + esc(c.note) : ""}</div>` : ""}
      <div class="btns">
        <button class="btn small sec" onclick="openBlock('${b.id}')">Voir / brief</button>
        ${b.level === 0 && b.left ? `<button class="btn small" title="Reprend les fonctions de ce bloc deja decompilees ailleurs : clones dans nos jeux puis decomps externes (compile + compare + verify)" onclick="runJob('donors',{block:'${b.id}'})">Reprendre</button>` : ""}
        ${b.state === "free" || b.state === "expired" ? `<button class="btn small" onclick="claimBlock('${b.id}','human')">Prendre</button>
          <button class="btn small sec" onclick="qwenBlock('${b.id}')" title="Qwen (Ollama local) travaille sur ce bloc">Qwen</button>` : ""}
        ${mine || (c && c.kind !== "human") ? `<button class="btn small green" onclick="releaseBlock('${b.id}',true)">Termine</button>
          <button class="btn small sec" onclick="releaseBlock('${b.id}',false)">Rendre</button>` : ""}
      </div></div>`;
  }
  $("#sub").innerHTML = h + `</div>${bl.length ? "" : '<div class="empty">Aucun bloc ici.</div>'}</div>`;
}
async function claimNext() {
  const r = await api("claim", {game: game(), block: "next", level: fLevel, kind: "human"});
  if (r.ok) { toast(`Bloc ${r.block} pris`); render(); openBlock(r.block); }
}
async function claimBlock(id, kind) { const r = await api("claim", {game: game(), block: id, kind}); if (r.ok) { toast(`Bloc ${id} pris`); render(); } }
async function releaseBlock(id, fin) {
  if (fin && !confirm(`Marquer ${id} comme termine ? (les fonctions non matchees retourneront dans un futur bloc au prochain recalcul)`)) return;
  const r = await api("release", {game: game(), block: id, finished: fin}); if (r.ok) { toast(fin ? "Bloc termine, bravo !" : "Bloc rendu a la queue"); render(); }
}
async function rebuildBlocks() {
  if (!confirm("Recalculer les blocs libres avec les fonctions restantes ?")) return;
  const r = await api("rebuild", {game: game()}); if (r.ok) { toast(`${r.blocks} blocs`); render(); }
}
function qwenBlock(id) { qwenDialog([id]); }
function qwenDialog(ids) {
  window.QWEN_IDS = ids;
  const s = O.settings, free = G.blocks.filter(b => (b.state === "free" || b.state === "expired") && (fLevel === null || b.level === fLevel)).length;
  modal(`<h2>Agents Qwen ${ids ? "sur " + esc(ids.join(", ")) : "sur plusieurs blocs"}</h2>
    <p class="hint">Chaque requete donne plusieurs essais : plusieurs versions par reponse, les petites fonctions par lots, et seulement les lignes a changer (SEARCH/REPLACE) pour les grosses. Les matches sont verifies par lots (verify complet) puis commites.
    Pour que les agents tournent vraiment en meme temps, Ollama doit etre lance avec <code>OLLAMA_NUM_PARALLEL</code> au moins egal au nombre d'agents (voir Reglages).</p>
    <table>${ids ? "" : `<tr><td>Niveau</td><td><select data-k="level"><option value="">le plus facile d'abord</option>${O.levels.map(l => `<option value="${l.n}" ${fLevel === l.n ? "selected" : ""}>${esc(l.label)}</option>`).join("")}</select></td></tr>
      ${optField(["count", `Nombre de blocs a donner a Qwen (${free} libres ici)`, "number", Math.min(4, Math.max(free, 1))])}`}
      ${optField(["agents", "Agents en parallele", "number", s.qwen_agents])}
      ${optField(["minutes", "Minutes max par fonction proche (2e passe ; la 1re passe rapide fait 1,5 min et s'arrete si plus de progres)", "number", s.qwen_minutes])}
      ${optField(["max", "Nombre max de fonctions (0 = toutes)", "number", 0])}
      ${optField(["batch", "Matches verifies ensemble", "number", 10])}
      ${optField(["variants", "Versions demandees par reponse (toutes compilees en parallele)", "number", s.qwen_variants])}
      ${optField(["group", "Petites fonctions (64 octets max) envoyees ensemble (1 = une par requete)", "number", s.qwen_group])}
      <tr><td>Modele</td><td><input data-k="model" value="${esc(s.qwen_model)}"></td></tr></table>
    <div class="btns" style="margin-top:12px"><button class="btn" onclick="launchQwen()">Lancer les agents</button>
    <button class="btn sec" onclick="closeModal()">Annuler</button></div>`);
}
async function launchQwen() {
  const o = readFields(); closeModal();
  if (o.level === "" || o.level === undefined) o.level = null; else o.level = +o.level;
  const r = await api("qwen_swarm", {game: game(), blocks: window.QWEN_IDS, ...o});
  if (r.n) toast(`Qwen : ${o.agents} agent(s) sur ${r.blocks.join(", ")} (onglet Queue)`);
  render();
}
async function openBlock(id) {
  modal('<p class="hint">Chargement...</p>');
  const d = await api(`block?game=${encodeURIComponent(game())}&id=${encodeURIComponent(id)}`);
  if (d.error) return closeModal();
  window.BRIEF = d.brief;
  modal(`<div class="btns" style="justify-content:space-between"><h2 style="margin:0">Bloc ${esc(id)}</h2>
    <div class="btns"><button class="btn small" onclick="navigator.clipboard.writeText(BRIEF);toast('Brief copie : colle-le a Claude ou a une autre IA')">Copier le brief pour une IA</button>
    <button class="btn small sec" onclick="closeModal()">Fermer</button></div></div>
    <table style="margin-top:10px"><tr><th>Fonction</th><th>Adresse</th><th class="num">Taille</th><th>Niveau</th><th>auto_match</th><th>Note</th></tr>
    ${d.functions.map(f => `<tr class="click" onclick="${f.mode === "arm" && (f.module || "main") === "main" ? "openEditor" : "showAsm"}('${esc(f.name)}')"><td>${f.done ? "&#10004; " : ""}<b>${esc(f.name)}</b></td><td class="hint">${hex(f.addr)}</td>
      <td class="num">${f.size}</td><td>${f.done ? '<span class="hint">matchee</span>' : `<span class="c${f.level}">${esc(LV(f.level).label)}</span>`}</td>
      <td class="hint">${esc(f.auto || "")}</td><td class="hint">${f.port ? portNote(f.port) + " " + esc(f.port.file) : f.shared >= 2 ? "SDK (" + f.shared + " jeux)" : ""}</td></tr>`).join("")}</table>
    <div id="asm"></div><h3 style="margin-top:14px">Brief (pour une personne ou une IA)</h3><pre>${esc(d.brief)}</pre>`);
}
async function showAsm(name) {
  const d = await api(`asm?game=${encodeURIComponent(game())}&name=${encodeURIComponent(name)}`);
  $("#asm").innerHTML = `<h3 style="margin-top:12px">${esc(name)}</h3><pre>${esc(d.asm)}</pre>`;
  $("#asm").scrollIntoView({behavior: "smooth"});
}

// ---- C editor: write the function, Ctrl+Enter compiles it with the game's compilers and shows the diff
const edKey = n => `ed:${game()}:${n}`;
async function openEditor(name) {
  modal('<p class="hint">Chargement...</p>');
  const d = await api(`wb/info?game=${encodeURIComponent(game())}&name=${encodeURIComponent(name)}`);
  if (d.error) return closeModal();
  window.ED = {name, info: d};
  const facts = [d.calls.length ? "appelle " + d.calls.slice(0, 6).join(", ") + (d.calls.length > 6 ? "..." : "") : "",
    d.data.length ? "donnees " + d.data.slice(0, 4).join(", ") : "", d.callers.length ? "appelee par " + d.callers.slice(0, 3).join(", ") : "",
    "compilateurs " + d.profiles.join(" / ")].filter(Boolean).join(" &middot; ");
  modal(`<div class="editor"><div class="btns" style="justify-content:space-between"><h2 style="margin:0">${esc(name)}
    <span class="hint">${esc(d.addr)} &middot; ${d.size} octets &middot; ${d.matched ? "deja matchee (" + esc(d.file) + ")" : "depart : " + esc(d.draft_from)}</span></h2>
    <div class="btns"><button class="btn small" onclick="edJudge()">Compiler (Ctrl+Entree)</button>
    <button class="btn small green" id="edsubmit" disabled onclick="edSubmit()" title="dans src/auto + delinks.txt, ROM reconstruite (garde si identique)">Integrer au jeu</button>
    <button class="btn small sec" onclick="edReset()">Revenir au depart</button>
    <button class="btn small sec" onclick="edShowAsm()">Assembleur</button>
    ${d.ghidra ? `<button class="btn small sec" onclick="$('#edout').textContent=ED.info.ghidra" title="la lecture de Ghidra (tache Brouillons Ghidra) : structure et noms utiles, types souvent faux">Ghidra</button>` : ""}
    <button class="btn small sec" onclick="closeModal()">Fermer</button></div></div>
    <div class="hint" style="margin:6px 0">${facts}</div>
    <div class="edgrid"><textarea id="edsrc" spellcheck="false"></textarea>
    <div><div id="edstatus" class="hint">Ctrl+Entree : compile avec le compilateur du jeu et compare au code d'origine (asm, #define/#pragma ajoutes... sont refuses).</div><pre id="edout"></pre></div></div>
    <div class="btns" style="margin-top:8px;justify-content:space-between"><span class="hint" id="edpending"></span>
    <button class="btn small sec" onclick="runJob('wb_commit',{push:true})" title="${esc(JD('wb_commit').desc)}">Valider les matchs en attente (verify + commit + push)</button></div></div>`);
  let saved = null;
  try { saved = localStorage.getItem(edKey(name)); } catch (e) {}
  const ta = $("#edsrc");
  ta.value = saved || d.draft || `#include "m2c.h"\n\n`;
  edShowAsm();
  ta.addEventListener("keydown", e => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); edJudge(); }
    else if (e.key === "Tab") { e.preventDefault(); const s = ta.selectionStart; ta.setRangeText("    ", s, ta.selectionEnd, "end"); }
  });
  ta.addEventListener("input", () => { try { localStorage.setItem(edKey(name), ta.value); } catch (e) {} $("#edsubmit").disabled = true; });
  edPending();
}
function edShowAsm() { $("#edout").textContent = ED.info.asm || "(pas d'assembleur : tache Desassembler)"; }
function edReset() {
  if (!confirm("Remettre le C de depart ? (tes changements de cette fonction sont perdus)")) return;
  try { localStorage.removeItem(edKey(ED.name)); } catch (e) {}
  $("#edsrc").value = ED.info.draft || ""; $("#edsubmit").disabled = true;
}
async function edJudge() {
  $("#edstatus").textContent = "Compilation...";
  const r = await api("wb/judge", {game: game(), name: ED.name, source: $("#edsrc").value});
  if (!r || r.error) { $("#edstatus").textContent = "Erreur"; $("#edout").textContent = r && r.output || ""; return; }
  const st = {match: "MATCH", near: `${r.diffs}/${r.total} instructions differentes`, size: `taille differente (0x${(r.size || 0).toString(16)} au lieu de 0x${(r.target_size || 0).toString(16)})`,
    compile: "ne compile pas", refused: "refuse"}[r.status] || r.status;
  $("#edstatus").innerHTML = `<b class="${r.match ? "c1" : r.status === "near" ? "c3" : "c5"}">${esc(st)}</b>` + (r.profile ? ` <span class="hint">(${esc(r.profile)})</span>` : "");
  $("#edout").textContent = r.match ? "Identique au code d'origine. Integre-la au jeu." : r.why || r.errors || r.diff || "";
  $("#edsubmit").disabled = !r.match || ED.info.matched;
}
async function edSubmit() {
  const r = await api("wb/submit", {game: game(), name: ED.name, source: $("#edsrc").value});
  if (r.n) { toast(`Integration de ${ED.name} lancee (onglet Queue) : la ROM est reconstruite`); $("#edsubmit").disabled = true; setTimeout(edPending, 3000); }
}
async function edPending() {
  const r = await api(`wb/pending?game=${encodeURIComponent(game())}`);
  if (r && r.pending && $("#edpending")) $("#edpending").textContent = r.pending.length ? `${r.pending.length} match(s) integre(s), pas encore valide(s) : ${r.pending.map(p => p.name).slice(0, 5).join(", ")}` : "Aucun match en attente de validation.";
}

async function subFunctions() {
  const q = `functions?game=${encodeURIComponent(game())}&level=${fnLevel}&q=${encodeURIComponent(fnQuery)}&state=${fnState}&kind=${fnKind}&limit=400`;
  $("#sub").innerHTML = `<div class="card"><div class="btns" style="margin-bottom:10px">
    <select onchange="fnState=this.value;subFunctions()"><option value="todo" ${fnState === "todo" ? "selected" : ""}>A faire (triees par difficulte)</option><option value="done" ${fnState === "done" ? "selected" : ""}>Deja matchees</option></select>
    <select onchange="fnLevel=this.value;fLevel=this.value===''?null:+this.value;subFunctions()"><option value="">Tous niveaux</option>${O.levels.map(l => `<option value="${l.n}" ${fnLevel === String(l.n) ? "selected" : ""}>${esc(l.label)}</option>`).join("")}</select>
    <select onchange="fnKind=this.value;subFunctions()">${[["", "Tous modules"], ["auto", "ARM module principal (outils auto)"], ["manual", "Tout ce que les outils ne font pas"], ["thumb", "Thumb"], ["overlay", "Overlays"], ["tcm", "ITCM / DTCM"]].map(([k, l]) => `<option value="${k}" ${fnKind === k ? "selected" : ""}>${l}</option>`).join("")}</select>
    <input placeholder="nom..." value="${esc(fnQuery)}" onchange="fnQuery=this.value;subFunctions()"><span class="hint" id="fncount"></span></div><div id="fntable" class="hint">Chargement...</div><div id="asm"></div></div>`;
  const d = await api(q);
  if (d.error) return;
  $("#fncount").textContent = `${fmt(d.total)} fonctions${d.total > d.rows.length ? " (400 premieres)" : ""}`;
  $("#fntable").innerHTML = `<table><tr><th>Fonction</th><th>Adresse</th><th class="num">Taille</th><th>Mode</th><th>Niveau</th><th>auto_match</th><th>Bloc</th><th>Note</th></tr>
    ${d.rows.map(f => `<tr class="click" onclick="${f.mode === "arm" && f.module === "main" ? "openEditor" : "showAsm"}('${esc(f.name)}')" title="${f.mode === "arm" && f.module === "main" ? "ouvrir l'editeur C" : "assembleur (l'editeur gere le module principal ARM)"}"><td><b>${esc(f.name)}</b></td><td class="hint">${hex(f.addr)}</td><td class="num">${f.size}</td>
    <td class="hint">${f.mode}${f.module !== "main" ? " &middot; " + esc(f.module) : ""}</td><td>${f.done ? (esc(f.file || "")) : `<span class="c${f.level}">${esc(LV(f.level).label)}</span>`}</td><td class="hint">${esc(f.auto || "")}</td>
    <td class="hint">${esc(f.block || "")}</td><td class="hint">${f.port ? portNote(f.port) : f.shared >= 2 ? "SDK (" + f.shared + ")" : ""}</td></tr>`).join("")}</table>`;
}

// ---- data: every .data / .rodata / .bss symbol of every module, matched or not; a click shows its bytes and a C
async function subData() {
  const S = G.data && G.data.sections || {};
  const secBars = Object.entries(S).map(([k, v]) => `<div style="flex:1;min-width:180px"><b>${esc(k)}</b> ${pctBar(v.bytes ? 100 * v.matched_bytes / v.bytes : 0)}
    <div class="hint">${fmt(v.matched)} / ${fmt(v.symbols)} symboles &middot; ${fmt(v.matched_bytes)} / ${fmt(v.bytes)} octets</div></div>`).join("");
  $("#sub").innerHTML = `<div class="card"><div class="btns" style="gap:16px;margin-bottom:12px">${secBars || '<span class="hint">Aucune section de donnees.</span>'}</div>
    <div class="btns" style="margin-bottom:10px">
    <select onchange="dState=this.value;subData()">${[["todo", "A faire"], ["done", "Deja matchees"], ["all", "Toutes"]].map(([k, l]) => `<option value="${k}" ${dState === k ? "selected" : ""}>${l}</option>`).join("")}</select>
    <select onchange="dSection=this.value;subData()"><option value="">Toutes sections</option>${[".data", ".rodata", ".bss"].map(k => `<option ${dSection === k ? "selected" : ""}>${k}</option>`).join("")}</select>
    <select id="dmod" onchange="dModule=this.value;subData()"><option value="">Tous modules</option></select>
    <input placeholder="nom..." value="${esc(dQuery)}" onchange="dQuery=this.value;subData()"><span class="hint" id="dcount"></span>
    <span style="flex:1"></span>
    <button class="btn small sec" title="${esc(JD("misses").desc)}" onclick="runJob('misses',{})">Rejouer les essais rates (fonctions + donnees)</button></div>
    <div id="dtable" class="hint">Chargement...</div></div>`;
  const d = await api(`data?game=${encodeURIComponent(game())}&state=${dState}&section=${encodeURIComponent(dSection)}&module=${encodeURIComponent(dModule)}&q=${encodeURIComponent(dQuery)}&limit=400`);
  if (d.error) return;
  $("#dmod").innerHTML = `<option value="">Tous modules</option>` + d.modules.map(m => `<option ${dModule === m ? "selected" : ""}>${esc(m)}</option>`).join("");
  $("#dcount").textContent = `${fmt(d.total)} symboles${d.total > d.rows.length ? " (400 premiers)" : ""}`;
  $("#dtable").innerHTML = d.rows.length ? `<table><tr><th>Donnee</th><th>Module</th><th>Section</th><th>Adresse</th><th class="num">Taille</th><th>Fichier</th><th class="num">Essais rates</th></tr>
    ${d.rows.map(r => `<tr class="click" onclick="showData('${esc(r.name)}')" title="octets decodes, pointeurs, qui l'utilise, et une declaration C"><td><b>${esc(r.name)}</b></td><td class="hint">${esc(r.module)}</td><td class="hint">${esc(r.section)}</td>
    <td class="hint">${hex(r.addr)}</td><td class="num">${fmt(r.size)}</td><td class="hint">${r.done ? esc(r.file) : "-"}</td><td class="num">${r.misses || ""}</td></tr>`).join("")}</table>` : '<p class="hint">Rien ici.</p>';
}
async function showData(name) {
  modal('<p class="hint">Chargement...</p>');
  const d = await api(`wb/data?game=${encodeURIComponent(game())}&name=${encodeURIComponent(name)}`);
  if (d.error) return modal(`<p>${esc(d.error)}</p>`);
  modal(`<h3 style="margin-top:0">${esc(d.name)} <span class="hint">${esc(d.addr)} &middot; ${esc(d.section || "")} &middot; ${fmt(d.size)} octets</span></h3>
    <p class="hint">${d.file ? "Fichier : " + esc(d.file) : "Pas encore dans un fichier source"}${d.used_by && d.used_by.length ? " &middot; utilisee par " + d.used_by.slice(0, 8).map(esc).join(", ") : ""}</p>
    ${d.string ? `<p>Texte : <code>${esc(d.string)}</code></p>` : ""}
    ${d.pointers && d.pointers.length ? `<p class="hint">Pointeurs : ${d.pointers.slice(0, 20).map(esc).join(", ")}</p>` : ""}
    ${d.words && d.words.length ? `<h4>Contenu</h4><pre style="max-height:220px;overflow:auto">${esc(d.words.join("\n"))}</pre>` : ""}
    <h4>Declaration C (exacte)</h4><pre style="max-height:260px;overflow:auto">${esc(d.c || "")}</pre>
    <div class="btns"><button class="btn small sec" onclick="navigator.clipboard.writeText(${esc(JSON.stringify(d.c || ""))}).then(()=>toast('Copie'))">Copier le C</button><button class="btn small sec" onclick="closeModal()">Fermer</button></div>`);
}

async function subMap() {
  $("#sub").innerHTML = `<div class="card"><h3>Carte memoire du module ARM9</h3><p class="hint">Chaque trait = une fonction, a sa place dans la memoire. Gris = matchee, couleur = difficulte. Survole pour le nom, clique pour l'assembleur.</p>
    <canvas id="map" height="260"></canvas><div class="legend"><span><i style="background:var(--done)"></i>matchee</span>${O.levels.map(l => `<span><i style="background:var(--l${l.n})"></i>${esc(l.label)}</span>`).join("")}</div>
    <div class="hint" id="maptip">&nbsp;</div><div id="asm"></div></div>`;
  const d = await api("map?game=" + encodeURIComponent(game()));
  if (d.error) return;
  const cv = $("#map"), ctx = cv.getContext("2d"), W = cv.clientWidth, rows = 8, H = 260;
  cv.width = W * devicePixelRatio; cv.height = H * devicePixelRatio; ctx.scale(devicePixelRatio, devicePixelRatio);
  const css = getComputedStyle(document.documentElement), col = l => css.getPropertyValue(l < 0 ? "--done" : "--l" + l).trim();
  const span = Math.max(d.end - d.start, 1), per = span / rows, rh = H / rows;
  const pos = a => { const o = a - d.start, r = Math.min(Math.floor(o / per), rows - 1); return [((o - r * per) / per) * W, r * rh]; };
  for (const [a, s, l] of d.functions) {
    const [x, y] = pos(a); ctx.fillStyle = col(l); ctx.fillRect(x, y + 2, Math.max(W * s / per, 1.2), rh - 4);
  }
  cv.onmousemove = e => {
    const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, row = Math.floor(y / rh);
    const a = d.start + row * per + (x / W) * per, f = d.functions.find(f => f[0] <= a && a < f[0] + Math.max(f[1], per / W * 2));
    $("#maptip").textContent = f ? `${f[3] || ""} ${hex(f[0])} - ${f[1]} octets - ${f[2] < 0 ? "matchee" : LV(f[2]).label}` : hex(a);
    cv._f = f;
  };
  cv.onclick = () => { if (cv._f && cv._f[3]) showAsm(cv._f[3]); };
}

const JOB_OPTS = {
  clone: [["other_games", "Prendre aussi les matchs de nos autres jeux", "check", true],
    ["max", "Nombre max de fonctions a integrer (0 = toutes)", "number", 0],
    ["block", "Seulement le bloc (ex. L0-01001, vide = tout le jeu)", "text", ""],
    ["list", "Seulement lister les familles (rapide, remplit le niveau Portable et l'ordre de la file)", "check", false],
    ["dry_run", "Essai a blanc (ne change rien)", "check", false]],
  donors: [["max", "Nombre max de fonctions a reprendre (un lot ; 0 = toutes)", "number", 50],
    ["block", "Seulement le bloc (ex. L0-01001, vide = tout le jeu)", "text", ""],
    ["jobs", "Fonctions essayees en parallele (-j)", "number", 14],
    ["bisect", "Builds ninja max pour isoler les fichiers qui cassent la ROM (0 = tout annuler)", "number", 40],
    ["list", "Seulement lister les candidates (rapide, remplit le niveau Portable)", "check", false],
    ["dry_run", "Essai a blanc (ne change rien)", "check", false]],
  auto: [["jobs", "Coeurs utilises (-j)", "number", 16],
    ["multi", "Multi recherche mwcc (chaque version aussi avec -O4,s / -O2 / -O3,p : plus lent)", "check", false],
    ["batch", "Match par lot : N fonctions a la fois, integrees + verifiees a chaque lot (0 = un seul passage)", "number", 0], ["permute", "Permuter sur N near misses (0 = non)", "number", 0],
    ["minutes", "Minutes de permuter par fonction", "number", 2], ["fresh", "Tout refaire (ignorer le cache des echecs)", "check", false],
    ["dry_run", "Essai a blanc (ne change rien)", "check", false],
    ["cached_only", "Seulement integrer les matches deja trouves (reprise rapide)", "check", false], ["force", "Relancer meme si l'auto-match est marque termine", "check", false]],
  permute: [["permute", "Nombre de near misses", "number", 10], ["minutes", "Minutes par fonction", "number", 2], ["jobs", "Coeurs (-j)", "number", 16],
    ["force", "Relancer meme si marque termine", "check", false]],
  culprits: [["fix", "Retirer les fichiers fautifs (non commites) et reconstruire", "check", true],
    ["any", "Autoriser aussi les fichiers deja commites (prudence)", "check", false]],
  moulinette: [["push", "Pousser sur GitHub si la verification passe", "check", true], ["permute_near", "Permuter sur N near misses (0 = non)", "number", 0],
    ["near_minutes", "Minutes de permuter par near miss", "number", 5], ["restart", "Oublier les echecs deja essayes", "select", ["", "all", "auto", "permuter", "qwen"]],
    ["no_drafts", "Sans brouillons m2c", "check", false], ["no_auto", "Sans auto-match", "check", false], ["no_commit", "Verifier seulement (pas de commit)", "check", false]],
  ghidra: [["block", "Seulement le bloc (ex. L1-02003, vide = les fonctions sans brouillon m2c)", "text", ""],
    ["max", "Nombre max de fonctions (0 = toutes)", "number", 200]],
  wb_commit: [["push", "Pousser sur GitHub si la verification passe", "check", true]],
};
function optField([k, label, type, def]) {
  if (type === "check") return `<tr><td>${esc(label)}</td><td><input type="checkbox" data-k="${k}" ${def ? "checked" : ""}></td></tr>`;
  if (type === "text") return `<tr><td>${esc(label)}</td><td><input data-k="${k}" value="${esc(def)}"></td></tr>`;
  if (type === "select") return `<tr><td>${esc(label)}</td><td><select data-k="${k}">${def.map(v => `<option value="${v}">${v || "non"}</option>`).join("")}</select></td></tr>`;
  return `<tr><td>${esc(label)}</td><td><input type="number" data-k="${k}" value="${def}" style="width:90px"></td></tr>`;
}
function readFields() {
  const o = {};
  document.querySelectorAll("#modalbody [data-k]").forEach(e => { o[e.dataset.k] = e.type === "checkbox" ? e.checked : e.type === "number" ? +e.value : e.value; });
  return o;
}
async function runJob(id, params) {
  if (JOB_OPTS[id] && !params) {
    const opts = JOB_OPTS[id].map(o => o[0] === "push" ? [o[0], o[1], o[2], !!G.game.remote] : o);
    modal(`<h2>${esc(JD(id).label)}</h2><p class="hint">${esc(JD(id).desc)}</p><table>${opts.map(optField).join("")}</table>
      <div class="btns" style="margin-top:12px"><button class="btn" onclick="closeModal();runJob('${id}',readFields())">Lancer</button>
      <button class="btn sec" onclick="closeModal()">Annuler</button></div>`);
    return;
  }
  params = params || (id === "progress" ? {game: game()} : {});  // from a game's page: only that game
  let r = await api("run", {id, game: game(), params});
  if (r.error && r.error.includes("forcer") && confirm("Auto-match deja termine sur ce jeu. Relancer quand meme ?")) r = await api("run", {id, game: game(), params: {...params, force: true}});
  if (r.n) toast(`Tache #${r.n} ajoutee a la queue`);
}
async function publishGame() {
  if (!confirm(`Publier ${G.game.title} sur GitHub en PUBLIC ?\nLa ROM et les fichiers du jeu ne sont jamais envoyes (verifie avant l'envoi).`)) return;
  const r = await api("run", {id: "publish", game: game()}); if (r.n) toast("Publication lancee (onglet Queue)");
}

// ---------------- Queue ----------------
// The page is built once; the periodic refresh only replaces the block whose content changed (claims, jobs, log),
// so scroll positions, an open "all tasks" list and the log stay where they are.
let lastOverview = 0, jobsAll = false;
const JOBS_SHOWN = 10;
async function viewQueue() {
  if (Date.now() - lastOverview > 30000) { await loadOverview(); lastOverview = Date.now(); }
  const d = await api("jobs"); J = d.jobs || [];
  return `<div class="split"><div class="card"><h3>Qui travaille sur quoi (tous les jeux)</h3>
    <p class="hint">Les blocs pris par des personnes ou des IA. Un bloc non touche depuis 48 h retourne dans la queue.</p>
    <div id="claimsbox">${claimsHtml()}</div></div>
    <div class="card"><h3>Comment rejoindre (personnes et IA)</h3>
    <p>Une personne ou une IA prend un bloc, travaille, puis le marque termine. Les prises sont enregistrees dans le repo GitHub du jeu (<code>.studio/claims/</code>), donc tout le monde voit la meme queue.</p>
    <pre>python studio/studio.py blocks &lt;jeu&gt; --free
python studio/studio.py claim &lt;jeu&gt; next --who NOM --kind claude
python studio/studio.py brief &lt;jeu&gt; &lt;bloc&gt;     (fiche de travail)
python studio/studio.py done &lt;jeu&gt; &lt;bloc&gt;</pre>
    <p class="hint">Les taches machine (en bas) passent une par une par jeu, et au maximum ${O.settings.max_parallel_jobs} en meme temps (Reglages).</p></div></div>
    <div class="card"><div class="btns" style="justify-content:space-between"><h3 style="margin:0">Taches machine</h3><span id="jobsbtn">${jobsButton()}</span></div>
    <div id="jobsbox">${jobsHtml()}</div><div id="logbox"></div></div>`;
}
function claimsHtml() {
  return O.queue.length ? `<table><tr><th>Jeu</th><th>Bloc</th><th>Qui</th><th>Depuis</th><th></th></tr>${O.queue.map(c => `<tr><td>${esc(c.title)}</td><td><b>${esc(c.block)}</b></td>
    <td>${esc(c.who)}<div class="hint">${esc(O.kinds[c.kind] || c.kind)}${c.note ? " &middot; " + esc(c.note) : ""}</div></td><td class="hint">${ago(c.touched)} ${c.expired ? '<span class="state expired">expire</span>' : ""}</td>
    <td><button class="btn small sec" onclick="selectGame('${c.game}')">Ouvrir</button></td></tr>`).join("")}</table>` : '<div class="empty">Personne ne travaille sur un bloc pour l\'instant.</div>';
}
function jobsButton() {
  return J.length > JOBS_SHOWN ? `<button class="btn small sec" onclick="toggleJobs()">${jobsAll ? "Reduire aux 10 dernieres" : `Voir toute la liste (${J.length})`}</button>` : "";
}
function jobRow(j) {
  return `<tr><td class="hint">${j.n}</td><td>${esc(j.label)}${j.params && j.params.block ? " " + esc(j.params.block) : ""}</td><td class="hint">${esc(j.game || "-")}</td>
    <td><span class="state ${j.state}">${ST[j.state] || j.state}</span></td><td style="min-width:140px"><div class="bar"><i style="width:${j.pct}%"></i></div></td>
    <td class="hint">${Math.floor(j.elapsed / 60)} min ${j.elapsed % 60} s</td>
    <td class="btns"><button class="btn small sec ${openLog === j.n ? "on" : ""}" onclick="showLog(${j.n})">Log</button>
    ${j.state === "running" || j.state === "queued" ? `<button class="btn small red" onclick="cancelJob(${j.n})">Stop</button>` : ""}
    ${j.id === "qwen" && j.state === "running" ? `<button class="btn small sec" onclick="api('qwen_stop',{game:'${j.game}'}).then(()=>toast('Qwen s\\'arretera apres la fonction en cours'))">Finir apres la fonction</button>` : ""}</td></tr>`;
}
function jobsHtml() {
  if (!J.length) return '<div class="empty">Aucune tache.</div>';
  const rows = jobsAll ? J : J.slice(0, JOBS_SHOWN);
  return `<div class="${jobsAll ? "scrollbox" : ""}" id="jobsscroll"><table><tr><th>#</th><th>Tache</th><th>Jeu</th><th>Etat</th><th>Avancement</th><th>Duree</th><th></th></tr>
    ${rows.map(jobRow).join("")}</table></div>${!jobsAll && J.length > JOBS_SHOWN ? `<div class="hint" style="margin-top:6px">${J.length - JOBS_SHOWN} taches plus anciennes masquees</div>` : ""}`;
}
function setHtml(id, html) {
  // Replaces a block only when its content changed, keeping the scroll position of its scrollable part
  const el = $("#" + id); if (!el || el._html === html) return;
  const sc = el.querySelector(".scrollbox"), top = sc ? sc.scrollTop : 0;
  el.innerHTML = html; el._html = html;
  const sc2 = el.querySelector(".scrollbox"); if (sc2) sc2.scrollTop = top;
}
function toggleJobs() { jobsAll = !jobsAll; setHtml("jobsbtn", jobsButton()); setHtml("jobsbox", jobsHtml()); }
async function refreshQueue() {
  if (Date.now() - lastOverview > 30000) { await loadOverview(); lastOverview = Date.now(); setHtml("claimsbox", claimsHtml()); }
  const d = await api("jobs"); if (d.error) return;
  J = d.jobs || [];
  setHtml("jobsbtn", jobsButton());
  setHtml("jobsbox", jobsHtml());
  if (openLog) showLog(openLog, true);
}
async function cancelJob(n) { await api("cancel", {n}); toast("Tache arretee"); refreshQueue(); }
async function showLog(n, refresh) {
  if (!refresh) { openLog = n; setHtml("jobsbox", jobsHtml()); }
  let pre = $("#logpre");
  const have = refresh && pre && $("#logbox").dataset.n === String(n) ? +(pre.dataset.size || -1) : -1;
  const d = await api(`log?n=${n}&from=${have}`);  // a refresh only gets the new end of the log
  const box = $("#logbox"); if (!box || d.error) return;
  pre = $("#logpre");
  if (!pre || box.dataset.n !== String(n)) {
    box.dataset.n = n;
    box.innerHTML = `<div class="btns" style="justify-content:space-between;margin-top:12px"><h3 style="margin:0">Log de la tache #${n}</h3>
      <button class="btn small sec" onclick="openLog=null;$('#logbox').innerHTML='';$('#logbox').dataset.n='';setHtml('jobsbox', jobsHtml())">Fermer</button></div><pre id="logpre"></pre>`;
    pre = $("#logpre");
  }
  const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 30;  // follow the end only if already there
  if (d.append && pre.dataset.size) {
    if (!d.log) return;
    pre.appendChild(document.createTextNode(d.log));
  } else {
    pre.textContent = d.log || "(pas encore de sortie : la tache demarre ou cherche encore, ca s'affiche des que possible)";
  }
  pre.dataset.size = d.log ? d.size : "";
  if (atBottom || !refresh) pre.scrollTop = pre.scrollHeight;
}

// ---------------- Engine map ----------------
async function viewEngine() {
  const d = await api("engine");
  if (d.error) return "";
  let h = `<div class="card"><h3>Studios (meme studio = souvent le meme moteur)</h3><div class="grid">${d.studios.map(s => `<div class="card" style="margin:0"><b>${esc(s.studio)}</b>
    <div class="hint">${s.games.map(g => `<a href="#game" onclick="selectGame('${g}');return false">${esc(g)}</a>`).join(", ")}</div></div>`).join("")}</div></div>`;
  h += `<div class="split"><div class="card"><h3>Jeux indexes (base d'empreintes)</h3><p class="hint">SDK = code Nintendo present dans 5 jeux ou plus. Unique = code propre au jeu.</p>
    <table><tr><th>Jeu</th><th class="num">Fonctions</th><th class="num">SDK</th><th class="num">Unique</th></tr>
    ${d.games.map(g => `<tr><td>${esc(g.title)}<div class="hint">${esc(g.studio)}</div></td><td class="num">${fmt(g.functions)}</td><td class="num">${fmt(g.sdk)}</td><td class="num">${fmt(g.unique)}</td></tr>`).join("")}</table>
    <div class="btns" style="margin-top:10px"><button class="btn small sec" onclick="api('run',{id:'scan'}).then(r=>r.n&&toast('Indexation lancee'))">Re-indexer les empreintes</button><button class="btn small sec" title="compile les depots de decomps-externes/ (NitroSDK, pret...)" onclick="api('run',{id:'donors_index'}).then(r=>r.n&&toast('Indexation lancee'))">Indexer les decomps externes</button><button class="btn small sec" title="${esc(JD('dataset').desc)}" onclick="api('run',{id:'dataset'}).then(r=>r.n&&toast('Export lance'))">Exporter le jeu de donnees (LoRA)</button><button class="btn small sec" title="${esc(JD('examples').desc)}" onclick="api('run',{id:'examples'}).then(r=>r.n&&toast('Indexation lancee'))">Indexer les exemples pour l'IA</button><button class="btn small sec" title="${esc(JD('clone_all').desc)}" onclick="api('run',{id:'clone_all'}).then(r=>r.n&&toast('Clonage lance'))">Cloner les jumelles dans tous les jeux</button><button class="btn small sec" title="${esc(JD('misses_all').desc)}" onclick="api('run',{id:'misses_all'}).then(r=>r.n&&toast('Rejeu lance'))">Rejouer les essais rates dans tous les jeux</button></div></div>
    <div class="card"><h3>Moteurs partages entre jeux</h3><p class="hint">Fonctions identiques entre deux jeux, hors SDK : du code moteur reutilise. Un match dans un jeu = gratuit dans l'autre (niveau "Portable").</p>
    <table><tr><th>Jeu A</th><th>Jeu B</th><th class="num">Moteur commun</th><th class="num">SDK commun</th></tr>
    ${d.pairs.slice(0, 40).map(p => `<tr><td>${esc(p.a)}</td><td>${esc(p.b)}</td><td class="num"><b>${fmt(p.engine)}</b></td><td class="num hint">${fmt(p.sdk)}</td></tr>`).join("")}</table></div></div>`;
  return h;
}

// ---------------- Progression ----------------
function viewProgress() {
  const x = window.XP; if (!x) return '<div class="empty">Chargement...</div>';
  return `<div class="kpis"><div class="kpi"><b>${x.level}</b><span>niveau (${esc(x.rank)})</span></div><div class="kpi"><b>${fmt(x.xp)}</b><span>XP total</span></div>
    <div class="kpi"><b>${fmt(x.stats.matched)}</b><span>fonctions matchees</span></div><div class="kpi"><b>${x.stats.blocks_done}</b><span>blocs termines</span></div></div>
    <div class="split"><div class="card"><h3>Butin recent</h3>${x.events.map(e => e.kind === "loot" ? `<div class="loot ${e.rarity}">+${e.xp} XP &middot; <b>${esc(e.name)}</b> (${e.size} octets) &middot; ${esc(e.game)}</div>`
    : `<div class="loot ${e.kind}">${esc(e.text)}</div>`).join("") || '<div class="empty">Rien encore.</div>'}</div>
    <div class="card"><h3>Succes</h3>${x.achievements.map(a => `<div class="ach ${a.unlocked ? "" : "off"}">${a.unlocked ? "&#127942;" : "&#128274;"} ${esc(a.label)}</div>`).join("")}</div></div>`;
}

// ---------------- Reglages ----------------
function viewSettings() {
  const s = O.settings;
  return `<div class="card" style="max-width:700px"><h3>Reglages</h3><table>
    <tr><td>Ton nom (pour prendre des blocs)</td><td><input id="s-who" value="${esc(s.who)}"></td></tr>
    <tr><td>Taches machine en parallele</td><td><input id="s-par" type="number" min="1" max="8" value="${s.max_parallel_jobs}"></td></tr>
    <tr><td>Modele Qwen (Ollama)</td><td><input id="s-model" value="${esc(s.qwen_model)}"></td></tr>
    <tr><td>Agents Qwen en parallele (par defaut)<div class="hint">Ollama doit avoir OLLAMA_NUM_PARALLEL &ge; ce nombre (variable d'environnement, puis redemarrer Ollama). Avec 16 Go de VRAM : environ 4 pour qwen9-ctx, 8 pour qwen-ctx (4b).</div></td><td><input id="s-agents" type="number" min="1" max="16" value="${s.qwen_agents}"></td></tr>
    <tr><td>Minutes max par fonction proche (Qwen, 2e passe)<div class="hint">Une 1re passe rapide (1,5 min) voit toutes les fonctions ; seules celles a 3 diffs ou moins ont droit a ce temps. Une fonction qui ne progresse plus s'arrete avant. Seul le temps de generation compte : l'attente de son tour sur le GPU ne mange pas le temps d'une fonction.</div></td><td><input id="s-min" type="number" min="1" max="60" value="${s.qwen_minutes}"></td></tr>
    <tr><td>Serveur du modele<div class="hint">llama.cpp : vraies requetes en parallele (une par agent), meme pour qwen3.5 qu'Ollama traite une par une. Demarre tout seul avec le fichier du modele deja telecharge par Ollama.</div></td><td><select id="s-backend"><option value="ollama" ${s.qwen_backend === "ollama" ? "selected" : ""}>Ollama</option><option value="openai" ${s.qwen_backend === "openai" ? "selected" : ""}>llama.cpp server (ou vLLM)</option></select> <input id="s-server" value="${esc(s.qwen_server)}" style="width:200px"></td></tr>
    <tr><td>Petit modele pour les fonctions faciles<div class="hint">1re passe sur les petites fonctions presque bonnes (ex. qwen-ctx). Vide = toujours le modele principal.</div></td><td><input id="s-small" value="${esc(s.qwen_small_model || "")}"></td></tr>
    <tr><td>Modele de la file difficile<div class="hint">pour les fonctions restees a 1-3 instructions pres (plus gros modele). Vide = le modele principal.</div></td><td><input id="s-hardm" value="${esc(s.qwen_hard_model || "")}"></td></tr>
    <tr><td>Publier les prises de blocs sur GitHub</td><td><input id="s-push" type="checkbox" ${s.push_claims ? "checked" : ""}></td></tr>
    <tr><td>Compte GitHub</td><td><input id="s-owner" value="${esc(s.github_owner)}" placeholder="rempli a la 1re publication"></td></tr></table>
    <div class="btns" style="margin-top:12px"><button class="btn" onclick="saveSettings()">Enregistrer</button></div></div>`;
}
async function saveSettings() {
  const r = await api("settings", {who: $("#s-who").value.trim(), max_parallel_jobs: +$("#s-par").value, qwen_model: $("#s-model").value.trim(),
    qwen_minutes: +$("#s-min").value, qwen_agents: +$("#s-agents").value, qwen_backend: $("#s-backend").value,
    qwen_small_model: $("#s-small").value.trim(), qwen_hard_model: $("#s-hardm").value.trim(),
    qwen_server: $("#s-server").value.trim(), push_claims: $("#s-push").checked, github_owner: $("#s-owner").value.trim()});
  if (!r.error) { O.settings = r; toast("Reglages enregistres"); }
}

// ---------------- boucle ----------------
(async function init() {
  // #edit/<game>/<function>: straight into the C editor (links from briefs, logs...)
  const deep = location.hash.match(/^#edit\/([^/]+)\/(\w+)$/);
  if (deep) tab = "game";
  tabs(); await loadOverview();
  if (deep && O.settings.active_game !== deep[1]) { await api("settings", {active_game: deep[1]}); O.settings.active_game = deep[1]; }
  render(); loadXP();
  if (deep) { location.hash = "game"; openEditor(deep[2]); }
  setInterval(async () => {
    if (document.hidden || $("#modal").classList.contains("on")) return;
    if (tab === "queue") await refreshQueue();
  }, 4000);
  // the games list follows the jobs (matches, new projects) without reloading the page; not while typing in it
  setInterval(async () => {
    if (document.hidden || tab !== "games" || $("#modal").classList.contains("on")) return;
    const a = document.activeElement;
    if (a && a.matches("input, select, textarea")) return;
    const before = JSON.stringify(O.games); await loadOverview();
    if (tab === "games" && JSON.stringify(O.games) !== before) render();
  }, 15000);
  setInterval(() => { if (!document.hidden) loadXP(); }, 60000);
})();
