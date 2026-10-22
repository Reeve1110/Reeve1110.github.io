"""扫码登录（一次性）：打开独立 profile 的小红书，登录后把 user_id 落盘。

用法：python scripts/xhs_login.py
弹窗后在小红书页面用 App 扫码登录，脚本检测到登录态会自动记录并退出。
"""
import json
import os
import sys
import time

from xhs_common import DATA, launch

ACCOUNT = os.path.join(DATA, "account.json")
TIMEOUT = 600


def get_uid(page):
    """只认页面状态里的本人 userId（游客态也会分发匿名 id，故仅作辅助）。"""
    return page.evaluate(
        """() => {
        try {
            const st = window.__INITIAL_STATE__;
            if (st && st.user && st.user.userInfo && st.user.userInfo.userId)
                return st.user.userInfo.userId;
        } catch (e) {}
        return null;
    }"""
    )


def has_session(ctx):
    """登录态硬标志：web_session cookie。
    注意 web_session 是 HttpOnly，document.cookie 读不到，必须走 context.cookies()。"""
    try:
        for c in ctx.cookies():
            if c.get("name") == "web_session" and c.get("value"):
                return True
    except Exception:
        pass
    return False


def main():
    pw, ctx = launch(headless=False)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    if has_session(ctx):
        print("已检测到登录态，跳过扫码。", flush=True)
    else:
        page.goto("https://www.xiaohongshu.com/login", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        # 若没自动出二维码，点一下"扫码登录"标签
        try:
            tab = page.get_by_text("扫码登录", exact=True)
            if tab.count():
                tab.first.click()
                page.wait_for_timeout(800)
        except Exception:
            pass
        print("浏览器已打开，请扫码登录（10 分钟内）...", flush=True)

    uid = None
    start = time.time()
    while time.time() - start < TIMEOUT:
        try:
            if has_session(ctx):
                uid = get_uid(page)
                if uid:
                    break
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
        except Exception:
            pass
        el = int(time.time() - start)
        if el % 20 == 0:
            try:
                page.screenshot(path=os.path.join(DATA, "login_wait.png"))
            except Exception:
                pass
            print(f"  等待扫码 {el}s ...（浏览器窗口请勿关闭）", flush=True)
        page.wait_for_timeout(2500)

    if uid:
        page.goto(f"https://www.xiaohongshu.com/user/profile/{uid}",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        nickname = page.title()
        info = {"user_id": uid, "page_title": nickname, "time": time.strftime("%F %T")}
        with open(ACCOUNT, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
        print("LOGIN_OK", json.dumps(info, ensure_ascii=False), flush=True)
        print("FINAL_URL", page.url, flush=True)
        page.screenshot(path=os.path.join(DATA, "profile_page.png"))
    else:
        print("LOGIN_TIMEOUT", flush=True)
    ctx.close()
    pw.stop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
