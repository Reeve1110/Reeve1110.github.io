"""发布前门禁：确认对外文件里没有任何账号敏感信息。

检查对象 = 真正会被 GitHub Pages 公开的文件（index.html / assets / data 白名单 / README）。
规则：
  1. 手机号、身份证号、邮箱、11 位以上连续数字（抖音号、订单号等）
  2. JSON 里出现 password / token / cookie / phone 之类的字段名
  3. data/ 下被 git 跟踪的只能有 works.json、profile.json 与 ai.example.json（模板，key 为空）
  4. assets/img 里的图片不得带 EXIF / GPS

用法：
  python scripts/guard_public.py        # 发现问题退出码 1
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

PUBLIC_FILES = [
    "index.html",
    "assets/js/app.js",
    "assets/css/style.css",
    "data/works.json",
    "data/profile.json",
    "data/ai.example.json",
    "README.md",
    "robots.txt",
    "sitemap.xml",
]

PUBLIC_DATA = ("works.json", "profile.json", "ai.example.json")

RULES = [
    ("手机号", r"(?<![0-9A-Za-z])1[3-9]\d{9}(?![0-9A-Za-z])"),
    ("身份证号", r"(?<![0-9A-Za-z])\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![0-9A-Za-z])"),
    ("连续 11 位以上数字（账号/订单号）", r"(?<![0-9A-Za-z])\d{11,}(?![0-9A-Za-z])"),
    ("邮箱", r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}"),
    ("敏感字段名", r'(?i)"(password|passwd|pwd|secret|token|cookie|session|phone|mobile|tel|idcard|id_card|realname|wechat|qq)"\s*:'),
]

ok = True


def fail(msg):
    global ok
    ok = False
    print("  ✗ " + msg)


def scan_text(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        fail(f"{rel} 不存在")
        return
    text = open(path, encoding="utf-8").read()
    hits = []
    for name, pat in RULES:
        for m in re.finditer(pat, text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append((name, line, m.group(0)[:40]))
    if hits:
        for name, line, val in hits[:8]:
            fail(f"{rel}:{line} 命中「{name}」→ {val}")
    else:
        print(f"  ✓ {rel}")


def check_tracked_data():
    try:
        out = subprocess.run(["git", "ls-files", "data"], cwd=ROOT, capture_output=True,
                             text=True, timeout=30).stdout
    except Exception as e:
        print(f"  ! 跳过 git 检查：{e}")
        return
    files = [l.strip() for l in out.splitlines() if l.strip()]
    bad = [f for f in files if os.path.basename(f) not in PUBLIC_DATA]
    if bad:
        fail("data/ 下不该被跟踪的文件：" + ", ".join(bad[:6]))
    else:
        print(f"  ✓ data/ 仅跟踪 {len(files)} 个公开文件")


def check_images():
    from PIL import Image
    d = os.path.join(ROOT, "assets", "img")
    if not os.path.isdir(d):
        fail("assets/img 不存在")
        return
    for name in sorted(os.listdir(d)):
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        p = os.path.join(d, name)
        im = Image.open(p)
        ex = im.getexif()
        gps = bool(ex.get(0x8825)) if ex else False
        if ex or gps:
            fail(f"assets/img/{name} 仍带 EXIF/GPS")
        else:
            print(f"  ✓ assets/img/{name} 无 EXIF")


def check_profile_shape():
    p = os.path.join(ROOT, "data", "profile.json")
    if not os.path.exists(p):
        return
    data = json.load(open(p, encoding="utf-8"))
    allowed_root = {"name", "role", "bio", "bio_source", "avatar", "links"}
    extra = set(data) - allowed_root
    if extra:
        fail(f"profile.json 含未知字段：{sorted(extra)}")
    for l in data.get("links", []):
        extra = set(l) - {"key", "label", "qr", "url"}
        if extra:
            fail(f"profile.json links 含未知字段：{sorted(extra)}")
        u = (l.get("url") or "").strip()
        if u and not re.match(r"^https?://", u, re.I):
            fail(f"profile.json 的 {l.get('key')} 链接不是 http(s)：{u[:40]}")
    print(f"  ✓ profile.json 字段收敛在 {sorted(allowed_root)}")


def check_ai_example():
    p = os.path.join(ROOT, "data", "ai.example.json")
    if not os.path.exists(p):
        return
    data = json.load(open(p, encoding="utf-8"))
    if (data.get("api_key") or "").strip():
        fail("ai.example.json 里的 api_key 必须留空")
    if ((data.get("custom") or {}).get("api_key") or "").strip():
        fail("ai.example.json 里 custom.api_key 必须留空")
    print("  ✓ ai.example.json 的 key 字段为空")


def main():
    print("检查对外文件是否泄露账号敏感信息：")
    for rel in PUBLIC_FILES:
        scan_text(rel)
    check_tracked_data()
    check_images()
    check_profile_shape()
    check_ai_example()
    print()
    if ok:
        print("结论：通过，可以发布。")
        sys.exit(0)
    print("结论：不通过 —— 先清理上面列出的内容再推送。")
    sys.exit(1)


if __name__ == "__main__":
    main()
