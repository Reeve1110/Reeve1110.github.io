"""小红书抓取公共模块。

两件事：
1) 每个小红书账号一个独立浏览器 profile（data/profiles/<key>），登录态互不干扰；
   Edge 正在运行时其真实 profile 被独占，Playwright 无法接管，只能走扫码登录一次。
2) 账号表 data/accounts.json 记录 key / 显示名 / user_id，供多账号同步使用。
"""
import json
import os
import shutil
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PROFILES_DIR = os.path.join(DATA, "profiles")
ACCOUNTS_JSON = os.path.join(DATA, "accounts.json")

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


def profile_dir(account="default"):
    return os.path.join(PROFILES_DIR, account)


def load_accounts():
    """账号表；首次运行自动把旧的单账号 account.json 迁移过来。"""
    if os.path.exists(ACCOUNTS_JSON):
        try:
            with open(ACCOUNTS_JSON, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    legacy = os.path.join(DATA, "account.json")
    accounts = []
    if os.path.exists(legacy):
        try:
            with open(legacy, encoding="utf-8") as f:
                old = json.load(f)
            if old.get("user_id"):
                # 显示名统一由管理工具按 profile.json 的 name 回填，这里不必硬编码
                accounts.append({"key": "default", "name": "",
                                 "user_id": old["user_id"], "enabled": True})
        except Exception:
            pass
    data = {"accounts": accounts}
    save_accounts(data)
    return data


def save_accounts(data):
    os.makedirs(DATA, exist_ok=True)
    tmp = ACCOUNTS_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ACCOUNTS_JSON)


def upsert_account(key, name=None, user_id=None):
    data = load_accounts()
    for a in data["accounts"]:
        if a.get("key") == key:
            if name:
                a["name"] = name
            if user_id:
                a["user_id"] = user_id
            save_accounts(data)
            return a
    item = {"key": key, "name": name or key, "user_id": user_id or "", "enabled": True}
    data["accounts"].append(item)
    save_accounts(data)
    return item


def prepare_profile(account="default", force=False):
    """初始化账号 profile 目录（不复制 Edge 的登录态，Edge 常驻会独占文件）。"""
    prof = profile_dir(account)
    os.makedirs(os.path.join(prof, "Default", "Network"), exist_ok=True)
    marker = os.path.join(prof, ".created")
    if not os.path.exists(marker):
        with open(marker, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    return prof


# 真实登录态判定。注意两点：
#   1) web_session cookie 游客态也会下发，不能拿它判断；
#   2) state 里的 userInfo / loggedIn 是 Vue ref，必须解包 .value 才能读到内容
#      （不解包会永远读到空对象，进而导致「以为没登录 → 反复刷新页面」）。
IS_LOGGED_IN_JS = """() => {
  const unref = v => (v && v.__v_isRef) ? v.value : v;
  try {
    const st = window.__INITIAL_STATE__;
    const u = st && st.user;
    if (!u) return false;
    const li = unref(u.loggedIn);
    const ui = unref(u.userInfo);
    if (li === true && ui && (ui.userId || ui.user_id)) return true;
    if (ui && (ui.userId || ui.user_id) && (ui.nickname || ui.nickName)) return true;
  } catch (e) {}
  try {
    const txt = document.body ? (document.body.innerText || '') : '';
    if (txt.indexOf('发布笔记') > -1) return true;
  } catch (e) {}
  return false;
}"""


def is_logged_in(page):
    """页面是否处于已登录状态。切勿用 cookie 判断——游客也有 web_session。"""
    try:
        return bool(page.evaluate(IS_LOGGED_IN_JS))
    except Exception:
        return False


def get_current_user(page):
    """返回 (userId, nickname)；未登录返回 ('', '')。"""
    try:
        return page.evaluate(
            """() => {
            const unref = v => (v && v.__v_isRef) ? v.value : v;
            try {
                const u = window.__INITIAL_STATE__ && window.__INITIAL_STATE__.user;
                const ui = unref(u && u.userInfo);
                if (ui) return [String(ui.userId || ui.user_id || ''),
                                String(ui.nickname || ui.nickName || '')];
            } catch (e) {}
            return ['', ''];
        }"""
        )
    except Exception:
        return ("", "")


def open_login_panel(page):
    """已登录之外的场景：把二维码浮层点出来（比直接跳 /login 稳，不会把页面刷走）。"""
    clicked = page.evaluate(
        """() => {
        const cands = [...document.querySelectorAll('button, div, span, a')]
          .filter(e => (e.innerText || '').trim() === '登录' && e.offsetParent !== null);
        if (!cands.length) return false;
        cands[cands.length - 1].click();
        return true;
    }"""
    )
    if clicked:
        page.wait_for_timeout(1200)
    return clicked


def launch(headless=False, force_copy=False, account="default"):
    prof = prepare_profile(account, force=force_copy)
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        prof,
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
