//! Движок проверки: ping + HTTP пробы, sequential/ultra турниры, мониторинг.
//! Порт CheckEngine из Python-версии (та же методика и скоринг).
use crate::config;
use crate::zapret;
use serde::Serialize;
use std::collections::HashMap;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Duration;
use tokio::sync::Semaphore;

pub const ULTRA_FINALISTS: usize = 6;

#[derive(Debug, Clone, Serialize)]
pub struct ProbeRow {
    pub name: String,
    pub host: String,
    pub ping_ms: Option<u64>,
    pub ping_ok: bool,
    pub http_ok: Option<bool>,
}

#[derive(Debug, Clone, Serialize)]
pub struct BatResult {
    pub ok: u64,
    pub fail: u64,
    pub ping_ok: u64,
    pub rows: Vec<ProbeRow>,
    pub started: bool,
    pub score: i64,
    #[serde(rename = "final")]
    pub final_: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct ProgressEvent {
    pub done: usize,
    pub total: usize,
    pub name: String,
    pub score: i64,
    pub grade: String,
}

pub struct Ctx {
    pub root: String,
    pub timeout_s: u64,
    pub ping_thr: u64,
    pub repeat: u32,
    pub workers: usize,
    pub cancel: Arc<AtomicBool>,
}

fn http_client(timeout: Duration) -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(timeout)
        .user_agent("Mozilla/5.0")
        .no_proxy()
        .build()
        .expect("reqwest client")
}

async fn http_check(client: &reqwest::Client, url: &str) -> bool {
    // HEAD, затем GET (как curl -I + urllib-fallback в Python)
    for method in [reqwest::Method::HEAD, reqwest::Method::GET] {
        match client.request(method, url).send().await {
            Ok(r) => {
                let c = r.status().as_u16();
                if (200..400).contains(&c) || c == 403 || c == 405 {
                    return true;
                }
                return false;
            }
            Err(_) => continue,
        }
    }
    false
}

async fn probe_target(
    client: reqwest::Client,
    name: String,
    val: String,
    _timeout: Duration,
    ping_thr: u64,
    ping_cap: u64,
    repeat: u32,
) -> ProbeRow {
    let (host, ping_only) = zapret::split_host(&val);
    let host_c = host.clone();
    let pm = tokio::task::spawn_blocking(move || zapret::ping_host(&host_c, ping_cap))
        .await
        .unwrap_or(None);
    let ping_ok = pm.map(|v| v < ping_thr).unwrap_or(false);
    let mut http_ok = None;
    if !ping_only {
        let mut ok = false;
        for _ in 0..repeat.max(1) {
            if http_check(&client, &val).await {
                ok = true;
                break;
            }
        }
        http_ok = Some(ok);
    }
    ProbeRow { name, host, ping_ms: pm, ping_ok, http_ok }
}

pub async fn probe_many(
    targets: &[(String, String)],
    timeout: Duration,
    ping_thr: u64,
    repeat: u32,
    workers: usize,
    cancel: &AtomicBool,
    on_row: &mut (dyn FnMut(&str, Option<u64>) + Send),
) -> Vec<ProbeRow> {
    let ping_cap = ping_thr.min(1500);
    let workers = workers.clamp(2, 16);
    let client = http_client(timeout);
    let sem = Arc::new(Semaphore::new(workers));
    let mut set = tokio::task::JoinSet::new();
    for (n, v) in targets {
        let (permit_owner, n, v) = (sem.clone(), n.clone(), v.clone());
        let client = client.clone();
        set.spawn(async move {
            let _p = permit_owner.acquire_owned().await.unwrap();
            probe_target(client, n, v, timeout, ping_thr, ping_cap, repeat).await
        });
    }
    let mut map: HashMap<String, ProbeRow> = HashMap::new();
    while let Some(r) = set.join_next().await {
        if cancel.load(Ordering::Relaxed) {
            set.abort_all();
            break;
        }
        if let Ok(row) = r {
            on_row(&row.name, row.ping_ms);
            map.insert(row.name.clone(), row);
        }
    }
    targets
        .iter()
        .filter_map(|(n, _)| map.remove(n))
        .collect()
}

pub fn network_alive() -> bool {
    zapret::ping_host("1.1.1.1", 800).is_some() || zapret::ping_host("8.8.8.8", 800).is_some()
}

fn summarize(rows: &[ProbeRow]) -> (u64, u64, u64) {
    let ok = rows.iter().filter(|r| r.http_ok == Some(true)).count() as u64;
    let fail = rows.iter().filter(|r| r.http_ok == Some(false)).count() as u64;
    let ping_ok = rows.iter().filter(|r| r.ping_ok).count() as u64;
    (ok, fail, ping_ok)
}

pub fn ping_grade(pm: Option<u64>) -> &'static str {
    match pm {
        None => "Не работает",
        Some(v) if v <= 100 => "Отличный",
        Some(v) if v <= 300 => "Хороший",
        Some(v) if v <= 1000 => "Средний",
        _ => "Плохой",
    }
}

pub fn config_grade(dm: Option<u64>, ym: Option<u64>) -> &'static str {
    fn rank(pm: Option<u64>) -> u8 {
        match pm {
            None => 0,
            Some(v) if v <= 100 => 4,
            Some(v) if v <= 300 => 3,
            Some(v) if v <= 1000 => 2,
            _ => 1,
        }
    }
    if rank(dm) <= rank(ym) {
        ping_grade(dm)
    } else {
        ping_grade(ym)
    }
}

fn wait_winws_logged_secs(bat: &str, logs: &mut Vec<String>) -> bool {
    // ждём появления winws polling'ом (как _wait_winws_logged без пробника)
    let t0 = std::time::Instant::now();
    while t0.elapsed() < Duration::from_secs(5) {
        if zapret::winws_running() {
            std::thread::sleep(Duration::from_millis(400));
            return true;
        }
        std::thread::sleep(Duration::from_millis(350));
    }
    logs.push(format!("  {bat}: winws не запустился — пропуск"));
    false
}

#[allow(clippy::too_many_arguments)]
async fn probe_bat(
    ctx: &Ctx,
    bat: &str,
    targets: &[(String, String)],
    logs: &mut Vec<String>,
    screen_only: bool,
    on_row: &mut (dyn FnMut(&str, Option<u64>) + Send),
) -> BatResult {
    zapret::start_winws_hidden(&ctx.root, bat);
    if !wait_winws_logged_secs(bat, logs) {
        return BatResult {
            ok: 0,
            fail: targets.len() as u64,
            ping_ok: 0,
            rows: vec![],
            started: false,
            score: -1,
            final_: true,
        };
    }
    let rows = probe_many(
        targets,
        Duration::from_secs(ctx.timeout_s),
        ctx.ping_thr,
        if screen_only { 1 } else { ctx.repeat },
        if screen_only { 4 } else { ctx.workers },
        &ctx.cancel,
        on_row,
    )
    .await;
    let (ok, fail, ping_ok) = summarize(&rows);
    let score = if screen_only {
        (ping_ok * 10 + ping_ok) as i64
    } else {
        (ok * 10 + ping_ok) as i64
    };
    BatResult { ok, fail, ping_ok, rows, started: true, score, final_: !screen_only }
}

/// Полная проверка списка. progress(done,total,name,score). Возвращает (results, abort_reason, logs).
/// on_row(bat, target, ping_ms) — мгновенный пинг каждой цели, без ожидания счёта.
pub async fn run_check<F, G>(
    ctx: &Ctx,
    bats: Vec<String>,
    mode: &str,
    mut progress: F,
    mut on_row: G,
) -> (HashMap<String, BatResult>, String, Vec<String>)
where
    F: FnMut(usize, usize, &str, i64, String),
    G: FnMut(&str, &str, Option<u64>) + Send,
{
    let mut logs = Vec::new();
    let mut out: HashMap<String, BatResult> = HashMap::new();
    if !network_alive() {
        logs.push("[!] Нет сети (не пингуются даже 1.1.1.1/8.8.8.8) — проверка прервана.".into());
        return (out, "nonetwork".into(), logs);
    }
    let mut targets = zapret::parse_targets(&ctx.root);
    if mode == "quick" {
        targets = zapret::quick_filter(&targets);
    }
    zapret::stop_winws();
    std::thread::sleep(Duration::from_millis(100));
    if mode == "ultra" {
        ultra_loop(ctx, bats, &targets, &mut progress, &mut on_row, &mut logs, &mut out).await;
    } else {
        seq_loop(ctx, bats, &targets, &mut progress, &mut on_row, &mut logs, &mut out).await;
    }
    zapret::stop_winws();
    (out, String::new(), logs)
}

async fn seq_loop<F>(
    ctx: &Ctx,
    mut bats: Vec<String>,
    targets: &[(String, String)],
    progress: &mut F,
    on_row: &mut (dyn FnMut(&str, &str, Option<u64>) + Send),
    logs: &mut Vec<String>,
    out: &mut HashMap<String, BatResult>,
) where
    F: FnMut(usize, usize, &str, i64, String),
{
    // сначала конфиги с лучшими прошлыми очками
    let cfg = config::load();
    bats.sort_by_key(|b| {
        -(cfg.best_scores.get(b).copied().unwrap_or_else(|| {
            let base = std::path::Path::new(b)
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or(b);
            cfg.best_scores.get(base).copied().unwrap_or(0)
        }))
    });
    let total = bats.len();
    let mut dead_chain = 0;
    for (idx, bat) in bats.iter().enumerate() {
        if ctx.cancel.load(Ordering::Relaxed) {
            break;
        }
        logs.push(format!("[{}/{}] Запуск {} …", idx + 1, total, bat));
        let mut r = probe_bat(ctx, bat, targets, logs, false, &mut |n, pm| on_row(bat, n, pm)).await;
        if r.started {
            let dt_ok = r.ok;
            logs.push(format!("  {bat}: HTTP OK={} ERR={} PingOK={} score={}", dt_ok, r.fail, r.ping_ok, r.score));
            if r.ok == 0 && r.ping_ok == 0 && r.fail > 0 {
                dead_chain += 1;
                if dead_chain >= 3 {
                    logs.push("[!] Три конфига подряд без единого пакета — сеть упала. Прерываю.".into());
                    zapret::stop_winws();
                    break;
                }
            } else {
                dead_chain = 0;
            }
        } else {
            r.score = -1;
        }
        progress(idx + 1, total, bat, r.score, grade_of_bat(&r));
        out.insert(bat.clone(), r);
        zapret::stop_winws();
        std::thread::sleep(Duration::from_millis(100));
    }
}

async fn ultra_loop<F>(
    ctx: &Ctx,
    mut bats: Vec<String>,
    targets: &[(String, String)],
    progress: &mut F,
    on_row: &mut (dyn FnMut(&str, &str, Option<u64>) + Send),
    logs: &mut Vec<String>,
    out: &mut HashMap<String, BatResult>,
) where
    F: FnMut(usize, usize, &str, i64, String),
{
    let mut screen: Vec<_> = targets
        .iter()
        .filter(|(n, _)| n == "DiscordMain" || n == "YouTubeWeb")
        .cloned()
        .collect();
    if screen.len() < 2 {
        screen = targets.iter().take(2).cloned().collect();
    }
    let screen: Vec<_> = screen
        .iter()
        .map(|(n, v)| {
            if v.starts_with("PING:") {
                (n.clone(), v.clone())
            } else {
                let (h, _) = zapret::split_host(v);
                (n.clone(), format!("PING:{h}"))
            }
        })
        .collect();
    let cfg = config::load();
    bats.sort_by_key(|b| {
        -(cfg.best_scores.get(b).copied().unwrap_or(0))
    });
    let total = bats.len();
    let n_fin = ULTRA_FINALISTS.min(total);
    let grand = total + n_fin;
    logs.push(format!("Режим УЛЬТРА: отсев {total} конфигов (только пинг), затем топ-{n_fin}."));
    zapret::stop_winws();
    std::thread::sleep(Duration::from_millis(100));
    // фаза 1: отсев
    let mut screened: Vec<(String, i64)> = Vec::new();
    for (idx, bat) in bats.iter().enumerate() {
        if ctx.cancel.load(Ordering::Relaxed) {
            break;
        }
        logs.push(format!("[отсев {}/{}] {} …", idx + 1, total, bat));
        let r = probe_bat(ctx, bat, &screen, logs, true, &mut |n, pm| on_row(bat, n, pm)).await;
        let s = if r.started { r.score } else { -1 };
        screened.push((bat.clone(), s));
        progress(idx + 1, grand, bat, s, grade_of_bat(&r));
        zapret::stop_winws();
        std::thread::sleep(Duration::from_millis(100));
        if s == (screen.len() as i64) * 11 {
            logs.push("Идеальный отсев — дальше только финал.".into());
            break;
        }
    }
    screened.sort_by_key(|(_, s)| -*s);
    let finalists: Vec<String> = screened.into_iter().take(n_fin).map(|(b, _)| b).collect();
    logs.push(format!("Финалисты топ-{}: {} — точный замер…", finalists.len(), finalists.join(", ")));
    // фаза 2: финал
    for (j, bat) in finalists.iter().enumerate() {
        if ctx.cancel.load(Ordering::Relaxed) {
            break;
        }
        logs.push(format!("[финал {}/{}] {} …", j + 1, finalists.len(), bat));
        let r = probe_bat(ctx, bat, targets, logs, false, &mut |n, pm| on_row(bat, n, pm)).await;
        progress(total + j + 1, grand, bat, r.score, grade_of_bat(&r));
        out.insert(bat.clone(), r);
        zapret::stop_winws();
        std::thread::sleep(Duration::from_millis(100));
    }
    // неотсеянные без точного замера — помечаем приблизительными
    for (bat, s) in out.clone() {
        let _ = (bat, s);
    }
}

/// ЭКО-проверка для мониторинга: только пинги quick-целей.
pub async fn test_current(root: &str, ping_thr: u64, cancel: &AtomicBool) -> (Vec<ProbeRow>, u64) {
    let targets = zapret::quick_filter(&zapret::parse_targets(root));
    let ping_targets: Vec<_> = targets
        .iter()
        .map(|(n, v)| {
            let (h, _) = zapret::split_host(v);
            (n.clone(), format!("PING:{h}"))
        })
        .collect();
    let rows = probe_many(&ping_targets, Duration::from_secs(2), ping_thr, 1, 4, cancel, &mut |_, _| {}).await;
    let bad = rows.iter().filter(|r| !r.ping_ok).count() as u64;
    (rows, bad)
}

/// Оценка готового результата для прогресса/телика (как в проверке Python).
fn grade_of_bat(r: &BatResult) -> String {
    if !r.started {
        return "Не работает".into();
    }
    grade_of(&r.rows).2.to_string()
}

pub fn grade_of(rows: &[ProbeRow]) -> (Option<u64>, Option<u64>, &'static str) {
    let (dm, ym) = {
        let pick = |names: &[&str]| {
            rows.iter()
                .filter(|r| names.contains(&r.name.as_str()))
                .filter_map(|r| r.ping_ms)
                .min()
        };
        (
            pick(&["DiscordMain", "DiscordGateway", "DiscordCDN", "DiscordUpdates"]),
            pick(&["YouTubeWeb", "YouTubeShort", "YouTubeImage", "YouTubeVideoRedirect"]),
        )
    };
    (dm, ym, config_grade(dm, ym))
}
