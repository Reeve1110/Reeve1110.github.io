"""管理工具冒烟测试：构建窗口、校验数据加载与勾选逻辑，不改动真实数据。

用法：python scripts/test_gui.py [--shot]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import admin_gui as G

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f"   [{detail}]" if detail else ""),
          flush=True)


def main():
    shot = "--shot" in sys.argv
    works_bak = open(G.WORKS_JSON, encoding="utf-8").read()
    acc_bak = open(G.ACCOUNTS_JSON, encoding="utf-8").read()

    app = G.App()
    app.update()

    try:
        check("窗口创建", app.winfo_exists() == 1)
        check("窗口标题", "管理工具" in app.title(), app.title())

        # 作品表
        rows = app.tree.get_children()
        check("作品列表有数据", len(rows) > 0, f"{len(rows)} 行")
        first = app.tree.item(rows[0], "values")
        check("列表列数正确", len(first) == 6, str(first[:3]))
        states = {r: app.tree.set(r, "sel") for r in rows}
        check("勾选状态已渲染", all(v in ("☑", "☐") for v in states.values()),
              f"{sum(1 for v in states.values() if v == '☑')} 个显示 / "
              f"{sum(1 for v in states.values() if v == '☐')} 个隐藏")

        # 分类名显示为中文而非 key
        cats = {c["key"]: c["name"] for c in app.works_data["categories"]}
        cat_cells = [app.tree.set(r, "cat") for r in rows]
        check("分类显示中文名", all(c in cats.values() for c in cat_cells), str(set(cat_cells)))

        # 勾选切换：只验证翻转，不强求初始状态
        target = rows[0]
        before = app.tree.set(target, "sel")
        app.toggle_work(target)
        after = app.tree.set(target, "sel")
        check("点击行翻转勾选", before != after and after in ("☑", "☐"), f"{before}→{after}")
        check("标记为未保存", app.dirty is True)
        w0 = next(w for w in app.works_data["works"] if w["id"] == target)
        check("hidden 与勾选一致", bool(w0.get("hidden")) == (after == "☐"))

        # 全不选 / 全选
        app.set_all(False)
        check("全不选", all(app.tree.set(r, "sel") == "☐" for r in app.tree.get_children()))
        app.set_all(True)
        check("全选", all(app.tree.set(r, "sel") == "☑" for r in app.tree.get_children()))

        # 保存
        ok = app.save_works(silent=True)
        check("保存成功", ok)
        saved = json.load(open(G.WORKS_JSON, encoding="utf-8"))
        check("落盘后全部显示", all(not w.get("hidden") for w in saved["works"]))
        check("保存后 dirty 清除", app.dirty is False)

        # 只看已隐藏
        app.toggle_work(app.tree.get_children()[0])
        app.save_works(silent=True)
        expect_hidden = sum(1 for w in app.works_data["works"] if w.get("hidden"))
        app.only_off.set(True)
        app.reload_works()
        n1 = len(app.tree.get_children())
        check("只看已隐藏过滤生效", n1 == expect_hidden, f"{n1} 行 / 应 {expect_hidden}")
        app.only_off.set(False)
        app.reload_works()
        check("取消过滤后恢复全部", len(app.tree.get_children()) == len(rows))

        # 预览
        app.tree.selection_set(app.tree.get_children()[0])
        app.update()
        check("预览区有内容",
              app.pv_title.cget("text") != "" or app.pv.cget("image") != "")

        # 账号页
        accs = app.acc_tree.get_children()
        check("账号列表有数据", len(accs) >= 1, f"{len(accs)} 个")
        vals = app.acc_tree.item(accs[0], "values")
        check("账号列展示完整", len(vals) == 4, str(vals))

        app.nb.select(1)
        app.update()
        check("切换到账号页", app.nb.index("current") == 1)
        app.nb.select(0)
        app.update()

        # 状态栏
        st = app.status.cget("text")
        check("状态栏统计", "作品" in st and "账号" in st, st[:40])

        # 布局完整性：底部按钮与日志框必须真的可见
        check("保存按钮可见", app.btn_save.winfo_ismapped() == 1)
        check("推送按钮可见", app.btn_push.winfo_ismapped() == 1)
        check("刷新按钮可见", app.btn_refresh.winfo_ismapped() == 1)
        check("刷新按钮未被挤压", app.btn_refresh.winfo_width() > 60,
              f"{app.btn_refresh.winfo_width()}px")
        check("日志区可见", app.logbox.winfo_ismapped() == 1,
              f"{app.logbox.winfo_width()}x{app.logbox.winfo_height()}")
        check("日志区有高度", app.logbox.winfo_height() > 40,
              str(app.logbox.winfo_height()))
        # 日志必须在窗口右半边，且不覆盖主体
        lx = app.logbox.winfo_rootx() - app.winfo_rootx()
        check("日志区在窗口右侧", lx > app.winfo_width() * 0.6,
              f"x={lx} / 宽 {app.winfo_width()}")
        fh = app.btn_push.winfo_rooty() + app.btn_push.winfo_height()
        wh = app.winfo_rooty() + app.winfo_height()
        check("推送按钮在窗口内", fh <= wh, f"{fh} <= {wh}")

        # 账号显示名统一
        names = {app.acc_tree.item(i, "values")[1] for i in app.acc_tree.get_children()}
        check("账号显示名已统一", len(names) <= 1, str(names))

        # 推送状态：已经 commit 但没 push 时也必须算「有东西可推」
        changed, ahead = app._git_push_state()
        raw = G.subprocess.run(["git", "rev-list", "--count", "@{u}..HEAD"], cwd=G.ROOT,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace")
        expect = int((raw.stdout or "0").strip() or 0)
        check("推送状态与 git 一致", ahead == expect and isinstance(ahead, int),
              f"未提交 {len(changed)} / 未推送 {ahead}（git 算 {expect}）")

        if shot:
            app.update()
            try:
                app.tk.call("wm", "attributes", ".", "-topmost", 1)
            except Exception:
                pass
            app.update()
            from PIL import ImageGrab
            x, y = app.winfo_rootx(), app.winfo_rooty()
            w, h = app.winfo_width(), app.winfo_height()
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            out = os.path.join(G.DATA, "shots", "gui.png")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            img.save(out)
            print("截图:", out, flush=True)

    finally:
        app.destroy()
        open(G.WORKS_JSON, "w", encoding="utf-8").write(works_bak)
        open(G.ACCOUNTS_JSON, "w", encoding="utf-8").write(acc_bak)

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n===== 汇总：{passed}/{total} 通过 =====", flush=True)
    for n, ok, d in results:
        if not ok:
            print(f"  FAILED: {n} [{d}]", flush=True)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
