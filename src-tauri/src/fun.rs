//! Funny option, секретные наборы (VSD/Spamton), конструктор стратегий.
//! Порт Python-версии: в вебе GIF играют сами (<img>), шифр читает zip-crate.
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::path::PathBuf;

// ---------- пути к ассетам ----------

/// Каталог assets: в проде — resources рядом с exe, в dev — корень проекта.
fn assets_dir() -> PathBuf {
    // cargo run: CWD = src-tauri -> ../assets
    let dev = PathBuf::from("../assets");
    if dev.is_dir() {
        return dev;
    }
    // прод: <exe>/../resources/assets (NSIS кладёт рядом) или <exe>/assets
    if let Ok(exe) = std::env::current_exe() {
        if let Some(d) = exe.parent() {
            for cand in [
                d.join("assets"),
                d.join("resources").join("assets"),
                d.join("_up_").join("assets"),
                d.join("_up_").join("resources").join("assets"),
            ] {
                if cand.is_dir() {
                    return cand;
                }
            }
            // запасной вариант: ищем wizard.jpg рекурсивно на 2 уровня (мало файлов — дёшево)
            if let Ok(rd) = std::fs::read_dir(d) {
                for e in rd.flatten() {
                    let p = e.path();
                    if p.is_dir() {
                        let c = p.join("assets");
                        if c.is_dir() {
                            return c;
                        }
                    }
                }
            }
        }
    }
    // tauri resource_dir (когда доступно через AppHandle — фронт не ходит сюда)
    PathBuf::from("assets")
}

pub fn funny_dir() -> PathBuf {
    assets_dir().join("funny")
}

pub fn packs_dir() -> PathBuf {
    assets_dir().join("packs")
}

pub fn terminal_dir() -> PathBuf {
    assets_dir().join("terminal")
}

pub fn wizard_dir() -> PathBuf {
    assets_dir().join("wizard")
}

/// Картинка мастера (assets/wizard/wizard.jpg) как data URL для первого шага.
pub fn wizard_image() -> Result<String, String> {
    let d = wizard_dir();
    for name in ["wizard.jpg", "wizard.jpeg", "wizard.png"] {
        let ext = if name.ends_with("png") { ".png" } else { ".jpg" };
        if let Some(p) = safe_name(&d, name, &[ext]) {
            let mime = if ext == ".png" { "image/png" } else { "image/jpeg" };
            return data_url(&p, mime);
        }
    }
    Err("Нет картинки мастера (assets/wizard/wizard.jpg)".into())
}

/// Видео мастера (assets/wizard/install_wizards.mp4) как data URL для шага установки.
pub fn wizard_video() -> Result<String, String> {
    let d = wizard_dir();
    if let Some(p) = safe_name(&d, "install_wizards.mp4", &[".mp4"]) {
        return data_url(&p, "video/mp4");
    }
    Err("Нет видео мастера (assets/wizard/install_wizards.mp4)".into())
}

pub fn music_dir() -> PathBuf {
    assets_dir().join("music")
}

/// Фоновая музыка тем (assets/music/*.mp3) как data URL, играет зацикленно.
pub fn theme_music(name: &str) -> Result<String, String> {
    let p = safe_name(&music_dir(), name, &[".mp3"]).ok_or("Нет трека")?;
    data_url(&p, "audio/mpeg")
}

fn safe_name(dir: &PathBuf, name: &str, exts: &[&str]) -> Option<PathBuf> {
    if name.contains(['/', '\\', '\0']) || name.contains("..") {
        return None;
    }
    let low = name.to_lowercase();
    if !exts.iter().any(|e| low.ends_with(e)) {
        return None;
    }
    let p = dir.join(name);
    if p.is_file() {
        Some(p)
    } else {
        None
    }
}

fn data_url(path: &std::path::Path, mime: &str) -> Result<String, String> {
    use std::io::Read;
    let mut f = std::fs::File::open(path).map_err(|e| e.to_string())?;
    let mut buf = Vec::new();
    f.read_to_end(&mut buf).map_err(|e| e.to_string())?;
    Ok(format!("data:{mime};base64,{}", base64_encode(&buf)))
}

fn base64_encode(data: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(data.len() * 4 / 3 + 4);
    for ch in data.chunks(3) {
        let b0 = ch[0] as u32;
        let b1 = *ch.get(1).unwrap_or(&0) as u32;
        let b2 = *ch.get(2).unwrap_or(&0) as u32;
        let n = (b0 << 16) | (b1 << 8) | b2;
        out.push(T[((n >> 18) & 63) as usize] as char);
        out.push(T[((n >> 12) & 63) as usize] as char);
        out.push(if ch.len() > 1 { T[((n >> 6) & 63) as usize] as char } else { '=' });
        out.push(if ch.len() > 2 { T[(n & 63) as usize] as char } else { '=' });
    }
    out
}

// ---------- funny option ----------

/// Имена gif/png из набора (для галереи и телика).
pub fn funny_list() -> Vec<String> {
    let d = funny_dir();
    let mut out = Vec::new();
    if let Ok(rd) = std::fs::read_dir(&d) {
        for e in rd.flatten() {
            if let Some(n) = e.file_name().to_str() {
                let low = n.to_lowercase();
                if (low.ends_with(".gif") || low.ends_with(".png")) && e.path().is_file() {
                    out.push(n.to_string());
                }
            }
        }
    }
    out.sort();
    out
}

pub fn funny_image(name: &str) -> Result<String, String> {
    let p = safe_name(&funny_dir(), name, &[".gif", ".png"]).ok_or("Нет файла")?;
    let mime = if p.extension().map(|e| e == "png").unwrap_or(false) {
        "image/png"
    } else {
        "image/gif"
    };
    data_url(&p, mime)
}

/// Маскот терминала (vault-boy.png/gif), если файл подложили.
pub fn terminal_mascot() -> Option<String> {
    let d = terminal_dir();
    for pat in ["vault-boy.png", "vault-boy.gif"] {
        if let Some(p) = safe_name(&d, pat, &[".png", ".gif"]) {
            let mime = if pat.ends_with("png") { "image/png" } else { "image/gif" };
            if let Ok(u) = data_url(&p, mime) {
                return Some(u);
            }
        }
    }
    None
}

// ---------- секретные наборы ----------

#[derive(Debug, Clone, Serialize)]
pub struct SecretPack {
    pub title: String,
    pub theme: String,
    pub hidden: bool,
    pub files: Vec<String>,
}

fn registry() -> Vec<(String, SecretPackMeta)> {
    vec![
        (
            "75515945e3e811f3a164ded3a60b5b9fb031e1c693eec3b01724318e1e8529a2".into(),
            SecretPackMeta { archive: "vsd_pack.zip", folder: "vsd", title: "VSD", theme: "vsd", hidden: false },
        ),
        (
            "e5348462fa506f3a65ab0039fea38e598b0d5580c5f96d7deedd5fa58d5f05a7".into(),
            SecretPackMeta { archive: "spamton_pack.zip", folder: "spamton", title: "Spamton", theme: "spamton", hidden: true },
        ),
    ]
}

struct SecretPackMeta {
    archive: &'static str,
    folder: &'static str,
    title: &'static str,
    theme: &'static str,
    hidden: bool,
}

fn pack_files_of(folder: &str) -> Vec<String> {
    let d = crate::config::data_dir().join(folder);
    let mut out = Vec::new();
    if let Ok(rd) = std::fs::read_dir(&d) {
        for e in rd.flatten() {
            if let Some(n) = e.file_name().to_str() {
                let low = n.to_lowercase();
                if (low.ends_with(".png") || low.ends_with(".gif")) && e.path().is_file() {
                    out.push(n.to_string());
                }
            }
        }
    }
    out.sort();
    out
}

/// Проверка кода по sha256 + распаковка (пароль = введённый код).
pub fn unlock_pack(code: &str) -> Result<SecretPack, String> {
    let code = code.trim();
    if code.is_empty() {
        return Err("Введите код".into());
    }
    let digest = format!("{:x}", Sha256::digest(code.as_bytes()));
    let meta = registry()
        .into_iter()
        .find(|(h, _)| h == &digest)
        .map(|(_, m)| m)
        .ok_or("Неверный код")?;
    let src = packs_dir().join(meta.archive);
    if !src.is_file() {
        return Err(format!("Нет архива {}", meta.archive));
    }
    let dst = crate::config::data_dir().join(meta.folder);
    std::fs::create_dir_all(&dst).map_err(|e| e.to_string())?;
    let f = std::fs::File::open(&src).map_err(|e| e.to_string())?;
    let mut z = zip::ZipArchive::new(f).map_err(|e| e.to_string())?;
    for i in 0..z.len() {
        let mut entry = z.by_index_decrypt(i, code.as_bytes()).map_err(|_| "Архив не открылся")?;
        let name = entry.name().to_string();
        if name.contains(['/', '\\']) || name.starts_with('.') {
            continue;
        }
        let low = name.to_lowercase();
        if !(low.ends_with(".png") || low.ends_with(".gif")) {
            continue;
        }
        let mut buf = Vec::new();
        use std::io::Read;
        entry.read_to_end(&mut buf).map_err(|e| e.to_string())?;
        std::fs::write(dst.join(&name), &buf).map_err(|e| e.to_string())?;
    }
    let files = pack_files_of(meta.folder);
    if files.is_empty() {
        return Err("Архив пуст".into());
    }
    Ok(SecretPack {
        title: meta.title.to_string(),
        theme: meta.theme.to_string(),
        hidden: meta.hidden,
        files,
    })
}

pub fn pack_state(title: &str) -> Option<SecretPack> {
    registry().into_iter().find(|(_, m)| m.title == title).map(|(_, m)| SecretPack {
        title: m.title.to_string(),
        theme: m.theme.to_string(),
        hidden: m.hidden,
        files: pack_files_of(m.folder),
    })
}

pub fn pack_image(title: &str, name: &str) -> Result<String, String> {
    let meta = registry()
        .into_iter()
        .find(|(_, m)| m.title == title)
        .map(|(_, m)| m)
        .ok_or("Набор неизвестен")?;
    let d = crate::config::data_dir().join(meta.folder);
    let p = safe_name(&d, name, &[".png", ".gif"]).ok_or("Нет файла")?;
    let mime = if p.extension().map(|e| e == "png").unwrap_or(false) {
        "image/png"
    } else {
        "image/gif"
    };
    data_url(&p, mime)
}

// ---------- конструктор стратегий ----------

#[derive(Debug, Clone, Serialize)]
pub struct StrategyDoc {
    pub bat: String,
    pub prefix: String,
    pub blocks: Vec<String>,
}

const STRAT_END: &[&str] = &[
    "pause", "exit", "goto ", "goto:", ":eof", "popd", "endlocal", "title ", "color ",
    "timeout ", "choice ", "cls",
];

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
    while out.ends_with('^') {
        out.pop();
    }
    out
}

/// Разобрать bat на префикс запуска + блоки стратегий (куски между --new).
pub fn strategy_parse(zapret_root: &str, bat: &str) -> Result<StrategyDoc, String> {
    let fp = std::path::Path::new(zapret_root).join(bat);
    let raw = std::fs::read_to_string(&fp).map_err(|e| format!("Не могу прочитать: {e}"))?;
    let lines: Vec<&str> = raw.lines().collect();
    let start = lines
        .iter()
        .position(|l| l.to_lowercase().contains("winws.exe"))
        .ok_or("в файле нет запуска winws.exe")?;
    // префикс — всё до winws.exe включительно (регистронезависимо)
    let line = lines[start];
    let low = line.to_lowercase();
    let pos = low.find("winws.exe").unwrap() + "winws.exe".len();
    let prefix = line[..pos].to_string();
    let mut rest = line[pos..].trim().to_string();
    if let Some(t) = rest.strip_prefix('"') {
        rest = t.to_string();
    }
    let mut end = start;
    for (i, l) in lines.iter().enumerate().skip(start + 1) {
        let t = l.trim().to_lowercase();
        if STRAT_END.iter().any(|p| t.starts_with(p)) {
            break;
        }
        end = i;
    }
    let mut chunks = Vec::new();
    if !rest.is_empty() {
        chunks.push(rest);
    }
    for l in &lines[start + 1..=end.min(lines.len().saturating_sub(1))] {
        if !l.trim().is_empty() {
            chunks.push(l.trim().to_string());
        }
    }
    let args = uncaret(&chunks.join(" "));
    // блоки — куски между отдельно стоящими --new
    let mut blocks: Vec<String> = vec![String::new()];
    for tok in args.split_whitespace() {
        if tok == "--new" {
            blocks.push(String::new());
        } else {
            let last = blocks.last_mut().unwrap();
            if !last.is_empty() {
                last.push(' ');
            }
            last.push_str(tok);
        }
    }
    let blocks: Vec<String> = blocks.into_iter().filter(|b| !b.is_empty()).collect();
    if blocks.is_empty() {
        return Err("не найдены аргументы winws".into());
    }
    Ok(StrategyDoc { bat: bat.to_string(), prefix, blocks })
}

/// Сохранить блоки: склейка --new, переносы через ^. as_new — новое имя или перезапись (.bak).
pub fn strategy_save(zapret_root: &str, bat: &str, blocks: Vec<String>, as_new: Option<String>) -> Result<String, String> {
    let blks: Vec<String> = blocks.into_iter().map(|b| b.trim().to_string()).filter(|b| !b.is_empty()).collect();
    if blks.is_empty() {
        return Err("Нет ни одного блока".into());
    }
    let fp = std::path::Path::new(zapret_root).join(bat);
    let raw = std::fs::read_to_string(&fp).map_err(|e| format!("Не могу прочитать: {e}"))?;
    let orig: Vec<String> = raw.lines().map(|l| l.to_string()).collect();
    let start = orig
        .iter()
        .position(|l| l.to_lowercase().contains("winws.exe"))
        .ok_or("в файле нет запуска winws.exe")?;
    // префикс из текущей строки запуска
    let line = &orig[start];
    let pos = line.to_lowercase().find("winws.exe").unwrap() + "winws.exe".len();
    let prefix = line[..pos].to_string();
    let mut end = start;
    for (i, l) in orig.iter().enumerate().skip(start + 1) {
        let t = l.trim().to_lowercase();
        if STRAT_END.iter().any(|p| t.starts_with(p)) {
            break;
        }
        end = i;
    }
    // сборка с переносами ~220 символов
    let args = blks.join(" --new ");
    let mut wrapped: Vec<String> = Vec::new();
    let mut cur = String::new();
    for tok in args.split(' ') {
        if cur.len() + tok.len() + 1 > 220 && !cur.is_empty() {
            wrapped.push(cur);
            cur = tok.to_string();
        } else {
            if !cur.is_empty() {
                cur.push(' ');
            }
            cur.push_str(tok);
        }
    }
    if !cur.is_empty() {
        wrapped.push(cur);
    }
    let mut new_lines: Vec<String> = orig[..start].to_vec();
    for (i, w) in wrapped.iter().enumerate() {
        if i == 0 {
            new_lines.push(if wrapped.len() > 1 {
                format!("{prefix} {w} ^")
            } else {
                format!("{prefix} {w}")
            });
        } else if i + 1 < wrapped.len() {
            new_lines.push(format!("{w} ^"));
        } else {
            new_lines.push(w.clone());
        }
    }
    new_lines.extend_from_slice(&orig[end + 1..]);
    let dst = if let Some(name) = as_new {
        if name.contains(['/', '\\']) || name.contains("..") || !name.to_lowercase().ends_with(".bat") {
            return Err("Некорректное имя файла".into());
        }
        fp.parent().unwrap_or(std::path::Path::new(".")).join(&name)
    } else {
        let bak = fp.with_extension("bat.bak");
        std::fs::copy(&fp, &bak).map_err(|e| e.to_string())?;
        fp.clone()
    };
    std::fs::write(&dst, new_lines.join("\n") + "\n").map_err(|e| e.to_string())?;
    Ok(dst.file_name().and_then(|n| n.to_str()).unwrap_or("").to_string())
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

    fn first_general(root: &str) -> Option<String> {
        crate::zapret::list_configs(root)
            .into_iter()
            .find(|c| c.to_lowercase().ends_with(".bat"))
    }

    #[test]
    fn strat_blocks_general() {
        let Some(root) = test_root() else {
            println!("SKIP: нет папки zapret");
            return;
        };
        let Some(bat) = first_general(&root) else {
            println!("SKIP: нет .bat в {root}");
            return;
        };
        let doc = strategy_parse(&root, &bat).expect("parse");
        assert!(!doc.blocks.is_empty(), "блоков нет");
        assert!(doc.prefix.to_lowercase().contains("winws.exe"));
        assert!(doc.blocks.iter().all(|b| b.contains("--filter") || b.contains("--dpi")));
    }

    #[test]
    fn strat_roundtrip() {
        // копия в temp, сохранение как новый + перезапись
        let Some(root) = test_root() else {
            println!("SKIP: нет папки zapret");
            return;
        };
        let Some(bat) = first_general(&root) else {
            println!("SKIP: нет .bat в {root}");
            return;
        };
        let tmp = std::env::temp_dir().join("zm_strat_test");
        std::fs::create_dir_all(&tmp).unwrap();
        let src = std::path::Path::new(&root).join(&bat);
        std::fs::copy(&src, tmp.join("general.bat")).unwrap();
        let root = tmp.to_string_lossy().into_owned();
        let doc = strategy_parse(&root, "general.bat").expect("parse");
        assert!(!doc.blocks.is_empty());
        let name = strategy_save(&root, "general.bat", doc.blocks.clone(), Some("general (strategy).bat".into()))
            .expect("save-as");
        assert_eq!(name, "general (strategy).bat");
        // переоткрыть сохранённый и сравнить блоки
        let doc2 = strategy_parse(&root, &name).expect("reparse");
        assert_eq!(doc.blocks, doc2.blocks, "блоки не сошлись после сохранения");
        std::fs::remove_dir_all(&tmp).unwrap();
    }

    #[test]
    fn unlock_wrong_code() {
        assert!(unlock_pack("nope-nope").is_err());
    }

    #[test]
    fn funny_assets_present() {
        // в dev: ../assets относительно src-tauri
        let list = funny_list();
        assert!(!list.is_empty(), "funny пуст");
        assert!(list.iter().any(|n| n == "idle_gif.gif"));
    }

    #[test]
    fn music_files_present() {
        let d = music_dir();
        for f in ["regular.mp3", "special.mp3"] {
            assert!(d.join(f).is_file(), "нет {f}");
        }
    }
}
