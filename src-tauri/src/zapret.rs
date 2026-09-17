//! Порт ядра Python-версии: конфиги, targets.txt, ping/HTTP-пробы — нет,
//! только: обнаружение bat, разбор аргументов winws, службы и процессы.
//! (Пробы живут в engine.rs.)
use serde::Serialize;
use std::collections::HashMap;
use std::path::Path;
use std::process::Command;
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;

// ================= запуск процессов =================

/// Синхронный запуск с таймаутом. Консольных окон нет (CREATE_NO_WINDOW).
/// Возвращает (код, stdout+stderr).
pub fn run_cmd(argv: &[&str], timeout: Duration) -> (i32, String) {
    run_cmd_owned(&argv.iter().map(|s| s.to_string()).collect::<Vec<_>>(), timeout)
}

fn run_cmd_owned(argv: &[String], timeout: Duration) -> (i32, String) {
    if argv.is_empty() {
        return (1, String::new());
    }
    let mut cmd = Command::new(&argv[0]);
    if argv.len() > 1 {
        cmd.args(&argv[1..]);
    }
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    let child = match cmd.stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => return (1, e.to_string()),
    };
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let out = child.wait_with_output();
        let _ = tx.send(out);
    });
    match rx.recv_timeout(timeout) {
        Ok(Ok(o)) => {
            let mut s = String::from_utf8_lossy(&o.stdout).into_owned();
            s.push_str(&String::from_utf8_lossy(&o.stderr));
            (o.status.code().unwrap_or(1), s)
        }
        Ok(Err(e)) => (1, e.to_string()),
        Err(_) => (124, "timeout".into()),
    }
}

/// `cmd /c <line>` скрыто (для составных sc-цепочек, как shell=True в Python).
pub fn run_shell(line: &str, timeout: Duration) -> (i32, String) {
    run_cmd(&["cmd", "/c", line], timeout)
}

// ================= конфиги =================

fn is_config_bat(name: &str) -> bool {
    let low = name.to_lowercase();
    low.ends_with(".bat") && !low.starts_with("service")
}

fn alt_sort_key(name: &str) -> (u8, u64, String) {
    if name.to_lowercase() == "general.bat" {
        return (0, 0, name.to_string());
    }
    let up = name.to_uppercase();
    if let Some(pos) = up.find("ALT") {
        let digits: String = up[pos + 3..].chars().take_while(|c| c.is_ascii_digit()).collect();
        if let Ok(n) = digits.parse::<u64>() {
            return (1, n, name.to_string());
        }
        return (1, 1, name.to_string());
    }
    (2, 0, name.to_string())
}

const CONFIG_SKIP_DIRS: &[&str] = &["bin", "lists", "utils", "data", ".git", "__pycache__"];

fn walk_configs(dir: &Path, root: &Path, out: &mut Vec<String>) {
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return,
    };
    let mut subdirs = Vec::new();
    let mut files = Vec::new();
    for e in entries.flatten() {
        let p = e.path();
        if p.is_dir() {
            if let Some(n) = p.file_name().and_then(|n| n.to_str()) {
                if !n.starts_with('.') && !CONFIG_SKIP_DIRS.contains(&n.to_lowercase().as_str()) {
                    subdirs.push(p);
                }
            }
        } else if p.is_file() {
            files.push(p);
        }
    }
    subdirs.sort();
    files.sort();
    for f in files {
        if let Some(n) = f.file_name().and_then(|n| n.to_str()) {
            if is_config_bat(n) {
                if let Ok(rel) = f.strip_prefix(root) {
                    out.push(rel.to_string_lossy().replace('/', "\\"));
                }
            }
        }
    }
    for d in subdirs {
        walk_configs(&d, root, out);
    }
}

/// Конфиги относительными путями от корня zapret (как list_configs в Python).
pub fn list_configs(zapret_root: &str) -> Vec<String> {
    let root = Path::new(zapret_root);
    if !root.is_dir() {
        return vec![];
    }
    let mut out = Vec::new();
    walk_configs(root, root, &mut out);
    out.sort_by(|a, b| {
        let da = Path::new(a).parent().map(|p| p.to_string_lossy().to_lowercase()).unwrap_or_default();
        let db = Path::new(b).parent().map(|p| p.to_string_lossy().to_lowercase()).unwrap_or_default();
        let ba = Path::new(a).file_name().and_then(|n| n.to_str()).unwrap_or(a);
        let bb = Path::new(b).file_name().and_then(|n| n.to_str()).unwrap_or(b);
        (da, alt_sort_key(ba)).cmp(&(db, alt_sort_key(bb)))
    });
    out
}

/// Короткое имя для UI: 'general (ALT)' или 'pack\\custom'.
pub fn display_bat(bat: &str) -> String {
    let p = Path::new(bat);
    let base = p
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or(bat)
        .strip_suffix(".bat")
        .unwrap_or(bat)
        .to_string();
    let parent = p
        .parent()
        .and_then(|d| d.file_name())
        .and_then(|n| n.to_str())
        .unwrap_or("");
    if !parent.is_empty() && parent.to_lowercase() != "pre-configs" {
        format!("{parent}\\{base}")
    } else {
        base
    }
}

// ================= targets.txt =================

pub const QUICK_NAMES: &[&str] = &[
    "DiscordMain",
    "DiscordGateway",
    "YouTubeWeb",
    "YouTubeShort",
    "YouTubeVideoRedirect",
    "GoogleMain",
    "CloudflareDNS1111",
];

fn default_targets() -> Vec<(String, String)> {
    vec![
        ("DiscordMain".into(), "https://discord.com".into()),
        ("YouTubeWeb".into(), "https://www.youtube.com".into()),
        ("GoogleMain".into(), "https://www.google.com".into()),
        ("CloudflareWeb".into(), "https://www.cloudflare.com".into()),
        ("CloudflareDNS1111".into(), "PING:1.1.1.1".into()),
        ("GoogleDNS8888".into(), "PING:8.8.8.8".into()),
    ]
}

/// Строка `NAME = "value"` (комменты # пропускаем).
pub fn parse_targets(zapret_root: &str) -> Vec<(String, String)> {
    let mut out = Vec::new();
    let p = Path::new(zapret_root).join("utils").join("targets.txt");
    if let Ok(src) = std::fs::read_to_string(&p) {
        for line in src.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            if let Some((k, v)) = line.split_once('=') {
                let name_ok = !k.trim().is_empty()
                    && k.trim().chars().all(|c| c.is_alphanumeric() || c == '_');
                let val = v.trim().trim_matches('"').trim();
                if name_ok && !val.is_empty() {
                    out.push((k.trim().to_string(), val.to_string()));
                }
            }
        }
    }
    if out.is_empty() {
        out = default_targets();
    }
    out
}

pub fn quick_filter(targets: &[(String, String)]) -> Vec<(String, String)> {
    let sub: Vec<_> = targets
        .iter()
        .filter(|(n, _)| QUICK_NAMES.contains(&n.as_str()))
        .cloned()
        .collect();
    if sub.len() >= 3 {
        return sub;
    }
    let mut out: Vec<_> = targets.iter().filter(|(_, v)| !v.starts_with("PING:")).take(4).cloned().collect();
    out.extend(targets.iter().filter(|(_, v)| v.starts_with("PING:")).take(2).cloned());
    out
}

/// (хост, ping_only) из URL или PING:.
pub fn split_host(val: &str) -> (String, bool) {
    if let Some(h) = val.strip_prefix("PING:") {
        return (h.trim().to_string(), true);
    }
    let mut h = val.trim();
    if let Some(s) = h.strip_prefix("https://") {
        h = s;
    } else if let Some(s) = h.strip_prefix("http://") {
        h = s;
    }
    (h.split('/').next().unwrap_or("").trim().to_string(), false)
}

/// Пинг через системную утилиту. Возвращает ms или None.
pub fn ping_host(host: &str, timeout_ms: u64) -> Option<u64> {
    let t = timeout_ms.to_string();
    let (_rc, out) = run_cmd(&["ping", "-n", "1", "-w", &t, host], Duration::from_secs(8));
    let low = out.to_lowercase();
    // ищем time=NNms / time<1ms
    let mut it = low.split("time").skip(1);
    // берём первое вхождение
    let bytes = out.as_bytes();
    let low_b = low.as_bytes();
    let mut i = 0;
    while i + 4 < low_b.len() {
        if &low_b[i..i + 4] == b"time" {
            let mut j = i + 4;
            if j < low_b.len() && (low_b[j] == b'=' || low_b[j] == b'<') {
                j += 1;
                let start = j;
                while j < low_b.len() && low_b[j].is_ascii_digit() {
                    j += 1;
                }
                if j + 1 < low_b.len() && &low_b[j..j + 2] == b"ms" {
                    let num = std::str::from_utf8(&bytes[start..j]).unwrap_or("");
                    if let Ok(n) = num.parse::<u64>() {
                        return Some(n);
                    }
                    return Some(1); // time<1ms без цифр
                }
            }
        }
        i += 1;
    }
    let _ = it.next();
    if out.to_uppercase().contains("TTL=") {
        return Some(1);
    }
    None
}

// ================= разбор bat =================

fn bat_expand_vars(text: &str, env: &HashMap<String, String>) -> String {
    let mut out = text.to_string();
    for _ in 0..5 {
        let mut next = String::with_capacity(out.len());
        let b = out.as_bytes();
        let mut i = 0;
        let mut changed = false;
        while i < b.len() {
            if b[i] == b'%' {
                if let Some(end) = out[i + 1..].find('%') {
                    let key = out[i + 1..i + 1 + end].to_uppercase();
                    if let Some(v) = env.get(&key) {
                        next.push_str(v);
                    } else {
                        next.push('%');
                        next.push_str(&out[i + 1..i + 1 + end]);
                        next.push('%');
                    }
                    i += end + 2;
                    changed = true;
                    continue;
                }
            }
            next.push(b[i] as char);
            i += 1;
        }
        // !VAR! — как в Python: тоже раскрываем (там 5 проходов по обоим)
        let mut next2 = String::with_capacity(next.len());
        let b2 = next.as_bytes();
        let mut j = 0;
        while j < b2.len() {
            if b2[j] == b'!' {
                if let Some(end) = next[j + 1..].find('!') {
                    let key = next[j + 1..j + 1 + end].to_uppercase();
                    if let Some(v) = env.get(&key) {
                        next2.push_str(v);
                    } else {
                        next2.push('!');
                        next2.push_str(&next[j + 1..j + 1 + end]);
                        next2.push('!');
                    }
                    j += end + 2;
                    changed = true;
                    continue;
                }
            }
            next2.push(b2[j] as char);
            j += 1;
        }
        if !changed || next2 == out {
            out = next2;
            break;
        }
        out = next2;
    }
    out
}

/// Разобрать `set ...`: возвращает (NAME, value) или None.
fn parse_set_line(s: &str) -> Option<(String, String)> {
    let t = s.trim();
    if t.len() < 4 || !t[..3].eq_ignore_ascii_case("set") {
        return None;
    }
    let rest = t[3..].trim_start();
    if rest.is_empty() {
        return None;
    }
    let (name, val) = if let Some(q) = rest.strip_prefix('"') {
        let inner = q.strip_suffix('"').unwrap_or(q);
        let (n, v) = inner.split_once('=')?;
        // "NAME = val": имя без пробелов/равно внутри (лениво как [^"=]+?)
        let n = n.trim();
        if n.is_empty() || n.contains('"') || n.contains('=') {
            return None;
        }
        (n.to_string(), v.to_string())
    } else {
        let (n, v) = rest.split_once('=')?;
        let n = n.trim();
        if n.is_empty() || n.contains(char::is_whitespace) {
            return None;
        }
        (n.to_string(), v.to_string())
    };
    let name = name.trim().to_uppercase();
    let mut val = val;
    // rstrip одного trailing пробела-блока: Python делает rstrip() всего хвоста
    while val.ends_with([' ', '\t', '\r']) {
        val.pop();
    }
    if name.is_empty() || name.contains('/') || name.contains('\\') {
        return None;
    }
    Some((name, val))
}

fn bat_collect_env(lines: &[String], batdir: &str) -> HashMap<String, String> {
    let mut env: HashMap<String, String> = HashMap::new();
    for (k, v) in std::env::vars() {
        env.insert(k.to_uppercase(), v);
    }
    // стек [cond, parent_active]
    let mut stack: Vec<(bool, bool)> = Vec::new();
    let active = |stack: &[(bool, bool)]| stack.iter().all(|(c, p)| *c && *p);
    for raw in lines {
        let s = raw.trim();
        if s.is_empty() || s.starts_with("::") || s.starts_with('@') {
            continue;
        }
        let low = s.to_lowercase();
        // if [not] exist <path> (
        if low.starts_with("if ") {
            // пробуем exist
            let after_if = s[2..].trim_start();
            // not?
            let (neg, rest) = if after_if.len() > 4 && after_if[..4].eq_ignore_ascii_case("not ") {
                (true, after_if[4..].trim_start())
            } else if after_if.len() > 3 && after_if[..3].eq_ignore_ascii_case("not") {
                (true, after_if[3..].trim_start())
            } else {
                (false, after_if)
            };
            if rest.len() > 5 && rest[..5].eq_ignore_ascii_case("exist") {
                let mut path = rest[5..].trim();
                // заканчивается на (
                if path.ends_with('(') {
                    path = path[..path.len() - 1].trim_end();
                    let parent = active(&stack);
                    let mut p = path.trim().trim_matches('"').to_string();
                    p = p.replace("%~dp0", batdir);
                    p = bat_expand_vars(&p, &env);
                    let mut hit = Path::new(&p).exists();
                    if neg {
                        hit = !hit;
                    }
                    stack.push((hit, parent));
                    continue;
                }
            }
            if rest.len() > 7 && rest[..7].eq_ignore_ascii_case("defined") {
                let mut name = rest[7..].trim();
                if name.ends_with('(') {
                    name = name[..name.len() - 1].trim_end();
                    let parent = active(&stack);
                    let mut hit = env.contains_key(&name.to_uppercase());
                    if neg {
                        hit = !hit;
                    }
                    stack.push((hit, parent));
                    continue;
                }
            }
            if s.ends_with('(') {
                // неизвестное условие — тело пропускаем
                let parent = active(&stack);
                stack.push((false, parent));
                continue;
            }
            continue;
        }
        if low == ") else (" || low == ")else(" {
            if let Some(top) = stack.last_mut() {
                top.0 = !top.0;
            }
            continue;
        }
        if s == ")" {
            stack.pop();
            continue;
        }
        if let Some((name, mut val)) = parse_set_line(s) {
            if !active(&stack) {
                continue;
            }
            val = val.replace("%~dp0", batdir);
            val = bat_expand_vars(&val, &env);
            if val.is_empty() {
                env.remove(&name);
            } else {
                env.insert(name, val);
            }
        }
    }
    env
}

fn collapse_ws(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Caret-эскейпы cmd: ^X -> X.
fn uncaret(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut it = s.chars();
    while let Some(c) = it.next() {
        if c == '^' {
            if let Some(n) = it.next() {
                out.push(n);
            }
            continue;
        }
        out.push(c);
    }
    let mut o = out;
    while o.ends_with('^') {
        o.pop();
    }
    o
}

const STRAT_END: &[&str] = &[
    "pause", "exit", "goto ", "goto:", ":eof", "popd", "endlocal", "title ", "color ",
    "timeout ", "choice ", "cls",
];

/// Аргументы winws.exe из bat (аналог build_service_args).
pub fn build_service_args(zapret_root: &str, bat_name: &str) -> Result<String, String> {
    let fp = Path::new(zapret_root).join(bat_name);
    let raw = std::fs::read_to_string(&fp).map_err(|e| format!("Не могу прочитать {bat_name}: {e}"))?;
    let glued = raw.replace("^\r\n", " ").replace("^\n", " ");
    let lines: Vec<String> = glued.lines().map(|l| l.to_string()).collect();
    let batdir = fp
        .parent()
        .map(|d| {
            let mut s = d.to_string_lossy().into_owned();
            if !s.ends_with(['\\', '/']) {
                s.push('\\');
            }
            s
        })
        .unwrap_or_default();
    let env = bat_collect_env(&lines, &batdir);
    let mut parts: Vec<String> = Vec::new();
    let mut capturing = false;
    for line in &lines {
        let low = line.to_lowercase();
        if low.contains("winws.exe") {
            let idx = low.find("winws.exe").unwrap() + "winws.exe".len();
            let mut tail = line[idx..].trim().to_string();
            if let Some(t) = tail.strip_prefix('"') {
                tail = t.to_string();
            }
            if tail.contains("--") {
                capturing = true;
                parts = vec![tail];
            } else if !capturing {
                capturing = true;
            }
            continue;
        }
        if !capturing {
            continue;
        }
        let s = line.trim();
        let l = s.to_lowercase();
        if STRAT_END.iter().any(|p| l.starts_with(p)) {
            break;
        }
        if s.is_empty()
            || s.starts_with("::")
            || l.starts_with("@echo")
            || l.starts_with("cd ")
            || l.starts_with("call ")
            || l.starts_with("set ")
            || l.starts_with("echo")
        {
            if l.contains("winws") || s.starts_with("--") || s.starts_with("\"--") {
                parts.push(s.to_string());
            }
            continue;
        }
        parts.push(s.to_string());
    }
    let mut args = collapse_ws(&uncaret(&parts.join(" ")));
    // отрезать хвосты start/cmd: висячие & | ) + слово
    loop {
        let t = args.trim_end();
        // ищем хвост вида <ws>[&|)]+<ws>[keyword]<ws>*$
        let bytes = t.as_bytes();
        let mut i = bytes.len();
        while i > 0 && bytes[i - 1].is_ascii_whitespace() {
            i -= 1;
        }
        let mut j = i;
        while j > 0 && bytes[j - 1].is_ascii_alphabetic() {
            j -= 1;
        }
        let word = &t[j..i];
        let wl = word.to_lowercase();
        let is_kw = wl.is_empty()
            || ["pause", "exit", "goto", "popd", "endlocal"].contains(&wl.as_str());
        // перед словом должны быть разделители
        let mut k = j;
        while k > 0 && bytes[k - 1].is_ascii_whitespace() {
            k -= 1;
        }
        let mut had_sep = false;
        while k > 0 && (bytes[k - 1] == b'&' || bytes[k - 1] == b'|' || bytes[k - 1] == b')') {
            had_sep = true;
            k -= 1;
        }
        if had_sep && is_kw {
            args = t[..k].trim_end().to_string();
            continue;
        }
        args = t.to_string();
        break;
    }
    if args.is_empty() || !args.contains("--") {
        return Err("Не найдены аргументы winws в bat-файле".into());
    }
    let mut out = args.replace("%~dp0", &batdir);
    out = bat_expand_vars(&out, &env);
    let bin = format!("{}\\bin\\", zapret_root.trim_end_matches(['\\', '/']));
    let lists = format!("{}\\lists\\", zapret_root.trim_end_matches(['\\', '/']));
    let (tcp, udp) = get_game_filter(zapret_root);
    out = out.replace("%BIN%", &bin).replace("%LISTS%", &lists);
    out = out
        .replace("%GameFilterTCP%", &tcp)
        .replace("%GameFilterUDP%", &udp)
        .replace("%GameFilter%", &tcp);
    // неопределённые %VAR% -> пусто (%% -> %)
    out = out.replace("%%", "\x00");
    {
        let mut res = String::with_capacity(out.len());
        let b = out.as_bytes();
        let mut i = 0;
        while i < b.len() {
            if b[i] == b'%' {
                if let Some(rel) = out[i + 1..].find('%') {
                    let inner = &out[i + 1..i + 1 + rel];
                    if !inner.is_empty()
                        && !inner.contains(char::is_whitespace)
                        && !inner.contains('%')
                    {
                        i += rel + 2;
                        continue;
                    }
                }
            }
            res.push(b[i] as char);
            i += 1;
        }
        out = res.replace('\x00', "%");
    }
    out = out.trim_start_matches(['"', ' ', '\t']).to_string();
    out = fallback_missing_files(&out, zapret_root);
    Ok(out)
}

/// Файлы, которых нет по пути: поискать basename в lists/ и bin/.
fn fallback_missing_files(args: &str, zapret_root: &str) -> String {
    let lists_dir = Path::new(zapret_root).join("lists");
    let bin_dir = Path::new(zapret_root).join("bin");
    let mut out = String::new();
    let b = args.as_bytes();
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'"' {
            if let Some(rel) = args[i + 1..].find('"') {
                let inner = &args[i + 1..i + 1 + rel];
                if inner.contains('\\') || inner.contains('/') {
                    let fixed = fix_path(inner, &lists_dir, &bin_dir);
                    out.push('"');
                    out.push_str(&fixed);
                    out.push('"');
                    i += rel + 2;
                    continue;
                }
            }
        }
        out.push(b[i] as char);
        i += 1;
    }
    out
}

fn fix_path(path: &str, lists_dir: &Path, bin_dir: &Path) -> String {
    if path.is_empty() || Path::new(path).exists() {
        return path.to_string();
    }
    if let Some(base) = Path::new(path).file_name().and_then(|n| n.to_str()) {
        for d in [lists_dir, bin_dir] {
            let cand = d.join(base);
            if cand.exists() {
                return cand.to_string_lossy().into_owned();
            }
        }
    }
    path.to_string()
}

pub fn get_game_filter(zapret_root: &str) -> (String, String) {
    let (mut tcp, mut udp) = ("12".to_string(), "12".to_string());
    let p = Path::new(zapret_root).join("utils").join("game_filter.enabled");
    if let Ok(mode) = std::fs::read_to_string(&p) {
        match mode.trim().to_lowercase().as_str() {
            "all" => {
                tcp = "1024-65535".into();
                udp = "1024-65535".into();
            }
            "tcp" => tcp = "1024-65535".into(),
            "udp" => udp = "1024-65535".into(),
            _ => {}
        }
    }
    (tcp, udp)
}

// ================= службы и процессы =================

#[derive(Debug, Clone, Serialize)]
pub struct ServiceStatus {
    pub zapret: String,
    pub windivert: String,
    pub winws: bool,
    pub strategy: String,
}

fn sc_state(name: &str) -> String {
    let (_rc, out) = run_cmd(&["sc", "query", name], Duration::from_secs(8));
    let low = out.to_lowercase();
    if low.contains("running") {
        "RUNNING".into()
    } else if low.contains("stopped") {
        "STOPPED".into()
    } else if low.contains("failed") || low.contains("1060") || low.contains("does not exist") || low.contains("не существует") {
        "NOT_INSTALLED".into()
    } else if _rc == 0 {
        "UNKNOWN".into()
    } else {
        "NOT_INSTALLED".into()
    }
}

fn reg_strategy() -> String {
    let (_rc, out) = run_cmd(
        &[
            "reg",
            "query",
            r"HKLM\System\CurrentControlSet\Services\zapret",
            "/v",
            "zapret-discord-youtube",
        ],
        Duration::from_secs(8),
    );
    for line in out.lines() {
        if line.contains("REG_SZ") {
            if let Some(pos) = line.find("REG_SZ") {
                return line[pos + 6..].trim().to_string();
            }
        }
    }
    String::new()
}

pub fn service_status() -> ServiceStatus {
    let zapret = sc_state("zapret");
    let windivert = sc_state("WinDivert");
    let (_rc, out) = run_cmd(
        &["tasklist", "/FI", "IMAGENAME eq winws.exe"],
        Duration::from_secs(8),
    );
    ServiceStatus {
        zapret,
        windivert,
        winws: out.to_lowercase().contains("winws.exe"),
        strategy: reg_strategy(),
    }
}

pub fn install_service(zapret_root: &str, bat_name: &str) -> (bool, String) {
    let args = match build_service_args(zapret_root, bat_name) {
        Ok(a) => a,
        Err(e) => return (false, e),
    };
    let bin_path = Path::new(zapret_root).join("bin").join("winws.exe");
    if !bin_path.exists() {
        return (false, format!("winws.exe не найден: {}", bin_path.display()));
    }
    let full = format!("\"{}\" {}", bin_path.display(), args);
    let stem = bat_name.strip_suffix(".bat").unwrap_or(bat_name);
    let cmds = format!(
        "sc stop zapret >nul 2>&1 & sc delete zapret >nul 2>&1 & \
         sc create zapret binPath= \"{full}\" DisplayName= \"zapret\" start= auto & \
         sc description zapret \"Zapret DPI bypass software\" & sc start zapret & \
         reg add \"HKLM\\System\\CurrentControlSet\\Services\\zapret\" /v zapret-discord-youtube /t REG_SZ /d \"{stem}\" /f"
    );
    let (rc, out) = run_shell(&cmds, Duration::from_secs(30));
    std::thread::sleep(Duration::from_secs(2));
    if service_status().zapret == "RUNNING" {
        (true, "Служба zapret установлена и запущена".into())
    } else {
        let tail: String = out.chars().take(600).collect();
        (false, format!("Не удалось запустить службу. Вывод: {tail} (код {rc})"))
    }
}

pub fn remove_service() -> (bool, String) {
    let cmds = "net stop zapret >nul 2>&1 & sc delete zapret >nul 2>&1 & \
        taskkill /IM winws.exe /F >nul 2>&1 & net stop WinDivert >nul 2>&1 & \
        sc delete WinDivert >nul 2>&1 & net stop WinDivert14 >nul 2>&1 & sc delete WinDivert14 >nul 2>&1";
    run_shell(cmds, Duration::from_secs(30));
    (true, "Службы zapret / WinDivert удалены, winws остановлен".into())
}

pub fn stop_winws() {
    run_cmd(&["taskkill", "/IM", "winws.exe", "/F"], Duration::from_secs(8));
}

pub fn winws_running() -> bool {
    let (_rc, out) = run_cmd(
        &["tasklist", "/FI", "IMAGENAME eq winws.exe"],
        Duration::from_secs(8),
    );
    out.to_lowercase().contains("winws.exe")
}

pub fn wait_winws_alive(timeout: Duration) -> bool {
    let t0 = std::time::Instant::now();
    while t0.elapsed() < timeout {
        if winws_running() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(400));
    }
    false
}

/// Прямой скрытый запуск winws (raw_arg сохраняет командную строку байт в байт).
/// Затем — скрытая консоль bat (cmd сам раскрывает переменные). Возвращает успех.
pub fn start_winws_hidden(zapret_root: &str, bat_name: &str) -> bool {
    if let Ok(args) = build_service_args(zapret_root, bat_name) {
        let exe = Path::new(zapret_root).join("bin").join("winws.exe");
        if exe.exists() {
            let mut cmd = Command::new(&exe);
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                cmd.creation_flags(CREATE_NO_WINDOW);
                cmd.raw_arg(&args);
            }
            #[cfg(not(windows))]
            {
                cmd.arg(&args);
            }
            cmd.current_dir(Path::new(zapret_root).join("bin"));
            cmd.stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null());
            if cmd.spawn().is_ok() && wait_winws_alive(Duration::from_secs(2)) {
                return true;
            }
        }
        stop_winws();
        std::thread::sleep(Duration::from_millis(300));
    }
    // фолбэк: настоящий bat в скрытой консоли
    let fp = Path::new(zapret_root).join(bat_name);
    if fp.exists() {
        let mut cmd = Command::new("cmd");
        cmd.args(["/c", &fp.to_string_lossy()]);
        #[cfg(windows)]
        cmd.creation_flags(CREATE_NO_WINDOW);
        cmd.stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null());
        if let Ok(mut child) = cmd.spawn() {
            let alive = wait_winws_alive(Duration::from_secs(3));
            let _ = child.kill();
            if alive {
                return true;
            }
        }
        stop_winws();
    }
    false
}

// ================= автозагрузка / dns =================

const TASK_NAME: &str = "ZapretManager";

pub fn app_autostart_enabled() -> bool {
    let (rc, _) = run_cmd(&["schtasks", "/query", "/tn", TASK_NAME], Duration::from_secs(10));
    rc == 0
}

/// Задача планировщика: при входе, с высшими правами. Требует админа (он есть по манифесту).
pub fn set_app_autostart(enable: bool, exe: &str) -> (bool, String) {
    if enable {
        let target = format!("\"{exe}\" --minimized");
        let (rc, out) = run_cmd(
            &[
                "schtasks", "/create", "/tn", TASK_NAME, "/tr", &target, "/sc", "onlogon",
                "/rl", "highest", "/f",
            ],
            Duration::from_secs(20),
        );
        if rc != 0 {
            let tail: String = out.chars().take(300).collect();
            return (false, format!("schtasks: {tail}"));
        }
        // подчистить legacy Run-значение
        run_cmd(
            &[
                "reg", "delete",
                r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                "/v", "ZapretManager", "/f",
            ],
            Duration::from_secs(10),
        );
        (true, "Приложение будет запускаться при входе с правами администратора".into())
    } else {
        run_cmd(&["schtasks", "/delete", "/tn", TASK_NAME, "/f"], Duration::from_secs(15));
        run_cmd(
            &[
                "reg", "delete",
                r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                "/v", "ZapretManager", "/f",
            ],
            Duration::from_secs(10),
        );
        (true, String::new())
    }
}

pub fn flush_dns() -> (bool, String) {
    let (rc, out) = run_cmd(&["ipconfig", "/flushdns"], Duration::from_secs(15));
    let low = out.to_lowercase();
    let ok = rc == 0 || low.contains("успешно") || low.contains("success");
    (ok, if ok { "Очищен".into() } else { format!("Не сброшен: {}", out.trim().chars().take(150).collect::<String>()) })
}

/// Сброс сетевого стека (нужен админ + ребут, как в v1).
pub fn net_reset() -> (bool, String) {
    let (rc, out) = run_shell("netsh winsock reset & netsh int ip reset", Duration::from_secs(30));
    let msg = if rc == 0 {
        "Стек сброшен — перезагрузите ПК.".to_string()
    } else {
        format!("Не сброшен: {}", out.trim().chars().take(200).collect::<String>())
    };
    (rc == 0, msg)
}

/// Перезапуск службы zapret (как кнопка ↻ в v1 при активной службе).
pub fn restart_service() -> (bool, String) {
    run_shell("net stop zapret >nul 2>&1 & net start zapret >nul 2>&1", Duration::from_secs(30));
    std::thread::sleep(Duration::from_secs(2));
    let st = service_status();
    let msg = format!("Служба zapret: {}", st.zapret);
    (st.zapret == "RUNNING", msg)
}

/// Перезапуск разового конфига без службы.
pub fn restart_standalone(zapret_root: &str, bat: &str) -> (bool, String) {
    stop_winws();
    std::thread::sleep(Duration::from_secs(1));
    let ok = start_winws_hidden(zapret_root, bat);
    std::thread::sleep(Duration::from_secs(2));
    let running = winws_running();
    (ok && running, format!("{bat}: {}", if running { "запущен" } else { "не запустился" }))
}

// ================= game/ipset фильтры =================

/// (включён, режим-текст) для game_filter.enabled.
pub fn game_filter_status(zapret_root: &str) -> (bool, String) {
    let p = Path::new(zapret_root).join("utils").join("game_filter.enabled");
    if let Ok(mode) = std::fs::read_to_string(&p) {
        return match mode.trim().to_lowercase().as_str() {
            "all" => (true, "TCP+UDP".into()),
            "tcp" => (true, "TCP".into()),
            "udp" => (true, "UDP".into()),
            _ => (false, "Выкл".into()),
        };
    }
    (false, "Выкл".into())
}

/// Цикл: выкл -> all -> tcp -> udp -> выкл. Возвращает новый текст режима.
pub fn game_filter_cycle(zapret_root: &str) -> String {
    let p = Path::new(zapret_root).join("utils").join("game_filter.enabled");
    let cur = std::fs::read_to_string(&p).unwrap_or_default().trim().to_lowercase();
    let modes = ["", "all", "tcp", "udp"];
    let idx = modes.iter().position(|m| *m == cur).unwrap_or(0);
    let next = modes[(idx + 1) % modes.len()];
    if next.is_empty() {
        let _ = std::fs::remove_file(&p);
    } else if std::fs::write(&p, next).is_err() {
        return "Ошибка".into();
    }
    match next {
        "all" => "TCP+UDP",
        "tcp" => "TCP",
        "udp" => "UDP",
        _ => "Выкл",
    }
    .to_string()
}

/// Статус ipset-all.txt: loaded / none / any.
pub fn ipset_status(zapret_root: &str) -> String {
    let p = Path::new(zapret_root).join("lists").join("ipset-all.txt");
    let content = match std::fs::read_to_string(&p) {
        Ok(c) => c,
        Err(_) => return "any".into(),
    };
    if content.lines().next().is_none() {
        return "any".into();
    }
    if content.lines().any(|l| l.contains("203.0.113.113/32")) {
        return "none".into();
    }
    "loaded".into()
}

/// Цикл: loaded -> none -> any -> loaded. Возвращает новый статус.
pub fn ipset_cycle(zapret_root: &str) -> Result<String, String> {
    let p = Path::new(zapret_root).join("lists").join("ipset-all.txt");
    let backup = Path::new(&format!("{}.backup", p.to_string_lossy())).to_path_buf();
    match ipset_status(zapret_root).as_str() {
        "loaded" => {
            if backup.exists() {
                std::fs::remove_file(&backup).map_err(|e| e.to_string())?;
            }
            std::fs::rename(&p, &backup).map_err(|e| e.to_string())?;
            std::fs::write(&p, "203.0.113.113/32\n").map_err(|e| e.to_string())?;
            Ok("none".into())
        }
        "none" => {
            std::fs::write(&p, "").map_err(|e| e.to_string())?;
            Ok("any".into())
        }
        _ => {
            if !backup.exists() {
                return Err("Нет бэкапа ipset-all.txt.backup для восстановления".into());
            }
            if p.exists() {
                std::fs::remove_file(&p).map_err(|e| e.to_string())?;
            }
            std::fs::rename(&backup, &p).map_err(|e| e.to_string())?;
            Ok("loaded".into())
        }
    }
}

// ================= диагностика =================

#[derive(Debug, Clone, Serialize)]
pub struct DiagRow {
    pub icon: String,
    pub name: String,
    pub status: String,
    pub kind: String, // good | warn | bad
}

fn reg_dword(hive: &str, key: &str, value: &str) -> Option<u32> {
    let (_rc, out) = run_cmd(&["reg", "query", &format!("{hive}\\{key}"), "/v", value], Duration::from_secs(8));
    for line in out.lines() {
        if line.contains("REG_DWORD") {
            let hex = line.split_whitespace().last().unwrap_or("");
            let hex = hex.strip_prefix("0x").unwrap_or(hex);
            if let Ok(n) = u32::from_str_radix(hex, 16) {
                return Some(n);
            }
        }
    }
    None
}

/// Диагностика как service.bat: BFE, прокси, TCP-метки, AdGuard, Killer, WinDivert.
pub fn run_diagnostics() -> Vec<DiagRow> {
    let mut rows = Vec::new();
    let (_rc, out) = run_cmd(&["sc", "query", "BFE"], Duration::from_secs(5));
    if out.contains("RUNNING") {
        rows.push(DiagRow { icon: "✓".into(), name: "Base Filtering Engine".into(), status: "running".into(), kind: "good".into() });
    } else {
        rows.push(DiagRow { icon: "✗".into(), name: "Base Filtering Engine".into(), status: "NOT running!".into(), kind: "bad".into() });
    }
    let proxy = reg_dword("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", "ProxyEnable").unwrap_or(0) == 1;
    if proxy {
        rows.push(DiagRow { icon: "!".into(), name: "System Proxy".into(), status: "enabled (may interfere)".into(), kind: "warn".into() });
    } else {
        rows.push(DiagRow { icon: "✓".into(), name: "System Proxy".into(), status: "disabled".into(), kind: "good".into() });
    }
    let (_rc, out) = run_cmd(&["netsh", "interface", "tcp", "show", "global"], Duration::from_secs(5));
    let low = out.to_lowercase();
    if low.contains("timestamps") && low.contains("enabled") {
        rows.push(DiagRow { icon: "✓".into(), name: "TCP Timestamps".into(), status: "enabled".into(), kind: "good".into() });
    } else {
        rows.push(DiagRow { icon: "!".into(), name: "TCP Timestamps".into(), status: "disabled".into(), kind: "warn".into() });
    }
    let (_rc, out) = run_cmd(&["tasklist", "/FI", "IMAGENAME eq AdguardSvc.exe"], Duration::from_secs(5));
    if out.contains("AdguardSvc.exe") {
        rows.push(DiagRow { icon: "✗".into(), name: "AdguardSvc".into(), status: "running (conflicts)".into(), kind: "bad".into() });
    } else {
        rows.push(DiagRow { icon: "✓".into(), name: "AdguardSvc".into(), status: "not running".into(), kind: "good".into() });
    }
    let (_rc, out) = run_cmd(&["sc", "query"], Duration::from_secs(5));
    if out.contains("Killer") {
        rows.push(DiagRow { icon: "✗".into(), name: "Killer Service".into(), status: "found (conflicts)".into(), kind: "bad".into() });
    } else {
        rows.push(DiagRow { icon: "✓".into(), name: "Killer Service".into(), status: "not found".into(), kind: "good".into() });
    }
    let (_rc, out) = run_cmd(&["sc", "query", "WinDivert"], Duration::from_secs(5));
    if out.contains("RUNNING") {
        rows.push(DiagRow { icon: "✓".into(), name: "WinDivert".into(), status: "running".into(), kind: "good".into() });
    } else {
        rows.push(DiagRow { icon: "✗".into(), name: "WinDivert".into(), status: "not running".into(), kind: "bad".into() });
    }
    rows
}

// ================= VPN =================

/// Активные VPN-адаптеры (имена) через Get-NetAdapter, как в v1.
pub fn vpn_status() -> (bool, Vec<String>) {
    let mut names: Vec<String> = Vec::new();
    let patterns = [
        "vpn", "tap", "tun", "wireguard", "openvpn", "nordlynx", "expressvpn", "surfshark",
        "proton", "wintun", "wiresock", "anyconnect", "forti", "globalprotect", "zscaler",
        "warp", "hamachi", "radmin", "zerotier", "tailscale", "neagent", "check point",
    ];
    let (rc, out) = run_cmd(
        &[
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | ForEach-Object { $_.Name + '|' + $_.InterfaceDescription }",
        ],
        Duration::from_secs(12),
    );
    if rc == 0 {
        for line in out.lines() {
            if !line.contains('|') {
                continue;
            }
            let low = line.to_lowercase();
            if patterns.iter().any(|p| low.contains(p)) {
                if let Some(nm) = line.split('|').next() {
                    let nm = nm.trim().to_string();
                    if !nm.is_empty() && !names.contains(&nm) {
                        names.push(nm);
                    }
                }
            }
        }
    }
    let active = !names.is_empty();
    (active, names)
}

// ================= ресурсы =================
// Только реальное потребление САМОЙ программы (её процесса),
// плюс процесс winws, если запущен. Никаких общесистемных цифр.

#[derive(Debug, Clone, Serialize)]
pub struct ProcStat {
    pub cpu: Option<f32>,
    pub ram_mb: Option<u64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ResourceStat {
    pub app: ProcStat,
    pub winws: Option<ProcStat>,
}

fn round1(v: f32) -> Option<f32> {
    if v.is_finite() {
        Some((v * 10.0).round() / 10.0)
    } else {
        None
    }
}

pub fn resource_status() -> ResourceStat {
    use sysinfo::{Pid, ProcessesToUpdate, System};
    let me = Pid::from_u32(std::process::id());
    let mut sys = System::new();
    // CPU считается по дельте: первый замер — база, второй — значение
    sys.refresh_processes(ProcessesToUpdate::Some(&[me]), true);
    std::thread::sleep(Duration::from_millis(300));
    sys.refresh_processes(ProcessesToUpdate::All, true);
    let app = sys
        .process(me)
        .map(|p| ProcStat {
            cpu: round1(p.cpu_usage()),
            ram_mb: Some(p.memory() / 1024 / 1024),
        })
        .unwrap_or(ProcStat { cpu: None, ram_mb: None });
    let winws = sys
        .processes()
        .values()
        .find(|p| p.name().to_string_lossy().eq_ignore_ascii_case("winws.exe"))
        .map(|p| ProcStat {
            cpu: round1(p.cpu_usage()),
            ram_mb: Some(p.memory() / 1024 / 1024),
        });
    ResourceStat { app, winws }
}

// ================= снапшот lists (diff релиза) =================

fn fnv1a64(data: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in data {
        h ^= *b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

/// {имя: hash} для lists/. Дешевле sha1, для diff достаточно.
pub fn snapshot_lists(zapret_root: &str) -> HashMap<String, String> {
    let mut snap = HashMap::new();
    let d = Path::new(zapret_root).join("lists");
    if let Ok(rd) = std::fs::read_dir(&d) {
        let mut names: Vec<String> = Vec::new();
        for e in rd.flatten() {
            if e.path().is_file() {
                if let Some(n) = e.file_name().to_str() {
                    names.push(n.to_string());
                }
            }
        }
        names.sort();
        for n in names {
            if let Ok(data) = std::fs::read(&d.join(&n)) {
                snap.insert(n, format!("{:016x}", fnv1a64(&data)));
            }
        }
    }
    snap
}

#[derive(Debug, Clone, Serialize)]
pub struct ListsDiff {
    pub added: Vec<String>,
    pub removed: Vec<String>,
    pub changed: Vec<String>,
}

pub fn diff_snaps(old: &HashMap<String, String>, new: &HashMap<String, String>) -> ListsDiff {    let mut added: Vec<String> = new.keys().filter(|k| !old.contains_key(*k)).cloned().collect();
    let mut removed: Vec<String> = old.keys().filter(|k| !new.contains_key(*k)).cloned().collect();
    let mut changed: Vec<String> = new
        .iter()
        .filter(|(k, v)| old.get(*k).map(|o| o != *v).unwrap_or(false))
        .map(|(k, _)| k.clone())
        .collect();
    added.sort();
    removed.sort();
    changed.sort();
    ListsDiff { added, removed, changed }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Корень zapret для тестов: перебор реальных папок, пропуск если нет.
    fn test_root() -> Option<String> {
        if let Ok(p) = std::env::var("ZAPRET_TEST_ROOT") {
            if std::path::Path::new(&p).is_dir() {
                return Some(p);
            }
        }
        let mut cands: Vec<String> = Vec::new();
        if let Ok(home) = std::env::var("USERPROFILE") {
            let desk = std::path::Path::new(&home).join("Desktop");
            if let Ok(rd) = std::fs::read_dir(&desk) {
                let mut v: Vec<String> = rd
                    .flatten()
                    .filter(|e| e.path().is_dir())
                    .filter_map(|e| e.file_name().into_string().ok())
                    .filter(|n| n.starts_with("zapret-discord-youtube"))
                    .collect();
                v.sort();
                for n in v {
                    cands.push(desk.join(n).to_string_lossy().into_owned());
                }
            }
        }
        for fixed in [
            r"D:\Desktop\zapret-discord-youtube-main",
            r"C:\zapret",
            r"D:\zapret",
        ] {
            cands.push(fixed.to_string());
        }
        cands.into_iter().find(|p| std::path::Path::new(p).is_dir())
    }

    #[test]
    fn configs_found() {
        let Some(root) = test_root() else {
            println!("SKIP: нет папки zapret");
            return;
        };
        let cfgs = list_configs(&root);
        assert!(!cfgs.is_empty(), "конфиги не найдены");
        assert!(cfgs.iter().any(|c| c.to_lowercase().contains("general")));
        assert!(!cfgs.iter().any(|c| c.to_lowercase().starts_with("service")));
    }

    #[test]
    fn display_names() {
        assert_eq!(display_bat(r"pre-configs\general.bat"), "general");
        assert_eq!(display_bat(r"pre-configs\general (ALT).bat"), "general (ALT)");
    }

    #[test]
    fn targets_parsed() {
        let Some(root) = test_root() else {
            println!("SKIP: нет папки zapret");
            return;
        };
        let t = parse_targets(&root);
        assert!(t.len() >= 3, "целей мало: {}", t.len());
        assert!(t.iter().any(|(n, _)| n == "DiscordMain"));
    }

    #[test]
    fn split_hosts() {
        assert_eq!(split_host("PING:1.1.1.1"), ("1.1.1.1".to_string(), true));
        assert_eq!(
            split_host("https://www.youtube.com/watch?v=1"),
            ("www.youtube.com".to_string(), false)
        );
    }

    #[test]
    fn resource_self_present() {
        let s = resource_status();
        assert!(s.app.ram_mb.unwrap_or(0) > 0, "нет своей RAM");
        assert!(s.app.cpu.is_some(), "нет своего CPU");
    }

    #[test]
    fn args_from_general() {
        let Some(root) = test_root() else {
            println!("SKIP: нет папки zapret");
            return;
        };
        let Some(bat) = list_configs(&root).into_iter().find(|c| c.to_lowercase().ends_with(".bat")) else {
            println!("SKIP: нет .bat");
            return;
        };
        let args = build_service_args(&root, &bat).expect("парсер пуст");
        assert!(args.contains("--"), "нет флагов: {args:.120}");
        assert!(args.contains("--filter"), "нет фильтров: {args:.200}");
        assert!(!args.contains("%GameFilterTCP%"), "переменные не раскрыты");
        assert!(!args.contains("%~dp0"), "%~dp0 не раскрыт");
    }

    #[test]
    fn args_all_configs() {
        // каждый найденный конфиг обязан дать аргументы winws
        let Some(root) = test_root() else {
            println!("SKIP: нет папки zapret");
            return;
        };
        let mut bad = Vec::new();
        for c in list_configs(&root) {
            if build_service_args(&root, &c).is_err() {
                bad.push(c);
            }
        }
        assert!(bad.is_empty(), "битые конфиги: {bad:?}");
    }

    #[test]
    fn diff_logic() {
        let old: HashMap<String, String> =
            [("a".into(), "1".into()), ("b".into(), "2".into())].into();
        let new: HashMap<String, String> =
            [("b".into(), "3".into()), ("c".into(), "4".into())].into();
        let d = diff_snaps(&old, &new);
        assert_eq!(d.added, vec!["c".to_string()]);
        assert_eq!(d.removed, vec!["a".to_string()]);
        assert_eq!(d.changed, vec!["b".to_string()]);
    }

    #[test]
    fn snapshot_lists_live() {
        let Some(root) = test_root() else {
            println!("SKIP: нет папки zapret");
            return;
        };
        let snap = snapshot_lists(&root);
        assert!(!snap.is_empty(), "снапшот пуст");
    }
}

