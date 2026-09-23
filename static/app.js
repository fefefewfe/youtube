"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const THEME_SWATCH = {
  neon: "linear-gradient(135deg,#140a30,#42126e,#0c285a)",
  sunset: "linear-gradient(135deg,#ff5e62,#ff9966,#8432a0)",
  ocean: "linear-gradient(135deg,#003c6e,#0077b6,#00b4d8)",
  light: "linear-gradient(135deg,#f5f7ff,#e1e8ff,#f0e4ff)",
  dark: "linear-gradient(135deg,#0a0a0e,#181820,#0e0e14)",
};

let META = null;
let P = null; // proyecto actual
let saveTimer = null;
let voiceCache = {};

// ---------------------------------------------------------------- utilidades
async function api(path, opts = {}) {
  const o = { ...opts };
  if (o.body && !(o.body instanceof FormData)) {
    o.headers = { "Content-Type": "application/json", ...(o.headers || {}) };
    o.body = JSON.stringify(o.body);
  }
  const r = await fetch(path, o);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r;
}

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " error" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), err ? 6000 : 3000);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function uid() { return Math.random().toString(16).slice(2, 12); }

function showJob(el, job) {
  el.classList.remove("hidden", "error");
  el.querySelector("i").style.width = `${Math.round(job.progress * 100)}%`;
  el.querySelector("span").textContent = job.status === "error" ? `❌ ${job.error}` : `${job.message} (${Math.round(job.progress * 100)}%)`;
  if (job.status === "error") el.classList.add("error");
}

async function pollJob(job, el, onDone) {
  while (true) {
    job = await api(`/api/jobs/${job.id}`);
    if (el) showJob(el, job);
    if (job.status === "done") { onDone && onDone(job); return job; }
    if (job.status === "error") { toast(job.error, true); return job; }
    await new Promise((r) => setTimeout(r, 1000));
  }
}

// ---------------------------------------------------------------- proyectos
async function loadProjects() {
  const list = await api("/api/projects");
  $("#projectList").innerHTML = list.map((p) => `
    <li data-id="${p.id}" class="${P && P.id === p.id ? "active" : ""}">
      <div class="t">${esc(p.title)}</div>
      <div class="m">${p.questions} preguntas · ${p.format}${p.has_video ? " · 🎬" : ""}${p.video_id ? " · ▶ subido" : ""}</div>
    </li>`).join("") || `<li class="muted small">Aún no hay proyectos</li>`;
  $$("#projectList li[data-id]").forEach((li) => li.onclick = () => openProject(li.dataset.id));
}

async function openProject(id) {
  await flushSave();
  P = await api(`/api/projects/${id}`);
  localStorage.setItem("lastProject", id);
  $("#empty").classList.add("hidden");
  $("#editor").classList.remove("hidden");
  renderAll();
  loadProjects();
  // reanudar trabajos en curso
  const js = await api(`/api/jobs?project_id=${id}`);
  for (const j of js.filter((j) => j.status === "running" || j.status === "queued")) {
    if (j.kind === "render" || j.kind === "autopilot") watchRender(j);
  }
}

function scheduleSave() {
  $("#saveState").textContent = "Guardando…";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, 700);
}

async function flushSave() {
  if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; await save(); }
}

async function save() {
  saveTimer = null;
  if (!P) return;
  try {
    const saved = await api(`/api/projects/${P.id}`, { method: "PUT", body: P });
    P.updated_at = saved.updated_at;
    $("#saveState").textContent = "✓ Guardado";
    loadProjects();
  } catch (e) {
    $("#saveState").textContent = "⚠ Error al guardar";
    toast(e.message, true);
  }
}

// ---------------------------------------------------------------- render UI
function renderAll() {
  $("#pTitle").value = P.title;
  $("#pTopic").value = P.topic;
  $("#pLanguage").value = P.language;
  $("#aiTopic").value = $("#aiTopic").value || P.topic;
  $("#btnExport").href = `/api/projects/${P.id}/export`;
  renderQuestions();
  renderSettings();
  renderPublish();
}

function renderQuestions() {
  const box = $("#questions");
  $("#qCount").textContent = `(${P.questions.length})`;
  box.innerHTML = P.questions.map((q, i) => `
    <div class="q" data-i="${i}">
      <div class="num">${i + 1}</div>
      <div class="body">
        <textarea rows="2" data-f="question" placeholder="Escribe la pregunta…">${esc(q.question)}</textarea>
        <div class="opts">
          ${[0, 1, 2, 3].map((k) => `
            <div class="opt ${q.correct === k ? "correct" : ""}">
              <input type="radio" name="c${q.id}" data-k="${k}" ${q.correct === k ? "checked" : ""} title="Marcar como correcta">
              <b>${"ABCD"[k]}</b>
              <input type="text" data-o="${k}" value="${esc(q.options[k] || "")}" placeholder="Opción ${"ABCD"[k]}">
            </div>`).join("")}
        </div>
        <input data-f="explanation" value="${esc(q.explanation)}" placeholder="Explicación o dato curioso (opcional)">
        <div class="tools">
          ${q.image ? `<img class="qimg" src="/files/${P.id}/${q.image}"><button class="btn ghost small-btn" data-act="rmimg">Quitar imagen</button>` : ""}
          <label class="btn ghost small-btn">🖼 Imagen<input type="file" accept="image/*" data-act="img" hidden></label>
          <button class="btn ghost small-btn" data-act="up" ${i === 0 ? "disabled" : ""}>↑</button>
          <button class="btn ghost small-btn" data-act="down" ${i === P.questions.length - 1 ? "disabled" : ""}>↓</button>
          <button class="btn ghost small-btn" data-act="preview">👁 Vista previa</button>
          <button class="btn ghost small-btn danger" data-act="del">🗑 Eliminar</button>
        </div>
      </div>
    </div>`).join("") || `<p class="muted">No hay preguntas todavía. Genera algunas con IA, impórtalas o añádelas a mano.</p>`;

  $$("#questions .q").forEach((el) => {
    const i = +el.dataset.i;
    const q = P.questions[i];
    el.querySelectorAll("[data-f]").forEach((inp) => inp.oninput = () => { q[inp.dataset.f] = inp.value; scheduleSave(); });
    el.querySelectorAll("[data-o]").forEach((inp) => inp.oninput = () => { q.options[+inp.dataset.o] = inp.value; scheduleSave(); });
    el.querySelectorAll("input[type=radio]").forEach((r) => r.onchange = () => {
      q.correct = +r.dataset.k;
      el.querySelectorAll(".opt").forEach((o, k) => o.classList.toggle("correct", k === q.correct));
      scheduleSave();
    });
    el.querySelectorAll("[data-act]").forEach((b) => {
      const act = b.dataset.act;
      if (act === "img") {
        b.onchange = async () => {
          if (!b.files[0]) return;
          await flushSave();
          const fd = new FormData(); fd.append("file", b.files[0]);
          try {
            const r = await api(`/api/projects/${P.id}/upload?kind=image&qid=${q.id}`, { method: "POST", body: fd });
            P = r.project; renderQuestions();
          } catch (e) { toast(e.message, true); }
        };
        return;
      }
      b.onclick = () => {
        if (act === "del") { if (!confirm("¿Eliminar esta pregunta?")) return; P.questions.splice(i, 1); }
        if (act === "up") [P.questions[i - 1], P.questions[i]] = [P.questions[i], P.questions[i - 1]];
        if (act === "down") [P.questions[i + 1], P.questions[i]] = [P.questions[i], P.questions[i + 1]];
        if (act === "rmimg") q.image = null;
        if (act === "preview") { flushSave().then(() => { switchTab("preview"); $("#pvQ").value = i; $("#pvPhase").value = "think"; refreshPreview(); }); return; }
        renderQuestions(); scheduleSave();
      };
    });
  });
  $("#pvQ").innerHTML = P.questions.map((q, i) => `<option value="${i}">${i + 1}. ${esc(q.question.slice(0, 50))}</option>`).join("");
}

function addQuestion() {
  P.questions.push({ id: uid(), question: "", options: ["", "", "", ""], correct: 0, explanation: "", image: null });
  renderQuestions(); scheduleSave();
  const last = $$("#questions .q").pop(); last && last.querySelector("textarea").focus();
}

// ---------------------------------------------------------------- ajustes
function bindSetting(sel, key, { type = "value", label = null, fmt = (v) => v } = {}) {
  const el = $(sel);
  const s = P.settings;
  if (type === "checked") el.checked = !!s[key]; else el.value = s[key] ?? "";
  const upd = () => { if (label) $(label).textContent = fmt(s[key]); };
  upd();
  el.oninput = el.onchange = () => {
    let v = type === "checked" ? el.checked : el.value;
    if (el.type === "range" || el.type === "number" || key === "fps") v = Number(v);
    s[key] = v; upd(); scheduleSave();
    if (key === "tts_provider") loadVoices();
    if (key === "theme") renderSettings();
  };
}

function renderSettings() {
  const s = P.settings;
  $$("#fmtSeg button").forEach((b) => {
    b.classList.toggle("active", b.dataset.v === s.format);
    b.onclick = () => { s.format = b.dataset.v; renderSettings(); scheduleSave(); };
  });
  $("#sTheme").innerHTML = META.themes.map((t) => `<option value="${t.id}">${t.name}</option>`).join("");
  $("#themeThumbs").innerHTML = META.themes.map((t) => `<button data-t="${t.id}" title="${t.name}" class="${t.id === s.theme ? "active" : ""}" style="background:${THEME_SWATCH[t.id] || "#333"}"></button>`).join("");
  $$("#themeThumbs button").forEach((b) => b.onclick = () => { s.theme = b.dataset.t; renderSettings(); scheduleSave(); });
  bindSetting("#sTheme", "theme");
  bindSetting("#sThink", "think_seconds", { label: "#thinkVal", fmt: (v) => `${v}s` });
  bindSetting("#sReveal", "reveal_seconds", { label: "#revealVal", fmt: (v) => `${v}s` });
  bindSetting("#sReadOptions", "read_options", { type: "checked" });
  bindSetting("#sExplain", "show_explanation", { type: "checked" });
  bindSetting("#sFps", "fps");
  bindSetting("#sProvider", "tts_provider");
  bindSetting("#sRate", "voice_rate", { label: "#rateVal", fmt: (v) => `${v > 0 ? "+" : ""}${v}%` });
  bindSetting("#sPitch", "voice_pitch", { label: "#pitchVal", fmt: (v) => `${v > 0 ? "+" : ""}${v}Hz` });
  bindSetting("#sIntro", "intro_enabled", { type: "checked" });
  bindSetting("#sIntroText", "intro_text");
  bindSetting("#sOutro", "outro_enabled", { type: "checked" });
  bindSetting("#sOutroText", "outro_text");
  bindSetting("#sMusicVol", "music_volume", { label: "#musicVolVal", fmt: (v) => `${Math.round(v * 100)}%` });
  bindSetting("#sSfxVol", "sfx_volume", { label: "#sfxVolVal", fmt: (v) => `${Math.round(v * 100)}%` });
  $("#musicName").textContent = s.music ? `🎵 ${s.music}` : "Sin música";
  loadVoices();
}

async function getVoices(provider, all = false) {
  const key = provider + (all ? ":all" : "");
  if (voiceCache[key]) return voiceCache[key];
  let list = META.voices[provider] || [];
  if (provider === "elevenlabs" || all) {
    try { list = await api(`/api/voices?provider=${provider}`); } catch { list = []; }
  }
  voiceCache[key] = list;
  return list;
}

async function loadVoices(all = false) {
  const s = P.settings;
  let list = await getVoices(s.tts_provider, all);
  if (s.tts_provider === "edge") {
    const byLang = list.filter((v) => v.lang === P.language);
    if (byLang.length) list = [...byLang, ...list.filter((v) => v.lang !== P.language && v.id.includes("Multilingual"))];
  }
  if (s.tts_provider === "elevenlabs" && !list.length) {
    $("#sVoice").innerHTML = `<option value="">Configura ELEVENLABS_API_KEY</option>`;
    return;
  }
  if (!list.find((v) => v.id === s.voice)) {
    if (list.length && s.tts_provider !== "silent") { s.voice = list[0].id; scheduleSave(); }
    if (s.voice && s.tts_provider !== "silent") list = [{ id: s.voice, name: s.voice }, ...list];
  }
  $("#sVoice").innerHTML = list.map((v) => `<option value="${esc(v.id)}">${esc(v.name)}</option>`).join("");
  $("#sVoice").value = s.tts_provider === "silent" ? "none" : s.voice;
  $("#sVoice").onchange = () => { s.voice = $("#sVoice").value; scheduleSave(); };
}

// ---------------------------------------------------------------- vista previa
function refreshPreview() {
  if (!P) return;
  $("#pvImg").src = `/api/projects/${P.id}/preview.jpg?q=${$("#pvQ").value || 0}&phase=${$("#pvPhase").value}&t=${Date.now()}`;
}

// ---------------------------------------------------------------- publicar
function renderPublish() {
  const y = P.youtube;
  $("#ytTitle").value = y.title; $("#ytDesc").value = y.description; $("#ytTags").value = (y.tags || []).join(", ");
  $("#ytPrivacy").value = y.privacy;
  $("#ytTitle").oninput = () => { y.title = $("#ytTitle").value; scheduleSave(); };
  $("#ytDesc").oninput = () => { y.description = $("#ytDesc").value; scheduleSave(); };
  $("#ytTags").oninput = () => { y.tags = $("#ytTags").value.split(",").map((t) => t.trim()).filter(Boolean); scheduleSave(); };
  $("#ytPrivacy").onchange = () => { y.privacy = $("#ytPrivacy").value; scheduleSave(); };
  $("#ytLink").innerHTML = y.video_id ? `✅ Subido: <a href="https://youtu.be/${y.video_id}" target="_blank" rel="noopener">https://youtu.be/${y.video_id}</a>` : "";
  const n = P.questions.length;
  const s = P.settings;
  $("#renderInfo").textContent = `${n} preguntas · ${s.format === "9:16" ? "Shorts 1080×1920" : "1920×1080"} · ${s.think_seconds}s por pregunta · voz: ${s.tts_provider === "silent" ? "ninguna" : s.voice}`;
  showVideo();
  ["#renderJob", "#metaJob", "#uploadJob"].forEach((s) => $(s).classList.add("hidden"));
}

function showVideo() {
  const has = !!P.video_file;
  $("#videoBox").classList.toggle("hidden", !has);
  if (!has) return;
  const v = `?v=${Math.round(P.updated_at)}`;
  $("#video").src = `/files/${P.id}/${P.video_file}${v}`;
  $("#thumb").src = `/files/${P.id}/${P.thumbnail_file}${v}`;
  $("#dlVideo").href = `/files/${P.id}/${P.video_file}?download=1`;
  $("#dlThumb").href = `/files/${P.id}/${P.thumbnail_file}?download=1`;
}

async function watchRender(job) {
  const pid = P.id;
  $("#btnRender").disabled = true;
  await pollJob(job, $("#renderJob"), async () => {
    if (P && P.id === pid) {
      const fresh = await api(`/api/projects/${pid}`);
      P.video_file = fresh.video_file; P.thumbnail_file = fresh.thumbnail_file; P.updated_at = fresh.updated_at;
      if (job.kind === "autopilot") { P = fresh; renderAll(); }
      showVideo();
      toast("🎬 ¡Vídeo listo!");
    }
    loadProjects();
  });
  $("#btnRender").disabled = false;
}

async function refreshYouTube() {
  try {
    const st = await api("/api/youtube/status");
    META.youtube = st;
    const chip = $("#ytChip");
    if (st.connected) { chip.textContent = `YouTube: ${st.channel || "conectado"}`; chip.classList.add("ok"); }
    else { chip.textContent = st.configured ? "YouTube: sin conectar" : "YouTube: sin configurar"; chip.classList.remove("ok"); }
    $("#ytStatus").textContent = st.connected ? `Conectado a ${st.channel || "tu canal"}` :
      st.configured ? "Conecta tu canal para subir vídeos." : "Añade data/client_secret.json para activar la subida (ver README).";
    $("#btnYtConnect").classList.toggle("hidden", st.connected || !st.configured);
    $("#btnYtDisconnect").classList.toggle("hidden", !st.connected);
    $("#btnUpload").disabled = !st.connected;
  } catch {}
}

function switchTab(name) {
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("hidden", t.id !== `tab-${name}`));
  if (name === "preview") refreshPreview();
  if (name === "publish") renderPublish();
}

// ---------------------------------------------------------------- piloto automático
function openAutopilot() {
  $("#apTheme").innerHTML = META.themes.map((t) => `<option value="${t.id}">${t.name}</option>`).join("");
  const fillVoices = () => {
    const lang = $("#apLang").value;
    const vs = META.voices.edge.filter((v) => v.lang === lang || v.id.includes("Multilingual"));
    $("#apVoice").innerHTML = vs.map((v) => `<option value="${v.id}">${esc(v.name)}</option>`).join("");
  };
  $("#apLang").onchange = fillVoices; fillVoices();
  $("#apUpload").disabled = !(META.youtube && META.youtube.connected);
  $("#apModal").classList.remove("hidden");
}

async function startAutopilot() {
  const topics = $("#apTopics").value.split("\n").map((t) => t.trim()).filter(Boolean);
  if (!topics.length) return toast("Escribe al menos un tema", true);
  try {
    const res = await api("/api/autopilot", {
      method: "POST", body: {
        topics, count: +$("#apCount").value, difficulty: $("#apDifficulty").value, language: $("#apLang").value,
        settings: { format: $("#apFormat").value, theme: $("#apTheme").value, voice: $("#apVoice").value, tts_provider: "edge" },
        upload: $("#apUpload").checked, privacy: $("#apPrivacy").value,
      },
    });
    $("#apJobs").innerHTML = res.map((r) => `<div class="ap-job" id="ap-${r.job.id}"><b>${esc(r.topic)}</b>
      <div class="job"><div class="bar"><i></i></div><span>En cola…</span></div></div>`).join("");
    loadProjects();
    res.forEach((r) => pollJob(r.job, $(`#ap-${r.job.id} .job`), () => loadProjects()));
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- eventos
async function init() {
  META = await api("/api/meta");
  $("#aiHint").classList.toggle("hidden", META.ai);
  $("#btnGenerate").disabled = !META.ai;
  refreshYouTube();
  await loadProjects();

  $("#btnNew").onclick = async () => {
    const p = await api("/api/projects", { method: "POST", body: { title: "Nuevo quiz" } });
    await openProject(p.id);
    switchTab("questions");
    $("#aiTopic").focus();
  };
  $("#pTitle").oninput = () => { P.title = $("#pTitle").value; scheduleSave(); };
  $("#pTopic").oninput = () => { P.topic = $("#pTopic").value; scheduleSave(); };
  $("#pLanguage").onchange = () => { P.language = $("#pLanguage").value; scheduleSave(); loadVoices(); };
  $$(".tabs button").forEach((b) => b.onclick = () => switchTab(b.dataset.tab));
  $("#btnAddQ").onclick = $("#btnAddQ2").onclick = addQuestion;

  $("#btnDelete").onclick = async () => {
    if (!confirm(`¿Eliminar "${P.title}" y todos sus archivos?`)) return;
    await api(`/api/projects/${P.id}`, { method: "DELETE" });
    P = null; $("#editor").classList.add("hidden"); $("#empty").classList.remove("hidden");
    loadProjects();
  };
  $("#btnDuplicate").onclick = async () => { await flushSave(); const p = await api(`/api/projects/${P.id}/duplicate`, { method: "POST" }); openProject(p.id); };

  $("#btnGenerate").onclick = async () => {
    const topic = $("#aiTopic").value.trim();
    if (!topic) return toast("Escribe un tema", true);
    await flushSave();
    $("#btnGenerate").disabled = true;
    try {
      const job = await api(`/api/projects/${P.id}/generate`, {
        method: "POST", body: { topic, count: +$("#aiCount").value, difficulty: $("#aiDifficulty").value,
          language: $("#pLanguage").value, extra: $("#aiExtra").value, replace: !$("#aiAppend").checked },
      });
      const pid = P.id;
      await pollJob(job, $("#genJob"), async () => {
        if (P && P.id === pid) { P = await api(`/api/projects/${pid}`); renderAll(); }
        toast("✨ Preguntas generadas");
      });
    } catch (e) { toast(e.message, true); }
    $("#btnGenerate").disabled = false;
  };

  $("#btnImport").onclick = async () => {
    const f = $("#importFile").files[0];
    if (!f) return toast("Elige un archivo CSV o JSON", true);
    await flushSave();
    const fd = new FormData(); fd.append("file", f);
    try {
      P = await api(`/api/projects/${P.id}/import?replace=${$("#importReplace").checked}`, { method: "POST", body: fd });
      renderAll(); toast("Preguntas importadas");
    } catch (e) { toast(e.message, true); }
  };

  $("#btnAllVoices").onclick = () => loadVoices(true);
  $("#btnTestVoice").onclick = async () => {
    const s = P.settings;
    $("#btnTestVoice").disabled = true;
    try {
      const r = await api("/api/tts/test", { method: "POST", body: { provider: s.tts_provider, voice: s.voice, rate: s.voice_rate, pitch: s.voice_pitch, text: $("#ttsText").value } });
      const blob = await r.blob();
      $("#ttsAudio").src = URL.createObjectURL(blob);
      $("#ttsAudio").play();
    } catch (e) { toast(e.message, true); }
    $("#btnTestVoice").disabled = false;
  };

  $("#btnMusic").onclick = async () => {
    const f = $("#musicFile").files[0];
    if (!f) return toast("Elige un archivo de audio", true);
    await flushSave();
    const fd = new FormData(); fd.append("file", f);
    try { const r = await api(`/api/projects/${P.id}/upload?kind=music`, { method: "POST", body: fd }); P = r.project; renderSettings(); toast("Música añadida"); }
    catch (e) { toast(e.message, true); }
  };
  $("#btnNoMusic").onclick = () => { P.settings.music = null; renderSettings(); scheduleSave(); };

  $("#btnPreview").onclick = async () => { await flushSave(); refreshPreview(); };
  $("#pvPhase").onchange = $("#pvQ").onchange = async () => { await flushSave(); refreshPreview(); };

  $("#btnRender").onclick = async () => {
    await flushSave();
    try { const job = await api(`/api/projects/${P.id}/render`, { method: "POST" }); watchRender(job); }
    catch (e) { toast(e.message, true); }
  };
  $("#btnMeta").onclick = async () => {
    await flushSave();
    try {
      const job = await api(`/api/projects/${P.id}/metadata`, { method: "POST" });
      const pid = P.id;
      await pollJob(job, $("#metaJob"), async () => {
        if (P && P.id === pid) { const f = await api(`/api/projects/${pid}`); P.youtube = f.youtube; renderPublish(); }
      });
    } catch (e) { toast(e.message, true); }
  };
  $("#btnUpload").onclick = async () => {
    await flushSave();
    if (!P.video_file) return toast("Primero genera el vídeo", true);
    try {
      const job = await api(`/api/projects/${P.id}/youtube`, { method: "POST" });
      const pid = P.id;
      await pollJob(job, $("#uploadJob"), async () => {
        if (P && P.id === pid) { const f = await api(`/api/projects/${pid}`); P.youtube = f.youtube; renderPublish(); }
        toast("⬆ ¡Subido a YouTube!"); loadProjects();
      });
    } catch (e) { toast(e.message, true); }
  };
  $("#btnYtDisconnect").onclick = async () => { await api("/api/youtube/disconnect", { method: "POST" }); refreshYouTube(); };

  $("#btnAutopilot").onclick = openAutopilot;
  $("#apClose").onclick = () => $("#apModal").classList.add("hidden");
  $("#apStart").onclick = startAutopilot;

  window.addEventListener("beforeunload", () => { if (saveTimer) save(); });
  if (new URLSearchParams(location.search).get("youtube") === "connected") { toast("✅ YouTube conectado"); history.replaceState(null, "", "/"); }
  const last = localStorage.getItem("lastProject");
  if (last) { try { await openProject(last); } catch { localStorage.removeItem("lastProject"); } }
}

init().catch((e) => toast(e.message, true));
