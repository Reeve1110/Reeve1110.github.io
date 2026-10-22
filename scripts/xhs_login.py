"""扫码登录（每个账号各一次）。

用法：
  python scripts/xhs_login.py                      # 登录默认账号（key=default）
  python scripts/xhs_login.py --account photo      # 登录第二个账号（key=photo）
  python scripts/xhs_login.py --account photo --name "小号"

登录成功后把 user_id 写进 data/accounts.json，之后 xhs_fetch.py 会自动遍历所有
enabled 的账号。同一账号只需登录一次，登录态存在 data/profiles/<key>/。

注意：登录判定**不能**看 web_session cookie（游客态也有），也不能在等待期间
反复 goto —— 会把二维码页面刷掉，导致扫码永远失败。这里只在当前页轮询状态，
最多做 3 次有间隔的 reload。
"""
import json
import os
import sys
import time

from xhs_common import (DATA, get_current_user, is_logged_in, launch,
                        open_login_panel, upsert_account)

TIMEOUT = 300          # 5 分钟足够扫码
RELOAD_GAP = 35        # 两次 reload 的最小间隔
MAX_RELOAD = 3


def parse_args():
    args = {"account": "default", "name": None}
    for i, a in enumerate(sys.argv):
        if a == "--account" and i + 1 < len(sys.argv):
            args["account"] = sys.argv[i + 1]
        if a == "--name" and i + 1 < len(sys.argv):
            args["name"] = sys.argv[i + 1]
    return args


def get_user(page):
    """返回 (userId, nickname)，取不到则 (None, '')。"""
    uid, nick = get_current_user(page)
    return (uid or None, nick)


def main():
    args = parse_args()
    account = args["account"]
    headless = "--headless" in sys.argv
    pw, ctx = launch(headless=headless, account=account)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    try:
        page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
        page.wait_for_timeout(3500)

        if is_logged_in(page):
            print(f"[{account}] 检测到已登录，直接读取账号信息。", flush=True)
        else:
            if not open_login_panel(page):
                # 没有可点的登录入口，才退回到登录页
                page.goto("https://www.xiaohongshu.com/login",
                          wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                try:
                    tab = page.get_by_text("扫码登录", exact=True)
                    if tab.count():
                        tab.first.click()
                        page.wait_for_timeout(800)
                except Exception:
                    pass
            print(f"[{account}] 浏览器已打开，请扫码登录（5 分钟内，窗口请勿关闭）…",
                  flush=True)

        uid, nick = "", ""
        start = time.time()
        last_reload = start
        reloads = 0
        last_tick = -1

        while time.time() - start < TIMEOUT:
            if is_logged_in(page):
                uid, nick = get_user(page)
                if uid:
                    break
                # 刚扫码，state 可能还没刷新，等一拍再看
                page.wait_for_timeout(1500)
                uid, nick = get_user(page)
                if uid:
                    break

            el = int(time.time() - start)
            # 长时间停在同一页且仍未登录，才做一次有间隔的 reload（最多 3 次）
            if (not uid and reloads < MAX_RELOAD
                    and time.time() - last_reload > RELOAD_GAP and el > 25):
                reloads += 1
                last_reload = time.time()
                print(f"  仍未见登录态，刷新页面第 {reloads}/{MAX_RELOAD} 次…",
                      flush=True)
                try:
                    page.reload(wait_until="domcontentloaded")
                    page.wait_for_timeout(2500)
                    if not is_logged_in(page):
                        open_login_panel(page)
                except Exception:
                    pass

            if el // 20 != last_tick // 20:
                last_tick = el
                try:
                    page.screenshot(path=os.path.join(DATA, f"login_{account}.png"))
                except Exception:
                    pass
                print(f"  等待扫码 {el}s …", flush=True)

            page.wait_for_timeout(1500)

        if not uid:
            print("LOGIN_TIMEOUT 未检测到登录态", flush=True)
            return 1

        page.goto(f"https://www.xiaohongshu.com/user/profile/{uid}",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        name = args["name"] or nick or account
        upsert_account(account, name=name, user_id=uid)
        print("LOGIN_OK " + json.dumps(
            {"account": account, "name": name, "user_id": uid,
             "time": time.strftime("%F %T")}, ensure_ascii=False), flush=True)
        try:
            page.screenshot(path=os.path.join(DATA, f"profile_{account}.png"))
        except Exception:
            pass
        page.wait_for_timeout(800)
        return 0
    finally:
        try:
            ctx.close()
            pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
