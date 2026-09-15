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

# Схема версий x.yy.zz: x — крупные обновления, y — рядовые обновления,
# z — фиксы. При повышении старшего звена все младшие сбрасываются в 0
# (пример: 1.2.3 -> рядовое -> 1.3.0; крупное -> 2.0.0; фикс -> 1.2.4).
APP_VERSION = "1.2.0"
APP_NAME = "Zapret Manager"
APP_REPO = "PROPANE3/zapret-manager"
APP_ID = "Flowseal.ZapretManager"

_LOCK_FD = None


def ensure_single_instance():
    """Только один инстанс: второй молча показывает окно первого и выходит.

    Без этого двойной клик по ярлыку плодит одинаковые окна друг на друге
    (то самое «двоение») и удваивает нагрузку (лаги, двойные проверки).
    """
    global _LOCK_FD
    try:
        import msvcrt
        os.makedirs(DATA_DIR, exist_ok=True)
        _LOCK_FD = open(os.path.join(DATA_DIR, "instance.lock"), "w")
        try:
            msvcrt.locking(_LOCK_FD.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            pass
    except Exception:
        pass
    try:
        if os.name == "nt":
            u = ctypes.windll.user32
            best = {"h": 0}

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def _cb(h, _):
                try:
                    if not u.IsWindowVisible(h):
                        return True
                    ln = u.GetWindowTextLengthW(h)
                    if ln <= 0:
                        return True
                    buf = ctypes.create_unicode_buffer(ln + 1)
                    u.GetWindowTextW(h, buf, ln + 1)
                    if buf.value.startswith(APP_NAME + " v"):
                        best["h"] = h
                        return False
                except Exception:
                    pass
                return True

            u.EnumWindows(_cb, 0)
            if best["h"]:
                try:
                    u.ShowWindow(best["h"], 9)  # SW_RESTORE
                    u.SetForegroundWindow(best["h"])
                except Exception:
                    pass
    except Exception:
        pass
    return False

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


# ---------- Смешная опция (assets/funny option) ----------
FUNNY_DIR = os.path.join(BASE_DIR, "assets", "funny option")
# Маленький телик-оверлей поверх всего (места в layout не занимает).
FUNNY_TV_SUB = 8          # 1920x1487 -> 240x186 на экране
FUNNY_TV_W, FUNNY_TV_H = 240, 186
# Экран телика в PNG прозрачный (замер по альфе): x 250..1390, y 248..945.
# Гифка кладётся ЗАДНИМ слоем под картинку телика — безель сам маскирует
# вылезающее, фоны гифок не трогаем (рисуем 1:1 как в файле, максимум — кроп
# безелем). Центр экрана на канвасе:
FUNNY_SCREEN_CX = (250 + 1390) // 2 // FUNNY_TV_SUB
FUNNY_SCREEN_CY = (248 + 945) // 2 // FUNNY_TV_SUB
# key -> [(файл, subsample), ...]: у некоторых есть _2-вариации
# (no_responce_2, excelent_2) — тоже используются, ротация при каждом показе.
# Сабсемплы подобраны под маленькое окошко экрана (143x88, см. FUNNY_HOLE_*):
# меньше пикселей на кадр -> декод/отрисовка в разы дешевле.
FUNNY_GIFS = {
    "idle": [("idle_gif.gif", 4)],
    "no_response": [("no_responce.gif", 3), ("no_responce_2.gif", 4)],
    "bad": [("bad.gif", 2)],
    "normal": [("normal.gif", 2)],
    "good": [("good.gif", 3)],
    "excellent": [("excellent.gif", 4), ("excelent_2.gif", 1)],
    "bg": [("bg_g.gif", 1)],
}
# Точный размер экрана телика на канвасе (замер по альфе: x 250..1390,
# y 248..945, сабсемпл TV 8). Кадры кропаются строго под него и не вылезают
# наружу вообще (чёрные поля — как тьма экрана, фоны не трогаем).
FUNNY_HOLE_W = (1390 - 250 + 7) // FUNNY_TV_SUB
FUNNY_HOLE_H = (945 - 248 + 7) // FUNNY_TV_SUB


def _fun_variant_spec(concrete):
    """concrete 'key#i' -> (файл, subsample)."""
    base, _, num = concrete.partition("#")
    variants = FUNNY_GIFS[base]
    return variants[int(num or 0) % len(variants)]


def _fun_all_concrete():
    """Все конкретные ключи ('bg#0', 'excellent#1', ...) для прогрева."""
    out = []
    for base, variants in FUNNY_GIFS.items():
        for i in range(len(variants)):
            out.append(f"{base}#{i}")
    return out


def _fun_blit_center(src, gw, gh, dw=FUNNY_HOLE_W, dh=FUNNY_HOLE_H):
    """Центрировать кадр gw×gh в окно dw×dh, лишнее — обрезать.

    Фоны не трогаем: копируем попиксельно 1:1; незаполненные поля —
    чёрные (как тьма экрана). Возвращает bytes dw×dh×3.
    """
    out = bytearray(dw * dh * 3)
    ox = (dw - gw) // 2
    oy = (dh - gh) // 2
    sx0 = max(0, -ox)
    sy0 = max(0, -oy)
    dx0 = max(0, ox)
    dy0 = max(0, oy)
    w = min(gw - sx0, dw - dx0)
    h = min(gh - sy0, dh - dy0)
    if w <= 0 or h <= 0:
        return bytes(out)
    for y in range(h):
        s = ((sy0 + y) * gw + sx0) * 3
        d = ((dy0 + y) * dw + dx0) * 3
        out[d:d + w * 3] = src[s:s + w * 3]
    return bytes(out)


def _read_png_rgba(path):
    """Прочитать PNG (8 бит, без чересстрочки) -> (w, h, bytearray RGBA)."""
    import struct as _st
    import zlib as _zl
    with open(path, "rb") as f:
        d = f.read()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a png")
    w = h = bd = ct = inter = None
    raw = b""
    pos = 8
    while pos < len(d):
        ln = _st.unpack(">I", d[pos:pos + 4])[0]
        typ = d[pos + 4:pos + 8]
        if typ == b"IHDR":
            w, h, bd, ct, _c, _f, inter = _st.unpack(">IIBBBBB",
                                                    d[pos + 8:pos + 21])
        elif typ == b"IDAT":
            raw += d[pos + 8:pos + 8 + ln]
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if bd != 8 or inter != 0 or ct not in (2, 6):
        raise ValueError("only 8-bit non-interlaced RGB/RGBA")
    ch = 4 if ct == 6 else 3
    px = bytearray(_zl.decompress(raw))
    stride = w * ch
    out = bytearray(w * h * 4)
    prev = bytearray(stride)
    i = 0
    for y in range(h):
        if y and y % 64 == 0:
            # уступить GIL интерфейсу (разбор — чистый CPU)
            try:
                time.sleep(0)
            except Exception:
                pass
        f = px[i]
        i += 1
        line = px[i:i + stride]
        i += stride
        cur = bytearray(stride)
        if f == 0:
            cur[:] = line
        elif f == 1:
            for x in range(stride):
                cur[x] = (line[x] + (cur[x - ch] if x >= ch else 0)) & 255
        elif f == 2:
            for x in range(stride):
                cur[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                a = cur[x - ch] if x >= ch else 0
                cur[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                a = cur[x - ch] if x >= ch else 0
                b = prev[x]
                c = prev[x - ch] if x >= ch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                best = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[x] = (line[x] + best) & 255
        else:
            raise ValueError("bad png filter")
        ro = y * w * 4
        if ch == 4:
            out[ro:ro + stride] = cur
        else:
            for x in range(w):
                o = ro + x * 4
                q = x * 3
                out[o] = cur[q]
                out[o + 1] = cur[q + 1]
                out[o + 2] = cur[q + 2]
                out[o + 3] = 255
        prev = cur
    return w, h, out


def _crop_center_square(w, h, rgba):
    """Центральный квадрат (для иконки: бока панорамы — вон)."""
    s = min(w, h)
    x0 = (w - s) // 2
    y0 = (h - s) // 2
    out = bytearray(s * s * 4)
    for y in range(s):
        src = ((y0 + y) * w + x0) * 4
        dst = y * s * 4
        out[dst:dst + s * 4] = rgba[src:src + s * 4]
    return s, out


def _encode_png_rgba(w, h, rgba):
    import struct as _st
    import zlib as _zl
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgba[y * w * 4:(y + 1) * w * 4]

    def chunk(t, dd):
        c = t + dd
        return (_st.pack(">I", len(dd)) + c
                + _st.pack(">I", _zl.crc32(c) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", _st.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", _zl.compress(bytes(raw)))
    png += chunk(b"IEND", b"")
    return png


def _wrap_ico(png_bytes):
    """PNG -> .ico с одной PNG-записью (размер читается из IHDR, так что
    квадрат 498 тоже валиден на Vista+)."""
    import struct as _st
    w, h = _st.unpack(">II", png_bytes[16:24])
    wb = w if w < 256 else 0
    hb = h if h < 256 else 0
    head = _st.pack("<HHH", 0, 1, 1)
    entry = _st.pack("<BBBBHHII", wb, hb, 0, 0, 1, 32, len(png_bytes), 6 + 16)
    return head + entry + png_bytes


# ранг оценки конфига (0..4 из config_grade) -> гифка телика
FUNNY_RANK_KEYS = ("no_response", "bad", "normal", "good", "excellent")
# пол тика, мс: быстрее гранулярности таймеров Tk (~15 мс) всё равно нельзя,
# а after(1) устраивал шторм под 1 КГц и вешал интерфейс
FUNNY_MIN_TICK = 15


# Сколько декодированных кадров несёт одно сообщение воркера.
# Меньше — отзывчивее появление новой гифки, больше — меньше дёрганий очереди.
FUNNY_CHUNK = 4


class _FunWorker(threading.Thread):
    """Фоновый декодер гифок (daemon на всё время жизни приложения).

    Каждая гифка декодируется РОВНО ОДИН РАЗ целиком в фоне: дальше анимация —
    это просто переключение готовых PhotoImage (ноль hex-строк, ноль put(),
    ноль мусора для GC на каждый кадр). Именно покадровый put() с гигантскими
    строками в главном потоке и вешал интерфейс. Tk тут НЕ трогаем (только
    байты), сборка PhotoImage — в тике главного потока.
    """

    def __init__(self, gen_of):
        super().__init__(daemon=True)
        self.tasks = queue.Queue()
        self.results = queue.Queue()
        self._gen_of = gen_of
        self.start()

    def run(self):
        while True:
            try:
                task = self.tasks.get()
            except Exception:
                return
            if task is None:
                return
            key, gen = task
            try:
                fname, sub = _fun_variant_spec(key)
                # bg — целиком, остальное — строгий кроп под экран телика
                crop = not key.split("#")[0] == "bg"
                player = GifPlayer(os.path.join(FUNNY_DIR, fname), sub)
                total = len(player.frames)
                if crop:
                    size = (FUNNY_HOLE_W, FUNNY_HOLE_H)
                else:
                    size = (player.dw, player.dh)
                batch = []
                for i in range(total):
                    if gen != self._gen_of(key):
                        break  # гифка уже не нужна — бросаем
                    if i and i % 8 == 0:
                        # уступить GIL интерфейсу (декод — чистый CPU)
                        try:
                            time.sleep(0)
                        except Exception:
                            pass
                    delay = player.advance()
                    if crop:
                        frame = _fun_blit_center(bytes(player.buf),
                                                 player.dw, player.dh)
                    else:
                        frame = bytes(player.buf)
                    batch.append((frame, delay))
                    if len(batch) >= FUNNY_CHUNK or i == total - 1:
                        if gen != self._gen_of(key):
                            break
                        self.results.put(
                            ("frames", key, gen, batch, size,
                             i == total - 1))
                        batch = []
            except Exception as e:
                try:
                    self.results.put(("err", key, gen, str(e)[:100]))
                except Exception:
                    pass


class GifPlayer:
    """Инкрементальный GIF-плеер на чистом stdlib.

    Зачем свой, а не tk.PhotoImage(format='gif -index N'): Tk при каждом
    запросе кадра N пере-декодирует кадры 0..N (квадратичная сложность —
    237-кадровый good.gif грузился бы минутами). Здесь файл парсится один
    раз, кадры декодируются строго по одному вперёд (LZW + disposal +
    transparency + чересстрочка по спеке GIF89a) прямо в display-буфер
    с субсемплированием. Все кадры, родные задержки (delay_cs*10 мс,
    0 -> 100 мс), фоны — попиксельно как в файле.
    """

    def __init__(self, path, subsample=1):
        with open(path, "rb") as f:
            d = f.read()
        if d[:6] not in (b"GIF87a", b"GIF89a"):
            raise ValueError("not a gif")
        self.w = int.from_bytes(d[6:8], "little")
        self.h = int.from_bytes(d[8:10], "little")
        pos = 13
        self.gct = None
        if d[10] & 0x80:
            m = 3 * (1 << ((d[10] & 7) + 1))
            self.gct = d[pos:pos + m]
            pos += m
        self.frames = []
        delay, disposal, trans = 0, 0, None
        n = len(d)
        while pos < n:
            b = d[pos]
            if b == 0x3B:
                break
            elif b == 0x21:
                if d[pos + 1] == 0xF9:
                    # 21 F9 04 packed delay_lo delay_hi trans_idx 00
                    flags = d[pos + 3]
                    delay = int.from_bytes(d[pos + 4:pos + 6], "little")
                    disposal = (flags >> 2) & 7
                    trans = d[pos + 6] if (flags & 1) else None
                    pos += 8
                else:
                    pos += 2
                    while True:
                        sz = d[pos]
                        pos += 1
                        if sz == 0:
                            break
                        pos += sz
            elif b == 0x2C:
                fx = int.from_bytes(d[pos + 1:pos + 3], "little")
                fy = int.from_bytes(d[pos + 3:pos + 5], "little")
                fw = int.from_bytes(d[pos + 5:pos + 7], "little")
                fh = int.from_bytes(d[pos + 7:pos + 9], "little")
                packed = d[pos + 9]
                pos += 10
                lct = None
                if packed & 0x80:
                    m = 3 * (1 << ((packed & 7) + 1))
                    lct = d[pos:pos + m]
                    pos += m
                lzw_min = d[pos]
                pos += 1
                data = bytearray()
                while True:
                    sz = d[pos]
                    pos += 1
                    if sz == 0:
                        break
                    data += d[pos:pos + sz]
                    pos += sz
                self.frames.append({
                    "rect": (fx, fy, fw, fh),
                    "inter": bool(packed & 0x40),
                    "lct": lct, "lzw_min": lzw_min,
                    "data": bytes(data),
                    "delay": delay, "disposal": disposal, "trans": trans,
                })
                delay, disposal, trans = 0, 0, None
            else:
                raise ValueError("bad gif block")
        if not self.frames:
            raise ValueError("no frames")
        self.sub = max(1, int(subsample))
        self.dw = (self.w + self.sub - 1) // self.sub
        self.dh = (self.h + self.sub - 1) // self.sub
        self.buf = bytearray(self.dw * self.dh * 3)  # старт с чёрного
        self._snap = None
        self.idx = -1
        self.cur_delay_ms = 100
        # грязный прямоугольник display-координат для частичной отрисовки
        # (x0, y0, x1, y1); None = весь кадр. Большинство кадров гифок —
        # частичные обновления, полный put каждого кадра и тормозил анимацию.
        self.dirty = None
        self._prev_bbox = None

    @staticmethod
    def _lzw(data, lzw_min, expect):
        out = bytearray()
        clear = 1 << lzw_min
        eoi = clear + 1
        bits = lzw_min + 1
        pos = 0
        bitbuf = 0
        nbits = 0
        m = len(data)

        def read():
            nonlocal pos, bitbuf, nbits
            while nbits < bits and pos < m:
                bitbuf |= data[pos] << nbits
                pos += 1
                nbits += 8
            if nbits < bits:
                return -1
            code = bitbuf & ((1 << bits) - 1)
            bitbuf >>= bits
            nbits -= bits
            return code

        table = [bytes([i]) for i in range(clear)] + [b"", b""]
        prev = b""
        while True:
            code = read()
            if code < 0:
                break
            if code == clear:
                bits = lzw_min + 1
                table = [bytes([i]) for i in range(clear)] + [b"", b""]
                prev = b""
                continue
            if code == eoi:
                break
            if code < len(table) and table[code] != b"":
                entry = table[code]
            elif code == len(table) and prev:
                entry = prev + prev[:1]
            else:
                break
            out += entry
            if len(out) >= expect:
                break
            if prev:
                table.append(prev + entry[:1])
                if len(table) == (1 << bits) and bits < 12:
                    bits += 1
            prev = entry
        return bytes(out[:expect])

    def _apply_prev_disposal(self):
        if self.idx < 0:
            return
        fr = self.frames[self.idx]
        if fr["disposal"] == 2:
            fx, fy, fw, fh = fr["rect"]
            s = self.sub
            for dy in range(fy, fy + fh, s):
                if dy >= self.h:
                    break
                row = (dy // s) * self.dw * 3
                for dx in range(fx, fx + fw, s):
                    if dx >= self.w:
                        break
                    o = row + (dx // s) * 3
                    self.buf[o:o + 3] = b"\x00\x00\x00"
        elif fr["disposal"] == 3 and self._snap is not None:
            self.buf[:] = self._snap
            self._snap = None

    def _disp_bbox(self, rect):
        """Прямоугольник кадра в display-координатах (с запасом на округление)."""
        fx, fy, fw, fh = rect
        s = self.sub
        x0 = max(0, fx // s)
        y0 = max(0, fy // s)
        x1 = min(self.dw, (fx + fw + s - 1) // s)
        y1 = min(self.dh, (fy + fh + s - 1) // s)
        if x1 <= x0 or y1 <= y0:
            return None
        return (x0, y0, x1, y1)

    @staticmethod
    def _union(a, b):
        if a is None:
            return b
        if b is None:
            return a
        return (min(a[0], b[0]), min(a[1], b[1]),
                max(a[2], b[2]), max(a[3], b[3]))

    def advance(self):
        """Декодировать следующий кадр в буфер. Возвращает его задержку, мс."""
        prev_bbox = self._prev_bbox
        self._apply_prev_disposal()
        self.idx = (self.idx + 1) % len(self.frames)
        fr = self.frames[self.idx]
        fx, fy, fw, fh = fr["rect"]
        pal = fr["lct"] or self.gct
        if pal is None:
            raise ValueError("no palette")
        if fr["disposal"] == 3:
            self._snap = bytes(self.buf)
        px = self._lzw(fr["data"], fr["lzw_min"], fw * fh)
        s = self.sub
        trans = fr["trans"]
        if fr["inter"]:
            full = bytearray(fw * fh)
            p = 0
            for (ystart, ystep) in ((0, 8), (4, 8), (2, 4), (1, 2)):
                for yy in range(ystart, fh, ystep):
                    full[yy * fw:(yy + 1) * fw] = px[p:p + fw]
                    p += fw
            px = bytes(full)
        for sy in range(0, fh, s):
            gy = fy + sy
            if gy >= self.h:
                break
            row = (gy // s) * self.dw * 3
            base = sy * fw
            for sx in range(0, fw, s):
                gx = fx + sx
                if gx >= self.w:
                    break
                ci = px[base + sx] if base + sx < len(px) else 0
                if trans is not None and ci == trans:
                    continue
                o = row + (gx // s) * 3
                po = ci * 3
                if po + 2 < len(pal):
                    self.buf[o] = pal[po]
                    self.buf[o + 1] = pal[po + 1]
                    self.buf[o + 2] = pal[po + 2]
        d = fr["delay"]
        self.cur_delay_ms = (d * 10) if d > 0 else 100
        # грязная зона = что нарисовали + что откатили (restore/сlear прошлого)
        cur_bbox = self._disp_bbox(fr["rect"])
        self.dirty = self._union(cur_bbox, prev_bbox)
        self._prev_bbox = cur_bbox
        return self.cur_delay_ms

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
    "check_mode": "ultra",
    "check_repeat": 1,
    "check_workers": 12,
    "ui_font": "Trebuchet MS",
    "ui_scale": "Крупный",
    "mono_font": "Consolas",
    "theme": "Алый",
    "silly_mode": False,
}


# ================= ресурсы =================
# Встроенная иконка (чёрный квадрат, белая Z) — запасной вариант, если нет
# assets/icon.png (например, запуск из неразвёрнутого архива).
_ICON_PNG_B64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAYAAABccqhmAAAY60lEQVR42u2dCXBVVbaGL9LP'
    'fk2/qeoVdjXDRYJhCIEEEgmDDBZEZpChKRBkEAGNoEyCCjyQQDFEugAFi1lmOggyD6JMAjKJ'
    'JAwyBSIyDwlDCITB8/ZKYzcNeyX3su6559xz/lX1lZTogqyz93/22XvttTweGAwGg8FgMBgM'
    'BoPBYDAYDAaDwWAwGAwGC64VL178uRIlStTyer3dFX9VrFFsV+xRpCh+UqQp0gEIEqcUxxQH'
    'FfsUOxVb1Dido/45SNFK/Try+eef/x1msO8T/VkVuD8phiuuKAwAHMQGNcZfVf/8o+IZzHhl'
    'KhDlVVDeU/88ggECXMR9xd8UzYoVK/a/bpv0BRWJivMYCADkskPxiqMnfuHChf9N/ZD7FQ/w'
    'wAHQkqNIcNTEV5shz6kfag4eLgA+c0fRIiYmpkAoz/0C6of44OH3Dh4qAP5zRhEZipO/4MO/'
    'PB4iADLok3lCSMz6IkWKFFC7+gl4aACY8lnw37ad/CVLlqQl/ww8KABM45raUytr1+O9fXhA'
    'AJjOXZU7EGu3N38KHgwAwUOlGZexfPKXKVOmAI74ALBmT0B9DpS2etmfhAcBgGVcV5vu/2PJ'
    '5FdLkJJ4AABYzpWgT361CfF79QffQPABsB61ChgQ7KX/IgQeANtwT4lAyWBN/rIIOAC2Y1uw'
    'BOAQgg2ALYk2+2ZfOIIMgG1JM/vtn4kgA2BfihYtWsysjL8/I8AA2J4LZr39/4bgAmD/68Pq'
    'Zf3vgU76oYq9txFcAEKCUYHe/GuKoAIQMpwO9PL/SwQVgJCiWKDe/s94UdcPgFBLD24fqLf/'
    'fyCgAIQcmwIlAB8imACEHurS3u8CIQAXEEwAQpJCgRAABBKA0FwBREMAAHDvRuAkXP4BwL1k'
    'Sd/+3d0YuA4dOhhXr14FLmXTpk2OGctSAZjkRgHo27evAXOn/frrr8YLL7wAAXgoAJvdKABj'
    'xozBTHCptWvXzlFjWSoArmz4MW/ePMwEF9ry5csdN5bDwsIKSQQg3Y0CsHHjRswGF5q69erE'
    '8RyHJCA/OXLkiN+D58aNG8bPP/9s7N2711ixYoUxZcoUY8iQIUafPn2Mfv36GWPHjjUuXbqE'
    'WWZTU12unDqeO0gE4KobBYAmc36WnZ1tLFmyxHj77beN8uXLP+GjevXquZP+p59+wuyyuY0c'
    'OdLJ4/ltiQDccGHTxTwHy7Fjx4yGDRsaKkdC+/83a9bMOHHiRO5uMsz+dujQIacu/eVNQ9xY'
    'BSg8PJwdLHPmzGH/v7p16xrXr18XD8h79+4Zt2/fNm7evGlkZmYaly9fNrZu3Zr7WbFw4UJj'
    '5syZxqRJk4ykpKTcN5dTGD16tHH//n1tTLZt2ybyze3p0J9Xrlw5p4/p4RIBeOA2AYiIiNAO'
    'll27dmn/+9jYWOPHH3/0e6LTJ8SePXuM2bNnGx999JHRunVrIzIy0rVZa4sXL9bGiQRQ8obm'
    'nidZr1693BDbv+IegB9UrFhRO1gqVKjwxH/bu3dvIycnx+dJv2XLFqNTp05GjRo12E8IN9Kk'
    'SRM2ZnFxcSLf3Kps8+bNbonvFAiAH8TExGgHzOPZYbTL74vRyqFKlSqY8HnA2YABA0R+6ZNJ'
    'Z3fv3nVUtl8+TIUA+EH9+vXzPSNeu3Ztvsv76dOnG6o8MyZ4Phw8eFAbw8OHD4tEk1tV0OZs'
    '27Zt3RRjCIA/vPvuu08MmqysrH/8/vjx4/Oc/PPnz3fT20XE4MGDtTG8c+dO7krsaf2WKlXK'
    'uHbtmtY37TW4LM4QAH+YPHnyE4OGEoPo9xo3bsxOfNpRppMATGzfqFy5svHgwQNtLN966y2R'
    'b0rG4p6RCz/FIAD+8O233z4xcOgYSeVUs5Ofjux0yUCAh3tDp6SkiK9yc0t/2uB1YawhAP5w'
    '9uzZJwbP3LlzjdTUVO3AovReTGj/oKNPndGnluQNHR0dnbv/orMRI0a4Nd4QAOmO9JkzZ7T/'
    'no4AK1WqhEntB5QpyWVJNm3aVOSbE2lKx3bxKQwEIBBHUrolZXx8PCa1n5tz3D2LvLIsfaF/'
    '//7ss3L5aQwEwAwBmDZtGia1n1A6M5ftJ91Q5Iz2BFwedwhAoAXg0WNB4BtUaYczaQo01fHT'
    '2apVqxB7CEDgBaBevXoYWH5A39/cd39CQoIp2X63bt3KPblB/CEAPlO6dOl8Jz9lrmFQ+Tf5'
    '6WhPZ7t37xb5fvXVV9n9mZYtWyL+EAD/aNSoUb4CQLUAMKh8Z9CgQewbWpo7wR350bEtYg8B'
    'CEga8KOWnp6OAeUHZcuWZZf+zZs3F/k+fvw49mcgAIFl4sSJeQrAG2+8gQHlx9Kfbt3p7Ouv'
    'vxb5pmvYXKov3bxE/CEAT8Xq1avzFAAMJt9ZsGCBNoYXL17MzQd4Wr8vvvhi7mUhnQ0bNgyx'
    'hwAE/moqWXJyMgaTj7Rq1Ypd+ktOUGhVkZaWpvVLnwSIPQRABDe4yKKiojCYfICuQnNvaGny'
    'FJVZ1xndKkTsIQCmXAQioyKdTq4c6w1CU5Xz58+L/NasWZMVZ6qniNhDAMRkZGRoB9iMGTMw'
    'kHyAeiSY0XiDxPfKlStav0uXLkXsIQCBgd70OmvTpg0Gkjf/cupcWe9u3bqZku1HBT9RaxEC'
    'YJjZEIS+LylDEAMp79jt37/flOq7lNGHpCwIgOnQ+THXCQiDKG8+/vhjtl4CrQwku/7UKEVn'
    'EyZMQOwhAF7Ta9PTeTYGkTev9tPsG7pq1aoi39RiDVWYIABBgbL8cJ/c/6U/l+03a9YsU+4Q'
    '0IpAKiwQAAjAE3zwwQeoJuMNTDsvujMhyfajzzFu6U+lxBF7CEDAGTdunPZaKQaQHjp712X7'
    '0aZptWrVRL4pZ0Bnp06dQuwhAOYwb9487XITA0j/3c/V9KcuvxLfU6dOZS/6IPYQANOgG2qP'
    '21dffYUBpIG6GnPVdyV+6ViPM7pfgNhDAExDd47dtWtXDKDHoIad3Bu6XLlyhqRiMFfb78sv'
    'v0TsIQDmovvuxOD5V6hFOrf0f/PNN0W+ly1bpvWbmZmJ2EMAzEe364zB869Hftx16fXr14uv'
    'D3Mm3VAEEIB8oaO+zz///AkweP4Jbe5xJrkpSdeHORs7dixiDwEAdlj6cyZtuEkbhzo7efIk'
    'LvpAAIAdjvy4Tr6UOyHxTSW8dEbZhbGxsYg/BADYNdvv6NGjoqU/1fbjyoZRnz/EHgIALIZr'
    'vEEnAdKlP7eqoAtAiD0EANhgY5Sznj17inxTghW39EfpNQgAsAFHjhzRTtIdO3aI/LZo0YJd'
    '+iPbDwIAbADduOPaeVG3n6f1S3UBuaU/7TUg9hAAYDGVKlVil/5t27YV+d60aRMrLIg9BAB4'
    'rW/nxVXhWbFihcj366+/blouAYAAgAAwadIk7QS9efOmyG9kZCR7hyAxMRGxhwAAq6levTr7'
    'hpYm5XDZfnS3ANl+EADgtb6dF9d4Y/jw4SLfI0aMYI/8sPSHAAAbwF3FlRb4iImJYVcVCQkJ'
    'iD0EAFhN06ZNTWnnRWRnZ2v9bt++HbGHAAA71/SnPgkS31QjgGu0KqkYDCAAIEAcPnxYO0nX'
    'rFkj8tuuXTutX8oARLYfBADYgKFDh2onKdXlk/RCpExBSuxBth8EANgUuorLWXx8vClHfpQH'
    'gNhDAIANuHjxonaSUm8Eid/evXuzwiKpGAwgACBAzJkzRztBz5w5I/JLyUJcn8AhQ4Yg9hAA'
    'YDV169Y1LduP2nbpLCUlBdl+EABgNeHh4UZGRoYpDTe5isFUal2aSwAgACAArFy5UjtJU1NT'
    'RX7j4uLYVQVaq0MAgA1o1qwZO0kpGUjimxJ7dLZ69WrEHgIA7LD056xBgwamZPvduHED2X4Q'
    'AGAHDh06pJ2kixYtEvnt2LEjm+1Hdf8QewgAsGm2H+UBSN7QdH34zp07Wt+zZ89G7CEAwGvj'
    '2n70exLfly9f1volUUDsIQDABnDVd5OSkkxZVVCqb1RUFGIPAQBWk5ycbEoJrpo1a2rbqJMN'
    'GjQIsYcAAKvhGm/QG5q6/HoFFYMvXLjACgtiDwEAFkPXeKmCr8769u0r8v3pp5+yu/7URgzx'
    'hwAAi9mwYYN2ku7atUvk95VXXmE3FHHkBwEANqBz587sG1rScJOW/llZWVrfCxYsQOwhAMBq'
    'qArP/fv3tZO/fv36It9r167VTn66WISlPwQAeK1v53XgwAHtJJ01a5bId5cuXdhVRcOGDRF/'
    'CACwmmHDhmknKTX6kCz9Cd2qgoxaiCH2EABgg6W/Wbf8uESizMxMxB4CAOyw9M/JydFO0gED'
    'Boh8jxkzhm3nJa0cBCAAIAAsWbKE7bojyfarU6cOu/QfOHAgYg8BAFbTpk0b7QSlFYGkpj8J'
    'B5dIdPToUcQeAgDsUOCDq8JDuQAS33Suz9X2Q+whAMAG7Ny505QSXK1bt2Y3FJs3b47YQwCA'
    '1fTp00c7QakVl+TIjwp8cNl+8+fPR+whAMBqKlasqL2KS7f8KFdf8t3/zTffsLkEqOkPAQAW'
    'Q293unJrRlJO9+7d2aU/nQgg/hAAYDGjRo3STlBK1pH4pWQhXe0AMsowROwhAAigxVBnHS4f'
    'X5pIxBX4+OWXXxB7CAAEwGrotl12drZ2kvbo0UPke+LEiWxhT2ofjvhDACAANs3227x5s8gv'
    'fdtzS39q8Y3YQwAgABbDnctTEpD0lh/XxjstLQ2xhwBAAKyGNufoeE9nkiM/Yt26daywIPYQ'
    'AAiADeCO/L744gtTCnwg2w8CAAGwCcOHD2fbeUlKcFHtAO4OAWr7QQAgADYgJiZGexWX/l3t'
    '2rVFvr///ns22w+xhwBAAGyQ7UdXbnU2evRokW/a2ecMR34QAAiADeDO5aVJOdQNiDMU+IAA'
    'QAC89u3kSycBdFNPku13+vRpre8jR44g9hAACIDV0ASnQps6o117iW+6KMQd+UVHRyP+EAAI'
    'gNUsW7ZMO0nXr18v8kudfDmjG4CIPQQAAmAxzZo1005Q2vWX3sPnEolSU1MRewgABMBqSpUq'
    'xb6h6ThQ4psqA+uMCn6inRcEAAJgA7gjv/Hjx4v80i1BzmjFgdhDACAAFpOYmKidoMePHxdd'
    '9ImMjGQv+iDbDwIAAbABcXFx2qu49N1Px4ES33S0p7Pr168j9hAACIDXBu280tPTTWnnxTUJ'
    'JStfvjziDwGAAFjNwoULtRN0z549Ir9VqlRhd/379++P2EMAIABWU6tWLbbhpqSdF+0ZnDlz'
    'Ruv7hx9+QOwBBMBqaIJfvXpVW9izffv2It9Tp05la/tFREQg/gACYDWrVq3STtKVK1eK/NIV'
    'Yc5ee+01xB5AAKymUaNG7CSV+uYKe1KnH8QeQAC89q3pT62+JL537Nih9U0XiyQ3CAEEAAIQ'
    'ILhz+ZEjR4r89uzZkxWWJk2aIPYAAmA1I0aM0E7Sw4cPiy760Jm+rkko2dy5cxF7AAGwmqpV'
    'q7Jv6PDwcJHvS5cuIdsPQADszOXLl7WTtGPHjiK/n3zyCSssOPIDEAAbsHTpUu0kXb16tchv'
    'vXr1kO0HIAB2pnHjxtoJmpWVlXv/3ytoEkrlu81IIwYQAAhAAKDGG7rafrQ8b9Gihcg3be5x'
    'lYNw5AcgADZg48aNprTzatiwIZtIhCM/AAGw8dI/EA03uSO/xYsXI/YAAmA1tPvOLc+ltf24'
    'bD86ZZDsKQAIAAQgQFBij84GDRpkmNHOi04CGjRogNgDCIDVUEqvzo4dOybyGxYWxh75TZ48'
    'GbH3mteZ+VF69eoFAQB6qKkm94aW+r516xbbIhyx95rWmflxS05OhgAAPVRj34zS21OmTGH3'
    'FKKiohB7k6AmrI/b4MGDIQDgSaiQhxmlt+k0gVv69+vXD7H3mles1cF9FCAAgaRNmzbawUIl'
    'vyS3/Cjbj1v679u3D7E3Ed0dC0rgcshJCwQgkNl+3NK/bt26pqwqaEUgaRYCnm75T4KOUwAM'
    'DsOXnnujR48W+e3UqROb7Ve/fn3E3oIkLulJDgTAYXTp0kU7UM6fP29Im4Tm5ORofc+YMQOx'
    'N5k1a9Y4PdMSAiAlOjpam5JLpbcl2X60Z7Bz507tALxw4QI6+XqtqdlIRoIPAcAgyZ2kXG2/'
    '9957T+R74MCBbIGPOnXqYJKazNChQ1kBcFCqNQRAmh2ms4MHD4r80tudK+stLRoKvKKy6oEo'
    '2Q4BcABUupvruiNdVXCnCWlpaZicQSCvjVcIAAQgF25zTnoZZ9asWVq/9OdVrlwZEzQIcP0U'
    'yWhfBgLgcgFYsWKFdnDMnDlTfOzELT2lewrAN1q1apXn2//999+HALhZAKivnhlHfpTQw6X6'
    'HjhwAJMzSOzatStPAXDYKgwC4A9Ut5++8XVmVoEPWvpjYgaHatWqGflZuXLlIABuFQB6E5tx'
    'GYcr8EFGdf8wOa19vo+aw1KvIQDSc/nU1FSRX2rnRdd5dTZ9+nRMzCBBFZTzMwd+ikEAfCE2'
    'Nlab7ZednS3q5Etvk/3795uypwACt/P/m02bNg0C4DYBoEl69OhRU1JCuUQisri4OEzMIEF3'
    '+32xhIQECIDbBIDruUebdhK/kZGR7EDr06cPJqbN3v5k8fHxEAA3CQBX248y9aSpvlw7Lxz5'
    'BZd33nnHp8lPR7QOvIAFAchrklLfPjPeBPPnz9f6pT2FSpUqYWIGEW4D9nE7e/asgbLgLhKA'
    'ZcuWaQcCFeaU+G3UqBE7yLp164ZJGUR2795t+GqUIAQBcIkAtGvXTjsILl26JN5Q5Ex6nAj8'
    'o3Xr1oY/5sATAAiAv8vC0qVLi/ympKSYsqcA/IOy+a5du+aXANBLAQLgAgE4deqUdgD06NFD'
    '5PfDDz9kBxd9FmBiBq+IS175/tynH3VkggA4XAASExO1D3/Lli3ismGcSVuEA/+YMGEC+yyo'
    'sSoJvcNrAEAAuIsguqU/Lc+lS/+TJ0+ytf0wKYNHhw4d8lzmV61a1fjss8+0ZdggAA4WANqc'
    'S09P1w6K5s2bi3zrBtRvVqFCBUzMING+ffs8j/zGjBmT+99t3br1id/77rvvIABOFgCu5968'
    'efNEfmvUqOGmtFLb8vLLL7O1FsjoPsZvnZt0m4Pdu3eHADhVAGrVqsV+D0quflLlWDo2RDsv'
    'a+nbt2+ey376xKOuTvTfRkREuOn7HwJAV0AzMzO13XalpbeXLFmiHUzU4w9Lf/OhfZt169bl'
    'e7xXs2bNf/w/L730EgTATQKwatUq7QMfO3asyC8V8eCsbdu2mKAm06tXL7aZ6qNGnwa+bBJC'
    'ABwoAFwmGK0IJH7pvJgzB28m2eJ8n54p3afw5WJP165dfbqjsXfvXgiA0wSAvs91Rkt/SRtv'
    'gpqC6CwjI8OpySSWQnUT6Mq2L2/83yZ/586dtb6o6+/jlpSUBAFwmgCcOHFCOzi4geErgwcP'
    'RiffIED7M8nJycbp06f9SuelAqu1a9dm/brwk819AjBq1Cjtg96wYUPu2/9pobJhnFGzD4lv'
    't0GnLwTVS6Qc/HHjxrHJVL7a8ePH8z3V0RltDEIAHCIA1atXz7PnG8x5Rkt+Kr3my6eES4qA'
    'PMoUiQDcC7Uf+Ny5c5gRLrLly5fnll7zZWxQJqALezGOkwjA7VD6YVeuXIkZ4RKjlu1RUVHi'
    'fSHKI3C4AAyTCMCNUM/2g8Hyst/uBziYPhIByAiVH5RyuWEwf61ly5ZOF4CuEgG4CAGAOdVo'
    's9jhG4BEa4kAnIQAwJxqlFjkguzJaIkA/AgBgDnVqG+D1/n9EJ+VCMCmUPlB6fYdtX8CwFfq'
    '1avneAHwSEwtHyYgLRUAlwpA8eLFOyOIALhUAIoWLVoYQQQgZDnnkRqCCEDIMhwCAIBLUZ/w'
    'JQMhAIcRTABCkj+IBUCdBHRHIAEIPYoVK1YwEAJQCMEEIORY7QmEqVzpZ5SzHAQUgJDiL55A'
    'mXI2EwEFIKQ2AP8USAGog6ACEDKkeQJpMTExBZTTqwgsACHx9v8/T6BNOf4MwQXA9jxQlZGf'
    'DbgAqNOAPyC4ANieUx6zjJwjwADYF3V/579ME4AiRYr8J4IMgG353mO2UYIBAg2ALQk3XQDU'
    'XkAx2mhAsAGwFWs9wTL1hw1FwAGwDTnq6O+5oAlAREQE5QWcQ+AB8Nqh8m9bjwVWEMEHwHIO'
    'eawy9Ye3wAMAwDLOBeTOv1AEBuBBABB0stR9/6IeO5j6y8zGAwEgqN/9hT12MvWXGocHA4Dp'
    '3FZv/jIeO5r6y72u+BUPCQBTuKQo4bGzqaVJFBKFAAg4JxWFPKFi6i+7HQ8NADF3VZLPm55Q'
    'NPWX/4viGh4iAE/FToXXE8pWpkyZgkrBOuGzAACfOa3mTKzHaaZ+sHcUd/CAAdByR038Gh6n'
    'm/pBYxUbcGIAgDdbMV+V8fJ63GZhYWGFlOLFqwBMp80ODAbgEi4+vFH7ogf2d1PJDXTDkATh'
    'JcUU9esbGCjAIVxTx+NJalyXVr/+PWb70302lHh4+ShRBXKW+udyxZaHO6X7FPsBCCK7FdsU'
    'G9XkXuT9e9XsvurXjRRhmLEwGAwGg8FgMBgMBoPBYDAYDAaDwWAwGMwi+3/j335AwqeTgwAA'
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

PRECONFIGS_DIRNAME = "pre-configs"


def _is_config_bat(name):
    low = (name or "").lower()
    return low.endswith(".bat") and not low.startswith("service")


def _alt_sort_key(name):
    """Естественная сортировка: general, general (ALT), ... ALT2..ALT13."""
    m = re.search(r"ALT\s*(\d+)", name)
    if name.lower() == "general.bat":
        return (0, 0, name)
    if m:
        return (1, int(m.group(1)), name)
    if "ALT" in name:
        return (1, 1, name)
    return (2, 0, name)


# Каталоги, где конфигов заведомо нет (не сканируем рекурсией).
CONFIG_SKIP_DIRS = {"bin", "lists", "utils", "data", ".git", "__pycache__"}


def list_configs(zapret_root):
    """Конфиги как ОТНОСИТЕЛЬНЫЕ пути от корня zapret — рекурсивно везде,
    кроме служебных каталогов (bin/lists/utils/...).

    Дом по умолчанию — pre-configs/ ('pre-configs/general.bat'), но видны
    и сторонние паки где угодно ('df_confs/DiscordFix.bat'): их относительные
    пути резолвятся парсером от каталога самого bat. Все потребители
    открывают через os.path.join(zapret_root, bat).
    """
    if not zapret_root or not os.path.isdir(zapret_root):
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(zapret_root):
        try:
            dirnames[:] = sorted(
                d for d in dirnames
                if d.lower() not in CONFIG_SKIP_DIRS
                and not d.startswith("."))
        except Exception:
            pass
        for fn in sorted(filenames):
            if _is_config_bat(fn):
                out.append(os.path.relpath(os.path.join(dirpath, fn),
                                           zapret_root))

    def key(p):
        return (os.path.dirname(p).lower(),
                *_alt_sort_key(os.path.basename(p)))

    return sorted(out, key=key)


def display_bat(bat):
    """Короткое имя для UI: 'general (ALT)' или 'pack/custom'."""
    try:
        base = os.path.basename(bat).replace(".bat", "")
        parent = os.path.basename(os.path.dirname(bat or ""))
        if parent and parent.lower() != PRECONFIGS_DIRNAME:
            return f"{parent}\\{base}"
        return base
    except Exception:
        return (bat or "").replace(".bat", "")


def organize_configs(zapret_root):
    """Создать pre-configs/ и перенести туда все конфиги из корня.

    Идемпотентно: повторный вызов двигает только остатки. Одинаковые файлы
    схлопываются (дубль в корне удаляется), одноимённые разные получают
    суффикс ' (n)'. Возвращает (moved:int, msg:str).
    """
    if not zapret_root or not os.path.isdir(zapret_root):
        return 0, "папка не найдена"
    pre = os.path.join(zapret_root, PRECONFIGS_DIRNAME)
    try:
        os.makedirs(pre, exist_ok=True)
    except Exception as e:
        return 0, f"не создать {PRECONFIGS_DIRNAME}: {e}"
    moved = 0
    try:
        names = sorted(os.listdir(zapret_root))
    except Exception as e:
        return 0, f"не прочитать папку: {e}"
    for fn in names:
        src = os.path.join(zapret_root, fn)
        try:
            if not os.path.isfile(src) or not _is_config_bat(fn):
                continue
            dst = os.path.join(pre, fn)
            if os.path.abspath(src) == os.path.abspath(dst):
                continue
            if os.path.exists(dst):
                try:
                    with open(src, "rb") as f1, open(dst, "rb") as f2:
                        same = f1.read() == f2.read()
                except Exception:
                    same = False
                if same:
                    try:
                        os.remove(src)
                    except Exception:
                        pass
                    continue
                stem, ext = os.path.splitext(fn)
                i = 1
                while os.path.exists(dst):
                    i += 1
                    dst = os.path.join(pre, f"{stem} ({i}){ext}")
            shutil.move(src, dst)
            moved += 1
        except Exception:
            continue
    if moved:
        return moved, f"в {PRECONFIGS_DIRNAME} перенесено конфигов: {moved}"
    return 0, "конфиги уже в порядке"


def parse_targets(zapret_root):
    targets = []  # list of (name, url_or_ping)
    p = os.path.join(zapret_root, "utils", "targets.txt") if zapret_root else ""
    if p and os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except Exception:
            src = ""
    else:
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
ULTRA_SCREEN_TARGETS = ("DiscordMain", "YouTubeWeb")

# Кэш результатов отсева между запусками (в памяти)
_ULTRA_SCREEN_CACHE = {}


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


_BAT_SET_RE = re.compile(
    r'^\s*set\s+(?:"([^"=]+?)\s*=\s*(.*)"|([^=\s]+?)\s*=\s*(.*))\s*$',
    re.IGNORECASE)


def _bat_expand_vars(text, env):
    """Раскрыть %VAR% и !VAR! по env (регистронезависимо), до 5 проходов."""
    try:
        for _ in range(5):
            new = re.sub(r"%([^%]+)%",
                         lambda m: env.get(m.group(1).upper(), m.group(0)),
                         text)
            new = re.sub(r"!([^!]+)!",
                         lambda m: env.get(m.group(1).upper(), m.group(0)),
                         new)
            if new == text:
                break
            text = new
    except Exception:
        pass
    return text


def _bat_collect_env(lines, batdir):
    """Плоский прогон bat: set-переменные с учётом if exist/defined.

    Файлы коллекции — straight-line код (проверено на 157 bat: ни меток,
    ни goto, ни сабрутин, ни for-блоков с set). Возвращает {NAME: value}
    с уже раскрытыми значениями.
    """
    env = {}
    try:
        for k, v in os.environ.items():
            try:
                env[str(k).upper()] = v
            except Exception:
                pass
    except Exception:
        pass
    stack = []  # фреймы [cond, parent_active]

    def active():
        try:
            return all(c and p for c, p in stack)
        except Exception:
            return False

    for raw_line in lines:
        try:
            s = raw_line.strip()
            if not s or s.startswith("::") or s.startswith("@"):
                continue
            # --- блоки if ---
            m = re.match(r"^if\s+(not\s+)?exist\s+(.+?)\s*\($", s,
                         re.IGNORECASE)
            if m:
                parent = active()
                try:
                    path = m.group(2).strip().strip('"')
                    path = path.replace("%~dp0", batdir)
                    path = _bat_expand_vars(path, env)
                    hit = os.path.exists(path)
                    if m.group(1):
                        hit = not hit
                except Exception:
                    hit = False
                stack.append([hit, parent])
                continue
            m = re.match(r"^if\s+(not\s+)?defined\s+(\w+)\s*\($", s,
                         re.IGNORECASE)
            if m:
                parent = active()
                try:
                    hit = (m.group(2).upper() in env)
                    if m.group(1):
                        hit = not hit
                except Exception:
                    hit = False
                stack.append([hit, parent])
                continue
            if re.match(r"^\)\s*else\s*\($", s, re.IGNORECASE):
                if stack:
                    cond, parent = stack[-1]
                    stack[-1] = [(not cond), parent]
                continue
            if s == ")":
                if stack:
                    stack.pop()
                continue
            if re.match(r"^if\s+.*\($", s, re.IGNORECASE):
                # неизвестное условие — тело пропускаем (консервативно)
                stack.append([False, active()])
                continue
            # --- присваивания ---
            m = _BAT_SET_RE.match(s)
            if m and active():
                name = (m.group(1) or m.group(3) or "").strip().upper()
                val = (m.group(2) if m.group(1) is not None
                       else m.group(4) or "")
                try:
                    val = val.rstrip()
                    val = val.replace("%~dp0", batdir)
                    val = _bat_expand_vars(val, env)
                except Exception:
                    pass
                if not name or "/" in name or "\\" in name:
                    continue
                if val == "":
                    env.pop(name, None)
                else:
                    env[name] = val
        except Exception:
            continue
    return env


def build_service_args(zapret_root, bat_name):
    """Собирает аргументы winws.exe из bat — упрощённый аналог service.bat.

    Понимает сторонние паки: set-переменные (BIN/LIST_PATH/...),
    if exist/defined-ветки, %~dp0 от КАТАЛОГА САМОГО bat (важно для
    подпапок: pre-configs/df_confs/.. разрешается верно).
    """
    fp = os.path.join(zapret_root, bat_name)
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
    except Exception as e:
        return None, f"Не могу прочитать {bat_name}: {e}"
    # склеить строки с ^
    raw = raw.replace("^\r\n", " ").replace("^\n", " ")
    lines = raw.splitlines()
    batdir = os.path.dirname(os.path.abspath(fp)) + os.sep
    env = _bat_collect_env(lines, batdir)
    # найти всё после winws.exe
    args_parts = []
    capturing = False
    for line in lines:
        if "winws.exe" in line.lower():
            idx = line.lower().find("winws.exe") + len("winws.exe")
            tail = line[idx:].strip()
            # убрать кавычку начала
            if tail.startswith('"'):
                tail = tail[1:]
            if "--" in tail:
                # строка с аргументами — новый (единственный) блок захвата
                capturing = True
                args_parts = [tail]
            elif not capturing:
                # первая строка запуска, аргументы — дальше
                capturing = True
            # упоминание в taskkill/echo без аргументов посреди захвата —
            # игнорируем, захват не трогаем
            continue
        if not capturing:
            continue
        s = line.strip()
        low = s.lower()
        # конец блока аргументов: дальше служебные команды bat, а не winws
        if low.startswith(("pause", "exit", "goto ", "goto:", ":eof",
                           "popd", "endlocal", "title ", "color ",
                           "timeout ", "choice ", "cls")):
            break
        if not s or s.startswith("::") or low.startswith("@echo") or low.startswith("cd ") \
           or low.startswith("call ") or low.startswith("set ") or low.startswith("echo"):
            # bat мог закончиться; но аргументы обычно в одном start-блоке
            if "winws" in low or s.startswith("--") or s.startswith('"--'):
                args_parts.append(s)
            continue
        args_parts.append(s)
    # caret-эскейпы по правилам cmd: ^X -> буквальный X (^! -> !, ^^ -> ^,
    # ^& -> & ...). Старый blanket-replace("^", " ") превращал ^! в " !",
    # и winws читал пустое имя файла (could not read с пустым именем).
    args = " ".join(args_parts)
    args = re.sub(r"\^([\s\S])", r"\1", args).rstrip("^").strip()
    # отрезать хвосты обёртки start/cmd: висячие кавычки, скобки, & pause...
    # (без rstrip('"'): закрывающая кавычка последнего аргумента обязана жить)
    args = re.sub(r"\s+", " ", args).strip()
    args = re.sub(r'\s+[&|)]+\s*(pause|exit|goto|popd|endlocal)?\s*$', "", args,
                  flags=re.IGNORECASE).strip()
    if not args or "--" not in args:
        return None, "Не найдены аргументы winws в bat-файле"
    # раскрытие: %~dp0 -> каталог bat, затем set-переменные
    args = args.replace("%~dp0", batdir)
    args = _bat_expand_vars(args, env)
    # совместимость: названия без учёта регистра уже раскрыты выше;
    # запасные значения, если bat их использовал, но не определил
    BIN = os.path.join(zapret_root, "bin") + os.sep
    LISTS = os.path.join(zapret_root, "lists") + os.sep
    tcp, udp = get_game_filter(zapret_root)
    args = args.replace("%BIN%", BIN).replace("%LISTS%", LISTS)
    args = args.replace("%GameFilterTCP%", tcp).replace("%GameFilterUDP%", udp).replace("%GameFilter%", tcp)
    # как cmd: неопределённые %VAR% -> пусто (%% -> проценты).
    # !...! НЕ трогаем: delayed expansion в этих bat нет, там ! всегда
    # буквальный (иначе убьём значения вроде --fake-tls=! из ^!).
    try:
        args = args.replace("%%", "\x00")
        args = re.sub(r"%[^%\s]+%", "", args)
        args = args.replace("\x00", "%")
    except Exception:
        pass
    # убрать остатки start-префиксов
    args = re.sub(r'^["\s]*', "", args)
    args = _fallback_missing_files(args, zapret_root)
    return args, ""


def _fallback_missing_files(args, zapret_root):
    """Файлы, которых нет по указанному пути, поискать в корне zapret.

    Покрывает переехавшие bat (их %~dp0 указывает мимо ресурсов):
    pre-configs\\general.bat просит pre-configs\\lists\\X, а лежит он в
    root\\lists\\. Не нашлось и там — оставить как есть: winws честно
    скажет какой файл (такие конфиги биты и под service.bat).
    """
    try:
        bin_dir = os.path.join(zapret_root, "bin")
        lists_dir = os.path.join(zapret_root, "lists")

        def fix(m):
            q, path = m.group(1), m.group(2)
            try:
                if not path or os.path.exists(path):
                    return m.group(0)
                # относительный — сначала от bin/ (там cwd у winws)
                if not os.path.isabs(path):
                    cand = os.path.normpath(os.path.join(bin_dir, path))
                    if os.path.exists(cand):
                        return m.group(0)  # winws сам разрулит
                base = os.path.basename(path)
                if base:
                    for d in (lists_dir, bin_dir):
                        try:
                            cand = os.path.join(d, base)
                            if os.path.exists(cand):
                                return q + cand + q
                        except Exception:
                            pass
            except Exception:
                pass
            return m.group(0)

        # квотированные значения-пути: "..." с \ или / внутри
        args = re.sub(r'(")([^"]*[\\/][^"]*)(")',
                      lambda m: fix(m), args)
    except Exception:
        pass
    return args


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


def _poll_winws(timeout_s):
    """Быстрая проверка «процесс есть» для стартовой цепочки (без settle)."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            if winws_running():
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _winws_cmdline(zapret_root, args):
    """Командная строка ОДНОЙ строкой: '"exe" args' — байт в байт как её
    собирает `start` в service.bat.

    Это критично: winws сам разбирает GetCommandLineW и ломается, если exe
    не в кавычках (список Popen без пробелов в пути кавычки не ставит —
    тогда winws склеивает значения с соседними аргументами:
    cannot access hostlist file '...txt" --hostlist="...'). Строка с
    квотированным exe парсится им верно (проверено: 9 профилей + все листы).
    """
    exe = os.path.join(zapret_root, "bin", "winws.exe")
    return exe, '"%s" %s' % (exe, args)


def _launch_direct(zapret_root, args):
    """Попытка 1: winws.exe напрямую, полностью скрыто (без окон и миганий).

    Возвращает Popen или None (для присмотра и добивания).
    """
    exe, cmdline = _winws_cmdline(zapret_root, args)
    if not os.path.exists(exe):
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return subprocess.Popen(
        cmdline, cwd=os.path.join(zapret_root, "bin"),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, startupinfo=si,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _bat_cmd_runnable(zapret_root, bat_name):
    """Можно ли запускать bat как скрипт (для cmd-фолбэка).

    Его %~dp0-вычисления должны указывать на существующие bin/lists —
    иначе будет системный диалог 'не найден winws.exe' (как с bat,
    переехавшими в pre-configs: их %~dp0bin ведёт в пустоту).
    """
    try:
        fp = os.path.join(zapret_root, bat_name)
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            low = f.read().lower()
        d = os.path.dirname(os.path.abspath(fp))
        if re.search(r"%~dp0\s*\\?\s*\.\.", low):
            base = os.path.dirname(d)  # стиль %~dp0..\bin (паки глубиной 1)
        elif "%~dp0" in low:
            base = d  # стиль %~dp0bin (bat обязан лежать рядом с bin/)
        else:
            return True  # без %~dp0 — расположение неважно
        return os.path.exists(os.path.join(base, "bin", "winws.exe"))
    except Exception:
        return False


def _kill_proc(p):
    try:
        if p is not None and p.poll() is None:
            p.kill()
    except Exception:
        pass


def _launch_cmd_bat(zapret_root, bat_name, hidden):
    """Попытка через настоящий bat (переменные раскрывает сам cmd).

    Возвращает Popen или None. Внимание: висящий на pause/меню cmd сам не
    умрёт — владелец обязан прибить его при неудаче (см. цепочку ниже).
    hidden=True: консоль скрыта; False: свёрнута (как service.bat).
    """
    fp = os.path.join(zapret_root, bat_name)
    if not os.path.exists(fp):
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0 if hidden else 6  # SW_HIDE / minimized
    return subprocess.Popen(
        ["cmd.exe", "/c", fp], cwd=zapret_root,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, startupinfo=si,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def start_winws_hidden(zapret_root, bat_name):
    """Запуск конфига: сначала скрыто напрямую, иначе — через bat-консоль.

    Прямой скрытый запуск не оставляет окон и не мигает. Каждый шаг
    проверяется появлением процесса; висящие cmd (pause/меню) прибиваются,
    чтобы не копились невидимые зомби. Шаги 2-3 пропускаются, если bat
    нельзя запускать как скрипт оттуда, где он лежит (его %~dp0 ведёт
    мимо bin/ — иначе вылезет системный диалог 'не найден winws.exe').
    Возвращает True, если процесс в итоге запущен.
    """
    procs = []
    try:
        args, _err = build_service_args(zapret_root, bat_name)
    except Exception:
        args = None
    # 1. прямой скрытый (идеал: ни окон, ни миганий)
    if args:
        try:
            p = _launch_direct(zapret_root, args)
            if p is not None:
                procs.append(p)
                if _poll_winws(2.0):
                    return True
        except Exception:
            pass
        try:
            run_log_write(f"  {bat_name}: прямой запуск пуст — пробую через bat")
        except Exception:
            pass
        stop_winws()
        time.sleep(0.3)
    else:
        try:
            run_log_write(f"  {bat_name}: парсер пуст — только запуск через bat")
        except Exception:
            pass
    cmd_ok = _bat_cmd_runnable(zapret_root, bat_name)
    if not cmd_ok:
        try:
            run_log_write(f"  {bat_name}: bat нельзя запускать как скрипт "
                          f"отсюда (%~dp0) — только прямой запуск")
        except Exception:
            pass
    # 2. настоящий bat в скрытой консоли (cmd сам раскрывает переменные)
    if cmd_ok:
        try:
            p = _launch_cmd_bat(zapret_root, bat_name, hidden=True)
            if p is not None:
                procs.append(p)
                if _poll_winws(2.5):
                    _kill_proc(p)  # консоль-родитель больше не нужен
                    return True
                _kill_proc(p)  # висящий на pause/меню — прибить
        except Exception:
            pass
        try:
            stop_winws()
        except Exception:
            pass
        time.sleep(0.3)
        # 3. как service.bat: bat в свёрнутой консоли (мигнёт, но запустится)
        try:
            p = _launch_cmd_bat(zapret_root, bat_name, hidden=False)
            if p is not None:
                procs.append(p)
                if _poll_winws(3.0):
                    try:
                        run_log_write(f"  {bat_name}: запущен через свёрнутую консоль")
                    except Exception:
                        pass
                    _kill_proc(p)
                    return True
                _kill_proc(p)
        except Exception:
            pass
    for p in procs:
        _kill_proc(p)
    return False


def start_bat_minimized(zapret_root, bat_name):
    """Совместимость: то же, что шаг 2 стартовой цепочки (скрытая консоль)."""
    try:
        return bool(_launch_cmd_bat(zapret_root, bat_name, hidden=True))
    except Exception:
        return False


def winws_running():
    _, out = run_cmd(["tasklist", "/FI", "IMAGENAME eq winws.exe"], timeout=8)
    return "winws.exe" in out.lower()


def wait_winws_alive(timeout_s=6.0, poll_s=0.5):
    """Ждать появления winws в tasklist (для фоновых потоков; блокирует)."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            if winws_running():
                return True
        except Exception:
            pass
        time.sleep(poll_s)
    return False


def winws_probe_output(zapret_root, bat_name, timeout_s=4.0):
    """Диагностический запуск winws с перехватом вывода (без окна).

    Скрытый боевой запуск при падении молчит (DEVNULL) — и приложение может
    только гадать («нужны права администратора?»). Пробник запускает ТУ ЖЕ
    командную строку, но с трубами: если winws падает сразу, в выводе будет
    настоящая причина (битый путь hostlist, драйвер, занятый WinDivert...).
    Возвращает текст вывода; переживший таймаут процесс гасится.
    """
    try:
        args, err = build_service_args(zapret_root, bat_name)
        if not args:
            return f"парсер: {err}"
        exe, cmdline = _winws_cmdline(zapret_root, args)
        if not os.path.exists(exe):
            return f"нет файла: {exe}"
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # окна всё равно нет, но вывод — в трубу
        try:
            p = subprocess.Popen(
                cmdline, cwd=os.path.join(zapret_root, "bin"),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, startupinfo=si,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                text=True, errors="ignore")
        except OSError as e:
            # 740 = нужен админ (манифест winws), 2 = нет файла и т.п.
            return f"запуск невозможен: {e}"
        try:
            out, _ = p.communicate(timeout=timeout_s)
            out = (out or "").strip()
            if not out:
                out = f"(пустой вывод, код выхода {p.returncode})"
            # важно именно НАЧАЛО (там причина), хвост — для контекста
            if len(out) > 1600:
                out = out[:1200] + "\n…[обрезано]…\n" + out[-400:]
            return out
        except subprocess.TimeoutExpired:
            try:
                p.kill()
            except Exception:
                pass
            try:
                p.communicate(timeout=3)
            except Exception:
                pass
            return (f"<процесс жив (пережил {timeout_s:g} c) — "
                    f"командная строка в порядке>")
    except Exception as e:
        return f"диагностика не удалась: {e}"


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


def hide_native_caption(root):
    """Прячем системную шапку (для Win10, где DWM-тинт невозможен).

    Только снимаем WS_CAPTION со стилей ВНЕШНЕГО окна. Subclass НЕ ставим:
    любой хук оконной процедуры ломает восстановление/разворачивание окна.
    Перетаскивание — ручное (Tk-бинды + WinAPI), ресайз рамкой, снап
    и таскбар-тоггл — нативные. Возвращает True, если капшен реально снят.
    """
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = toplevel_hwnd(root)
        if not hwnd:
            return False
        style = user32.GetWindowLongW(hwnd, -16)
        if not (style & 0x00C00000):
            return True
        user32.SetWindowLongW(hwnd, -16, style & ~0x00C00000)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
        return not bool(user32.GetWindowLongW(hwnd, -16) & 0x00C00000)
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

    def _wait_winws_logged(self, bat, timeout_s, log_cb, fast=False):
        """Ждать winws; при первом за проверку промахе — снять диагноз
        пробником (настоящий вывод winws) один раз, не по каждому конфигу."""
        if wait_winws_ready(timeout_s, fast=fast):
            return True
        if log_cb and not getattr(self, "_diag_done", False):
            self._diag_done = True
            try:
                diag = winws_probe_output(self.cfg.get("zapret_root", ""),
                                          bat, timeout_s=2.5)
                if diag:
                    log_cb(f"  диагностика {bat}: {diag[:300]}")
            except Exception:
                pass
        return False

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
        только пинг 2 ключевых целей, 1 повтор, 2с таймаут, фоновый приоритет."""
        targets = parse_targets(self.cfg["zapret_root"])
        targets = quick_filter(targets)
        # Только пинг для мониторинга — быстрее и достаточно для детектирования проблем
        ping_targets = [(n, f"PING:{split_host(v)[0]}") for n, v in targets]
        timeout = 2
        ping_thr = int(self.cfg.get("ping_threshold_ms", 5000))
        eco = thread_bg_mode(True)
        try:
            results = self.probe_many(ping_targets, timeout, ping_thr, 1, 4)
        finally:
            if eco:
                thread_bg_mode(False)
        # Для мониторинга смотрим только пинги
        bad_ping = sum(1 for r in results if not r["ping_ok"])
        # Блокировка если ≥50% целей не пингуются
        blocked = bad_ping >= max(2, len(results) // 2)
        return {"results": results, "ok_http": 0, "fail_http": 0,
                "bad_ping": bad_ping, "dpi_block": False,
                "ping_problem": blocked, "blocked": blocked}

    def check_configs(self, bat_list, progress_cb=None, log_cb=None, boost=False):
        self.running = True
        self.cancel_flag.clear()
        all_targets = parse_targets(self.cfg["zapret_root"])
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
        self._diag_done = False  # диагноз пробника — один раз за проверку
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
        """Обычный последовательный замер каждого конфига.
        Оптимизирован: сортировка по best_scores, уменьшенные таймауты."""
        # Сортируем: сначала конфиги с лучшими прошлыми результатами
        # (basename-фолбэк: старые очки хранились голыми именами до переезда)
        scores = self.cfg.get("best_scores", {})

        def _score(b):
            try:
                return scores.get(b, scores.get(os.path.basename(b), 0))
            except Exception:
                return 0

        bat_list = sorted(bat_list, key=lambda b: -_score(b))

        # остановить всё перед тестами
        stop_winws()
        time.sleep(0.1)
        dead_chain = 0
        for idx, bat in enumerate(bat_list):
            if self.cancel_flag.is_set():
                break
            if log_cb:
                log_cb(f"[{idx+1}/{total}] Запуск {bat} …")
            t0 = time.time()
            start_winws_hidden(self.cfg["zapret_root"], bat)
            if not self._wait_winws_logged(bat, 5.0, log_cb):
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
            # circuit breaker: три подряд полных глухаря
            if ok == 0 and ping_ok_n == 0 and fail > 0:
                dead_chain += 1
                if dead_chain >= 3:
                    if log_cb:
                        log_cb("⛔ Три конфига подряд без единого пакета — сеть упала. Прерываю.")
                    self.abort_reason = "deadnet"
                    stop_winws()
                    break
            else:
                dead_chain = 0
            stop_winws()
            time.sleep(0.1)

    def _ultra_loop(self, bat_list, targets, timeout, ping_thr, repeat,
                    workers, turbo, all_results, progress_cb, log_cb):
        """УЛЬТРА-турнир: дешёвый отсев всех -> точный замер топ-N.

        Оптимизации:
        - Приоритизация конфигов по best_scores из прошлых запусков
        - Отсев только по пингу (без HTTP) — в 3-5 раз быстрее
        - Кэш результатов отсева между запусками
        - Ранний выход при идеальном скоре
        - Уменьшенные таймауты и паузы
        """
        screen = [(n, v) for n, v in targets if n in ULTRA_SCREEN_TARGETS]
        if len(screen) < 2:
            screen = targets[:2]
        # Только пинг для отсева — HTTP не нужен, достаточно ping_ok
        screen_ping_only = [(n, v) for n, v in screen if v.startswith("PING:")]
        if not screen_ping_only:
            # если нет PING целей, берём хосты из HTTP целей
            screen_ping_only = [(n, f"PING:{split_host(v)[0]}") for n, v in screen]

        total = len(bat_list)
        n_fin = min(ULTRA_FINALISTS, total)
        grand = total + n_fin

        # Сортируем конфиги: сначала те, у кого были хорошие scores
        scores = self.cfg.get("best_scores", {})

        def _score2(b):
            try:
                return scores.get(b, scores.get(os.path.basename(b), 0))
            except Exception:
                return 0

        order = sorted(bat_list, key=lambda b: -_score2(b))

        if log_cb:
            log_cb(f"Режим УЛЬТРА: отсев {total} конфигов (только пинг, таймаут 2с), "
                   f"затем точный замер топ-{n_fin}."
                   + (" ТУРБО: приоритет процесса повышен." if turbo else ""))
            log_cb("Почему не все сразу: конфиги делят один WinDivert — "
                   "параллельный запуск испортил бы замер.")

        stop_winws()
        time.sleep(0.1)
        dead_chain = 0
        perfect_score = len(screen_ping_only) * 10 + len(screen_ping_only)  # max possible

        # --- фаза 1: отсев (только пинг) ---
        for idx, bat in enumerate(order):
            if self.cancel_flag.is_set():
                break
            if log_cb:
                log_cb(f"[отсев {idx+1}/{total}] {bat} …")
            t0 = time.time()

            # Проверка кэша
            cache_key = f"{bat}:{self.cfg['zapret_root']}"
            if cache_key in _ULTRA_SCREEN_CACHE:
                cached = _ULTRA_SCREEN_CACHE[cache_key]
                ping_ok_n = cached["ping_ok"]
                score = cached["score"]
                all_results[bat] = {"ok": 0, "fail": 0, "ping_ok": ping_ok_n,
                                    "rows": [], "started": True, "score": score,
                                    "final": False}
                if log_cb:
                    log_cb(f"  {bat}: кэш pingOK={ping_ok_n} score={score} (~0 c)")
                if progress_cb:
                    progress_cb(idx + 1, grand, bat, score, all_results[bat])
                if score >= perfect_score:
                    if log_cb:
                        log_cb(f"  ⚡ Идеальный скор — прыгаем в финал!")
                    break
                continue

            start_winws_hidden(self.cfg["zapret_root"], bat)
            if not self._wait_winws_logged(bat, 3.0, log_cb, fast=True):
                if log_cb:
                    log_cb(f"  {bat}: winws не запустился — пропуск")
                all_results[bat] = {"ok": 0, "fail": len(screen_ping_only), "rows": [],
                                    "started": False, "score": -1, "final": False}
                if progress_cb:
                    progress_cb(idx + 1, grand, bat, -1, all_results[bat])
                continue

            # Только пинг, 1 повтор, таймаут 2с, больше потоков
            rows = self.probe_many(screen_ping_only, 2, ping_thr, 1, min(16, workers * 2))
            ping_ok_n = sum(1 for r in rows if r["ping_ok"])
            score = ping_ok_n * 11  # вес пинга выше для отсева
            all_results[bat] = {"ok": 0, "fail": 0, "ping_ok": ping_ok_n,
                                "rows": rows, "started": True, "score": score,
                                "final": False}

            # Кэшируем результат отсева
            _ULTRA_SCREEN_CACHE[cache_key] = {"ping_ok": ping_ok_n, "score": score}

            if log_cb:
                log_cb(f"  {bat}: отсев pingOK={ping_ok_n}/{len(screen_ping_only)} score={score} (~{time.time()-t0:.1f} c)")
            if progress_cb:
                progress_cb(idx + 1, grand, bat, score, all_results[bat])

            if ping_ok_n == 0:
                dead_chain += 1
                if dead_chain >= 3:
                    if log_cb:
                        log_cb("⛔ Три конфига подряд без пинга — сеть упала. Прерываю.")
                    self.abort_reason = "deadnet"
                    stop_winws()
                    return
            else:
                dead_chain = 0

            # Ранний выход: если набрали макс. скор, дальше отсев не нужен
            if score >= perfect_score:
                if log_cb:
                    log_cb(f"  ⚡ Идеальный пинг — остальные в финал без отсева")
                break

            stop_winws()
            time.sleep(0.1)

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
            if not self._wait_winws_logged(bat, 5.0, log_cb):
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
            time.sleep(0.1)


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


class ToolTip:
    """Подсказка при наведении с удержанием: всплывает через ~0.6 с.

    Только stdlib (Toplevel + after). Привязывается к любому виджету:
    add_tooltip(widget, text). Текст с переносами (wraplength).
    """

    def __init__(self, widget, text, delay_ms=600):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after = None
        self._tip = None
        try:
            widget.bind("<Enter>", self._schedule, add="+")
            widget.bind("<Leave>", self._hide, add="+")
            widget.bind("<ButtonPress-1>", self._hide, add="+")
        except Exception:
            pass

    def _schedule(self, _e=None):
        self._hide()
        try:
            self._after = self.widget.after(self.delay_ms, self._show)
        except Exception:
            pass

    def _show(self, _e=None):
        self._after = None
        if self._tip is not None:
            return
        try:
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return
        try:
            tip = tk.Toplevel(self.widget)
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)
            tip.configure(bg=BORDER)
            frm = tk.Frame(tip, bg=CARD2, padx=10, pady=8)
            frm.pack(fill="both", expand=True, padx=1, pady=1)
            tk.Label(frm, text=self.text, bg=CARD2, fg=TEXT, font=(FONT, 9),
                     wraplength=300, justify="left").pack()
            tip.update_idletasks()
            try:
                sw = tip.winfo_screenwidth()
                ww = tip.winfo_reqwidth()
                if x + ww > sw - 10:
                    x = max(10, sw - ww - 10)
            except Exception:
                pass
            tip.geometry(f"+{x}+{y}")
            self._tip = tip
        except Exception:
            pass

    def _hide(self, _e=None):
        try:
            if self._after is not None:
                try:
                    self.widget.after_cancel(self._after)
                except Exception:
                    pass
                self._after = None
        except Exception:
            pass
        try:
            t, self._tip = self._tip, None
            if t is not None:
                t.destroy()
        except Exception:
            self._tip = None


def add_tooltip(widget, text, delay_ms=600):
    """Навесить подсказку «наведи и подержи» на виджет (или список виджетов)."""
    try:
        widgets = list(widget) if isinstance(widget, (list, tuple)) else [widget]
        for w in widgets:
            if w is not None:
                ToolTip(w, text, delay_ms)
    except Exception:
        pass
    return widget


class Toggle(tk.Canvas):
    """Тумблер в духе Synapse/WeMod. API как у Checkbutton: variable=, command=.

    Клик — flip + command. Программная смена variable подхватывается через
    trace (как set_all_checks). Цвета читаются из палитры при отрисовке.
    """

    def __init__(self, parent, variable=None, command=None, width=46,
                 height=26, **kw):
        self._var = variable if variable is not None else tk.BooleanVar(value=False)
        self._command = command
        self._bw = max(34, int(width))
        self._bh = max(20, int(height))
        self._hover = False
        self._trace = None
        try:
            bg0 = parent.cget("background")
        except Exception:
            bg0 = BG
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("bd", 0)
        super().__init__(parent, width=self._bw, height=self._bh, bg=bg0, **kw)
        self.bind("<Enter>", lambda _e: self._set_hover(True), add="+")
        self.bind("<Leave>", lambda _e: self._set_hover(False), add="+")
        self.bind("<Button-1>", self._flip, add="+")
        try:
            self.configure(cursor="hand2")
        except Exception:
            pass
        try:
            self._trace = self._var.trace_add("write", lambda *_a: self._draw())
        except Exception:
            self._trace = None
        self._draw()
        track_themed(self)

    def _set_hover(self, v):
        self._hover = bool(v)
        self._draw()

    def get(self):
        try:
            return bool(self._var.get())
        except Exception:
            return False

    def set(self, val):
        try:
            self._var.set(bool(val))
        except Exception:
            pass
        self._draw()

    def _flip(self, _e=None):
        try:
            self._var.set(not bool(self._var.get()))
        except Exception:
            pass
        self._draw()
        if callable(self._command):
            try:
                self._command()
            except Exception:
                pass
        return "break"

    def _draw(self):
        try:
            if not self.winfo_exists():
                return
            self.delete("all")
            w, h = self._bw, self._bh
            on = self.get()
            r = h // 2
            if on:
                track = ACCENT_HOVER if self._hover else ACCENT
                knob_c = "white"
            else:
                track = BORDER if not self._hover else MUTED
                knob_c = MUTED if not self._hover else TEXT
            self.create_polygon(_round_points(1, 1, w - 1, h - 1, r - 1),
                                smooth=True, splinesteps=8,
                                fill=track, outline="")
            kr = r - 4
            cx = (w - r - 1) if on else (r + 1)
            cy = h // 2
            self.create_oval(cx - kr, cy - kr, cx + kr, cy + kr,
                             fill=knob_c, outline="")
            self.configure(cursor="hand2")
        except Exception:
            pass

    def apply_theme(self):
        try:
            self.configure(bg=self.master.cget("background"))
        except Exception:
            pass
        self._draw()


class Segmented(tk.Canvas):
    """Сегмент-контроль (Быстрый | Полный | Ультра). variable хранит КЛЮЧ."""

    def __init__(self, parent, options, variable, command=None, height=32,
                 font=None, **kw):
        # options: [(key, label), ...]
        self._opts = list(options or [("a", "A")])
        self._var = variable
        self._command = command
        self._font = font or (FONT, 10, "bold")
        self._h = max(26, int(height))
        self._hover = -1
        try:
            _f = tkfont.Font(font=self._font)
            widths = [_f.measure(lbl) for _k, lbl in self._opts]
        except Exception:
            widths = [len(lbl) * 9 for _k, lbl in self._opts]
        self._seg_w = max(widths) + 28 if widths else 120
        self._bw = self._seg_w * len(self._opts) + 4
        try:
            bg0 = parent.cget("background")
        except Exception:
            bg0 = BG
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("bd", 0)
        super().__init__(parent, width=self._bw, height=self._h, bg=bg0, **kw)
        self.bind("<Enter>", lambda _e: None, add="+")
        self.bind("<Motion>", self._on_move, add="+")
        self.bind("<Leave>", lambda _e: self._on_leave(), add="+")
        self.bind("<Button-1>", self._on_click, add="+")
        try:
            self.configure(cursor="hand2")
        except Exception:
            pass
        try:
            self._var.trace_add("write", lambda *_a: self._draw())
        except Exception:
            pass
        self._draw()
        track_themed(self)

    def _idx_at(self, x):
        i = int((x - 2) // self._seg_w)
        if 0 <= i < len(self._opts):
            return i
        return -1

    def _on_move(self, e):
        self._hover = self._idx_at(e.x)
        self._draw()

    def _on_leave(self):
        self._hover = -1
        self._draw()

    def _on_click(self, e):
        i = self._idx_at(e.x)
        if 0 <= i < len(self._opts):
            try:
                self._var.set(self._opts[i][0])
            except Exception:
                pass
            self._draw()
            if callable(self._command):
                try:
                    self._command()
                except Exception:
                    pass
        return "break"

    def _draw(self):
        try:
            if not self.winfo_exists():
                return
            self.delete("all")
            w, h = self._bw, self._h
            r = 9
            self.create_polygon(_round_points(1, 1, w - 1, h - 1, r),
                                smooth=True, splinesteps=8,
                                fill=CARD2, outline=BORDER)
            try:
                cur = self._var.get()
            except Exception:
                cur = None
            for i, (key, lbl) in enumerate(self._opts):
                x0 = 2 + i * self._seg_w
                x1 = x0 + self._seg_w
                if key == cur:
                    self.create_polygon(
                        _round_points(x0 + 1, 4, x1 - 1, h - 4, 7),
                        smooth=True, splinesteps=8, fill=ACCENT, outline="")
                    fg = "white"
                else:
                    fg = TEXT if i == self._hover else MUTED
                self.create_text((x0 + x1) // 2, h // 2, text=lbl,
                                 fill=fg, font=self._font)
        except Exception:
            pass

    def apply_theme(self):
        try:
            self.configure(bg=self.master.cget("background"))
        except Exception:
            pass
        self._draw()


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
            self._chrome_ok = hide_native_caption(root)
        except Exception:
            self._chrome_ok = False
        root.bind("<Map>", self._on_map_chrome, add="+")
        # смешная опция — только ПОСЛЕ отрисовки окна: сначала интерфейс,
        # потом гифки (иначе декодер делит CPU с первичной раскладкой
        # и строки/элементы ползут по 8 секунд)
        self._silly_applied = False
        self._silly_map_fired = False
        root.bind("<Map>", self._on_map_silly_ready, add="+")
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
        # resource monitor
        self.start_resource_monitor()
        # страховка: если <Map> так и не придёт — включить опцию позже
        try:
            self.root.after(8000, self._apply_silly_deferred)
        except Exception:
            pass

    def _on_map_chrome(self, _e=None):
        # Tk возвращает WS_CAPTION при первом показе — снять снова.
        # Только стиль, без subclass (он ломал restore/maximize).
        try:
            if hide_native_caption(self.root):
                self._chrome_ok = True
        except Exception:
            pass

    def _on_map_silly_ready(self, _e=None):
        """Окно отрисовалось — через паузу можно включать смешную опцию."""
        try:
            if self._silly_map_fired:
                return
            self._silly_map_fired = True
            self.root.after(1500, self._apply_silly_deferred)
        except Exception:
            pass

    def _apply_silly_deferred(self):
        """Отложенное включение опции (один раз)."""
        try:
            if getattr(self, "_silly_applied", False):
                return
            self._silly_applied = True
            if self.cfg.get("silly_mode"):
                self.apply_silly_mode()
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
        # force игнорируется: нативного даблклика больше нет (нет HTCAPTION),
        # разворачиваем всегда вручную
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
        brand = tk.Frame(sb, bg=SIDEBAR)
        brand.pack(fill="x", padx=14, pady=(18, 6))
        tk.Label(brand, text="🔥", bg=ACCENT, fg="white",
                 font=(FONT, 14), width=2).pack(side="left")
        btxt = tk.Frame(brand, bg=SIDEBAR)
        btxt.pack(side="left", fill="both", expand=True, padx=(10, 0))
        tk.Label(btxt, text="МЕНЮ", bg=SIDEBAR, fg=TEXT,
                 font=(FONT, 12, "bold"), anchor="w").pack(fill="x")
        tk.Label(btxt, text="DPI bypass control", bg=SIDEBAR, fg=MUTED,
                 font=(FONT, 8), anchor="w").pack(fill="x")
        tk.Frame(sb, bg=BORDER, height=1).pack(fill="x", padx=14, pady=(6, 12))
        self.nav_btns = {}
        self.nav_strips = {}
        for key, label in [("check", "🔍  Проверка"),
                           ("domains", "🌐  Домены"),
                           ("logs", "📋  Логи"),
                           ("actions", "📝  Журнал"),
                           ("settings", "⚙️  Настройки")]:
            b = tk.Button(sb, text=label, bg=SIDEBAR, fg=MUTED, font=(FONT, 11),
                          bd=0, anchor="w", padx=14, pady=10, cursor="hand2",
                          activebackground=CARD2, activeforeground=TEXT,
                          command=lambda k=key: self.show_page(k))
            b.pack(fill="x", padx=10, pady=2)
            self.nav_btns[key] = b
        sb_bottom = tk.Frame(sb, bg=SIDEBAR)
        sb_bottom.pack(side="bottom", fill="x", padx=18, pady=16)

        # Фоновая гифка смешной опции — в левом меню, без подписей.
        # Шире сайдбара (220 > 194): Label фиксированной ширины центрирует
        # и кропит бока (максимум, что разрешено с фонами, — обрезать).
        # Пакуется только при включённой опции (см. apply_silly_mode).
        self.fun_bg_lbl = tk.Label(sb_bottom, bg=SIDEBAR, width=194,
                                   anchor="center")
        # Resource monitor
        self.res_frame = tk.Frame(sb_bottom, bg=SIDEBAR)
        self.res_frame.pack(fill="x", pady=(0, 8))
        self.res_cpu = tk.Label(self.res_frame, text="CPU: —%", bg=SIDEBAR, fg=MUTED, font=(FONT, 8), anchor="w")
        self.res_cpu.pack(fill="x")
        self.res_ram = tk.Label(self.res_frame, text="RAM: — MB", bg=SIDEBAR, fg=MUTED, font=(FONT, 8), anchor="w")
        self.res_ram.pack(fill="x")
        self.res_gpu = tk.Label(self.res_frame, text="GPU: —%", bg=SIDEBAR, fg=MUTED, font=(FONT, 8), anchor="w")
        self.res_gpu.pack(fill="x")
        
        # Quick toggles — строки-кнопки с текущим режимом справа
        self.toggle_frame = tk.Frame(sb_bottom, bg=SIDEBAR)
        self.toggle_frame.pack(fill="x", pady=(0, 8))
        self.game_filter_var = tk.BooleanVar(value=False)
        self.game_filter_btn = tk.Button(
            self.toggle_frame, text="🎮 Game Filter: —", bg=CARD2, fg=TEXT,
            font=(FONT, 9), anchor="w", bd=0, padx=10, pady=6, cursor="hand2",
            activebackground=BORDER, activeforeground=TEXT,
            command=self.toggle_game_filter)
        self.game_filter_btn.pack(fill="x", anchor="w")
        self.ipset_filter_var = tk.BooleanVar(value=False)
        self.ipset_filter_btn = tk.Button(
            self.toggle_frame, text="🔢 IPSet Filter: —", bg=CARD2, fg=TEXT,
            font=(FONT, 9), anchor="w", bd=0, padx=10, pady=6, cursor="hand2",
            activebackground=BORDER, activeforeground=TEXT,
            command=self.toggle_ipset_filter)
        self.ipset_filter_btn.pack(fill="x", anchor="w", pady=(4, 0))
        
        self.admin_lbl = tk.Label(sb_bottom, text="", bg=SIDEBAR, fg=MUTED, font=(FONT, 9))
        self.admin_lbl.pack(anchor="w")
        tk.Label(sb_bottom, text=f"v{APP_VERSION}",
                 bg=SIDEBAR, fg="#6B5A5C", font=(FONT, 8)).pack(anchor="w", pady=(4, 0))

        # смешной уголок — маленький телик-оверлей поверх всего окна
        # (места в layout не занимает) + фон в левом меню
        self.build_fun_panel()
        # main
        main = tk.Frame(body, bg=BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(2, weight=1)
        main.columnconfigure(0, weight=1)
        # header
        hdr = tk.Frame(main, bg=BG)
        hdr.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 10))
        hdr.columnconfigure(0, weight=1)
        titlebox = tk.Frame(hdr, bg=BG)
        titlebox.grid(row=0, column=0, sticky="w")
        self.page_title = tk.Label(titlebox, text="Проверка конфигов", bg=BG, fg=TEXT, font=(FONT, 20, "bold"), anchor="w")
        self.page_title.pack(anchor="w")
        self.page_sub = tk.Label(titlebox, text="", bg=BG, fg=MUTED, font=(FONT, 10), anchor="w")
        self.page_sub.pack(anchor="w", pady=(2, 0))
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
        subs = {"check": "замер пингов Discord и YouTube по каждому конфигу",
                "domains": "списки обхода и их содержимое",
                "logs": "история замеров и подробный ход",
                "actions": "все переключения и изменения настроек",
                "settings": "папки, мониторинг, оформление, приложение"}
        self.page_title.config(text=titles.get(key, key))
        try:
            self.page_sub.config(text=subs.get(key, ""))
        except Exception:
            pass
        # только видимая страница в layout: ресайз не пересчитывает сотни
        # скрытых виджетов (иначе виснет)
        for k, pg in self.pages.items():
            if k == key:
                pg.grid()
            else:
                pg.grid_remove()
        for k, b in self.nav_btns.items():
            if k == key:
                b.config(bg=ACCENT, fg="white", font=(FONT, 11, "bold"),
                         activebackground=ACCENT_HOVER)
            else:
                b.config(bg=SIDEBAR, fg=MUTED, font=(FONT, 11),
                         activebackground=CARD2)
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
                elif kind == "diag_results":
                    self.show_diag_results(payload)
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

    def show_diag_results(self, results):
        """Show diagnostics results in a modal"""
        d = tk.Toplevel(self.root)
        d.title("Диагностика")
        d.configure(bg=CARD)
        d.resizable(False, False)
        try:
            d.transient(self.root)
            d.grab_set()
        except Exception:
            pass
        
        tk.Label(d, text="Результаты диагностики", bg=CARD, fg=TEXT, font=(FONT, 12, "bold"),
                 anchor="w").pack(fill="x", padx=18, pady=(16, 8))
        
        for icon, name, status, color in results:
            row = tk.Frame(d, bg=CARD)
            row.pack(fill="x", padx=18, pady=2)
            tk.Label(row, text=icon, bg=CARD, fg=color, font=(FONT, 10, "bold")).pack(side="left")
            tk.Label(row, text=name, bg=CARD, fg=TEXT, font=(FONT, 10), width=25, anchor="w").pack(side="left")
            tk.Label(row, text=status, bg=CARD, fg=color, font=(FONT, 10), anchor="w").pack(side="left")
        
        btns = tk.Frame(d, bg=CARD)
        btns.pack(fill="x", padx=18, pady=14)
        RButton(btns, text="OK", style="accent", command=d.destroy).pack(side="right")
        
        try:
            self.root.update_idletasks()
            d.update_idletasks()
            ww, wh = d.winfo_reqwidth(), d.winfo_reqheight()
            rx, ry, rw, rh = self._win_xywh()
            d.geometry(f"+{rx + max(0, (rw - ww) // 2)}+{ry + max(0, (rh - wh) // 2)}")
        except Exception:
            pass

    # ================= страница ПРОВЕРКА =================
    def _section(self, parent, text):
        """Микрозаоловок секции в духе Synapse: капс + приглушённый."""
        try:
            lbl = tk.Label(parent, text=str(text).upper(), bg=CARD, fg=MUTED,
                           font=(FONT, 9, "bold"), anchor="w")
        except Exception:
            return None
        return lbl

    def build_check_page(self):
        p = self.pages["check"]
        p.columnconfigure(0, weight=1)
        p.rowconfigure(0, weight=1)
        # вся главная — в скролле: конфиги и пинги листаются без ресайза окна
        scr = ScrollFrame(p, bg=BG)
        scr.grid(row=0, column=0, sticky="nsew")
        inner = scr.inner
        # HERO: что сейчас активно (как шапка игры в WeMod)
        ao, abar = self.card(inner)
        ao.pack(fill="x", pady=(0, 12))
        aleft = tk.Frame(abar, bg=CARD)
        aleft.pack(side="left", fill="both", expand=True, padx=18, pady=12)
        self._section(aleft, "Сейчас активно").pack(anchor="w", pady=(0, 2))
        self.active_lbl = tk.Label(aleft, text="—", bg=CARD, fg=TEXT, font=(FONT, 16, "bold"), anchor="w")
        self.active_lbl.pack(anchor="w")
        self.svc_lbl = tk.Label(aleft, text="", bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w")
        self.svc_lbl.pack(anchor="w", pady=(4, 0))
        self.vpn_lbl = tk.Label(aleft, text="VPN: проверка…", bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w")
        self.vpn_lbl.pack(anchor="w")
        # живые пинги-чипы
        self.ping_frame = tk.Frame(aleft, bg=CARD)
        self.ping_frame.pack(anchor="w", pady=(8, 0))
        self.ping_discord_lbl = tk.Label(self.ping_frame, text="DS  —", bg=CARD2, fg=MUTED,
                                         font=(MONO, 10, "bold"), padx=10, pady=4)
        self.ping_discord_lbl.pack(side="left", padx=(0, 8))
        self.ping_youtube_lbl = tk.Label(self.ping_frame, text="YT  —", bg=CARD2, fg=MUTED,
                                         font=(MONO, 10, "bold"), padx=10, pady=4)
        self.ping_youtube_lbl.pack(side="left")
        aright = tk.Frame(abar, bg=CARD)
        aright.pack(side="right", padx=18, pady=12)
        RButton(aright, text="✔ Применить выбранный", style="accent",
                   command=self.on_apply_selected).pack(side="left", padx=(0, 8))
        RButton(aright, text="↻", style="ghost",
                   command=self.on_restart_config).pack(side="left", padx=(0, 8))
        add_tooltip(aright.winfo_children()[-1], "Перезапустить активный конфиг")
        RButton(aright, text="■", style="ghost",
                   command=self.on_remove_service).pack(side="left", padx=(0, 8))
        add_tooltip(aright.winfo_children()[-1], "Остановить обход и удалить службу")
        RButton(aright, text="🔧", style="ghost",
                   command=self.run_diagnostics).pack(side="left")
        add_tooltip(aright.winfo_children()[-1], "Диагностика: BFE, прокси, WinDivert")
        # Start ping monitor
        self._start_ping_monitor()
        # ЗАПУСК ПРОВЕРКИ: большая кнопка + прогресс
        o, top = self.card(inner)
        o.pack(fill="x", pady=(0, 12))
        top.columnconfigure(0, weight=1)
        brow = tk.Frame(top, bg=CARD)
        brow.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 10))
        self.btn_check_sel = RButton(brow, text="▶  ПРОВЕРИТЬ ВЫБРАННЫЕ", style="accent",
                                     font=(FONT, 12, "bold"), height=42, pad_x=26,
                                     command=self.start_check_selected)
        self.btn_check_all = RButton(brow, text="Все", style="ghost", height=42,
                                     command=self.start_check_all)
        self.btn_cancel = RButton(brow, text="⛔ Отмена", style="ghost", height=42,
                                  command=self.cancel_check, state="disabled")
        self.btn_check_sel.pack(side="left", padx=(0, 8))
        self.btn_check_all.pack(side="left", padx=(0, 8))
        self.btn_cancel.pack(side="left")
        self.prog = ttk.Progressbar(top, style="Horizontal.TProgressbar", mode="determinate")
        self.prog.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 4))
        self.prog_lbl = tk.Label(top, text="Готов к проверке", bg=CARD, fg=MUTED, font=(FONT, 9))
        self.prog_lbl.grid(row=2, column=0, sticky="w", padx=18, pady=(0, 6))
        self.check_desc = tk.Label(top, text="Подробный ход — во вкладке «Логи» → «▶ Последний запуск».",
                  bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=700, justify="left")
        self.check_desc.grid(row=3, column=0, sticky="w", padx=18, pady=(0, 12))
        self._autowrap(self.check_desc, p)
        # ПАРАМЕТРЫ: сегмент-контроль + поля
        qo, quick = self.card(inner)
        qo.pack(fill="x", pady=(0, 12))
        self._section(quick, "Параметры проверки").pack(anchor="w", padx=18, pady=(12, 8))
        qf = tk.Frame(quick, bg=CARD)
        qf.pack(fill="x", padx=18, pady=(0, 6))
        self.q_mode_var = tk.StringVar(value=self.cfg.get("check_mode", "quick"))
        if self.q_mode_var.get() not in MODE_LABELS:
            self.q_mode_var.set(mode_key(self.q_mode_var.get()))
        mode_seg = Segmented(qf, options=[("quick", "Быстрый"),
                                          ("full", "Полный"),
                                          ("ultra", "Ультра")],
                             variable=self.q_mode_var, font=(FONT, 10, "bold"))
        mode_seg.pack(side="left", padx=(0, 18))
        rep_lbl = tk.Label(qf, text="Повторы", bg=CARD, fg=MUTED, font=(FONT, 9))
        rep_lbl.pack(side="left")
        self.q_repeat_var = tk.StringVar(value=str(self.cfg.get("check_repeat", 2)))
        rep_menu = DropMenu(qf, variable=self.q_repeat_var, values=["1", "2", "3"],
                            width=8)
        rep_menu.pack(side="left", padx=(6, 18))
        thr_lbl = tk.Label(qf, text="Макс. пинг, мс", bg=CARD, fg=MUTED, font=(FONT, 9))
        thr_lbl.pack(side="left")
        self.q_thr_var = tk.StringVar(value=str(self.cfg.get("ping_threshold_ms", 5000)))
        thr_entry = ttk.Entry(qf, textvariable=self.q_thr_var, width=8)
        thr_entry.pack(side="left", padx=(6, 18))
        wor_lbl = tk.Label(qf, text="Потоки", bg=CARD, fg=MUTED, font=(FONT, 9))
        wor_lbl.pack(side="left")
        self.q_workers_var = tk.StringVar(value=str(self.cfg.get("check_workers", 8)))
        wor_menu = DropMenu(qf, variable=self.q_workers_var,
                            values=[str(n) for n in (4, 6, 8, 10, 12, 16)],
                            width=8)
        wor_menu.pack(side="left", padx=(6, 18))
        save_btn = RButton(qf, text="💾 Сохранить", style="ghost", height=30,
                           command=self.save_quick_settings)
        save_btn.pack(side="left")
        # подсказки «наведи и подержи» — что делает каждая опция
        add_tooltip(mode_seg,
                    "Режим проверки:\n"
                    "• Быстрый — только Discord+YouTube (~7 целей), в ~3 раза быстрее.\n"
                    "• Полный — все цели из utils/targets.txt.\n"
                    "• Ультра — сначала дешёвый отсев всех по пингу, "
                    "затем точный замер топ-6.")
        add_tooltip([rep_lbl, rep_menu],
                    "Повторы: сколько раз запрашивать каждую HTTP-цель.\n"
                    "Зачёт при первом успехе — дальше не ждём.\n"
                    "Больше повторов — точнее, но проверка дольше.")
        add_tooltip([thr_lbl, thr_entry],
                    "Макс. пинг (мс): порог для оценки.\n"
                    "Пинг ниже порога считается хорошим и влияет на оценку "
                    "конфига и на срабатывание автомониторинга.")
        add_tooltip([wor_lbl, wor_menu],
                    "Потоки: сколько целей проверять параллельно.\n"
                    "Больше потоков — быстрее, но выше нагрузка на сеть и CPU.\n"
                    "При ручной проверке включается ТУРБО (потоки ×2).")
        add_tooltip(save_btn, "Сохранить режим, повторы, пинг и потоки.\nПрименятся к следующей проверке.")
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
        # список конфигов + пинги: левая карточка (конфиги) никогда не
        # схлопывается — у неё вес и минимальная ширина; правая (таблица)
        # при большом числе колонок ужимается сама, а не сосед.
        mid = tk.Frame(inner, bg=BG)
        mid.pack(fill="x")
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1, minsize=240)
        mid.columnconfigure(1, weight=2, minsize=280)
        o1, left = self.card(mid)
        o1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._section(left, "Конфиги • ▶ применить").pack(anchor="w", padx=14, pady=(12, 6))
        self.cfg_listbox_frame = tk.Frame(left, bg=CARD)
        self.cfg_listbox_frame.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        self.cfg_vars = {}
        self.cfg_toggles = {}
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
        self._section(right, "Пинги • DS Discord / YT YouTube").pack(anchor="w", padx=14, pady=(12, 6))
        gwrap = tk.Frame(right, bg=CARD)
        gwrap.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        # Только Discord и YouTube: лишних колонок нет (детали — по клику ниже)
        self.grade_tree_cols = ["config", "discord", "youtube", "grade"]
        self.grade_tree = ttk.Treeview(gwrap, columns=self.grade_tree_cols, show="headings", height=12)
        for c, w, t in [("config", 170, "Конфиг"), ("discord", 60, "DS"),
                        ("youtube", 60, "YT"), ("grade", 110, "Оценка")]:
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
        self._section(bot, "Детали конфига — кликните строку выше").pack(anchor="w", padx=14, pady=(12, 4))
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

    def set_all_checks(self, val):
        for v in self.cfg_vars.values():
            v.set(val)

    def _grade_row(self, bat, v):
        """Строка таблицы пингов: (values, tag). Только Discord и YouTube.
        Нефиналисты Ультры — с ≈. Остальные цели — в деталях по клику."""
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
        # смешная опция: телик показывает гифку по оценке текущего конфига
        try:
            if self.cfg.get("silly_mode") and res is not None:
                if res.get("started"):
                    dm, ym = service_pings(res.get("rows", []))
                    _txt, _col, rank = config_grade(dm, ym)
                else:
                    _txt, rank = "Не работает", 0
                key = FUNNY_RANK_KEYS[rank] if 0 <= rank <= 4 else "idle"
                self._fun_show_tv(key)
        except Exception:
            pass

    def selected_configs(self):
        return [k for k, v in self.cfg_vars.items() if v.get()]

    def save_quick_settings(self):
        """Быстрые параметры с главной: режим + повторы + макс. пинг + потоки."""
        try:
            rep = min(3, max(1, int(self.q_repeat_var.get())))
            thr = max(300, int(self.q_thr_var.get()))
            wor = min(16, max(4, int(self.q_workers_var.get())))
        except ValueError:
            self.dlg_error("Повторы, пинг и потоки — числа")
            return
        _m = (self.q_mode_var.get() or "").strip()
        self.cfg["check_mode"] = _m if _m in MODE_LABELS else mode_key(_m)
        self.cfg["check_repeat"] = rep
        self.cfg["ping_threshold_ms"] = thr
        self.cfg["check_workers"] = wor
        save_config(self.cfg)
        self.engine.cfg = self.cfg
        log_action(f"Быстрые параметры: режим={self.cfg['check_mode']}, повторы={rep}, "
                   f"макс. пинг={thr} мс, потоки={wor}")
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
        # снимок списка: смена галочек/обновление каталога посреди проверки
        # не должны трогать ни текущий замер, ни окно конфигов слева
        bat_list = list(bat_list or [])
        if not bat_list:
            self.dlg_info("Выберите хотя бы один конфиг")
            return
        try:
            _all = parse_targets(self.cfg["zapret_root"])
            _mode = self.cfg.get("check_mode", "quick")
            _probed = quick_filter(_all) if _mode == "quick" else _all
            _names = ", ".join(n for n, _v in _probed) or "—"
            _n = len(_probed)
        except Exception:
            _mode, _names, _n = self.cfg.get("check_mode", "quick"), "—", "?"
        run_log_reset(f"Конфигов: {len(bat_list)} • режим: {mode_label(_mode)}\n"
                      f"Цели проверки ({_n}): {_names}\n"
                      f"Конфиги: {', '.join(bat_list)}")
        # прогрев гифок результатов — здесь, а не на старте приложения:
        # воркеру никто не мешает, к первым итогам всё готово
        try:
            if self.cfg.get("silly_mode") and self._fun_visible:
                for k in _fun_all_concrete():
                    self._fun_request(k)
        except Exception:
            pass
        if not is_admin():
            run_log_write("⚠ Нет прав администратора — winws может не запуститься. "
                          "Запустите приложение через run.bat (ПКМ → Запуск от администратора).")
        for t in (self.grade_tree, self.detail_tree):
            for i in t.get_children():
                t.delete(i)
        self.btn_check_sel.config(state="disabled")
        self.btn_check_all.config(state="disabled")
        self.btn_cancel.config(state="normal")
        try:
            if self.cfg.get("silly_mode"):
                self._fun_show_tv("idle")
        except Exception:
            pass
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
        # проверки больше нет — телик снова idle
        try:
            if self.cfg.get("silly_mode"):
                self._fun_show_tv("idle")
        except Exception:
            pass
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
        self._update_toggles()

    def _update_toggles(self):
        """Update toggle button texts to reflect current status"""
        try:
            # Game Filter
            enabled, mode = self.get_game_filter_status()
            self.game_filter_var.set(enabled)
            self.game_filter_btn.config(text=f"🎮 Game Filter: {mode}")
            
            # IPSet Filter
            status = self.get_ipset_status()
            self.ipset_filter_var.set(status != "any")
            status_text = {"loaded": "Загружен", "none": "Минимум", "any": "Все"}.get(status, status)
            self.ipset_filter_btn.config(text=f"🔢 IPSet Filter: {status_text}")
        except Exception:
            pass

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

    # ================= Смешная опция =================
    def build_fun_panel(self):
        """Маленький телик-оверлей поверх всего окна + фон в левом меню.

        Места в layout не занимает: телик — place() в углу окна (root),
        поверх всех страниц; фоновая гифка — fun_bg_lbl в сайдбаре.
        Никаких подписей про содержимое — только картинки. Гифка экрана
        лежит ЗАДНИМ слоем под картинкой телика (у неё прозрачный экран),
        фоны гифок не трогаем — рисуем попиксельно как в файле.
        """
        # key -> {"photos": [PhotoImage], "delays": [ms], "done": bool,
        #           "size": (dw, dh)} — готовые кадры (декод один раз в фоне)
        self._fun_cache = {}
        self._fun_loading = set()  # ключи, уже заказанные воркеру
        self._fun_keygen = {}  # key -> поколение (отмена устаревшего декода)
        self._fun_variant_idx = {}  # base -> индекс текущей вариации _2
        self._fun_anim = {"tv": {"key": None, "after": None, "shown": -1},
                          "bg": {"key": None, "after": None, "shown": -1}}
        self._fun_worker = None
        self._fun_visible = False
        self._fun_tv_img = None
        self._fun_tv_item = None
        self._fun_screen_item = None
        self._silly_icon = None
        # тонкая рамка + чёрный канвас: прозрачные углы и поля гифки — как тьма
        wrap = tk.Frame(self.root, bg=BORDER, padx=1, pady=1)
        self.fun_tv_wrap = wrap
        self.fun_tv_canvas = tk.Canvas(wrap, width=FUNNY_TV_W, height=FUNNY_TV_H,
                                       bg="#000000", highlightthickness=0, bd=0)
        self.fun_tv_canvas.pack()
        self._fun_place_args = {"in_": self.root, "relx": 1.0, "rely": 1.0,
                                "x": -12, "y": -12, "anchor": "se"}

    def _fun_overlay_show(self):
        try:
            self.fun_tv_wrap.place(**self._fun_place_args)
            self.fun_tv_wrap.lift()
        except Exception:
            pass

    def _fun_overlay_hide(self):
        try:
            self.fun_tv_wrap.place_forget()
        except Exception:
            pass

    def _fun_build_tv(self):
        """Собрать картинки канваса телика (отложенно после включения)."""
        try:
            if not self.cfg.get("silly_mode") or not self._fun_visible:
                return
            if self._fun_tv_item is not None:
                return
            try:
                self.fun_tv_canvas.delete("all")
            except Exception:
                pass
            # СНАЧАЛА задний слой (гифка экрана), ПОТОМ телик поверх:
            # прозрачный экран покажет гифку, она строго в границах экрана.
            # Заглушка 1x1 — настоящий кадр встанет первым тиком.
            try:
                self._fun_blank = tk.PhotoImage(width=1, height=1)
                self._fun_screen_item = self.fun_tv_canvas.create_image(
                    FUNNY_SCREEN_CX, FUNNY_SCREEN_CY, anchor="center",
                    image=self._fun_blank)
            except Exception as e:
                log_action(f"Смешная опция: канвас: {e}", "error")
                self._fun_screen_item = None
            tv_path = os.path.join(FUNNY_DIR, "tv_ts_screen.png")
            base = tk.PhotoImage(file=tv_path)
            try:
                self._fun_tv_img = base.subsample(FUNNY_TV_SUB, FUNNY_TV_SUB)
            except Exception:
                self._fun_tv_img = base
            self._fun_tv_item = self.fun_tv_canvas.create_image(
                0, 0, anchor="nw", image=self._fun_tv_img)
            try:
                # телик строго поверх гифки
                self.fun_tv_canvas.tag_raise(self._fun_tv_item,
                                             self._fun_screen_item)
            except Exception:
                pass
        except Exception:
            pass

    @staticmethod
    def _fun_buf_to_tcl(buf, dw, dh):
        """Буфер кадра -> tcl-строка для PhotoImage.put. Вызывается только
        при сборке новых кадров (не на каждый тик)."""
        rows = []
        for y in range(dh):
            base = y * dw * 3
            rows.append("{" + " ".join(
                "#%02x%02x%02x" % (buf[base + x * 3], buf[base + x * 3 + 1],
                                   buf[base + x * 3 + 2])
                for x in range(dw)) + "}")
        return " ".join(rows)

    def _fun_request(self, key):
        """Заказать воркеру полный декод гифки (один раз; повтор — no-op).

        key — конкретный ('bg#0', 'excellent#1'); базу в конкретный
        превращает _fun_play (ротация вариаций).
        """
        try:
            _fun_variant_spec(key)  # проверка существования
            if key in self._fun_cache or key in self._fun_loading:
                return
            if self._fun_worker is None:
                return
            self._fun_loading.add(key)
            gen = self._fun_keygen.get(key, 0) + 1
            self._fun_keygen[key] = gen
            self._fun_worker.tasks.put((key, gen))
        except Exception:
            pass

    def _fun_consume_chunks(self):
        """Забрать готовые чанки у воркера (сырые кадры; в PhotoImage
        собираются лениво, по мере показа — без пачек-подвисаний)."""
        try:
            worker = self._fun_worker
            if worker is None:
                return
            while True:
                try:
                    res = worker.results.get_nowait()
                except queue.Empty:
                    break
                if not res or res[0] == "err":
                    continue
                _tag, key, gen, batch, size, done = res
                if gen != self._fun_keygen.get(key, -1):
                    continue  # устаревший декод — выбросить
                ent = self._fun_cache.get(key)
                if ent is None:
                    ent = {"raw": [], "photos": [], "delays": [],
                           "done": False, "size": size}
                    self._fun_cache[key] = ent
                try:
                    for buf, dms in batch:
                        ent["raw"].append(buf)
                        ent["photos"].append(None)
                        ent["delays"].append(dms)
                    if done:
                        ent["done"] = True
                        self._fun_loading.discard(key)
                except Exception:
                    continue
        except Exception:
            pass

    def _fun_cached_photo(self, key, idx):
        """Готовый PhotoImage кадра idx (собрать при первом показе)."""
        ent = self._fun_cache.get(key)
        if ent is None or idx >= len(ent["photos"]):
            return None
        ph = ent["photos"][idx]
        if ph is None:
            try:
                dw, dh = ent["size"]
                buf = ent["raw"][idx]
                if buf is None:
                    return None
                ph = tk.PhotoImage(width=dw, height=dh)
                ph.put(self._fun_buf_to_tcl(buf, dw, dh))
                ent["photos"][idx] = ph
                ent["raw"][idx] = None  # байты больше не нужны
            except Exception:
                return None
        return ph

    def _fun_stop_slot(self, which):
        try:
            st = self._fun_anim[which]
            if st.get("after") is not None:
                try:
                    self.root.after_cancel(st["after"])
                except Exception:
                    pass
            st["after"] = None
            st["key"] = None
            st["base"] = None
        except Exception:
            pass

    def _fun_tick(self, which):
        """Тик анимации: переключить на следующий ГОТОВЫЙ кадр.

        Тяжёлой работы нет вообще: декод — один раз в фоне, здесь только
        смена картинки (itemconfig/config) и планирование по родной
        задержке кадра. Поэтому вкладки больше не виснут.
        """
        try:
            st = self._fun_anim[which]
        except Exception:
            return
        if not self.cfg.get("silly_mode") or not self._fun_visible:
            st["after"] = None
            return
        try:
            self._fun_consume_chunks()
        except Exception:
            pass
        delay = FUNNY_MIN_TICK
        try:
            key = st.get("key")
            ent = self._fun_cache.get(key) if key else None
            n = len(ent["photos"]) if ent else 0
            if n:
                nxt = (st.get("shown", -1) + 1) % n
                photo = self._fun_cached_photo(key, nxt)
                if photo is None:
                    self._fun_request(key)
                else:
                    if which == "tv" and self._fun_screen_item is not None:
                        self.fun_tv_canvas.itemconfig(
                            self._fun_screen_item, image=photo)
                    elif which == "bg":
                        self.fun_bg_lbl.config(image=photo)
                    st["shown"] = nxt
                    try:
                        delay = max(FUNNY_MIN_TICK, int(ent["delays"][nxt]))
                    except Exception:
                        delay = FUNNY_MIN_TICK
            elif key:
                self._fun_request(key)
        except Exception:
            pass
        try:
            st["after"] = self.root.after(delay, self._tick_cb(which))
        except Exception:
            st["after"] = None

    def _tick_cb(self, which):
        return lambda: self._fun_tick(which)

    def _fun_next_variant(self, base):
        """Следующая вариация базы ('excellent' -> 'excellent#1'), по кругу."""
        try:
            n = len(FUNNY_GIFS[base])
        except Exception:
            return f"{base}#0"
        try:
            i = (self._fun_variant_idx.get(base, -1) + 1) % max(1, n)
        except Exception:
            i = 0
        try:
            self._fun_variant_idx[base] = i
        except Exception:
            pass
        return f"{base}#{i}"

    def _fun_play(self, which, key):
        """Поставить гифку key (база) на слот tv/bg.

        Вариации _2 ротируются: каждый переход на базу показывает следующую.
        Показ начинается, как только воркер отдаст первые кадры (декод идёт
        в фоне, интерфейс не виснет); до готовности — предыдущая картинка.
        """
        try:
            st = self._fun_anim[which]
        except Exception:
            return
        if st.get("base") == key and st.get("after") is not None:
            return
        self._fun_stop_slot(which)
        concrete = self._fun_next_variant(key)
        st["key"] = concrete
        st["base"] = key
        st["shown"] = -1
        self._fun_request(concrete)
        try:
            st["after"] = self.root.after(FUNNY_MIN_TICK, self._tick_cb(which))
        except Exception:
            st["after"] = None

    def _fun_show_tv(self, key):
        try:
            self._fun_play("tv", key)
        except Exception:
            pass

    def _fun_stop(self):
        for st in getattr(self, "_fun_anim", {}).values():
            try:
                if st.get("after") is not None:
                    try:
                        self.root.after_cancel(st["after"])
                    except Exception:
                        pass
                st["after"] = None
                st["key"] = None
                st["shown"] = -1
            except Exception:
                pass
        # поколения вперёд — воркер бросит недодекодированное
        try:
            for k in list(getattr(self, "_fun_keygen", {})):
                self._fun_keygen[k] = self._fun_keygen.get(k, 0) + 1
        except Exception:
            pass
        try:
            self._fun_loading.clear()
        except Exception:
            pass
        # слить очередь результатов, чтобы не копилось старье
        try:
            if self._fun_worker is not None:
                try:
                    while True:
                        self._fun_worker.results.get_nowait()
                except queue.Empty:
                    pass
        except Exception:
            pass
        # освободить готовые кадры
        try:
            self._fun_cache.clear()
        except Exception:
            pass
        try:
            self._fun_tv_img = None
            self._fun_tv_item = None
            self._fun_screen_item = None
            self._fun_blank = None
        except Exception:
            pass

    def _silly_icon_thread_main(self):
        """Фоновая подготовка иконки: разбор PNG, кроп, .ico + квадрат-PNG.

        Всё тяжёлое (побайтовый pure-Python PNG на ~2 МБ) — здесь, НЕ в
        UI-потоке: именно это вешало интерфейс на секунды при включении.
        Готовые пути отдаём через очередь, применение — в _fun_icon_poll.
        """
        try:
            src = os.path.join(FUNNY_DIR, "icon_silly.png")
            ico = os.path.join(DATA_DIR, "silly_icon.ico")
            sq = os.path.join(DATA_DIR, "silly_icon_sq.png")
            try:
                fresh = (os.path.exists(ico) and os.path.exists(sq)
                         and os.path.getmtime(ico) >= os.path.getmtime(src)
                         and os.path.getmtime(sq) >= os.path.getmtime(src))
            except Exception:
                fresh = False
            if not fresh:
                w, h, rgba = _read_png_rgba(src)
                s, sqb = _crop_center_square(w, h, rgba)
                try:
                    with open(ico, "wb") as f:
                        f.write(_wrap_ico(_encode_png_rgba(s, s, sqb)))
                except Exception:
                    ico = ""
                try:
                    with open(sq, "wb") as f:
                        f.write(_encode_png_rgba(s, s, sqb))
                except Exception:
                    sq = ""
            ok_ico = ico if ico and os.path.exists(ico) else ""
            ok_sq = sq if sq and os.path.exists(sq) else ""
            try:
                self._fun_icon_result.put(("icon", ok_ico, ok_sq))
            except Exception:
                pass
        except Exception:
            try:
                self._fun_icon_result.put(("icon", "", ""))
            except Exception:
                pass

    def _fun_icon_poll(self):
        """Забрать готовую иконку из фона и применить (быстрые вызовы)."""
        try:
            if not self.cfg.get("silly_mode"):
                return
            try:
                _tag, ico, sq = self._fun_icon_result.get_nowait()
            except queue.Empty:
                try:
                    self.root.after(250, self._fun_icon_poll)
                except Exception:
                    pass
                return
            try:
                self._fun_icon_busy = False
            except Exception:
                pass
            if not self.cfg.get("silly_mode"):
                return
            if ico:
                try:
                    self.root.iconbitmap(ico)
                except Exception:
                    pass
            if sq and os.path.exists(sq):
                try:
                    img = tk.PhotoImage(file=sq)
                    try:
                        f = max(1, img.width() // 64)
                        if f > 1:
                            img = img.subsample(f, f)
                    except Exception:
                        pass
                    self._silly_icon = img  # держать ссылку!
                    self.root.iconphoto(True, img)
                except Exception:
                    pass
        except Exception:
            pass

    def _set_app_icon(self, silly):
        """Иконка приложения: silly — кропнутый квадрат, иначе обычная.

        Кроп обязателен: исходник — широкая панорама, в таскбаре она
        сплющивалась в неузнаваемое. Для таскбара/alt-tab ставим .ico через
        iconbitmap (его Windows точно показывает), для окон Tk — iconphoto.
        Тяжёлая подготовка — в фоне (_silly_icon_thread_main), здесь только
        запуск: включение опции мгновенное, иконка догоняет через секунду.
        """
        try:
            if silly:
                try:
                    if getattr(self, "_fun_icon_busy", False):
                        return
                    self._fun_icon_busy = True
                    if getattr(self, "_fun_icon_result", None) is None:
                        self._fun_icon_result = queue.Queue()
                    try:
                        while True:
                            self._fun_icon_result.get_nowait()
                    except queue.Empty:
                        pass
                    threading.Thread(target=self._silly_icon_thread_main,
                                     daemon=True).start()
                    self.root.after(250, self._fun_icon_poll)
                except Exception:
                    try:
                        self._fun_icon_busy = False
                    except Exception:
                        pass
            else:
                try:
                    self._fun_icon_busy = False
                except Exception:
                    pass
                self._silly_icon = None
                try:
                    _ico = os.path.join(BASE_DIR, "assets", "icon.ico")
                    if os.path.exists(_ico):
                        self.root.iconbitmap(_ico)
                except Exception:
                    pass
                if hasattr(self.root, "_icon_img"):
                    try:
                        self.root.iconphoto(True, self.root._icon_img)
                    except Exception:
                        pass
        except Exception:
            pass

    def apply_silly_mode(self):
        """Показать/спрятать смешной уголок + сменить иконку."""
        on = bool(self.cfg.get("silly_mode"))
        if on:
            need = ["tv_ts_screen.png", "icon_silly.png", "bg_g.gif", "idle_gif.gif"]
            missing = [f for f in need
                       if not os.path.exists(os.path.join(FUNNY_DIR, f))]
            if missing:
                self.cfg["silly_mode"] = False
                save_config(self.cfg)
                try:
                    self.silly_var.set(False)
                except Exception:
                    pass
                self.dlg_error("Смешная опция: нет файлов: " + ", ".join(missing))
                on = False
        try:
            if on:
                # фоновый декодер (один на всё время)
                if self._fun_worker is None:
                    try:
                        self._fun_worker = _FunWorker(
                            lambda k: self._fun_keygen.get(k, 0))
                    except Exception as e:
                        log_action(f"Смешная опция: без фонового декода: {e}",
                                   "error")
                        self._fun_worker = None
                if self._fun_worker is None:
                    self.cfg["silly_mode"] = False
                    save_config(self.cfg)
                    try:
                        self.silly_var.set(False)
                    except Exception:
                        pass
                    self.dlg_error("Смешная опция: не запустился фоновый поток")
                    on = False
                self._fun_overlay_show()
                try:
                    self.fun_bg_lbl.pack(fill="x", pady=(0, 8),
                                         before=self.res_frame)
                except Exception:
                    try:
                        self.fun_bg_lbl.pack(fill="x", pady=(0, 8))
                    except Exception:
                        pass
                self._fun_visible = True
                # сборка канваса — отложенно: декод PNG телика (~0.3 c) не
                # должен фризить включение; оверлей уже показан, тики идут
                try:
                    self.root.after(60, self._fun_build_tv)
                except Exception:
                    pass
                self._fun_play("bg", "bg")
                self._fun_show_tv("idle")
                # на старте греем ТОЛЬКО видимое (idle+bg): остальные гифки
                # закажем при старте проверки (там воркеру не мешает раскладка)
                self._set_app_icon(True)
                log_action("Смешная опция ВКЛ: телик + фон + silly-иконка")
            else:
                self._fun_stop()
                self._fun_overlay_hide()
                try:
                    self.fun_bg_lbl.pack_forget()
                except Exception:
                    pass
                self._fun_visible = False
                self._set_app_icon(False)
        except Exception as e:
            log_action(f"Смешная опция: {e}", "error")

    def on_silly_toggle(self):
        on = bool(self.silly_var.get())
        self.cfg["silly_mode"] = on
        try:
            self._silly_applied = True
        except Exception:
            pass
        save_config(self.cfg)
        log_action(f"Смешная опция: {'ВКЛ' if on else 'ВЫКЛ'}")
        self.apply_silly_mode()
        self.msg_q.put(("actions_refresh", None))

    # ================= Resource Monitor =================
    def start_resource_monitor(self):
        """Периодический замер РЕАЛЬНЫХ ресурсов процесса (только stdlib+ctypes).

        Раньше использовался модуль wmi (не входит в stdlib) — импорт всегда
        падал и виджеты вечно показывали «—%». Теперь CPU/RAM меряются через
        WinAPI напрямую: GetSystemTimes/GetProcessTimes (CPU) и
        GetProcessMemoryInfo (RAM процесса). Без консолей и дочерних процессов.
        """
        self._res_prev = None
        self._res_gpu_name = None
        self._update_resources()

    def _res_gpu_display_name(self):
        """Имя видеоадаптера из реестра (один раз, кэш). Нагрузку GPU через
        stdlib честно не получить — показываем имя, а не выдуманные проценты."""
        if self._res_gpu_name is not None:
            return self._res_gpu_name
        name = ""
        try:
            if winreg is not None:
                base = (r"SYSTEM\CurrentControlSet\Control\Class"
                        r"\{4d36e968-e325-11ce-bfc1-08002be10318}")
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
                        i = 0
                        while True:
                            try:
                                sub = winreg.EnumKey(k, i)
                            except OSError:
                                break
                            i += 1
                            if not sub.isdigit():
                                continue
                            try:
                                with winreg.OpenKey(k, sub) as sk:
                                    desc, _ = winreg.QueryValueEx(sk, "DriverDesc")
                                    desc = (desc or "").strip()
                                    if desc and desc not in name:
                                        name = (name + " / " + desc) if name else desc
                            except Exception:
                                continue
                except Exception:
                    pass
        except Exception:
            pass
        self._res_gpu_name = name
        return name

    @staticmethod
    def _ft_to_int(ft):
        try:
            return (int(ft.dwHighDateTime) << 32) | int(ft.dwLowDateTime)
        except Exception:
            return 0

    def _update_resources(self):
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return
        try:
            if os.name != "nt":
                raise RuntimeError("non-windows")
            import ctypes as _ct
            from ctypes import wintypes as _wt
            k32 = _ct.windll.kernel32
            psapi = _ct.windll.psapi

            class _PMC(_ct.Structure):
                _fields_ = [("cb", _wt.DWORD),
                            ("PageFaultCount", _wt.DWORD),
                            ("PeakWorkingSetSize", _ct.c_size_t),
                            ("WorkingSetSize", _ct.c_size_t),
                            ("QuotaPeakPagedPoolUsage", _ct.c_size_t),
                            ("QuotaPagedPoolUsage", _ct.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", _ct.c_size_t),
                            ("QuotaNonPagedPoolUsage", _ct.c_size_t),
                            ("PagefileUsage", _ct.c_size_t),
                            ("PeakPagefileUsage", _ct.c_size_t)]

            k32.GetCurrentProcess.argtypes = []
            k32.GetCurrentProcess.restype = _wt.HANDLE
            try:
                psapi.GetProcessMemoryInfo.argtypes = [_wt.HANDLE,
                                                       _ct.c_void_p,
                                                       _wt.DWORD]
                psapi.GetProcessMemoryInfo.restype = _wt.BOOL
            except Exception:
                pass
            hproc = k32.GetCurrentProcess()
            # --- RAM процесса ---
            pmc = _PMC()
            pmc.cb = _ct.sizeof(pmc)
            ram_mb = None
            try:
                if psapi.GetProcessMemoryInfo(hproc, _ct.byref(pmc), pmc.cb):
                    ram_mb = pmc.WorkingSetSize / 1024 / 1024
            except Exception:
                ram_mb = None
            # --- CPU: системный (GetSystemTimes) + процесса (GetProcessTimes) ---
            k32.GetSystemTimes.argtypes = [_ct.POINTER(_wt.FILETIME)] * 3
            k32.GetSystemTimes.restype = _wt.BOOL
            k32.GetProcessTimes.argtypes = [_wt.HANDLE,
                                            _ct.POINTER(_wt.FILETIME),
                                            _ct.POINTER(_wt.FILETIME),
                                            _ct.POINTER(_wt.FILETIME),
                                            _ct.POINTER(_wt.FILETIME)]
            k32.GetProcessTimes.restype = _wt.BOOL
            idle, sk, su = _wt.FILETIME(), _wt.FILETIME(), _wt.FILETIME()
            c1, e1, pk, pu = (_wt.FILETIME(), _wt.FILETIME(),
                              _wt.FILETIME(), _wt.FILETIME())
            if not k32.GetSystemTimes(_ct.byref(idle), _ct.byref(sk), _ct.byref(su)):
                raise RuntimeError("GetSystemTimes failed")
            if not k32.GetProcessTimes(hproc, _ct.byref(c1), _ct.byref(e1),
                                       _ct.byref(pk), _ct.byref(pu)):
                raise RuntimeError("GetProcessTimes failed")
            now_wall = time.perf_counter()
            cur = {"idle": self._ft_to_int(idle),
                   "sys": self._ft_to_int(sk) + self._ft_to_int(su),
                   "proc": self._ft_to_int(pk) + self._ft_to_int(pu),
                   "wall": now_wall}
            prev = self._res_prev
            self._res_prev = cur
            if prev is not None:
                sys_delta = cur["sys"] - prev["sys"]          # 100-нс
                idle_delta = cur["idle"] - prev["idle"]       # 100-нс
                proc_delta = cur["proc"] - prev["proc"]       # 100-нс
                wall_delta = cur["wall"] - prev["wall"]       # сек
                ncpu = os.cpu_count() or 1
                sys_pct = None
                if sys_delta > 0:
                    sys_pct = max(0.0, min(100.0, (sys_delta - idle_delta) * 100.0 / sys_delta))
                proc_pct = None
                if wall_delta > 0 and proc_delta >= 0:
                    proc_pct = max(0.0, min(100.0, (proc_delta / 1e7) * 100.0 / (wall_delta * ncpu)))
                if sys_pct is None and proc_pct is None:
                    self.res_cpu.config(text="CPU: …")
                elif proc_pct is None:
                    self.res_cpu.config(text=f"CPU: {sys_pct:.0f}%")
                elif sys_pct is None:
                    self.res_cpu.config(text=f"CPU app: {proc_pct:.1f}%")
                else:
                    self.res_cpu.config(text=f"CPU: {sys_pct:.0f}% • app {proc_pct:.1f}%")
            else:
                self.res_cpu.config(text="CPU: …")
            if ram_mb is not None:
                self.res_ram.config(text=f"RAM: {ram_mb:.0f} МБ")
            else:
                self.res_ram.config(text="RAM: —")
            gname = self._res_gpu_display_name()
            if gname:
                self.res_gpu.config(text=f"GPU: {gname[:24]}")
            else:
                self.res_gpu.config(text="GPU: н/д")
        except Exception:
            try:
                self.res_cpu.config(text="CPU: —")
                self.res_ram.config(text="RAM: —")
                self.res_gpu.config(text="GPU: н/д")
            except Exception:
                pass
        # следующий замер через 2 с
        try:
            self.root.after(2000, self._update_resources)
        except Exception:
            pass

    def get_game_filter_status(self):
        """Read game_filter.enabled and return (enabled, mode_text)"""
        try:
            p = os.path.join(self.cfg["zapret_root"], "utils", "game_filter.enabled")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    mode = f.read().strip().lower()
                if mode == "all":
                    return True, "TCP+UDP"
                elif mode == "tcp":
                    return True, "TCP"
                elif mode == "udp":
                    return True, "UDP"
            return False, "Выкл"
        except Exception:
            return False, "Ошибка"

    def get_ipset_status(self):
        """Check ipset-all.txt status: loaded / none / any"""
        try:
            p = os.path.join(self.cfg["zapret_root"], "lists", "ipset-all.txt")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                if not lines:
                    return "any"
                if any("203.0.113.113/32" in line for line in lines):
                    return "none"
                return "loaded"
            return "any"
        except Exception:
            return "any"

    def toggle_game_filter(self):
        """Cycle: disabled -> all -> tcp -> udp -> disabled"""
        try:
            p = os.path.join(self.cfg["zapret_root"], "utils", "game_filter.enabled")
            current = ""
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    current = f.read().strip().lower()
            
            modes = ["", "all", "tcp", "udp"]  # empty = disabled
            idx = modes.index(current) if current in modes else 0
            next_mode = modes[(idx + 1) % len(modes)]
            
            if next_mode:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(next_mode)
            else:
                if os.path.exists(p):
                    os.remove(p)
            
            # Update checkbox to reflect state (checked if any mode enabled)
            self.game_filter_var.set(bool(next_mode))
            log_action(f"Game Filter: {next_mode or 'disabled'}")
            # сразу показать активный вариант на кнопке (не ждать следующего refresh)
            try:
                self._update_toggles()
            except Exception:
                pass
            try:
                mode_txt = {"all": "TCP+UDP", "tcp": "TCP", "udp": "UDP"}.get(next_mode, "Выкл")
                self.msg_q.put(("toast", ("Game Filter", f"Теперь: {mode_txt}", GREEN)))
            except Exception:
                pass
        except Exception as e:
            log_action(f"Game Filter toggle error: {e}", "error")

    def toggle_ipset_filter(self):
        """Cycle ipset-all.txt: loaded -> none -> any -> loaded"""
        try:
            p = os.path.join(self.cfg["zapret_root"], "lists", "ipset-all.txt")
            backup = p + ".backup"
            status = self.get_ipset_status()
            
            if status == "loaded":
                # loaded -> none (keep only placeholder)
                if not os.path.exists(backup):
                    os.rename(p, backup)
                else:
                    os.remove(backup)
                    os.rename(p, backup)
                with open(p, "w", encoding="utf-8") as f:
                    f.write("203.0.113.113/32\n")
                new_status = "none"
            elif status == "none":
                # none -> any (empty file)
                with open(p, "w", encoding="utf-8") as f:
                    pass
                new_status = "any"
            else:  # any
                # any -> loaded (restore from backup)
                if os.path.exists(backup):
                    if os.path.exists(p):
                        os.remove(p)
                    os.rename(backup, p)
                    new_status = "loaded"
                else:
                    self.dlg_error("Нет бэкапа ipset-all.txt.backup для восстановления")
                    return
            
            self.ipset_filter_var.set(new_status != "any")
            log_action(f"IPSet Filter: {new_status}")
            # сразу показать активный вариант на кнопке (не ждать следующего refresh)
            try:
                self._update_toggles()
            except Exception:
                pass
            try:
                txt = {"loaded": "Загружен", "none": "Минимум", "any": "Все"}.get(new_status, new_status)
                self.msg_q.put(("toast", ("IPSet Filter", f"Теперь: {txt}", GREEN)))
            except Exception:
                pass
        except Exception as e:
            log_action(f"IPSet Filter toggle error: {e}", "error")

    def run_diagnostics(self):
        """Run diagnostics similar to service.bat"""
        def _diag():
            results = []
            try:
                # BFE service
                rc, out = run_cmd(["sc", "query", "BFE"], timeout=5)
                if "RUNNING" in out:
                    results.append(("✓", "Base Filtering Engine", "running", GREEN))
                else:
                    results.append(("✗", "Base Filtering Engine", "NOT running!", RED))
                
                # Proxy
                proxy_enabled = False
                if winreg:
                    try:
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
                            v, _ = winreg.QueryValueEx(k, "ProxyEnable")
                            proxy_enabled = int(v) == 1
                    except Exception:
                        pass
                if proxy_enabled:
                    results.append(("⚠", "System Proxy", "enabled (may interfere)", YELLOW))
                else:
                    results.append(("✓", "System Proxy", "disabled", GREEN))
                
                # TCP timestamps
                rc, out = run_cmd(["netsh", "interface", "tcp", "show", "global"], timeout=5)
                if "enabled" in out.lower() and "timestamps" in out.lower():
                    results.append(("✓", "TCP Timestamps", "enabled", GREEN))
                else:
                    results.append(("⚠", "TCP Timestamps", "disabled", YELLOW))
                
                # Adguard
                rc, out = run_cmd(["tasklist", "/FI", "IMAGENAME eq AdguardSvc.exe"], timeout=5)
                if "AdguardSvc.exe" in out:
                    results.append(("✗", "AdguardSvc", "running (conflicts)", RED))
                else:
                    results.append(("✓", "AdguardSvc", "not running", GREEN))
                
                # Killer
                rc, out = run_cmd(["sc", "query"], timeout=5)
                if "Killer" in out:
                    results.append(("✗", "Killer Service", "found (conflicts)", RED))
                else:
                    results.append(("✓", "Killer Service", "not found", GREEN))
                
                # WinDivert
                rc, out = run_cmd(["sc", "query", "WinDivert"], timeout=5)
                if "RUNNING" in out:
                    results.append(("✓", "WinDivert", "running", GREEN))
                else:
                    results.append(("✗", "WinDivert", "not running", RED))
                
                # Show results
                self.msg_q.put(("diag_results", results))
                
            except Exception as e:
                self.msg_q.put(("diag_results", [("✗", "Error", str(e), RED)]))
        
        threading.Thread(target=_diag, daemon=True).start()

    def _start_ping_monitor(self):
        """Periodic ping to Discord/YouTube for real-time display"""
        def _ping():
            try:
                if not self.root.winfo_exists():
                    return
                targets = parse_targets(self.cfg["zapret_root"])
                targets = quick_filter(targets)
                ping_targets = [(n, f"PING:{split_host(v)[0]}") for n, v in targets]
                engine = CheckEngine(self.cfg)
                results = engine.probe_many(ping_targets, 2, 5000, 1, 4)
                for r in results:
                    name = r["name"]
                    pm = r["ping_ms"]
                    txt = f"{pm}ms" if pm else "—"
                    color = GREEN if pm and pm < 100 else (YELLOW if pm and pm < 300 else (ACCENT2 if pm else RED))
                    if name == "DiscordMain":
                        self.root.after(0, lambda: self.ping_discord_lbl.config(text=f"DS: {txt}", fg=color))
                    elif name == "YouTubeWeb":
                        self.root.after(0, lambda: self.ping_youtube_lbl.config(text=f"YT: {txt}", fg=color))
            except Exception:
                pass
            if self.root.winfo_exists():
                self.root.after(10000, _ping)
        threading.Thread(target=_ping, daemon=True).start()

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
        running = wait_winws_alive(6.0)
        if not (ok and running) and is_admin():
            # боевой запуск не оставил процесса — узнать настоящую причину
            # пробником (перехват вывода), а не гадать про администратора.
            # Без админа и так всё ясно — пробник не запускаем.
            try:
                diag = winws_probe_output(self.cfg["zapret_root"], bat)
            except Exception as e:
                diag = str(e)
            if diag.startswith("<процесс жив"):
                # пробник жив: старт в принципе работает (первый был
                # медленным/транзиентным) — повторяем боевой один раз
                log_action(f"Разовый запуск {bat}: пробник жив, повторяю",
                           "apply")
                stop_winws()
                time.sleep(0.5)
                ok = start_winws_hidden(self.cfg["zapret_root"], bat)
                running = wait_winws_alive(6.0)
        if ok and running:
            self.cfg["active_config"] = bat
            save_config(self.cfg)
            msg = f"{bat} запущен (без автозагрузки)"
            log_action(f"Вручную запущен конфиг без службы: {bat}", "apply")
        else:
            try:
                diag
            except NameError:
                diag = ""
            if not is_admin():
                msg = (f"{bat}: не запустился — нужны права администратора "
                       f"(запустите через run.bat)")
            elif diag:
                msg = f"{bat}: не запустился: {diag[:220]}"
            else:
                msg = f"{bat}: не запустился (см. журнал действий)"
            log_action(f"Ошибка разового запуска {bat}: {(diag or '')[:400]}",
                       "error")
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
        self.dom_hint = tk.Label(row, text="Клик по строке — просмотр, тумблер справа — вкл/выкл",
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
        # Scrollable frame with checkboxes instead of Listbox
        self.dom_scroll = ScrollFrame(l, bg=CARD)
        self.dom_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.dom_items_frame = self.dom_scroll.inner
        self.dom_vars = {}  # оставлено для совместимости
        self.dom_row_frames = {}  # base_name -> frame
        self.dom_row_labels = {}  # base_name -> Label (зелёный/красный)
        self.dom_row_toggles = {}  # base_name -> Toggle
        self._dom_selected = ""  # выбранный для просмотра список
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

    def _is_disabled(self, fname):
        return fname.endswith(".disabled")

    def _get_base_name(self, fname):
        if fname.endswith(".disabled"):
            return fname[:-9]
        return fname

    def _collect_list_files(self):
        """base -> (fname, disabled). Возвращает отсортированный dict."""
        all_files = {}
        d = self._lists_dir()
        if not d:
            return all_files
        for fp in glob.glob(os.path.join(d, "*.txt")):
            fname = os.path.basename(fp)
            base = self._get_base_name(fname)
            disabled = self._is_disabled(fname)
            if base not in all_files:
                all_files[base] = (fname, disabled)
            elif disabled and not all_files[base][1]:
                # .disabled важнее: именно он отражает выключенное состояние
                all_files[base] = (fname, disabled)
        for fp in glob.glob(os.path.join(d, "*.txt.disabled")):
            fname = os.path.basename(fp)
            base = self._get_base_name(fname)
            all_files[base] = (fname, True)
        return all_files

    def _is_list_enabled(self, base):
        """Актуальное состояние по файловой системе (не по виджетам)."""
        d = self._lists_dir()
        if not d:
            return False
        if os.path.exists(os.path.join(d, base + ".disabled")):
            return False
        return os.path.exists(os.path.join(d, base))

    def refresh_domains_list(self):
        try:
            # Clear existing widgets
            for w in self.dom_items_frame.winfo_children():
                w.destroy()
            self.dom_vars.clear()
            self.dom_row_frames.clear()
            self.dom_row_labels.clear()
            self.dom_row_toggles.clear()

            d = self._lists_dir()
            if not d:
                self.dom_hint.config(text="Папка lists/ не найдена — проверьте корневую папку в Настройках")
                return

            all_files = self._collect_list_files()
            self.dom_hint.config(text=f"Списки из {d} — изменения вступят в силу после перезапуска zapret")

            for base in sorted(all_files.keys()):
                fname, disabled = all_files[base]
                self._create_list_row(base, fname, disabled)

            # восстановить выбор (или первый), но НЕ переключать состояние
            keep = getattr(self, "_dom_selected", "")
            if keep in all_files:
                self._select_list(keep)
            elif all_files:
                self._select_list(sorted(all_files.keys())[0])
        except Exception:
            pass

    def _create_list_row(self, base, fname, disabled):
        """Строка списка в духе мод-листа: подпись + тумблер справа.

        Зелёная — включён, красная — выключен. Клик по строке только ВЫБИРАЕТ
        список для просмотра справа; переключает только сам тумблер.
        """
        row = tk.Frame(self.dom_items_frame, bg=CARD)
        row.pack(fill="x", padx=4, pady=2)
        self.dom_row_frames[base] = row

        fg = GREEN if not disabled else RED
        lbl = tk.Label(row, text=("● " + base), bg=CARD, fg=fg,
                       font=(FONT, 10), anchor="w", cursor="hand2")
        lbl.pack(side="left", fill="x", expand=True, padx=(6, 0), pady=3)
        self.dom_row_labels[base] = lbl
        var = tk.BooleanVar(value=not disabled)
        tg = Toggle(row, variable=var, width=40, height=22,
                    command=lambda b=base, v=var: self._on_list_toggle(b, v))
        tg.pack(side="right", padx=(0, 6), pady=3)
        self.dom_row_toggles[base] = tg

        for w in (row, lbl):
            w.bind("<Button-1>", lambda e, b=base: self._select_list(b), add="+")
            w.bind("<Enter>", lambda e, b=base: self._on_list_hover(b, True), add="+")
            w.bind("<Leave>", lambda e, b=base: self._on_list_hover(b, False), add="+")

    def _on_list_toggle(self, base, var):
        """Тумблер строки: вкл/выкл именно этот список."""
        try:
            self._set_list_enabled(base, bool(var.get()))
        except Exception:
            pass
        # вернуть тумблер в фактическое состояние (переименование файлов)
        try:
            cur = self._is_list_enabled(base)
            if var.get() != cur:
                var.set(cur)
        except Exception:
            pass

    def _on_list_hover(self, base, inside):
        """Лёгкая подсветка при наведении (выбранная строка не трогаем)."""
        try:
            if getattr(self, "_dom_selected", "") == base:
                return
            frame = self.dom_row_frames.get(base)
            if frame is None:
                return
            bg = CARD2 if inside else CARD
            frame.configure(bg=bg)
            lbl = self.dom_row_labels.get(base)
            if lbl is not None:
                lbl.configure(bg=bg)
        except Exception:
            pass

    def _set_list_enabled(self, base, enable):
        """Включить/выключить конкретный список (переименование файлов)."""
        if not base:
            return
        d = self._lists_dir()
        if not d:
            return
        disabled_path = os.path.join(d, base + ".disabled")
        enabled_path = os.path.join(d, base)
        try:
            if enable:
                if os.path.exists(disabled_path):
                    os.rename(disabled_path, enabled_path)
                    log_action(f"Список включён: {base}", "lists")
                else:
                    self.dlg_info(f"«{base}» уже включён")
                    return
            else:
                if os.path.exists(enabled_path):
                    os.rename(enabled_path, disabled_path)
                    log_action(f"Список выключен: {base}", "lists")
                else:
                    self.dlg_info(f"«{base}» уже выключен")
                    return
        except Exception as e:
            self.dlg_error(f"Не удалось переключить {base}: {e}")
            return
        self.refresh_domains_list()

    def _select_list(self, base):
        """Выбрать список для просмотра/редактирования. Состояние НЕ меняет."""
        self._dom_selected = base
        # Highlight selected row
        for b, frame in self.dom_row_frames.items():
            try:
                lbl = self.dom_row_labels.get(b)
                if b == base:
                    frame.configure(bg=ACCENT_DEEP)
                    if lbl is not None:
                        lbl.configure(bg=ACCENT_DEEP)
                else:
                    frame.configure(bg=CARD)
                    if lbl is not None:
                        lbl.configure(bg=CARD)
            except Exception:
                pass

        # Determine real filename
        d = self._lists_dir()
        if not d:
            return
        enabled = self._is_list_enabled(base)
        real_name = base if enabled else (base + ".disabled")
        fp = os.path.join(d, real_name)
        self._dom_current = fp

        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            status = " [ВЫКЛ]" if not enabled else " [ВКЛ]"
            self.dom_title.config(
                text=f"{real_name}  ({len(content.splitlines())} строк, {len(content)} симв.){status}")
            self.dom_text.delete("1.0", "end")
            self.dom_text.insert("end", content)
        except Exception as e:
            self.dlg_error(f"Не удалось прочитать файл: {e}")

    def show_domain_file(self):
        """Called when user clicks on a row - kept for compatibility"""
        pass

    def save_domain_file(self):
        fp = self._dom_current
        if not fp:
            self.dlg_info("Выберите файл слева")
            return
        try:
            if os.path.exists(fp):
                shutil.copy2(fp, fp + ".bak")
            with open(fp, "w", encoding="utf-8") as f:
                f.write(self.dom_text.get("1.0", "end-1c").replace("\n", "\n"))
            try:
                fname = os.path.basename(fp)
                status = " [OFF]" if fname.endswith(".disabled") else " [ON]"
                self.dom_title.config(
                    text=f"{fname}  (сохранено, бэкап: .bak){status}")
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
        self._section(l, "Файлы").pack(anchor="w", padx=12, pady=(10, 4))
        self.logs_list = tk.Listbox(l, bg=CARD2, fg=TEXT, font=(FONT, 9),
                                    bd=0, highlightthickness=0, selectbackground=ACCENT,
                                    selectforeground="white")
        self.logs_list.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.logs_list.bind("<<ListboxSelect>>", lambda e: self.show_log_file())
        o2, r = self.card(mid)
        o2.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self._section(r, "Содержимое").pack(anchor="w", padx=12, pady=(10, 4))
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
        ("monitor", "📡  Мониторинг"),
        ("appear", "🎨  Оформление"),
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
        self._build_set_monitor()
        self._build_set_appear()
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
                b.config(bg=ACCENT, fg="white", font=(FONT, 10, "bold"),
                         activebackground=ACCENT_HOVER)
            else:
                b.config(bg=CARD, fg=MUTED, font=(FONT, 10),
                         activebackground=CARD2)

    def _set_scroll(self, parent):
        o, box = self.card(parent)
        o.pack(fill="both", expand=True)
        scr = ScrollFrame(box, bg=CARD)
        scr.pack(fill="both", expand=True, padx=12, pady=12)
        return scr.inner

    def _set_row(self, parent, label, hint=""):
        """Строка настройки: подпись слева, место под контрол справа."""
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=8, pady=5)
        left = tk.Frame(row, bg=CARD)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text=label, bg=CARD, fg=TEXT, font=(FONT, 10),
                 anchor="w").pack(anchor="w")
        if hint:
            tk.Label(left, text=hint, bg=CARD, fg=MUTED, font=(FONT, 9),
                     anchor="w").pack(anchor="w")
        ctl = tk.Frame(row, bg=CARD)
        ctl.pack(side="right", padx=(12, 0))
        return ctl

    def _build_set_folder(self):
        inner = self._set_scroll(self.set_pages["folder"])
        self._section(inner, "Корневая папка zapret").pack(anchor="w", padx=8, pady=(8, 2))
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

    def _build_set_monitor(self):
        inner = self._set_scroll(self.set_pages["monitor"])
        self._section(inner, "Мониторинг и автопереключение").pack(anchor="w", padx=8, pady=(8, 2))
        self.mon_var = tk.BooleanVar(value=bool(self.cfg.get("monitor_enabled", True)))
        ctl = self._set_row(inner, "Следить за соединением",
                            "при проблемах — переключить на рабочий конфиг")
        Toggle(ctl, variable=self.mon_var,
               command=self.on_monitor_toggle).pack(anchor="e")
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
        self._section(inner, "Оформление").pack(anchor="w", padx=8, pady=(8, 2))
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
        self._section(inner, "Шрифт и масштаб").pack(anchor="w", padx=8, pady=(10, 2))
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
        self.silly_var = tk.BooleanVar(value=bool(self.cfg.get("silly_mode", False)))
        ctl = self._set_row(inner, "Funny option",
                            "телик с гифками, фон и silly-иконка")
        Toggle(ctl, variable=self.silly_var,
               command=self.on_silly_toggle).pack(anchor="e")

    def _build_set_app(self):
        inner = self._set_scroll(self.set_pages["app"])
        self._section(inner, "Приложение").pack(anchor="w", padx=8, pady=(8, 2))
        self.autostart_var = tk.BooleanVar(value=bool(self.cfg.get("app_autostart", False)))
        ctl = self._set_row(inner, "Запускать вместе с Windows",
                            "с правами администратора")
        Toggle(ctl, variable=self.autostart_var,
               command=self.on_autostart_toggle).pack(anchor="e")
        RButton(inner, text="📂 Открыть папку данных", style="ghost",
                   command=self.open_data_folder).pack(anchor="w", padx=8, pady=8)
        RButton(inner, text="📌 Создать ярлык на рабочем столе", style="accent",
                   command=self.on_make_shortcut).pack(anchor="w", padx=8, pady=(0, 8))
        RButton(inner, text="🔄 Обновить кэш иконок Windows", style="ghost",
                   command=self.on_refresh_icons).pack(anchor="w", padx=8, pady=(0, 8))
        tk.Label(inner, text=f"{APP_NAME} v{APP_VERSION} • только стандартная библиотека\n"
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
            # 2b. бэкап pre-configs целиком (свои подпапки/кастомные bat):
            # замена папки ниже снесла бы их вместе со старым корнем
            pre_src = os.path.join(root, PRECONFIGS_DIRNAME)
            if os.path.isdir(pre_src):
                try:
                    _sh.copytree(pre_src, os.path.join(tmp, "user",
                                                       PRECONFIGS_DIRNAME),
                                 ignore_dangling_symlinks=True)
                    user_files.append(PRECONFIGS_DIRNAME)
                except Exception as e:
                    log_action(f"Бэкап {PRECONFIGS_DIRNAME} не удался: {e}",
                               "error")
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
                if relp == PRECONFIGS_DIRNAME:
                    continue  # pre-configs — отдельно шагом 6b
                src = os.path.join(tmp, "user", relp)
                if os.path.isfile(src):
                    dst = os.path.join(root, relp)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    _sh.copy2(src, dst)
            # 6b. вернуть кастомы из pre-configs (только то, чего нет в
            # свежем релизе — одноимённые берём свежие), затем разложить
            # свежие bat из корня по pre-configs
            try:
                pre_bak = os.path.join(tmp, "user", PRECONFIGS_DIRNAME)
                pre_new = os.path.join(root, PRECONFIGS_DIRNAME)
                if os.path.isdir(pre_bak):
                    fresh_names = set()
                    if os.path.isdir(pre_new):
                        for _dp, _dn, _fns in os.walk(pre_new):
                            fresh_names.update(_fns)
                    for _dp, _dn, _fns in os.walk(pre_bak):
                        for _fn in _fns:
                            if _fn in fresh_names:
                                continue
                            _src = os.path.join(_dp, _fn)
                            _rel = os.path.relpath(_src, pre_bak)
                            _dst = os.path.join(pre_new, _rel)
                            os.makedirs(os.path.dirname(_dst), exist_ok=True)
                            _sh.copy2(_src, _dst)
            except Exception as e:
                log_action(f"Возврат кастомов {PRECONFIGS_DIRNAME}: {e}",
                           "error")
            try:
                moved, omsg = organize_configs(root)
                log_action(f"Раскладка конфигов после переустановки: {omsg}")
            except Exception as e:
                log_action(f"Раскладка конфигов не удалась: {e}", "error")
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
        # раскладка конфигов: pre-configs/ + всё внутрь
        try:
            moved, omsg = organize_configs(v)
            log_action(f"Раскладка конфигов: {omsg}")
            if moved:
                self.msg_q.put(("toast", ("Конфиги",
                                          f"{omsg}. Проверка смотрит туда "
                                          f"и в подпапки.", GREEN)))
        except Exception as e:
            log_action(f"Раскладка конфигов не удалась: {e}", "error")
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

    # ---------- static ----------
    def refresh_all_static(self):
        cfgs = list_configs(self.cfg.get("zapret_root", ""))
        # сохранить галочки пользователя (иначе обновление списка во время
        # проверки сбрасывало бы выбор и казалось, что «окно конфигов пропало»)
        try:
            prev_sel = {k: bool(v.get()) for k, v in self.cfg_vars.items()}
        except Exception:
            prev_sel = {}
        for w in self.cfg_checks.winfo_children():
            w.destroy()
        self.cfg_vars = {}
        self.cfg_toggles = {}
        for bat in cfgs:
            v = tk.BooleanVar(value=prev_sel.get(bat, True))
            self.cfg_vars[bat] = v
            row = tk.Frame(self.cfg_checks, bg=CARD)
            row.pack(fill="x", anchor="w", pady=1)
            lbl = tk.Label(row, text=display_bat(bat), bg=CARD, fg=TEXT,
                           font=(FONT, 10), anchor="w", cursor="hand2")
            lbl.pack(side="left", fill="x", expand=True, padx=(2, 0))
            tg = Toggle(row, variable=v)
            tg.pack(side="left", padx=4)
            self.cfg_toggles[bat] = tg
            # ▶ — выбрать конфиг сразу, без запуска проверки
            tk.Button(row, text="▶", bg=CARD, fg=ACCENT2, font=(FONT, 10, "bold"),
                      bd=0, cursor="hand2", activebackground=CARD2,
                      activeforeground=TEXT, width=3,
                      command=lambda b=bat: self.on_apply_config(b)).pack(side="right")

            def _flip(_e=None, _v=v):
                try:
                    _v.set(not bool(_v.get()))
                except Exception:
                    pass

            lbl.bind("<Button-1>", _flip, add="+")
            row.bind("<Button-1>", _flip, add="+")
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
        self.root.after(500, self.refresh_active_bar)
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
    # DPI: Per-Monitor V2 СРАЗУ (до создания окон!) — иначе Windows
    # битмапно тянет окно (двоение/мыло/тормоза на масштабах ≠100%).
    # Tk 9 сам дорисовывает остальное.
    try:
        if os.name == "nt":
            try:
                ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
            except Exception:
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)
                except Exception:
                    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    minimized = "--minimized" in sys.argv
    if not ensure_single_instance():
        sys.exit(0)
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
