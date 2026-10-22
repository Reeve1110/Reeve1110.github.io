"""验证登录等待流程：未登录时不得反复导航（页面被刷走会导致扫码永远失败）。

用一个全新 profile 模拟未登录账号，观察 35 秒内主框架导航次数与 URL 变化。
"""
import os
import shutil
import sys
import time

from xhs_common import is_logged_in, launch, open_login_panel, profile_dir

ACC = "tmpcheck"


def main():
    prof = profile_dir(ACC)
    if os.path.isdir(prof):
        shutil.rmtree(prof, ignore_errors=True)

    pw, ctx = launch(headless="--headed" not in sys.argv, account=ACC)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    navs = []

    def on_nav(frame):
        if frame == page.main_frame:
            navs.append((round(time.time() % 1000, 1), frame.url))

    page.on("framenavigated", on_nav)
    try:
        page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        print("初始已登录?", is_logged_in(page), flush=True)
        print("登录入口可点?", open_login_panel(page), flush=True)

        start = time.time()
        marks = []
        while time.time() - start < 35:
            marks.append((round(time.time() - start),
                          page.url.split("?")[0], is_logged_in(page)))
            page.wait_for_timeout(5000)

        for m in marks:
            print(f"  t={m[0]:>2}s  logged_in={m[2]}  {m[1]}", flush=True)

        print(f"\n主框架导航次数：{len(navs)}", flush=True)
        for n in navs:
            print("   ", n[1][:90], flush=True)

        # SPA 初始化自身会触发几次同 URL 的导航，判断标准是「是否停留在同一页面」
        urls = [n[1] for n in navs]
        distinct = set(urls)
        stayed = len(distinct) <= 1 and page.url.split("?")[0].endswith("/explore")
        print("\nRESULT:",
              "PASS 页面稳定在 explore，未被刷走" if stayed else "FAIL 页面被导航到别处",
              flush=True)
        return 0 if stayed else 1
    finally:
        ctx.close()
        pw.stop()
        shutil.rmtree(prof, ignore_errors=True)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
