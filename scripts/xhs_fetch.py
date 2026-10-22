"""抓取本人小红书公开笔记 → 本地图片 + data/works.json。

两阶段设计（可断点续跑）：
  阶段1  元数据：逐条打开笔记详情，每成功一条立刻写 data/raw/notes.json
  阶段2  图片：只走 HTTP 下载 + 转码，不再依赖浏览器

用法：
  python scripts/xhs_fetch.py                # 抓元数据 + 下载图片
  python scripts/xhs_fetch.py --meta-only    # 只抓元数据
  python scripts/xhs_fetch.py --images-only  # 只下载图片（复用 notes.json）
  python scripts/xhs_fetch.py --limit 5
"""
import json
import os
import re
import sys
import time

from PIL import Image
from playwright.sync_api import sync_playwright

from xhs_common import DATA, ROOT, launch

RAW_DIR = os.path.join(DATA, "raw")
NOTES_JSON = os.path.join(RAW_DIR, "notes.json")
ACCOUNT = os.path.join(DATA, "account.json")
WORKS_JSON = os.path.join(ROOT, "data", "works.json")
IMG_ROOT = os.path.join(ROOT, "images", "works")

FULL_MAX = 1600
THUMB_W = 720
TMP_IMG = os.path.join(RAW_DIR, "_tmp.img")


# ---------------- 文本工具 ----------------

def slugify(title, date, idx):
    base = f"{date}-{idx:02d}"
    t = re.sub(r"[^\w\u4e00-\u9fa5]+", "-", (title or "").strip())[:22].strip("-")
    return f"{base}-{t}" if t else base


def clean_desc(desc):
    d = (desc or "").replace("\r\n", "\n").strip()
    lines = [ln.strip() for ln in d.split("\n") if ln.strip()]
    return "\n".join(lines)


def first_line(desc):
    for ln in clean_desc(desc).split("\n"):
        t = re.sub(r"#\S+", "", ln).strip()
        if t:
            return t[:24]
    return ""


EMOJI_RE = re.compile(r"\[[^\[\]]{1,10}R\]")          # 小红书表情占位，如 [哭惹R][色色R]
TOPIC_RE = re.compile(r"#([^#\[\]]{1,24})\[话题\]#")   # #xxx[话题]# → #xxx


def clean_text(s):
    s = s or ""
    s = EMOJI_RE.sub("", s)
    s = TOPIC_RE.sub(r"#\1", s)
    s = re.sub(r"\[[^\[\]]*$", "", s)   # 标题被页面截断时残留的半个表情标记
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


# 初始分类规则：只用于首次导入生成可用分类，之后直接改 works.json 的 category 即可
CLASSIFY_RULES = [
    ("pets", "萌宠", ["猫", "狸花", "猫条", "猫学", "修狗", "狗", "螳螂"]),
    ("campus", "校园", ["录取", "学校", "大学", "宿舍", "体校", "上课", "课", "老师"]),
    ("city", "城市", ["南昌", "福州", "泉州", "赣州", "滕王阁", "寻乌", "晚霞", "街", "塔"]),
    ("landscape", "风景", ["晚霞", "日落", "海", "山", "云", "光"]),
]


def classify(title, desc):
    txt = (title or "") + " " + (desc or "")
    for key, _name, kws in CLASSIFY_RULES:
        for k in kws:
            if k in txt:
                return key
    return "other"


def extract_tags(desc, title):
    txt = (title or "") + " " + (desc or "")
    tags = re.findall(r"#([^#\[\]\s]{1,20})(?:\[话题\])?#", txt)
    out = []
    for t in tags:
        t = t.strip()
        if t and t not in out:
            out.append(t)
    return out[:8]


def parse_time(ms):
    try:
        ts = int(ms)
        if ts > 1e12:
            ts //= 1000
        return time.strftime("%Y-%m-%d", time.localtime(ts))
    except Exception:
        return ""


def load_notes():
    if not os.path.exists(NOTES_JSON):
        return []
    try:
        with open(NOTES_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_notes(notes):
    os.makedirs(RAW_DIR, exist_ok=True)
    tmp = NOTES_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)
    os.replace(tmp, NOTES_JSON)


# ---------------- 页面脚本 ----------------

SCROLL_JS = """
() => {
  const box = document.querySelector('.feeds-page') || document.querySelector('#userPostedFeeds')
              || document.querySelector('.note-list');
  if (box) box.scrollTop = box.scrollHeight;
  window.scrollTo(0, document.body.scrollHeight);
  return document.querySelectorAll('section.note-item, .note-item').length;
}
"""

COLLECT_JS = """
() => {
  const out = [];
  const seen = new Set();
  const NOTE_RE = /\\/user\\/profile\\/[0-9a-f]+\\/([0-9a-f]{16,})/;
  const EXPLORE_RE = /\\/explore\\/([0-9a-f]{16,})/;
  document.querySelectorAll('section.note-item, .note-item').forEach(sec => {
    const links = [...sec.querySelectorAll('a[href]')];
    // 必须优先取带 xsec_token 的站内链接，裸 /explore/<id> 会 404
    let a = links.find(x => {
      const h = x.getAttribute('href') || '';
      return NOTE_RE.test(h) && h.indexOf('xsec_token') > -1;
    });
    if (!a) a = links.find(x => NOTE_RE.test(x.getAttribute('href') || ''));
    if (!a) a = links.find(x => EXPLORE_RE.test(x.getAttribute('href') || ''));
    if (!a) return;

    const href = a.getAttribute('href') || '';
    const m = href.match(NOTE_RE) || href.match(EXPLORE_RE);
    if (!m) return;
    const id = m[1];
    if (seen.has(id)) return;
    seen.add(id);

    const img = sec.querySelector('img');
    const txt = (sec.innerText || '').replace(/\\s+/g, ' ').trim();
    out.push({
      id: id,
      href: href.startsWith('http') ? href : ('https://www.xiaohongshu.com' + href),
      cover: img ? (img.currentSrc || img.src) : '',
      title: txt.split('\\n')[0].trim(),
      isVideo: !!sec.querySelector('.play-icon, .video-icon, [class*="play-icon"]'),
      // 私密笔记卡片文本以「仅自己可见」开头（该标识不是独立元素，只能靠文本判断）
      isPrivate: txt.indexOf('仅自己可见') === 0,
    });
  });
  return out;
}
"""

DETAIL_JS = """
(id) => {
  const out = {got: false};
  const st = window.__INITIAL_STATE__;
  try {
    const map = st && st.note && st.note.noteDetailMap;
    if (map) {
      const key = Object.keys(map).find(k => k === id) || Object.keys(map)[0];
      const d = map[key];
      const n = d && d.note;
      if (n) {
        out.got = true;
        out.title = String(n.title || '');
        out.desc = String(n.desc || '');
        out.time = n.time || 0;
        out.type = String(n.type || '');
        out.userId = n.user ? String(n.user.userId || n.user.user_id || '') : '';
        out.nickname = n.user ? String(n.user.nickname || n.user.nickName || '') : '';
        out.images = (n.imageList || []).map(im => ({
          url: String(im.urlDefault || im.urlPre || im.url || ''),
          w: Number(im.width) || 0,
          h: Number(im.height) || 0,
        })).filter(x => x.url);
        out.tags = (n.tagList || []).map(t => String(t.name || '')).filter(Boolean);
      }
    }
  } catch (e) { out.err = String(e).slice(0, 120); }

  if (!out.title) {
    const t = document.querySelector('#detail-title, .note-content .title');
    if (t) out.title = t.innerText.trim();
  }
  if (!out.desc) {
    const d = document.querySelector('#detail-desc, .note-content .desc');
    if (d) out.desc = d.innerText.trim();
  }
  if (!out.images || !out.images.length) {
    const seen = [];
    document.querySelectorAll('.swiper-slide img, .media-container img').forEach(i => {
      const u = i.currentSrc || i.src;
      if (u && u.indexOf('data:') !== 0 && seen.indexOf(u) < 0) seen.push(u);
    });
    out.images = seen.map(u => ({url: u, w: 0, h: 0}));
  }
  // 二次校验：详情页出现「仅自己可见」= 私密笔记
  try {
    out.private = (document.body.innerText || '').slice(0, 3000).indexOf('仅自己可见') > -1;
  } catch (e) { out.private = false; }
  return out;
}
"""

DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def scrape(page, uid, limit=None, force=False):
    url = f"https://www.xiaohongshu.com/user/profile/{uid}"
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    if "login" in page.url:
        print("!! 未登录，无法访问个人主页", flush=True)
        return load_notes()

    # 边滚边累积：虚拟列表会回收节点，只取最后一屏会漏
    found = {}
    last_cnt, stable = 0, 0
    for _ in range(150):
        for it in page.evaluate(COLLECT_JS):
            found.setdefault(it["id"], it)
        cnt = page.evaluate(SCROLL_JS)
        if limit and len(found) >= limit:
            break
        if cnt == last_cnt:
            stable += 1
            page.wait_for_timeout(2200)
            if stable >= 4:
                break
        else:
            stable, last_cnt = 0, cnt
            page.wait_for_timeout(1200)

    items = list(found.values())
    n_priv = sum(1 for x in items if x.get("isPrivate"))
    print(f"主页共发现 {len(items)} 条笔记（其中疑似私密 {n_priv} 条）", flush=True)
    if limit:
        items = items[:limit]

    notes = [] if force else load_notes()
    done = {n["id"] for n in notes}
    for i, it in enumerate(items):
        if it["id"] in done:
            continue
        print(f"  [{i + 1}/{len(items)}] {it['id']} ...", end=" ", flush=True)
        try:
            page.goto(it["href"], wait_until="domcontentloaded")
            page.wait_for_timeout(1900)
            d = page.evaluate(DETAIL_JS, it["id"])
        except Exception as e:
            print("打开失败:", str(e)[:90], flush=True)
            continue

        if d.get("private") or it.get("isPrivate"):
            print("跳过（仅自己可见）", flush=True)
            continue

        if d.get("userId") and d["userId"] != uid:
            print("跳过（非本人）", flush=True)
            continue

        if (d.get("type") or "").lower() == "video":
            print("跳过（视频）", flush=True)
            continue

        imgs = d.get("images") or []
        if not imgs:
            print("跳过（无图）", flush=True)
            continue

        date = parse_time(d.get("time"))
        if not date:
            try:
                m = DATE_RE.search(page.inner_text("body")[:4000])
                date = m.group(0) if m else time.strftime("%Y-%m-%d")
            except Exception:
                date = time.strftime("%Y-%m-%d")

        note = {
            "id": it["id"],
            "title": (d.get("title") or "").strip() or first_line(d.get("desc")) or "无题",
            "desc": clean_desc(d.get("desc")),
            "date": date,
            "images": imgs,
            "tags": d.get("tags") or extract_tags(d.get("desc"), d.get("title")),
            "url": it["href"].split("?")[0],
        }
        notes.append(note)
        save_notes(notes)          # 增量落盘，崩溃不丢进度
        print(f"{len(imgs)} 图 · {date} · {note['title'][:16]}", flush=True)

    return notes


# ---------------- 下载与转码 ----------------

def download(url, dest, retries=3):
    import urllib.error
    import urllib.request

    headers = {
        "Referer": "https://www.xiaohongshu.com/",
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0"),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=35) as r:
                body = r.read()
            if len(body) < 2048:
                raise ValueError("too small")
            with open(dest, "wb") as f:
                f.write(body)
            return True
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                print(f"HTTP {e.code} ", end="", flush=True)
                return False
            time.sleep(1.0 * (attempt + 1))
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return False


def process(raw_path, full_path, thumb_path):
    with Image.open(raw_path) as im:
        im = im.convert("RGB")
        w, h = im.size

        full = im
        if max(w, h) > FULL_MAX:
            k = FULL_MAX / max(w, h)
            full = im.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
        full.save(full_path, "WEBP", quality=86, method=4)

        tw = min(THUMB_W, w)
        th = max(1, int(h * tw / w))
        im.resize((tw, th), Image.LANCZOS).save(thumb_path, "WEBP", quality=76, method=4)
        return full.size


def build_images(note, slug):
    out_dir = os.path.join(IMG_ROOT, slug)
    os.makedirs(out_dir, exist_ok=True)

    result = []
    for i, im in enumerate(note["images"], 1):
        src = im["url"].replace("http://", "https://")
        name = f"{i:02d}"
        full_p = os.path.join(out_dir, name + ".webp")
        thumb_p = os.path.join(out_dir, name + "_t.webp")

        if os.path.exists(full_p) and os.path.exists(thumb_p):
            try:
                with Image.open(full_p) as ex:
                    result.append({"src": f"images/works/{slug}/{name}.webp",
                                   "thumb": f"images/works/{slug}/{name}_t.webp",
                                   "w": ex.size[0], "h": ex.size[1]})
                continue
            except Exception:
                pass

        if not download(src, TMP_IMG):
            print(f"图{i}失败 ", end="", flush=True)
            continue
        try:
            fw, fh = process(TMP_IMG, full_p, thumb_p)
        except Exception as e:
            print(f"图{i}转码失败 ", end="", flush=True)
            continue
        result.append({"src": f"images/works/{slug}/{name}.webp",
                       "thumb": f"images/works/{slug}/{name}_t.webp",
                       "w": fw, "h": fh})

    if os.path.exists(TMP_IMG):
        try:
            os.remove(TMP_IMG)
        except OSError:
            pass
    return result


def build_works(notes):
    cat_names = {"pets": "萌宠", "campus": "校园", "city": "城市",
                 "landscape": "风景", "other": "其他"}
    works = []
    for i, n in enumerate(notes):
        title = clean_text(n["title"]) or "无题"
        caption = clean_text(n["desc"])
        slug = slugify(title, n["date"], i + 1)
        print(f"下载 {slug} ...", end=" ", flush=True)
        imgs = build_images(n, slug)
        if not imgs:
            print("无可用图片，跳过", flush=True)
            continue
        print(f"{len(imgs)} 张", flush=True)
        ck = classify(title, caption)
        works.append({
            "id": n["id"],
            "slug": slug,
            "title": title,
            "caption": caption,
            "date": n["date"],
            "year": n["date"][:4] if n["date"] else "",
            "tags": n["tags"],
            "category": ck,
            "source": n["url"],
            "thumb": imgs[0]["thumb"],
            "images": imgs,
        })

    order = ["pets", "campus", "city", "landscape", "other"]
    used = {w["category"] for w in works}
    data = {
        "site": {"title": "Reeve", "subtitle": "记录光与日常。"},
        "categories": [{"key": k, "name": cat_names[k]} for k in order if k in used],
        "works": works,
    }
    tmp = WORKS_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, WORKS_JSON)
    print(f"\n站点数据已生成：{WORKS_JSON}（{len(works)} 个作品）", flush=True)
    return data


# ---------------- 主流程 ----------------

def main():
    limit = None
    for i, a in enumerate(sys.argv):
        if a == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])
    meta_only = "--meta-only" in sys.argv
    images_only = "--images-only" in sys.argv
    force = "--force" in sys.argv

    if not os.path.exists(ACCOUNT):
        print("缺少 data/account.json", flush=True)
        sys.exit(1)
    with open(ACCOUNT, encoding="utf-8") as f:
        uid = json.load(f)["user_id"]

    notes = load_notes()

    if not images_only:
        pw, ctx = launch(headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            notes = scrape(page, uid, limit, force=force)
            print(f"\n元数据：{len(notes)} 条", flush=True)
        finally:
            try:
                ctx.close()
                pw.stop()
            except Exception:
                pass

    if not meta_only:
        build_works(notes)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
