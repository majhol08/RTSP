#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RTSP Dashboard — Safe Smart PRO (Arabic UI)
نسخة مُحسّنة بواجهة عربية احترافية مع:
- تقسيم مرن عبر PanedWindow لإعطاء العناصر مساحة حرّة.
- تعريب كامل للنصوص والعناوين.
- شريط أدوات علوي مبسّط + تلميحات.
- جدول قابل للفرز/التصفية + قائمة يمين (نسخ IP/URL/الصف).
- أزرار "نسخ" سريعة أسفل الجدول لنسخ الروابط/العناوين المختارة.
- معاينات قابلة للتكبير (نافذة عائمة) بالنقر المزدوج.
- إبراز الحالة بالألوان (ناجحة/فاشلة).
- حفظ تفضيلات بسيطة (آخر منافذ/خيارات) تلقائياً.

ملاحظة: تعتمد على نسخة "PRO" السابقة في المنطق (الكشف الذكي/الكاش/الفحص/المعاينات).
المتطلبات:
    pip install opencv-python pillow
(اختياري) ONVIF: pip install onvif-zeep
"""
import os
import time
import socket
import threading
import json
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Dict, Tuple

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;7000000|max_delay;5000000")
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

try:
    import cv2
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)  # type: ignore
    except Exception:
        pass
except Exception:
    print("تحتاج لتثبيت OpenCV: pip install opencv-python")
    raise

try:
    import tkinter as tk
    from tkinter import messagebox, filedialog, simpledialog
    try:
        import ttkbootstrap as ttk
        BOOTSTRAP = True
    except Exception:  # pragma: no cover - fallback if ttkbootstrap missing
        from tkinter import ttk  # type: ignore
        BOOTSTRAP = False
except Exception:
    print("tkinter مفقود في بيئتك.")
    raise

try:
    from PIL import Image, ImageTk
except Exception:
    print("تحتاج لتثبيت Pillow: pip install pillow")
    raise

# ONVIF (اختياري)
HAS_ONVIF = False
try:
    from onvif import ONVIFCamera  # type: ignore
    HAS_ONVIF = True
except Exception:
    HAS_ONVIF = False

APP_TITLE = "لوحة RTSP — احترافية وآمنة (واجهة عربية)"
CACHE_FILE = "rtsp_smart_cache.json"
PREFS_FILE = "rtsp_prefs.json"

# مقتبس من النسخة PRO (تستطيع تعديل/توسيع لاحقاً)
VENDOR_DB: Dict[str, Dict] = {
    "hikvision": {
        "match": ["hikvision"],
        "paths": ["Streaming/Channels/101", "Streaming/Channels/102", "h264Preview_01_main", "h264Preview_01_sub"],
        "ports": [554, 10554],
        "defaults": [("admin", "12345"), ("admin", "admin"), ("admin", "")],
    },
    "dahua": {
        "match": ["dahua", "general"],
        "paths": ["cam/realmonitor?channel=1&subtype=0", "cam/realmonitor?channel=1&subtype=1"],
        "ports": [554],
        "defaults": [("admin", "admin"), ("admin", "")],
    },
    "axis": {
        "match": ["axis"],
        "paths": ["axis-media/media.amp", "axis-media/media.amp?videocodec=h264"],
        "ports": [554],
        "defaults": [("root", "pass"), ("root", "root"), ("root", "")],
    },
    "reolink": {
        "match": ["reolink"],
        "paths": ["Preview_01_main", "Preview_01_sub", "h264Preview_01_main", "h264Preview_01_sub"],
        "ports": [554],
        "defaults": [("admin", "")],
    },
    "uniview": {
        "match": ["uniview", "unv", "uv"],
        "paths": ["media/video1", "media/video2", "media/video3"],
        "ports": [554],
        "defaults": [("admin", "123456"), ("admin", "")],
    },
    "amcrest": {
        "match": ["amcrest"],
        "paths": ["cam/realmonitor?channel=1&subtype=0", "cam/realmonitor?channel=1&subtype=1", "h264Preview_01_main", "h264Preview_01_sub"],
        "ports": [554],
        "defaults": [("admin", "admin"), ("admin", "")],
    },
    "foscam": {
        "match": ["foscam"],
        "paths": ["videoMain", "videoSub"],
        "ports": [88, 554],
        "defaults": [("admin", ""), ("user", "user")],
    },
    "tapo": {
        "match": ["tapo"],
        "paths": ["stream1", "stream2", "stream6", "stream7"],
        "ports": [554],
        "defaults": [],
    },
    "hanwha": {
        "match": ["hanwha", "wisenet", "samsung"],
        "paths": ["profile1/media.smp", "profile2/media.smp"],
        "ports": [554],
        "defaults": [("admin", "111111"), ("admin", "4321"), ("admin", "")],
    },
    "bosch": {
        "match": ["bosch"],
        "paths": ["", "video?inst=1", "video?inst=2", "?inst=1", "?inst=2"],
        "ports": [554],
        "defaults": [("admin", "admin"), ("admin", "")],
    },
    "unifi_protect": {
        "match": ["unifi", "ubiquiti", "protect"],
        "paths": [""],
        "ports": [7447],
        "defaults": [],
    },
    "generic": {
        "match": [],
        "paths": ["", "live", "live.sdp", "h264", "h265", "stream", "stream1", "stream2", "0", "1", "video", "video.mp4", "unicast"],
        "ports": [554, 8554],
        "defaults": [("admin", "admin"), ("admin", "12345"), ("admin", ""), ("user", "user")],
    },
}

ERROR_HINTS = {
    401: "401 غير مخوّل — تحقّق من اسم المستخدم/كلمة المرور ونوع المصادقة (Basic/Digest).",
    404: "404 لم يتم العثور على البث — عدّل مسار RTSP ليتوافق مع طراز الكاميرا.",
    451: "451 — خطأ من الجهاز/البرنامج الثابت. جرّب تقليل الحمل أو إعادة التشغيل أو تفعيل RTSP.",
    500: "500 — خطأ داخلي. تحقّق من الإعدادات/الإصدار وأعد المحاولة.",
}

def ping_host(ip: str, port: int, timeout: float = 1.2) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False

def rtsp_headers(ip: str, port: int, timeout: float = 2.5) -> Dict[str, str]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    headers = {}
    try:
        s.connect((ip, port))
        req = f"DESCRIBE rtsp://{ip}:{port}/ RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: RTSP-ArUI/1.0\r\nAccept: application/sdp\r\n\r\n"
        s.sendall(req.encode("ascii", "ignore"))
        data = s.recv(4096)
        raw = data.decode("latin1", "ignore").split("\r\n")
        for line in raw[1:]:
            if not line.strip():
                break
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
    except Exception:
        pass
    finally:
        try: s.close()
        except Exception: pass
    return headers

def detect_vendor(headers: Dict[str, str]) -> str:
    text = " ".join(headers.get(k, "") for k in ("server", "www-authenticate", "proxy-authenticate")).lower()
    for vendor, info in VENDOR_DB.items():
        if any(token in text for token in info["match"]):
            return vendor
    return "generic"

def build_urls(ip: str, port: int, user: Optional[str], pwd: Optional[str], paths: List[str]) -> List[str]:
    auth = ""
    if user:
        if pwd is None:
            pwd = ""
        auth = f"{user}:{pwd}@"
    host = f"{ip}:{port}"
    urls = []
    for p in paths:
        p = str(p).lstrip("/")
        urls.append(f"rtsp://{auth}{host}" + ("" if p == "" else f"/{p}"))
    return urls

def quick_open(url: str, warm_ms: int = 220) -> bool:
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        cap.release()
        return False
    time.sleep(warm_ms/1000.0)
    ok, _ = cap.read()
    cap.release()
    return bool(ok)

# -------------------------------- UI ---------------------------------

class BigPreview(tk.Toplevel):
    def __init__(self, master, title: str, url: str):
        super().__init__(master)
        self.title(title)
        self.geometry("960x540")
        self.label = ttk.Label(self, text="...")
        self.label.pack(fill="both", expand=True)
        self.running = True
        self.cap = None
        self.url = url
        self.after(10, self._start)

    def _start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def destroy(self):
        self.running = False
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass
        super().destroy()

    def _loop(self):
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            self.after(0, lambda: self.label.config(text="تعذر فتح البث"))
            return
        self.cap = cap
        consecutive_fail = 0
        while self.running:
            try:
                ok, frame = cap.read()
            except Exception:
                ok = False
            if not ok:
                consecutive_fail += 1
                if consecutive_fail >= 10:
                    break
                time.sleep(0.1)
                continue
            consecutive_fail = 0
            # ملاءمة نافذة المعاينة
            try:
                w = max(self.label.winfo_width(), 640)
                h = max(self.label.winfo_height(), 360)
                frame = cv2.resize(frame, (w, h))
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            except Exception:
                continue
            def update_on_main(img_arr=rgb):
                pil_img = Image.fromarray(img_arr)
                imgtk = ImageTk.PhotoImage(master=self.label, image=pil_img)
                self.label.imgtk = imgtk
                self.label.config(image=imgtk, text="")
            self.after(0, update_on_main)
        self.running = False
        self.after(0, lambda: self.label.config(text="انقطع البث"))

class PreviewTile(ttk.Frame):
    def __init__(self, master, cam_id: int, url: str, on_close, on_open_big, *args, **kwargs):
        super().__init__(master, padding=6, *args, **kwargs)
        self.cam_id = cam_id
        self.url = url
        self.on_close = on_close
        self.on_open_big = on_open_big
        self.running = False
        self.cap = None
        self._build()

    def _build(self):
        bar = ttk.Frame(self); bar.pack(fill="x")
        ttk.Label(bar, text=f"#{self.cam_id}", style="Header.TLabel").pack(side="left")
        ttk.Button(bar, text="تكبير", width=6, command=self.open_big).pack(side="right", padx=4)
        ttk.Button(bar, text="إيقاف", width=6, command=self.stop).pack(side="right")
        self.label = ttk.Label(self, text="..."); self.label.pack(fill="both", expand=True)
        self.label.bind("<Double-Button-1>", lambda e: self.open_big())

    def open_big(self):
        self.on_open_big(self.cam_id, self.url)

    def start(self):
        if self.running: return
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False
        self.after(0, self._cleanup)

    def _cleanup(self):
        if self.cap is not None:
            try: self.cap.release()
            except Exception: pass
            self.cap = None
        self.on_close(self.cam_id)

    def _loop(self):
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            self.after(0, lambda: self.label.config(text="تعذر فتح البث"))
            self.running = False
            self.after(0, self._cleanup)
            return
        self.cap = cap
        consecutive_fail = 0
        while self.running:
            try:
                ok, frame = cap.read()
            except Exception:
                ok = False
            if not ok:
                consecutive_fail += 1
                if consecutive_fail >= 10:
                    break
                time.sleep(0.1)
                continue
            consecutive_fail = 0
            try:
                frame = cv2.resize(frame, (320, 240))
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            except Exception:
                continue
            def update_on_main(img_arr=rgb):
                pil_img = Image.fromarray(img_arr)
                imgtk = ImageTk.PhotoImage(master=self.label, image=pil_img)
                self.label.imgtk = imgtk
                self.label.config(image=imgtk, text="")
            self.after(0, update_on_main)
        self.running = False
        self.after(0, self._cleanup)

root_cls = ttk.Window if BOOTSTRAP else tk.Tk

class Dashboard(root_cls):
    def __init__(self):
        if BOOTSTRAP:
            super().__init__(themename="flatly")
        else:
            super().__init__()
        self.title(APP_TITLE)
        self.geometry("1360x900")
        self.minsize(1150, 780)
        self.big_previews: Dict[int, BigPreview] = {}

        self.ui_style = ttk.Style()
        if not BOOTSTRAP:
            try:
                self.ui_style.theme_use("clam")
            except Exception:
                pass
        self.ui_style.configure("TButton", padding=8, font=("Segoe UI", 10))
        self.ui_style.configure("TLabel", font=("Segoe UI", 10))
        self.ui_style.configure("Header.TLabel", font=("Segoe UI", 10, "bold"))
        self.ui_style.configure("Good.TLabel", foreground="#137333")
        self.ui_style.configure("Warn.TLabel", foreground="#b06d00")
        self.ui_style.configure("Bad.TLabel", foreground="#a50e0e")
        self.ui_style.configure("URL.TLabel", foreground="#1558d6")
        self.ui_style.configure("Status.TLabel", font=("Segoe UI", 10))

        self.rows: Dict[int, Dict] = {}
        self.preview_tiles: Dict[int, PreviewTile] = {}
        self.max_workers = 8
        self.max_previews = 6
        self.cache: Dict[str, Dict] = {}
        self._load_cache()
        self._load_prefs()

        self._build_ui()

    # --------------- PREFERENCES -----------------
    def _load_prefs(self):
        self.prefs = {"probe_threads": 8, "max_previews": 6, "port": 554}
        try:
            with open(PREFS_FILE, "r", encoding="utf-8") as f:
                self.prefs.update(json.load(f))
        except Exception:
            pass

    def _save_prefs(self):
        try:
            with open(PREFS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.prefs, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # --------------- CACHE -----------------
    def _load_cache(self):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                self.cache = json.load(f)
        except Exception:
            self.cache = {}

    def _save_cache(self):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # --------------- UI -----------------
    def _build_ui(self):
        # شريط أدوات علوي
        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill="x")
        self.user_var = tk.StringVar(); self.pwd_var = tk.StringVar(); self.port_var = tk.StringVar(value=str(self.prefs.get("port", 554)))
        ttk.Label(toolbar, text="اسم المستخدم:").pack(side="right", padx=6)
        ttk.Entry(toolbar, width=16, textvariable=self.user_var).pack(side="right")
        ttk.Label(toolbar, text="كلمة المرور:").pack(side="right", padx=6)
        ttk.Entry(toolbar, width=16, textvariable=self.pwd_var, show="•").pack(side="right")
        ttk.Label(toolbar, text="المنفذ:").pack(side="right", padx=6)
        ttk.Entry(toolbar, width=7, textvariable=self.port_var).pack(side="right")
        ttk.Label(toolbar, text="خيوط الفحص:").pack(side="right", padx=6)
        self.threads_var = tk.IntVar(value=int(self.prefs.get("probe_threads", 8)))
        ttk.Spinbox(toolbar, from_=1, to=32, width=5, textvariable=self.threads_var).pack(side="right")
        ttk.Label(toolbar, text="عدد المعاينات:").pack(side="right", padx=6)
        self.previews_var = tk.IntVar(value=int(self.prefs.get("max_previews", 6)))
        ttk.Spinbox(toolbar, from_=1, to=16, width=5, textvariable=self.previews_var).pack(side="right")

        self.smart_var = tk.BooleanVar(value=True)
        self.try_defaults_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(toolbar, text="فحص ذكي", variable=self.smart_var).pack(side="left", padx=6)
        ttk.Checkbutton(toolbar, text="تجربة اعتماد افتراضي (بحدود)", variable=self.try_defaults_var).pack(side="left", padx=6)
        if BOOTSTRAP:
            ttk.Button(toolbar, text="🌓 تبديل النسق", command=self.toggle_theme).pack(side="left", padx=6)

        # واجهة على شكل ألسنة
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=6)

        # تبويب الكاميرات
        cam_tab = ttk.Frame(notebook, padding=8)
        notebook.add(cam_tab, text="الكاميرات")

        ips_box = ttk.LabelFrame(cam_tab, text="ألصق عنوان IP في كل سطر", padding=8)
        ips_box.pack(fill="x")
        self.ips_text = tk.Text(ips_box, height=4)
        self.ips_text.pack(fill="x", expand=False)
        ttk.Button(ips_box, text="إضافة إلى القائمة", command=self.on_add).pack(anchor="e", pady=(6,0))

        # شريط بحث/تصفية
        search_bar = ttk.Frame(cam_tab)
        search_bar.pack(fill="x", pady=(8,4))
        ttk.Label(search_bar, text="تصفية:").pack(side="left")
        self.filter_entry = ttk.Entry(search_bar, width=40)
        self.filter_entry.pack(side="left", padx=6)
        self.filter_entry.bind("<KeyRelease>", lambda e: self._refresh_table())

        # الجدول
        table_box = ttk.LabelFrame(cam_tab, text="الكاميرات", padding=6)
        table_box.pack(fill="both", expand=True)

        cols = ("id","ip","vendor","path","status","latency","url")
        headers_ar = {
            "id":"#",
            "ip":"العنوان",
            "vendor":"البائع",
            "path":"المسار",
            "status":"الحالة",
            "latency":"الكمون",
            "url":"الرابط"
        }
        self.tree = ttk.Treeview(table_box, columns=cols, show="headings", selectmode="extended")
        for c, w in zip(cols, (60,180,140,260,120,110,520)):
            self.tree.heading(c, text=headers_ar[c], command=lambda col=c: self._sort_by(col, False))
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(table_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

        # ألوان الصفوف حسب الحالة
        self.tree.tag_configure("SUCCESS", foreground="#137333")
        self.tree.tag_configure("FAILED", foreground="#a50e0e")

        # قائمة يمين (نسخ)
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="نسخ IP", command=lambda: self.copy_from_selection("ip"))
        self.menu.add_command(label="نسخ الرابط", command=lambda: self.copy_from_selection("url"))
        self.menu.add_command(label="نسخ الصف", command=lambda: self.copy_from_selection("row"))
        self.tree.bind("<Button-3>", self._popup_menu)

        # أزرار أسفل الجدول + نسخ سريع
        actions = ttk.Frame(cam_tab)
        actions.pack(fill="x", pady=(6,0))
        self.filter_var = tk.StringVar(value="ALL")
        for txt in ("ALL","SUCCESS","FAILED"):
            ttk.Radiobutton(actions, text=txt, value=txt, variable=self.filter_var, command=self._refresh_table).pack(side="left", padx=4)

        ttk.Button(actions, text="🔎 فحص الكل", command=self.on_probe_all).pack(side="right", padx=4)
        ttk.Button(actions, text="فحص المحدد", command=self.on_probe_selected).pack(side="right", padx=4)
        ttk.Button(actions, text="تعيين مسار للمحدد", command=self.on_set_path_selected).pack(side="right", padx=4)

        copy_bar = ttk.Frame(cam_tab)
        copy_bar.pack(fill="x", pady=(6,0))
        ttk.Button(copy_bar, text="نسخ IPs المحددة", command=lambda: self.copy_from_selection("ip")).pack(side="left", padx=4)
        ttk.Button(copy_bar, text="نسخ URLs المحددة", command=lambda: self.copy_from_selection("url")).pack(side="left", padx=4)
        ttk.Button(copy_bar, text="نسخ الصفوف المحددة", command=lambda: self.copy_from_selection("row")).pack(side="left", padx=4)

        control_bar = ttk.Frame(cam_tab)
        control_bar.pack(fill="x", pady=(6,0))
        ttk.Button(control_bar, text="▶️ تشغيل معاينة", command=self.on_start_selected).pack(side="left", padx=4)
        ttk.Button(control_bar, text="⏹ إيقاف معاينة", command=self.on_stop_selected).pack(side="left", padx=4)
        ttk.Button(control_bar, text="📸 لقطة", command=self.on_snapshot_selected).pack(side="left", padx=4)

        # تبويب المعاينات
        prev_tab = ttk.Frame(notebook, padding=8)
        notebook.add(prev_tab, text="المعاينات")
        preview_box = ttk.LabelFrame(prev_tab, text="المعاينات (320×240) — انقر مرتين للتكبير", padding=8)
        preview_box.pack(fill="both", expand=True)
        self.preview_grid = ttk.Frame(preview_box)
        self.preview_grid.pack(fill="both", expand=True)

        self.status_label = ttk.Label(self, text="جاهز", style="Status.TLabel")
        self.status_label.pack(anchor="w", padx=12, pady=(0,10))

        # إنهاء: إعادة رسم أولية
        self._refresh_table()

    def toggle_theme(self):
        if not BOOTSTRAP:
            return
        current = self.ui_style.theme_use()
        new_theme = "darkly" if current != "darkly" else "flatly"
        self.ui_style.theme_use(new_theme)

    # ----------------- Helpers -----------------
    def _popup_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def copy_from_selection(self, what: str):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("نسخ", "اختر صفوفًا أولاً."); return
        rows = []
        for iid in sel:
            vals = self.tree.item(iid, "values")
            row = { "id": vals[0], "ip": vals[1], "vendor": vals[2], "path": vals[3], "status": vals[4], "latency": vals[5], "url": vals[6] }
            if what == "ip":
                rows.append(row["ip"])
            elif what == "url":
                if row["url"]:
                    rows.append(row["url"])
            else:
                rows.append("\t".join(vals))
        text = "\n".join(rows)
        if text:
            self.clipboard_clear(); self.clipboard_append(text)
            self._set_status(f"تم نسخ {len(rows)} عنصر(عناصر) إلى الحافظة.", "good")
        else:
            self._set_status("لا يوجد ما يُنسخ.", "warn")

    def _sort_by(self, col, descending):
        data = [(self.tree.set(child, col), child) for child in self.tree.get_children('')]
        try:
            data.sort(reverse=descending, key=lambda t: (float(t[0].split()[0]) if col=="latency" and t[0]!="n/a" else t[0]))
        except Exception:
            data.sort(reverse=descending, key=lambda t: t[0])
        for ix, item in enumerate(data):
            self.tree.move(item[1], '', ix)
        self.tree.heading(col, command=lambda: self._sort_by(col, not descending))

    # ----------------- Data/Table -----------------
    def _refresh_table(self):
        # collect text filter
        text_filter = (self.filter_entry.get() or "").strip().lower()
        for item in self.tree.get_children():
            self.tree.delete(item)
        f = self.filter_var.get()
        rows = list(self.rows.values())
        if f == "SUCCESS":
            rows = [r for r in rows if r["status"] == "SUCCESS"]
        elif f == "FAILED":
            rows = [r for r in rows if r["status"] == "FAILED"]
        if text_filter:
            def match(r):
                bundle = f"{r['ip']} {r.get('vendor','')} {r.get('path','')} {r.get('status','')} {r.get('url','')}".lower()
                return text_filter in bundle
            rows = [r for r in rows if match(r)]
        for r in rows:
            tags = (r.get("status",""),)
            self.tree.insert("", "end", iid=str(r["id"]), values=(r["id"], r["ip"], r.get("vendor",""), r.get("path",""), r.get("status",""), r.get("latency",""), r.get("url","")), tags=tags)

    def _set_status(self, text, kind="info"):
        style = {"good":"Good.TLabel", "warn":"Warn.TLabel", "bad":"Bad.TLabel"}.get(kind, "Status.TLabel")
        self.status_label.config(text=f"الحالة: {text}", style=style)

    # ----------------- Add/Probe/Preview/Snapshot -----------------
    def on_add(self):
        txt = self.ips_text.get("1.0","end").strip()
        if not txt:
            messagebox.showwarning("تنبيه", "ألصق عناوين IP أولاً."); return
        try:
            port = int(self.port_var.get().strip() or "554")
        except Exception:
            port = 554
        user = self.user_var.get().strip() or None
        pwd = self.pwd_var.get() or None
        ips = [line.strip() for line in txt.splitlines() if line.strip()]
        start = len(self.rows) + 1
        for i, ip in enumerate(ips):
            cam_id = start + i
            cache_hit = self.cache.get(ip, {})
            self.rows[cam_id] = {
                "id": cam_id, "ip": ip, "port": cache_hit.get("port", port),
                "user": cache_hit.get("user", user), "pwd": cache_hit.get("pwd", pwd),
                "vendor": cache_hit.get("vendor", "unknown"),
                "path": cache_hit.get("path", "__AUTO__"),
                "status": "NEW", "latency": "", "url": "",
            }
        self._refresh_table()
        self._set_status(f"تمت إضافة {len(ips)} كاميرا.", "good")

        # حفظ تفضيلات حالية
        self.prefs["probe_threads"] = int(self.threads_var.get())
        self.prefs["max_previews"] = int(self.previews_var.get())
        try:
            self.prefs["port"] = int(self.port_var.get().strip() or "554")
        except Exception:
            pass
        self._save_prefs()

    def on_set_path_selected(self):
        sel = [int(i) for i in self.tree.selection()]
        if not sel: messagebox.showinfo("معلومة", "اختر كاميرات من الجدول أولاً."); return
        path = simpledialog.askstring("تعيين المسار", "أدخل مسار RTSP (مثال Streaming/Channels/101). اتركه فارغاً للعودة إلى AUTO:")
        if path is None: return
        path = path.strip() or "__AUTO__"
        for cam_id in sel:
            r = self.rows[cam_id]; r["path"] = path; r["status"] = "NEW"; r["url"] = ""; r["latency"]=""
        self._refresh_table()

    # --- ذكاء الفحص (مبسّط: يعتمد على رؤوس RTSP والكاش) ---
    def _smart_probe_single(self, r: Dict) -> Tuple[str, str, str, float, str, Tuple[Optional[str], Optional[str], int]]:
        ip = r["ip"]
        user, pwd = r.get("user"), r.get("pwd")
        path_setting = r.get("path", "__AUTO__")
        # منافذ مرشحة
        base_port = int(r.get("port") or 554)
        candidate_ports: List[int] = [base_port]
        headers = self._rtsp_headers_safe(ip, base_port)
        vendor = detect_vendor(headers)
        vendor_info = VENDOR_DB.get(vendor, VENDOR_DB["generic"])
        for p in vendor_info.get("ports", []):
            if p not in candidate_ports: candidate_ports.append(p)
        for p in VENDOR_DB["generic"]["ports"]:
            if p not in candidate_ports: candidate_ports.append(p)
        # مسارات
        paths = [path_setting] if path_setting != "__AUTO__" else (vendor_info["paths"] or VENDOR_DB["generic"]["paths"])
        start = time.time()
        for port in candidate_ports:
            if not ping_host(ip, port):
                continue
            urls = build_urls(ip, port, user, pwd, paths)
            for pth, url in zip(paths, urls):
                if quick_open(url):
                    elapsed_ms = (time.time()-start)*1000.0
                    return "SUCCESS", url, vendor, elapsed_ms, pth, (user, pwd, port)
            if self.try_defaults_var.get():
                defaults = vendor_info.get("defaults", [])[:3]
                for u, pw in defaults:
                    urls = build_urls(ip, port, u, pw, paths)
                    for pth, url in zip(paths, urls):
                        if quick_open(url):
                            elapsed_ms = (time.time()-start)*1000.0
                            return "SUCCESS", url, vendor, elapsed_ms, pth, (u, pw, port)
        elapsed_ms = (time.time()-start)*1000.0
        return "FAILED","", vendor, elapsed_ms, (paths[0] if paths else ""), (user, pwd, base_port)

    def _rtsp_headers_safe(self, ip, port):
        try:
            return rtsp_headers(ip, port)
        except Exception:
            return {}

    def on_probe_all(self): self._probe_ids(list(self.rows.keys()))
    def on_probe_selected(self):
        sel = [int(i) for i in self.tree.selection()]
        if not sel: messagebox.showinfo("معلومة", "اختر كاميرات من الجدول أولاً."); return
        self._probe_ids(sel)

    def _probe_ids(self, ids: List[int]):
        if not ids: return
        self._set_status("جاري الفحص الذكي...", "warn")
        self.max_workers = int(self.threads_var.get() or 8)

        def run():
            succ, fail = 0, 0
            with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                futures = {ex.submit(self._smart_probe_single, self.rows[cid]): cid for cid in ids}
                for fut in as_completed(futures):
                    cam_id = futures[fut]
                    status, url, vendor, elapsed, path_used, creds = fut.result()
                    r = self.rows[cam_id]
                    r["status"] = status; r["url"]=url; r["latency"]=f"{elapsed:.0f} ms" if elapsed>=0 else "n/a"
                    r["vendor"] = vendor
                    if path_used: r["path"] = path_used
                    if status == "SUCCESS":
                        succ += 1
                        u,pw,port_used = creds
                        r["port"] = port_used
                        self.cache[r["ip"]] = {"vendor": vendor, "path": r["path"], "user": u, "pwd": pw, "port": port_used}
                    else:
                        fail += 1
                    self.after(0, self._refresh_table)
            self._save_cache()
            self.after(0, lambda: self._set_status(f"انتهى الفحص — ناجحة: {succ}, فاشلة: {fail}", "good" if succ else "bad"))
        threading.Thread(target=run, daemon=True).start()

    def on_start_selected(self):
        ids = [int(i) for i in self.tree.selection()]
        if not ids: messagebox.showinfo("معلومة", "اختر كاميرات ناجحة من الجدول."); return
        success_ids = [i for i in ids if self.rows[i]["status"] == "SUCCESS" and self.rows[i]["url"]]
        if not success_ids: messagebox.showwarning("تنبيه", "لا توجد كاميرات ناجحة للافتتاح."); return
        self.max_previews = int(self.previews_var.get() or 6)
        current = len(self.preview_tiles); slots = max(0, self.max_previews - current)
        if slots <= 0: messagebox.showwarning("تنبيه", "وصلت للحد الأقصى للمعاينات."); return
        for cam_id in success_ids[:slots]:
            self._open_preview(cam_id)

    def _open_preview(self, cam_id: int):
        if cam_id in self.preview_tiles: return
        url = self.rows[cam_id]["url"]
        tile = PreviewTile(self.preview_grid, cam_id, url, on_close=self._on_tile_close, on_open_big=self._open_big_preview)
        self.preview_tiles[cam_id] = tile
        idx = len(self.preview_tiles)-1; r, c = divmod(idx, 3)
        tile.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")
        self.preview_grid.grid_columnconfigure(c, weight=1)
        tile.start(); self._set_status(f"تشغيل معاينة للكاميرا #{cam_id}", "good")

    def _open_big_preview(self, cam_id: int, url: str):
        if cam_id in self.big_previews and self.big_previews[cam_id].winfo_exists():
            try: self.big_previews[cam_id].lift(); return
            except Exception: pass
        win = BigPreview(self, f"معاينة مكبرة — كاميرا #{cam_id}", url)
        self.big_previews[cam_id] = win

    def _on_tile_close(self, cam_id: int):
        tile = self.preview_tiles.pop(cam_id, None)
        if tile is not None:
            try: tile.destroy()
            except Exception: pass

    def on_stop_selected(self):
        ids = [int(i) for i in self.tree.selection()]
        stop_all = not ids
        for k, tile in list(self.preview_tiles.items()):
            if stop_all or (k in ids):
                tile.stop()

    def on_snapshot_selected(self):
        sel = self.tree.selection()
        if not sel: messagebox.showinfo("معلومة", "اختر كاميرا واحدة من الجدول."); return
        cam_id = int(sel[0]); r = self.rows[cam_id]
        if r["status"] != "SUCCESS" or not r["url"]:
            messagebox.showwarning("تنبيه", "هذه الكاميرا ليست في حالة ناجحة."); return
        path = filedialog.asksaveasfilename(defaultextension=".jpg",
                                            filetypes=[("JPEG","*.jpg"),("PNG","*.png"),("All Files","*.*")],
                                            title=f"حفظ لقطة - كاميرا #{cam_id}")
        if not path: return
        def worker():
            cap = cv2.VideoCapture(r["url"], cv2.CAP_FFMPEG)
            ok, frame = cap.read(); cap.release()
            def done():
                if ok:
                    import os
                    ext = os.path.splitext(path)[1].lower()
                    if ext == ".png": cv2.imwrite(path, frame, [cv2.IMWRITE_PNG_COMPRESSION, 3])
                    else: cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    self._set_status(f"تم حفظ لقطة: {path}", "good")
                else:
                    self._set_status("تعذر التقاط لقطة.", "bad")
            self.after(0, done)
        threading.Thread(target=worker, daemon=True).start()

def main():
    app = Dashboard()
    app.mainloop()

if __name__ == "__main__":
    main()
