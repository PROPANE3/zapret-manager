//! Zapret Manager v2 (Tauri 2): точка входа, команды, мониторинг.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod config;
mod engine;
mod fun;
mod reinstall;
mod zapret;

use config::AppConfig;
use engine::BatResult;
use serde::Serialize;
use std::collections::HashMap;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::time::Duration;
use tauri::{Emitter, Manager};

// ================= состояние =================

pub struct CheckState {
    pub cancel: Arc<AtomicBool>,
    pub running: AtomicBool,
}

pub struct MonitorState {
    pub handle: Mutex<Option<tokio::task::JoinHandle<()>>>,
    pub wd_primary: Mutex<String>,
    pub wd_fallback: Mutex<String>,
    pub wd_due_unix: Mutex<u64>,
}

pub struct ReinstallState {
    pub running: AtomicBool,
}

fn unix_now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

// ================= логи =================

fn actions_path() -> std::path::PathBuf {
    config::data_dir().join("actions.log")
}

fn switches_path() -> std::path::PathBuf {
    config::data_dir().join("switches.log")
}

fn ts_now() -> String {
    // Локальное время без chrono: civil_from_days по дням эпохи (UTC).
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    // дней с эпохи -> дата (алгоритм Ховарда Хиннанта, days_to_civil)
    let z = secs / 86400 + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    let t = secs % 86400;
    format!("{y:04}-{m:02}-{d:02} {:02}:{:02}:{:02}", t / 3600, (t / 60) % 60, t % 60)
}

pub(crate) fn log_action(text: &str, kind: &str) {
    let _ = std::fs::create_dir_all(config::data_dir());
    let line = format!("[{}] [{}] {}\n", ts_now(), kind, text);
    use std::io::Write;
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(actions_path())
    {
        let _ = f.write_all(line.as_bytes());
    }
}

fn log_switch(text: &str) {
    let _ = std::fs::create_dir_all(config::data_dir());
    let line = format!("[{}] {}\n", ts_now(), text);
    use std::io::Write;
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(switches_path())
    {
        let _ = f.write_all(line.as_bytes());
    }
}

fn read_tail(path: &std::path::Path, limit: usize) -> Vec<String> {
    std::fs::read_to_string(path)
        .map(|s| {
            let v: Vec<String> = s.lines().map(|l| l.to_string()).collect();
            v.into_iter().rev().take(limit).collect::<Vec<_>>().into_iter().rev().collect()
        })
        .unwrap_or_default()
}

// ================= DTO =================

#[derive(Debug, Clone, Serialize)]
pub struct CmdResult {
    pub ok: bool,
    pub msg: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ConfigEntry {
    pub name: String,
    pub display: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct FrontendResult {
    pub ok: u64,
    pub fail: u64,
    pub ping_ok: u64,
    pub score: i64,
    pub started: bool,
    #[serde(rename = "final")]
    pub final_: bool,
    pub grade: String,
    pub discord_ms: Option<u64>,
    pub youtube_ms: Option<u64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CheckDone {
    pub results: HashMap<String, FrontendResult>,
    pub aborted: String,
    pub log: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ToastEvent {
    pub title: String,
    pub text: String,
    pub kind: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ListEntry {
    pub name: String,
    pub enabled: bool,
}

// ================= команды =================

#[tauri::command]
fn get_version() -> String {
    "2.0.0".into()
}

#[tauri::command]
fn get_config() -> AppConfig {
    config::load()
}

#[tauri::command]
fn save_config(cfg: AppConfig) -> AppConfig {
    config::save(&cfg);
    cfg
}

#[tauri::command]
fn autodetect_root() -> Option<String> {
    config::autodetect_root()
}

#[tauri::command]
fn list_configs() -> Vec<ConfigEntry> {
    let cfg = config::load();
    let favs = cfg.fav_configs.clone();
    let mut v: Vec<ConfigEntry> = zapret::list_configs(&cfg.zapret_root)
        .into_iter()
        .map(|n| {
            let d = zapret::display_bat(&n);
            ConfigEntry { name: n, display: d }
        })
        .collect();
    // избранное сверху
    v.sort_by_key(|e| (!favs.contains(&e.name), e.name.to_lowercase()));
    v
}

#[tauri::command]
fn get_service_status() -> zapret::ServiceStatus {
    zapret::service_status()
}

#[tauri::command]
fn apply_config(app: tauri::AppHandle, bat: String, mode: String) -> CmdResult {
    let mut cfg = config::load();
    if mode == "once" {
        // разовый запуск без службы
        let st = zapret::service_status();
        if st.zapret == "RUNNING" || st.zapret == "STOPPED" {
            zapret::remove_service();
            std::thread::sleep(Duration::from_secs(1));
        }
        zapret::stop_winws();
        std::thread::sleep(Duration::from_millis(500));
        let ok = zapret::start_winws_hidden(&cfg.zapret_root, &bat);
        let running = zapret::wait_winws_alive(Duration::from_secs(6));
        if ok && running {
            cfg.active_config = bat.clone();
            config::save(&cfg);
            log_action(&format!("Вручную запущен конфиг без службы: {bat}"), "apply");
            log_switch(&format!("разово → {bat}"));
            return CmdResult { ok: true, msg: format!("{bat} запущен (без автозагрузки)") };
        }
        log_action(&format!("Ошибка разового запуска {bat}"), "error");
        return CmdResult { ok: false, msg: format!("{bat}: не запустился (см. журнал)") };
    }
    let (ok, msg) = zapret::install_service(&cfg.zapret_root, &bat);
    if ok {
        cfg.active_config = bat.clone();
        config::save(&cfg);
        // ручной выбор снимает план возврата watchdog
        if let Some(ms) = app.try_state::<MonitorState>() {
            *ms.wd_primary.lock().unwrap() = String::new();
            *ms.wd_fallback.lock().unwrap() = String::new();
            *ms.wd_due_unix.lock().unwrap() = 0;
        }
        log_action(&format!("Вручную применён конфиг {bat}: {msg}"), "apply");
        log_switch(&format!("вручную → {bat}"));
    } else {
        log_action(&format!("Ошибка установки {bat}: {msg}"), "error");
    }
    CmdResult { ok, msg: format!("{bat}: {msg}") }
}

#[tauri::command]
fn remove_service_cmd() -> CmdResult {
    let (ok, msg) = zapret::remove_service();
    log_action(&format!("Удаление службы: {msg}"), "apply");
    log_switch("служба удалена (обход выключен)");
    CmdResult { ok, msg }
}

#[tauri::command]
fn restart_service_cmd() -> CmdResult {
    let (ok, msg) = zapret::restart_service();
    log_action(&format!("Перезапуск службы: {msg}"), "apply");
    CmdResult { ok, msg }
}

#[tauri::command]
fn restart_standalone_cmd(bat: String) -> CmdResult {
    let cfg = config::load();
    if bat.is_empty() {
        return CmdResult { ok: false, msg: "Нет активного конфига".into() };
    }
    let (ok, msg) = zapret::restart_standalone(&cfg.zapret_root, &bat);
    log_action(&format!("Перезапуск конфига без службы: {msg}"), "apply");
    CmdResult { ok, msg }
}

#[tauri::command]
fn net_reset() -> CmdResult {
    let (ok, msg) = zapret::net_reset();
    log_action(&format!("Сброс сети: {msg}"), if ok { "net" } else { "error" });
    CmdResult { ok, msg }
}

// ---------- game/ipset фильтры ----------

#[derive(Debug, Clone, Serialize)]
pub struct FilterState {
    pub game_on: bool,
    pub game_mode: String,
    pub ipset: String,
}

#[tauri::command]
fn filter_state() -> FilterState {
    let cfg = config::load();
    let (game_on, game_mode) = zapret::game_filter_status(&cfg.zapret_root);
    FilterState { game_on, game_mode, ipset: zapret::ipset_status(&cfg.zapret_root) }
}

#[tauri::command]
fn game_filter_toggle() -> FilterState {
    let cfg = config::load();
    let mode = zapret::game_filter_cycle(&cfg.zapret_root);
    log_action(&format!("Game Filter: {mode}"), "info");
    filter_state()
}

#[tauri::command]
fn ipset_toggle() -> Result<FilterState, String> {
    let cfg = config::load();
    let st = zapret::ipset_cycle(&cfg.zapret_root)?;
    log_action(&format!("IPSet Filter: {st}"), "info");
    Ok(filter_state())
}

// ---------- диагностика / vpn / ресурсы ----------

#[tauri::command]
fn run_diagnostics() -> Vec<zapret::DiagRow> {
    zapret::run_diagnostics()
}

#[derive(Debug, Clone, Serialize)]
pub struct VpnState {
    pub active: bool,
    pub names: Vec<String>,
}

#[tauri::command]
fn vpn_state() -> VpnState {
    let (active, names) = zapret::vpn_status();
    VpnState { active, names }
}

#[tauri::command]
fn resource_state() -> zapret::ResourceStat {
    zapret::resource_status()
}

// ---------- экспорт отчёта ----------

#[tauri::command]
fn export_report() -> Result<CmdResult, String> {
    let cfg = config::load();
    let mut l: Vec<String> = vec![
        "# Отчёт Zapret Manager v2.0.0".into(),
        String::new(),
        format!("Время: {}", ts_now()),
        format!("Корень zapret: `{}`", cfg.zapret_root),
        format!("Активный конфиг: `{}`", if cfg.active_config.is_empty() { "—" } else { &cfg.active_config }),
        String::new(),
        "## Службы".into(),
    ];
    let st = zapret::service_status();
    l.push(format!(
        "zapret: `{}` • WinDivert: `{}` • winws: `{}`",
        st.zapret,
        st.windivert,
        if st.winws { "да" } else { "нет" }
    ));
    if !st.strategy.is_empty() {
        l.push(format!("Стратегия службы: `{}`", st.strategy));
    }
    if !cfg.best_scores.is_empty() {
        l.push(String::new());
        l.push("## Оценки конфигов (топ-10)".into());
        let mut v: Vec<_> = cfg.best_scores.iter().collect();
        v.sort_by_key(|(_, s)| -**s);
        for (k, s) in v.into_iter().take(10) {
            l.push(format!("- `{k}` — {s}"));
        }
    }
    l.push(String::new());
    l.push("## Переключения (последние 100)".into());
    l.push("```".into());
    let sw = read_tail(&switches_path(), 100);
    l.push(if sw.is_empty() { "(пусто)".into() } else { sw.join("\n") });
    l.push("```".into());
    l.push(String::new());
    l.push("## Журнал действий (последние 200)".into());
    l.push("```".into());
    let acts = read_tail(&actions_path(), 200);
    l.push(if acts.is_empty() { "(пусто)".into() } else { acts.join("\n") });
    l.push("```".into());
    let fp = config::data_dir().join(format!("zapret-report-{}.md", ts_now().replace([':', ' '], "-")));
    std::fs::write(&fp, l.join("\n") + "\n").map_err(|e| e.to_string())?;
    log_action(&format!("Отчёт выгружен: {}", fp.file_name().and_then(|n| n.to_str()).unwrap_or("")), "info");
    Ok(CmdResult {
        ok: true,
        msg: format!("Сохранено: {} (папка данных)", fp.file_name().and_then(|n| n.to_str()).unwrap_or("")),
    })
}

// ---------- ярлык / кэш иконок / обновления ----------

#[tauri::command]
fn make_shortcut() -> CmdResult {
    let exe = std::env::current_exe().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default();
    if exe.is_empty() {
        return CmdResult { ok: false, msg: "Не найден путь exe".into() };
    }
    let dir = std::path::Path::new(&exe).parent().map(|d| d.to_string_lossy().into_owned()).unwrap_or_default();
    let ps = format!(
        "$d=[Environment]::GetFolderPath('Desktop');$p=\"$d\\Zapret Manager v2.lnk\";$s=(New-Object -ComObject WScript.Shell).CreateShortcut($p);$s.TargetPath='{exe}';$s.WorkingDirectory='{dir}';$s.IconLocation='{exe},0';$s.Description='Zapret Manager v2';$s.Save();Write-Output $p"
    );
    let (rc, out) = zapret::run_cmd(
        &["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", &ps],
        std::time::Duration::from_secs(25),
    );
    let lnk = out.lines().last().unwrap_or("").trim().to_string();
    if rc == 0 && !lnk.is_empty() && std::path::Path::new(&lnk).exists() {
        log_action(&format!("Создан ярлык: {lnk}"), "info");
        CmdResult { ok: true, msg: format!("Ярлык создан:\n{lnk}") }
    } else {
        CmdResult { ok: false, msg: format!("Не удалось: {}", out.trim().chars().take(200).collect::<String>()) }
    }
}

#[tauri::command]
fn refresh_icon_cache() -> CmdResult {
    // как в v1: снести IconCache*.db и перезапустить проводник
    let home = std::env::var("USERPROFILE").unwrap_or_default();
    let cache = format!("{home}\\AppData\\Local\\Microsoft\\Windows\\Explorer");
    zapret::run_cmd(&["taskkill", "/f", "/im", "explorer.exe"], std::time::Duration::from_secs(15));
    std::thread::sleep(std::time::Duration::from_secs(1));
    let mut removed = 0;
    for pat in ["IconCache.db", "iconcache_*.db"] {
        let prefix = pat.trim_end_matches("*.db").trim_end_matches('*');
        let is_wild = pat.contains('*');
        if let Ok(rd) = std::fs::read_dir(&cache) {
            for e in rd.flatten() {
                if let Some(n) = e.file_name().to_str() {
                    let hit = if is_wild {
                        n.to_lowercase().starts_with(&prefix.to_lowercase()) && n.to_lowercase().ends_with(".db")
                    } else {
                        n.eq_ignore_ascii_case(pat)
                    };
                    if hit && std::fs::remove_file(e.path()).is_ok() {
                        removed += 1;
                    }
                }
            }
        }
    }
    zapret::run_cmd(&["explorer.exe"], std::time::Duration::from_secs(10));
    log_action(&format!("Сброшен кэш иконок ({removed} файлов)"), "info");
    CmdResult { ok: true, msg: format!("Удалено файлов кэша: {removed}. Если иконка не сменилась — перезагрузите ПК.") }
}

#[derive(Debug, Clone, Serialize)]
pub struct UpdateInfo {
    pub zapret_tag: String,
    pub zapret_url: String,
    pub app_version: String,
    pub app_url: String,
}

fn http_get_text(url: &str, timeout_s: u64) -> Result<String, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(timeout_s))
        .user_agent("ZapretManager-v2")
        .build()
        .map_err(|e| e.to_string())?;
    client.get(url).send().map_err(|e| e.to_string())?.text().map_err(|e| e.to_string())
}

/// Проверка обновлений: свежий релиз zapret + version.txt нашего репозитория.
#[tauri::command]
fn check_updates() -> UpdateInfo {
    let mut info = UpdateInfo {
        zapret_tag: String::new(),
        zapret_url: "https://github.com/Flowseal/zapret-discord-youtube/releases/latest".into(),
        app_version: String::new(),
        app_url: "https://github.com/PROPANE3/zapret-manager/releases".into(),
    };
    if let Ok(text) = http_get_text("https://api.github.com/repos/Flowseal/zapret-discord-youtube/releases/latest", 20) {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(&text) {
            if let Some(tag) = v.get("tag_name").and_then(|t| t.as_str()) {
                info.zapret_tag = tag.to_string();
            }
            if let Some(arr) = v.get("assets").and_then(|a| a.as_array()) {
                for a in arr {
                    let nm = a.get("name").and_then(|n| n.as_str()).unwrap_or("");
                    if nm.starts_with("zapret-discord-youtube-") && nm.ends_with(".zip") {
                        if let Some(u) = a.get("browser_download_url").and_then(|u| u.as_str()) {
                            info.zapret_url = u.to_string();
                        }
                        break;
                    }
                }
            }
        }
    }
    if let Ok(text) = http_get_text("https://raw.githubusercontent.com/PROPANE3/zapret-manager/main/version.txt", 15) {
        let ver = text.trim().to_string();
        if !ver.is_empty() && ver != "2.0.0" {
            info.app_version = ver;
        }
    }
    info
}

#[tauri::command]
fn open_url(url: String) {
    let _ = zapret::run_cmd(&["cmd", "/c", "start", "", &url], std::time::Duration::from_secs(10));
}

// ---------- переустановка zapret ----------

#[tauri::command]
async fn reinstall_zapret(app: tauri::AppHandle, state: tauri::State<'_, ReinstallState>) -> Result<reinstall::ReinstallDone, String> {
    if state.running.swap(true, Ordering::Relaxed) {
        return Ok(reinstall::ReinstallDone {
            ok: false,
            msg: "Переустановка уже идёт".into(),
            tag: String::new(),
            diff: String::new(),
        });
    }
    let root = config::load().zapret_root.clone();
    let done = reinstall::run(app.clone(), root).await;
    state.running.store(false, Ordering::Relaxed);
    let _ = app.emit(
        "reinstall-done",
        serde_json::json!({ "ok": done.ok, "msg": done.msg, "tag": done.tag, "diff": done.diff }),
    );
    Ok(done)
}

// ---------- diff списков ----------

fn snapshot_path() -> std::path::PathBuf {
    config::data_dir().join("lists_snapshot.json")
}

fn load_snapshot() -> HashMap<String, String> {
    std::fs::read_to_string(snapshot_path())
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

#[tauri::command]
fn lists_snapshot_save() -> CmdResult {
    let cfg = config::load();
    let snap = zapret::snapshot_lists(&cfg.zapret_root);
    let _ = std::fs::create_dir_all(config::data_dir());
    let _ = std::fs::write(snapshot_path(), serde_json::to_string_pretty(&snap).unwrap_or_default());
    CmdResult { ok: true, msg: format!("Снимок сохранён (файлов: {})", snap.len()) }
}

#[tauri::command]
fn release_diff() -> zapret::ListsDiff {
    let cfg = config::load();
    zapret::diff_snaps(&load_snapshot(), &zapret::snapshot_lists(&cfg.zapret_root))
}

// ---------- история переключений ----------

#[tauri::command]
fn read_switches(limit: usize) -> Vec<String> {
    read_tail(&switches_path(), limit.min(2000))
}

#[tauri::command]
fn cancel_check(state: tauri::State<'_, CheckState>) {
    state.cancel.store(true, Ordering::Relaxed);
}

fn to_frontend(map: &HashMap<String, BatResult>) -> HashMap<String, FrontendResult> {
    map.iter()
        .map(|(k, v)| {
            let (dm, ym, grade) = engine::grade_of(&v.rows);
            let grade = if v.started { grade.to_string() } else { "Не работает".to_string() };
            (
                k.clone(),
                FrontendResult {
                    ok: v.ok,
                    fail: v.fail,
                    ping_ok: v.ping_ok,
                    score: v.score,
                    started: v.started,
                    final_: v.final_,
                    grade,
                    discord_ms: dm,
                    youtube_ms: ym,
                },
            )
        })
        .collect()
}

#[tauri::command]
async fn run_check(
    app: tauri::AppHandle,
    state: tauri::State<'_, CheckState>,
    bats: Vec<String>,
) -> Result<CheckDone, String> {
    if state.running.load(Ordering::Relaxed) {
        return Err("Проверка уже идёт".into());
    }
    state.running.store(true, Ordering::Relaxed);
    state.cancel.store(false, Ordering::Relaxed);
    // общий флаг отмены: фронт ставит state.cancel, колбэк прогресса
    // пробрасывает его в движок (проверка между конфигами)
    let cancel_flag = state.cancel.clone();
    let app_c = app.clone();
    let cfg = config::load();
    let mode = cfg.check_mode.clone();
    let mut workers = cfg.check_workers;
    let cpu = num_cpus();
    workers = workers.max(cpu * 2).min(16);
    let ctx = engine::Ctx {
        root: cfg.zapret_root.clone(),
        timeout_s: cfg.check_timeout_s,
        ping_thr: cfg.ping_threshold_ms,
        repeat: cfg.check_repeat,
        workers,
        cancel: cancel_flag.clone(),
    };
    let had_service = zapret::service_status().zapret == "RUNNING";
    let app_p = app.clone();
    let (results, mut aborted, logs) = engine::run_check(
        &ctx,
        bats,
        &mode,
        |done, total, name, score| {
            if state.cancel.load(Ordering::Relaxed) {
                cancel_flag.store(true, Ordering::Relaxed);
            }
            let _ = app_c.emit(
                "check-progress",
                engine::ProgressEvent { done, total, name: name.to_string(), score },
            );
        },
        |bat, name, ping_ms| {
            // мгновенный пинг цели — без ожидания счёта конфига
            let _ = app_p.emit(
                "probe-ping",
                serde_json::json!({ "bat": bat, "name": name, "ping_ms": ping_ms }),
            );
        },
    )
    .await;
    if state.cancel.load(Ordering::Relaxed) && aborted.is_empty() {
        aborted = "cancelled".into();
    }
    // восстановить службу, если была
    if had_service {
        let active = config::load().active_config.clone();
        if !active.is_empty() {
            let root = config::load().zapret_root.clone();
            let _ = zapret::install_service(&root, &active);
        }
    }
    // очки + история
    let mut cfg2 = config::load();
    for (b, r) in &results {
        if r.started {
            cfg2.best_scores.insert(b.clone(), r.score);
        }
    }
    config::save(&cfg2);
    save_check_history(&cfg2, &mode, &results);
    state.running.store(false, Ordering::Relaxed);
    let done = CheckDone { results: to_frontend(&results), aborted, log: logs };
    let _ = app.emit("check-done", &done);
    Ok(done)
}

fn num_cpus() -> usize {
    std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4)
}

fn save_check_history(cfg: &AppConfig, mode: &str, results: &HashMap<String, BatResult>) {
    use std::io::Write;
    let _ = std::fs::create_dir_all(config::checks_dir());
    let ts = ts_now().replace([':', ' '], "-");
    let mut summary = serde_json::Map::new();
    for (k, v) in results {
        let (dm, ym, grade) = engine::grade_of(&v.rows);
        summary.insert(
            k.clone(),
            serde_json::json!({
                "ok": v.ok, "fail": v.fail, "ping_ok": v.ping_ok, "score": v.score,
                "discord_ms": dm, "youtube_ms": ym,
                "grade": if v.started { grade } else { "Не работает" },
                "final": v.final_, "mode": mode,
            }),
        );
    }
    let doc = serde_json::json!({
        "time": ts_now(), "active": cfg.active_config,
        "mode": mode, "summary": summary,
    });
    let path = config::checks_dir().join(format!("check_{ts}.json"));
    if let Ok(mut f) = std::fs::File::create(path) {
        let _ = f.write_all(serde_json::to_string_pretty(&doc).unwrap_or_default().as_bytes());
    }
}

// ================= мониторинг =================

#[tauri::command]
async fn monitor_start(app: tauri::AppHandle, state: tauri::State<'_, MonitorState>) -> Result<bool, String> {
    monitor_stop_inner(&state);
    let app_c = app.clone();
    let h = tokio::spawn(async move { monitor_loop(app_c).await });
    *state.handle.lock().unwrap() = Some(h);
    log_action("Мониторинг запущен", "info");
    Ok(true)
}

#[tauri::command]
fn monitor_stop(state: tauri::State<'_, MonitorState>) -> bool {
    monitor_stop_inner(&state);
    log_action("Мониторинг остановлен", "info");
    true
}

fn monitor_stop_inner(state: &tauri::State<'_, MonitorState>) {
    if let Some(h) = state.handle.lock().unwrap().take() {
        h.abort();
    }
}

/// Игра из списка запущена? (один tasklist, как в v1)
fn game_running(procs_csv: &str) -> Option<String> {
    let procs: Vec<String> = procs_csv
        .split(',')
        .map(|p| {
            let p = p.trim().to_lowercase();
            if p.is_empty() || p.ends_with(".exe") {
                p
            } else {
                format!("{p}.exe")
            }
        })
        .filter(|p| !p.is_empty())
        .collect();
    if procs.is_empty() {
        return None;
    }
    let (_rc, out) = zapret::run_cmd(&["tasklist", "/FO", "CSV", "/NH"], std::time::Duration::from_secs(10));
    let low = out.to_lowercase();
    procs.into_iter().find(|p| low.contains(&format!("\"{p}\"")))
}

async fn monitor_loop(app: tauri::AppHandle) {
    tokio::time::sleep(Duration::from_secs(15)).await;
    let mut game_noticed = false;
    loop {
        let cfg = config::load();
        if !cfg.monitor_enabled {
            break;
        }
        // игровой режим: не дёргать сеть пока идёт игра
        if cfg.game_mode {
            if let Some(g) = game_running(&cfg.game_procs) {
                if !game_noticed {
                    game_noticed = true;
                    log_action(&format!("Игровой режим: {g} запущена — мониторинг на паузе"), "monitor");
                }
                tokio::time::sleep(Duration::from_secs(60)).await;
                continue;
            } else if game_noticed {
                game_noticed = false;
                log_action("Игровой режим: игра закрыта — мониторинг возобновлён", "monitor");
            }
        }
        // умный watchdog: пора попробовать вернуться к основному?
        let due = app
            .try_state::<MonitorState>()
            .map(|ms: tauri::State<'_, MonitorState>| *ms.wd_due_unix.lock().unwrap())
            .unwrap_or(0);
        if due != 0 && unix_now() >= due {
            watchdog_try_return(&app).await;
        }
        let st = zapret::service_status();
        if st.zapret != "RUNNING" && !st.winws {
            tokio::time::sleep(Duration::from_secs(60)).await;
            continue;
        }
        let cancel = AtomicBool::new(false);
        let (_rows, bad) = engine::test_current(&cfg.zapret_root, cfg.ping_threshold_ms, &cancel).await;
        // blocked: >= половины плохих (минимум 2), как в Python
        let total = zapret::quick_filter(&zapret::parse_targets(&cfg.zapret_root)).len().max(1);
        if bad >= (total / 2).max(2) as u64 {
            on_blocked(&app, &cfg, bad).await;
        }
        let iv = cfg.monitor_interval_min.max(1) * 60;
        tokio::time::sleep(Duration::from_secs(iv)).await;
    }
}

/// Вооружить возврат: запомнить основной и время следующей попытки.
fn watchdog_arm(app: &tauri::AppHandle, primary: &str, fallback: &str, return_min: u64) {
    if let Some(ms) = app.try_state::<MonitorState>() {
        *ms.wd_primary.lock().unwrap() = primary.to_string();
        *ms.wd_fallback.lock().unwrap() = fallback.to_string();
        *ms.wd_due_unix.lock().unwrap() = unix_now() + return_min.max(5) * 60;
        log_action(&format!("Watchdog: возврат к {primary} через ~{} мин", return_min.max(5)), "autoswitch");
    }
}

/// Попытка вернуться на основной: ставим, ждём 45 с, проверяем, иначе откат.
async fn watchdog_try_return(app: &tauri::AppHandle) {
    let (primary, fallback) = match app.try_state::<MonitorState>() {
        Some(ms) => (ms.wd_primary.lock().unwrap().clone(), ms.wd_fallback.lock().unwrap().clone()),
        None => return,
    };
    if primary.is_empty() {
        return;
    }
    let cur = config::load().active_config.clone();
    if cur == primary {
        if let Some(ms) = app.try_state::<MonitorState>() {
            *ms.wd_primary.lock().unwrap() = String::new();
            *ms.wd_fallback.lock().unwrap() = String::new();
            *ms.wd_due_unix.lock().unwrap() = 0;
        }
        return;
    }
    log_action(&format!("Watchdog: пробую вернуться {cur} → {primary}"), "autoswitch");
    let _ = app.emit(
        "toast",
        ToastEvent { title: "Watchdog".into(), text: format!("Пробую вернуться на {primary}…"), kind: "".into() },
    );
    let cfg = config::load();
    let (ok, _) = zapret::install_service(&cfg.zapret_root, &primary);
    if !ok {
        if let Some(ms) = app.try_state::<MonitorState>() {
            *ms.wd_due_unix.lock().unwrap() = unix_now() + cfg.watchdog_return_min.max(5) * 60;
        }
        return;
    }
    let mut cfg2 = config::load();
    cfg2.active_config = primary.clone();
    config::save(&cfg2);
    tokio::time::sleep(Duration::from_secs(45)).await;
    let cancel = AtomicBool::new(false);
    let (_rows, bad) = engine::test_current(&cfg2.zapret_root, cfg2.ping_threshold_ms, &cancel).await;
    let total = zapret::quick_filter(&zapret::parse_targets(&cfg2.zapret_root)).len().max(1);
    if bad >= (total / 2).max(2) as u64 {
        log_action("Watchdog: основной всё ещё сбоит — возврат на запасной", "autoswitch");
        let fb = if fallback.is_empty() { cur } else { fallback };
        let (ok2, _) = zapret::install_service(&cfg2.zapret_root, &fb);
        if ok2 {
            let mut cfg3 = config::load();
            cfg3.active_config = fb.clone();
            config::save(&cfg3);
            log_switch(&format!("watchdog откат → {fb}"));
        }
        if let Some(ms) = app.try_state::<MonitorState>() {
            *ms.wd_due_unix.lock().unwrap() = unix_now() + cfg2.watchdog_return_min.max(5) * 60;
        }
        let _ = app.emit(
            "toast",
            ToastEvent { title: "Watchdog".into(), text: "Основной всё ещё сбоит — вернулся на запасной.".into(), kind: "".into() },
        );
    } else {
        if let Some(ms) = app.try_state::<MonitorState>() {
            *ms.wd_primary.lock().unwrap() = String::new();
            *ms.wd_fallback.lock().unwrap() = String::new();
            *ms.wd_due_unix.lock().unwrap() = 0;
        }
        log_switch(&format!("watchdog возврат → {primary}"));
        let _ = app.emit(
            "toast",
            ToastEvent { title: "Watchdog".into(), text: format!("Основной {primary} снова в строю!"), kind: "good".into() },
        );
    }
    let _ = app.emit("status-refresh", ());
}

async fn on_blocked(app: &tauri::AppHandle, cfg: &AppConfig, bad_ping: u64) {
    let cur = if cfg.active_config.is_empty() {
        zapret::service_status().strategy
    } else {
        cfg.active_config.clone()
    };
    log_action(
        &format!("Проблемы с соединением: плохой пинг={bad_ping}. Текущий: {}.", cur),
        "monitor",
    );
    // напарник: охраняется только основной
    if cfg.buddy_enabled && !cfg.buddy_primary.is_empty() && cur != cfg.buddy_primary {
        log_action(
            &format!("Напарник: {} сбоит, но охраняется только {} — пропуск", cur, cfg.buddy_primary),
            "autoswitch",
        );
        return;
    }
    let mut scores = cfg.best_scores.clone();
    scores.remove(&cur);
    if scores.is_empty() {
        let _ = app.emit(
            "toast",
            ToastEvent {
                title: "Проблемы с соединением".into(),
                text: "Нет данных для автопереключения. Запустите проверку.".into(),
                kind: "bad".into(),
            },
        );
        return;
    }
    let nxt = scores.iter().max_by_key(|(_, s)| *s).map(|(k, _)| k.clone()).unwrap();
    let (ok, m) = zapret::install_service(&cfg.zapret_root, &nxt);
    if ok {
        let mut cfg2 = config::load();
        cfg2.active_config = nxt.clone();
        if cfg2.buddy_enabled && !cfg2.buddy_primary.is_empty() {
            cfg2.buddy_fallback = nxt.clone();
        }
        config::save(&cfg2);
        if !cur.is_empty() && cur != nxt {
            watchdog_arm(app, &cur, &nxt, cfg.watchdog_return_min);
        }
        log_action(&format!("Автопереключение: {cur} → {nxt}"), "autoswitch");
        log_switch(&format!("авто: {cur} → {nxt}"));
        let _ = app.emit(
            "toast",
            ToastEvent { title: "Автопереключение".into(), text: format!("{cur} сбоил.\nВключён {nxt}."), kind: "good".into() },
        );
    } else {
        log_action(&format!("Автопереключение не удалось ({nxt}): {m}"), "error");
    }
    let _ = app.emit("status-refresh", ());
}

// ================= списки =================

fn lists_dir() -> std::path::PathBuf {
    std::path::Path::new(&config::load().zapret_root).join("lists")
}

#[tauri::command]
fn list_lists() -> Vec<ListEntry> {
    let d = lists_dir();
    let mut out = Vec::new();
    if let Ok(rd) = std::fs::read_dir(&d) {
        for e in rd.flatten() {
            let p = e.path();
            if !p.is_file() {
                continue;
            }
            let fname = match p.file_name().and_then(|n| n.to_str()) {
                Some(n) => n.to_string(),
                None => continue,
            };
            if fname.ends_with(".disabled") {
                if let Some(base) = fname.strip_suffix(".disabled") {
                    if base.ends_with(".txt") {
                        out.push(ListEntry { name: base.to_string(), enabled: false });
                    }
                }
            } else if fname.ends_with(".txt") {
                // .disabled важнее: если есть пара — выключен
                if d.join(format!("{fname}.disabled")).exists() {
                    continue;
                }
                out.push(ListEntry { name: fname, enabled: true });
            }
        }
    }
    out.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
    out
}

#[tauri::command]
fn read_list(name: String) -> Result<String, String> {
    if name.contains(['/', '\\', '\0']) || name.contains("..") {
        return Err("Некорректное имя".into());
    }
    let d = lists_dir();
    for cand in [d.join(&name), d.join(format!("{name}.disabled"))] {
        if cand.is_file() {
            return std::fs::read_to_string(&cand).map_err(|e| e.to_string());
        }
    }
    Err("Файл не найден".into())
}

#[tauri::command]
fn save_list(name: String, content: String) -> Result<CmdResult, String> {
    if name.contains(['/', '\\', '\0']) || name.contains("..") {
        return Err("Некорректное имя".into());
    }
    let d = lists_dir();
    let mut target = None;
    for cand in [d.join(&name), d.join(format!("{name}.disabled"))] {
        if cand.is_file() {
            target = Some(cand);
            break;
        }
    }
    let target = target.ok_or("Файл не найден")?;
    if target.exists() {
        let bak = target.with_extension("txt.bak");
        let _ = std::fs::copy(&target, bak);
    }
    std::fs::write(&target, content).map_err(|e| e.to_string())?;
    log_action(&format!("Отредактирован список {} (бэкап .bak)", target.file_name().and_then(|n| n.to_str()).unwrap_or("")), "lists");
    Ok(CmdResult { ok: true, msg: "Сохранено (старая копия — в .bak)".into() })
}

#[tauri::command]
fn toggle_list(name: String, enable: bool) -> Result<CmdResult, String> {
    if name.contains(['/', '\\', '\0']) || name.contains("..") {
        return Err("Некорректное имя".into());
    }
    let d = lists_dir();
    let enabled = d.join(&name);
    let disabled = d.join(format!("{name}.disabled"));
    if enable {
        if disabled.exists() {
            std::fs::rename(&disabled, &enabled).map_err(|e| e.to_string())?;
            log_action(&format!("Список включён: {name}"), "lists");
            return Ok(CmdResult { ok: true, msg: format!("«{name}» включён") });
        }
        return Ok(CmdResult { ok: true, msg: format!("«{name}» уже включён") });
    }
    if enabled.exists() {
        std::fs::rename(&enabled, &disabled).map_err(|e| e.to_string())?;
        log_action(&format!("Список выключен: {name}"), "lists");
        return Ok(CmdResult { ok: true, msg: format!("«{name}» выключен") });
    }
    Ok(CmdResult { ok: true, msg: format!("«{name}» уже выключен") })
}

#[tauri::command]
fn create_list(name: String) -> Result<CmdResult, String> {
    let mut n = name.trim().replace(['/', '\\'], "");
    if n.to_lowercase().ends_with(".disabled") {
        n = n[..n.len() - 9].to_string();
    }
    if !n.to_lowercase().ends_with(".txt") {
        n.push_str(".txt");
    }
    if n == ".txt" || n.chars().any(|c| ":*?\"<>|".contains(c)) {
        return Err("Некорректное имя файла".into());
    }
    let d = lists_dir();
    if !d.is_dir() {
        return Err("Папка lists/ не найдена".into());
    }
    let fp = d.join(&n);
    if fp.exists() || d.join(format!("{n}.disabled")).exists() {
        return Err(format!("«{n}» уже существует"));
    }
    std::fs::write(&fp, format!("# {n} — создан из Zapret Manager\n")).map_err(|e| e.to_string())?;
    log_action(&format!("Создан список {n}"), "lists");
    Ok(CmdResult { ok: true, msg: format!("«{n}» создан") })
}

// ================= журнал/логи/прочее =================

#[tauri::command]
fn read_actions(limit: usize) -> Vec<String> {
    read_tail(&actions_path(), limit.min(2000))
}

#[tauri::command]
fn read_checks() -> Vec<String> {
    let mut out = Vec::new();
    if let Ok(rd) = std::fs::read_dir(config::checks_dir()) {
        for e in rd.flatten() {
            if let Some(n) = e.path().file_name().and_then(|n| n.to_str()) {
                if n.ends_with(".json") {
                    out.push(n.to_string());
                }
            }
        }
    }
    out.sort();
    out.reverse();
    out
}

#[tauri::command]
fn read_check_file(name: String) -> Result<String, String> {
    if name.contains(['/', '\\']) || name.contains("..") || !name.ends_with(".json") {
        return Err("Некорректное имя".into());
    }
    std::fs::read_to_string(config::checks_dir().join(name)).map_err(|e| e.to_string())
}

#[tauri::command]
fn set_autostart(enable: bool) -> CmdResult {
    let exe = std::env::current_exe().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default();
    let (ok, msg) = zapret::set_app_autostart(enable, &exe);
    if ok {
        log_action(
            &format!("Автозагрузка приложения: {}", if enable { "включена" } else { "выключена" }),
            "info",
        );
    }
    CmdResult { ok, msg }
}

#[tauri::command]
fn flush_dns() -> CmdResult {
    let (ok, msg) = zapret::flush_dns();
    log_action(&format!("Сброс DNS-кэша: {msg}"), if ok { "net" } else { "error" });
    CmdResult { ok, msg }
}

#[derive(Debug, Clone, Serialize)]
pub struct PingPoint {
    pub name: String,
    pub ping_ms: Option<u64>,
}

/// Живые пинги DS/YT для hero (монитор лёгкий, как _start_ping_monitor в Python).
#[tauri::command]
async fn ping_status() -> Vec<PingPoint> {
    let cfg = config::load();
    let cancel = AtomicBool::new(false);
    let (rows, _) = engine::test_current(&cfg.zapret_root, cfg.ping_threshold_ms, &cancel).await;
    let want = ["DiscordMain", "YouTubeWeb"];
    want.iter()
        .map(|n| {
            let pm = rows.iter().find(|r| &r.name == n).and_then(|r| r.ping_ms);
            PingPoint { name: n.to_string(), ping_ms: pm }
        })
        .collect()
}

#[tauri::command]
fn autostart_status() -> bool {
    zapret::app_autostart_enabled()
}

#[tauri::command]
fn open_data_folder() -> bool {
    let dir = config::data_dir();
    let _ = std::fs::create_dir_all(&dir);
    std::process::Command::new("explorer")
        .arg(dir)
        .spawn()
        .is_ok()
}

// ---------- funny option / секреты / стратегии ----------

#[tauri::command]
fn funny_list() -> Vec<String> {
    fun::funny_list()
}

#[tauri::command]
fn funny_image(name: String) -> Result<String, String> {
    fun::funny_image(&name)
}

#[tauri::command]
fn wizard_image() -> Result<String, String> {
    fun::wizard_image()
}

#[tauri::command]
fn wizard_video() -> Result<String, String> {
    fun::wizard_video()
}

#[tauri::command]
fn theme_music(name: String) -> Result<String, String> {
    fun::theme_music(&name)
}

#[tauri::command]
fn terminal_mascot() -> Option<String> {
    fun::terminal_mascot()
}

#[tauri::command]
fn silly_icon(app: tauri::AppHandle, on: bool) -> bool {
    let path = if on {
        fun::funny_dir().join("icon_silly.png")
    } else {
        // дефолтная иконка из ресурсов бандла
        let rel = std::path::Path::new("icons").join("icon.png");
        if let Ok(res) = app.path().resource_dir() {
            let p = res.join(&rel);
            if p.is_file() {
                p
            } else {
                return false;
            }
        } else {
            return false;
        }
    };
    let dynimg = match image::open(&path) {
        Ok(i) => i,
        Err(_) => return false,
    };
    // квадратный кроп под таскбар (как _crop_center_square в v1)
    let rgba = dynimg.to_rgba8();
    let (w, h) = (rgba.width(), rgba.height());
    let s = w.min(h);
    let x0 = (w - s) / 2;
    let y0 = (h - s) / 2;
    let mut px = Vec::with_capacity((s * s * 4) as usize);
    for y in 0..s {
        for x in 0..s {
            let p = rgba.get_pixel(x0 + x, y0 + y);
            px.extend_from_slice(&p.0);
        }
    }
    let icon = tauri::image::Image::new_owned(px, s, s);
    match app.get_webview_window("main") {
        Some(w) => w.set_icon(icon).is_ok(),
        None => false,
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct SecretUiState {
    pub title: String,
    pub theme: String,
    pub hidden: bool,
    pub files: Vec<String>,
    pub enabled: bool,
}

#[tauri::command]
fn secret_unlock(code: String) -> Result<fun::SecretPack, String> {
    let pack = fun::unlock_pack(&code)?;
    let mut cfg = config::load();
    cfg.secret_pack = pack.title.clone();
    if pack.title == "Spamton" {
        if cfg.theme != pack.theme {
            cfg.vsd_prev_theme = cfg.theme.clone();
        }
        cfg.spamton_enabled = true;
    } else {
        if cfg.theme != pack.theme {
            cfg.vsd_prev_theme = cfg.theme.clone();
        }
        cfg.vsd_enabled = true;
    }
    config::save(&cfg);
    log_action(&format!("Секретный набор {} разблокирован", pack.title), "info");
    Ok(pack)
}

#[tauri::command]
fn secret_state() -> Option<SecretUiState> {
    let cfg = config::load();
    let title = cfg.secret_pack.trim().to_string();
    if title.is_empty() {
        return None;
    }
    let mut st = fun::pack_state(&title)?;
    let enabled = if title == "Spamton" { cfg.spamton_enabled } else { cfg.vsd_enabled };
    // файлы могли стереть — тогда как будто закрыто
    if st.files.is_empty() {
        return None;
    }
    Some(SecretUiState {
        title: st.title.clone(),
        theme: st.theme.clone(),
        hidden: st.hidden,
        files: std::mem::take(&mut st.files),
        enabled,
    })
}

#[tauri::command]
fn secret_set_enabled(title: String, en: bool, prev_theme: String) -> bool {
    let mut cfg = config::load();
    if title == "Spamton" {
        cfg.spamton_enabled = en;
    } else {
        cfg.vsd_enabled = en;
    }
    if en && !prev_theme.is_empty() {
        cfg.vsd_prev_theme = prev_theme;
    }
    config::save(&cfg);
    true
}

#[tauri::command]
fn pack_image(title: String, name: String) -> Result<String, String> {
    fun::pack_image(&title, &name)
}

#[tauri::command]
fn strategy_parse(bat: String) -> Result<fun::StrategyDoc, String> {
    let cfg = config::load();
    fun::strategy_parse(&cfg.zapret_root, &bat)
}

#[tauri::command]
fn strategy_save(bat: String, blocks: Vec<String>, as_new: Option<String>) -> Result<String, String> {
    let cfg = config::load();
    let name = fun::strategy_save(&cfg.zapret_root, &bat, blocks, as_new)?;
    log_action(&format!("Стратегии: сохранён {name}"), "apply");
    Ok(name)
}

#[derive(Debug, Clone, Serialize)]
pub struct AppUpdate {
    pub version: String,
    pub body: String,
}

/// Проверка обновлений приложения через штатный Tauri updater (подпись minisign).
#[tauri::command]
async fn app_update_check(app: tauri::AppHandle) -> Result<Option<AppUpdate>, String> {
    use tauri_plugin_updater::UpdaterExt;
    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| e.to_string())?;
    Ok(update.map(|u| AppUpdate {
        version: u.version.clone(),
        body: u.body.clone().unwrap_or_default(),
    }))
}

/// Скачивание + установка + перезапуск.
#[tauri::command]
async fn app_update_install(app: tauri::AppHandle) -> Result<String, String> {
    use tauri_plugin_updater::UpdaterExt;
    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| e.to_string())?
        .ok_or("Обновлений нет")?;
    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(|e| e.to_string())?;
    log_action("Приложение обновлено, перезапуск", "info");
    app.restart();
}

fn main() {
    // AppUserModelID первым делом — как в Python main() (иконка таскбара + тосты)
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        extern "system" {
            fn SetCurrentProcessExplicitAppUserModelID(appid: *const u16) -> i32;
        }
        let wide: Vec<u16> = std::ffi::OsStr::new("Flowseal.ZapretManager")
            .encode_wide()
            .chain(std::iter::once(0))
            .collect();
        unsafe {
            SetCurrentProcessExplicitAppUserModelID(wide.as_ptr());
        }
    }
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            // второй запуск — показать окно первого (как ensure_single_instance в v1)
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_window_state::Builder::new().build())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(CheckState { cancel: Arc::new(AtomicBool::new(false)), running: AtomicBool::new(false) })
        .manage(MonitorState {
            handle: Mutex::new(None),
            wd_primary: Mutex::new(String::new()),
            wd_fallback: Mutex::new(String::new()),
            wd_due_unix: Mutex::new(0),
        })
        .manage(ReinstallState { running: AtomicBool::new(false) })
        .invoke_handler(tauri::generate_handler![
            get_version,
            get_config,
            save_config,
            autodetect_root,
            list_configs,
            get_service_status,
            apply_config,
            remove_service_cmd,
            cancel_check,
            run_check,
            monitor_start,
            monitor_stop,
            list_lists,
            read_list,
            save_list,
            toggle_list,
            create_list,
            read_actions,
            read_checks,
            read_check_file,
            set_autostart,
            autostart_status,
            flush_dns,
            net_reset,
            ping_status,
            restart_service_cmd,
            restart_standalone_cmd,
            filter_state,
            game_filter_toggle,
            ipset_toggle,
            run_diagnostics,
            vpn_state,
            resource_state,
            lists_snapshot_save,
            release_diff,
            read_switches,
            funny_list,
            funny_image,
            wizard_image,
            wizard_video,
            theme_music,
            terminal_mascot,
            silly_icon,
            secret_unlock,
            secret_state,
            secret_set_enabled,
            pack_image,
            strategy_parse,
            strategy_save,
            app_update_check,
            app_update_install,
            reinstall_zapret,
            export_report,
            make_shortcut,
            refresh_icon_cache,
            check_updates,
            open_url,
            open_data_folder,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
