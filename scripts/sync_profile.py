"""把小红书账号的「简介」同步到站点（data/profile.json）。

站点签名的两种来源，由 profile.json 的 bio_source 决定：
  custom       自定义：用你在管理工具 / profile.json 里手写的那段
  xiaohongshu  同步：每次运行本脚本都用小红书上的简介覆盖

用法：
  python scripts/sync_profile.py                  # 第一个启用账号
  python scripts/sync_profile.py --account photo  # 指定账号
  python scripts/sync_profile.py --dry-run        # 只看抓到的内容，不写文件

安全：只抓昵称 / 简介 / 小红书号用于本地核对；小红书号不会写进 profile.json。
"""
import json
import os
import re
import sys

from xhs_common import DATA, launch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNTS = os.path.join(DATA, "accounts.json")
PROFILE = os.path.join(ROOT, "data", "profile.json")
RAW = os.path.join(DATA, "raw")

EXTRACT_JS = r"""() => {
  const unwrap = (v) => {
    let n = 0;
    while (v && typeof v === 'object' && 'value' in v && n < 4) { v = v.value; n++; }
    return v;
  };
  const s = (o, k) => (o && o[k] != null ? String(o[k]) : '');
  const st = window.__INITIAL_STATE__;
  const u = st && st.user;
  const page = unwrap(u && u.userPageData) || {};
  const info = unwrap(page.basicInfo) || {};
  const ui = unwrap(u && u.userInfo) || {};
  return {
    nick: s(info, 'nickname') || s(info, 'nickName') || s(ui, 'nickname'),
    desc: s(info, 'desc') || s(info, 'description') || s(ui, 'desc'),
    redId: s(info, 'redId') || s(ui, 'redId'),
    userId: s(info, 'userId') || s(ui, 'userId'),
  };
}"""


def clean_bio(desc, max_lines=4, max_len=140):
    text = (desc or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]{2,}", " ", ln).strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln][:max_lines]
    out = "\n".join(lines)
    return out[:max_len].rstrip()


def pick_account(argv):
    key = None
    for i, a in enumerate(argv):
        if a == "--account" and i + 1 < len(argv):
            key = argv[i + 1]
    accs = []
    if os.path.exists(ACCOUNTS):
        accs = json.load(open(ACCOUNTS, encoding="utf-8")).get("accounts", [])
    if key:
        for a in accs:
            if a.get("key") == key:
                return a
        raise SystemExit(f"没有这个账号：{key}")
    for a in accs:
        if a.get("enabled", True) and a.get("user_id"):
            return a
    raise SystemExit("accounts.json 里没有可用账号，先在管理工具里添加并登录。")


def main():
    dry = "--dry-run" in sys.argv
    acc = pick_account(sys.argv)
    key, uid = acc["key"], acc.get("user_id", "")
    if not uid:
        raise SystemExit(f"账号 {key} 缺少 user_id")

    print(f"读取 {key} 的主页资料…", flush=True)
    pw, ctx = launch(headless=True, account=key)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"https://www.xiaohongshu.com/user/profile/{uid}",
                  wait_until="commit")
        for _ in range(40):
            try:
                info = page.evaluate(EXTRACT_JS) or {}
                if info.get("desc") is not None and info.get("nick"):
                    break
            except Exception:
                pass
            page.wait_for_timeout(200)
        info = page.evaluate(EXTRACT_JS) or {}
    finally:
        try:
            ctx.close()
            pw.stop()
        except Exception:
            pass

    nick = (info.get("nick") or "").strip()
    bio = clean_bio(info.get("desc"))
    print(f"  昵称：{nick or '（未取到）'}")
    print(f"  简介：{bio.replace(chr(10), ' / ') or '（空）'}")

    os.makedirs(RAW, exist_ok=True)
    tmp = os.path.join(RAW, f"profile_{key}.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"account": key, "nick": nick, "bio": bio,
                   "has_red_id": bool(info.get("redId"))},
                  f, ensure_ascii=False, indent=2)

    if dry:
        print("\n--dry-run：没有写入 profile.json")
        return

    prof = {}
    if os.path.exists(PROFILE):
        prof = json.load(open(PROFILE, encoding="utf-8"))
    source = prof.get("bio_source", "custom")
    if source != "xiaohongshu":
        print(f"\n当前签名来源是「{source}」，保持不覆盖。"
              f"想用小红书简介请在管理工具里把来源切到「同步小红书」。")
        return
    if not bio:
        print("\n小红书简介为空，保留原签名。")
        return

    prof["bio"] = bio
    with open(PROFILE, "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, indent=2)
    print("\n已写入 data/profile.json 的 bio（来源：小红书）")


if __name__ == "__main__":
    main()
