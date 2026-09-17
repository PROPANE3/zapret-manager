//! Переустановка zapret из приложения: свежий релиз Flowseal,
//! пользовательские списки сохраняются, diff списков считается.
//! Порт _reinstall_worker из Python-версии.
use crate::{config, zapret};
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tauri::Emitter;

#[derive(Debug, Clone, Serialize)]
pub struct ReinstallProgress {
    pub phase: String,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReinstallDone {
    pub ok: bool,
    pub msg: String,
    pub tag: String,
    pub diff: String,
}

fn emit(app: &tauri::AppHandle, phase: &str, detail: &str) {
    let _ = app.emit(
        "reinstall-progress",
        ReinstallProgress { phase: phase.into(), detail: detail.into() },
    );
}

/// (tag, zip_url) свежего релиза Flowseal.
async fn gh_latest() -> Result<(String, String), String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(20))
        .user_agent("ZapretManager-v2")
        .build()
        .map_err(|e| e.to_string())?;
    let rel: serde_json::Value = client
        .get("https://api.github.com/repos/Flowseal/zapret-discord-youtube/releases/latest")
        .header("Accept", "application/vnd.github+json")
        .send()
        .await
        .map_err(|e| e.to_string())?
        .json()
        .await
        .map_err(|e| e.to_string())?;
    let tag = rel.get("tag_name").and_then(|t| t.as_str()).unwrap_or("").trim().to_string();
    let mut zurl = String::new();
    if let Some(arr) = rel.get("assets").and_then(|a| a.as_array()) {
        for a in arr {
            let nm = a.get("name").and_then(|n| n.as_str()).unwrap_or("");
            if nm.starts_with("zapret-discord-youtube-") && nm.ends_with(".zip") {
                zurl = a.get("browser_download_url").and_then(|u| u.as_str()).unwrap_or("").to_string();
                break;
            }
        }
    }
    if zurl.is_empty() {
        return Err("в релизе нет zip-архива".into());
    }
    Ok((tag, zurl))
}

fn is_config_bat(name: &str) -> bool {
    let low = name.to_lowercase();
    low.ends_with(".bat") && !low.starts_with("service")
}

/// Раскладка конфигов: pre-configs/ + всё внутрь (как organize_configs в v1).
fn organize_configs(root: &Path) -> (usize, String) {
    let pre = root.join("pre-configs");
    if std::fs::create_dir_all(&pre).is_err() {
        return (0, "не создать pre-configs".into());
    }
    let mut moved = 0;
    let names: Vec<String> = std::fs::read_dir(root)
        .map(|rd| {
            rd.flatten()
                .filter(|e| e.path().is_file())
                .filter_map(|e| e.file_name().to_str().map(|n| n.to_string()))
                .collect()
        })
        .unwrap_or_default();
    let mut names = names;
    names.sort();
    for fn_ in names {
        if !is_config_bat(&fn_) {
            continue;
        }
        let src = root.join(&fn_);
        let mut dst = pre.join(&fn_);
        if src == dst {
            continue;
        }
        if dst.exists() {
            let same = std::fs::read(&src)
                .and_then(|a| std::fs::read(&dst).map(|b| (a, b)))
                .map(|(a, b)| a == b)
                .unwrap_or(false);
            if same {
                let _ = std::fs::remove_file(&src);
                continue;
            }
            let stem = fn_.strip_suffix(".bat").unwrap_or(&fn_);
            let mut i = 1;
            while dst.exists() {
                i += 1;
                dst = pre.join(format!("{stem} ({i}).bat"));
            }
        }
        if std::fs::rename(&src, &dst).is_ok() {
            moved += 1;
        }
    }
    if moved > 0 {
        (moved, format!("в pre-configs перенесено конфигов: {moved}"))
    } else {
        (0, "конфиги уже в порядке".into())
    }
}

/// Простой построчный unified diff (LCS, с лимитом строк).
fn unified_diff(old: &[&str], new: &[&str], limit: usize) -> Vec<String> {
    let (n, m) = (old.len(), new.len());
    // LCS-таблица, capped для экономии памяти
    let cap_n = n.min(2000);
    let cap_m = m.min(2000);
    let mut dp = vec![vec![0u16; cap_m + 1]; cap_n + 1];
    for i in (0..cap_n).rev() {
        for j in (0..cap_m).rev() {
            dp[i][j] = if old[i] == new[j] {
                dp[i + 1][j + 1].saturating_add(1)
            } else {
                dp[i + 1][j].max(dp[i][j + 1])
            };
        }
    }
    let mut out = Vec::new();
    let (mut i, mut j) = (0, 0);
    while (i < cap_n || j < cap_m) && out.len() < limit {
        if i < cap_n && j < cap_m && old[i] == new[j] {
            i += 1;
            j += 1;
        } else if j < cap_m && (i >= cap_n || dp[i][j + 1] >= dp[i + 1][j]) {
            out.push(format!("+{}", new[j]));
            j += 1;
        } else if i < cap_n {
            out.push(format!("-{}", old[i]));
            i += 1;
        } else {
            break;
        }
    }
    if n > cap_n || m > cap_m {
        out.push("… (файл обрезан)".into());
    }
    out
}

fn copy_dir(src: &Path, dst: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(dst)?;
    for e in std::fs::read_dir(src)? {
        let e = e?;
        let (s, d) = (e.path(), dst.join(e.file_name()));
        if s.is_dir() {
            copy_dir(&s, &d)?;
        } else {
            std::fs::copy(&s, &d)?;
        }
    }
    Ok(())
}

pub async fn run(app: tauri::AppHandle, root: String) -> ReinstallDone {
    let fail = |msg: String| ReinstallDone { ok: false, msg, tag: String::new(), diff: String::new() };
    let root = PathBuf::from(&root);
    if !root.is_dir() {
        return fail("папка zapret не найдена".into());
    }
    crate::log_action(&format!("Переустановка zapret начата: {}", root.display()), "info");
    // 1. остановить всё
    emit(&app, "status", "останавливаю службу…");
    zapret::remove_service();
    std::thread::sleep(Duration::from_secs(1));
    zapret::stop_winws();
    // 1b. снимок lists/ до замены
    let old_snap = zapret::snapshot_lists(root.to_str().unwrap_or(""));
    // 2. бэкап пользовательских файлов
    emit(&app, "status", "бэкап пользовательских файлов…");
    let tmp = std::env::temp_dir().join(format!("zapret_mgr_{}", std::process::id()));
    let _ = std::fs::create_dir_all(&tmp);
    let mut user_files: Vec<String> = Vec::new();
    for base in ["", "lists"] {
        let d = if base.is_empty() { root.clone() } else { root.join(base) };
        let Ok(rd) = std::fs::read_dir(&d) else { continue };
        for e in rd.flatten() {
            let name = match e.file_name().to_str() {
                Some(n) => n.to_string(),
                None => continue,
            };
            if !(name.ends_with("-user.txt") || name == "ipset-all.txt.backup") || !e.path().is_file() {
                continue;
            }
            let rel = if base.is_empty() { name.clone() } else { format!("{base}\\{name}") };
            let dst = tmp.join("user").join(&rel);
            if std::fs::create_dir_all(dst.parent().unwrap()).is_ok() && std::fs::copy(e.path(), &dst).is_ok() {
                user_files.push(rel);
            }
        }
    }
    for rel in [r"utils\game_filter.enabled", r"utils\check_updates.enabled"] {
        let cand = root.join(rel);
        if cand.is_file() {
            let dst = tmp.join("user").join(rel);
            if std::fs::create_dir_all(dst.parent().unwrap()).is_ok() && std::fs::copy(&cand, &dst).is_ok() {
                user_files.push(rel.to_string());
            }
        }
    }
    // 2b. pre-configs целиком (свои подпапки/кастомы)
    let pre_src = root.join("pre-configs");
    if pre_src.is_dir() && copy_dir(&pre_src, &tmp.join("user").join("pre-configs")).is_err() {
        crate::log_action("Бэкап pre-configs не удался", "error");
    } else if pre_src.is_dir() {
        user_files.push("pre-configs".into());
    }
    // 3. свежий релиз
    emit(&app, "status", "узнаю свежий релиз…");
    let (tag, zurl) = match gh_latest().await {
        Ok(t) => t,
        Err(e) => {
            let _ = std::fs::remove_dir_all(&tmp);
            return fail(format!("Не удалось узнать релиз: {e}"));
        }
    };
    crate::log_action(&format!("Скачиваю свежий релиз ({tag})…"), "info");
    // 4. скачивание с прогрессом
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(300))
        .user_agent("ZapretManager-v2")
        .build()
        .unwrap();
    let mut resp = match client.get(&zurl).send().await {
        Ok(r) => r,
        Err(e) => {
            let _ = std::fs::remove_dir_all(&tmp);
            return fail(format!("Не скачалось: {e}"));
        }
    };
    let total = resp.content_length().unwrap_or(0);
    let zpath = tmp.join("fresh.zip");
    {
        let mut file = match std::fs::File::create(&zpath) {
            Ok(f) => f,
            Err(e) => {
                let _ = std::fs::remove_dir_all(&tmp);
                return fail(format!("Не создать временный файл: {e}"));
            }
        };
        use std::io::Write;
        let mut done: u64 = 0;
        let mut last_pct = 0u64;
        loop {
            // chunk() — без futures-util: reqwest отдаёт следующий кусок
            match resp.chunk().await {
                Ok(Some(chunk)) => {
                    if file.write_all(&chunk).is_err() {
                        let _ = std::fs::remove_dir_all(&tmp);
                        return fail("Не записать архив".into());
                    }
                    done += chunk.len() as u64;
                    if total > 0 {
                        let pct = done.saturating_mul(100).checked_div(total).unwrap_or(100);
                        if pct >= last_pct + 5 {
                            last_pct = pct;
                            emit(&app, "progress", &format!("{pct}% ({} МБ)", done / 1024 / 1024));
                        }
                    } else if done / 1024 / 1024 != last_pct {
                        last_pct = done / 1024 / 1024;
                        emit(&app, "progress", &format!("{last_pct} МБ"));
                    }
                }
                Ok(None) => break,
                Err(e) => {
                    let _ = std::fs::remove_dir_all(&tmp);
                    return fail(format!("Обрыв скачивания: {e}"));
                }
            }
        }
    }
    // 5. распаковать, найти корень
    emit(&app, "status", "распаковка…");
    let fresh = tmp.join("fresh");
    {
        let f = match std::fs::File::open(&zpath) {
            Ok(f) => f,
            Err(e) => {
                let _ = std::fs::remove_dir_all(&tmp);
                return fail(format!("Не открыть архив: {e}"));
            }
        };
        let mut z = match zip::ZipArchive::new(f) {
            Ok(z) => z,
            Err(e) => {
                let _ = std::fs::remove_dir_all(&tmp);
                return fail(format!("Битый архив: {e}"));
            }
        };
        if z.extract(&fresh).is_err() {
            let _ = std::fs::remove_dir_all(&tmp);
            return fail("Не распаковать архив".into());
        }
    }
    let items: Vec<String> = std::fs::read_dir(&fresh)
        .map(|rd| {
            rd.flatten()
                .filter(|e| e.file_name().to_str() != Some("__MACOSX"))
                .filter_map(|e| e.file_name().to_str().map(|n| n.to_string()))
                .collect()
        })
        .unwrap_or_default();
    let new_root = if items.len() == 1 && fresh.join(&items[0]).is_dir() {
        fresh.join(&items[0])
    } else {
        fresh.clone()
    };
    if !new_root.join("service.bat").exists() {
        let _ = std::fs::remove_dir_all(&tmp);
        return fail("в архиве нет service.bat — странный релиз".into());
    }
    // 6. заменить папку (старая -> .prev, откат при ошибке)
    emit(&app, "status", "замена папки…");
    let prev = PathBuf::from(format!("{}.prev", root.to_string_lossy().trim_end_matches(['\\', '/'])));
    if prev.exists() {
        let _ = std::fs::remove_dir_all(&prev);
    }
    if std::fs::rename(&root, &prev).is_err() {
        let _ = std::fs::remove_dir_all(&tmp);
        return fail("не переименовать старую папку (занята процессом?)".into());
    }
    let moved_ok = std::fs::rename(&new_root, &root).is_ok();
    if !moved_ok {
        let _ = std::fs::remove_dir_all(&root);
        let _ = std::fs::rename(&prev, &root);
        let _ = std::fs::remove_dir_all(&tmp);
        return fail("не перенести свежую папку — откачено назад".into());
    }
    // 7. вернуть пользовательские файлы
    for relp in &user_files {
        if relp == "pre-configs" {
            continue;
        }
        let src = tmp.join("user").join(relp);
        if src.is_file() {
            let dst = root.join(relp);
            let _ = std::fs::create_dir_all(dst.parent().unwrap());
            let _ = std::fs::copy(&src, &dst);
        }
    }
    // 7b. кастомы из pre-configs (только чего нет в свежем релизе)
    {
        let bak = tmp.join("user").join("pre-configs");
        let new_pre = root.join("pre-configs");
        if bak.is_dir() {
            let mut fresh_names = std::collections::HashSet::new();
            // имена свежих файлов на всех уровнях (свои кастомы не трогаем)
            fn names(d: &Path, into: &mut std::collections::HashSet<String>) {
                if let Ok(rd) = std::fs::read_dir(d) {
                    for e in rd.flatten() {
                        if let Some(n) = e.file_name().to_str() {
                            into.insert(n.to_string());
                        }
                        if e.path().is_dir() {
                            names(&e.path(), into);
                        }
                    }
                }
            }
            names(&new_pre, &mut fresh_names);
            fn restore(bak: &Path, rel: &Path, dst_root: &Path, fresh: &std::collections::HashSet<String>) {
                if let Ok(rd) = std::fs::read_dir(bak) {
                    for e in rd.flatten() {
                        let name = match e.file_name().to_str() {
                            Some(n) => n.to_string(),
                            None => continue,
                        };
                        if e.path().is_dir() {
                            restore(&e.path(), &rel.join(&name), dst_root, fresh);
                            continue;
                        }
                        if fresh.contains(&name) {
                            continue;
                        }
                        let dst = dst_root.join(rel).join(&name);
                        let _ = std::fs::create_dir_all(dst.parent().unwrap());
                        let _ = std::fs::copy(e.path(), &dst);
                    }
                }
            }
            restore(&bak, Path::new(""), &new_pre, &fresh_names);
        }
    }
    // 8. раскладка конфигов
    let (_moved, omsg) = organize_configs(&root);
    crate::log_action(&format!("Раскладка конфигов после переустановки: {omsg}"), "info");
    // 9. diff списков (prev ещё жив — построчный)
    let mut diff_text = String::new();
    {
        let new_snap = zapret::snapshot_lists(root.to_str().unwrap_or(""));
        let d = zapret::diff_snaps(&old_snap, &new_snap);
        // сохранить снимок
        let sp = config::data_dir().join("lists_snapshot.json");
        let _ = std::fs::create_dir_all(config::data_dir());
        let _ = std::fs::write(&sp, serde_json::to_string_pretty(&new_snap).unwrap_or_default());
        if !d.added.is_empty() || !d.removed.is_empty() || !d.changed.is_empty() {
            let mut parts = Vec::new();
            if !d.added.is_empty() {
                parts.push(format!("+{}: {}", d.added.len(), d.added.iter().take(5).cloned().collect::<Vec<_>>().join(", ")));
            }
            if !d.removed.is_empty() {
                parts.push(format!("−{}: {}", d.removed.len(), d.removed.iter().take(5).cloned().collect::<Vec<_>>().join(", ")));
            }
            if !d.changed.is_empty() {
                parts.push(format!("~{}: {}", d.changed.len(), d.changed.iter().take(8).cloned().collect::<Vec<_>>().join(", ")));
            }
            diff_text = parts.join("; ");
            crate::log_action(&format!("Diff списков после переустановки: {diff_text}"), "lists");
            // построчный diff изменённых — в файл
            let mut dl = vec![
                format!("# Diff списков ({tag})"),
                format!("Добавлены: {}", if d.added.is_empty() { "—".into() } else { d.added.join(", ") }),
                format!("Удалены: {}", if d.removed.is_empty() { "—".into() } else { d.removed.join(", ") }),
                String::new(),
            ];
            for fn_ in d.changed.iter().take(10) {
                let lo = std::fs::read_to_string(prev.join("lists").join(fn_)).unwrap_or_default();
                let ln = std::fs::read_to_string(root.join("lists").join(fn_)).unwrap_or_default();
                let lo_l: Vec<&str> = lo.lines().collect();
                let ln_l: Vec<&str> = ln.lines().collect();
                dl.push(format!("## {fn_} ({} → {} строк)", lo_l.len(), ln_l.len()));
                dl.push("```diff".into());
                dl.extend(unified_diff(&lo_l, &ln_l, 400));
                dl.push("```".into());
            }
            let safe_tag: String = tag.chars().map(|c| if c.is_alphanumeric() || c == '.' || c == '-' { c } else { '_' }).take(40).collect();
            let dp = config::data_dir().join(format!("lists_diff_{safe_tag}.md"));
            let _ = std::fs::write(&dp, dl.join("\n") + "\n");
        }
    }
    let _ = std::fs::remove_dir_all(&prev);
    let _ = std::fs::remove_dir_all(&tmp);
    crate::log_action(&format!("Zapret переустановлен ({tag}), пользовательских файлов: {}", user_files.len()), "info");
    ReinstallDone {
        msg: format!("Версия {tag}. Выберите конфиг и примените."),
        tag,
        diff: diff_text,
        ok: true,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn diff_basic() {
        let old = ["a", "b", "c"];
        let new = ["a", "x", "c", "d"];
        let d = unified_diff(&old, &new, 400);
        assert!(d.iter().any(|l| l == "-b"), "нет -b: {d:?}");
        assert!(d.iter().any(|l| l == "+x"), "нет +x: {d:?}");
        assert!(d.iter().any(|l| l == "+d"), "нет +d: {d:?}");
        assert!(!d.iter().any(|l| l == "+a" || l == "-a"), "a не менялась: {d:?}");
    }

    #[test]
    fn organize_moves_root_bats() {
        let tmp = std::env::temp_dir().join("zm_organize_test");
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        std::fs::write(tmp.join("general.bat"), "a").unwrap();
        std::fs::write(tmp.join("service.bat"), "s").unwrap();
        let (moved, _) = organize_configs(&tmp);
        assert_eq!(moved, 1);
        assert!(tmp.join("pre-configs").join("general.bat").exists());
        assert!(tmp.join("service.bat").exists(), "service трогать нельзя");
        // дубль с тем же содержимым — удаляется
        std::fs::write(tmp.join("general.bat"), "a").unwrap();
        let (moved2, _) = organize_configs(&tmp);
        assert_eq!(moved2, 0);
        assert!(!tmp.join("general.bat").exists());
        // одноимённый с другим содержимым — суффикс
        std::fs::write(tmp.join("general.bat"), "b").unwrap();
        let (moved3, _) = organize_configs(&tmp);
        assert_eq!(moved3, 1);
        assert!(tmp.join("pre-configs").join("general (2).bat").exists());
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
