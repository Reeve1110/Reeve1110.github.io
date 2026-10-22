"""小红书抓取公共模块：复用 Edge 登录态（复制 profile 关键文件到独立目录）。

原因：Edge 正在运行时其真实 profile 被锁，Playwright 无法直接接管；
      且直接驱动用户主 profile 有污染风险。做法是把 Cookies / Local Storage /
      Local State（含 DPAPI 加密密钥）复制到项目内的独立 profile，同账号 Windows
      DPAPI 可正常解密，Chromium 启动后即为已登录状态。
"""
import os
import shutil
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PROFILE = os.path.join(DATA, "xhs_profile")

EDGE_USER_DATA = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data"
)
SRC_DEFAULT = os.path.join(EDGE_USER_DATA, "Default")

CHROME_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=Translate,OptimizationHints",
]


def prepare_profile(force=False):
    """把 Edge 的登录态文件复制到独立 profile 目录。"""
    os.makedirs(os.path.join(PROFILE, "Default", "Network"), exist_ok=True)
    os.makedirs(os.path.join(PROFILE, "Default", "Local Storage", "leveldb"), exist_ok=True)
    os.makedirs(os.path.join(PROFILE, "Default", "IndexedDB"), exist_ok=True)

    marker = os.path.join(PROFILE, ".copied")
    if os.path.exists(marker) and not force:
        return PROFILE

    pairs = [
        (os.path.join(EDGE_USER_DATA, "Local State"),
         os.path.join(PROFILE, "Local State")),
        (os.path.join(SRC_DEFAULT, "Network", "Cookies"),
         os.path.join(PROFILE, "Default", "Network", "Cookies")),
        (os.path.join(SRC_DEFAULT, "Preferences"),
         os.path.join(PROFILE, "Default", "Preferences")),
    ]
    # 文件被运行中的 Edge 独占时无法复制，属于正常情况：全新 profile 走扫码登录
    for src, dst in pairs:
        if os.path.exists(src):
            try:
                shutil.copy2(src, dst)
            except (PermissionError, OSError) as e:
                print(f"[profile] 跳过 {os.path.basename(dst)}: {e}")

    for sub in ("Local Storage", "IndexedDB", "Session Storage"):
        s = os.path.join(SRC_DEFAULT, sub)
        d = os.path.join(PROFILE, "Default", sub)
        if os.path.isdir(s):
            try:
                shutil.copytree(s, d, dirs_exist_ok=True)
            except (PermissionError, OSError) as e:
                print(f"[profile] 跳过 {sub}: {e}")

    with open(marker, "w", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    return PROFILE


def launch(headless=False, force_copy=False):
    prepare_profile(force=force_copy)
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        PROFILE,
        channel="msedge",
        headless=headless,
        args=CHROME_ARGS,
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        device_scale_factor=1,
    )
    # 抹掉最常见的自动化指纹
    ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    return pw, ctx


def probe_login(page):
    """返回 (logged_in: bool, user_id: str|None)。"""
    page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    # 页面右上角出现"登录"按钮 = 未登录
    login_btn = page.locator("text=登录").count()
    me = page.evaluate(
        """() => {
        const out = {url: location.href, links: []};
        document.querySelectorAll('a[href*="/user/profile/"]').forEach(a => {
            const m = a.getAttribute('href').match(/user\\/profile\\/([0-9a-f]{10,})/);
            if (m) out.links.push({id: m[1], text: (a.innerText||'').trim()});
        });
        try {
            const st = window.__INITIAL_STATE__;
            if (st && st.user) {
                const u = st.user.userInfo || st.user;
                out.stateUser = u;
            }
        } catch (e) {}
        return out;
    }"""
    )
    print("[probe]", me.get("url"))
    print("[probe] 用户链接:", me.get("links")[:6])
    su = me.get("stateUser") or {}
    uid = su.get("userId") or su.get("user_id") or su.get("userId")
    print("[probe] state.user:", {k: (str(v)[:40]) for k, v in list(su.items())[:12]} if su else None)
    print("[probe] 登录字样出现次数:", login_btn)
    return bool(uid or me.get("links")), uid


if __name__ == "__main__":
    headless = "--headless" in sys.argv
    pw, ctx = launch(headless=headless, force_copy="--copy" in sys.argv)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        ok, uid = probe_login(page)
        # 登录态自检：尝试打开个人主页（需要 uid 才知道地址）
        if uid:
            page.goto(f"https://www.xiaohongshu.com/user/profile/{uid}",
                      wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            print("[probe] 个人主页标题:", page.title())
            print("[probe] 最终 URL:", page.url)
        shot = os.path.join(DATA, "probe.png")
        page.screenshot(path=shot, full_page=False)
        print("[probe] 截图:", shot)
        print("[probe] RESULT:", "LOGGED_IN" if ok else "NOT_LOGGED_IN", uid)
    finally:
        if "--keep" not in sys.argv:
            ctx.close()
            pw.stop()
