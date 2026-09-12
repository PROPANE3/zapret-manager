#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zapret Manager — лёгкая панель управления zapret-discord-youtube.
Только стандартная библиотека Python. Минимальное потребление ресурсов.
Тёмный современный UI на tkinter.
"""
import ctypes
import concurrent.futures as cf
import datetime
import glob
import json
import os
import queue
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

try:
    import tkinter as tk
    from tkinter import ttk, filedialog
    import tkinter.font as tkfont
except ImportError:
    print("tkinter не найден")
    sys.exit(1)

try:
    import winreg
except ImportError:
    winreg = None

APP_VERSION = "1.12.0"
APP_NAME = "Zapret Manager"
APP_REPO = "PROPANE3/zapret-manager"
APP_ID = "Flowseal.ZapretManager"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CHECKS_DIR = os.path.join(DATA_DIR, "checks")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
ACTIONS_PATH = os.path.join(DATA_DIR, "actions.log")

os.makedirs(CHECKS_DIR, exist_ok=True)

# ---------- палитра: алый / красный / чёрный ----------
BG = "#0A0A0C"          # почти чёрный фон
TITLEBAR_BG = "#120608"  # чёрный с красным оттенком (шапка окна)
SIDEBAR = "#100708"      # сайдбар — чёрно-алый
CARD = "#141014"         # карточки — тёмные с тёплым подтоном
CARD2 = "#1E1214"        # вложенные панели
BORDER = "#3A1518"       # бордо-рамки
TEXT = "#F3E9E9"         # тёплый белый
MUTED = "#9C8B8E"        # приглушённый розово-серый
ACCENT = "#C1121F"       # алый
ACCENT_HOVER = "#E5383B"  # яркий красный для hover
ACCENT_DEEP = "#6E0A11"  # глубокий тёмно-алый для градиента
ACCENT2 = "#FF6B6B"      # светло-алый для уведомлений
GREEN = "#35D07F"
YELLOW = "#F5A524"
RED = "#FF2E2E"
FONT = "Trebuchet MS"
MONO = "Consolas"

# Быстрый режим: только ключевые домены (Discord + YouTube + Google).
# Даёт ~3x ускорение: 7 целей вместо 16.
QUICK_NAMES = ("DiscordMain", "DiscordGateway", "YouTubeWeb", "YouTubeShort",
               "YouTubeVideoRedirect", "GoogleMain", "CloudflareDNS1111")

MODE_LABELS = {"quick": "Быстрый (Discord+YouTube)",
               "full": "Полный (все цели)",
               "ultra": "Ультра (турнир: отсев + топ-6)"}


def mode_label(mode):
    return MODE_LABELS.get(mode, MODE_LABELS["quick"])


def mode_key(label):
    for k, v in MODE_LABELS.items():
        if v in (label or "") or (label or "") in v:
            return k
    if "Ультра" in (label or ""):
        return "ultra"
    if "Полный" in (label or ""):
        return "full"
    return "quick"

# ---------- темы оформления (имя -> палитра) ----------
THEMES = {
    "Алый": {
        "BG": "#0A0A0C", "TITLEBAR_BG": "#120608", "SIDEBAR": "#100708",
        "CARD": "#141014", "CARD2": "#1E1214", "BORDER": "#3A1518",
        "TEXT": "#F3E9E9", "MUTED": "#9C8B8E",
        "ACCENT": "#C1121F", "ACCENT_HOVER": "#E5383B",
        "ACCENT_DEEP": "#6E0A11", "ACCENT2": "#FF6B6B",
    },
    "Фиолет": {
        "BG": "#0B0E14", "TITLEBAR_BG": "#12101D", "SIDEBAR": "#10141D",
        "CARD": "#151B29", "CARD2": "#1A2133", "BORDER": "#2A3350",
        "TEXT": "#E8ECF4", "MUTED": "#8B93A9",
        "ACCENT": "#7C3AED", "ACCENT_HOVER": "#8B5CF6",
        "ACCENT_DEEP": "#2A1B4E", "ACCENT2": "#22D3EE",
    },
    "Изумруд": {
        "BG": "#090C0B", "TITLEBAR_BG": "#071009", "SIDEBAR": "#0A0F0C",
        "CARD": "#101613", "CARD2": "#15201A", "BORDER": "#1E3A2B",
        "TEXT": "#E9F3EC", "MUTED": "#8B9C91",
        "ACCENT": "#10B981", "ACCENT_HOVER": "#34D399",
        "ACCENT_DEEP": "#064E3B", "ACCENT2": "#6EE7B7",
    },
    "Океан": {
        "BG": "#080B10", "TITLEBAR_BG": "#06121A", "SIDEBAR": "#08101A",
        "CARD": "#0E1622", "CARD2": "#12202F", "BORDER": "#1B2C44",
        "TEXT": "#E9F0F7", "MUTED": "#8B9AAD",
        "ACCENT": "#0284C7", "ACCENT_HOVER": "#38BDF8",
        "ACCENT_DEEP": "#0C2A44", "ACCENT2": "#7DD3FC",
    },
    "Закат": {
        "BG": "#0C0A08", "TITLEBAR_BG": "#160D06", "SIDEBAR": "#120C07",
        "CARD": "#171310", "CARD2": "#211913", "BORDER": "#3D2615",
        "TEXT": "#F5ECE3", "MUTED": "#9C8F82",
        "ACCENT": "#EA580C", "ACCENT_HOVER": "#FB923C",
        "ACCENT_DEEP": "#431407", "ACCENT2": "#FDBA74",
    },
}


def apply_theme(name):
    pal = THEMES.get(name, THEMES["Алый"])
    for k, v in pal.items():
        globals()[k] = v


THEME_KEYS = ("BG", "TITLEBAR_BG", "SIDEBAR", "CARD", "CARD2", "BORDER",
              "TEXT", "MUTED", "ACCENT", "ACCENT_HOVER", "ACCENT_DEEP", "ACCENT2")

# Живой реестр кастомных виджетов (RButton, NiceScroll, DropMenu, StatusBadge):
# у каждого есть .apply_theme(). WeakSet — погибшие сами выпадают.
import weakref as _weakref
THEMED = _weakref.WeakSet()
THEME_REMAP = {}


def track_themed(widget):
    try:
        THEMED.add(widget)
    except Exception:
        pass
    return widget


def remap_color(hexcolor):
    try:
        return THEME_REMAP.get(str(hexcolor).lower(), hexcolor)
    except Exception:
        return hexcolor


# Красивые читаемые шрифты (фильтруются по наличию в системе)
FONT_WHITELIST = ["Calibri", "Segoe UI", "Verdana", "Tahoma", "Trebuchet MS",
                  "Corbel", "Candara", "Georgia", "Arial"]
MONO_WHITELIST = ["Cascadia Mono", "Cascadia Code", "Consolas", "Lucida Console"]
UI_SCALES = {"Компактный": 0.92, "Обычный": 1.0, "Крупный": 1.12, "Очень крупный": 1.25}

DEFAULT_CONFIG = {
    "zapret_root": r"D:\Desktop\zapret-discord-youtube-main",
    "active_config": "",
    "best_scores": {},
    "app_autostart": False,
    "monitor_enabled": True,
    "monitor_interval_min": 3,
    "ping_threshold_ms": 5000,
    "check_timeout_s": 4,
    "targets_override": "",
    "check_mode": "quick",      # quick = Discord+YouTube, full = все цели
    "check_repeat": 2,          # повторов HTTP-проверки (лучший результат идёт в зачёт)
    "check_workers": 8,         # параллельных потоков на цели
    "ui_font": "Trebuchet MS",
    "ui_scale": "Крупный",
    "mono_font": "Consolas",
    "theme": "Алый",
}


def _migrate_appearance(cfg):
    """Одноразовая миграция на новый вид v1.2 (шрифт крупнее и красивее)."""
    if not cfg.get("appearance_v2"):
        cfg["ui_font"] = "Trebuchet MS"
        cfg["ui_scale"] = "Крупный"
        cfg["appearance_v2"] = True
        return True
    return False

# ================= ресурсы =================
# Встроенная иконка (чёрный квадрат, белая Z) — запасной вариант, если нет
# assets/icon.png (например, запуск из неразвёрнутого архива).
_ICON_PNG_B64 = (
    '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'
    'AABJRU5ErkJggg=='
)

# ================= helpers =================

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg.update(data)
    except Exception:
        pass
    # автоопределение папки zapret если дефолт не существует
    if not os.path.isdir(cfg.get("zapret_root", "")):
        for cand in [r"D:\Desktop\zapret-discord-youtube-main",
                     os.path.join(os.path.expanduser("~"), "Desktop", "zapret-discord-youtube-main"),
                     r"C:\zapret", r"D:\zapret"]:
            if os.path.isdir(cand):
                cfg["zapret_root"] = cand
                break
    if _migrate_appearance(cfg):
        save_config(cfg)
    return cfg


def save_config(cfg):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def log_action(text, kind="info"):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(ACTIONS_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{kind}] {text}\n")
    except Exception:
        pass


def read_actions(limit=500):
    if not os.path.exists(ACTIONS_PATH):
        return []
    try:
        with open(ACTIONS_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return lines[-limit:]
    except Exception:
        return []


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def run_cmd(cmd, timeout=15, shell=False):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           shell=shell, errors="ignore",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:
        return 1, str(e)


def elevated_cmd(cmdline):
    """Запустить команду с запросом UAC."""
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", f"/c {cmdline}", None, 1)
        return True
    except Exception:
        return False


def set_process_priority(high=True):
    """Турбо: повысить приоритет процесса на время ручной проверки."""
    try:
        if os.name != "nt":
            return False
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.SetPriorityClass.restype = wintypes.BOOL
        # HIGH_PRIORITY_CLASS=0x80 / NORMAL_PRIORITY_CLASS=0x20
        return bool(k.SetPriorityClass(k.GetCurrentProcess(), 0x80 if high else 0x20))
    except Exception:
        return False


def thread_bg_mode(on=True):
    """Эко: перевести текущий поток в фоновый режим (меньше CPU+I/O)."""
    try:
        if os.name != "nt":
            return False
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.GetCurrentThread.restype = wintypes.HANDLE
        k.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
        k.SetThreadPriority.restype = wintypes.BOOL
        # THREAD_MODE_BACKGROUND_BEGIN=0x10000 / END=0x20000
        return bool(k.SetThreadPriority(k.GetCurrentThread(), 0x10000 if on else 0x20000))
    except Exception:
        return False


# ================= zapret core =================

def list_configs(zapret_root):
    if not zapret_root or not os.path.isdir(zapret_root):
        return []
    files = glob.glob(os.path.join(zapret_root, "*.bat"))
    out = []
    for fp in files:
        name = os.path.basename(fp)
        if name.lower().startswith("service"):
            continue
        out.append(name)
    # естественная сортировка: general, general (ALT), ... ALT2..ALT13
    def key(n):
        m = re.search(r"ALT\s*(\d+)", n)
        if n.lower() == "general.bat":
            return (0, 0, n)
        if m:
            return (1, int(m.group(1)), n)
        if "ALT" in n:
            return (1, 1, n)
        return (2, 0, n)
    return sorted(out, key=key)


def parse_targets(zapret_root, override_text=""):
    targets = []  # list of (name, url_or_ping)
    src = ""
    if override_text and override_text.strip():
        src = override_text
    else:
        p = os.path.join(zapret_root, "utils", "targets.txt") if zapret_root else ""
        if p and os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    src = f.read()
            except Exception:
                src = ""
    for line in src.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^(\w+)\s*=\s*"(.+)"\s*$', line)
        if m:
            targets.append((m.group(1), m.group(2)))
    if not targets:
        targets = [
            ("DiscordMain", "https://discord.com"),
            ("YouTubeWeb", "https://www.youtube.com"),
            ("GoogleMain", "https://www.google.com"),
            ("CloudflareWeb", "https://www.cloudflare.com"),
            ("CloudflareDNS1111", "PING:1.1.1.1"),
            ("GoogleDNS8888", "PING:8.8.8.8"),
        ]
    return targets


def split_host(target_value):
    if target_value.startswith("PING:"):
        return target_value[5:].strip(), True
    h = re.sub(r"^https?://", "", target_value).split("/")[0].strip()
    return h, False


def ping_host(host, timeout_ms=2000):
    """Возвращает ms или None при таймауте. Лёгкий ping через системную утилиту."""
    try:
        # -n 1 : один пакет, -w : таймаут мс
        rc, out = run_cmd(["ping", "-n", "1", "-w", str(timeout_ms), host], timeout=8)
        m = re.search(r"time[=<]\s*(\d+)\s*ms", out, re.IGNORECASE)
        if m:
            return int(m.group(1))
        if "TTL=" in out.upper() or "ttl=" in out.lower():
            return 1
        return None
    except Exception:
        return None


def http_check(url, timeout=5):
    """True/False/None(unsupported). Используем curl если есть, иначе urllib."""
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if curl:
        try:
            rc, out = run_cmd([curl, "-I", "-s", "-m", str(timeout),
                               "--connect-timeout", "3",
                               "-o", "NUL" if os.name == "nt" else "/dev/null",
                               "-w", "%{http_code}", url], timeout=timeout + 4)
            code = out.strip()[-3:] if out.strip() else ""
            if code.isdigit():
                c = int(code)
                if 200 <= c < 400:
                    return True
                if c in (403, 405):
                    return True  # сервер ответил — DPI не режет
                return False
            low = out.lower()
            if "could not resolve" in low or "certificate" in low or "ssl" in low:
                return False
            return False if rc != 0 else True
        except Exception:
            pass
    # fallback urllib
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return 200 <= r.status < 400
    except Exception:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return 200 <= r.status < 400
        except Exception:
            return False


def quick_filter(targets):
    """Быстрый режим: только ключевые домены Discord/YouTube/Google."""
    sub = [(n, v) for n, v in targets if n in QUICK_NAMES]
    if len(sub) >= 3:
        return sub
    # fallback если targets.txt кастомный: первые HTTP + первые PING
    https = [(n, v) for n, v in targets if not v.startswith("PING:")][:4]
    pings = [(n, v) for n, v in targets if v.startswith("PING:")][:2]
    return https + pings


def probe_target(name, val, timeout, ping_thr, ping_cap_ms, repeat):
    """Проверка одной цели: 1 ping + до `repeat` попыток HTTP (зачёт при 1 успехе)."""
    host, ping_only = split_host(val)
    pm = ping_host(host, timeout_ms=ping_cap_ms)
    ping_ok = pm is not None and pm < ping_thr
    http_ok = None
    if not ping_only:
        ok = False
        for _ in range(max(1, int(repeat))):
            try:
                if http_check(val, timeout=timeout):
                    ok = True
                    break  # успех с первой попытки — дальше не ждём
            except Exception:
                pass
        http_ok = ok
    return {"name": name, "host": host, "ping_ms": pm,
            "ping_ok": ping_ok, "http_ok": http_ok, "ping_only": ping_only}


ULTRA_FINALISTS = 6
ULTRA_SCREEN_TARGETS = ("YouTubeWeb", "DiscordMain")


def network_alive():
    """Есть ли вообще сеть: быстрый ping до DNS. False = дальше проверять бессмысленно."""
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            if ping_host(host, timeout_ms=800) is not None:
                return True
        except Exception:
            pass
    return False


def wait_winws_ready(timeout_s=6.0, fast=False):
    """Ждём появления winws polling'ом вместо фиксированного sleep."""
    poll, settle = (0.25, 0.3) if fast else (0.35, 0.4)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if winws_running():
            time.sleep(settle)
            return True
        time.sleep(poll)
    return winws_running()


LAST_RUN_LOG = os.path.join(CHECKS_DIR, "_last_run.log")
LAST_RUN_LABEL = "▶ Последний запуск"

# Шкала оценок пинга (мс): границы сверху вниз
GRADE_FAIL = ("Не работает", RED, 0)
GRADE_POOR = ("Плохой", "#FB923C", 1)
GRADE_MID = ("Средний", YELLOW, 2)
GRADE_GOOD = ("Хороший", GREEN, 3)
GRADE_GREAT = ("Отличный", "#4ADE80", 4)


def ping_grade(pm):
    """Оценка одного пинга: (текст, цвет, ранг). None = пакет не получен."""
    if pm is None:
        return GRADE_FAIL
    if pm <= 100:
        return GRADE_GREAT
    if pm <= 300:
        return GRADE_GOOD
    if pm <= 1000:
        return GRADE_MID
    return GRADE_POOR  # 2000 и выше (но пакет есть)


def fmt_ping(pm):
    return "—" if pm is None else f"{pm} мс"


DISCORD_NAMES = ("DiscordMain", "DiscordGateway", "DiscordCDN", "DiscordUpdates")
YOUTUBE_NAMES = ("YouTubeWeb", "YouTubeShort", "YouTubeImage", "YouTubeVideoRedirect")


def service_pings(rows):
    """Лучшие пинги Discord и YouTube среди целей конфига (None = недоступен)."""
    by_name = {r["name"]: r for r in (rows or [])}

    def pick(names):
        have = [by_name[n]["ping_ms"] for n in names if n in by_name]
        if not have:
            return None
        ok = [v for v in have if v is not None]
        return min(ok) if ok else None

    return pick(DISCORD_NAMES), pick(YOUTUBE_NAMES)


def config_grade(discord_ms, youtube_ms):
    """Итоговая пометка конфига — по худшему из двух сервисов."""
    g1, g2 = ping_grade(discord_ms), ping_grade(youtube_ms)
    return g1 if g1[2] <= g2[2] else g2


def run_log_reset(header=""):
    try:
        with open(LAST_RUN_LOG, "w", encoding="utf-8") as f:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"=== Проверка {ts} ===\n")
            if header:
                f.write(header + "\n")
    except Exception:
        pass


def run_log_write(line):
    try:
        with open(LAST_RUN_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_game_filter(zapret_root):
    tcp, udp = "12", "12"
    try:
        p = os.path.join(zapret_root, "utils", "game_filter.enabled")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                mode = f.read().strip().lower()
            if mode == "all":
                tcp = udp = "1024-65535"
            elif mode == "tcp":
                tcp = "1024-65535"
            elif mode == "udp":
                udp = "1024-65535"
    except Exception:
        pass
    return tcp, udp


def build_service_args(zapret_root, bat_name):
    """Собирает аргументы winws.exe из bat — упрощённый аналог service.bat."""
    fp = os.path.join(zapret_root, bat_name)
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
    except Exception as e:
        return None, f"Не могу прочитать {bat_name}: {e}"
    # склеить строки с ^
    raw = raw.replace("^\r\n", " ").replace("^\n", " ")
    lines = raw.splitlines()
    # найти всё после winws.exe
    args_parts = []
    capturing = False
    for line in lines:
        if "winws.exe" in line.lower():
            capturing = True
            idx = line.lower().find("winws.exe") + len("winws.exe")
            tail = line[idx:].strip()
            # убрать кавычку начала
            if tail.startswith('"'):
                tail = tail[1:]
            args_parts.append(tail)
        elif capturing:
            s = line.strip()
            if not s or s.startswith("::") or s.lower().startswith("@echo") or s.lower().startswith("cd ") \
               or s.lower().startswith("call ") or s.lower().startswith("set ") or s.lower().startswith("echo"):
                # bat мог закончиться; но аргументы обычно в одном start-блоке
                if "winws" in s.lower() or s.startswith("--") or s.startswith('"--'):
                    args_parts.append(s)
                continue
            args_parts.append(s)
    args = " ".join(args_parts).replace("^", " ").strip()
    args = re.sub(r"\s+", " ", args)
    if not args or "--" not in args:
        return None, "Не найдены аргументы winws в bat-файле"
    BIN = os.path.join(zapret_root, "bin") + os.sep
    LISTS = os.path.join(zapret_root, "lists") + os.sep
    tcp, udp = get_game_filter(zapret_root)
    args = args.replace("%~dp0bin\\", BIN).replace("%~dp0lists\\", LISTS)
    args = args.replace("%BIN%", BIN).replace("%LISTS%", LISTS)
    args = args.replace("%GameFilterTCP%", tcp).replace("%GameFilterUDP%", udp).replace("%GameFilter%", tcp)
    # %~dp0 общий
    args = args.replace("%~dp0", zapret_root + os.sep)
    # убрать остатки start-префиксов
    args = re.sub(r'^["\s]*', "", args)
    return args, ""


def service_status():
    st = {"zapret": "NOT_INSTALLED", "windivert": "NOT_INSTALLED",
          "winws": False, "strategy": ""}
    rc, out = run_cmd(["sc", "query", "zapret"], timeout=8)
    lo = out.lower()
    if "running" in lo:
        st["zapret"] = "RUNNING"
    elif "stopped" in lo:
        st["zapret"] = "STOPPED"
    elif "failed" in lo or "1060" in lo or "does not exist" in lo or "не существует" in lo:
        st["zapret"] = "NOT_INSTALLED"
    elif rc == 0:
        st["zapret"] = "UNKNOWN"
    rc2, out2 = run_cmd(["sc", "query", "WinDivert"], timeout=8)
    if "running" in out2.lower():
        st["windivert"] = "RUNNING"
    elif "stopped" in out2.lower():
        st["windivert"] = "STOPPED"
    rc3, out3 = run_cmd(["tasklist", "/FI", "IMAGENAME eq winws.exe"], timeout=8)
    if "winws.exe" in out3.lower():
        st["winws"] = True
    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"System\CurrentControlSet\Services\zapret") as k:
                try:
                    v, _ = winreg.QueryValueEx(k, "zapret-discord-youtube")
                    st["strategy"] = v
                except FileNotFoundError:
                    pass
        except Exception:
            pass
    return st


def install_service(zapret_root, bat_name):
    args, err = build_service_args(zapret_root, bat_name)
    if not args:
        return False, err
    bin_path = os.path.join(zapret_root, "bin", "winws.exe")
    if not os.path.exists(bin_path):
        return False, f"winws.exe не найден: {bin_path}"
    # экранировать кавычки для sc
    full = f'"{bin_path}" {args}'
    cmds = (
        f'sc stop zapret >nul 2>&1 & sc delete zapret >nul 2>&1 & '
        f'sc create zapret binPath= "{full}" DisplayName= "zapret" start= auto & '
        f'sc description zapret "Zapret DPI bypass software" & '
        f'sc start zapret & '
        f'reg add "HKLM\\System\\CurrentControlSet\\Services\\zapret" /v zapret-discord-youtube /t REG_SZ /d "{os.path.splitext(bat_name)[0]}" /f'
    )
    if not is_admin():
        ok = elevated_cmd(cmds)
        if ok:
            return True, "Запрос на установку отправлен с правами администратора. Проверьте статус через 5 секунд."
        return False, "Нужны права администратора"
    rc, out = run_cmd(cmds, timeout=30, shell=True)
    time.sleep(2)
    st = service_status()
    if st["zapret"] == "RUNNING":
        return True, "Служба zapret установлена и запущена"
    return False, f"Не удалось запустить службу. Вывод: {out[:600]}"


def remove_service():
    cmds = ('net stop zapret >nul 2>&1 & sc delete zapret >nul 2>&1 & '
            'taskkill /IM winws.exe /F >nul 2>&1 & '
            'net stop WinDivert >nul 2>&1 & sc delete WinDivert >nul 2>&1 & '
            'net stop WinDivert14 >nul 2>&1 & sc delete WinDivert14 >nul 2>&1')
    if not is_admin():
        ok = elevated_cmd(cmds)
        if ok:
            return True, "Запрос на удаление отправлен (UAC)."
        return False, "Нужны права администратора"
    run_cmd(cmds, timeout=30, shell=True)
    return True, "Службы zapret / WinDivert удалены, winws остановлен"


def stop_winws():
    run_cmd(["taskkill", "/IM", "winws.exe", "/F"], timeout=8)


def _split_win_args(args):
    """Делит строку аргументов с учётом кавычек (пути с пробелами)."""
    import shlex
    try:
        return shlex.split(args, posix=False)
    except Exception:
        return args.split()


def start_winws_hidden(zapret_root, bat_name):
    """Запуск конфига БЕЗ окон: winws.exe напрямую, без консоли и кнопки в таскбаре.

    Раньше запускался .bat через cmd — оставалось свёрнутое окно winws
    (консоль + кнопка «zapret: ...» в таскбаре). Теперь аргументы берутся
    из bat (тот же парсер, что для службы) и winws стартует скрытым процессом.
    Возвращает True, если процесс запущен.
    """
    try:
        args, err = build_service_args(zapret_root, bat_name)
        if not args:
            return start_bat_minimized(zapret_root, bat_name)
        exe = os.path.join(zapret_root, "bin", "winws.exe")
        if not os.path.exists(exe):
            return False
        cmd = [exe] + [a.strip('"') for a in _split_win_args(args)]
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(cmd, cwd=os.path.join(zapret_root, "bin"),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, startupinfo=si,
                         creationflags=flags)
        return True
    except Exception:
        try:
            return start_bat_minimized(zapret_root, bat_name)
        except Exception:
            return False


def start_bat_minimized(zapret_root, bat_name):
    fp = os.path.join(zapret_root, bat_name)
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 6  # minimized
        subprocess.Popen(["cmd.exe", "/c", fp], cwd=zapret_root,
                         startupinfo=si,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False


def winws_running():
    _, out = run_cmd(["tasklist", "/FI", "IMAGENAME eq winws.exe"], timeout=8)
    return "winws.exe" in out.lower()


# ---- системная шторка в цветах темы (Windows 11: DWM caption/border) ----
# Шторка остаётся родной (кнопки, снап, таскбар без глюков), но красится
# в TITLEBAR_BG/TEXT и рамка гасится в цвет фона. На Windows 10 — тихо no-op.


def toplevel_hwnd(root):
    """Внешнее окно TkTopLevel (у winfo_id — внутренний TkChild без декораций)."""
    try:
        if os.name != "nt":
            return None
        user32 = ctypes.windll.user32
        inner = root.winfo_id()
        outer = user32.GetParent(inner)
        if outer and user32.IsWindow(outer):
            return outer
        if user32.IsWindow(inner):
            return inner
    except Exception:
        pass
    return None


def win_rect(root):
    """Истинный прямоугольник окна (l, t, r, b).

    winfo_x/y при снятом WS_CAPTION врут (кэш Tk), поэтому геометрию
    для перетаскивания и позиционирования берём из WinAPI.
    """
    try:
        from ctypes import wintypes
        u = ctypes.windll.user32
        hwnd = toplevel_hwnd(root)
        if not hwnd:
            return None
        u.GetWindowRect.argtypes = [wintypes.HWND,
                                    ctypes.POINTER(wintypes.RECT)]
        rc = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(rc))
        return (rc.left, rc.top, rc.right, rc.bottom)
    except Exception:
        return None


def win_move(root, x, y):
    try:
        u = ctypes.windll.user32
        hwnd = toplevel_hwnd(root)
        if not hwnd:
            return False
        return bool(u.SetWindowPos(hwnd, 0, int(x), int(y), 0, 0,
                                   0x0001 | 0x0004 | 0x0020))
    except Exception:
        return False


_CHROME_STATE = {"cb": None, "old": None}


def setup_borderless(root, titlebar_h=44, btn_reserve_px=150, border_px=8):
    """Прячем системную шапку (для Win10, где DWM-тинт невозможен).

    Убираем WS_CAPTION у ВНЕШНЕГО окна + отдаём WM_NCCALCSIZE 0 (неклиентской
    области нет) + нативное перетаскивание/ресайз через WM_NCHITTEST.
    Таскбар, кнопки, снап, тень сохраняются. Возвращает True при успехе.
    """
    if os.name != "nt":
        return False
    try:
        from ctypes import wintypes
        LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
        user32 = ctypes.windll.user32
        hwnd = toplevel_hwnd(root)
        if not hwnd:
            return False

        style = user32.GetWindowLongW(hwnd, -16)
        user32.SetWindowLongW(hwnd, -16, style & ~0x00C00000)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)

        WM_NCCALCSIZE = 0x83
        WM_NCHITTEST = 0x84
        HTCLIENT, HTCAPTION = 1, 2
        HTLEFT, HTRIGHT, HTTOP, HTBOTTOM = 10, 11, 12, 15
        HTTOPLEFT, HTTOPRIGHT = 13, 14
        HTBOTTOMLEFT, HTBOTTOMRIGHT = 16, 17
        WNDPROCTYPE = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                         wintypes.WPARAM, wintypes.LPARAM)
        user32.DefWindowProcW.restype = LRESULT
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM]
        user32.CallWindowProcW.restype = LRESULT
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                           wintypes.UINT, wintypes.WPARAM,
                                           wintypes.LPARAM]
        user32.GetWindowRect.argtypes = [wintypes.HWND,
                                         ctypes.POINTER(wintypes.RECT)]

        def _proc(h, msg, wp, lp):
            if msg == WM_NCCALCSIZE:
                if wp:
                    return 0
                return user32.DefWindowProcW(h, msg, wp, lp)
            if msg == WM_NCHITTEST:
                x = ctypes.c_short(lp & 0xFFFF).value
                y = ctypes.c_short((lp >> 16) & 0xFFFF).value
                rc = wintypes.RECT()
                user32.GetWindowRect(h, ctypes.byref(rc))
                if not user32.IsZoomed(h):
                    b = border_px
                    left = x < rc.left + b
                    right = x >= rc.right - b
                    top = y < rc.top + b
                    bottom = y >= rc.bottom - b
                    if top and left:
                        return HTTOPLEFT
                    if top and right:
                        return HTTOPRIGHT
                    if bottom and left:
                        return HTBOTTOMLEFT
                    if bottom and right:
                        return HTBOTTOMRIGHT
                    if left:
                        return HTLEFT
                    if right:
                        return HTRIGHT
                    if top:
                        return HTTOP
                    if bottom:
                        return HTBOTTOM
                if (y - rc.top) < titlebar_h and (rc.right - x) > btn_reserve_px:
                    return HTCAPTION
                return HTCLIENT
            return user32.CallWindowProcW(prev_proc[0], h, msg, wp, lp)

        prev_proc = [_CHROME_STATE["old"]]
        _CHROME_STATE["cb"] = WNDPROCTYPE(_proc)
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            set_ptr = user32.SetWindowLongPtrW
        else:
            set_ptr = user32.SetWindowLongW
        set_ptr.restype = ctypes.c_void_p
        set_ptr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        _CHROME_STATE["old"] = set_ptr(hwnd, -4, _CHROME_STATE["cb"])
        return True
    except Exception:
        return False


_VPN_RE = None


def _vpn_re():
    global _VPN_RE
    if _VPN_RE is None:
        _VPN_RE = re.compile(
            r"VPN|TAP|TUN|WireGuard|OpenVPN|NordLynx|ExpressVPN|Surfshark|"
            r"Proton|Wintun|WireSock|AnyConnect|Forti|GlobalProtect|Zscaler|"
            r"WARP|Check\s?Point|Hamachi|Radmin|ZeroTier|Tailscale|NEAgent",
            re.IGNORECASE)
    return _VPN_RE


def vpn_status(timeout=12):
    """VPN активен? Возвращает (active: bool, names: list).

    Смотрит поднятые адаптеры с VPN-признаками в имени/описании + классические
    RAS-подключения. Только stdlib (powershell встроен в Windows).
    """
    names = []
    try:
        rc, out = run_cmd(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | "
             "ForEach-Object { $_.Name + '|' + $_.InterfaceDescription }"],
            timeout=timeout)
        if rc == 0:
            rx = _vpn_re()
            for line in out.splitlines():
                if "|" not in line:
                    continue
                nm, desc = line.split("|", 1)
                if rx.search(nm) or rx.search(desc):
                    nm = nm.strip()
                    if nm and nm not in names:
                        names.append(nm)
    except Exception:
        pass
    try:
        rc2, out2 = run_cmd(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-VpnConnection -AllUserConnection -ErrorAction SilentlyContinue | "
             "Where-Object { $_.ConnectionStatus -eq 'Connected' } | "
             "ForEach-Object { $_.Name }"],
            timeout=timeout)
        if rc2 == 0:
            for line in out2.splitlines():
                line = line.strip()
                if line and line not in names:
                    names.append(line)
    except Exception:
        pass
    return (len(names) > 0, names)


def tint_native_caption(root):
    """Покрасить системную шторку и убрать обрисовку окна (Win11 DWM).

    DWMWA_CAPTION_COLOR=35, DWMWA_TEXT_COLOR=36, DWMWA_BORDER_COLOR=34.
    Рамка красится в цвет фона — визуально обрисовки нет.
    """
    try:
        if os.name != "nt":
            return False
        from ctypes import wintypes
        hwnd = toplevel_hwnd(root)
        if not hwnd:
            return False

        def dwm_hex(h):
            h = h.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return (b << 16) | (g << 8) | r  # COLORREF 0x00BBGGRR

        dwm = ctypes.windll.dwmapi
        ok = True
        for attr, color in ((35, dwm_hex(TITLEBAR_BG)),
                            (36, dwm_hex(TEXT)),
                            (34, dwm_hex(BG))):
            try:
                c = wintypes.DWORD(color)
                hr = dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(c),
                                               ctypes.sizeof(c))
                if hr != 0:
                    ok = False
            except Exception:
                ok = False
        return ok
    except Exception:
        return False


def available_fonts(whitelist):
    try:
        tmp = tk._default_root
        fams = set(tkfont.families(tmp)) if tmp else set()
    except Exception:
        fams = set()
    found = [f for f in whitelist if f in fams]
    if not found:
        return list(whitelist[:3])
    return found


# ---- сброс кэша иконок Windows (проводник мигнёт и перезапустится) ----
def refresh_icon_cache():
    """Удаляет IconCache*.db и перезапускает проводник. Возвращает (ok, msg)."""
    try:
        if os.name != "nt":
            return False, "только Windows"
        cache_dir = os.path.join(os.path.expanduser("~"), "AppData", "Local",
                                 "Microsoft", "Windows", "Explorer")
        run_cmd(["taskkill", "/f", "/im", "explorer.exe"], timeout=15)
        time.sleep(1)
        removed = 0
        for pat in ("IconCache.db", "iconcache_*.db"):
            for fp in glob.glob(os.path.join(cache_dir, pat)):
                try:
                    os.remove(fp)
                    removed += 1
                except Exception:
                    pass
        run_cmd(["explorer.exe"], timeout=10)
        log_action(f"Сброшен кэш иконок ({removed} файлов), проводник перезапущен")
        return True, f"Удалено файлов кэша: {removed}. Если иконка не сменилась — перезагрузите ПК."
    except Exception as e:
        return False, str(e)


def system_toasts_allowed():
    """Разрешены ли системные уведомления (иначе WinRT молча глотает тосты).

    Возвращает False, если пользователь выключил уведомления в Windows —
    тогда показываем встроенное окно, чтобы ничего не потерять.
    """
    try:
        if os.name != "nt" or winreg is None:
            return False
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\PushNotifications") as k:
            try:
                v, _ = winreg.QueryValueEx(k, "ToastEnabled")
                return int(v) != 0
            except FileNotFoundError:
                return True  # ключа нет = включены по умолчанию
    except Exception:
        return True


def notify_windows(title, text):
    """Тост в Центр уведомлений Windows (notify.ps1 + WinRT).

    Возвращает True, если тост принят системой. Иначе False — caller
    показывает встроенное всплывающее окно как запасной вариант.
    """
    try:
        if os.name != "nt":
            return False
        ps1 = os.path.join(BASE_DIR, "notify.ps1")
        if not os.path.exists(ps1):
            return False
        icon = os.path.join(BASE_DIR, "assets", "icon.png")
        rc, _ = run_cmd(["powershell", "-NoProfile", "-NonInteractive",
                         "-ExecutionPolicy", "Bypass", "-File", ps1,
                         "-Title", str(title)[:120], "-Text", str(text)[:240],
                         "-AppId", APP_ID,
                         "-Icon", icon if os.path.exists(icon) else ""],
                        timeout=20)
        return rc == 0
    except Exception:
        return False


def set_lnk_appid(lnk_path, appid):
    """Прописывает System.AppUserModelID в .lnk — без этого тосты не
    закрепляются в Центре уведомлений. Только stdlib (ctypes + COM)."""
    try:
        if os.name != "nt":
            return False

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong),
                        ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort),
                        ("Data4", ctypes.c_ubyte * 8)]

        class PROPERTYKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]

        class PROPVARIANT(ctypes.Structure):
            _fields_ = [("vt", ctypes.c_ushort),
                        ("r1", ctypes.c_ushort),
                        ("r2", ctypes.c_ushort),
                        ("r3", ctypes.c_ushort),
                        ("data", ctypes.c_void_p)]

        def _guid(s):
            s = s.strip("{}")
            p = s.split("-")
            d4 = bytes.fromhex(p[3] + p[4])
            return GUID(int(p[0], 16), int(p[1], 16), int(p[2], 16),
                        (ctypes.c_ubyte * 8)(*d4))

        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
        ole32.CoInitialize(None)
        try:
            iid = _guid("{886d8eeb-8cf2-4446-8d02-cdba1dbdcf99}")
            store = ctypes.c_void_p()
            shell32.SHGetPropertyStoreFromParsingName.argtypes = [
                ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_int,
                ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
            shell32.SHGetPropertyStoreFromParsingName.restype = ctypes.c_long
            # GPS_READWRITE=2: по умолчанию хранилище только для чтения
            hr = shell32.SHGetPropertyStoreFromParsingName(
                lnk_path, None, 2, ctypes.byref(iid), ctypes.byref(store))
            if hr != 0 or not store.value:
                return False
            try:
                WINF = ctypes.WINFUNCTYPE
                # COM: object -> vtable -> functions (двойное разыменование!)
                _p0 = ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))
                _fns = ctypes.cast(_p0[0], ctypes.POINTER(ctypes.c_void_p))
                buf = ctypes.create_unicode_buffer(appid)
                prop = PROPVARIANT()
                prop.vt = 31  # VT_LPWSTR
                prop.data = ctypes.cast(buf, ctypes.c_void_p).value
                key = PROPERTYKEY(_guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"), 5)
                fn_set = WINF(ctypes.c_long, ctypes.c_void_p,
                              ctypes.POINTER(PROPERTYKEY),
                              ctypes.POINTER(PROPVARIANT))(_fns[6])
                # S_OK=записано, S_FALSE=уже стоит такое же — оба успех
                if fn_set(store, ctypes.byref(key), ctypes.byref(prop)) not in (0, 1):
                    return False
                fn_commit = WINF(ctypes.c_long, ctypes.c_void_p)(_fns[7])
                if fn_commit(store) not in (0, 1):
                    return False
                return True
            finally:
                try:
                    fn_rel = WINF(ctypes.c_ulong, ctypes.c_void_p)(_fns[2])
                    fn_rel(store)
                except Exception:
                    pass
        finally:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass
    except Exception:
        return False


def ensure_startmenu_shortcut():
    """Ярлык в меню Пуск — без него тосты не закрепляются в Центре уведомлений."""
    try:
        if os.name != "nt":
            return
        ps = ("$d=[Environment]::GetFolderPath('Programs');"
              "$p=\"$d\\Zapret Manager.lnk\";"
              "if (Test-Path -LiteralPath $p) { exit 0 };"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($p);"
              f"$s.TargetPath='{BASE_DIR}\\run.bat';"
              f"$s.WorkingDirectory='{BASE_DIR}';"
              f"$s.IconLocation='{BASE_DIR}\\assets\\icon.ico,0';"
              "$s.Description='Zapret Manager';$s.Save()")
        run_cmd(["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=20)
        # AppID на ярлыке меню Пуск — иначе тосты не закрепляются в Центре
        try:
            import subprocess as _sp
            _out = _sp.run(["powershell", "-NoProfile", "-Command",
                            "[Environment]::GetFolderPath('Programs')"],
                           capture_output=True, text=True, timeout=15)
            _lnk = os.path.join(_out.stdout.strip(),
                                "Zapret Manager.lnk")
            if os.path.exists(_lnk):
                set_lnk_appid(_lnk, APP_ID)
        except Exception:
            pass
    except Exception:
        pass


# ---- ярлык на рабочем столе в один клик ----
def create_desktop_shortcut():
    """Создать «Zapret Manager.lnk» на рабочем столе (иконка Z, запуск через run.bat).

    Возвращает (ok, путь_или_ошибка). Только stdlib: ярлык делает PowerShell
    через WScript.Shell, Python лишь запускает команду.
    """
    try:
        if os.name != "nt":
            return False, "только Windows"
        target = os.path.join(BASE_DIR, "run.bat")
        icon = os.path.join(BASE_DIR, "assets", "icon.ico")

        def q(s):
            return "'" + s.replace("'", "''") + "'"

        ps = ("$d=[Environment]::GetFolderPath('Desktop');"
              "$p=\"$d\\Zapret Manager.lnk\";"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($p);"
              f"$s.TargetPath={q(target)};$s.WorkingDirectory={q(BASE_DIR)};"
              f"$s.IconLocation={q(icon + ',0')};"
              "$s.Description='Zapret Manager — обход DPI';$s.Save();Write-Output $p")
        rc, out = run_cmd(["powershell", "-NoProfile", "-NonInteractive",
                           "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=25)
        lnk = (out.strip().splitlines() or [""])[-1].strip()
        if rc == 0 and lnk and os.path.exists(lnk):
            try:
                set_lnk_appid(lnk, APP_ID)
            except Exception:
                pass
            log_action(f"Создан ярлык на рабочем столе: {lnk}")
            return True, lnk
        return False, (out.strip()[:300] or f"код {rc}")
    except Exception as e:
        return False, str(e)


# ---- автозагрузка самого приложения ----
APP_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_RUN_NAME = "ZapretManager"
APP_TASK_NAME = "ZapretManager"


def _app_launch_target():
    exe = sys.executable
    low = exe.lower()
    if low.endswith("python.exe"):
        exe = exe[: -len("python.exe")] + "pythonw.exe"
    if getattr(sys, "frozen", False):
        return f'"{exe}" --minimized'
    return f'"{exe}" "{os.path.abspath(__file__)}" --minimized'


def _legacy_run_value():
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_RUN_KEY) as k:
            v, _ = winreg.QueryValueEx(k, APP_RUN_NAME)
            return bool(v)
    except Exception:
        return False


def _drop_legacy_run_value():
    if winreg is None:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            try:
                winreg.DeleteValue(k, APP_RUN_NAME)
            except FileNotFoundError:
                pass
    except Exception:
        pass


def _task_exists():
    rc, _ = run_cmd(["schtasks", "/query", "/tn", APP_TASK_NAME], timeout=10)
    return rc == 0


def app_autostart_enabled():
    try:
        if _task_exists():
            return True
    except Exception:
        pass
    return _legacy_run_value()


def set_app_autostart(enable):
    """Автозагрузка через планировщик с высшим приоритетом (админ при входе).

    Создание задачи с /rl highest требует прав администратора один раз —
    без них отправляем команду через UAC-запрос.
    """
    try:
        if enable:
            target = _app_launch_target()
            args = ["schtasks", "/create", "/tn", APP_TASK_NAME,
                    "/tr", target, "/sc", "onlogon", "/rl", "highest", "/f"]
            if is_admin():
                rc, out = run_cmd(args, timeout=20)
                if rc != 0:
                    return False, f"schtasks: {out.strip()[:300]}"
            else:
                # schtasks с кавычками через cmd: экранируем для /c
                cmdline = "schtasks /create /tn \"{}\" /tr \"{}\" /sc onlogon /rl highest /f".format(
                    APP_TASK_NAME, target.replace('"', '""'))
                if not elevated_cmd(cmdline):
                    return False, "Нужны права администратора (UAC отклонён)"
                time.sleep(2)
                if not _task_exists():
                    return False, "Задача не создалась — подтвердите UAC и попробуйте снова"
            _drop_legacy_run_value()
            log_action("Автозагрузка приложения ВКЛ (планировщик, с правами администратора)")
            return True, "Приложение будет запускаться при входе с правами администратора"
        else:
            if is_admin():
                run_cmd(["schtasks", "/delete", "/tn", APP_TASK_NAME, "/f"], timeout=15)
            else:
                elevated_cmd(f'schtasks /delete /tn "{APP_TASK_NAME}" /f')
                time.sleep(1)
            _drop_legacy_run_value()
            log_action("Автозагрузка приложения ВЫКЛ")
            return True, ""
    except Exception as e:
        return False, str(e)


# ================= движок проверки =================

class CheckEngine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.cancel_flag = threading.Event()
        self.running = False
        self.abort_reason = ""  # nonetwork | deadnet | "" (отмена/ок)

    def cancel(self):
        self.cancel_flag.set()

    def probe_many(self, targets, timeout, ping_thr, repeat, workers):
        """Параллельная проверка целей в пуле потоков — главный источник ускорения."""
        ping_cap = min(ping_thr, 1500)
        workers = min(16, max(2, int(workers)))
        order = [n for n, _ in targets]
        results = {}

        def _one(pair):
            n, v = pair
            try:
                return probe_target(n, v, timeout, ping_thr, ping_cap, repeat)
            except Exception:
                host, po = split_host(v)
                return {"name": n, "host": host, "ping_ms": None,
                        "ping_ok": False, "http_ok": None if po else False,
                        "ping_only": po}

        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_one, p): p[0] for p in targets}
            for fut in cf.as_completed(futs):
                if self.cancel_flag.is_set():
                    for f in futs:
                        f.cancel()
                    break
                try:
                    r = fut.result()
                except Exception:
                    continue
                results[r["name"]] = r
        return [results[n] for n in order if n in results]

    def test_targets_current(self):
        """ЭКО-режим для автомониторинга: минимум ресурсов —
        3 потока, 1 повтор, короткий таймаут, фоновый приоритет потока."""
        targets = parse_targets(self.cfg["zapret_root"], self.cfg.get("targets_override", ""))
        targets = quick_filter(targets)
        timeout = min(3, int(self.cfg.get("check_timeout_s", 4)))
        ping_thr = int(self.cfg.get("ping_threshold_ms", 5000))
        eco = thread_bg_mode(True)
        try:
            results = self.probe_many(targets, timeout, ping_thr, 1, 3)
        finally:
            if eco:
                thread_bg_mode(False)
        ok_http = sum(1 for r in results if r["http_ok"] is True)
        fail_http = sum(1 for r in results if r["http_ok"] is False)
        bad_ping = sum(1 for r in results if not r["ping_ok"])
        total_http = ok_http + fail_http
        dpi_block = (total_http > 0 and fail_http / total_http >= 0.5)
        ping_problem = (bad_ping >= max(2, len(results) // 2))
        blocked = dpi_block and ping_problem or (total_http > 0 and fail_http == total_http)
        return {"results": results, "ok_http": ok_http, "fail_http": fail_http,
                "bad_ping": bad_ping, "dpi_block": dpi_block,
                "ping_problem": ping_problem, "blocked": blocked}

    def check_configs(self, bat_list, progress_cb=None, log_cb=None, boost=False):
        self.running = True
        self.cancel_flag.clear()
        all_targets = parse_targets(self.cfg["zapret_root"], self.cfg.get("targets_override", ""))
        mode = self.cfg.get("check_mode", "quick")
        if mode == "quick":
            targets = quick_filter(all_targets)
        else:
            targets = all_targets
        timeout = int(self.cfg.get("check_timeout_s", 4))
        ping_thr = int(self.cfg.get("ping_threshold_ms", 5000))
        repeat = int(self.cfg.get("check_repeat", 2))
        workers = int(self.cfg.get("check_workers", 8))
        turbo = False
        if boost:
            # ТУРБО для ручной проверки: максимум потоков + высокий приоритет процесса
            cpu = os.cpu_count() or 4
            workers = min(16, max(workers, cpu * 2))
            turbo = set_process_priority(True)
        all_results = {}
        self.abort_reason = ""
        # гейт: без сети проверять нечего (иначе 22 × таймауты впустую)
        if not network_alive():
            if log_cb:
                log_cb("⛔ Нет сети (не пингуются даже 1.1.1.1/8.8.8.8) — проверка прервана.")
            self.abort_reason = "nonetwork"
            if boost:
                set_process_priority(False)
            self.running = False
            return all_results
        # запомнить что было запущено, чтобы восстановить
        had_service = service_status()["zapret"] == "RUNNING"
        if had_service:
            if log_cb:
                log_cb("Обнаружена служба zapret — для честной проверки она будет временно остановлена и потом возвращена.")
        if mode == "ultra":
            self._ultra_loop(bat_list, targets, timeout, ping_thr, repeat,
                             workers, turbo, all_results, progress_cb, log_cb)
        else:
            if log_cb:
                modetxt = ('БЫСТРЫЙ (Discord+YouTube, ' + str(len(targets)) + ' целей, повторов: ' + str(repeat) + ', потоков: ' + str(workers) + ')'
                           if mode == 'quick' else 'ПОЛНЫЙ (' + str(len(targets)) + ' целей, потоков: ' + str(workers) + ')')
                log_cb(f"Режим: {modetxt} — цели проверяются параллельно."
                       + (" ТУРБО: приоритет процесса повышен." if turbo else ""))
            self._seq_loop(bat_list, targets, timeout, ping_thr, repeat,
                           workers, len(bat_list), all_results, progress_cb, log_cb)
        stop_winws()
        # сохранить историю: используемый конфиг + пинги целевых сервисов
        try:
            ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            path = os.path.join(CHECKS_DIR, f"check_{ts}.json")
            summary = {}
            for k, v in all_results.items():
                dm, ym = service_pings(v.get("rows", []))
                summary[k] = {"ok": v["ok"], "fail": v["fail"],
                              "ping_ok": v.get("ping_ok", 0), "score": v["score"],
                              "discord_ms": dm, "youtube_ms": ym,
                              "grade": config_grade(dm, ym)[0] if v.get("started") else "Не работает",
                              "final": bool(v.get("final", True)),
                              "mode": mode}
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"time": ts,
                           "active": self.cfg.get("active_config", ""),
                           "mode": mode,
                           "summary": summary,
                           "details": all_results}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        if boost:
            set_process_priority(False)  # вернуть обычный приоритет
        self.running = False
        return all_results

    def _seq_loop(self, bat_list, targets, timeout, ping_thr, repeat,
                  workers, total, all_results, progress_cb, log_cb):
        """Обычный последовательный замер каждого конфига."""
        # остановить всё перед тестами
        stop_winws()
        time.sleep(0.2)
        dead_chain = 0
        for idx, bat in enumerate(bat_list):
            if self.cancel_flag.is_set():
                break
            if log_cb:
                log_cb(f"[{idx+1}/{total}] Запуск {bat} …")
            t0 = time.time()
            start_winws_hidden(self.cfg["zapret_root"], bat)
            if not wait_winws_ready(6.0):
                if log_cb:
                    log_cb(f"  {bat}: winws не запустился — пропуск")
                all_results[bat] = {"ok": 0, "fail": len(targets), "rows": [],
                                    "started": False, "score": -1, "final": True}
                if progress_cb:
                    progress_cb(idx + 1, total, bat, -1, all_results[bat])
                continue
            rows = self.probe_many(targets, timeout, ping_thr, repeat, workers)
            ok = sum(1 for r in rows if r["http_ok"] is True)
            fail = sum(1 for r in rows if r["http_ok"] is False)
            ping_ok_n = sum(1 for r in rows if r["ping_ok"])
            dt = time.time() - t0
            score = ok * 10 + ping_ok_n
            all_results[bat] = {"ok": ok, "fail": fail, "ping_ok": ping_ok_n,
                                "rows": rows, "started": True, "score": score,
                                "final": True}
            if log_cb:
                log_cb(f"  {bat}: HTTP OK={ok} ERR={fail} PingOK={ping_ok_n} score={score} ({dt:.0f} c)")
            if progress_cb:
                progress_cb(idx + 1, total, bat, score, all_results[bat])
            # circuit breaker: три подряд полных глухаря (не пингуется НИЧЕГО) —
            # это уже не конфиги, а упавшая сеть. Дальше гнать таймауты бессмысленно.
            if ok == 0 and ping_ok_n == 0 and fail > 0:
                dead_chain += 1
                if dead_chain >= 3:
                    if log_cb:
                        log_cb("⛔ Три конфига подряд без единого пакета — похоже, сеть упала. Прерываю.")
                    self.abort_reason = "deadnet"
                    stop_winws()
                    break
            else:
                dead_chain = 0
            stop_winws()
            time.sleep(0.2)

    def _ultra_loop(self, bat_list, targets, timeout, ping_thr, repeat,
                    workers, turbo, all_results, progress_cb, log_cb):
        """УЛЬТРА-турнир: дешёвый отсев всех -> точный замер топ-N.

        Честное предупреждение: одновременно гнать все конфиги НЕЛЬЗЯ —
        все winws делят один драйвер WinDivert и один сетевой путь, стратегии
        стали бы кромсать одни и те же пакеты и замер показал бы кашу, а не
        качество конфига. Поэтому отсев идёт по очереди, но очень дёшево
        (2 ключевые цели, 1 повтор), а точно меряем только финалистов.
        Пинги отсева — ПРИБЛИЗИТЕЛЬНЫЕ (помечены ≈).
        """
        screen = [(n, v) for n, v in targets if n in ULTRA_SCREEN_TARGETS]
        if len(screen) < 2:
            screen = targets[:2]
        total = len(bat_list)
        n_fin = min(ULTRA_FINALISTS, total)
        grand = total + n_fin
        if log_cb:
            log_cb(f"Режим УЛЬТРА: отсев {total} конфигов по {len(screen)} целям "
                   f"(1 повтор, таймаут 3с), затем точный замер топ-{n_fin}."
                   + (" ТУРБО: приоритет процесса повышен." if turbo else ""))
            log_cb("Почему не все сразу: конфиги делят один WinDivert — "
                   "параллельный запуск испортил бы замер.")
        stop_winws()
        time.sleep(0.2)
        order = list(bat_list)
        dead_chain = 0
        # --- фаза 1: отсев ---
        for idx, bat in enumerate(order):
            if self.cancel_flag.is_set():
                break
            if log_cb:
                log_cb(f"[отсев {idx+1}/{total}] {bat} …")
            t0 = time.time()
            start_winws_hidden(self.cfg["zapret_root"], bat)
            if not wait_winws_ready(4.0, fast=True):
                if log_cb:
                    log_cb(f"  {bat}: winws не запустился — пропуск")
                all_results[bat] = {"ok": 0, "fail": len(screen), "rows": [],
                                    "started": False, "score": -1, "final": False}
                if progress_cb:
                    progress_cb(idx + 1, grand, bat, -1, all_results[bat])
                continue
            rows = self.probe_many(screen, 3, ping_thr, 1, workers)
            ok = sum(1 for r in rows if r["http_ok"] is True)
            fail = sum(1 for r in rows if r["http_ok"] is False)
            ping_ok_n = sum(1 for r in rows if r["ping_ok"])
            score = ok * 10 + ping_ok_n
            all_results[bat] = {"ok": ok, "fail": fail, "ping_ok": ping_ok_n,
                                "rows": rows, "started": True, "score": score,
                                "final": False}
            if log_cb:
                log_cb(f"  {bat}: отсев OK={ok} ERR={fail} (~{time.time()-t0:.0f} c)")
            if progress_cb:
                progress_cb(idx + 1, grand, bat, score, all_results[bat])
            if ok == 0 and ping_ok_n == 0 and fail > 0:
                dead_chain += 1
                if dead_chain >= 3:
                    if log_cb:
                        log_cb("⛔ Три конфига подряд без единого пакета — похоже, сеть упала. Прерываю.")
                    self.abort_reason = "deadnet"
                    stop_winws()
                    return
            else:
                dead_chain = 0
            stop_winws()
            time.sleep(0.2)
        if self.cancel_flag.is_set():
            return
        # --- фаза 2: финал ---
        ranked = sorted(all_results.items(), key=lambda kv: -kv[1]["score"])
        finalists = [b for b, _ in ranked[:n_fin]]
        if log_cb:
            log_cb(f"Финалисты топ-{len(finalists)}: {', '.join(finalists)} — точный замер…")
        for j, bat in enumerate(finalists):
            if self.cancel_flag.is_set():
                break
            if log_cb:
                log_cb(f"[финал {j+1}/{len(finalists)}] {bat} …")
            t0 = time.time()
            start_winws_hidden(self.cfg["zapret_root"], bat)
            if not wait_winws_ready(6.0):
                if log_cb:
                    log_cb(f"  {bat}: winws не запустился в финале")
                all_results[bat]["final"] = True
                if progress_cb:
                    progress_cb(total + j + 1, grand, bat,
                                all_results[bat]["score"], all_results[bat])
                continue
            rows = self.probe_many(targets, timeout, ping_thr, repeat, workers)
            ok = sum(1 for r in rows if r["http_ok"] is True)
            fail = sum(1 for r in rows if r["http_ok"] is False)
            ping_ok_n = sum(1 for r in rows if r["ping_ok"])
            score = ok * 10 + ping_ok_n
            all_results[bat] = {"ok": ok, "fail": fail, "ping_ok": ping_ok_n,
                                "rows": rows, "started": True, "score": score,
                                "final": True}
            if log_cb:
                log_cb(f"  {bat}: финал OK={ok} ERR={fail} score={score} ({time.time()-t0:.0f} c)")
            if progress_cb:
                progress_cb(total + j + 1, grand, bat, score, all_results[bat])
            stop_winws()
            time.sleep(0.2)


# ================= UI =================

class ScrollFrame(tk.Frame):
    # Виджеты со своим колесом: страницу под ними не крутим (иначе перелёты)
    _WHEEL_SELF = ("Text", "Listbox", "Entry", "TEntry", "Combobox", "TCombobox",
                   "Spinbox", "TSpinbox")

    def __init__(self, parent, bg=CARD, **kw):
        super().__init__(parent, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.vsb = NiceScroll(self, command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.inner.bind("<Configure>", self._region)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._sync_width, add="+")
        self.canvas.bind("<Configure>", self._sync_width, add="+")
        self.bind_all("<MouseWheel>", self._wheel, add="+")

    def _region(self, _e=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            self._autohide()
        except Exception:
            pass

    def _on_scroll(self, first, last):
        try:
            self.vsb.set(first, last)
            self._autohide()
        except Exception:
            pass

    def _fits(self):
        """Контент помещается целиком — крутить нечего."""
        try:
            bbox = self.canvas.bbox("all")
            if not bbox:
                return True
            return (bbox[3] - bbox[1]) <= self.canvas.winfo_height()
        except Exception:
            return False

    def _autohide(self):
        # нет прокрутки — прячем ползунок, есть — показываем
        try:
            if self._fits():
                self.canvas.yview_moveto(0)
                if str(self.vsb.winfo_manager()) == "pack":
                    self.vsb.pack_forget()
            else:
                if str(self.vsb.winfo_manager()) != "pack":
                    self.vsb.pack(side="right", fill="y")
        except Exception:
            pass

    def _sync_width(self, e=None):
        # NOTE: ширина хранится в self._bw — имя self._w занято Tk (путь виджета)!
        try:
            self.canvas.itemconfig(self.win, width=self.canvas.winfo_width())
            self._region()
        except Exception:
            pass

    def _wheel(self, e):
        try:
            tgt = self.winfo_containing(e.x_root, e.y_root)
            if not tgt or not str(tgt).startswith(str(self)):
                return
            # у текстов/списков/полей своё колесо — страницу не трогаем
            try:
                if tgt.winfo_class() in self._WHEEL_SELF:
                    return
            except Exception:
                pass
            if self._fits():
                return
            steps = int(-1 * (e.delta / 120))
            if steps == 0:
                steps = -1 if e.delta > 0 else 1
            self.canvas.yview_scroll(steps, "units")
        except Exception:
            pass


def _mix_hex(h1, h2, t):
    """Смешать два #rrggbb цвета (t=0 -> h1)."""
    try:
        a = tuple(int(h1.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        b = tuple(int(h2.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    except Exception:
        return h1


def _round_points(x0, y0, x1, y1, r, seg=4):
    """Точки скруглённого прямоугольника для create_polygon(smooth=True)."""
    import math as _m
    pts = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0),
                       (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for i in range(seg + 1):
            a = _m.radians(a0 + 90 * i / seg)
            pts += [cx + r * _m.cos(a), cy + r * _m.sin(a)]
    return pts


class StatusBadge(tk.Canvas):
    """Пилюля статуса в шапке: цветная точка + текст на тонированной подложке."""

    def __init__(self, parent, **kw):
        self._text = "статус…"
        self._color = MUTED
        try:
            bg0 = parent.cget("background")
        except Exception:
            bg0 = BG
        self._bg0 = bg0
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("bd", 0)
        super().__init__(parent, width=160, height=28, bg=bg0, **kw)
        self._draw()
        track_themed(self)

    def set(self, text, color):
        self._text = text or ""
        self._color = color or MUTED
        try:
            _f = tkfont.Font(font=(FONT, 10))
            self.configure(width=_f.measure(self._text) + 44)
        except Exception:
            pass
        self._draw()

    def _draw(self):
        try:
            self.delete("all")
            w, h = int(self.cget("width")), 28
            try:
                bg0 = self.master.cget("background")
            except Exception:
                bg0 = self._bg0
            pill = _mix_hex(bg0, self._color, 0.16)
            r = h // 2 - 1
            self.create_polygon(_round_points(2, 2, w - 2, h - 2, r),
                                smooth=True, splinesteps=8, fill=pill, outline="")
            cx = 16
            self.create_oval(cx - 6, h // 2 - 6, cx + 6, h // 2 + 6,
                             fill=self._color, outline="")
            self.create_text(cx + 12, h // 2, text=self._text, fill=self._color,
                             font=(FONT, 10, "bold"), anchor="w")
        except Exception:
            pass

    def apply_theme(self):
        self._color = remap_color(self._color)
        try:
            self.configure(bg=self.master.cget("background"))
        except Exception:
            pass
        self._draw()


class RButton(tk.Canvas):
    """Кнопка-пилюля со скруглением. style: accent | ghost.

    Цвета берутся из палитры в момент отрисовки; при живой смене темы
    перерисовывается через THEMED.apply_theme().
    """

    def __init__(self, parent, text="", style="accent", command=None,
                 font=None, pad_x=18, height=34, min_width=0,
                 state="normal", **kw):
        self._text = text
        self._style = style if style in ("accent", "ghost") else "ghost"
        self._command = command
        self._font = font or (FONT, 10, "bold" if self._style == "accent" else "normal")
        self._h = max(24, int(height))
        self._pad = pad_x
        self._enabled = (state != "disabled")
        self._hover = False
        self._pressed = False
        try:
            _f = tkfont.Font(font=self._font)
            tw = _f.measure(text)
        except Exception:
            tw = len(text) * 8
        w = max(min_width, tw + pad_x * 2, 44)
        try:
            bg0 = parent.cget("background")
        except Exception:
            bg0 = CARD
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("bd", 0)
        super().__init__(parent, width=int(w), height=self._h, bg=bg0, **kw)
        self._bw = int(w)
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.bind("<ButtonPress-1>", self._on_press, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")
        self.bind("<space>", lambda _e: self.invoke(), add="+")
        self.bind("<Return>", lambda _e: self.invoke(), add="+")
        try:
            self.configure(takefocus=1)
        except Exception:
            pass
        self._draw()
        track_themed(self)

    def _colors(self):
        if not self._enabled:
            return (CARD2, MUTED, BORDER)
        if self._style == "accent":
            bg = ACCENT_HOVER if (self._hover or self._pressed) else ACCENT
            return (bg, "white", bg)
        if self._pressed:
            return (ACCENT_DEEP, TEXT, ACCENT_DEEP)
        if self._hover:
            return (BORDER, TEXT, ACCENT)
        return (CARD2, TEXT, BORDER)

    def _round_rect(self, x0, y0, x1, y1, r, fill, outline, width=1, tag=""):
        # один smooth-полигон вместо 8 примитивов — дешевле перерисовка
        pts = _round_points(x0, y0, x1, y1, r)
        self.create_polygon(pts, smooth=True, splinesteps=8, fill=fill,
                            outline=outline if width else fill, width=width,
                            tags=tag)

    def _draw(self):
        try:
            self.delete("all")
            bg, fg, edge = self._colors()
            r = 9  # прямоугольник со скруглёнными углами (не пилюля)
            self._round_rect(2, 2, self._bw - 2, self._h - 2, r, bg, edge,
                             0 if self._style == "accent" and self._enabled else 1)
            self.create_text(self._bw // 2, self._h // 2, text=self._text,
                             fill=fg, font=self._font)
            self.configure(cursor="hand2" if self._enabled else "arrow")
        except Exception:
            pass

    def apply_theme(self):
        try:
            self.configure(bg=self.master.cget("background"))
        except Exception:
            pass
        self._draw()

    def _on_enter(self, _e=None):
        if not self._enabled:
            return
        self._hover = True
        self._draw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, _e=None):
        if not self._enabled:
            return
        self._pressed = True
        self._draw()

    def _on_release(self, _e=None):
        was = self._pressed and self._hover and self._enabled
        self._pressed = False
        self._draw()
        if was and callable(self._command):
            try:
                self._command()
            except Exception:
                pass

    def invoke(self):
        if self._enabled and callable(self._command):
            try:
                self._command()
            except Exception:
                pass

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        self._draw()

    def set_text(self, text):
        self._text = text
        try:
            _f = tkfont.Font(font=self._font)
            self._bw = max(_f.measure(text) + self._pad * 2, 44)
            self.configure(width=self._bw)
        except Exception:
            pass
        self._draw()

    def config(self, **kw):
        if "state" in kw:
            self.set_enabled(kw.pop("state") != "disabled")
        if "text" in kw:
            self.set_text(kw.pop("text"))
        if "command" in kw:
            self._command = kw.pop("command")
        if kw:
            try:
                super().configure(**kw)
            except Exception:
                pass

    configure = config


class NiceScroll(tk.Canvas):
    """Тонкий скруглённый скроллбар. API как у ttk.Scrollbar: command=, .set()."""

    def __init__(self, parent, command=None, width=12, **kw):
        self._command = command
        self._bw = max(8, int(width))
        self._first, self._last = 0.0, 1.0
        self._hover = False
        self._dragging = False
        self._grab = 0
        try:
            bg0 = parent.cget("background")
        except Exception:
            bg0 = BG
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("bd", 0)
        super().__init__(parent, width=self._bw, bg=bg0, **kw)
        self.bind("<Configure>", lambda _e: self._draw(), add="+")
        self.bind("<Enter>", lambda _e: self._set_hover(True), add="+")
        self.bind("<Leave>", lambda _e: self._set_hover(False), add="+")
        self.bind("<ButtonPress-1>", self._press, add="+")
        self.bind("<B1-Motion>", self._drag, add="+")
        self.bind("<ButtonRelease-1>", lambda _e: self._end_drag(), add="+")
        track_themed(self)

    def set(self, first, last):
        try:
            self._first = max(0.0, min(1.0, float(first)))
            self._last = max(0.0, min(1.0, float(last)))
        except Exception:
            self._first, self._last = 0.0, 1.0
        self._draw()

    def _geom(self):
        h = max(1, self.winfo_height())
        pad = 3
        track_h = max(1, h - pad * 2)
        fh = max(0.0, self._last - self._first)
        if fh >= 1.0:
            return pad, track_h, pad, pad + track_h
        th = max(30, track_h * fh)
        span = max(1e-6, 1.0 - fh)
        y0 = pad + (track_h - th) * (self._first / span)
        return pad, track_h, y0, y0 + th

    def _thumb_color(self):
        if self._dragging or self._hover:
            return ACCENT
        return BORDER

    def _draw(self):
        try:
            self.delete("all")
            pad, track_h, y0, y1 = self._geom()
            x0, x1 = 2, self._bw - 2
            col = self._thumb_color()
            self.create_polygon(_round_points(x0, y0, x1, y1, (x1 - x0) // 2),
                                smooth=True, splinesteps=8, fill=col, outline="")
            self.configure(cursor="hand2" if self._hover or self._dragging else "arrow")
        except Exception:
            pass

    def apply_theme(self):
        try:
            self.configure(bg=self.master.cget("background"))
        except Exception:
            pass
        self._draw()

    def _set_hover(self, v):
        self._hover = bool(v)
        if not v:
            self._dragging = False
        self._draw()

    def _press(self, e):
        try:
            _, _, y0, y1 = self._geom()
            if y0 <= e.y <= y1:
                self._dragging = True
                self._grab = e.y - y0
            else:
                pad, track_h, ty0, ty1 = self._geom()
                if callable(self._command):
                    self._command("scroll", -1 if e.y < ty0 else 1, "pages")
            self._draw()
        except Exception:
            pass

    def _drag(self, e):
        if not self._dragging:
            return
        try:
            pad, track_h, y0, y1 = self._geom()
            th = y1 - y0
            frac = (e.y - pad - self._grab) / max(1.0, track_h - th)
            frac = max(0.0, min(1.0, frac))
            if callable(self._command):
                self._command("moveto", frac)
        except Exception:
            pass

    def _end_drag(self):
        self._dragging = False
        self._draw()


class DropMenu(tk.Frame):
    """Красивый выпадающий список вместо Combobox. Темы — через THEMED."""

    def __init__(self, parent, variable, values, width=24, command=None, **kw):
        super().__init__(parent, bg=BORDER, padx=1, pady=1)
        self._var = variable
        self._values = list(values or [])
        self._command = command
        self._pop = None
        self._inner = tk.Frame(self, bg=CARD2)
        self._inner.pack(fill="both", expand=True)
        self._lbl = tk.Label(self._inner, textvariable=variable, bg=CARD2,
                             fg=TEXT, font=(FONT, 10), anchor="w")
        self._lbl.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=5)
        self._arrow = tk.Label(self._inner, text="▾", bg=CARD2, fg=MUTED,
                               font=(FONT, 10))
        self._arrow.pack(side="right", padx=8)
        try:
            _f = tkfont.Font(font=(FONT, 10))
            tw = max([_f.measure(str(v)) for v in self._values] + [60])
            self.configure(width=max(tw + 48, int(width) * 9))
        except Exception:
            pass
        for w in (self, self._inner, self._lbl, self._arrow):
            w.bind("<Button-1>", self._toggle, add="+")
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
        track_themed(self)

    def set_values(self, values):
        self._values = list(values or [])
        if self._var.get() not in self._values and self._values:
            self._var.set(self._values[0])

    def apply_theme(self):
        try:
            self.configure(bg=BORDER)
            self._inner.configure(bg=CARD2)
            self._lbl.configure(bg=CARD2, fg=TEXT)
            self._arrow.configure(bg=CARD2, fg=MUTED)
        except Exception:
            pass
        try:
            if self._pop is not None:
                self._close()
        except Exception:
            pass

    def _toggle(self, _e=None):
        if self._pop is not None:
            self._close()
            return "break"
        try:
            pop = tk.Toplevel(self)
            pop.overrideredirect(True)
            pop.attributes("-topmost", True)
            pop.configure(bg=BORDER)
            frm = tk.Frame(pop, bg=CARD2)
            frm.pack(fill="both", expand=True, padx=1, pady=1)
            for v in self._values:
                row = tk.Label(frm, text=v, bg=CARD2, fg=TEXT, font=(FONT, 10),
                               anchor="w", padx=10, pady=5)
                row.pack(fill="x")
                row.bind("<Enter>", lambda e, r=row: r.configure(bg=ACCENT, fg="white"))
                row.bind("<Leave>", lambda e, r=row: r.configure(bg=CARD2, fg=TEXT))
                row.bind("<Button-1>", lambda e, val=v: self._pick(val))
            pop.update_idletasks()
            x = self.winfo_rootx()
            y = self.winfo_rooty() + self.winfo_height() + 2
            pop.geometry(f"{self.winfo_width()}x{min(240, 30 * max(1, len(self._values)))}+{x}+{y}")
            self._pop = pop
            pop.bind("<Escape>", lambda _e: self._close())
            pop.bind("<FocusOut>", lambda _e: self.after(120, self._autoclose))
            try:
                pop.focus_set()
            except Exception:
                pass
        except Exception:
            pass
        return "break"

    def _autoclose(self):
        try:
            if self._pop is not None and not str(self.focus_get()).startswith(str(self._pop)):
                self._close()
        except Exception:
            pass

    def _pick(self, val):
        try:
            self._var.set(val)
        except Exception:
            pass
        self._close()
        if callable(self._command):
            try:
                self._command()
            except Exception:
                pass

    def _close(self):
        try:
            p, self._pop = self._pop, None
            if p is not None:
                p.destroy()
        except Exception:
            self._pop = None


class ZapretApp:
    def __init__(self, root, minimized=False):
        self.root = root
        self.cfg = load_config()
        self.engine = CheckEngine(self.cfg)
        self.msg_q = queue.Queue()
        self.last_results = {}
        self.monitor_thread = None
        self.monitor_stop = threading.Event()
        self.minimized = minimized

        root.title(f"{APP_NAME} v{APP_VERSION}")
        # стартовый размер — широко, чтобы все поля видны сразу: 1480x860,
        # ужато под экран и отцентрировано
        try:
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            ww, hh = min(1480, max(1100, sw - 40)), min(860, max(660, sh - 60))
            root.geometry(f"{ww}x{hh}+{(sw - ww) // 2}+{(sh - hh) // 2}")
        except Exception:
            root.geometry("1480x860")
        root.minsize(1000, 640)
        try:
            root.configure(bg=BG)
        except Exception:
            pass
        try:
            root.iconbitmap(default="")
        except Exception:
            pass
        # своя шапка вместо системной (на Win10 DWM-тинт невозможен).
        # Tk сбрасывает стиль при первом показе — повтор по <Map>.
        self._chrome_ok = False
        self._maximized = False
        try:
            root.update_idletasks()
            self._chrome_ok = setup_borderless(root)
        except Exception:
            self._chrome_ok = False
        root.bind("<Map>", self._on_map_chrome, add="+")
        self.style_setup()
        self.build_layout()
        self.refresh_all_static()
        self.root.after(200, self.poll_queue)
        if minimized:
            try:
                root.iconify()
            except Exception:
                pass
        # автопроверка папки
        if not os.path.isdir(self.cfg.get("zapret_root", "")):
            self.root.after(400, self.ask_zapret_root_first)
        # старт мониторинга
        if self.cfg.get("monitor_enabled"):
            self.start_monitor()
        # проверка обновлений zapret-discord-youtube и самого приложения
        self.check_zapret_updates()
        self.check_app_updates()

    def _on_map_chrome(self, _e=None):
        # Tk возвращает WS_CAPTION при первом показе — снять снова
        try:
            u = ctypes.windll.user32
            hwnd = toplevel_hwnd(self.root)
            if hwnd and (u.GetWindowLongW(hwnd, -16) & 0x00C00000):
                self._chrome_ok = setup_borderless(self.root)
        except Exception:
            pass

    # ---------- стиль ----------
    def style_setup(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=CARD)
        st.configure("TLabel", background=BG, foreground=TEXT, font=(FONT, 10))
        st.configure("Card.TLabel", background=CARD, foreground=TEXT)
        st.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT, 9))
        st.configure("MutedCard.TLabel", background=CARD, foreground=MUTED, font=(FONT, 9))
        st.configure("Title.TLabel", background=BG, foreground=TEXT, font=(FONT, 16, "bold"))
        st.configure("H2.TLabel", background=CARD, foreground=TEXT, font=(FONT, 12, "bold"))
        st.configure("Accent.TButton", background=ACCENT, foreground="white",
                     font=(FONT, 10, "bold"), borderwidth=0, padding=(14, 8))
        st.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("disabled", BORDER)])
        st.configure("Ghost.TButton", background=CARD2, foreground=TEXT,
                     font=(FONT, 10), borderwidth=1, padding=(12, 7))
        st.map("Ghost.TButton", background=[("active", BORDER)])
        st.configure("Nav.TButton", background=SIDEBAR, foreground=MUTED,
                     font=(FONT, 11), borderwidth=0, padding=(12, 10), anchor="w")
        st.map("Nav.TButton", background=[("active", CARD2)], foreground=[("active", TEXT)])
        st.configure("TEntry", fieldbackground=CARD2, background=CARD2, foreground=TEXT,
                     bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                     selectbackground=ACCENT, selectforeground="white")
        st.configure("TCheckbutton", background=BG, foreground=TEXT, font=(FONT, 10))
        st.configure("Card.TCheckbutton", background=CARD, foreground=TEXT, font=(FONT, 10))
        st.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=CARD2,
                     bordercolor=BG, lightcolor=ACCENT, darkcolor=ACCENT)
        # таблицы — здесь (единое место), чтобы живая смена темы их красила
        st.configure("Treeview", background=CARD2, foreground=TEXT,
                     fieldbackground=CARD2, font=(FONT, 9), borderwidth=0,
                     rowheight=24)
        st.configure("Treeview.Heading", background=BORDER, foreground=TEXT,
                     font=(FONT, 9, "bold"))
        st.map("Treeview", background=[("selected", ACCENT)],
               foreground=[("selected", "white")])
        # рамка выпадашки комбобокса (иначе серая из clam)
        st.configure("ComboboxPopdownFrame", background=BORDER, relief="flat",
                     borderwidth=1)
        # скроллбары, комбобоксы, спинбоксы — в цветах темы
        st.configure("Vertical.TScrollbar", background=CARD2, troughcolor=BG,
                     bordercolor=BG, arrowcolor=MUTED, relief="flat")
        st.map("Vertical.TScrollbar", background=[("active", BORDER)],
               arrowcolor=[("active", TEXT)])
        st.configure("TCombobox", fieldbackground=CARD2, background=CARD2,
                     foreground=TEXT, arrowcolor=MUTED, bordercolor=BORDER,
                     lightcolor=BORDER, darkcolor=BORDER)
        st.map("TCombobox", fieldbackground=[("readonly", CARD2)],
               foreground=[("readonly", TEXT)])
        try:
            self.root.option_add("*TCombobox*Listbox.background", CARD2)
            self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
            self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
            self.root.option_add("*TCombobox*Listbox.selectForeground", "white")
            self.root.option_add("*TCombobox*Listbox.font", (FONT, 10))
            self.root.option_add("*Menu.background", CARD2)
            self.root.option_add("*Menu.foreground", TEXT)
        except Exception:
            pass

    # ---------- своя шапка окна ----------
    def build_titlebar(self):
        """Шапка в стиле темы + системные кнопки ─ ▢ ✕."""
        bar = tk.Frame(self.root, bg=TITLEBAR_BG, height=40)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        bar.columnconfigure(0, weight=1)
        left = tk.Frame(bar, bg=TITLEBAR_BG)
        left.grid(row=0, column=0, sticky="w")
        tk.Label(left, text="🔥", bg=TITLEBAR_BG, fg=ACCENT_HOVER,
                 font=(FONT, 13)).pack(side="left", padx=(14, 6))
        tk.Label(left, text=APP_NAME, bg=TITLEBAR_BG, fg=TEXT,
                 font=(FONT, 11, "bold")).pack(side="left")
        tk.Label(left, text=f"v{APP_VERSION}", bg=TITLEBAR_BG, fg=MUTED,
                 font=(FONT, 9)).pack(side="left", padx=(8, 0))
        btns = tk.Frame(bar, bg=TITLEBAR_BG)
        btns.grid(row=0, column=1, sticky="e", padx=(0, 6))

        def _mk(txt, cmd, hover_role):
            # цвета резолвятся в момент наведения — переживают смену темы
            b = tk.Button(btns, text=txt, bg=TITLEBAR_BG, fg=MUTED, font=(FONT, 11),
                          bd=0, width=4, cursor="hand2", activebackground=TITLEBAR_BG,
                          activeforeground="white", command=cmd)
            b.pack(side="left", padx=1, pady=3)

            def _h(_e=None, bb=b):
                bb.config(bg=CARD2 if hover_role == "card2" else ACCENT,
                          fg="white")

            def _l(_e=None, bb=b):
                bb.config(bg=TITLEBAR_BG, fg=MUTED)

            b.bind("<Enter>", _h)
            b.bind("<Leave>", _l)
            return b

        _mk("─", lambda: self._win_min(), "card2")
        self.btn_max = _mk("▢", lambda: self.toggle_maximize(), "card2")
        _mk("✕", lambda: self._win_close(), "accent")
        # даблклик — развернуть (при рабочем borderless этим занимается Windows)
        bar.bind("<Double-Button-1>", lambda e: self.toggle_maximize(force=True))
        left.bind("<Double-Button-1>", lambda e: self.toggle_maximize(force=True))
        # ручной drag — страховка: работает, только если нативный не двигает
        # окно сам (сверяем позицию: двигаем лишь пока она стоит на месте).
        # Так ручной и нативный режимы никогда не дерутся.
        self._drag = {"x": 0, "y": 0, "wx": 0, "wy": 0, "on": False}
        bar.bind("<ButtonPress-1>", self._drag_start)
        bar.bind("<B1-Motion>", self._drag_move)
        bar.bind("<ButtonRelease-1>", self._drag_stop)
        left.bind("<ButtonPress-1>", self._drag_start)
        left.bind("<B1-Motion>", self._drag_move)
        left.bind("<ButtonRelease-1>", self._drag_stop)
        # тонкая акцентная линия под шапкой
        self.title_strip = tk.Frame(self.root, bg=ACCENT, height=2)
        self.title_strip.grid(row=1, column=0, columnspan=2, sticky="ew")

    def _drag_start(self, e):
        try:
            rc = win_rect(self.root) or (e.x_root, e.y_root,
                                         e.x_root + 100, e.y_root + 100)
            self._drag.update(x=e.x_root, y=e.y_root,
                              wx=rc[0], wy=rc[1], on=True)
        except Exception:
            pass

    def _drag_move(self, e):
        d = getattr(self, "_drag", None)
        if not d or not d.get("on"):
            return
        try:
            if self.root.state() == "zoomed":
                return
            rc = win_rect(self.root)
            if rc is None:
                return
            if (rc[0], rc[1]) != (d["wx"], d["wy"]):
                # нативный drag уже двигает — стоим в стороне, обновляем базу
                d.update(x=e.x_root, y=e.y_root, wx=rc[0], wy=rc[1])
                return
            win_move(self.root, rc[0] + e.x_root - d["x"],
                     rc[1] + e.y_root - d["y"])
        except Exception:
            pass

    def _drag_stop(self, _e=None):
        try:
            self._drag["on"] = False
        except Exception:
            pass

    def _win_min(self):
        try:
            self.root.iconify()
        except Exception:
            pass

    def _win_close(self):
        if self.engine.running:
            if not self.dlg_ask("Проверка ещё идёт. Завершить и закрыть?"):
                return
            self.engine.cancel()
        log_action("Приложение закрыто пользователем")
        try:
            self.monitor_stop.set()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def toggle_maximize(self, force=False):
        if self._chrome_ok and force:
            return
        try:
            if self.root.state() == "zoomed":
                self.root.state("normal")
                self._maximized = False
            else:
                self.root.state("zoomed")
                self._maximized = True
            try:
                self.btn_max.config(text="❐" if self._maximized else "▢")
            except Exception:
                pass
        except Exception:
            pass

    def _sync_max_glyph(self):
        try:
            if not hasattr(self, "btn_max"):
                return
            zoomed = (self.root.state() == "zoomed")
            if zoomed != self._maximized:
                self._maximized = zoomed
                self.btn_max.config(text="❐" if zoomed else "▢")
        except Exception:
            pass

    # ---------- каркас ----------
    def build_layout(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=1)
        self.build_titlebar()
        body = tk.Frame(self.root, bg=BG)
        body.grid(row=2, column=0, columnspan=2, sticky="nsew")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        # sidebar
        sb = tk.Frame(body, bg=SIDEBAR, width=230)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        logo = tk.Label(sb, text="🔥 Zapret Manager", bg=SIDEBAR, fg=TEXT, font=(FONT, 14, "bold"), anchor="w")
        logo.pack(fill="x", padx=18, pady=(20, 4))
        sub = tk.Label(sb, text="DPI bypass control", bg=SIDEBAR, fg=MUTED, font=(FONT, 9), anchor="w")
        sub.pack(fill="x", padx=18, pady=(0, 16))
        self.nav_btns = {}
        self.nav_strips = {}
        for key, label in [("check", "🔍  Проверка конфигов"),
                           ("domains", "🌐  Домены"),
                           ("logs", "📋  Логи проверок"),
                           ("actions", "📝  Журнал действий"),
                           ("settings", "⚙️  Настройки")]:
            row = tk.Frame(sb, bg=SIDEBAR)
            row.pack(fill="x")
            strip = tk.Frame(row, bg=SIDEBAR, width=4)
            strip.pack(side="left", fill="y")
            self.nav_strips[key] = strip
            b = tk.Button(row, text=label, bg=SIDEBAR, fg=MUTED, font=(FONT, 11),
                          bd=0, anchor="w", padx=14, pady=10, cursor="hand2",
                          activebackground=CARD2, activeforeground=TEXT,
                          command=lambda k=key: self.show_page(k))
            b.pack(side="left", fill="both", expand=True)
            self.nav_btns[key] = b
        sb_bottom = tk.Frame(sb, bg=SIDEBAR)
        sb_bottom.pack(side="bottom", fill="x", padx=18, pady=16)
        self.admin_lbl = tk.Label(sb_bottom, text="", bg=SIDEBAR, fg=MUTED, font=(FONT, 9))
        self.admin_lbl.pack(anchor="w")
        tk.Label(sb_bottom, text=f"v{APP_VERSION} • stdlib • ~20 МБ RAM",
                 bg=SIDEBAR, fg="#6B5A5C", font=(FONT, 8)).pack(anchor="w", pady=(4, 0))

        # main
        main = tk.Frame(body, bg=BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(2, weight=1)
        main.columnconfigure(0, weight=1)
        # header
        hdr = tk.Frame(main, bg=BG)
        hdr.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 10))
        hdr.columnconfigure(0, weight=1)
        self.page_title = tk.Label(hdr, text="Проверка конфигов", bg=BG, fg=TEXT, font=(FONT, 18, "bold"), anchor="w")
        self.page_title.grid(row=0, column=0, sticky="w")
        # разделительная линия — отдельным рядом, чтобы текст не залазил на неё
        hr = tk.Frame(main, bg=BORDER, height=1)
        hr.grid(row=1, column=0, sticky="ew", padx=24)
        # статус-бейдж справа
        pill_wrap = tk.Frame(hdr, bg=BG)
        pill_wrap.grid(row=0, column=1, sticky="e")
        self.status_badge = StatusBadge(pill_wrap)
        self.status_badge.pack(side="left")
        # content
        self.content = tk.Frame(main, bg=BG)
        self.content.grid(row=2, column=0, sticky="nsew", padx=24, pady=14)
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)
        self.pages = {}
        for key in ("check", "domains", "logs", "actions", "settings"):
            f = tk.Frame(self.content, bg=BG)
            f.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = f
        self.build_check_page()
        self.build_domains_page()
        self.build_logs_page()
        self.build_actions_page()
        self.build_settings_page()
        self.show_page("check")

    def show_page(self, key):
        titles = {"check": "Проверка конфигов", "domains": "Домены и списки",
                  "logs": "Логи проверок", "actions": "Журнал действий",
                  "settings": "Настройки"}
        self.page_title.config(text=titles.get(key, key))
        # только видимая страница в layout: ресайз не пересчитывает сотни
        # скрытых виджетов (иначе виснет)
        for k, pg in self.pages.items():
            if k == key:
                pg.grid()
            else:
                pg.grid_remove()
        for k, b in self.nav_btns.items():
            strip = self.nav_strips.get(k)
            if k == key:
                b.config(bg=CARD2, fg=TEXT, font=(FONT, 11, "bold"))
                if strip is not None:
                    strip.config(bg=ACCENT)
            else:
                b.config(bg=SIDEBAR, fg=MUTED, font=(FONT, 11))
                if strip is not None:
                    strip.config(bg=SIDEBAR)
        if key == "logs":
            self.refresh_logs_list()
        if key == "actions":
            self.refresh_actions()
        if key == "domains":
            self.refresh_domains_list()

    # ---------- общие виджеты ----------
    def card(self, parent, **kw):
        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        inner = tk.Frame(outer, bg=CARD, **kw)
        inner.pack(fill="both", expand=True)
        return outer, inner

    def _autowrap(self, lbl, ref, pad=70, minw=320):
        """Подпись переносит текст по ширине окна — ничего не перекрывает.

        С coalescing-задержкой: во время живого ресайза не дёргаем layout
        на каждый пиксель (иначе виснет).
        """
        state = {"after": None}

        def _apply():
            state["after"] = None
            try:
                w = max(minw, ref.winfo_width() - pad)
                if abs(w - int(lbl.cget("wraplength") or 0)) >= 20:
                    lbl.config(wraplength=w)
            except Exception:
                pass

        def _u(_e=None):
            try:
                if state["after"] is not None:
                    self.root.after_cancel(state["after"])
            except Exception:
                pass
            try:
                state["after"] = self.root.after(180, _apply)
            except Exception:
                pass

        ref.bind("<Configure>", _u, add="+")
        self.root.after(400, _apply)

    @staticmethod
    def _tree_wheel(tree):
        """Колесо над таблицей: если строк мало — крутит страницу,
        если таблица переполнена — её саму, а упёршись в край — снова страницу."""
        def _h(e):
            try:
                n = len(tree.get_children())
                try:
                    vis = int(tree.cget("height"))
                except Exception:
                    vis = 10
                if n <= max(1, vis):
                    return None  # влезает — пусть крутит страница
                top, bottom = tree.yview()
                steps = int(-1 * (e.delta / 120)) or (-1 if e.delta > 0 else 1)
                if (steps < 0 and top <= 0.0) or (steps > 0 and bottom >= 1.0):
                    return None  # край таблицы — отдаём странице
                tree.yview_scroll(steps, "units")
                return "break"
            except Exception:
                return None
        tree.bind("<MouseWheel>", _h)

    def notify(self, title, text, color=ACCENT2):
        """Уведомление: Центр Windows (если разрешён), иначе встроенный тост."""
        try:
            if system_toasts_allowed() and notify_windows(title, text):
                return
        except Exception:
            pass
        self.toast(title, text, color)

    def _win_xywh(self):
        """Позиция+размер окна: правда из WinAPI, запасной — winfo."""
        try:
            rc = win_rect(self.root)
            if rc:
                return (rc[0], rc[1], rc[2] - rc[0], rc[3] - rc[1])
        except Exception:
            pass
        try:
            return (self.root.winfo_x(), self.root.winfo_y(),
                    self.root.winfo_width(), self.root.winfo_height())
        except Exception:
            return (100, 100, 1200, 750)

    def toast(self, title, text, color=ACCENT2):
        try:
            t = tk.Toplevel(self.root)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            t.configure(bg=BORDER)
            frm = tk.Frame(t, bg=CARD, padx=16, pady=12)
            frm.pack(fill="both", expand=True, padx=1, pady=1)
            tk.Label(frm, text=title, bg=CARD, fg=color, font=(FONT, 10, "bold"), anchor="w").pack(fill="x")
            tk.Label(frm, text=text, bg=CARD, fg=TEXT, font=(FONT, 10), anchor="w",
                     wraplength=320, justify="left").pack(fill="x", pady=(4, 0))
            self.root.update_idletasks()
            x, y, w, h = self._win_xywh()
            t.geometry(f"360x110+{x + w - 380}+{y + h - 160}")
            t.after(6000, t.destroy)
        except Exception:
            pass

    # ---------- красивые модалки вместо системных messagebox ----------
    def _modal(self, kind, title, text, buttons):
        """Каркас модалки. kind: info|error|ask. buttons: [(label, value, style)].
        Возвращает value нажатой кнопки (Esc = последнее значение).

        Без затемнения всего экрана: только карточка (overrideredirect+topmost
        +grab — проверенная видимая комбинация).
        """
        res = {"v": buttons[-1][1] if buttons else None}
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.attributes("-topmost", True)
        ov.configure(bg=BORDER)
        outer = tk.Frame(ov, bg=BORDER, padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="both", expand=True)
        accent = {"info": ACCENT, "error": RED, "ask": YELLOW}.get(kind, ACCENT)
        tk.Frame(inner, bg=accent, height=4).pack(fill="x")
        body = tk.Frame(inner, bg=CARD)
        body.pack(fill="both", expand=True, padx=22, pady=16)
        glyph, gcol = {"info": ("✓", GREEN), "error": ("✕", RED),
                       "ask": ("?", YELLOW)}.get(kind, ("✓", GREEN))
        top = tk.Frame(body, bg=CARD)
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text=glyph, bg=CARD, fg=gcol, font=(FONT, 16, "bold")).pack(side="left", padx=(0, 10))
        tk.Label(top, text=title, bg=CARD, fg=TEXT, font=(FONT, 12, "bold"),
                 anchor="w").pack(side="left")
        tk.Label(body, text=text, bg=CARD, fg=TEXT, font=(FONT, 10),
                 wraplength=380, justify="left").pack(fill="x", pady=(0, 14))
        brow = tk.Frame(body, bg=CARD)
        brow.pack(fill="x")

        def _done(v):
            res["v"] = v
            try:
                ov.destroy()
            except Exception:
                pass

        for label, val, sty in buttons:
            RButton(brow, text=label, style=sty,
                    command=lambda v=val: _done(v)).pack(side="left", padx=(0, 10))
        ov.bind("<Escape>", lambda _e: _done(res["v"]))
        try:
            self.root.update_idletasks()
            ov.update_idletasks()
            ww, wh = ov.winfo_reqwidth(), ov.winfo_reqheight()
            rx, ry, rw, rh = self._win_xywh()
            ov.geometry(f"+{rx + max(0, (rw - ww) // 2)}+{ry + max(0, (rh - wh) // 2)}")
        except Exception:
            pass
        try:
            ov.grab_set()
            ov.wait_window()
        except Exception:
            try:
                ov.destroy()
            except Exception:
                pass
        return res["v"]

    def dlg_info(self, text, title="Zapret Manager"):
        self._modal("info", title, text, [("Понятно", None, "accent")])

    def dlg_error(self, text, title="Ошибка"):
        self._modal("error", title, text, [("Понятно", None, "accent")])

    def dlg_ask(self, text, title="Подтверждение"):
        return bool(self._modal("ask", title, text,
                                [("Да", True, "accent"), ("Нет", False, "ghost")]))

    def poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_q.get_nowait()
                if kind == "progress":
                    done, total, name, score, res = payload
                    self.update_progress(done, total, name, score, res)
                elif kind == "done":
                    self.on_check_done(payload)
                elif kind == "status":
                    self.set_status(payload[0], payload[1])
                elif kind == "toast":
                    self.notify(payload[0], payload[1], payload[2] if len(payload) > 2 else ACCENT2)
                elif kind == "actions_refresh":
                    self.refresh_actions()
                elif kind == "zapret_update":
                    local, remote = payload
                    self.show_update_banner(local, remote)
                elif kind == "app_update":
                    self.show_app_update_banner(payload)
                elif kind == "vpn":
                    self._show_vpn(payload[0], payload[1])
        except queue.Empty:
            pass
        # даблклик по шапке разворачивает сама Windows — синхронизируем глиф
        try:
            self._sync_max_glyph()
        except Exception:
            pass
        self.root.after(250, self.poll_queue)

    def set_status(self, text, color=MUTED):
        try:
            self.status_badge.set(text, color)
        except Exception:
            pass

    # ================= страница ПРОВЕРКА =================
    def build_check_page(self):
        p = self.pages["check"]
        p.columnconfigure(0, weight=1)
        p.rowconfigure(0, weight=1)
        # вся главная — в скролле: конфиги и пинги листаются без ресайза окна
        scr = ScrollFrame(p, bg=BG)
        scr.grid(row=0, column=0, sticky="nsew")
        inner = scr.inner
        # верхняя карточка управления
        o, top = self.card(inner)
        o.pack(fill="x", pady=(0, 12))
        top.columnconfigure(0, weight=1)
        self.check_desc = tk.Label(top, text="Для каждого конфига меряются пинги Discord и YouTube, ставится оценка. "
                           "Подробный ход проверки — во вкладке «Логи проверок» → «▶ Последний запуск».",
                 bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=700, justify="left")
        self.check_desc.grid(row=0, column=0, columnspan=4, sticky="w", padx=16, pady=(12, 8))
        self._autowrap(self.check_desc, p)
        brow = tk.Frame(top, bg=CARD)
        brow.grid(row=1, column=0, columnspan=4, sticky="w", padx=16, pady=(0, 6))
        self.btn_check_sel = RButton(brow, text="▶ Проверить выбранные", style="accent",
                                     command=self.start_check_selected)
        self.btn_check_all = RButton(brow, text="Проверить все", style="ghost",
                                     command=self.start_check_all)
        self.btn_cancel = RButton(brow, text="⛔ Отмена", style="ghost",
                                  command=self.cancel_check, state="disabled")
        self.btn_check_sel.pack(side="left", padx=(0, 8))
        self.btn_check_all.pack(side="left", padx=(0, 8))
        self.btn_cancel.pack(side="left")
        self.prog = ttk.Progressbar(top, style="Horizontal.TProgressbar", mode="determinate")
        self.prog.grid(row=2, column=0, columnspan=4, sticky="ew", padx=16, pady=(0, 4))
        self.prog_lbl = tk.Label(top, text="Готов к проверке", bg=CARD, fg=MUTED, font=(FONT, 9))
        self.prog_lbl.grid(row=3, column=0, columnspan=4, sticky="w", padx=16, pady=(0, 12))
        # быстрые параметры проверки — на главной, чтобы не лазить в настройки
        qo, quick = self.card(inner)
        qo.pack(fill="x", pady=(0, 12))
        qf = tk.Frame(quick, bg=CARD)
        qf.pack(fill="x", padx=16, pady=10)
        tk.Label(qf, text="Режим:", bg=CARD, fg=MUTED, font=(FONT, 10)).pack(side="left")
        self.q_mode_var = tk.StringVar(value=mode_label(self.cfg.get("check_mode", "quick")))
        DropMenu(qf, variable=self.q_mode_var, values=list(MODE_LABELS.values()),
                 width=26).pack(side="left", padx=(6, 14))
        tk.Label(qf, text="Повторы:", bg=CARD, fg=MUTED, font=(FONT, 10)).pack(side="left")
        self.q_repeat_var = tk.StringVar(value=str(self.cfg.get("check_repeat", 2)))
        DropMenu(qf, variable=self.q_repeat_var, values=["1", "2", "3"],
                 width=8).pack(side="left", padx=(6, 14))
        tk.Label(qf, text="Макс. пинг, мс:", bg=CARD, fg=MUTED, font=(FONT, 10)).pack(side="left")
        self.q_thr_var = tk.StringVar(value=str(self.cfg.get("ping_threshold_ms", 5000)))
        ttk.Entry(qf, textvariable=self.q_thr_var, width=8).pack(side="left", padx=(6, 14))
        RButton(qf, text="💾", style="accent", height=30,
                   command=self.save_quick_settings).pack(side="left")
        # баннер обновления zapret (скрыт, показывается при наличии апдейта)
        self.update_banner_o, ub = self.card(inner)
        self.update_banner_o.pack(fill="x", pady=(0, 12))
        self.update_banner_o.pack_forget()
        self.update_lbl = tk.Label(ub, text="", bg=CARD, fg=YELLOW, font=(FONT, 10, "bold"))
        self.update_lbl.pack(side="left", padx=16, pady=10)
        RButton(ub, text="Открыть релизы", style="accent",
                   command=lambda: webbrowser.open(
                       "https://github.com/Flowseal/zapret-discord-youtube/releases/latest")).pack(
            side="right", padx=(0, 8), pady=8)
        RButton(ub, text="×", style="ghost", height=30,
                   command=lambda: self.update_banner_o.pack_forget()).pack(
            side="right", padx=(0, 16), pady=8)
        # баннер обновления самого приложения (скрыт до проверки версии)
        self.app_banner_o, ab = self.card(inner)
        self.app_banner_o.pack(fill="x", pady=(0, 12))
        self.app_banner_o.pack_forget()
        self.app_update_lbl = tk.Label(ab, text="", bg=CARD, fg=ACCENT2, font=(FONT, 10, "bold"))
        self.app_update_lbl.pack(side="left", padx=16, pady=10)
        RButton(ab, text="⬇ Обновить сейчас", style="accent",
                   command=self.on_app_update_now).pack(
            side="right", padx=(0, 8), pady=8)
        RButton(ab, text="×", style="ghost", height=30,
                   command=lambda: self.app_banner_o.pack_forget()).pack(
            side="right", padx=(0, 16), pady=8)
        # активный конфиг + действия (бывшая вкладка «Выбор конфига»)
        ao, abar = self.card(inner)
        ao.pack(fill="x", pady=(0, 12))
        aleft = tk.Frame(abar, bg=CARD)
        aleft.pack(side="left", fill="both", expand=True, padx=16, pady=8)
        tk.Label(aleft, text="Активный конфиг", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        self.active_lbl = tk.Label(aleft, text="—", bg=CARD, fg=TEXT, font=(FONT, 13, "bold"), anchor="w")
        self.active_lbl.pack(anchor="w")
        self.svc_lbl = tk.Label(aleft, text="", bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w")
        self.svc_lbl.pack(anchor="w")
        self.vpn_lbl = tk.Label(aleft, text="VPN: проверка…", bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w")
        self.vpn_lbl.pack(anchor="w")
        aright = tk.Frame(abar, bg=CARD)
        aright.pack(side="right", padx=16, pady=8)
        RButton(aright, text="✔ Применить выбранный", style="accent",
                   command=self.on_apply_selected).pack(side="left", padx=(0, 8))
        RButton(aright, text="↻ Перезапустить", style="ghost",
                   command=self.on_restart_config).pack(side="left", padx=(0, 8))
        RButton(aright, text="■ Остановить", style="ghost",
                   command=self.on_remove_service).pack(side="left")
        # список конфигов + лог
        mid = tk.Frame(inner, bg=BG)
        mid.pack(fill="x")
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)
        o1, left = self.card(mid)
        o1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tk.Label(left, text="Конфиги (▶ — применить без проверки)", bg=CARD, fg=TEXT, font=(FONT, 12, "bold")).pack(anchor="w", padx=14, pady=(12, 6))
        self.cfg_listbox_frame = tk.Frame(left, bg=CARD)
        self.cfg_listbox_frame.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        self.cfg_vars = {}
        self.cfg_checks = tk.Frame(self.cfg_listbox_frame, bg=CARD)
        self.cfg_checks.pack(fill="both", expand=True)
        btns = tk.Frame(left, bg=CARD)
        btns.pack(fill="x", padx=14, pady=(0, 12))
        RButton(btns, text="Выбрать все", style="ghost",
                   command=lambda: self.set_all_checks(True)).pack(side="left", padx=(0, 6))
        RButton(btns, text="Снять все", style="ghost",
                   command=lambda: self.set_all_checks(False)).pack(side="left")

        o2, right = self.card(mid)
        o2.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        tk.Label(right, text="Пинги Discord / YouTube", bg=CARD, fg=TEXT, font=(FONT, 12, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
        tk.Label(right, text="Не работает • Плохой (2000) • Средний (1000) • Хороший (300) • Отличный (100)",
                 bg=CARD, fg=MUTED, font=(FONT, 8)).pack(anchor="w", padx=14, pady=(0, 6))
        gwrap = tk.Frame(right, bg=CARD)
        gwrap.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        gcols = ("config", "discord", "youtube", "grade")
        self.grade_tree = ttk.Treeview(gwrap, columns=gcols, show="headings", height=12)
        for c, w, t in [("config", 190, "Конфиг"), ("discord", 90, "Discord"),
                        ("youtube", 90, "YouTube"), ("grade", 120, "Оценка")]:
            self.grade_tree.heading(c, text=t)
            self.grade_tree.column(c, width=w, anchor="center" if c != "config" else "w",
                                   stretch=(c == "config"))
        gsb = NiceScroll(gwrap, command=self.grade_tree.yview)
        self.grade_tree.configure(yscrollcommand=gsb.set)
        self.grade_tree.pack(side="left", fill="both", expand=True)
        gsb.pack(side="right", fill="y")
        self.grade_tree.bind("<<TreeviewSelect>>", self._on_grade_select)
        self.grade_tree.bind("<Double-Button-1>", lambda _e: self.on_apply_selected())
        self._tree_wheel(self.grade_tree)
        # детали выбранного конфига
        o3, bot = self.card(inner)
        o3.pack(fill="both", expand=True, pady=(12, 0))
        tk.Label(bot, text="Детали конфига (кликните строку выше)", bg=CARD, fg=TEXT, font=(FONT, 12, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
        dcols = ("target", "ping", "http")
        self.detail_tree = ttk.Treeview(bot, columns=dcols, show="headings", height=7)
        for c, w, t in [("target", 260, "Цель"), ("ping", 130, "Пинг"), ("http", 200, "HTTP")]:
            self.detail_tree.heading(c, text=t)
            self.detail_tree.column(c, width=w, anchor="center" if c != "target" else "w",
                                    stretch=(c == "target"))
        self.detail_tree.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._tree_wheel(self.detail_tree)
        for tag, col in [("g0", RED), ("g1", "#FB923C"), ("g2", YELLOW),
                         ("g3", GREEN), ("g4", "#4ADE80"), ("err", RED)]:
            self.grade_tree.tag_configure(tag, foreground=col)
            self.detail_tree.tag_configure(tag, foreground=col)

    def set_all_checks(self, val):
        for v in self.cfg_vars.values():
            v.set(val)

    def _grade_row(self, bat, v):
        """Строка таблицы пингов: (values, tag). Нефиналисты Ультры — с ≈."""
        if not v.get("started"):
            return (bat, "—", "—", "Не работает"), "g0"
        dm, ym = service_pings(v.get("rows", []))
        text, _color, rank = config_grade(dm, ym)
        if v.get("final", True) is False:
            text += " ≈"
        return (bat, fmt_ping(dm), fmt_ping(ym), text), f"g{rank}"

    def _insert_grade_row(self, bat, v):
        try:
            vals, tag = self._grade_row(bat, v)
            iid = self.grade_tree.insert("", "end", values=vals, tags=(tag,))
            self.grade_tree.see(iid)
            return iid
        except Exception:
            return None

    def _fill_details(self, bat, v):
        try:
            for i in self.detail_tree.get_children():
                self.detail_tree.delete(i)
            if not v or not v.get("rows"):
                self.detail_tree.insert("", "end", values=(bat, "нет данных", ""))
                return
            for r in v["rows"]:
                pm = r.get("ping_ms")
                ping_txt = fmt_ping(pm)
                http = r.get("http_ok")
                http_txt = "—" if http is None else ("OK" if http else "ERR")
                tag = ("err",) if http is False else ()
                self.detail_tree.insert("", "end",
                                        values=(r["name"], ping_txt, http_txt), tags=tag)
        except Exception:
            pass

    def _on_grade_select(self, _e=None):
        try:
            sel = self.grade_tree.selection()
            if not sel:
                return
            bat = self.grade_tree.item(sel[0], "values")[0]
            v = (self.last_results or {}).get(bat)
            if v is not None:
                self._fill_details(bat, v)
        except Exception:
            pass

    def update_progress(self, done, total, name, score, res=None):
        try:
            self.prog["maximum"] = total
            self.prog["value"] = done
            self.prog_lbl.config(text=f"{done}/{total} • {name}")
            if res is not None:
                self._insert_grade_row(name, res)
        except Exception:
            pass

    def selected_configs(self):
        return [k for k, v in self.cfg_vars.items() if v.get()]

    def save_quick_settings(self):
        """Быстрые параметры с главной: режим + повторы + макс. пинг."""
        try:
            rep = min(3, max(1, int(self.q_repeat_var.get())))
            thr = max(300, int(self.q_thr_var.get()))
        except ValueError:
            self.dlg_error("Повторы и пинг — числа")
            return
        self.cfg["check_mode"] = mode_key(self.q_mode_var.get())
        self.cfg["check_repeat"] = rep
        self.cfg["ping_threshold_ms"] = thr
        save_config(self.cfg)
        self.engine.cfg = self.cfg
        log_action(f"Быстрые параметры: режим={self.cfg['check_mode']}, повторы={rep}, макс. пинг={thr} мс")
        self.msg_q.put(("toast", ("Параметры", "Сохранено. Применятся к следующей проверке.", GREEN)))

    def start_check_selected(self):
        sel = self.selected_configs()
        if not sel:
            self.dlg_info("Выберите хотя бы один конфиг")
            return
        self.start_check(sel)

    def start_check_all(self):
        cfgs = list_configs(self.cfg["zapret_root"])
        if not cfgs:
            self.dlg_info("Конфиги не найдены. Проверьте корневую папку zapret в Настройках.")
            return
        self.start_check(cfgs)

    def start_check(self, bat_list):
        if self.engine.running:
            self.dlg_info("Проверка уже идёт")
            return
        run_log_reset(f"Конфигов: {len(bat_list)}")
        if not is_admin():
            run_log_write("⚠ Нет прав администратора — winws может не запуститься. "
                          "Запустите приложение через run.bat (ПКМ → Запуск от администратора).")
        for t in (self.grade_tree, self.detail_tree):
            for i in t.get_children():
                t.delete(i)
        self.btn_check_sel.config(state="disabled")
        self.btn_check_all.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.set_status("проверка…", YELLOW)
        self.prog_lbl.config(text=f"0/{len(bat_list)} • запуск…")
        log_action(f"Старт проверки конфигов: {', '.join(bat_list)}")
        t = threading.Thread(target=self._check_worker, args=(bat_list,), daemon=True)
        t.start()

    def _check_worker(self, bat_list):
        def prog(d, t_, n, s, r=None):
            self.msg_q.put(("progress", (d, t_, n, s, r)))
        def lg(m):
            run_log_write(m)
        res = self.engine.check_configs(bat_list, progress_cb=prog, log_cb=lg, boost=True)
        self.msg_q.put(("done", res))

    def on_check_done(self, res):
        self.last_results = res or {}
        self.btn_check_sel.config(state="normal")
        self.btn_check_all.config(state="normal")
        self.btn_cancel.config(state="disabled")
        if not self.last_results:
            reason = getattr(self.engine, "abort_reason", "")
            if reason == "nonetwork":
                txt, col = "нет сети — проверка прервана", RED
                tip = "Нет сети: DNS не пингуются. Проверьте интернет."
            elif reason == "deadnet":
                txt, col = "сеть упала — проверка прервана", RED
                tip = "Сеть упала посреди проверки: три конфига подряд без пакетов."
            else:
                txt, col = "прервано пользователем", YELLOW
                tip = "Проверка отменена."
            self.set_status(txt, col)
            try:
                self.prog_lbl.config(text=tip)
            except Exception:
                pass
            run_log_write(f"✔ {tip}")
            self.msg_q.put(("toast", ("Проверка", tip, col)))
            self.refresh_active_bar()
            return
        # лучший — по score (как раньше), показываем — пинги и оценку
        best = None
        best_score = -1
        for bat, v in self.last_results.items():
            if v["score"] > best_score:
                best_score = v["score"]
                best = bat
        try:
            for i in self.grade_tree.get_children():
                self.grade_tree.delete(i)
        except Exception:
            pass
        order = sorted(self.last_results.items(), key=lambda x: -x[1]["score"])
        best_iid = None
        for bat, v in order:
            iid = self._insert_grade_row(bat, v)
            if bat == best:
                best_iid = iid
        if best and best_iid:
            try:
                self.grade_tree.selection_set(best_iid)
            except Exception:
                pass
            self._fill_details(best, self.last_results[best])
        # сохранить best
        self.cfg["best_scores"] = {k: v["score"] for k, v in self.last_results.items()}
        save_config(self.cfg)
        self.set_status(f"готово • лучший: {best}", GREEN if best else MUTED)
        self.prog_lbl.config(text=f"{len(self.last_results)} • готово • лучший: {best}")
        run_log_write(f"✔ Готово. Лучший конфиг: {best} (score={best_score})")
        log_action(f"Проверка завершена. Лучший: {best} (score={best_score})")
        self.msg_q.put(("toast", ("Проверка завершена",
                                  f"Лучший конфиг: {best}" + (" (ультра, топ-6 точно)" if self.cfg.get("check_mode") == "ultra" else ""),
                                  GREEN)))
        self.refresh_active_bar()
        if best and not self.cfg.get("active_config"):
            self.cfg["active_config"] = best
            save_config(self.cfg)

    def show_update_banner(self, local, remote):
        try:
            self.update_lbl.config(
                text=f"Доступно обновление zapret: {local or '?'} → {remote}. Рекомендуется обновить.")
            self.update_banner_o.pack(fill="x", pady=(0, 12))
        except Exception:
            pass
        log_action(f"Найдено обновление zapret-discord-youtube: {local} → {remote}", "update")
        self.msg_q.put(("toast", ("Обновление zapret",
                                  f"Вышла версия {remote} (у вас {local or '?'}).", YELLOW)))

    def show_app_update_banner(self, remote):
        try:
            self.app_update_lbl.config(
                text=f"Вышел {APP_NAME} v{remote} (у вас v{APP_VERSION}). Скачайте свежий релиз.")
            self.app_banner_o.pack(fill="x", pady=(0, 12))
        except Exception:
            pass
        log_action(f"Найдено обновление приложения: {APP_VERSION} → {remote}", "update")
        self.msg_q.put(("toast", ("Обновление приложения",
                                  f"Доступен {APP_NAME} v{remote}.", YELLOW)))

    def on_app_update_now(self):
        if self.engine.running:
            self.dlg_info("Дождитесь конца проверки, потом обновитесь")
            return
        if not self.dlg_ask("Скачать и установить обновление?\nПриложение перезапустится, настройки сохранятся."):
            return
        self.set_status("обновление…", YELLOW)
        threading.Thread(target=self._self_update_worker, daemon=True).start()

    def _self_update_worker(self):
        import shutil as _sh
        import tempfile as _tf
        import zipfile as _zf
        try:
            self.msg_q.put(("status", ("скачиваю обновление…", YELLOW)))
            req = urllib.request.Request(
                f"https://api.github.com/repos/{APP_REPO}/releases/latest",
                headers={"User-Agent": "ZapretManager",
                         "Accept": "application/vnd.github+json"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    rel = json.load(r)
            except Exception:
                raise RuntimeError("релизов пока нет")
            zurl = ""
            for a in rel.get("assets", []):
                nm = a.get("name", "")
                if nm.lower().startswith("zapretmanager-v") and nm.lower().endswith(".zip"):
                    zurl = a.get("browser_download_url", "")
                    break
            if not zurl:
                for a in rel.get("assets", []):
                    if a.get("name", "").lower().endswith(".zip"):
                        zurl = a.get("browser_download_url", "")
                        break
            if not zurl:
                raise RuntimeError("в релизе нет zip — открываю страницу")
            tmp = _tf.mkdtemp(prefix="zapretmgr_upd_")
            zpath = os.path.join(tmp, "update.zip")
            rq = urllib.request.Request(zurl, headers={"User-Agent": "ZapretManager"})
            with urllib.request.urlopen(rq, timeout=180) as r, open(zpath, "wb") as f:
                _sh.copyfileobj(r, f, 1024 * 256)
            with _zf.ZipFile(zpath) as z:
                z.extractall(os.path.join(tmp, "u"))
            # корень обновления: ищем app.py (в корне zip или в одной папке)
            uroot = os.path.join(tmp, "u")
            if not os.path.exists(os.path.join(uroot, "app.py")):
                subs = [p for p in os.listdir(uroot)
                        if os.path.isdir(os.path.join(uroot, p))]
                hit = [p for p in subs if os.path.exists(os.path.join(uroot, p, "app.py"))]
                if not hit:
                    raise RuntimeError("в архиве нет app.py")
                uroot = os.path.join(uroot, hit[0])
            # проверка: новый app.py компилируется
            import py_compile as _pc
            _pc.compile(os.path.join(uroot, "app.py"), doraise=True)
            # копируем всё, кроме данных/кэша/рантайма (они машинные и/или заняты)
            skip_dirs = {"data", "__pycache__", ".git"}
            skip_files = {"zapret-manager.exe", "pyvenv.cfg"}
            n = 0
            for dirpath, dirnames, filenames in os.walk(uroot):
                dirnames[:] = [d for d in dirnames if d not in skip_dirs]
                for fn in filenames:
                    if fn in skip_files or fn.endswith((".dll", ".pyc")):
                        continue
                    src = os.path.join(dirpath, fn)
                    relp = os.path.relpath(src, uroot)
                    dst = os.path.join(BASE_DIR, relp)
                    os.makedirs(os.path.dirname(dst) or BASE_DIR, exist_ok=True)
                    _sh.copy2(src, dst)
                    n += 1
            _sh.rmtree(tmp, ignore_errors=True)
            save_config(self.cfg)
            log_action(f"Приложение обновлено ({n} файлов), перезапуск")
            self.msg_q.put(("toast", ("Обновление установлено", "Перезапускаюсь…", GREEN)))
            time.sleep(1)
            self.root.after(0, self.restart_app)
        except Exception as e:
            log_action(f"Автообновление не удалось: {e}", "error")
            self.msg_q.put(("toast", ("Обновление", f"Не удалось: {e}", RED)))
            try:
                webbrowser.open(f"https://github.com/{APP_REPO}/releases/latest")
            except Exception:
                pass
            self.msg_q.put(("status", ("готово", MUTED)))

    def check_app_updates(self):
        threading.Thread(target=self._app_update_worker, daemon=True).start()

    def _app_update_worker(self):
        time.sleep(5)  # дать UI отрисоваться
        try:
            url = (f"https://raw.githubusercontent.com/{APP_REPO}/main/version.txt")
            req = urllib.request.Request(url, headers={"User-Agent": "ZapretManager",
                                                       "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=8) as r:
                remote = r.read().decode("utf-8", "ignore").strip().split()[0]
            if remote and self._ver_newer(remote, APP_VERSION):
                self.msg_q.put(("app_update", remote))
        except Exception as e:
            log_action(f"Проверка обновлений приложения не удалась: {e}", "update")

    def check_zapret_updates(self):
        threading.Thread(target=self._update_check_worker, daemon=True).start()

    def _update_check_worker(self):
        time.sleep(3)  # дать UI отрисоваться
        try:
            local = ""
            sb = os.path.join(self.cfg.get("zapret_root", ""), "service.bat")
            if os.path.exists(sb):
                with open(sb, "r", encoding="utf-8", errors="ignore") as f:
                    m = re.search(r'set\s+"LOCAL_VERSION=([^"]+)"', f.read())
                    if m:
                        local = m.group(1).strip()
            url = ("https://raw.githubusercontent.com/Flowseal/"
                   "zapret-discord-youtube/main/.service/version.txt")
            req = urllib.request.Request(url, headers={"User-Agent": "ZapretManager",
                                                       "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=7) as r:
                remote = r.read().decode("utf-8", "ignore").strip().split()[0]
            if remote and local and remote != local and self._ver_newer(remote, local):
                self.msg_q.put(("zapret_update", (local, remote)))
            elif remote and not local:
                self.msg_q.put(("zapret_update", ("?", remote)))
        except Exception as e:
            log_action(f"Проверка обновлений zapret не удалась: {e}", "update")

    @staticmethod
    def _ver_newer(remote, local):
        def parts(v):
            return [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v)[:4]]
        try:
            return parts(remote) > parts(local)
        except Exception:
            return remote != local

    def cancel_check(self):
        self.engine.cancel()
        run_log_write("⛔ Отмена запрошена…")
        try:
            self.prog_lbl.config(text="отмена…")
        except Exception:
            pass

    # ================= активный конфиг (на главной) =================
    def refresh_active_bar(self):
        try:
            st = service_status()
            active = self.cfg.get("active_config", "") or st.get("strategy", "")
            self.active_lbl.config(text=active or "не выбран")
            z = st["zapret"]
            if z == "RUNNING":
                col = GREEN
                txt = f"Служба: RUNNING   •   WinDivert: {st['windivert']}   •   winws: {'да' if st['winws'] else 'нет'}"
                pill, pcol = "обход: активен (служба)", GREEN
            elif st["winws"]:
                # конфиг запущен разово, без службы — это тоже «работает»
                col = GREEN
                txt = f"Обход активен (без службы, winws запущен)   •   WinDivert: {st['windivert']}"
                pill, pcol = "обход: активен", GREEN
            elif z == "STOPPED":
                col, txt, pill, pcol = (YELLOW, f"Служба: STOPPED   •   winws: нет",
                                        "zapret: STOPPED", YELLOW)
            else:
                col, txt, pill, pcol = (RED, f"Служба: {z}   •   winws: нет",
                                        f"zapret: {z}", RED)
            self.svc_lbl.config(text=txt, fg=col)
            self.set_status(pill, pcol)
        except Exception:
            pass
        self.refresh_vpn_async()

    def refresh_vpn_async(self):
        """VPN-статус в фоне (подпроцесс ~0.5с), кэш 60с."""
        try:
            now = time.time()
            ts, _, _ = getattr(self, "_vpn_cache", (0, False, []))
            if now - ts < 60:
                cached = self._vpn_cache
                self.msg_q.put(("vpn", (cached[1], cached[2])))
                return
            if getattr(self, "_vpn_busy", False):
                return
            self._vpn_busy = True
        except Exception:
            return

        def _w():
            try:
                active, names = vpn_status()
                self._vpn_cache = (time.time(), active, names)
                self.msg_q.put(("vpn", (active, names)))
            except Exception:
                pass
            finally:
                self._vpn_busy = False

        threading.Thread(target=_w, daemon=True).start()

    def _show_vpn(self, active, names):
        try:
            if active:
                self.vpn_lbl.config(
                    text=f"VPN: ВКЛ ({', '.join(names)[:60]}) — возможны ошибки!",
                    fg=YELLOW)
            else:
                self.vpn_lbl.config(text="VPN: выкл", fg=MUTED)
        except Exception:
            pass

    def selected_grade_bat(self):
        try:
            sel = self.grade_tree.selection()
            if sel:
                return self.grade_tree.item(sel[0], "values")[0]
        except Exception:
            pass
        return ""

    def on_apply_selected(self):
        bat = self.selected_grade_bat()
        if not bat:
            self.dlg_info("Выберите конфиг в таблице пингов (клик по строке)")
            return
        self.on_apply_config(bat)

    def on_restart_config(self):
        active = self.cfg.get("active_config", "")
        st = service_status()
        if st["zapret"] in ("RUNNING", "STOPPED"):
            if not self.dlg_ask("Перезапустить службу zapret (активный конфиг)?"):
                return
            self.set_status("перезапуск…", YELLOW)
            threading.Thread(target=self._restart_worker, daemon=True).start()
        elif active:
            if not self.dlg_ask(f"Перезапустить {active} (без службы)?"):
                return
            threading.Thread(target=self._restart_standalone_worker,
                             args=(active,), daemon=True).start()
        else:
            self.dlg_info("Нет активного конфига для перезапуска")

    def _restart_worker(self):
        cmds = 'net stop zapret >nul 2>&1 & net start zapret >nul 2>&1'
        if not is_admin():
            ok = elevated_cmd(cmds)
            msg = "Запрос на перезапуск отправлен (UAC)." if ok else "Нужны права администратора"
            self.msg_q.put(("toast", ("Перезапуск", msg, GREEN if ok else RED)))
            log_action(f"Перезапуск службы: {msg}", "apply")
        else:
            run_cmd(cmds, timeout=30, shell=True)
            time.sleep(2)
            st = service_status()
            msg = f"Служба zapret: {st['zapret']}"
            self.msg_q.put(("toast", ("Перезапуск", msg, GREEN if st["zapret"] == "RUNNING" else RED)))
            log_action(f"Перезапуск службы: {msg}", "apply")
        self.root.after(500, self.refresh_active_bar)
        self.msg_q.put(("actions_refresh", None))

    def _restart_standalone_worker(self, bat):
        stop_winws()
        time.sleep(1)
        ok = start_winws_hidden(self.cfg["zapret_root"], bat)
        time.sleep(2)
        running = winws_running()
        msg = f"{bat}: {'запущен' if running else 'не запустился'}"
        self.msg_q.put(("toast", ("Перезапуск", msg, GREEN if running else RED)))
        log_action(f"Перезапуск конфига без службы: {msg}", "apply")
        self.root.after(500, self.refresh_active_bar)
        self.msg_q.put(("actions_refresh", None))

    def on_apply_config(self, bat):
        mode = self.ask_apply_mode(bat)
        if mode == "service":
            self.set_status("установка службы…", YELLOW)
            threading.Thread(target=self._apply_worker, args=(bat,), daemon=True).start()
        elif mode == "once":
            self.set_status("запуск без автозагрузки…", YELLOW)
            threading.Thread(target=self._once_worker, args=(bat,), daemon=True).start()

    def ask_apply_mode(self, bat):
        """Диалог: в автозагрузку (служба) или разово (без службы)."""
        res = {"mode": None}
        d = tk.Toplevel(self.root)
        d.title("Применение конфига")
        d.configure(bg=CARD)
        d.resizable(False, False)
        try:
            d.transient(self.root)
            d.grab_set()
        except Exception:
            pass
        tk.Label(d, text=bat, bg=CARD, fg=TEXT, font=(FONT, 12, "bold"),
                 anchor="w").pack(fill="x", padx=18, pady=(16, 4))
        tk.Label(d, text="Как использовать конфиг?",
                 bg=CARD, fg=MUTED, font=(FONT, 10), anchor="w").pack(fill="x", padx=18)
        var = tk.StringVar(value="service")
        tk.Radiobutton(d, text="Служба Windows + автозагрузка (рекомендуется)",
                       variable=var, value="service", bg=CARD, fg=TEXT,
                       font=(FONT, 10), anchor="w", activebackground=CARD,
                       selectcolor=ACCENT).pack(fill="x", padx=18, pady=(8, 0))
        tk.Radiobutton(d, text="Запустить разово, без автозагрузки",
                       variable=var, value="once", bg=CARD, fg=TEXT,
                       font=(FONT, 10), anchor="w", activebackground=CARD,
                       selectcolor=ACCENT).pack(fill="x", padx=18)
        btns = tk.Frame(d, bg=CARD)
        btns.pack(fill="x", padx=18, pady=14)

        def _ok():
            res["mode"] = var.get()
            d.destroy()

        RButton(btns, text="OK", style="accent", command=_ok).pack(side="left", padx=(0, 8))
        RButton(btns, text="Отмена", style="ghost", command=d.destroy).pack(side="left")
        try:
            self.root.update_idletasks()
            rx, ry, rw, rh = self._win_xywh()
            x = rx + (rw - 420) // 2
            y = ry + (rh - 220) // 2
            d.geometry(f"420x220+{x}+{y}")
        except Exception:
            pass
        try:
            self.root.wait_window(d)
        except Exception:
            pass
        return res["mode"]

    def _once_worker(self, bat):
        # разовый запуск: убрать службу (иначе конфликт за WinDivert), поднять bat
        st = service_status()
        if st["zapret"] in ("RUNNING", "STOPPED"):
            remove_service()
            time.sleep(1)
        stop_winws()
        time.sleep(0.5)
        ok = start_winws_hidden(self.cfg["zapret_root"], bat)
        time.sleep(2)
        running = winws_running()
        if ok and running:
            self.cfg["active_config"] = bat
            save_config(self.cfg)
            msg = f"{bat} запущен (без автозагрузки)"
            log_action(f"Вручную запущен конфиг без службы: {bat}", "apply")
        else:
            msg = f"{bat}: не запустился (нужны права администратора?)"
            log_action(f"Ошибка разового запуска {bat}", "error")
        self.msg_q.put(("toast", ("Разовый запуск", msg, GREEN if ok and running else RED)))
        self.root.after(500, self.refresh_active_bar)
        self.msg_q.put(("actions_refresh", None))

    def _apply_worker(self, bat):
        ok, msg = install_service(self.cfg["zapret_root"], bat)
        if ok:
            self.cfg["active_config"] = bat
            save_config(self.cfg)
            log_action(f"Вручную применён конфиг {bat}: {msg}", "apply")
        else:
            log_action(f"Ошибка установки {bat}: {msg}", "error")
        self.msg_q.put(("toast", ("Применение конфига", f"{bat}: {msg}", GREEN if ok else RED)))
        self.msg_q.put(("status", (f"zapret: {service_status()['zapret']}", GREEN if ok else RED)))
        self.root.after(500, self.refresh_active_bar)
        self.msg_q.put(("actions_refresh", None))

    def on_remove_service(self):
        if self.dlg_ask("Удалить службу zapret и остановить обход?"):
            threading.Thread(target=self._remove_worker, daemon=True).start()

    def _remove_worker(self):
        ok, msg = remove_service()
        log_action(f"Удаление службы: {msg}", "apply")
        self.msg_q.put(("toast", ("Служба", msg, GREEN if ok else RED)))
        self.root.after(500, self.refresh_active_bar)
        self.msg_q.put(("actions_refresh", None))

    # ================= страница ДОМЕНЫ =================
    def build_domains_page(self):
        p = self.pages["domains"]
        p.rowconfigure(1, weight=1)
        p.columnconfigure(0, weight=1)
        o, top = self.card(p)
        o.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        row = tk.Frame(top, bg=CARD)
        row.pack(fill="x", padx=16, pady=12)
        self.dom_hint = tk.Label(row, text="Списки из папки lists/",
                                 bg=CARD, fg=MUTED, font=(FONT, 9))
        self.dom_hint.pack(side="left")
        RButton(row, text="🔄 Обновить", style="ghost",
                   command=self.refresh_domains_list).pack(side="right", padx=(6, 0))
        RButton(row, text="💾 Сохранить", style="accent",
                   command=self.save_domain_file).pack(side="right")
        mid = tk.Frame(p, bg=BG)
        mid.grid(row=1, column=0, sticky="nsew")
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=3)
        mid.rowconfigure(0, weight=1)
        o1, l = self.card(mid)
        o1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tk.Label(l, text="Файлы", bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        self.dom_list = tk.Listbox(l, bg=CARD2, fg=TEXT, font=(FONT, 9),
                                   bd=0, highlightthickness=0, selectbackground=ACCENT,
                                   selectforeground="white")
        self.dom_list.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.dom_list.bind("<<ListboxSelect>>", lambda _e: self.show_domain_file())
        o2, r = self.card(mid)
        o2.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.dom_title = tk.Label(r, text="Содержимое", bg=CARD, fg=TEXT, font=(FONT, 11, "bold"))
        self.dom_title.pack(anchor="w", padx=12, pady=(10, 4))
        self.dom_text = tk.Text(r, bg=CARD2, fg=TEXT, font=(MONO, 9), bd=0, wrap="none", padx=10, pady=10, insertbackground=TEXT, selectbackground=ACCENT, selectforeground="white")
        self.dom_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._dom_current = ""

    def _lists_dir(self):
        d = os.path.join(self.cfg.get("zapret_root", ""), "lists")
        return d if os.path.isdir(d) else ""

    def refresh_domains_list(self):
        try:
            self.dom_list.delete(0, "end")
            d = self._lists_dir()
            if not d:
                self.dom_hint.config(text="Папка lists/ не найдена — проверьте корневую папку в Настройках")
                return
            files = sorted(glob.glob(os.path.join(d, "*.txt")))
            self.dom_hint.config(text=f"Списки из {d} — изменения вступят в силу после перезапуска zapret")
            for fp in files:
                self.dom_list.insert("end", os.path.basename(fp))
            if files:
                self.dom_list.select_set(0)
                self.show_domain_file()
        except Exception:
            pass

    def _dom_path(self):
        try:
            sel = self.dom_list.curselection()
            if not sel:
                return ""
            return os.path.join(self._lists_dir(), self.dom_list.get(sel[0]))
        except Exception:
            return ""

    def show_domain_file(self):
        try:
            fp = self._dom_path()
            if not fp:
                return
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            self._dom_current = fp
            self.dom_title.config(
                text=f"{os.path.basename(fp)}  ({len(content.splitlines())} строк, {len(content)} симв.)")
            self.dom_text.delete("1.0", "end")
            self.dom_text.insert("end", content)
        except Exception as e:
            self.dlg_error(f"Не удалось прочитать файл: {e}")

    def save_domain_file(self):
        fp = self._dom_current or self._dom_path()
        if not fp:
            self.dlg_info("Выберите файл слева")
            return
        try:
            if os.path.exists(fp):
                shutil.copy2(fp, fp + ".bak")
            with open(fp, "w", encoding="utf-8") as f:
                f.write(self.dom_text.get("1.0", "end-1c").replace("\n", "\n"))
            try:
                self.dom_title.config(
                    text=f"{os.path.basename(fp)}  (сохранено, бэкап: .bak)")
            except Exception:
                pass
            log_action(f"Отредактирован список {os.path.basename(fp)} (бэкап .bak)", "lists")
            self.dlg_info("Сохранено (старая копия — в .bak).\nПерезапустите конфиг для применения.")
        except Exception as e:
            self.dlg_error(f"Не удалось сохранить: {e}")

    # ================= страница ЛОГИ =================
    def build_logs_page(self):
        p = self.pages["logs"]
        p.rowconfigure(1, weight=1)
        p.columnconfigure(0, weight=1)
        o, top = self.card(p)
        o.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        row = tk.Frame(top, bg=CARD)
        row.pack(fill="x", padx=16, pady=12)
        tk.Label(row, text="История проверок сохраняется в data/checks/*.json",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left")
        RButton(row, text="🔄 Обновить", style="ghost",
                   command=self.refresh_logs_list).pack(side="right", padx=(6, 0))
        RButton(row, text="🗑 Удалить", style="ghost",
                   command=self.delete_selected_log).pack(side="right", padx=(6, 0))
        RButton(row, text="🧹 Все", style="ghost",
                   command=self.clear_all_logs).pack(side="right", padx=(6, 0))
        RButton(row, text="📂 Открыть папку", style="ghost",
                   command=self.open_checks_folder).pack(side="right")
        mid = tk.Frame(p, bg=BG)
        mid.grid(row=1, column=0, sticky="nsew")
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=2)
        mid.rowconfigure(0, weight=1)
        o1, l = self.card(mid)
        o1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tk.Label(l, text="Файлы", bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        self.logs_list = tk.Listbox(l, bg=CARD2, fg=TEXT, font=(FONT, 9),
                                    bd=0, highlightthickness=0, selectbackground=ACCENT,
                                    selectforeground="white")
        self.logs_list.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.logs_list.bind("<<ListboxSelect>>", lambda e: self.show_log_file())
        o2, r = self.card(mid)
        o2.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        tk.Label(r, text="Содержимое", bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        self.log_view = tk.Text(r, bg=CARD2, fg="#E3CDCD", font=(MONO, 9), bd=0, wrap="word", padx=10, pady=10, insertbackground=TEXT, selectbackground=ACCENT, selectforeground="white")
        self.log_view.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def refresh_logs_list(self):
        try:
            self.logs_list.delete(0, "end")
            self.logs_list.insert("end", LAST_RUN_LABEL)
            files = sorted(glob.glob(os.path.join(CHECKS_DIR, "*.json")), reverse=True)
            for fp in files:
                self.logs_list.insert("end", os.path.basename(fp))
            self.logs_list.select_set(0)
            self.show_log_file()
        except Exception:
            pass

    def show_log_file(self):
        try:
            sel = self.logs_list.curselection()
            if not sel:
                return
            name = self.logs_list.get(sel[0])
            self.log_view.delete("1.0", "end")
            if name == LAST_RUN_LABEL:
                # подробный ход последней проверки (бывший «Ход проверки»)
                if os.path.exists(LAST_RUN_LOG):
                    with open(LAST_RUN_LOG, "r", encoding="utf-8", errors="ignore") as f:
                        self.log_view.insert("end", f.read() or "Пока пусто — запустите проверку.")
                else:
                    self.log_view.insert("end", "Пока пусто — запустите проверку.")
                self.log_view.see("end")
                return
            with open(os.path.join(CHECKS_DIR, name), "r", encoding="utf-8") as f:
                data = json.load(f)
            self.log_view.insert("end", f"Время: {data.get('time','')}\n")
            if data.get("active"):
                self.log_view.insert("end", f"Используемый конфиг: {data['active']}\n")
            if data.get("mode") == "ultra":
                self.log_view.insert("end", "Режим УЛЬТРА: точные замеры только у финалистов, остальные ≈\n")
            self.log_view.insert("end", "\n")
            for cfg, s in data.get("summary", {}).items():
                dm = s.get("discord_ms")
                ym = s.get("youtube_ms")
                approx = "" if s.get("final", True) else "≈"
                self.log_view.insert(
                    "end", f"{cfg}: Discord={fmt_ping(dm)} YouTube={fmt_ping(ym)} "
                           f"[{s.get('grade', '?')}{approx}]  (HTTP OK={s['ok']} ERR={s['fail']})\n")
        except Exception as e:
            pass

    def open_checks_folder(self):
        try:
            os.startfile(CHECKS_DIR)
        except Exception:
            pass

    def _selected_log_name(self):
        try:
            sel = self.logs_list.curselection()
            if not sel:
                return ""
            return self.logs_list.get(sel[0])
        except Exception:
            return ""

    def delete_selected_log(self):
        name = self._selected_log_name()
        if not name:
            self.dlg_info("Выберите лог слева")
            return
        if name == LAST_RUN_LABEL:
            if not self.dlg_ask("Очистить «Последний запуск»?"):
                return
            try:
                open(LAST_RUN_LOG, "w", encoding="utf-8").close()
            except Exception:
                pass
            log_action("Очищен лог последнего запуска")
            self.refresh_logs_list()
            return
        if not self.dlg_ask(f"Удалить {name}?"):
            return
        try:
            os.remove(os.path.join(CHECKS_DIR, name))
            log_action(f"Удалён лог проверки: {name}")
        except Exception as e:
            self.dlg_error(f"Не удалось удалить: {e}")
        self.refresh_logs_list()

    def clear_all_logs(self):
        if not self.dlg_ask("Удалить ВСЕ логи проверок?"):
            return
        n = 0
        try:
            for fp in glob.glob(os.path.join(CHECKS_DIR, "*.json")):
                try:
                    os.remove(fp)
                    n += 1
                except Exception:
                    pass
            try:
                open(LAST_RUN_LOG, "w", encoding="utf-8").close()
            except Exception:
                pass
            log_action(f"Очищены все логи проверок ({n} файлов)")
        except Exception:
            pass
        self.refresh_logs_list()

    # ================= страница ЖУРНАЛ =================
    def build_actions_page(self):
        p = self.pages["actions"]
        p.rowconfigure(1, weight=1)
        p.columnconfigure(0, weight=1)
        o, top = self.card(p)
        o.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        row = tk.Frame(top, bg=CARD)
        row.pack(fill="x", padx=16, pady=12)
        tk.Label(row, text="Здесь фиксируются все автопереключения, ручные применения и изменения настроек.",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left")
        RButton(row, text="🔄 Обновить", style="ghost",
                   command=self.refresh_actions).pack(side="right", padx=(6, 0))
        RButton(row, text="🧹 Очистить", style="ghost",
                   command=self.clear_actions).pack(side="right")
        o2, wrap = self.card(p)
        o2.grid(row=1, column=0, sticky="nsew")
        self.actions_view = tk.Text(wrap, bg=CARD2, fg="#E3CDCD", font=(MONO, 9), bd=0, wrap="word", padx=10, pady=10, insertbackground=TEXT, selectbackground=ACCENT, selectforeground="white")
        self.actions_view.pack(fill="both", expand=True, padx=14, pady=14)

    def refresh_actions(self):
        try:
            self.actions_view.delete("1.0", "end")
            lines = read_actions(500)
            if not lines:
                self.actions_view.insert("end", "Пока пусто. Действия появятся после проверок и переключений.\n")
            else:
                for ln in lines:
                    self.actions_view.insert("end", ln)
                self.actions_view.see("end")
        except Exception:
            pass

    def clear_actions(self):
        try:
            open(ACTIONS_PATH, "w", encoding="utf-8").close()
            self.refresh_actions()
        except Exception:
            pass

    # ================= страница НАСТРОЙКИ =================
    SET_SECTIONS = [
        ("folder", "📁  Папка"),
        ("speed", "🚀  Проверка"),
        ("monitor", "📡  Мониторинг"),
        ("appear", "🎨  Оформление"),
        ("targets", "🎯  Цели"),
        ("app", "ℹ️  Приложение"),
    ]

    def build_settings_page(self):
        p = self.pages["settings"]
        p.columnconfigure(1, weight=1)
        p.rowconfigure(0, weight=1)
        nav = tk.Frame(p, bg=CARD, width=170)
        nav.grid(row=0, column=0, sticky="nsew")
        nav.grid_propagate(False)
        tk.Label(nav, text="Разделы", bg=CARD, fg=MUTED, font=(FONT, 9),
                 anchor="w").pack(fill="x", padx=14, pady=(12, 6))
        self.set_nav_btns = {}
        for key, label in self.SET_SECTIONS:
            b = tk.Button(nav, text=label, bg=CARD, fg=MUTED, font=(FONT, 10),
                          bd=0, anchor="w", padx=14, pady=9, cursor="hand2",
                          activebackground=CARD2, activeforeground=TEXT,
                          command=lambda k=key: self.show_settings_section(k))
            b.pack(fill="x")
            self.set_nav_btns[key] = b
        wrap = tk.Frame(p, bg=BG)
        wrap.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.set_pages = {}
        for key, _label in self.SET_SECTIONS:
            f = tk.Frame(wrap, bg=BG)
            f.grid(row=0, column=0, sticky="nsew")
            self.set_pages[key] = f
        self._build_set_folder()
        self._build_set_speed()
        self._build_set_monitor()
        self._build_set_appear()
        self._build_set_targets()
        self._build_set_app()
        self.show_settings_section("folder")

    def show_settings_section(self, key):
        for k, pg in self.set_pages.items():
            if k == key:
                pg.grid()
            else:
                pg.grid_remove()
        for k, b in self.set_nav_btns.items():
            if k == key:
                b.config(bg=CARD2, fg=TEXT, font=(FONT, 10, "bold"))
            else:
                b.config(bg=CARD, fg=MUTED, font=(FONT, 10))

    def _set_scroll(self, parent):
        o, box = self.card(parent)
        o.pack(fill="both", expand=True)
        scr = ScrollFrame(box, bg=CARD)
        scr.pack(fill="both", expand=True, padx=12, pady=12)
        return scr.inner

    def _build_set_folder(self):
        inner = self._set_scroll(self.set_pages["folder"])
        tk.Label(inner, text="Корневая папка zapret", bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        tk.Label(inner, text="Папка, где лежат general*.bat, service.bat и каталоги bin/ и lists/.",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w", padx=8)
        r1 = tk.Frame(inner, bg=CARD)
        r1.pack(fill="x", padx=8, pady=8)
        self.root_var = tk.StringVar(value=self.cfg.get("zapret_root", ""))
        ttk.Entry(r1, textvariable=self.root_var, width=60).pack(side="left", fill="x", expand=True, padx=(0, 8))
        RButton(r1, text="📁 Обзор…", style="ghost", command=self.browse_root).pack(side="left")
        RButton(r1, text="💾 Сохранить", style="accent", command=self.save_root).pack(side="left", padx=(8, 0))
        r2 = tk.Frame(inner, bg=CARD)
        r2.pack(fill="x", padx=8, pady=(4, 8))
        tk.Label(r2, text="Сломалась папка? Скачает свежий релиз с GitHub Flowseal, ваши списки сохранит.",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left")
        RButton(r2, text="🔄 Переустановить Zapret", style="ghost",
                   command=self.on_reinstall_zapret).pack(side="right")

    def _build_set_speed(self):
        inner = self._set_scroll(self.set_pages["speed"])
        tk.Label(inner, text="Скорость проверки", bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        self.speed_desc = tk.Label(inner, text="Быстрый: только Discord + YouTube + Google, параллельно. Ручная — ТУРБО (потоки+приоритет), авто — ЭКО.\n"
                             "УЛЬТРА — турнир: дешёвый отсев всех по 2 целям, затем точный замер топ-6.\n"
                             "Все сразу нельзя: конфиги делят один WinDivert и испортят замер друг другу.\n"
                             "Пинги отсева — ПРИБЛИЗИТЕЛЬНЫЕ (≈), точные — только у финалистов.",
                 bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=650, justify="left")
        self.speed_desc.pack(anchor="w", padx=8)
        self._autowrap(self.speed_desc, self.set_pages["speed"], pad=260)
        spd = tk.Frame(inner, bg=CARD)
        spd.pack(fill="x", padx=8, pady=8)
        tk.Label(spd, text="Режим, повторы и макс. пинг — на главной (карточка под кнопками проверки).",
                 bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=600, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=4)
        tk.Label(spd, text="Параллельных потоков (турбо добавит сам):", bg=CARD, fg=MUTED, font=(FONT, 10)).grid(row=1, column=0, sticky="w", pady=4)
        self.workers_var = tk.StringVar(value=str(self.cfg.get("check_workers", 8)))
        DropMenu(spd, variable=self.workers_var,
                 values=[str(n) for n in (4, 6, 8, 10, 12, 16)],
                 width=8).grid(row=1, column=1, padx=8, sticky="w")
        RButton(spd, text="💾 Сохранить потоки", style="ghost",
                   command=self.save_speed).grid(row=2, column=0, pady=10, sticky="w")

    def _build_set_monitor(self):
        inner = self._set_scroll(self.set_pages["monitor"])
        tk.Label(inner, text="Мониторинг и автопереключение", bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        self.mon_var = tk.BooleanVar(value=bool(self.cfg.get("monitor_enabled", True)))
        tk.Checkbutton(inner, text="Следить за пингом и DPI, при проблемах — переключать на рабочий конфиг",
                       variable=self.mon_var, bg=CARD, fg=TEXT, font=(FONT, 10),
                       activebackground=CARD, selectcolor=CARD2, wraplength=600, justify="left",
                       command=self.on_monitor_toggle).pack(anchor="w", padx=8)
        grid = tk.Frame(inner, bg=CARD)
        grid.pack(fill="x", padx=8, pady=8)
        tk.Label(grid, text="Интервал проверки (мин):", bg=CARD, fg=MUTED, font=(FONT, 10)).grid(row=0, column=0, sticky="w", pady=4)
        self.interval_var = tk.StringVar(value=str(self.cfg.get("monitor_interval_min", 3)))
        ttk.Entry(grid, textvariable=self.interval_var, width=8).grid(row=0, column=1, padx=8)
        tk.Label(grid, text="Макс. пинг — на главной (общий для проверок и мониторинга).",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).grid(row=1, column=0, columnspan=2, sticky="w", pady=4)
        tk.Label(grid, text="Таймаут HTTP (с):", bg=CARD, fg=MUTED, font=(FONT, 10)).grid(row=2, column=0, sticky="w", pady=4)
        self.timeout_var = tk.StringVar(value=str(self.cfg.get("check_timeout_s", 5)))
        ttk.Entry(grid, textvariable=self.timeout_var, width=8).grid(row=2, column=1, padx=8)
        RButton(grid, text="💾 Сохранить мониторинг", style="ghost",
                   command=self.save_monitor).grid(row=3, column=0, pady=10, sticky="w")

    def _build_set_appear(self):
        inner = self._set_scroll(self.set_pages["appear"])
        tk.Label(inner, text="Оформление", bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        th = tk.Frame(inner, bg=CARD)
        th.pack(fill="x", padx=8, pady=4)
        tk.Label(th, text="Цветовая тема (применяется сразу):", bg=CARD, fg=MUTED, font=(FONT, 10)).grid(row=0, column=0, sticky="w", pady=4)
        self.theme_var = tk.StringVar(value=self.cfg.get("theme", "Алый"))
        trow = tk.Frame(th, bg=CARD)
        trow.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 4))
        self.theme_btns = {}
        for _name in THEMES:
            _pal = THEMES[_name]
            _b = tk.Button(trow, text=_name, bg=_pal["ACCENT"], fg="white",
                           font=(FONT, 10, "bold"), bd=0, padx=12, pady=6,
                           cursor="hand2", activebackground=_pal["ACCENT_HOVER"],
                           activeforeground="white",
                           command=lambda n=_name: self.pick_theme(n))
            _b.pack(side="left", padx=(0, 8))
            self.theme_btns[_name] = _b
        self._mark_theme_buttons()
        tk.Label(th, text="Верхняя шторка красится в цвета темы автоматически.",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)
        tk.Label(inner, text="Шрифт и масштаб", bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w", padx=8, pady=(10, 2))
        fnt = tk.Frame(inner, bg=CARD)
        fnt.pack(fill="x", padx=8, pady=4)
        tk.Label(fnt, text="Шрифт интерфейса (сохраняется сразу):", bg=CARD, fg=MUTED, font=(FONT, 10)).grid(row=0, column=0, sticky="w", pady=4)
        self.font_var = tk.StringVar(value=self.cfg.get("ui_font", FONT))
        self.font_box = DropMenu(fnt, variable=self.font_var, values=[],
                                 width=24, command=self.on_font_changed)
        self.font_box.grid(row=0, column=1, padx=8, sticky="w")
        tk.Label(fnt, text="Масштаб интерфейса (сохраняется сразу):", bg=CARD, fg=MUTED, font=(FONT, 10)).grid(row=1, column=0, sticky="w", pady=4)
        self.scale_var = tk.StringVar(value=self.cfg.get("ui_scale", "Обычный"))
        self.scale_box = DropMenu(fnt, variable=self.scale_var, values=list(UI_SCALES.keys()),
                                  width=24, command=self.on_font_changed)
        self.scale_box.grid(row=1, column=1, padx=8, sticky="w")
        tk.Label(fnt, text="Моноширинный, логи (сохраняется сразу):", bg=CARD, fg=MUTED, font=(FONT, 10)).grid(row=2, column=0, sticky="w", pady=4)
        self.monofont_var = tk.StringVar(value=self.cfg.get("mono_font", MONO))
        self.monofont_box = DropMenu(fnt, variable=self.monofont_var, values=[],
                                     width=24, command=self.on_font_changed)
        self.monofont_box.grid(row=2, column=1, padx=8, sticky="w")
        tk.Label(fnt, text="Шрифт и масштаб вступают в силу после перезапуска.",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 2))
        RButton(fnt, text="↻ Перезапустить программу", style="accent",
                   command=self.restart_app).grid(row=4, column=0, pady=8, sticky="w")
        self.root.after(100, self._fill_font_boxes)

    def _build_set_targets(self):
        inner = self._set_scroll(self.set_pages["targets"])
        tk.Label(inner, text="Свои цели (необязательно, формат как в targets.txt)", bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        self.targets_txt = tk.Text(inner, bg=CARD2, fg=TEXT, font=(MONO, 9), height=8, bd=0, padx=8, pady=8, insertbackground=TEXT, selectbackground=ACCENT, selectforeground="white")
        self.targets_txt.pack(fill="both", expand=True, padx=8, pady=4)
        self.targets_txt.insert("1.0", self.cfg.get("targets_override", ""))
        RButton(inner, text="💾 Сохранить цели", style="ghost",
                   command=self.save_targets).pack(anchor="w", padx=8, pady=8)

    def _build_set_app(self):
        inner = self._set_scroll(self.set_pages["app"])
        tk.Label(inner, text="Приложение", bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        self.autostart_var = tk.BooleanVar(value=bool(self.cfg.get("app_autostart", False)))
        tk.Checkbutton(inner, text="Запускать Zapret Manager вместе с Windows (с правами администратора)",
                       variable=self.autostart_var, bg=CARD, fg=TEXT, font=(FONT, 10),
                       activebackground=CARD, selectcolor=CARD2,
                       command=self.on_autostart_toggle).pack(anchor="w", padx=8, pady=4)
        RButton(inner, text="📂 Открыть папку данных", style="ghost",
                   command=self.open_data_folder).pack(anchor="w", padx=8, pady=8)
        RButton(inner, text="📌 Создать ярлык на рабочем столе", style="accent",
                   command=self.on_make_shortcut).pack(anchor="w", padx=8, pady=(0, 8))
        RButton(inner, text="🔄 Обновить кэш иконок Windows", style="ghost",
                   command=self.on_refresh_icons).pack(anchor="w", padx=8, pady=(0, 8))
        tk.Label(inner, text=f"{APP_NAME} v{APP_VERSION} • только стандартная библиотека • ~20 МБ RAM\n"
                             "Ручная проверка: турбо (максимум потоков + приоритет).\n"
                             "Автомониторинг: эко (3 потока, фоновый приоритет, сон между проверками).",
                 bg=CARD, fg=MUTED, font=(FONT, 9), justify="left").pack(anchor="w", padx=8, pady=(8, 4))

    def open_data_folder(self):
        try:
            os.startfile(DATA_DIR)
        except Exception:
            pass

    def on_make_shortcut(self):
        ok, msg = create_desktop_shortcut()
        if ok:
            self.dlg_info(f"Ярлык создан:\n{msg}\n\nЗапускайте приложение двойным кликом.")
        else:
            self.dlg_error(f"Не удалось создать ярлык:\n{msg}")
        self.msg_q.put(("actions_refresh", None))

    def on_refresh_icons(self):
        if not self.dlg_ask("Сбросить кэш иконок Windows?\nПроводник на секунду перезапустится (окна папок закроются)."):
            return
        threading.Thread(target=self._refresh_icons_worker, daemon=True).start()

    def _refresh_icons_worker(self):
        ok, msg = refresh_icon_cache()
        self.msg_q.put(("toast", ("Кэш иконок", msg, GREEN if ok else RED)))

    def on_reinstall_zapret(self):
        root = self.root_var.get().strip() or self.cfg.get("zapret_root", "")
        if not self.dlg_ask(
                "Переустановить Zapret?\n\n"
                f"Папка: {root}\n"
                "Служба и обход остановятся, папка заменится свежим релизом "
                "с GitHub Flowseal.\nВаши списки (*-user.txt, настройки) сохранятся."):
            return
        self.set_status("переустановка zapret…", YELLOW)
        threading.Thread(target=self._reinstall_worker, args=(root,), daemon=True).start()

    def _reinstall_worker(self, root):
        import shutil as _sh
        import tempfile as _tf
        import zipfile as _zf
        try:
            if not root or not os.path.isdir(root):
                raise RuntimeError("папка zapret не найдена")
            try:
                self.msg_q.put(("status", ("переустановка zapret…", YELLOW)))
            except Exception:
                pass
            log_action(f"Переустановка zapret начата: {root}")
            # 1. остановить всё
            try:
                remove_service()
            except Exception as e:
                log_action(f"Остановка службы при переустановке: {e}", "error")
            time.sleep(1)
            stop_winws()
            # 2. бэкап пользовательских файлов (корень + lists/)
            tmp = _tf.mkdtemp(prefix="zapret_mgr_")
            user_files = []
            for base in ("", "lists"):
                d = os.path.join(root, base) if base else root
                if not os.path.isdir(d):
                    continue
                for name in os.listdir(d):
                    if not (name.endswith("-user.txt") or name == "ipset-all.txt.backup"):
                        continue
                    cand = os.path.join(d, name)
                    if not os.path.isfile(cand):
                        continue
                    rel = os.path.relpath(cand, root)
                    dst = os.path.join(tmp, "user", rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    _sh.copy2(cand, dst)
                    user_files.append(rel)
            for rel in (os.path.join("utils", "game_filter.enabled"),
                        os.path.join("utils", "check_updates.enabled")):
                cand = os.path.join(root, rel)
                if os.path.isfile(cand):
                    dst = os.path.join(tmp, "user", rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    _sh.copy2(cand, dst)
                    user_files.append(rel)
            # 3. узнать свежий релиз и скачать zip
            req = urllib.request.Request(
                "https://api.github.com/repos/Flowseal/zapret-discord-youtube/releases/latest",
                headers={"User-Agent": "ZapretManager",
                         "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                rel = json.load(r)
            tag = (rel.get("tag_name") or "").strip()
            zurl, zname = "", ""
            for a in rel.get("assets", []):
                nm = a.get("name", "")
                if nm.startswith("zapret-discord-youtube-") and nm.endswith(".zip"):
                    zurl, zname = a.get("browser_download_url", ""), nm
                    break
            if not zurl:
                raise RuntimeError("в релизе нет zip-архива")
            log_action(f"Скачиваю {zname} ({tag})…")
            zpath = os.path.join(tmp, zname)
            rq = urllib.request.Request(zurl, headers={"User-Agent": "ZapretManager"})
            with urllib.request.urlopen(rq, timeout=120) as r, open(zpath, "wb") as f:
                _sh.copyfileobj(r, f, 1024 * 256)
            # 4. распаковать, найти корень (файлы или одна папка)
            with _zf.ZipFile(zpath) as z:
                z.extractall(os.path.join(tmp, "fresh"))
            fresh = os.path.join(tmp, "fresh")
            items = [p for p in os.listdir(fresh) if p != "__MACOSX"]
            if len(items) == 1 and os.path.isdir(os.path.join(fresh, items[0])):
                new_root = os.path.join(fresh, items[0])
            else:
                new_root = fresh
            if not os.path.exists(os.path.join(new_root, "service.bat")):
                raise RuntimeError("в архиве нет service.bat — странный релиз")
            # 5. заменить папку (старая -> .prev, откат при ошибке)
            prev = root.rstrip("\\/") + ".prev"
            if os.path.exists(prev):
                _sh.rmtree(prev, ignore_errors=True)
            os.rename(root, prev)
            try:
                _sh.move(new_root, root)
            except Exception:
                if os.path.exists(root):
                    _sh.rmtree(root, ignore_errors=True)
                os.rename(prev, root)
                raise
            # 6. вернуть пользовательские файлы
            for relp in user_files:
                src = os.path.join(tmp, "user", relp)
                if os.path.isfile(src):
                    dst = os.path.join(root, relp)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    _sh.copy2(src, dst)
            _sh.rmtree(prev, ignore_errors=True)
            _sh.rmtree(tmp, ignore_errors=True)
            # 7. обновить UI
            self.cfg["zapret_root"] = root
            try:
                self.root_var.set(root)
            except Exception:
                pass
            save_config(self.cfg)
            self.engine.cfg = self.cfg
            log_action(f"Zapret переустановлен ({tag}), пользовательских файлов: {len(user_files)}")
            self.msg_q.put(("toast", ("Zapret переустановлен",
                                      f"Версия {tag}. Выберите конфиг и примените.", GREEN)))
            self.root.after(300, self.refresh_all_static)
        except Exception as e:
            log_action(f"Переустановка zapret не удалась: {e}", "error")
            self.msg_q.put(("toast", ("Переустановка", f"Не удалось: {e}", RED)))
        finally:
            self.msg_q.put(("status", ("готово", MUTED)))
            self.msg_q.put(("actions_refresh", None))

    def browse_root(self):
        d = filedialog.askdirectory(title="Выберите корневую папку zapret (где лежат general*.bat)")
        if d:
            self.root_var.set(d)

    def save_root(self):
        v = self.root_var.get().strip()
        if not os.path.isdir(v):
            self.dlg_error("Папка не существует")
            return
        if not glob.glob(os.path.join(v, "*.bat")):
            if not self.dlg_ask("В папке нет .bat файлов. Всё равно сохранить?"):
                return
        self.cfg["zapret_root"] = v
        save_config(self.cfg)
        self.engine.cfg = self.cfg
        log_action(f"Изменена корневая папка zapret: {v}")
        self.refresh_all_static()
        self.refresh_active_bar()
        self.dlg_info("Папка сохранена")

    def on_autostart_toggle(self):
        en = self.autostart_var.get()
        ok, msg = set_app_autostart(en)
        if ok:
            self.cfg["app_autostart"] = en
            save_config(self.cfg)
            log_action(f"Автозагрузка приложения: {'включена' if en else 'выключена'}")
            if en and msg:
                self.dlg_info(msg)
            self.msg_q.put(("actions_refresh", None))
        else:
            self.dlg_error(f"Не удалось изменить автозагрузку: {msg}")
            self.autostart_var.set(not en)

    def on_monitor_toggle(self):
        en = self.mon_var.get()
        self.cfg["monitor_enabled"] = en
        save_config(self.cfg)
        log_action(f"Мониторинг: {'включён' if en else 'выключен'}")
        if en:
            self.start_monitor()
        else:
            self.monitor_stop.set()
        self.msg_q.put(("actions_refresh", None))

    def save_monitor(self):
        try:
            iv = max(1, int(self.interval_var.get()))
            to = min(30, max(2, int(self.timeout_var.get())))
        except ValueError:
            self.dlg_error("Введите числа")
            return
        self.cfg["monitor_interval_min"] = iv
        self.cfg["check_timeout_s"] = to
        save_config(self.cfg)
        self.engine.cfg = self.cfg
        log_action(f"Настройки мониторинга: интервал={iv} мин, таймаут={to} c "
                   f"(макс. пинг берётся с главной: {self.cfg.get('ping_threshold_ms')} мс)")
        self.monitor_stop.set()
        if self.cfg.get("monitor_enabled"):
            self.start_monitor()
        self.dlg_info("Сохранено")

    def save_speed(self):
        try:
            wor = min(16, max(4, int(self.workers_var.get())))
        except ValueError:
            self.dlg_error("Введите число потоков")
            return
        self.cfg["check_workers"] = wor
        save_config(self.cfg)
        self.engine.cfg = self.cfg
        log_action(f"Потоки проверки: {wor} (режим/повторы/пинг — на главной)")
        self.dlg_info("Сохранено. Ручная проверка идёт в турбо-режиме.")

    def _mark_theme_buttons(self):
        cur = self.theme_var.get()
        for name, b in self.theme_btns.items():
            try:
                if name == cur:
                    b.config(relief="sunken", bd=3)
                else:
                    b.config(relief="flat", bd=0)
            except Exception:
                pass

    def pick_theme(self, name):
        if name not in THEMES:
            return
        self.theme_var.set(name)
        self.preview_theme()

    def preview_theme(self):
        """Предпросмотр темы: применить живьём и сразу сохранить."""
        name = self.theme_var.get()
        if name not in THEMES:
            return
        self.apply_theme_live(name)
        self._mark_theme_buttons()
        if self.cfg.get("theme") != name:
            self.cfg["theme"] = name
            save_config(self.cfg)
            log_action(f"Тема изменена: {name} (без перезапуска)")

    def apply_theme_live(self, name):
        """Перекрасить весь интерфейс без перезапуска.

        Цвета всех виджетов заданы из 12 констант палитры — маппим
        старое значение -> новое и обходим дерево виджетов.
        """
        old = {k: globals()[k] for k in THEME_KEYS}
        apply_theme(name)
        mapping = {}
        for k in THEME_KEYS:
            if old[k].lower() != globals()[k].lower():
                mapping[old[k].lower()] = globals()[k]
        global THEME_REMAP
        THEME_REMAP = mapping
        if not mapping:
            return
        self.style_setup()
        opts = ("background", "foreground", "activebackground",
                "activeforeground", "selectcolor", "selectbackground",
                "selectforeground", "troughcolor", "highlightbackground",
                "highlightcolor", "insertbackground", "disabledforeground",
                "buttonbackground")

        def fix(w):
            try:
                for opt in opts:
                    try:
                        cur = w.cget(opt)
                    except Exception:
                        continue
                    if isinstance(cur, str) and cur.lower() in mapping:
                        try:
                            w.configure(**{opt: mapping[cur.lower()]})
                        except Exception:
                            pass
            except Exception:
                pass
            try:
                for ch in w.winfo_children():
                    fix(ch)
            except Exception:
                pass

        fix(self.root)
        try:
            tint_native_caption(self.root)
        except Exception:
            pass
        self._repaint_combo_popups()
        # кастомные виджеты перекрашиваются сами
        try:
            for w in list(THEMED):
                try:
                    w.apply_theme()
                except Exception:
                    pass
        except Exception:
            pass

    def _repaint_combo_popups(self):
        """Уже созданные выпадашки комбобоксов читают цвета при создании —
        красим их вручную (иначе остаются в старой теме).

        Popdown — это $combobox.popdown.f.l (вложен в комбобокс, не в root).
        """
        try:
            boxes = []

            def walk(w):
                try:
                    if w.winfo_class() == "TCombobox":
                        boxes.append(w)
                    for ch in w.winfo_children():
                        walk(ch)
                except Exception:
                    pass

            walk(self.root)
            for b in boxes:
                try:
                    lb = str(b) + ".popdown.f.l"
                    if int(b.tk.call("winfo", "exists", lb)):
                        b.tk.call(lb, "configure",
                                  "-background", CARD2, "-foreground", TEXT,
                                  "-selectbackground", ACCENT,
                                  "-selectforeground", "white")
                except Exception:
                    pass
        except Exception:
            pass

    def _fill_font_boxes(self):
        try:
            fams = available_fonts(FONT_WHITELIST)
            self.font_box.set_values(fams)
            if self.font_var.get() not in fams and fams:
                self.font_var.set(fams[0])
            mams = available_fonts(MONO_WHITELIST)
            self.monofont_box.set_values(mams)
            if self.monofont_var.get() not in mams and mams:
                self.monofont_var.set(mams[0])
        except Exception:
            pass

    def on_font_changed(self):
        """Шрифты сохраняются сразу при выборе; перезапуск — по вопросу."""
        new_font = (self.font_var.get() or "").strip() or "Trebuchet MS"
        new_scale = self.scale_var.get() if self.scale_var.get() in UI_SCALES else "Крупный"
        new_mono = (self.monofont_var.get() or "").strip() or "Consolas"
        if (new_font == self.cfg.get("ui_font") and new_scale == self.cfg.get("ui_scale")
                and new_mono == self.cfg.get("mono_font")):
            return
        self.cfg["ui_font"] = new_font
        self.cfg["ui_scale"] = new_scale
        self.cfg["mono_font"] = new_mono
        save_config(self.cfg)
        log_action(f"Шрифты: {new_font} / {new_scale} / {new_mono} — нужен перезапуск")
        if self.dlg_ask("Сохранено. Перезапустить программу сейчас?"):
            self.restart_app()

    def restart_app(self):
        log_action("Перезапуск приложения для применения вида")
        try:
            save_config(self.cfg)
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            self.dlg_error(f"Не удалось перезапустить: {e}")

    def save_targets(self):
        self.cfg["targets_override"] = self.targets_txt.get("1.0", "end").strip()
        save_config(self.cfg)
        self.engine.cfg = self.cfg
        log_action("Обновлён список целей для проверок")
        self.dlg_info("Цели сохранены")

    # ---------- static ----------
    def refresh_all_static(self):
        cfgs = list_configs(self.cfg.get("zapret_root", ""))
        for w in self.cfg_checks.winfo_children():
            w.destroy()
        self.cfg_vars = {}
        for bat in cfgs:
            v = tk.BooleanVar(value=True)
            self.cfg_vars[bat] = v
            row = tk.Frame(self.cfg_checks, bg=CARD)
            row.pack(fill="x", anchor="w")
            tk.Checkbutton(row, text=bat.replace(".bat", ""), variable=v, bg=CARD, fg=TEXT,
                           font=(FONT, 10), anchor="w", activebackground=CARD,
                           selectcolor=CARD2).pack(side="left", fill="x", expand=True)
            # ▶ — выбрать конфиг сразу, без запуска проверки
            tk.Button(row, text="▶", bg=CARD, fg=ACCENT2, font=(FONT, 10, "bold"),
                      bd=0, cursor="hand2", activebackground=CARD2,
                      activeforeground=TEXT, width=3,
                      command=lambda b=bat: self.on_apply_config(b)).pack(side="right")
        if not cfgs:
            tk.Label(self.cfg_checks, text="⚠ Конфиги не найдены", bg=CARD, fg=YELLOW,
                     font=(FONT, 10)).pack(anchor="w")
        adm = "🛡 Администратор" if is_admin() else "⚠ Без прав администратора"
        col = GREEN if is_admin() else YELLOW
        self.admin_lbl.config(text=adm, fg=col)
        try:
            self.autostart_var.set(app_autostart_enabled())
            self.cfg["app_autostart"] = self.autostart_var.get()
        except Exception:
            pass
        self.refresh_active_bar()

    def ask_zapret_root_first(self):
        if self.dlg_ask("Не найдена папка zapret.\nВыбрать корневую папку (где лежат general*.bat) сейчас?"):
            self.show_page("settings")
            self.browse_root()
            self.save_root()

    # ================= мониторинг =================
    def start_monitor(self):
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_stop.set()
            time.sleep(0.3)
        self.monitor_stop.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        log_action("Мониторинг запущен")

    def _monitor_loop(self):
        # первая быстрая проверка через 30 c, дальше по интервалу
        time.sleep(30)
        while not self.monitor_stop.is_set():
            try:
                if not self.cfg.get("monitor_enabled"):
                    break
                if self.engine.running:
                    time.sleep(20)
                    continue
                st = service_status()
                # мониторим только если что-то активно
                if st["zapret"] not in ("RUNNING",) and not st["winws"]:
                    time.sleep(60)
                    continue
                res = self.engine.test_targets_current()
                if res["blocked"]:
                    self.on_blocked_detected(res)
            except Exception as e:
                log_action(f"Ошибка мониторинга: {e}", "error")
            iv = max(1, int(self.cfg.get("monitor_interval_min", 3))) * 60
            # сон с возможностью ранней остановки (экономит CPU: один wait вместо цикла)
            self.monitor_stop.wait(iv)

    def on_blocked_detected(self, res):
        cur = self.cfg.get("active_config", "") or service_status().get("strategy", "")
        msg = (f"Обнаружены проблемы: HTTP fail={res['fail_http']} ok={res['ok_http']}, "
               f"плохой пинг={res['bad_ping']}. Текущий: {cur or 'неизвестен'}. "
               f"Порог пинга {self.cfg.get('ping_threshold_ms')} мс.")
        log_action(msg, "monitor")
        # ищем замену среди известных оценок
        scores = dict(self.cfg.get("best_scores", {}))
        # исключить текущий
        if cur in scores:
            scores.pop(cur, None)
        if not scores:
            log_action("Нет данных о других конфигах — запустите полную проверку", "monitor")
            self.msg_q.put(("toast", ("⚠ Проблемы с соединением",
                                      "Нет данных для автопереключения. Запустите проверку конфигов.", RED)))
            return
        nxt = max(scores, key=lambda k: scores[k])
        log_action(f"Автопереключение: {cur} → {nxt} (score={scores[nxt]})", "autoswitch")
        ok, m = install_service(self.cfg["zapret_root"], nxt)
        if ok:
            self.cfg["active_config"] = nxt
            save_config(self.cfg)
            log_action(f"Автопереключение выполнено: теперь активен {nxt}", "autoswitch")
            self.msg_q.put(("toast", ("🔄 Автопереключение",
                                      f"{cur} сбоил (пинг/DPI).\nВключён {nxt}.", GREEN)))
        else:
            log_action(f"Автопереключение не удалось ({nxt}): {m}", "error")
            self.msg_q.put(("toast", ("⚠ Не удалось переключить",
                                      f"{nxt}: {m}", RED)))
        self.root.after(500, self.refresh_choose)
        self.msg_q.put(("actions_refresh", None))


def main():
    global FONT, MONO
    # AppUserModelID — ПЕРВЫМ делом: иначе таскбар группирует окно
    # под иконку pythonw.exe вместо нашей Z (и тосты не попадут в Центр уведомлений)
    try:
        if os.name == "nt":
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    minimized = "--minimized" in sys.argv
    # тема, шрифт и масштаб из настроек — до построения UI
    _cfg0 = load_config()
    apply_theme(_cfg0.get("theme", "Алый"))
    FONT = _cfg0.get("ui_font", "Trebuchet MS") or "Trebuchet MS"
    MONO = _cfg0.get("mono_font", "Consolas") or "Consolas"
    _scale = UI_SCALES.get(_cfg0.get("ui_scale", "Крупный"), 1.12)
    root = tk.Tk()
    # иконка: чёрный квадрат с белой Z — окну, приложению и таскбару.
    # Файлы -> встроенная в код (если запуск без папки assets).
    _icon_src = "нет"
    try:
        _ico = os.path.join(BASE_DIR, "assets", "icon.ico")
        if os.path.exists(_ico):
            root.iconbitmap(_ico)
            root.iconbitmap(default=_ico)
            _icon_src = "файл icon.ico"
        else:
            print(f"[icon] нет файла: {_ico}")
    except Exception as e:
        print(f"[icon] iconbitmap: {e}")
    try:
        _png = os.path.join(BASE_DIR, "assets", "icon.png")
        if os.path.exists(_png):
            root._icon_img = tk.PhotoImage(file=_png)
            root.iconphoto(True, root._icon_img)
            if _icon_src == "нет":
                _icon_src = "файл icon.png"
        elif _ICON_PNG_B64:
            root._icon_img = tk.PhotoImage(data=_ICON_PNG_B64)
            root.iconphoto(True, root._icon_img)
            _icon_src = "встроенная"
        else:
            print(f"[icon] нет файла: {_png}")
    except Exception as e:
        print(f"[icon] iconphoto: {e}")
        try:
            if _ICON_PNG_B64:
                root._icon_img = tk.PhotoImage(data=_ICON_PNG_B64)
                root.iconphoto(True, root._icon_img)
                _icon_src = "встроенная (fallback)"
        except Exception as e2:
            print(f"[icon] embedded: {e2}")
    print(f"[icon] источник: {_icon_src}")
    try:
        log_action(f"Иконка: {_icon_src}")
    except Exception:
        pass
    # системная шторка в цветах темы + рамка в цвет фона (Windows 11 DWM)
    try:
        root.update_idletasks()
        tint_native_caption(root)
        root.after(1200, lambda: tint_native_caption(root))
    except Exception:
        pass
    # лёгкий DPI-aware
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    # масштаб интерфейса (шрифты + отступы пропорционально, без лишних затрат)
    try:
        if abs(_scale - 1.0) > 0.01:
            cur = float(root.tk.call("tk", "scaling"))
            root.tk.call("tk", "scaling", cur * _scale)
    except Exception:
        pass
    app = ZapretApp(root, minimized=minimized)
    try:
        ensure_startmenu_shortcut()
    except Exception:
        pass
    root.mainloop()


if __name__ == "__main__":
    main()
