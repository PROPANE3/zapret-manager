/* Zapret Manager v2 frontend: вызовы Rust-команд + рендер. Без сборки. */
const invoke = window.__TAURI__.core.invoke;
const listen = window.__TAURI__.event.listen;

const S = {
  cfg: null, configs: [], checked: {}, results: {}, selGrade: "",
  domFiles: [], domSel: "", logs: [],
  pingHist: { DiscordMain: [], YouTubeWeb: [] },
  vpnCache: null, filters: null,
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------- звук (WebAudio, вместо winsound) ---------- */
let AC = null;
function beep(kind) {
  if (!S.cfg?.sound_enabled) return;
  try {
    AC = AC || new (window.AudioContext || window.webkitAudioContext)();
    const seq = kind === "up" ? [523, 659, 784] : [440, 330];
    seq.forEach((f, i) => {
      const o = AC.createOscillator(), g = AC.createGain();
      o.connect(g); g.connect(AC.destination);
      o.frequency.value = f;
      const t = AC.currentTime + i * 0.16;
      g.gain.setValueAtTime(0.12, t);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.15);
      o.start(t); o.stop(t + 0.16);
    });
  } catch (_) { /* без звука — не ошибка */ }
}

/* ---------- тосты ---------- */
function toast(title, text, kind = "") {
  const d = document.createElement("div");
  d.className = "toast " + kind;
  d.innerHTML = `<b>${esc(title)}</b><span>${esc(text)}</span>`;
  $("toasts").appendChild(d);
  setTimeout(() => d.remove(), 6000);
  if (kind === "good") beep("up");
  if (kind === "bad") beep("down");
}

async function api(cmd, args = {}) {
  try {
    return await invoke(cmd, args);
  } catch (e) {
    toast("Ошибка", String(e?.message ?? e), "bad");
    throw e;
  }
}

/* ---------- модалка ---------- */
function openModal(title, bodyHTML, buttons = []) {
  $("modal-title").textContent = title;
  $("modal-body").innerHTML = bodyHTML;
  const bb = $("modal-btns");
  bb.innerHTML = "";
  for (const [label, cls, fn] of buttons) {
    const b = document.createElement("button");
    b.className = "btn " + cls;
    b.textContent = label;
    b.addEventListener("click", fn);
    bb.appendChild(b);
  }
  $("modal-wrap").classList.remove("hidden");
}
function closeModal() { $("modal-wrap").classList.add("hidden"); }
$("modal-wrap").addEventListener("click", (e) => { if (e.target.id === "modal-wrap") closeModal(); });

/* ---------- навигация ---------- */
const TITLES = {
  check: ["Проверка конфигов", "замер пингов Discord и YouTube по каждому конфигу"],
  domains: ["Домены и списки", "списки обхода и их содержимое"],
  logs: ["Логи проверок", "история замеров"],
  journal: ["Журнал действий", "все переключения и изменения настроек"],
  settings: ["Настройки", "папка, мониторинг, оформление, приложение"],
};
document.querySelectorAll("#nav button").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll("#nav button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    document.querySelectorAll(".page").forEach((p) => p.classList.add("hidden"));
    $("page-" + b.dataset.page).classList.remove("hidden");
    $("page-title").textContent = TITLES[b.dataset.page][0];
    $("page-sub").textContent = TITLES[b.dataset.page][1];
    if (b.dataset.page === "logs") refreshLogs();
    if (b.dataset.page === "journal") refreshJournal();
    if (b.dataset.page === "domains") refreshDomains();
  });
});

/* ---------- тема ---------- */
function applyTheme(name) {
  document.documentElement.dataset.theme = name;
  if (name !== "custom" && name !== "custom-live") document.documentElement.removeAttribute("style");
  document.querySelectorAll("#theme-row button").forEach((b) =>
    b.classList.toggle("accent", b.dataset.theme === name));
}
document.querySelectorAll("#theme-row button").forEach((b) => {
  b.addEventListener("click", async () => {
    await setTheme(b.dataset.theme);
  });
});

/* ---------- hero / статусы ---------- */
function fmtPing(pm) { return pm == null ? "—" : pm + "ms"; }
function pingColor(pm) {
  if (pm == null) return "var(--red)";
  if (pm < 100) return "var(--green)";
  if (pm < 300) return "var(--yellow)";
  return "var(--accent2)";
}

async function refreshActiveBar() {
  const st = await api("get_service_status");
  const active = S.cfg.active_config || st.strategy || "не выбран";
  $("active-name").textContent = active;
  let txt, col;
  if (st.zapret === "RUNNING") {
    txt = `Служба: RUNNING • WinDivert: ${st.windivert} • winws: ${st.winws ? "да" : "нет"}`;
    col = "var(--green)"; setPill("обход: активен (служба)", col);
  } else if (st.winws) {
    txt = "Обход активен (без службы, winws запущен)"; col = "var(--green)";
    setPill("обход: активен", col);
  } else if (st.zapret === "STOPPED") {
    txt = "Служба: STOPPED • winws: нет"; col = "var(--yellow)";
    setPill("zapret: STOPPED", col);
  } else {
    txt = `Служба: ${st.zapret} • winws: нет`; col = "var(--red)";
    setPill(`zapret: ${st.zapret}`, col);
  }
  $("svc-line").textContent = txt;
  $("svc-line").style.color = col;
  // напарник
  if (S.cfg.buddy_enabled && S.cfg.buddy_primary) {
    const cur = S.cfg.active_config;
    const mark = cur === S.cfg.buddy_primary ? "✓ на основном"
      : (cur === S.cfg.buddy_fallback && S.cfg.buddy_fallback ? "→ на запасном" : "→ не на паре");
    $("buddy-line").textContent = `Напарник: ${shortBat(S.cfg.buddy_primary)} → ${S.cfg.buddy_fallback ? shortBat(S.cfg.buddy_fallback) : "?"} (${mark})`;
  } else $("buddy-line").textContent = "";
  // пинги + джиттер (история до 40 замеров, как спарклайны v1)
  try {
    const pts = await api("ping_status");
    for (const p of pts) {
      const el = p.name === "DiscordMain" ? $("ping-ds") : $("ping-yt");
      const tag = p.name === "DiscordMain" ? "DS" : "YT";
      const h = S.pingHist[p.name];
      h.push(p.ping_ms ?? null);
      if (h.length > 40) h.shift();
      const vals = h.filter((v) => v != null);
      let jit = "";
      if (vals.length >= 2) {
        let s = 0;
        for (let i = 1; i < vals.length; i++) s += Math.abs(vals[i] - vals[i - 1]);
        jit = ` ±${(s / (vals.length - 1)).toFixed(0)}`;
      }
      el.textContent = `${tag}: ${fmtPing(p.ping_ms)}${jit}`;
      el.style.color = pingColor(p.ping_ms);
    }
  } catch (_) {}
  // vpn (кэш 60 с — powershell тяжёлый)
  try {
    const now = Date.now();
    if (!S.vpnCache || now - S.vpnCache.ts > 60000) {
      const v = await api("vpn_state");
      S.vpnCache = { ...v, ts: now };
    }
    const v = S.vpnCache;
    $("vpn-line").textContent = v.active ? `VPN: ВКЛ (${v.names.join(", ").slice(0, 60)}) — возможны ошибки!` : "VPN: выкл";
    $("vpn-line").style.color = v.active ? "var(--yellow)" : "";
  } catch (_) {}
  // ресурсы
  try {
    const r = await api("resource_state");
    const parts = [];
    if (r.cpu != null) parts.push(`CPU ${r.cpu.toFixed(0)}%`);
    if (r.ram_mb != null) parts.push(`RAM ${r.ram_mb} МБ`);
    if (r.gpu) parts.push(r.gpu);
    $("res-line").textContent = parts.join(" • ");
  } catch (_) {}
}
function setPill(text, color) {
  const p = $("status-pill");
  p.textContent = text; p.style.color = color;
}
function shortBat(b) {
  const parts = b.split(/[\\/]/);
  const base = parts[parts.length - 1].replace(/\.bat$/i, "");
  const parent = parts.length > 1 ? parts[parts.length - 2] : "";
  return parent && parent.toLowerCase() !== "pre-configs" ? `${parent}\\${base}` : base;
}

/* ---------- конфиги ---------- */
async function refreshConfigs() {
  const list = await api("list_configs");
  S.configs = list;
  const box = $("cfg-list");
  box.innerHTML = "";
  if (!list.length) { box.innerHTML = `<div class="muted">⚠ Конфиги не найдены</div>`; return; }
  for (const c of list) {
    if (!(c.name in S.checked)) S.checked[c.name] = true;
    const fav = (S.cfg.fav_configs || []).includes(c.name);
    const row = document.createElement("div");
    row.className = "cfg-row";
    row.innerHTML = `<button class="star ${fav ? "on" : ""}" title="В избранное">★</button>
      <input type="checkbox" ${S.checked[c.name] ? "checked" : ""}>
      <span class="nm" title="${esc(c.name)}" style="${fav ? "font-weight:bold" : ""}">${esc(c.display)}</span>
      <button class="go" title="Применить сразу">▶</button>`;
    row.querySelector(".star").addEventListener("click", async (e) => {
      e.stopPropagation();
      const favs = S.cfg.fav_configs || [];
      const i = favs.indexOf(c.name);
      if (i >= 0) favs.splice(i, 1); else favs.push(c.name);
      S.cfg.fav_configs = favs;
      await api("save_config", { cfg: S.cfg });
      refreshConfigs();
    });
    row.querySelector("input").addEventListener("change", (e) => { S.checked[c.name] = e.target.checked; });
    row.querySelector(".nm").addEventListener("click", () => {
      S.checked[c.name] = !S.checked[c.name];
      row.querySelector("input").checked = S.checked[c.name];
    });
    row.querySelector(".nm").addEventListener("dblclick", () => applyBat(c.name));
    row.querySelector(".go").addEventListener("click", () => applyBat(c.name));
    box.appendChild(row);
  }
}
function selectedConfigs() { return S.configs.map((c) => c.name).filter((n) => S.checked[n]); }

/* ---------- проверка ---------- */
function setChecking(on) {
  ["btn-check-sel", "btn-check-all", "btn-check-active"].forEach((id) => $(id).disabled = on);
  $("btn-cancel").disabled = !on;
}
async function startCheck(bats) {
  if (!bats.length) { toast("Проверка", "Выберите хотя бы один конфиг", "bad"); return; }
  setChecking(true);
  $("grade-table tbody").innerHTML = "";
  $("check-log").textContent = "";
  $("prog-fill").style.width = "0%";
  $("prog-label").textContent = "Проверка идёт…";
  try {
    const done = await api("run_check", { bats });
    renderResults(done.results);
    $("check-log").textContent = (done.log || []).join("\n");
    $("prog-fill").style.width = "100%";
    $("prog-label").textContent = done.aborted ? "Проверка прервана" : "Готово";
    S.cfg = await api("get_config");
    refreshActiveBar();
  } catch (e) { /* ошибка уже в тосте */ }
  setChecking(false);
}
$("btn-check-sel").addEventListener("click", () => startCheck(selectedConfigs()));
$("btn-check-all").addEventListener("click", () => startCheck(S.configs.map((c) => c.name)));
$("btn-check-active").addEventListener("click", async () => {
  const bat = S.cfg.active_config;
  if (!bat) { toast("Проверка", "Нет активного конфига", "bad"); return; }
  startCheck([bat]);
});
$("btn-cancel").addEventListener("click", () => api("cancel_check"));

function gradeColor(g) {
  return { "Отличный": "var(--green)", "Хороший": "var(--green)", "Средний": "var(--yellow)", "Плохой": "var(--accent2)", "Не работает": "var(--red)" }[g] || "var(--muted)";
}
function renderResults(results) {
  S.results = results;
  const tb = $("grade-table tbody");
  tb.innerHTML = "";
  const rows = Object.entries(results).sort((a, b) => b[1].score - a[1].score);
  for (const [name, r] of rows) {
    const tr = document.createElement("tr");
    if (name === S.selGrade) tr.classList.add("sel");
    tr.innerHTML = `<td>${esc(shortBat(name))}</td>
      <td style="color:${gradeColor(r.grade)};font-weight:bold">${esc(r.grade)}${r.final ? "" : "≈"}</td>
      <td>${fmtPing(r.discord_ms)}</td><td>${fmtPing(r.youtube_ms)}</td>
      <td>${r.score}</td><td><button class="go" title="Применить">▶</button></td>`;
    tr.addEventListener("click", () => { S.selGrade = name; tb.querySelectorAll("tr").forEach((x) => x.classList.remove("sel")); tr.classList.add("sel"); });
    tr.querySelector(".go").addEventListener("click", (e) => { e.stopPropagation(); applyBat(name); });
    tb.appendChild(tr);
  }
}

/* ---------- применение ---------- */
async function applyBat(bat) {
  setPill("установка службы…", "var(--yellow)");
  const r = await api("apply_config", { bat, mode: "service" });
  toast("Применение конфига", r.msg, r.ok ? "good" : "bad");
  S.cfg = await api("get_config");
  refreshActiveBar();
}
$("btn-apply-sel").addEventListener("click", () => {
  if (!S.selGrade) { toast("Применение", "Выберите конфиг в таблице результатов", "bad"); return; }
  applyBat(S.selGrade);
});
$("btn-remove-svc").addEventListener("click", async () => {
  if (!confirm("Удалить службу zapret и остановить обход?")) return;
  const r = await api("remove_service_cmd");
  toast("Служба", r.msg, r.ok ? "good" : "bad");
  refreshActiveBar();
});
$("btn-restart-svc").addEventListener("click", async () => {
  const st = await api("get_service_status").catch(() => null);
  if (st && (st.zapret === "RUNNING" || st.zapret === "STOPPED")) {
    if (!confirm("Перезапустить службу zapret (активный конфиг)?")) return;
    const r = await api("restart_service_cmd");
    toast("Перезапуск", r.msg, r.ok ? "good" : "bad");
  } else if (S.cfg.active_config) {
    if (!confirm(`Перезапустить ${S.cfg.active_config} (без службы)?`)) return;
    const r = await api("restart_standalone_cmd", { bat: S.cfg.active_config });
    toast("Перезапуск", r.msg, r.ok ? "good" : "bad");
  } else toast("Перезапуск", "Нет активного конфига", "bad");
  refreshActiveBar();
});

/* ---------- параметры ---------- */
function renderSeg() {
  document.querySelectorAll("#seg-mode button").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === S.cfg.check_mode));
}
document.querySelectorAll("#seg-mode button").forEach((b) => {
  b.addEventListener("click", async () => {
    S.cfg.check_mode = b.dataset.mode;
    await api("save_config", { cfg: S.cfg });
    renderSeg();
  });
});
$("btn-save-quick").addEventListener("click", async () => {
  S.cfg.check_repeat = Math.min(3, Math.max(1, +$("in-repeat").value || 1));
  S.cfg.ping_threshold_ms = +$("in-thr").value || 5000;
  S.cfg.check_workers = Math.min(16, Math.max(2, +$("in-workers").value || 12));
  await api("save_config", { cfg: S.cfg });
  toast("Параметры", "Сохранено", "good");
});

/* ---------- фильтры Game/IPSet ---------- */
async function refreshFilters() {
  try {
    S.filters = await api("filter_state");
    $("btn-game-filter").textContent = `🎮 Game Filter: ${S.filters.game_mode}`;
    const ipTxt = { loaded: "Загружен", none: "Минимум", any: "Все" }[S.filters.ipset] || S.filters.ipset;
    $("btn-ipset-filter").textContent = `🔢 IPSet Filter: ${ipTxt}`;
  } catch (_) {}
}
$("btn-game-filter").addEventListener("click", async () => {
  await api("game_filter_toggle").catch(() => {});
  refreshFilters();
});
$("btn-ipset-filter").addEventListener("click", async () => {
  try { await api("ipset_toggle"); }
  catch (e) { /* тост уже показан */ }
  refreshFilters();
});

/* ---------- диагностика ---------- */
$("btn-diag").addEventListener("click", async () => {
  const rows = await api("run_diagnostics").catch(() => []);
  const icons = { good: "var(--green)", warn: "var(--yellow)", bad: "var(--red)" };
  openModal("Диагностика", rows.map((r) =>
    `<div class="diag-row"><b style="color:${icons[r.kind] || "var(--text)"}">${esc(r.icon)}</b><span style="width:200px">${esc(r.name)}</span><span style="color:${icons[r.kind] || "var(--text)"}">${esc(r.status)}</span></div>`
  ).join("") || "Нет данных", [
    ["🧹 DNS-кэш", "ghost", async () => { const r = await api("flush_dns"); toast("DNS-кэш", r.msg, r.ok ? "good" : "bad"); }],
    ["🌐 Сброс сети", "ghost", async () => {
      if (!confirm("Сбросить сетевой стек (winsock)? Нужна перезагрузка ПК. Продолжить?")) return;
      const r = await api("net_reset"); toast("Сброс сети", r.msg, r.ok ? "good" : "bad");
    }],
    ["OK", "accent", closeModal],
  ]);
});
/* ---------- секреты, funny, спамтон, стратегии ---------- */
const imgCache = {};
async function imgUrl(cmd, args) {
  const key = cmd + JSON.stringify(args);
  if (imgCache[key]) return imgCache[key];
  const url = await api(cmd, args);
  imgCache[key] = url;
  return url;
}

const SECRET = { pack: null };

async function secretSync() {
  try { SECRET.pack = await api("secret_state"); } catch (_) { SECRET.pack = null; }
  const row = $("secret-toggle-row");
  if (!SECRET.pack) {
    row.classList.add("hidden");
    $("secret-status").textContent = "";
    $("theme-vsd").classList.add("hidden");
    return;
  }
  row.classList.remove("hidden");
  $("secret-toggle-label").textContent = SECRET.pack.title + " оформление";
  const on = !!SECRET.pack.enabled;
  $("set-secret").checked = on;
  $("secret-status").textContent =
    `Набор ${SECRET.pack.title} (${SECRET.pack.files.length}), ${on ? "показывается" : "выключено"}`;
  if (!SECRET.pack.hidden) $("theme-vsd").classList.remove("hidden");
}

async function setTheme(name, save = true) {
  if (SPAM.on && name !== "spamton") spamDisable(false);
  S.cfg.theme = name;
  if (save) await api("save_config", { cfg: S.cfg });
  applyTheme(name);
  paintBricks(name === "spamton");
  paintTermMascot(name === "terminal");
}

$("btn-secret-ok").addEventListener("click", async () => {
  const code = $("secret-code").value.trim();
  if (!code) return;
  try {
    const pack = await api("secret_unlock", { code });
    $("secret-code").value = "";
    S.cfg = await api("get_config");
    await secretSync();
    if (pack.title === "Spamton") spamIntro();
    else {
      await setTheme(pack.theme);
      funApply();
      vsdGallery();
    }
    toast("Секретный набор", `Набор ${pack.title}: файлов ${pack.files.length}`, "good");
  } catch (_) {}
});

$("set-secret").addEventListener("change", async (e) => {
  const on = e.target.checked;
  const pack = SECRET.pack;
  if (!pack) { e.target.checked = false; return; }
  S.cfg = await api("get_config");
  if (pack.title === "Spamton") {
    if (on) {
      if (!pack.files.length) { e.target.checked = false; toast("Набор", "Недоступен", "bad"); return; }
      if (S.cfg.theme !== "spamton") S.cfg.vsd_prev_theme = S.cfg.theme;
      S.cfg.spamton_enabled = true;
      await api("save_config", { cfg: S.cfg });
      SPAM.on = true;
      await setTheme("spamton");
      spamExtrasOn(false);
    } else spamDisable(true);
  } else {
    if (on) {
      if (S.cfg.theme !== pack.theme) S.cfg.vsd_prev_theme = S.cfg.theme;
      S.cfg.vsd_enabled = true;
      await api("save_config", { cfg: S.cfg });
      await setTheme(pack.theme);
      funApply();
      vsdGallery();
    } else {
      S.cfg.vsd_enabled = false;
      await api("save_config", { cfg: S.cfg });
      await setTheme(S.cfg.vsd_prev_theme && S.cfg.vsd_prev_theme !== pack.theme ? S.cfg.vsd_prev_theme : "scarlet");
      funApply();
    }
  }
  S.cfg = await api("get_config");
  await secretSync();
  vsdGallery();
});

/* ----- funny option: телик + фон + иконка ----- */
const FUN = { files: [], bgTimer: null, bgIdx: 0 };
const TV_BY_GRADE = { "Отличный": "excellent.gif", "Хороший": "good.gif", "Средний": "normal.gif", "Плохой": "bad.gif", "Не работает": "no_responce.gif" };

async function funApply() {
  const on = !!S.cfg.silly_mode;
  clearInterval(FUN.bgTimer);
  $("tv").classList.toggle("hidden", !on);
  $("gal-fun").classList.add("hidden");
  try { await api("silly_icon", { on }); } catch (_) {}
  if (!on) return;
  try {
    FUN.files = await api("funny_list");
    $("tv-frame").src = await imgUrl("funny_image", { name: "tv_ts_screen.png" });
    $("tv-screen").src = await imgUrl("funny_image", { name: "idle_gif.gif" });
    const cyc = FUN.files.filter((f) => f === "bg_g.gif" || f === "idle_gif.gif");
    if (cyc.length) {
      const show = async () => {
        FUN.bgIdx = (FUN.bgIdx + 1) % cyc.length;
        try { $("gal-fun").src = await imgUrl("funny_image", { name: cyc[FUN.bgIdx] }); } catch (_) {}
        $("gal-fun").classList.remove("hidden");
      };
      show();
      FUN.bgTimer = setInterval(show, 8000);
    }
  } catch (_) {}
}
function funGradeScreen(results) {
  if (!S.cfg.silly_mode) return;
  const order = ["Отличный", "Хороший", "Средний", "Плохой", "Не работает"];
  let best = "Не работает";
  for (const [, r] of Object.entries(results || {})) {
    if (order.indexOf(r.grade) < order.indexOf(best)) best = r.grade;
  }
  const f = TV_BY_GRADE[best] || "idle_gif.gif";
  imgUrl("funny_image", { name: f }).then((u) => { $("tv-screen").src = u; }).catch(() => {});
}
$("set-funny").addEventListener("change", async (e) => {
  S.cfg.silly_mode = e.target.checked;
  await api("save_config", { cfg: S.cfg });
  funApply();
});

/* ----- галереи ----- */
let vsdTimer = null, vsdIdx = 0;
async function vsdGallery() {
  clearInterval(vsdTimer);
  $("gal-vsd").classList.add("hidden");
  if (SECRET.pack?.title !== "VSD" || !SECRET.pack.enabled) return;
  const files = SECRET.pack.files.filter((f) => f.endsWith(".png"));
  if (!files.length) return;
  const show = async () => {
    vsdIdx = (vsdIdx + 1) % files.length;
    try { $("gal-vsd").src = await imgUrl("pack_image", { title: "VSD", name: files[vsdIdx] }); } catch (_) {}
    $("gal-vsd").classList.remove("hidden");
  };
  show();
  vsdTimer = setInterval(show, 5000);
}
async function spamSideStatic() {
  $("gal-spam").classList.add("hidden");
  const old = $("spam-sky");
  if (old) old.remove();
  if (SECRET.pack?.title !== "Spamton" || !SECRET.pack.enabled) return;
  const f = SECRET.pack.files.find((x) => x.toLowerCase() === "spamton_laugh.gif");
  if (!f) return;
  try {
    const sky = document.createElement("div");
    sky.id = "spam-sky";
    sky.innerHTML = `<div class="sun"></div><div class="cloud c1"></div><div class="cloud c2"></div>`;
    $("gal-spam").before(sky);
    $("gal-spam").src = await imgUrl("pack_image", { title: "Spamton", name: f });
    $("gal-spam").classList.remove("hidden");
  } catch (_) {}
}
async function paintTermMascot(on) {
  const wrap = $("gal-term-wrap");
  wrap.classList.add("hidden");
  if (!on) return;
  try {
    const u = await api("terminal_mascot");
    if (!u) return;
    $("gal-term").src = u;
    wrap.classList.remove("hidden");
  } catch (_) {}
}

/* ----- кирпич ----- */
function paintBricks(on) {
  $("brick-top").classList.toggle("hidden", !on);
  $("brick-bottom").classList.toggle("hidden", !on);
}

/* ----- спамтон-движок ----- */
const SPAM = {
  on: false, sayT: null, shopT: null, nos: 0,
  quotes: ["HELLO, MY FRIEND! IT'S ME, SPAMTON G. SPAMTON!", "YOU WANT IT! YOU WANT [[HyperlinkBlocked]], DON'T YOU?", "I'M A [[BIG SHOT]] NOW!", "HAVE YOU EVER HEARD OF [Free Kromer]?", "DON'T FORGET! [[KROMER]] MAKES THE WORLD GO ROUND!", "WOWIE! A CUSTOMER!! COME ON IN!", "NO ONE CAN STOP THE [[BIG SHOT]] EXPRESS!", "THAT'S MY [Special Price]! JUST FOR YOU!"],
  goods: [["S. POTION", "5 KROMER"], ["[[Leftover Pippis]]", "15 KROMER"], ["KEYGEN 1997", "30 KROMER"], ["TRASH CAN (MINT)", "50 KROMER"], ["LANCER COOKIES", "2 KROMER"], ["[HyperlinkBlocked]", "??? KROMER"], ["BIG SHOT BOWTIE", "100 KROMER"], ["DEAL-A-DAY LENS", "25 KROMER"]],
  ads: [["PIPPIS!!", "50% OFF", "EAT NOW"], ["[[KROMER]]", "FREE*", "*NOT FREE"], ["BIG SHOT", "BE ONE", "CLICK!"], ["WIRE SALE", "-99%", "TODAY"], ["KEYGEN", "PRO 1997", "DOWNLOAD"], ["DEALS!!", "DEALS!!", "DEALS!!"]],
  adWins: [],
};
function spamClearTimers() {
  ["sayT", "shopT"].forEach((k) => { if (SPAM[k]) { clearTimeout(SPAM[k]); SPAM[k] = null; } });
  SPAM.adWins.forEach((w) => { try { w.el.remove(); } catch (_) {} clearInterval(w.tick); clearTimeout(w.die); });
  SPAM.adWins = [];
  const s = $("spam-say");
  if (s) s.classList.add("hidden");
  const b = $("blackout");
  if (b) { b.classList.add("hidden"); b.innerHTML = ""; }
}
function spamExtrasOn() {
  SPAM.on = true;
  spamSideStatic();
  spamSaySchedule(true);
  spamShopSchedule();
}
function spamDisable(restore) {
  SPAM.on = false;
  SPAM.nos = 0;
  spamClearTimers();
  $("gal-spam").classList.add("hidden");
  const sky = $("spam-sky");
  if (sky) sky.remove();
  paintBricks(false);
  if (restore) {
    const prev = S.cfg.vsd_prev_theme && S.cfg.vsd_prev_theme !== "spamton" ? S.cfg.vsd_prev_theme : "scarlet";
    S.cfg.spamton_enabled = false;
    api("save_config", { cfg: S.cfg }).then(() => setTheme(prev));
  } else {
    S.cfg.spamton_enabled = false;
    api("save_config", { cfg: S.cfg });
  }
  secretSync();
  vsdGallery();
}
async function spamIntro() {
  const ov = $("spam-intro");
  try {
    const u = await imgUrl("pack_image", { title: "Spamton", name: "Spamton_came.gif" });
    $("spam-intro-img").src = u;
  } catch (_) { spamIntroEnd(); return; }
  ov.classList.remove("hidden");
  const done = () => spamIntroEnd();
  ov.onclick = done;
  setTimeout(done, 3600);
}
async function spamIntroEnd() {
  const ov = $("spam-intro");
  if (ov.classList.contains("hidden")) return;
  ov.classList.add("hidden");
  ov.onclick = null;
  SPAM.on = true;
  await setTheme("spamton");
  paintBricks(true);
  spamSideStatic();
  spamSaySchedule(true);
  spamShopSchedule();
  S.cfg = await api("get_config");
  await secretSync();
  vsdGallery();
}
function spamSaySchedule(first) {
  clearTimeout(SPAM.sayT);
  if (!SPAM.on) return;
  SPAM.sayT = setTimeout(spamSay, (first ? 20 + Math.random() * 20 : 45 + Math.random() * 75) * 1000);
}
function spamSay() {
  if (!SPAM.on) return;
  const s = $("spam-say");
  s.textContent = SPAM.quotes[Math.floor(Math.random() * SPAM.quotes.length)];
  s.classList.remove("hidden");
  setTimeout(() => s.classList.add("hidden"), 6000);
  spamSaySchedule(false);
}
function spamShopSchedule() {
  clearTimeout(SPAM.shopT);
  if (!SPAM.on) return;
  SPAM.shopT = setTimeout(spamShopOffer, (180 + Math.random() * 240) * 1000);
}
async function spamShopOffer() {
  if (!SPAM.on || !$("blackout").classList.contains("hidden")) { spamShopSchedule(); return; }
  const [name, price] = SPAM.goods[Math.floor(Math.random() * SPAM.goods.length)];
  let portrait = "";
  try { portrait = `<img class="spam-portrait" src="${await imgUrl("pack_image", { title: "Spamton", name: "ref.png" })}">`; } catch (_) {}
  openModal("SPAMTON G. SPAMTON",
    `${portrait}<div>BUY ${esc(name)}?</div><div class="spam-price">ONLY ${esc(price)}!!</div><div style="clear:both"></div>`, [
    ["[[YES]]", "accent", () => { closeModal(); SPAM.nos = 0; spamAds(); spamShopSchedule(); }],
    ["no...", "ghost", () => {
      closeModal();
      SPAM.nos++;
      if (SPAM.nos >= 3) { SPAM.nos = 0; spamBlackout(); spamShopSchedule(); return; }
      toast("SPAMTON", "WHY NOT?? DEAL'S GONE!", "");
      spamShopSchedule();
    }],
  ]);
  $("modal-card").id = "spam-shop-card";
}
const _origCloseModal = closeModal;
closeModal = function () {
  _origCloseModal();
  const m = $("modal-card");
  if (m) m.id = "modal-card";
};
function spamAds() {
  if (!SPAM.on) return;
  const bgs = ["#FFE600", "#FF8AC2", "#7FD4F7", "#FFFFFF", "#B6F09C"];
  for (let i = 0; i < 7; i++) {
    const [a, b, c] = SPAM.ads[Math.floor(Math.random() * SPAM.ads.length)];
    const el = document.createElement("div");
    el.className = "spam-ad";
    el.innerHTML = `<div class="in" style="background:${bgs[i % bgs.length]}"><div style="font-size:18px">${esc(a)}</div><div style="color:#C1121F">${esc(b)}</div><div style="background:#111;color:#FFE600;margin-top:6px;padding:4px">${esc(c)}</div></div>`;
    el.style.left = Math.random() * (innerWidth - 240) + "px";
    el.style.top = Math.random() * (innerHeight - 160) + "px";
    el.addEventListener("click", () => spamAdClose(w));
    document.body.appendChild(el);
    const w = { el, dx: [-3, -2, 2, 3][i % 4], dy: i % 2 ? 2 : -2, tick: null, die: null };
    w.tick = setInterval(() => {
      let x = el.offsetLeft + w.dx, y = el.offsetTop + w.dy;
      if (x <= 0 || x >= innerWidth - 230) { w.dx *= -1; x = Math.max(0, Math.min(innerWidth - 230, x)); }
      if (y <= 0 || y >= innerHeight - 150) { w.dy *= -1; y = Math.max(0, Math.min(innerHeight - 150, y)); }
      el.style.left = x + "px"; el.style.top = y + "px";
    }, 80);
    w.die = setTimeout(() => spamAdClose(w), 10000);
    SPAM.adWins.push(w);
  }
}
function spamAdClose(w) {
  try { clearInterval(w.tick); clearTimeout(w.die); w.el.remove(); } catch (_) {}
  SPAM.adWins = SPAM.adWins.filter((x) => x !== w);
}
function spamBlackout() {
  const b = $("blackout");
  b.classList.remove("hidden");
  b.innerHTML = `<div class="lamp-cord" id="bl-cord"></div><div class="lamp-shade" id="bl-shade"></div><div class="lamp-bulb" id="bl-bulb"></div><div class="beam" id="bl-beam"></div><button class="yesbtn" id="bl-yes">[[YES]]</button>`;
  const layout = (t) => {
    const w = innerWidth, h = innerHeight, cx = w / 2;
    const shift = Math.round(110 * Math.sin(t * 0.22));
    const set = (id, l, top, wd, ht) => { const e = $(id); e.style.left = l + "px"; e.style.top = top + "px"; if (wd) e.style.width = wd + "px"; if (ht) e.style.height = ht + "px"; };
    set("bl-cord", cx - 2, 0, 4, 34);
    set("bl-shade", cx - 34, 30, 68, 32);
    set("bl-bulb", cx - 9, 56, 18, 18);
    const beam = $("bl-beam");
    beam.style.left = "0px"; beam.style.top = "70px"; beam.style.width = w + "px"; beam.style.height = (h - 70) + "px";
    beam.style.clipPath = `polygon(${cx - 26}px 0, ${cx + 26}px 0, ${cx + 190 + shift}px 100%, ${cx - 190 + shift}px 100%)`;
    const yes = $("bl-yes");
    yes.style.left = (cx + shift - 60) + "px";
    yes.style.top = Math.round(h * 0.62) + "px";
  };
  let t = 0;
  layout(0);
  const tick = setInterval(() => {
    if ($("blackout").classList.contains("hidden")) { clearInterval(tick); return; }
    layout(++t);
  }, 120);
  b._tick = tick;
  const end = (purchased) => {
    clearInterval(tick);
    b.classList.add("hidden"); b.innerHTML = "";
    if (purchased) {
      toast("SPAMTON", "PLEASURE DOING BUSINESS!!", "good");
      spamAds();
    }
    spamShopSchedule();
  };
  $("bl-yes").addEventListener("click", () => end(true));
  b.onkeydown = (e) => { if (e.key === "Escape") end(false); };
  b.tabIndex = -1; b.focus();
}
$("btn-dom-diff").addEventListener("click", async () => {
  const d = await api("release_diff").catch(() => null);
  if (!d) return;
  const sec = (t, arr, cls) => arr.length
    ? `<div class="sect">${t}</div>` + arr.map((x) => `<div class="${cls}">${esc(x)}</div>`).join("")
    : "";
  const empty = !d.added.length && !d.removed.length && !d.changed.length;
  openModal("Diff списков", empty ? "Изменений относительно снимка нет." :
    sec("Добавлены", d.added, "diff-add") + sec("Удалены", d.removed, "diff-del") + sec("Изменены", d.changed, "diff-chg"), [
    ["Закрыть", "accent", closeModal],
  ]);
});
$("btn-dom-snap").addEventListener("click", async () => {
  const r = await api("lists_snapshot_save").catch(() => null);
  if (r) toast("Снимок", r.msg, "good");
});
async function refreshDomains() {
  S.domFiles = await api("list_lists");
  const box = $("dom-list");
  box.innerHTML = "";
  for (const f of S.domFiles) {
    const row = document.createElement("div");
    row.className = "dom-row" + (f.name === S.domSel ? " sel" : "");
    row.innerHTML = `<span class="dom-dot ${f.enabled ? "on" : "off"}">●</span><span style="flex:1">${esc(f.name)}</span><input type="checkbox" ${f.enabled ? "checked" : ""} title="вкл/выкл">`;
    row.addEventListener("click", async (e) => {
      if (e.target.type === "checkbox") {
        const r = await api("toggle_list", { name: f.name, enable: e.target.checked });
        toast("Списки", r.msg, r.ok ? "good" : "bad");
        refreshDomains();
        return;
      }
      S.domSel = f.name;
      box.querySelectorAll(".dom-row").forEach((x) => x.classList.remove("sel"));
      row.classList.add("sel");
      showDomain(f.name);
    });
    box.appendChild(row);
  }
  if (!S.domFiles.length) box.innerHTML = `<div class="muted">Папка lists/ не найдена</div>`;
}
async function showDomain(name) {
  try {
    const text = await api("read_list", { name });
    $("dom-title").textContent = `${name} (${text.split("\n").length} строк)`;
    $("dom-text").value = text;
  } catch (e) { /* тост уже показан */ }
}
$("btn-dom-save").addEventListener("click", async () => {
  if (!S.domSel) { toast("Списки", "Выберите файл слева", "bad"); return; }
  const r = await api("save_list", { name: S.domSel, content: $("dom-text").value });
  toast("Списки", r.msg, r.ok ? "good" : "bad");
  showDomain(S.domSel);
});
$("btn-dom-refresh").addEventListener("click", refreshDomains);
$("btn-dom-new").addEventListener("click", async () => {
  const name = prompt("Имя нового списка (например, mylist-user.txt):", "mylist-user.txt");
  if (!name) return;
  try {
    const r = await api("create_list", { name });
    toast("Списки", r.msg, "good");
    S.domSel = name.endsWith(".txt") ? name : name + ".txt";
    refreshDomains();
  } catch (_) {}
});

/* ---------- логи / журнал ---------- */
async function refreshLogs() {
  const files = await api("read_checks");
  const box = $("logs-list");
  box.innerHTML = "";
  const mkRow = (label, fn) => {
    const row = document.createElement("div");
    row.className = "dom-row";
    row.textContent = label;
    row.addEventListener("click", () => {
      box.querySelectorAll(".dom-row").forEach((x) => x.classList.remove("sel"));
      row.classList.add("sel");
      fn();
    });
    box.appendChild(row);
    return row;
  };
  mkRow("🔄 Переключения", async () => {
    const lines = await api("read_switches", { limit: 500 }).catch(() => []);
    $("log-view").textContent = lines.join("\n") || "Пока пусто — переключений не было.";
  });
  for (const f of files) {
    const row = document.createElement("div");
    row.className = "dom-row";
    row.textContent = f;
    row.addEventListener("click", async () => {
      box.querySelectorAll(".dom-row").forEach((x) => x.classList.remove("sel"));
      row.classList.add("sel");
      try {
        const raw = await api("read_check_file", { name: f });
        const data = JSON.parse(raw);
        let out = `Время: ${data.time || ""}\nАктивный: ${data.active || "—"}\nРежим: ${data.mode || ""}\n\n`;
        for (const [cfg, s] of Object.entries(data.summary || {})) {
          out += `${cfg}: DS=${fmtPing(s.discord_ms)} YT=${fmtPing(s.youtube_ms)} [${s.grade}] (OK=${s.ok} ERR=${s.fail})\n`;
        }
        $("log-view").textContent = out;
      } catch (_) {}
    });
    box.appendChild(row);
  }
  if (!files.length) box.innerHTML = `<div class="muted">Пока пусто — запустите проверку.</div>`;
}
$("btn-logs-refresh").addEventListener("click", refreshLogs);
async function refreshJournal() {
  const lines = await api("read_actions", { limit: 500 });
  $("journal-view").textContent = lines.join("\n") || "Пока пусто.";
}
$("btn-journal-refresh").addEventListener("click", refreshJournal);

/* ---------- настройки ---------- */
async function loadSettings() {
  $("set-root").value = S.cfg.zapret_root || "";
  $("set-mon").checked = !!S.cfg.monitor_enabled;
  $("set-sound").checked = !!S.cfg.sound_enabled;
  $("set-interval").value = S.cfg.monitor_interval_min;
  $("set-timeout").value = S.cfg.check_timeout_s;
  $("set-buddy").checked = !!S.cfg.buddy_enabled;
  $("set-wdreturn").value = S.cfg.watchdog_return_min || 15;
  $("in-repeat").value = S.cfg.check_repeat;
  $("in-thr").value = S.cfg.ping_threshold_ms;
  $("in-workers").value = S.cfg.check_workers;
  renderSeg();
  paintBuddy();
  $("set-autostart").checked = await api("autostart_status").catch(() => false);
}
$("btn-autodetect").addEventListener("click", async () => {
  const r = await api("autodetect_root");
  if (r) $("set-root").value = r;
  else toast("Папка", "Не нашёл сам — укажите вручную", "bad");
});
$("btn-save-root").addEventListener("click", async () => {
  S.cfg.zapret_root = $("set-root").value.trim();
  await api("save_config", { cfg: S.cfg });
  toast("Папка", "Сохранено", "good");
  refreshConfigs(); refreshActiveBar();
});
$("btn-save-mon").addEventListener("click", async () => {
  S.cfg.monitor_enabled = $("set-mon").checked;
  S.cfg.sound_enabled = $("set-sound").checked;
  S.cfg.monitor_interval_min = Math.max(1, +$("set-interval").value || 3);
  S.cfg.check_timeout_s = Math.min(30, Math.max(2, +$("set-timeout").value || 4));
  S.cfg.watchdog_return_min = Math.max(5, +$("set-wdreturn").value || 15);
  S.cfg.buddy_enabled = $("set-buddy").checked;
  await api("save_config", { cfg: S.cfg });
  await api("monitor_stop").catch(() => {});
  if (S.cfg.monitor_enabled) await api("monitor_start").catch(() => {});
  toast("Мониторинг", "Сохранено", "good");
  paintBuddy(); refreshActiveBar();
});
function paintBuddy() {
  $("buddy-pair").textContent = S.cfg.buddy_primary
    ? `Пара: ${shortBat(S.cfg.buddy_primary)} → ${S.cfg.buddy_fallback ? shortBat(S.cfg.buddy_fallback) : "— подберётся при падении"}`
    : "Пара не назначена";
}
$("btn-buddy-assign").addEventListener("click", async () => {
  if (!S.cfg.active_config) { toast("Напарник", "Нет активного конфига", "bad"); return; }
  S.cfg.buddy_primary = S.cfg.active_config;
  S.cfg.buddy_fallback = "";
  await api("save_config", { cfg: S.cfg });
  paintBuddy(); refreshActiveBar();
});
$("btn-data-folder").addEventListener("click", () => api("open_data_folder"));
$("btn-flush-dns").addEventListener("click", async () => {
  const r = await api("flush_dns");
  toast("DNS-кэш", r.msg, r.ok ? "good" : "bad");
});
$("set-autostart").addEventListener("change", async (e) => {
  const r = await api("set_autostart", { enable: e.target.checked });
  if (!r.ok) { toast("Автозагрузка", r.msg, "bad"); e.target.checked = !e.target.checked; }
  else if (r.msg) toast("Автозагрузка", r.msg, "good");
});

/* ---------- события из Rust ---------- */
/* ---------- шрифты живьём (без перезапуска) ---------- */
const FONT_FAMS = ["Trebuchet MS", "Calibri", "Segoe UI", "Verdana", "Tahoma", "Arial"];
function applyFont() {
  const fam = localStorage.getItem("zm-font") || "Trebuchet MS";
  const scale = +(localStorage.getItem("zm-scale") || 100);
  document.body.style.fontFamily = `"${fam}", "Segoe UI", sans-serif`;
  document.documentElement.style.fontSize = (14 * scale / 100) + "px";
  const sel = $("font-fam");
  if (sel && !sel.options.length) {
    FONT_FAMS.forEach((f) => {
      const o = document.createElement("option");
      o.value = f; o.textContent = f; o.style.fontFamily = `"${f}", sans-serif`;
      sel.appendChild(o);
    });
  }
  if (sel) sel.value = fam;
  const sc = $("font-scale");
  if (sc) sc.value = scale;
}
$("font-fam")?.addEventListener("change", (e) => {
  localStorage.setItem("zm-font", e.target.value);
  applyFont();
});
$("font-scale")?.addEventListener("input", (e) => {
  localStorage.setItem("zm-scale", e.target.value);
  applyFont();
});

/* ---------- вотчер сна (скачок wall-clock) ---------- */
let lastTick = Date.now();
setInterval(async () => {
  const now = Date.now();
  const jumped = now - lastTick;
  lastTick = now;
  if (jumped < 90000) return;
  toast("💤 Пробуждение", "ПК проснулся из сна — проверяю связь…", "");
  try {
    const pts = await api("ping_status");
    const bad = pts.filter((p) => p.ping_ms == null).length;
    toast("💤 После сна", bad ? "Связь плохая — мониторинг подберёт конфиг." : "Связь в порядке.", bad ? "bad" : "good");
  } catch (_) {}
}, 15000);

/* ---------- игровой режим: UI ---------- */
$("btn-save-game").addEventListener("click", async () => {
  S.cfg.game_procs = $("set-game-procs").value;
  S.cfg.game_mode = $("set-game").checked;
  await api("save_config", { cfg: S.cfg });
  toast("Игровой режим", "Сохранено", "good");
});

/* ---------- приложение: ярлык, кэш, экспорт, обновления ---------- */
$("btn-shortcut").addEventListener("click", async () => {
  const r = await api("make_shortcut").catch(() => null);
  if (r) toast("Ярлык", r.msg, r.ok ? "good" : "bad");
});
$("btn-icon-cache").addEventListener("click", async () => {
  if (!confirm("Сбросить кэш иконок Windows? Проводник на секунду перезапустится.")) return;
  const r = await api("refresh_icon_cache").catch(() => null);
  if (r) toast("Кэш иконок", r.msg, r.ok ? "good" : "bad");
});
$("btn-export").addEventListener("click", async () => {
  try {
    const r = await api("export_report");
    toast("Отчёт", r.msg, "good");
    api("open_data_folder");
  } catch (_) {}
});
$("btn-updates").addEventListener("click", async () => {
  $("update-info").textContent = "Проверяю…";
  $("update-info").innerHTML = "";
  try {
    const u = await api("check_updates");
    if (u.zapret_tag) {
      const b = document.createElement("button");
      b.className = "btn ghost"; b.textContent = `⬇ zapret ${u.zapret_tag}`;
      b.addEventListener("click", () => api("open_url", { url: u.zapret_url }));
      $("update-info").appendChild(b);
    }
  } catch (_) {}
  try {
    const upd = await api("app_update_check");
    if (upd) {
      const b = document.createElement("button");
      b.className = "btn accent"; b.textContent = `⬇ Менеджер v${upd.version} — установить`;
      b.title = upd.body.slice(0, 300);
      b.addEventListener("click", async () => {
        if (!confirm(`Установить v${upd.version}? Приложение перезапустится.`)) return;
        toast("Обновление", "Скачиваю и ставлю…", "");
        try { await api("app_update_install"); }
        catch (e) { toast("Обновление", "Не удалось", "bad"); }
      });
      $("update-info").appendChild(b);
    } else if (!$("update-info").children.length) {
      $("update-info").textContent = "Всё свежее.";
    }
  } catch (_) {
    if (!$("update-info").children.length) $("update-info").textContent = "Не удалось проверить.";
  }
});

/* ---------- своя тема: редактор ---------- */
const THEME_KEYS = ["BG", "TITLEBAR_BG", "SIDEBAR", "CARD", "CARD2", "BORDER", "TEXT", "MUTED", "ACCENT", "ACCENT_HOVER", "ACCENT_DEEP", "ACCENT2"];
const THEME_CSS = { BG: "--bg", TITLEBAR_BG: "--titlebar", SIDEBAR: "--sidebar", CARD: "--card", CARD2: "--card2", BORDER: "--border", TEXT: "--text", MUTED: "--muted", ACCENT: "--accent", ACCENT_HOVER: "--accent-hover", ACCENT_DEEP: "--accent-deep", ACCENT2: "--accent2" };
function buildThemeEditor() {
  const g = $("custom-theme-grid");
  g.innerHTML = "";
  const cur = S.cfg.custom_theme || {};
  for (const k of THEME_KEYS) {
    const lab = document.createElement("label");
    lab.innerHTML = `${k} <input type="color" data-k="${k}" value="${cur[k] || "#000000"}">`;
    g.appendChild(lab);
  }
  g.querySelectorAll("input").forEach((inp) => {
    inp.addEventListener("input", () => {
      document.documentElement.style.setProperty(THEME_CSS[inp.dataset.k], inp.value);
      document.documentElement.dataset.theme = "custom-live";
    });
  });
}
function readThemeEditor() {
  const pal = {};
  document.querySelectorAll("#custom-theme-grid input").forEach((inp) => { pal[inp.dataset.k] = inp.value; });
  return pal;
}
function applyCustomTheme() {
  const pal = S.cfg.custom_theme || {};
  for (const k of THEME_KEYS) {
    if (pal[k]) document.documentElement.style.setProperty(THEME_CSS[k], pal[k]);
  }
  document.documentElement.dataset.theme = "custom";
  document.querySelectorAll("#theme-row button").forEach((b) => b.classList.remove("accent"));
}
$("btn-theme-save").addEventListener("click", async () => {
  S.cfg.custom_theme = readThemeEditor();
  S.cfg.theme = "custom";
  await api("save_config", { cfg: S.cfg });
  applyCustomTheme();
  toast("Своя тема", "Сохранено", "good");
});
$("btn-theme-export").addEventListener("click", () => {
  const json = JSON.stringify({ name: "custom", palette: readThemeEditor() }, null, 2);
  openModal("Экспорт темы", `<textarea style="width:100%;min-height:200px;font-family:Consolas,monospace">${esc(json)}</textarea><div class="btn-row" style="margin-top:8px"><button class="btn accent" id="theme-copy">📋 Копировать</button></div>`, [["Закрыть", "ghost", () => closeModal()]]);
  $("theme-copy").addEventListener("click", () => {
    navigator.clipboard?.writeText(json).then(() => toast("Тема", "Скопировано", "good")).catch(() => {});
  });
});
$("btn-theme-import").addEventListener("click", () => {
  openModal("Импорт темы", `<textarea id="theme-import-text" style="width:100%;min-height:200px;font-family:Consolas,monospace" placeholder='{"palette": {...}}'></textarea>`, [
    ["Применить", "accent", () => {
      try {
        const data = JSON.parse($("theme-import-text").value);
        const pal = data.palette || data;
        for (const k of THEME_KEYS) {
          if (typeof pal[k] === "string" && /^#[0-9a-fA-F]{6}$/.test(pal[k])) {
            document.documentElement.style.setProperty(THEME_CSS[k], pal[k]);
            const inp = document.querySelector(`#custom-theme-grid input[data-k="${k}"]`);
            if (inp) inp.value = pal[k];
          }
        }
        document.documentElement.dataset.theme = "custom-live";
        closeModal();
        toast("Тема", "Импортировано — не забудьте Сохранить", "good");
      } catch (_) { toast("Тема", "Неверный JSON", "bad"); }
    }],
    ["Отмена", "ghost", () => closeModal()],
  ]);
});
$("btn-theme-reset").addEventListener("click", async () => {
  S.cfg.custom_theme = {};
  S.cfg.theme = "scarlet";
  await api("save_config", { cfg: S.cfg });
  document.documentElement.removeAttribute("style");
  applyTheme("scarlet");
  buildThemeEditor();
});
const STRAT_PRESETS = {
  "fake": "--dpi-desync=fake --dpi-desync-repeats=6",
  "multisplit": "--dpi-desync=multisplit --dpi-desync-split-seqovl=681 --dpi-desync-split-pos=1",
  "disorder": "--dpi-desync=disorder --dpi-desync-split-pos=1",
  "без desync": "",
};
let STRAT = null;
$("btn-strategy").addEventListener("click", async () => {
  const bat = S.selGrade || S.cfg.active_config;
  if (!bat) { toast("Стратегии", "Выберите конфиг в таблице", "bad"); return; }
  try {
    STRAT = await api("strategy_parse", { bat });
    STRAT.idx = 0;
    renderStrategy();
  } catch (_) {}
});
function stratTitle(b) {
  const m = b.match(/--filter-[^\s]+(?:=[^\s]+)?/);
  if (!m) return (b.slice(0, 60) || "(пустой блок)");
  const d = b.match(/--dpi-desync=([^\s]+)/);
  return d ? `${m[0]}  •  ${d[1]}` : m[0];
}
function renderStrategy() {
  const items = STRAT.blocks.map((b, i) =>
    `<div class="dom-row ${i === STRAT.idx ? "sel" : ""}" data-i="${i}">${i + 1}. ${esc(stratTitle(b))}</div>`).join("");
  openModal(`🧬 Стратегии — ${esc(STRAT.bat)}`,
    `<div style="display:flex;gap:10px"><div style="width:260px;max-height:300px;overflow:auto">${items}</div>
     <div style="flex:1"><textarea id="strat-text" spellcheck="false" style="width:100%;min-height:200px;font-family:Consolas,monospace"></textarea>
     <div class="btn-row" style="margin-top:8px"><select id="strat-preset">${Object.keys(STRAT_PRESETS).map((k) => `<option>${k}</option>`).join("")}</select>
     <button class="btn ghost" id="strat-apply-preset">Шаблон</button>
     <button class="btn ghost" id="strat-add">＋ Блок</button>
     <button class="btn ghost" id="strat-dup">⧉ Дублировать</button>
     <button class="btn ghost" id="strat-del">✕ Удалить</button></div></div></div>`, [
    ["💾 Как новый", "accent", () => stratSave(true)],
    ["💾 Перезаписать (.bak)", "ghost", () => { if (confirm("Перезаписать исходный bat? Старая копия — в .bak.")) stratSave(false); }],
    ["Отмена", "ghost", () => closeModal()],
  ]);
  const sync = () => {
    document.querySelectorAll("#modal-body .dom-row").forEach((r) =>
      r.classList.toggle("sel", +r.dataset.i === STRAT.idx));
    $("strat-text").value = STRAT.blocks[STRAT.idx] || "";
  };
  document.querySelectorAll("#modal-body .dom-row").forEach((r) =>
    r.addEventListener("click", () => { STRAT.blocks[STRAT.idx] = $("strat-text").value; STRAT.idx = +r.dataset.i; sync(); }));
  sync();
  $("strat-apply-preset").addEventListener("click", () => {
    let b = $("strat-text").value.replace(/\s*--dpi-desync[^\s]*/g, "").replace(/\s+/g, " ").trim();
    const p = STRAT_PRESETS[$("strat-preset").value];
    if (p) b = (b + " " + p).trim();
    $("strat-text").value = b;
    STRAT.blocks[STRAT.idx] = b;
    renderStrategy();
  });
  $("strat-add").addEventListener("click", () => {
    STRAT.blocks.push("--filter-tcp=80,443 --dpi-desync=fake --dpi-desync-repeats=6");
    STRAT.idx = STRAT.blocks.length - 1;
    renderStrategy();
  });
  $("strat-dup").addEventListener("click", () => {
    STRAT.blocks.splice(STRAT.idx + 1, 0, STRAT.blocks[STRAT.idx] || "");
    renderStrategy();
  });
  $("strat-del").addEventListener("click", () => {
    if (STRAT.blocks.length <= 1) { toast("Стратегии", "Нельзя удалить последний блок", "bad"); return; }
    STRAT.blocks.splice(STRAT.idx, 1);
    STRAT.idx = 0;
    renderStrategy();
  });
}
async function stratSave(asNew) {
  STRAT.blocks[STRAT.idx] = $("strat-text").value;
  const blks = STRAT.blocks.map((b) => b.trim()).filter(Boolean);
  if (!blks.length) { toast("Стратегии", "Нет ни одного блока", "bad"); return; }
  const nofilt = blks.map((b, i) => b.includes("--filter") ? -1 : i + 1).filter((x) => x > 0);
  if (nofilt.length && !confirm(`Блоки без --filter: ${nofilt.join(", ")}. Сохранить всё равно?`)) return;
  let name = null;
  if (asNew) {
    name = prompt("Имя нового файла:", STRAT.bat.replace(/\.bat$/i, "") + " (strategy).bat");
    if (!name) return;
  }
  try {
    const saved = await api("strategy_save", { bat: STRAT.bat, blocks: blks, asNew: name });
    toast("Стратегии", `Сохранено: ${saved}`, "good");
    closeModal();
    refreshConfigs();
  } catch (_) {}
}

/* ---------- мастер первого запуска ---------- */
async function maybeWizard() {
  if (localStorage.getItem("zm-wizard") === "1") return false;
  const cfgs = await api("list_configs").catch(() => []);
  const hasScores = S.cfg.best_scores && Object.keys(S.cfg.best_scores).length > 0;
  if (cfgs.length && hasScores) { localStorage.setItem("zm-wizard", "1"); return false; }
  openWizard();
  return true;
}
function openWizard() {
  const W = { step: 0, shortcut: true };
  const wiz = $("wizard");
  wiz.classList.remove("hidden");
  const show = () => {
    const titles = ["Шаг 1/3 — папка zapret", "Шаг 2/3 — проверка конфигов", "Шаг 3/3 — применить лучший"];
    $("wizard-sub").textContent = titles[W.step];
    const body = $("wizard-body"), nav = $("wizard-nav");
    body.innerHTML = ""; nav.innerHTML = "";
    const back = document.createElement("button");
    back.className = "btn ghost"; back.textContent = "← Назад"; back.disabled = W.step === 0;
    back.addEventListener("click", () => { W.step--; show(); });
    const close = document.createElement("button");
    close.className = "btn ghost"; close.textContent = "Закрыть";
    close.addEventListener("click", () => { wiz.classList.add("hidden"); localStorage.setItem("zm-wizard", "1"); startTour(); });
    const next = document.createElement("button");
    next.className = "btn accent"; next.textContent = W.step < 2 ? "Далее →" : "Готово";
    nav.append(back, next, close);
    if (W.step === 0) {
      body.innerHTML = `<div class="muted" style="margin-bottom:8px">Где лежит zapret (general.bat, service.bat, bin/, lists/)?</div>
        <div class="btn-row"><input id="wiz-root" style="flex:1" value="${esc(S.cfg.zapret_root || "")}">
        <button class="btn ghost" id="wiz-find">🔍 Найти</button></div>
        <label class="row" style="margin-top:8px"><span>Ярлык на рабочем столе</span><input type="checkbox" id="wiz-shortcut" class="switch" checked></label>
        <div class="muted small">Нет папки? После мастера: Настройки → Папка (там же переустановка скачает свежий релиз).</div>`;
      $("wiz-find").addEventListener("click", async () => {
        const r = await api("autodetect_root").catch(() => null);
        if (r) $("wiz-root").value = r;
        else toast("Папка", "Не нашёл сам — укажите вручную", "bad");
      });
      next.addEventListener("click", async () => {
        const v = $("wiz-root").value.trim();
        if (!v) { toast("Мастер", "Укажите папку", "bad"); return; }
        W.shortcut = $("wiz-shortcut").checked;
        S.cfg.zapret_root = v;
        await api("save_config", { cfg: S.cfg });
        const cfgs = await api("list_configs").catch(() => []);
        if (!cfgs.length) { toast("Мастер", "В папке нет .bat — проверьте путь", "bad"); return; }
        W.step = 1; show();
        refreshConfigs();
      });
    } else if (W.step === 1) {
      body.innerHTML = `<div id="wiz-status">Нажмите «Запустить проверку» — это несколько минут.</div>
        <div class="btn-row" style="margin-top:10px"><button class="btn accent" id="wiz-run">▶ Запустить проверку</button></div>`;
      $("wiz-run").addEventListener("click", async () => {
        $("wiz-status").textContent = "Проверка идёт… можно подождать.";
        $("wiz-run").disabled = true;
        await startCheck(S.configs.map((c) => c.name));
        const n = S.cfg.best_scores ? Object.keys(S.cfg.best_scores).length : 0;
        $("wiz-status").textContent = `Готово! Оценок: ${n}. Жмите «Далее →».`;
      });
      next.addEventListener("click", () => { W.step = 2; show(); });
    } else {
      const scores = S.cfg.best_scores || {};
      const win = Object.keys(scores).sort((a, b) => scores[b] - scores[a])[0];
      body.innerHTML = win
        ? `<div style="font-size:16px;font-weight:bold">🏆 Лучший: ${esc(shortBat(win))} (score=${scores[win]})</div>
           <div class="muted" style="margin-top:6px">Применение ставит службу Windows с автозагрузкой.</div>`
        : `<div>Оценок нет — проверьте позже вручную.</div>`;
      next.textContent = win ? "✔ Применить и завершить" : "Завершить";
      next.addEventListener("click", async () => {
        wiz.classList.add("hidden");
        localStorage.setItem("zm-wizard", "1");
        if (W.shortcut) api("make_shortcut").catch(() => {});
        if (win) applyBat(win);
        startTour();
      });
    }
  };
  show();
}

/* ---------- тур подсказок ---------- */
const TOUR = [
  ["#nav button[data-page='check']", "1. Проверка", "Здесь конфиги: галочки + большая кнопка. Замер пингов, оценки, даблклик — применить."],
  ["#active-name", "2. Что активно", "Текущий конфиг, служба, живые пинги и напарник."],
  ["#btn-check-sel", "3. Запуск", "Проверить выбранные, все или только активный."],
  ["#nav button[data-page='domains']", "4. Домены", "Списки обхода: правка, новые листы, diff."],
  ["#nav button[data-page='settings']", "5. Настройки", "Папка, мониторинг, темы, приложение. Приятного обхода!"],
];
function startTour() {
  if (localStorage.getItem("zm-tour") === "1") return;
  tourStep(0);
}
function tourStep(i) {
  const tip = $("tour-tip");
  if (i >= TOUR.length) { tip.classList.add("hidden"); localStorage.setItem("zm-tour", "1"); return; }
  const [sel, title, text] = TOUR[i];
  const el = document.querySelector(sel);
  if (!el) { tourStep(i + 1); return; }
  const r = el.getBoundingClientRect();
  tip.innerHTML = `<b>${title} (${i + 1}/${TOUR.length})</b><div style="margin:6px 0 10px">${text}</div>
    <div class="btn-row"><button class="btn accent" id="tour-next">${i + 1 < TOUR.length ? "Далее →" : "Готово ✓"}</button>
    <button class="btn ghost" id="tour-skip">Пропустить</button></div>`;
  tip.classList.remove("hidden");
  tip.style.left = Math.min(innerWidth - 340, r.right + 10) + "px";
  tip.style.top = Math.min(innerHeight - 200, r.bottom + 8) + "px";
  $("tour-next").addEventListener("click", () => tourStep(i + 1));
  $("tour-skip").addEventListener("click", () => { tip.classList.add("hidden"); localStorage.setItem("zm-tour", "1"); });
}

/* ---------- переустановка zapret ---------- */
$("btn-reinstall").addEventListener("click", async () => {
  const root = $("set-root").value.trim() || S.cfg.zapret_root;
  if (!confirm(`Переустановить Zapret?\n\nПапка: ${root}\nСлужба и обход остановятся, папка заменится свежим релизом.\nСписки (*-user.txt, настройки) сохранятся.`)) return;
  $("btn-reinstall").disabled = true;
  $("reinstall-prog").classList.remove("hidden");
  $("reinstall-fill").style.width = "2%";
  $("reinstall-status").textContent = "старт…";
  try {
    const done = await api("reinstall_zapret");
    $("reinstall-fill").style.width = "100%";
    $("reinstall-status").textContent = done.ok ? `Готово: ${done.tag}` : `Ошибка: ${done.msg}`;
    toast("Переустановка", done.ok ? done.msg : done.msg, done.ok ? "good" : "bad");
    if (done.ok) {
      if (done.diff) openModal("Списки изменились", `<div class="logbox">${esc(done.diff)}</div>`, [["Понятно", "accent", () => closeModal()]]);
      refreshConfigs();
      refreshActiveBar();
    }
  } catch (_) {
    $("reinstall-status").textContent = "Ошибка";
  }
  $("btn-reinstall").disabled = false;
  setTimeout(() => $("reinstall-prog").classList.add("hidden"), 4000);
});
async function bootSecrets() {
  await secretSync();
  $("set-funny").checked = !!S.cfg.silly_mode;
  funApply();
  vsdGallery();
  paintTermMascot(S.cfg.theme === "terminal");
  paintBricks(S.cfg.theme === "spamton");
  if (SECRET.pack?.title === "Spamton" && SECRET.pack.enabled && SECRET.pack.files.length) {
    SPAM.on = true;
    spamSideStatic();
    spamSaySchedule(true);
    spamShopSchedule();
  }
}

async function boot() {
  S.cfg = await api("get_config");
  applyFont();
  if (S.cfg.theme === "custom" && S.cfg.custom_theme && Object.keys(S.cfg.custom_theme).length) applyCustomTheme();
  else applyTheme(S.cfg.theme || "scarlet");
  await loadSettings();
  $("set-game").checked = !!S.cfg.game_mode;
  $("set-game-procs").value = S.cfg.game_procs || "";
  buildThemeEditor();
  await refreshConfigs();
  await refreshActiveBar();
  await refreshFilters();
  await bootSecrets();
  const wiz = await maybeWizard();
  if (!wiz) setTimeout(startTour, 2500);
  await api("monitor_start").catch(() => {});
  await listen("check-progress", (e) => {
    const p = e.payload;
    $("prog-fill").style.width = (100 * p.done / Math.max(1, p.total)) + "%";
    $("prog-label").textContent = `[${p.done}/${p.total}] ${p.name} — score ${p.score}`;
  });
  await listen("check-done", (e) => {
    renderResults(e.payload.results || {});
    funGradeScreen(e.payload.results || {});
    setChecking(false);
    $("prog-fill").style.width = "100%";
  });
  await listen("toast", (e) => {
    const t = e.payload;
    toast(t.title, t.text, t.kind === "good" ? "good" : t.kind === "bad" ? "bad" : "");
    refreshActiveBar();
  });
  await listen("status-refresh", () => refreshActiveBar());
  await listen("reinstall-progress", (e) => {
    const p = e.payload || {};
    $("reinstall-prog").classList.remove("hidden");
    if (p.phase === "progress") {
      const m = String(p.detail || "").match(/(\d+)%/);
      if (m) $("reinstall-fill").style.width = m[1] + "%";
      $("reinstall-status").textContent = "скачивание: " + (p.detail || "");
    } else {
      $("reinstall-status").textContent = p.detail || "";
    }
  });
  setInterval(refreshActiveBar, 15000);
}
document.addEventListener("DOMContentLoaded", () => boot().catch((e) => {
  document.body.innerHTML = "<pre style='padding:40px'>Не удалось связаться с ядром: " + esc(e) + "</pre>";
}));
