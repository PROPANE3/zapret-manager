//! Настройки приложения: JSON рядом с exe (data/config.json), как в Python-версии.
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct AppConfig {
    pub zapret_root: String,
    pub active_config: String,
    pub best_scores: HashMap<String, i64>,
    pub monitor_enabled: bool,
    pub monitor_interval_min: u64,
    pub ping_threshold_ms: u64,
    pub check_timeout_s: u64,
    pub check_mode: String,
    pub check_repeat: u32,
    pub check_workers: usize,
    pub theme: String,
    pub buddy_enabled: bool,
    pub buddy_primary: String,
    pub buddy_fallback: String,
    pub sound_enabled: bool,
    pub silly_mode: bool,
    pub secret_pack: String,
    pub vsd_enabled: bool,
    pub spamton_enabled: bool,
    pub vsd_prev_theme: String,
    pub fav_configs: Vec<String>,
    pub game_mode: bool,
    pub game_procs: String,
    pub watchdog_return_min: u64,
    pub custom_theme: std::collections::HashMap<String, String>,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            zapret_root: String::new(),
            active_config: String::new(),
            best_scores: HashMap::new(),
            monitor_enabled: true,
            monitor_interval_min: 3,
            ping_threshold_ms: 5000,
            check_timeout_s: 4,
            check_mode: "ultra".into(),
            check_repeat: 1,
            check_workers: 12,
            theme: "scarlet".into(),
            buddy_enabled: false,
            buddy_primary: String::new(),
            buddy_fallback: String::new(),
            sound_enabled: true,
            silly_mode: false,
            secret_pack: String::new(),
            vsd_enabled: false,
            spamton_enabled: false,
            vsd_prev_theme: String::new(),
            fav_configs: Vec::new(),
            game_mode: false,
            game_procs: "cs2.exe, dota2.exe, GTA5.exe, eldenring.exe".into(),
            watchdog_return_min: 15,
            custom_theme: HashMap::new(),
        }
    }
}

fn exe_dir() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."))
}

/// Каталог data/ рядом с exe (в dev — рядом с target/debug).
pub fn data_dir() -> PathBuf {
    exe_dir().join("data")
}

pub fn checks_dir() -> PathBuf {
    data_dir().join("checks")
}

fn config_path() -> PathBuf {
    data_dir().join("config.json")
}

fn is_zapret_root(p: &std::path::Path) -> bool {
    p.is_dir() && p.join("service.bat").is_file() && p.join("bin").is_dir()
}

fn default_root_candidates() -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    // 1. рядом с самим менеджером: его папка или папки-соседи
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            if is_zapret_root(dir) {
                out.push(dir.to_string_lossy().into_owned());
            }
            if let Ok(rd) = std::fs::read_dir(dir) {
                for e in rd.flatten() {
                    let p = e.path();
                    if p.is_dir() && is_zapret_root(&p) {
                        out.push(p.to_string_lossy().into_owned());
                    }
                }
            }
        }
    }
    // 2. рабочий стол: любая zapret-discord-youtube-*, сначала свежие
    if let Ok(home) = std::env::var("USERPROFILE") {
        let desk = PathBuf::from(home).join("Desktop");
        if let Ok(rd) = std::fs::read_dir(&desk) {
            let mut v: Vec<(std::time::SystemTime, PathBuf)> = rd
                .flatten()
                .map(|e| e.path())
                .filter(|p| {
                    p.is_dir()
                        && p.file_name()
                            .and_then(|n| n.to_str())
                            .map(|n| n.starts_with("zapret-discord-youtube"))
                            .unwrap_or(false)
                        && is_zapret_root(p)
                })
                .map(|p| {
                    let mt = std::fs::metadata(&p)
                        .and_then(|m| m.modified())
                        .unwrap_or(std::time::UNIX_EPOCH);
                    (mt, p)
                })
                .collect();
            v.sort_by(|a, b| b.0.cmp(&a.0));
            for (_, p) in v {
                out.push(p.to_string_lossy().into_owned());
            }
        }
        for fixed in ["zapret-discord-youtube-main", "zapret"] {
            let p = desk.join(fixed);
            if is_zapret_root(&p) {
                let s = p.to_string_lossy().into_owned();
                if !out.contains(&s) {
                    out.push(s);
                }
            }
        }
    }
    // 3. корни дисков (старый фолбэк)
    for fixed in [r"C:\zapret", r"D:\zapret"] {
        if is_zapret_root(std::path::Path::new(fixed)) {
            out.push(fixed.to_string());
        }
    }
    out
}

pub fn load() -> AppConfig {
    let mut cfg = AppConfig::default();
    if let Ok(text) = std::fs::read_to_string(config_path()) {
        if let Ok(data) = serde_json::from_str::<AppConfig>(&text) {
            cfg = data;
        }
    }
    if cfg.zapret_root.is_empty()
        || !std::path::Path::new(&cfg.zapret_root).is_dir()
    {
        for cand in default_root_candidates() {
            if std::path::Path::new(&cand).is_dir() {
                cfg.zapret_root = cand;
                break;
            }
        }
    }
    // миграция имён режимов/тем из Python-версии — значения совместимы
    if cfg.check_mode != "quick" && cfg.check_mode != "full" && cfg.check_mode != "ultra" {
        cfg.check_mode = "ultra".into();
    }
    cfg
}

pub fn save(cfg: &AppConfig) {
    let dir = data_dir();
    let _ = std::fs::create_dir_all(&dir);
    let _ = std::fs::create_dir_all(checks_dir());
    if let Ok(text) = serde_json::to_string_pretty(cfg) {
        let _ = std::fs::write(config_path(), text);
    }
}

/// Первый подходящий корень zapret (кнопка «Найти» в настройках).
pub fn autodetect_root() -> Option<String> {
    for cand in default_root_candidates() {
        if std::path::Path::new(&cand).is_dir() {
            return Some(cand);
        }
    }
    None
}
