"""站点自测：桌面端 / 移动端逐项检查渲染、导航、图片、分类、详情。

用法：python scripts/test_site.py [--url http://127.0.0.1:8765/]
产出：data/shots/*.png + 控制台 PASS/FAIL 明细
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "data", "shots")
BASE = "http://127.0.0.1:8765/"

results = []


def site_author():
    """显示名以 data/profile.json 为准，改名字不用改测试。"""
    try:
        with open(os.path.join(ROOT, "data", "profile.json"), encoding="utf-8") as f:
            return (json.load(f).get("name") or "").strip()
    except Exception:
        return ""


AUTHOR = site_author()


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f"   [{detail}]" if detail else ""), flush=True)


def hero_checks(page, label):
    """首屏：满屏背景、身份信息、二维码、层级切换、敏感信息不落 DOM。"""
    box = page.evaluate(
        """() => {
        const r = document.getElementById('hero').getBoundingClientRect();
        return {w: Math.round(r.width), h: Math.round(r.height), vw: innerWidth, vh: innerHeight};
    }""")
    check(f"{label} 首屏占满视口",
          abs(box["h"] - box["vh"]) <= 2 and box["w"] >= box["vw"] - 1,
          f"hero {box['w']}x{box['h']} / vp {box['vw']}x{box['vh']}")

    bg = page.evaluate(
        """() => {
        const i = document.getElementById('heroImg');
        const w0 = (window.__site.works[0] || {});
        const im = (w0.images || [])[0] || {};
        return {nw: i.naturalWidth, src: i.getAttribute('src') || '',
                cover: getComputedStyle(i).objectFit, latest: im.src || ''};
    }""")
    check(f"{label} 背景是最新作品封面", bg["nw"] > 0 and bg["src"] == bg["latest"],
          (bg["src"] or "")[-46:])
    check(f"{label} 背景铺满不变形", bg["cover"] == "cover", bg["cover"])

    # 封面版本号：rev 变了图片 URL 就变，换封面时不会读到 CDN 旧图
    rev = page.evaluate(
        """() => {
        const w = window.__site.works[0] || {};
        const im = (w.images || [])[0] || {};
        return {rev: w.rev || '', src: im.src || '', thumb: w.thumb || ''};
    }""")
    tag = ("v=" + rev["rev"]) if rev["rev"] else ""
    check(f"{label} 封面带版本号（换封面可破缓存）",
          bool(tag) and tag in rev["src"] and tag in rev["thumb"],
          f"rev={rev['rev']} · {rev['src'][-22:]}")

    name = page.locator("#heroName").inner_text().strip()
    bio = page.locator("#heroBio").inner_text().strip()
    eyebrow = page.locator("#heroEyebrow").inner_text().strip()
    prof_bio = page.evaluate("() => ((window.__site.profile || {}).bio || '').trim()")
    prof_role = page.evaluate("() => ((window.__site.profile || {}).role || '').trim()")
    check(f"{label} 展示名字", name != "", name)
    # 小标题（副标题）与签名都允许为空：为空即不渲染，也不许有默认文案兜底
    # 注意 CSS 上有 text-transform: uppercase，比较时要归一化大小写
    check(f"{label} 小标题与配置一致（允许为空）",
          eyebrow.lower() == prof_role.lower(),
          f"profile={prof_role[:14]!r} dom={eyebrow[:14]!r}")
    check(f"{label} 签名与配置一致（允许为空）",
          (prof_bio != "") == (bio != ""),
          f"profile={prof_bio[:14]!r} dom={bio[:14]!r}")
    check(f"{label} 无默认签名文案",
          "记录光与日常" not in page.evaluate("() => document.body.innerText"))

    # 收录相关：canonical 固定指向主域名，避免 www / 裸域重复收录
    canon = page.evaluate(
        "() => { const l = document.querySelector('link[rel=canonical]'); return l ? l.href : ''; }")
    check(f"{label} canonical 指向主域名",
          canon.rstrip("/") == "https://www.frw.fan", canon)

    # Search Console 验证标记：删了会导致资源掉验证，必须有
    verify = page.evaluate(
        "() => { const m = document.querySelector('meta[name=google-site-verification]');"
        " return m ? m.content : ''; }")
    check(f"{label} 保留 Search Console 验证标记", len(verify) > 20, verify[:18] + "…")
    av = page.evaluate(
        "() => { const a = document.getElementById('heroAvatar');"
        " return a.hidden ? 0 : a.naturalWidth; }")
    check(f"{label} 头像已加载", av > 0, f"{av}px")

    qr = page.evaluate(
        """() => [...document.querySelectorAll('.qr-tile')].map(t => {
        const i = t.querySelector('img');
        const r = t.getBoundingClientRect();
        const f = t.querySelector('.qr-frame').getBoundingClientRect();
        return {key: t.dataset.key || '', nw: i.naturalWidth, w: Math.round(f.width),
                bottom: Math.round(r.bottom), vh: innerHeight};
    })""")
    check(f"{label} 两个二维码都在", len(qr) == 2, str([q["key"] for q in qr]))
    check(f"{label} 二维码素材有效", all(q["nw"] >= 300 for q in qr), str([q["nw"] for q in qr]))
    check(f"{label} 二维码在首屏内", all(q["bottom"] <= q["vh"] + 1 for q in qr),
          str([q["bottom"] for q in qr]))
    check(f"{label} 二维码尺寸可扫描", all(q["w"] >= 80 for q in qr), str([q["w"] for q in qr]))

    # 卡片里只留二维码本体 + 平台名，不再有「扫码找到我 / 手机相机或…」这类提示
    card = page.evaluate(
        """() => {
        const a = document.getElementById('heroConnect');
        if (!a) return null;
        return {
          text: (a.innerText || '').replace(/\\s+/g, ' ').trim(),
          labels: [...a.querySelectorAll('.qr-label')].map(e => e.innerText.trim()),
        };
    }""")
    check(f"{label} 二维码卡片无提示文案",
          bool(card) and "扫码找到我" not in card["text"] and "扫一扫" not in card["text"],
          (card or {}).get("text", ""))
    check(f"{label} 保留平台名说明",
          bool(card) and len(card["labels"]) == 2 and all(card["labels"]),
          str((card or {}).get("labels")))

    # 二维码可点击直接跳转：tile 是 <a>，https 外链，新窗口 + noopener
    qlink = page.evaluate(
        """() => [...document.querySelectorAll('.qr-tile')].map(t => ({
          tag: t.tagName.toLowerCase(),
          href: t.getAttribute('href') || '',
          target: t.getAttribute('target') || '',
          rel: t.getAttribute('rel') || '',
        }))""")
    check(f"{label} 二维码可点击跳转",
          len(qlink) == 2 and all(x["tag"] == "a" and x["href"].startswith("https://")
                                  for x in qlink),
          str([(x["tag"], x["href"][:30]) for x in qlink]))
    check(f"{label} 外链新窗口打开且带 noopener",
          all(x["target"] == "_blank" and "noopener" in x["rel"] for x in qlink),
          str([(x["target"], x["rel"]) for x in qlink]))

    check(f"{label} 首屏内头部透明",
          page.evaluate("() => document.getElementById('siteHeader')"
                        ".classList.contains('is-over-hero')"))
    # 滚过首屏：头部必须切回实底（页面不够长时按几何规则判定）
    page.evaluate("() => window.scrollTo(0, document.getElementById('hero').offsetHeight + 200)")
    page.wait_for_timeout(450)
    st = page.evaluate(
        """() => {
        const el = document.getElementById('siteHeader');
        return {y: Math.round(window.scrollY),
                heroH: document.getElementById('hero').offsetHeight,
                over: el.classList.contains('is-over-hero'),
                bg: getComputedStyle(el).backgroundColor};
    }""")
    past = st["y"] >= st["heroH"] - 44
    solid_bg = st["bg"] not in ("rgba(0, 0, 0, 0)", "transparent")
    check(f"{label} 头部随首屏切换（几何一致）", (not st["over"]) == past and solid_bg == past,
          f"y={st['y']} hero={st['heroH']} bg={st['bg']}")
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(350)

    leak = page.evaluate(
        """() => {
        const txt = document.body.innerText || '';
        const attrs = [...document.querySelectorAll('[src],[href]')];
        return {
            phone: /(?<![0-9A-Za-z])1[3-9]\\d{9}(?![0-9A-Za-z])/.test(txt),
            longnum: /(?<![0-9A-Za-z])\\d{11,}(?![0-9A-Za-z])/.test(txt),
            mail: /[\\w.+-]+@[\\w-]+\\.[\\w.]+/.test(txt),
            danger: attrs.some(e => /^\\s*javascript:/i.test(
                e.getAttribute('src') || e.getAttribute('href') || '')),
        };
    }""")
    check(f"{label} 页面无手机号/长串数字",
          not leak["phone"] and not leak["longnum"], str(leak))
    check(f"{label} 无邮箱无危险链接",
          not leak["mail"] and not leak["danger"], str(leak))


def run(pw, label, viewport, mobile=False, shots_prefix=""):
    print(f"\n===== {label} ({viewport['width']}x{viewport['height']}) =====", flush=True)
    browser = pw.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(
        viewport=viewport,
        device_scale_factor=1,
        is_mobile=mobile,
        has_touch=mobile,
        locale="zh-CN",
    )
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(("console." + m.type, m.text))
            if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: errors.append(("pageerror", str(e))))
    page.on("requestfailed", lambda r: errors.append(("requestfailed", r.url)))

    # 1. 首页渲染
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(800)
    cards = page.locator(".card").count()
    check(f"{label} 首页卡片数量", cards > 0, f"{cards} 张")

    # 2. 标题 / 结构
    check(f"{label} 站点标题",
          page.title() != "" and (not AUTHOR or AUTHOR in page.title()), page.title())
    check(f"{label} 头部存在", page.locator("#siteHeader").is_visible())

    # 2b. 首屏
    hero_checks(page, label)

    # 3. 图片是否真的解码成功（自然宽高 > 0）
    bad = page.evaluate(
        """() => [...document.querySelectorAll('.card img')]
                .filter(i => !(i.naturalWidth > 0)).length"""
    )
    check(f"{label} 图片全部加载", bad == 0, f"{bad} 张失败")

    # 4. 瀑布流：卡片高度有无重叠/塌陷
    geo = page.evaluate(
        """() => {
        const cards = [...document.querySelectorAll('.card')].map(c => {
            const r = c.getBoundingClientRect();
            return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)};
        });
        return {cards, cols: getComputedStyle(document.getElementById('gallery')).gridTemplateColumns};
    }"""
    )
    heights = [c["h"] for c in geo["cards"]]
    check(f"{label} 卡片高度正常", all(h > 80 for h in heights),
          f"min={min(heights) if heights else 0} max={max(heights) if heights else 0}")

    # 同列卡片不重叠
    overlap = False
    for i, a in enumerate(geo["cards"]):
        for b in geo["cards"][i + 1:]:
            if abs(a["x"] - b["x"]) < 4 and abs(a["y"] - b["y"]) < 4:
                overlap = True
    check(f"{label} 卡片无重叠", not overlap)

    ncols = len(geo["cols"].split())
    check(f"{label} 网格列数", (ncols >= 2), f"{ncols} 列")

    page.screenshot(path=os.path.join(SHOTS, f"{shots_prefix}home.png"), full_page=False)

    # 5. 移动端菜单（仅移动）
    if mobile:
        nav_visible = page.locator("#nav").is_visible()
        check(f"{label} 移动端导航默认收起", not nav_visible)
        page.click("#menuBtn")
        page.wait_for_timeout(300)
        check(f"{label} 移动端菜单可展开", page.locator("#nav").is_visible())
        page.screenshot(path=os.path.join(SHOTS, f"{shots_prefix}menu.png"))
        page.click("#menuBtn")
        page.wait_for_timeout(200)
    else:
        check(f"{label} 桌面端导航可见", page.locator("#nav").is_visible())

    # 6. 分类导航
    nav_links = page.locator("#nav .nav-link")
    n_nav = nav_links.count()
    check(f"{label} 分类链接数量", n_nav >= 2, f"{n_nav} 个")

    if n_nav >= 2:
        if mobile:
            page.click("#menuBtn")
            page.wait_for_timeout(300)
        second = nav_links.nth(1)
        cat_name = second.inner_text()
        second.click()
        page.wait_for_timeout(600)
        check(f"{label} 分类跳转 URL", "#/c/" in page.url, page.url)
        cat_cards = page.locator(".card").count()
        check(f"{label} 分类筛选有结果", cat_cards > 0, f"{cat_cards} 张")
        check(f"{label} 分类标题显示", page.locator("#sectionTitle").is_visible(),
              cat_name.replace("\n", " "))
        # 分类内所有卡片确实属于该分类
        ok_cat = page.evaluate(
            """() => {
            const key = decodeURIComponent(location.hash.replace('#/c/', ''));
            const st = window.__site;
            return st.filtered.every(w => w.category === key);
        }"""
        )
        check(f"{label} 分类内容过滤正确", ok_cat)
        page.screenshot(path=os.path.join(SHOTS, f"{shots_prefix}category.png"))

    # 7. 回到全部
    if mobile:
        page.click("#menuBtn")
        page.wait_for_timeout(300)
    page.click("#nav .nav-link[data-nav='all']")
    page.wait_for_timeout(500)
    check(f"{label} 返回全部", page.locator(".card").count() == cards,
          f"{page.locator('.card').count()} 张")

    # 8. 详情视图
    first = page.locator(".card").first
    first.click()
    page.wait_for_timeout(900)
    check(f"{label} 详情层打开", page.locator("#viewer").is_visible())
    check(f"{label} 详情 URL", "#/work/" in page.url, page.url)
    vw = page.evaluate("() => document.getElementById('viewerImg').naturalWidth")
    check(f"{label} 详情图加载", vw and vw > 0, f"naturalWidth={vw}")
    vh = page.evaluate(
        """() => { const i = document.getElementById('viewerImg');
                   const r = i.getBoundingClientRect();
                   return {w: Math.round(r.width), h: Math.round(r.height)}; }"""
    )
    vp = page.viewport_size
    check(f"{label} 详情图不溢出视口",
          vh["w"] <= vp["width"] and vh["h"] <= vp["height"], json.dumps(vh))
    check(f"{label} 详情标题非空",
          page.locator("#viewerTitle").inner_text().strip() != "")
    page.screenshot(path=os.path.join(SHOTS, f"{shots_prefix}detail.png"))

    # 8b. 多图切换（作品内）
    cur_id = page.evaluate(
        "() => decodeURIComponent(location.hash.replace('#/work/', ''))")
    n_img = page.evaluate(
        "(id) => { const w = window.__site.works.find(x => x.id === id); return w ? w.images.length : 0; }",
        cur_id)
    if n_img > 1:
        src0 = page.evaluate("() => document.getElementById('viewerImg').src")
        cnt_of = lambda: page.locator("#viewerCount").inner_text().strip()

        if mobile:
            # 移动端不显示左右按钮，用滑动手势
            check(f"{label} 移动端翻页按钮隐藏",
                  not page.locator("#viewerNext").is_visible())
            swipe = lambda dx: page.evaluate(
                """(dx) => {
                const stage = document.getElementById('viewerStage');
                const T = (t, x) => new Touch({identifier: 1, target: stage, clientX: x, clientY: 300});
                const mk = (type, x, arr) => new TouchEvent(type, {
                    bubbles: true, cancelable: true,
                    touches: arr ? [T(type, x)] : [],
                    changedTouches: [T(type, x)],
                });
                stage.dispatchEvent(mk('touchstart', 300, true));
                stage.dispatchEvent(mk('touchend', 300 + dx, false));
            }""", dx)
            swipe(-200)
            page.wait_for_timeout(600)
            src1 = page.evaluate("() => document.getElementById('viewerImg').src")
            check(f"{label} 左滑切换下一张", src0 != src1)
            check(f"{label} 图片计数正确", cnt_of() == f"2 / {n_img}", cnt_of())
            swipe(200)
            page.wait_for_timeout(600)
            check(f"{label} 右滑回上一张", cnt_of() == f"1 / {n_img}", cnt_of())
        else:
            page.click("#viewerNext")
            page.wait_for_timeout(700)
            src1 = page.evaluate("() => document.getElementById('viewerImg').src")
            check(f"{label} 下一张可切换", src0 != src1)
            check(f"{label} 图片计数正确", cnt_of() == f"2 / {n_img}", cnt_of())
            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(500)
            check(f"{label} 方向键切图", cnt_of() == f"3 / {n_img}", cnt_of())
            page.keyboard.press("ArrowLeft")
            page.wait_for_timeout(500)
            check(f"{label} 方向键回退", cnt_of() == f"2 / {n_img}", cnt_of())
    else:
        check(f"{label} 单图不显示翻页按钮",
              not page.locator("#viewerNext").is_visible())

    # 9. 关闭详情
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    check(f"{label} Esc 关闭详情", not page.locator("#viewer").is_visible())

    # 10. 直接访问详情深链（刷新后仍可打开）
    page.goto(BASE + "#/work/" + page.evaluate(
        "() => window.__site.works[0].id"), wait_until="networkidle")
    page.wait_for_timeout(900)
    check(f"{label} 详情深链可直达", page.locator("#viewer").is_visible())
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    # 11. 无横向溢出
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    check(f"{label} 无横向滚动溢出", overflow <= 1, f"{overflow}px")

    # 12. 固定暗色：默认 dark、没有切换按钮、底色确实是深色
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(300)
    theme = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
    check(f"{label} 默认暗色主题", theme == "dark", theme)
    check(f"{label} 已移除主题切换按钮", page.locator("#themeBtn").count() == 0,
          f"{page.locator('#themeBtn').count()} 个")
    body_bg = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    rgb = [int(x) for x in body_bg.replace("rgba(", "").replace("rgb(", "").rstrip(")").split(",")[:3]]
    check(f"{label} 底色为暗色", sum(rgb) / 3 < 60, body_bg)
    page.screenshot(path=os.path.join(SHOTS, f"{shots_prefix}dark-fixed.png"))

    # 13. 边界路由
    page.goto(BASE + "#/work/__not_exist__", wait_until="networkidle")
    page.wait_for_timeout(700)
    check(f"{label} 无效作品 ID 不打开详情", not page.locator("#viewer").is_visible())
    check(f"{label} 无效作品 ID 回退首页", page.locator(".card").count() > 0)

    page.goto(BASE + "#/c/__no_such_cat__", wait_until="networkidle")
    page.wait_for_timeout(700)
    check(f"{label} 空分类显示提示", page.locator("#empty").is_visible())

    # 14. 控制台错误
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(800)
    hard = [e for e in errors if e[0] in ("console.error", "pageerror", "requestfailed")]
    check(f"{label} 控制台无错误", len(hard) == 0,
          "; ".join(f"{k}:{v[:90]}" for k, v in hard[:3]))
    if errors:
        print("   全部控制台告警：", flush=True)
        for k, v in errors[:8]:
            print(f"     - {k}: {v[:120]}", flush=True)

    ctx.close()
    browser.close()


def main():
    os.makedirs(SHOTS, exist_ok=True)
    global BASE
    for i, a in enumerate(sys.argv):
        if a == "--url" and i + 1 < len(sys.argv):
            BASE = sys.argv[i + 1]
    with sync_playwright() as pw:
        run(pw, "桌面", {"width": 1440, "height": 900}, mobile=False, shots_prefix="desk-")
        run(pw, "手机", {"width": 390, "height": 844}, mobile=True, shots_prefix="mob-")
        run(pw, "平板", {"width": 820, "height": 1180}, mobile=False, shots_prefix="tab-")

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n===== 汇总：{passed}/{total} 通过 =====", flush=True)
    for n, ok, d in results:
        if not ok:
            print(f"  FAILED: {n}  [{d}]", flush=True)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
