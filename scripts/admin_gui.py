"""摄影站 · 桌面管理工具

做四件事：
  1) 账号：添加 / 登录 / 启用停用（对应 data/accounts.json 与独立 profile）
  2) 作品：勾选哪些文章对外显示（写 works.json 的 hidden），一键抓取新笔记
  3) 刷新：重新拉取已有笔记的内容（发布日期保持首次发布不变）
  4) 推送：git add / commit / push，推完 GitHub Pages 自动更新

依赖：Python 3.13+（需带 tkinter）、Pillow；运行时用 pythonw.exe 可无黑窗。
"""
import json
import os
import queue
import subprocess
import sys
import threading
import webbrowser

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except Exception:
    HAS_PIL = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
WORKS_JSON = os.path.join(DATA, "works.json")
ACCOUNTS_JSON = os.path.join(DATA, "accounts.json")
PROFILE_JSON = os.path.join(DATA, "profile.json")
PROFILES = os.path.join(DATA, "profiles")
SITE_URL = "https://www.frw.fan/"

# 高 DPI 屏下保持字体清晰（必须在创建 Tk 之前设置）
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

C_BG = "#ffffff"
C_FG = "#14110f"
C_SOFT = "#6b665f"
C_LINE = "#e6e3de"
C_ACCENT = "#14110f"
C_OK = "#1f7a4d"
C_WARN = "#b0621b"


def python_exe():
    """子进程用 python.exe（pythonw 拿不到 stdout）。"""
    p = sys.executable
    if p.lower().endswith("pythonw.exe"):
        return p[: -len("pythonw.exe")] + "python.exe"
    return p


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.works_data = load_json(WORKS_JSON, {"site": {}, "categories": [], "works": []})
        self.accounts_data = load_json(ACCOUNTS_JSON, {"accounts": []})
        self.profile_data = load_json(PROFILE_JSON, {})

        self.title(f"{self.author_name()} · 管理工具")
        self.geometry("1280x840")
        self.minsize(1120, 700)
        self.configure(bg=C_BG)

        self.dirty = False
        self.busy = False
        self.q = queue.Queue()
        self.preview_img = None
        self.current_tab = 0

        self._style()
        self._build()
        self.reload_works()
        self.reload_profile()
        self.reload_accounts()
        self.refresh_status()
        self.log("就绪 · 抓取、刷新、推送的输出都会实时打在右侧这一栏", "dim")
        self.after(120, self._drain_queue)

    # ---------------- 样式 ----------------

    def author_name(self):
        """全站显示名：统一取个人信息里的名字（多个账号都是同一个人）。"""
        n = ((self.profile_data or {}).get("name") or "").strip()
        return n or "作者"

    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure(".", background=C_BG, foreground=C_FG,
                    font=("Microsoft YaHei UI", 9))
        s.configure("TFrame", background=C_BG)
        s.configure("TLabel", background=C_BG, foreground=C_FG)
        s.configure("Soft.TLabel", foreground=C_SOFT)
        s.configure("Title.TLabel", font=("Microsoft YaHei UI", 13, "bold"))
        s.configure("TNotebook", background=C_BG, borderwidth=0)
        s.configure("TNotebook.Tab", padding=(18, 8), font=("Microsoft YaHei UI", 10))
        s.map("TNotebook.Tab",
              background=[("selected", C_BG), ("!selected", "#f4f3f1")],
              foreground=[("selected", C_FG), ("!selected", C_SOFT)])
        s.configure("Treeview", rowheight=26, fieldbackground=C_BG,
                    background=C_BG, borderwidth=0)
        s.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"),
                    background="#faf9f7", relief="flat")
        s.map("Treeview", background=[("selected", "#eceae6")],
              foreground=[("selected", C_FG)])
        s.configure("TButton", padding=(12, 6))
        s.configure("Accent.TButton", padding=(16, 8),
                    font=("Microsoft YaHei UI", 9, "bold"))
        s.configure("TEntry", padding=4)

    # ---------------- 布局 ----------------

    def _build(self):
        # 注意 pack 顺序：底部组件先占位，否则中间 expand 的主体把它们挤出窗口
        st = tk.Frame(self, bg="#f4f3f1", height=30)
        st.pack(fill="x", side="bottom")
        st.pack_propagate(False)
        self.status = tk.Label(st, text="", bg="#f4f3f1", fg=C_SOFT,
                               anchor="w", padx=14, font=("Microsoft YaHei UI", 9))
        self.status.pack(side="left")
        self.busy_lbl = tk.Label(st, text="", bg="#f4f3f1", fg=C_WARN,
                                 anchor="e", padx=14, font=("Microsoft YaHei UI", 9))
        self.busy_lbl.pack(side="right")

        # 外壳：左主体 + 右日志两列（切得干净，谁也不挤谁）
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)

        # ---- 右列：运行日志，固定宽度、整列撑满 ----
        logf = ttk.Frame(outer, padding=(14, 10, 14, 12), width=380)
        logf.pack(side="right", fill="y")
        logf.pack_propagate(False)

        bar = ttk.Frame(logf)
        bar.pack(fill="x")
        ttk.Label(bar, text="运行日志", style="Soft.TLabel").pack(side="left")
        ttk.Button(bar, text="清空", width=6,
                   command=lambda: self.logbox.delete("1.0", "end")).pack(side="right")

        wrap = ttk.Frame(logf)
        wrap.pack(fill="both", expand=True, pady=(6, 0))
        self.logbox = tk.Text(wrap, height=20, width=42, bg="#f4f3f1", fg="#33302c",
                              relief="flat", font=("Consolas", 9),
                              wrap="word", padx=10, pady=8, bd=0,
                              highlightthickness=0)
        sb = ttk.Scrollbar(wrap, command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        self.logbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.logbox.tag_configure("ok", foreground=C_OK)
        self.logbox.tag_configure("warn", foreground=C_WARN)
        self.logbox.tag_configure("dim", foreground=C_SOFT)

        # ---- 左列：头部 + 标签页 ----
        left_col = ttk.Frame(outer)
        left_col.pack(side="left", fill="both", expand=True)

        head = ttk.Frame(left_col, padding=(18, 14, 18, 6))
        head.pack(fill="x")
        self.head_title = ttk.Label(head, text=f"{self.author_name()} 摄影站",
                                    style="Title.TLabel")
        self.head_title.pack(side="left")
        ttk.Label(head, text="  管理工具", style="Soft.TLabel").pack(side="left")
        link = ttk.Label(head, text=SITE_URL, foreground="#1a5dc8", cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda e: webbrowser.open(SITE_URL))

        self.nb = ttk.Notebook(left_col)
        self.nb.pack(fill="both", expand=True, padx=14, pady=(4, 4))
        self.tab_works = ttk.Frame(self.nb, padding=10)
        self.tab_acc = ttk.Frame(self.nb, padding=10)
        self.tab_me = ttk.Frame(self.nb, padding=10)
        self.nb.add(self.tab_works, text="作品同步")
        self.nb.add(self.tab_me, text="个人信息")
        self.nb.add(self.tab_acc, text="账号管理")
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab)

        self._build_works(self.tab_works)
        self._build_profile(self.tab_me)
        self._build_accounts(self.tab_acc)

    def _build_works(self, parent):
        # 底部按钮先占位，中间表格才能正确拿到剩余空间
        foot = ttk.Frame(parent)
        foot.pack(fill="x", side="bottom", pady=(10, 0))
        self.btn_save = ttk.Button(foot, text="保存修改", command=self.save_works)
        self.btn_save.pack(side="left")
        self.btn_push = ttk.Button(foot, text="推送更新", style="Accent.TButton",
                                   command=self.push)
        self.btn_push.pack(side="left", padx=(8, 0))
        self.dirty_lbl = ttk.Label(foot, text="", foreground=C_WARN)
        self.dirty_lbl.pack(side="left", padx=(12, 0))
        ttk.Label(foot, text="推送后约 1 分钟生效",
                  style="Soft.TLabel").pack(side="left", padx=(14, 0))
        self.btn_fetch = ttk.Button(foot, text="抓取新笔记", style="Accent.TButton",
                                    command=self.fetch_notes)
        self.btn_fetch.pack(side="right")
        self.btn_refresh = ttk.Button(foot, text="刷新笔记状态",
                                      command=self.refresh_notes)
        self.btn_refresh.pack(side="right", padx=(0, 8))

        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="全选", width=7,
                   command=lambda: self.set_all(True)).pack(side="left")
        ttk.Button(bar, text="全不选", width=8,
                   command=lambda: self.set_all(False)).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="刷新列表", width=9,
                   command=self.reload_works).pack(side="left", padx=(6, 0))
        self.only_off = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="只看已隐藏", variable=self.only_off,
                        command=self.reload_works).pack(side="left", padx=(14, 0))
        ttk.Label(bar, text="☑ 显示 / ☐ 隐藏", style="Soft.TLabel").pack(
            side="left", padx=(12, 0))

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)

        cols = ("sel", "date", "title", "cat", "imgs", "author")
        self.tree = ttk.Treeview(left, columns=cols, show="headings",
                                 selectmode="browse", height=12)
        for c, t, w, a, stretch in (
                ("sel", "显示", 54, "center", False),
                ("date", "日期", 132, "w", False),
                ("title", "标题", 280, "w", True),
                ("cat", "分类", 76, "w", False),
                ("imgs", "图片", 58, "center", False),
                ("author", "账号", 84, "w", False)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, minwidth=min(w, 240 if c == "title" else w),
                             anchor=a, stretch=stretch)
        sb = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ttk.Frame(body, width=226)
        right.pack(side="right", fill="y", padx=(14, 0))
        right.pack_propagate(False)
        self.pv = tk.Label(right, bg="#f4f3f1", text="选中一行看预览",
                           fg=C_SOFT, font=("Microsoft YaHei UI", 9))
        self.pv.pack(fill="both", expand=True)
        self.pv_title = ttk.Label(right, text="", wraplength=216, style="Soft.TLabel")
        self.pv_title.pack(fill="x", pady=(6, 0))

    # ---------------- 个人信息 ----------------

    def _build_profile(self, parent):
        foot = ttk.Frame(parent)
        foot.pack(fill="x", side="bottom", pady=(12, 0))
        ttk.Button(foot, text="保存", style="Accent.TButton",
                   command=self.save_profile).pack(side="left")
        ttk.Button(foot, text="从小红书同步简介",
                   command=self.sync_bio).pack(side="left", padx=(8, 0))
        ttk.Label(foot, text="改完点保存；推送在「作品同步」页",
                  style="Soft.TLabel").pack(side="right")

        box = ttk.Frame(parent)
        box.pack(fill="both", expand=True)

        ttk.Label(box, text="名字", style="Soft.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 4))
        self.var_name = tk.StringVar()
        ttk.Entry(box, textvariable=self.var_name, width=30).grid(
            row=1, column=0, sticky="w")
        ttk.Label(box, text="名字会显示在首屏大标题和左上角", style="Soft.TLabel").grid(
            row=1, column=1, sticky="w", padx=(12, 0))

        ttk.Label(box, text="小标题", style="Soft.TLabel").grid(
            row=2, column=0, sticky="w", pady=(14, 4))
        self.var_role = tk.StringVar()
        ttk.Entry(box, textvariable=self.var_role, width=30).grid(
            row=3, column=0, sticky="w")
        ttk.Label(box, text="例如 Photography · 摄影", style="Soft.TLabel").grid(
            row=3, column=1, sticky="w", padx=(12, 0))

        ttk.Label(box, text="个性签名", style="Soft.TLabel").grid(
            row=4, column=0, sticky="w", pady=(14, 4))
        wrapy = ttk.Frame(box)
        wrapy.grid(row=5, column=0, columnspan=2, sticky="w")
        self.txt_bio = tk.Text(wrapy, width=46, height=4, wrap="word",
                               bg="#faf9f7", fg="#33302c", relief="flat",
                               font=("Microsoft YaHei UI", 10), padx=10, pady=8)
        self.txt_bio.pack(side="left")
        ttk.Scrollbar(wrapy, command=self.txt_bio.yview).pack(side="left", fill="y")

        src = ttk.Frame(box)
        src.grid(row=6, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Label(src, text="签名来源", style="Soft.TLabel").pack(side="left")
        self.var_src = tk.StringVar(value="custom")
        ttk.Radiobutton(src, text="自定义（手动编辑上面这段）", value="custom",
                        variable=self.var_src).pack(side="left", padx=(12, 0))
        ttk.Radiobutton(src, text="同步小红书（每次同步用账号简介覆盖）",
                        value="xiaohongshu", variable=self.var_src).pack(
            side="left", padx=(12, 0))

        tip = ttk.Label(
            box,
            text="提示：留空则不显示签名（不会补任何默认文案）；换行会被保留，首屏按原样分行显示。"
                 "选「同步小红书」后每次抓取/同步都会用小红书上的简介替换这里的内容。",
            style="Soft.TLabel", wraplength=720, justify="left")
        tip.grid(row=7, column=0, columnspan=2, sticky="w", pady=(14, 0))

        ttk.Label(box, text="头像与二维码", style="Soft.TLabel").grid(
            row=8, column=0, sticky="w", pady=(18, 4))
        self.lbl_assets = ttk.Label(box, text="", style="Soft.TLabel",
                                    wraplength=720, justify="left")
        self.lbl_assets.grid(row=9, column=0, columnspan=2, sticky="w")

    def reload_profile(self):
        p = self.profile_data or {}
        self.var_name.set(p.get("name", ""))
        self.var_role.set(p.get("role", ""))
        self.var_src.set(p.get("bio_source", "custom"))
        self.txt_bio.delete("1.0", "end")
        self.txt_bio.insert("1.0", p.get("bio", ""))
        links = "、".join(l.get("label", "") for l in p.get("links", []))
        self.lbl_assets.configure(
            text=f"头像：{p.get('avatar', '（未设置）')}    二维码：{links or '（未设置）'}\n"
                 f"图片在 assets/img/，换图直接覆盖同名文件即可")

    def save_profile(self):
        bio = self.txt_bio.get("1.0", "end").rstrip()
        data = dict(self.profile_data or {})
        data["name"] = self.var_name.get().strip() or "翎溯"
        data["role"] = self.var_role.get().strip()
        data["bio"] = bio
        data["bio_source"] = self.var_src.get()
        try:
            save_json(PROFILE_JSON, data)
            self.profile_data = data
            # 名字是全站唯一作者名，改完同步到标题栏与账号表
            self.head_title.configure(text=f"{self.author_name()} 摄影站")
            self.title(f"{self.author_name()} · 管理工具")
            self.unify_account_names()
            self.reload_accounts()
            self.log("✓ profile.json 已保存（记得去「作品同步」页推送）", "ok")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def sync_bio(self):
        accs = [a for a in self.accounts_data.get("accounts", [])
                if a.get("enabled", True) and a.get("user_id")]
        if not accs:
            messagebox.showwarning("没有可用账号",
                                   "先去「账号管理」添加并登录账号。")
            return
        if self.var_src.get() != "xiaohongshu":
            if not messagebox.askyesno(
                    "改用小红书简介？",
                    "当前签名来源是「自定义」，同步会被跳过。\n"
                    "要改成「同步小红书」并立即拉取吗？"):
                return
            self.var_src.set("xiaohongshu")
            self.save_profile()

        script = os.path.join(ROOT, "scripts", "sync_profile.py")
        self.set_busy("同步简介…")
        self.log(f"→ 读取 {accs[0]['name']} 的小红书简介", "warn")
        self.run_cmd([python_exe(), script, "--account", accs[0]["key"]],
                     "同步简介", on_done=self._after_sync_bio)

    def _after_sync_bio(self, ok):
        self.profile_data = load_json(PROFILE_JSON, {})
        self.reload_profile()
        if ok:
            self.log("✓ 签名已更新", "ok")

    def _build_accounts(self, parent):
        tip = ttk.Label(
            parent,
            text="添加账号后会自动弹出浏览器扫码登录。账号信息与登录态只存在本机，不会进仓库。",
            style="Soft.TLabel")
        tip.pack(fill="x", side="bottom", pady=(8, 0))

        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="添加账号", command=self.add_account).pack(side="left")
        ttk.Button(bar, text="登录 / 重新登录",
                   command=self.login_account).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="启用 / 停用",
                   command=self.toggle_account).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="清除登录态",
                   command=self.reset_login).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="移除账号", command=self.remove_account).pack(side="left", padx=(6, 0))
        ttk.Label(bar, text="每个账号独立登录态，互不影响",
                  style="Soft.TLabel").pack(side="left", padx=(14, 0))

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        cols = ("key", "name", "uid", "state")
        self.acc_tree = ttk.Treeview(body, columns=cols, show="headings",
                                     selectmode="browse", height=10)
        for c, t, w, a, stretch in (("key", "标识", 110, "w", False),
                                    ("name", "显示名", 180, "w", False),
                                    ("uid", "小红书 ID", 250, "w", False),
                                    ("state", "状态", 90, "w", True)):
            self.acc_tree.heading(c, text=t)
            self.acc_tree.column(c, width=w, minwidth=w, anchor=a, stretch=stretch)
        sb = ttk.Scrollbar(body, command=self.acc_tree.yview)
        self.acc_tree.configure(yscrollcommand=sb.set)
        self.acc_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ---------------- 通用 ----------------

    def log(self, text, tag=None):
        self.logbox.insert("end", text + "\n", tag or ())
        self.logbox.see("end")

    def refresh_status(self):
        works = self.works_data.get("works", [])
        shown = sum(1 for w in works if not w.get("hidden"))
        hidden = len(works) - shown
        accs = self.accounts_data.get("accounts", [])
        on = sum(1 for a in accs if a.get("enabled", True))
        self.status.configure(
            text=f"作品 {len(works)} 个 · 显示 {shown} · 隐藏 {hidden}    |    "
                 f"账号 {on}/{len(accs)} 启用")
        self.dirty_lbl.configure(text="● 有未保存的修改" if self.dirty else "")

    def _on_tab(self, e=None):
        self.current_tab = self.nb.index("current")

    def set_busy(self, text=""):
        self.busy = bool(text)
        self.busy_lbl.configure(text=("⏳ " + text) if text else "")
        state = "disabled" if self.busy else "normal"
        for name in ("btn_save", "btn_push", "btn_refresh", "btn_fetch"):
            b = getattr(self, name, None)
            if b is not None:
                b.configure(state=state)
        self.update_idletasks()

    # ---------------- 作品 ----------------

    def reload_works(self):
        self.works_data = load_json(WORKS_JSON, {"works": [], "categories": []})
        cats = {c["key"]: c["name"] for c in self.works_data.get("categories", [])}
        self.tree.delete(*self.tree.get_children())
        only_off = self.only_off.get()

        works = sorted(self.works_data.get("works", []),
                       key=lambda w: w.get("date") or "", reverse=True)
        for w in works:
            if only_off and not w.get("hidden"):
                continue
            sel = "☐" if w.get("hidden") else "☑"
            self.tree.insert(
                "", "end", iid=w["id"],
                values=(sel, w.get("date", ""), w.get("title", ""),
                        cats.get(w.get("category"), w.get("category", "")),
                        len(w.get("images", [])), w.get("author", "")))
        self.refresh_status()

    def _on_tree_click(self, e):
        col = self.tree.identify_column(e.x)
        row = self.tree.identify_row(e.y)
        if not row:
            return
        if col in ("#1", "#2", "#3"):
            self.toggle_work(row)

    def toggle_work(self, iid):
        for w in self.works_data.get("works", []):
            if w["id"] == iid:
                w["hidden"] = not w.get("hidden", False)
                self.dirty = True
                self.tree.set(iid, "sel", "☐" if w["hidden"] else "☑")
                if self.only_off.get() and not w["hidden"]:
                    self.tree.delete(iid)
                break
        self.refresh_status()

    def set_all(self, visible):
        for iid in self.tree.get_children():
            for w in self.works_data.get("works", []):
                if w["id"] == iid:
                    w["hidden"] = not visible
                    break
            self.tree.set(iid, "sel", "☑" if visible else "☐")
        self.dirty = True
        if self.only_off.get() and visible:
            self.reload_works()
        self.refresh_status()

    def _on_select(self, e=None):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        w = next((x for x in self.works_data.get("works", []) if x["id"] == iid), None)
        if not w:
            return
        self.pv_title.configure(text=f"{w.get('title', '')}\n{w.get('date', '')} · "
                                     f"{len(w.get('images', []))} 张")
        if not HAS_PIL:
            return
        thumb = w.get("thumb") or (w["images"][0]["thumb"] if w.get("images") else "")
        path = os.path.join(ROOT, thumb.replace("/", os.sep)) if thumb else ""
        if not path or not os.path.exists(path):
            self.pv.configure(image="", text="（无预览）")
            return
        try:
            im = Image.open(path)
            im.thumbnail((216, 260))
            self.preview_img = ImageTk.PhotoImage(im)
            self.pv.configure(image=self.preview_img, text="")
        except Exception:
            self.pv.configure(image="", text="（预览加载失败）")

    def save_works(self, silent=False):
        try:
            save_json(WORKS_JSON, self.works_data)
            self.dirty = False
            self.refresh_status()
            if not silent:
                self.log("✓ works.json 已保存", "ok")
            return True
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            return False

    # ---------------- 账号 ----------------

    def reload_accounts(self):
        self.accounts_data = load_json(ACCOUNTS_JSON, {"accounts": []})
        self.unify_account_names()
        self.acc_tree.delete(*self.acc_tree.get_children())
        for a in self.accounts_data.get("accounts", []):
            self.acc_tree.insert(
                "", "end", iid=a["key"],
                values=(a.get("key", ""), self.author_name(),
                        a.get("user_id", "") or "（未登录）",
                        "启用" if a.get("enabled", True) else "已停用"))
        self.refresh_status()

    def unify_account_names(self):
        """几个账号都是同一个人的，显示名统一用「个人信息」里的名字，不再逐个命名。"""
        want = self.author_name()
        changed = False
        for a in self.accounts_data.get("accounts", []):
            if a.get("name") != want:
                a["name"] = want
                changed = True
        if changed:
            try:
                save_json(ACCOUNTS_JSON, self.accounts_data)
            except Exception:
                pass
        return changed

    def _sel_account(self):
        s = self.acc_tree.selection()
        if not s:
            messagebox.showinfo("提示", "请先在列表里选中一个账号")
            return None
        return s[0]

    def add_account(self):
        key = simpledialog.askstring("添加账号", "账号标识（英文，用作文件夹名）：", parent=self)
        if not key:
            return
        key = key.strip().lower().replace(" ", "_")
        if not key.replace("_", "").isalnum():
            messagebox.showerror("格式不对", "只能用英文字母、数字和下划线")
            return
        if any(a.get("key") == key for a in self.accounts_data.get("accounts", [])):
            messagebox.showerror("已存在", f"账号 {key} 已经加过了")
            return
        # 多个账号都是同一个人的，显示名统一用个人信息里的名字，不再单独询问
        self.accounts_data.setdefault("accounts", []).append(
            {"key": key, "name": self.author_name(), "user_id": "", "enabled": True})
        save_json(ACCOUNTS_JSON, self.accounts_data)
        self.reload_accounts()
        self.log(f"已添加账号 {key}，接下来会自动打开浏览器让你扫码", "ok")
        self.after(300, lambda: self.login_account(key))

    def login_account(self, key=None):
        key = key or self._sel_account()
        if not key:
            return
        self.set_busy(f"等待 {key} 扫码登录…")
        self.log(f"→ 打开浏览器，请用小红书 App 扫码登录 [{key}]", "warn")
        script = os.path.join(ROOT, "scripts", "xhs_login.py")
        self.run_cmd([python_exe(), script, "--account", key], "登录",
                     on_done=lambda ok: self._after_login(ok, key))

    def _after_login(self, ok, key):
        self.reload_accounts()
        if ok:
            self.log(f"✓ 账号 {key} 登录成功", "ok")
        else:
            self.log(f"✗ 账号 {key} 登录未完成（超时或取消）", "warn")

    def toggle_account(self):
        key = self._sel_account()
        if not key:
            return
        for a in self.accounts_data.get("accounts", []):
            if a["key"] == key:
                a["enabled"] = not a.get("enabled", True)
                break
        save_json(ACCOUNTS_JSON, self.accounts_data)
        self.reload_accounts()

    def reset_login(self):
        """删掉该账号的本机登录态，下次登录会重新出二维码（用于换号）。"""
        key = self._sel_account()
        if not key:
            return
        if not messagebox.askyesno(
                "清除登录态",
                f"将删除账号 {key} 在本机保存的登录态（浏览器数据），\n"
                f"已导入的作品不受影响。\n\n之后点「登录 / 重新登录」会重新出二维码。继续？"):
            return
        prof = os.path.join(PROFILES, key)
        import shutil
        shutil.rmtree(prof, ignore_errors=True)
        for a in self.accounts_data.get("accounts", []):
            if a.get("key") == key:
                a["user_id"] = ""
                break
        save_json(ACCOUNTS_JSON, self.accounts_data)
        self.reload_accounts()
        self.log(f"已清除 {key} 的登录态，现在可以重新登录（换号）", "ok")

    def remove_account(self):
        key = self._sel_account()
        if not key:
            return
        if not messagebox.askyesno("移除账号", f"确定移除账号 {key}？\n（不会删除已导入的作品）"):
            return
        self.accounts_data["accounts"] = [
            a for a in self.accounts_data.get("accounts", []) if a.get("key") != key]
        save_json(ACCOUNTS_JSON, self.accounts_data)
        prof = os.path.join(PROFILES, key)
        if os.path.isdir(prof) and messagebox.askyesno(
                "删除登录态", f"同时删除 {key} 的本机登录态目录？\n{prof}"):
            import shutil
            shutil.rmtree(prof, ignore_errors=True)
            self.log(f"已删除登录态 {prof}", "dim")
        self.reload_accounts()

    # ---------------- 抓取 ----------------

    def fetch_notes(self):
        accs = [a for a in self.accounts_data.get("accounts", [])
                if a.get("enabled", True) and a.get("user_id")]
        if not accs:
            messagebox.showwarning(
                "没有可用账号",
                "先去「账号管理」添加并登录账号，再抓取。")
            return
        if self.dirty and not self.save_works(silent=True):
            return

        names = "\n".join(f"  · {a['name']}（{a['key']}）" for a in accs)
        if not messagebox.askyesno(
                "抓取新笔记",
                f"将同步以下账号的公开笔记：\n{names}\n\n"
                f"已有的作品不会被覆盖，只会追加新笔记。继续？"):
            return

        self.set_busy("抓取中…")
        self.log("→ 开始抓取（只抓公开笔记，私密与视频会自动跳过）", "warn")
        script = os.path.join(ROOT, "scripts", "xhs_fetch.py")
        self.run_cmd([python_exe(), script], "抓取",
                     on_done=self._after_fetch)

    def _after_fetch(self, ok):
        self.reload_works()
        if ok:
            self.log("✓ 抓取完成，列表已刷新", "ok")
        else:
            self.log("✗ 抓取中断，详情见上方日志", "warn")

    def refresh_notes(self):
        """只更新已有笔记编辑后的内容（标题/正文/图片/标签），
        发布日期永远保持首次发布时那一天，分类与显示状态也不动。"""
        accs = [a for a in self.accounts_data.get("accounts", [])
                if a.get("enabled", True) and a.get("user_id")]
        if not accs:
            messagebox.showwarning(
                "没有可用账号",
                "先去「账号管理」添加并登录账号，再刷新。")
            return
        if self.dirty and not self.save_works(silent=True):
            return

        names = "\n".join(f"  · {a['key']}" for a in accs)
        if not messagebox.askyesno(
                "刷新笔记状态",
                f"会重新打开每一条已导入的笔记，用最新内容更新：\n"
                f"  标题 / 正文 / 图片 / 标签\n\n"
                f"保持不变：\n"
                f"  · 发布日期（始终是首次发布那天）\n"
                f"  · 分类、显示或隐藏状态\n\n"
                f"账号：\n{names}\n\n继续？"):
            return

        self.set_busy("刷新笔记状态…")
        self.log("→ 开始刷新已有笔记（内容更新，日期不动）", "warn")
        script = os.path.join(ROOT, "scripts", "xhs_fetch.py")
        self.run_cmd([python_exe(), script, "--refresh"], "刷新笔记状态",
                     on_done=self._after_refresh)

    def _after_refresh(self, ok):
        self.reload_works()
        if ok:
            self.log("✓ 刷新完成：内容已更新，发布日期保持不变", "ok")
            self.log("   改完记得点「推送更新」让线上生效", "dim")
        else:
            self.log("✗ 刷新中断，详情见上方日志", "warn")

    # ---------------- 推送 ----------------

    def push(self):
        if self.dirty and not self.save_works(silent=True):
            return
        try:
            st = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace")
            changed = [l for l in st.stdout.splitlines() if l.strip()]
        except Exception as e:
            messagebox.showerror("git 不可用", str(e))
            return
        if not changed:
            messagebox.showinfo("没有改动", "本地没有需要推送的修改。")
            return

        works = self.works_data.get("works", [])
        shown = sum(1 for w in works if not w.get("hidden"))
        default_msg = f"更新作品：显示 {shown}/{len(works)} 组"
        msg = simpledialog.askstring("推送", f"改动 {len(changed)} 个文件，提交说明：",
                                     initialvalue=default_msg, parent=self)
        if msg is None:
            return

        self.set_busy("推送中…")
        self.log(f"→ 推送 {len(changed)} 个文件", "warn")
        cmd = ("git add -A && git -c core.quotepath=false commit -m \"%s\" && git push"
               % (msg or "更新").replace('"', "'"))
        self.run_cmd(cmd, "推送", shell=True, on_done=self._after_push)

    def _after_push(self, ok):
        if ok:
            self.log(f"✓ 已推送，约 1 分钟后生效：{SITE_URL}", "ok")
            if messagebox.askyesno("推送成功", "已推送到 GitHub。\n现在打开线上站点看看？"):
                webbrowser.open(SITE_URL)
        else:
            self.log("✗ 推送失败，检查网络或 SSH 配置", "warn")

    # ---------------- 子进程 ----------------

    def run_cmd(self, cmd, title, shell=False, on_done=None):
        def worker():
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"
            env.pop("http_proxy", None)
            env.pop("https_proxy", None)
            try:
                p = subprocess.Popen(
                    cmd, cwd=ROOT, shell=shell, env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW)
                for line in p.stdout:
                    self.q.put(("log", line.rstrip()))
                p.wait()
                self.q.put(("done", p.returncode == 0, title, on_done))
            except Exception as e:
                self.q.put(("log", f"启动失败：{e}"))
                self.q.put(("done", False, title, on_done))

        threading.Thread(target=worker, daemon=True).start()

    def _drain_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "log":
                    line = item[1]
                    if not line.strip():
                        continue
                    tag = ("ok" if line.startswith("✓") or "成功" in line
                           else "warn" if ("✗" in line or "失败" in line or "跳过" in line)
                           else "dim" if line.startswith("  等待") else None)
                    self.log(line, tag)
                elif item[0] == "done":
                    _, ok, title, cb = item
                    self.set_busy("")
                    self.log(("✓ " if ok else "✗ ") + f"{title}结束", "ok" if ok else "warn")
                    if cb:
                        try:
                            cb(ok)
                        except TypeError:
                            cb()
        except queue.Empty:
            pass
        self.after(150, self._drain_queue)

    def on_close(self):
        if self.dirty and messagebox.askyesno(
                "有未保存的修改", "作品显示状态还没保存，要退出吗？"):
            self.destroy()
        elif not self.dirty:
            self.destroy()


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
