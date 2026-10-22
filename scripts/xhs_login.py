"""扫码登录（每个账号各一次）。

用法：
  python scripts/xhs_login.py                      # 登录默认账号（key=default）
  python scripts/xhs_login.py --account photo      # 登录第二个账号（key=photo）
  python scripts/xhs_login.py --account photo --name "小号"

登录成功后把 user_id 写进 data/accounts.json，之后 xhs_fetch.py 会自动遍历所有
enabled 的账号。同一账号只需登录一次，登录态存在 data/profiles/<key>/。
"""
import json
import os
import sys
import time

from xhs_common import DATA, launch, upsert_account

TIMEOUT = 600


def parse_args():
    args = {"account": "default", "name": None}
    for i, a in enumerate(sys.argv):
        if a == "--account" and i + 1 < len(sys.argv):
            args["account"] = sys.argv[i + 1]
        if a == "--name" and i + 1 < len(sys.argv):
            args["name"] = sys.argv[i + 1]
    return args


def get_uid(page):
    return page.evaluate(
        """() => {
        try {
            const st = window.__INITIAL_STATE__;
            if (st && st.user && st.user.userInfo && st.user.userInfo.userId)
                return String(st.user.userInfo.userId);
        } catch (e) {}
        return null;
    }"""
    )


def get_nickname(page):
    return page.evaluate(
        """() => {
        try {
            const st = window.__INITIAL_STATE__;
            const ui = st && st.user && st.user.userInfo;
            return ui ? String(ui.nickname || ui.nickName || '') : '';
        } catch (e) { return ''; }
    }"""
    )


def has_session(ctx):
    """登录态硬标志：web_session（HttpOnly，document.cookie 读不到）。"""
    try:
        for c in ctx.cookies():
            if c.get("name") == "web_session" and c.get("value"):
                return True
    except Exception:
        pass
    return False


def main():
    args = parse_args()
    account = args["account"]
    pw, ctx = launch(headless=False, account=account)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    if has_session(ctx):
        print(f"[{account}] 已有登录态，直接读取账号信息。", flush=True)
        page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
    else:
        page.goto("https://www.xiaohongshu.com/login", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        try:
            tab = page.get_by_text("扫码登录", exact=True)
            if tab.count():
                tab.first.click()
                page.wait_for_timeout(800)
        except Exception:
            pass
        print(f"[{account}] 浏览器已打开，请扫码登录（10 分钟内）...", flush=True)

    uid = None
    start = time.time()
    while time.time() - start < TIMEOUT:
        try:
            if has_session(ctx):
                uid = get_uid(page)
                if not uid:
                    page.goto("https://www.xiaohongshu.com/explore",
                              wait_until="domcontentloaded")
                    page.wait_for_timeout(2500)
                    uid = get_uid(page)
                if uid:
                    break
        except Exception:
            pass
        el = int(time.time() - start)
        if el % 20 == 0:
            try:
                page.screenshot(path=os.path.join(DATA, f"login_{account}.png"))
            except Exception:
                pass
            print(f"  等待扫码 {el}s ...", flush=True)
        page.wait_for_timeout(2500)

    if not uid:
        print("LOGIN_TIMEOUT", flush=True)
        ctx.close()
        pw.stop()
        sys.exit(1)

    page.goto(f"https://www.xiaohongshu.com/user/profile/{uid}",
              wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    nick = args["name"] or get_nickname(page) or account
    upsert_account(account, name=nick, user_id=uid)
    info = {"account": account, "name": nick, "user_id": uid,
            "time": time.strftime("%F %T")}
    print("LOGIN_OK " + json.dumps(info, ensure_ascii=False), flush=True)
    page.screenshot(path=os.path.join(DATA, f"profile_{account}.png"))
    ctx.close()
    pw.stop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
