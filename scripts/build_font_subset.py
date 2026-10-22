"""把本机安装的思源黑体（Source Han Sans CN）按站点实际用字裁剪成 woff2。

为什么不用整套字体：思源黑体一个权重就是 8MB 级别的 CJK 字体，整包放上去首屏会非常慢。
这里只保留页面真正会出现的字（正文 + 标题 + 数字 + 标点），体积通常只有几十 KB。

规则：
  · 用字来源 = index.html / app.js / style.css / works.json / profile.json 的全部可见字符
  · 另外补一份 ASCII 与常用中文标点，避免繁体/新加作品缺字
  · 缺字时会自动回落到系统里的思源黑体或微软雅黑，不会出现方块

用法：
  python scripts/build_font_subset.py
  python scripts/build_font_subset.py --weights 300,400,500
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "data", "pylibs"))

from fontTools import subset                      # noqa: E402
from fontTools.ttLib import TTFont                # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "fonts")

FONT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")
SOURCES = {
    300: "SourceHanSansCN-Light.otf",
    400: "SourceHanSansCN-Regular.otf",
    500: "SourceHanSansCN-Medium.otf",
}

# 只统计页面真正会渲染的文字；README / 样式表里的中文不会出现在屏幕上
TEXT_FILES = ["index.html", "assets/js/app.js", "data/works.json", "data/profile.json"]

EXTRA = (
    "0123456789"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "，。、；：？！“”‘’（）《》〈〉【】—…·～￥%&@#*/+-=_|\\\"'<>[]{}^~`"
    "·•●○◆◇■□★☆→←↑↓"
    "年月份日作品张组个系列收藏点赞评论分享关注私信发布时间地点相机镜头光圈快门感光度"
    "全部首页分类标签关于联系版权转载授权说明最新更多加载没有内容空错误重试返回上一张下一张关闭"
    "春夏秋冬东南西北城市街头校园角落动物植物建筑人像风景旅行日常记录光与影"
)


def collect_chars():
    chars = set(EXTRA)
    for rel in TEXT_FILES:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        text = open(p, encoding="utf-8").read()
        chars.update(c for c in text if ord(c) > 0x1F)
    chars.discard("\n")
    chars.discard("\r")
    chars.discard("\t")
    return "".join(sorted(chars))


def build(weight, filename, text):
    src = os.path.join(FONT_DIR, filename)
    if not os.path.exists(src):
        print(f"  ! 找不到 {src}")
        return None
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.desubroutinize = True
    opts.recalc_bounds = True
    opts.notdef_outline = True
    opts.layout_features = ["kern", "liga", "vert", "vrt2", "palt"]
    opts.name_IDs = ["*"]
    opts.name_legacy = True

    font = TTFont(src)
    sub = subset.Subsetter(options=opts)
    sub.populate(text=text)
    sub.subset(font)

    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f"shs-{weight}.woff2")
    font.flavor = "woff2"
    font.save(dst)
    return dst


def main():
    weights = [400, 500]
    for i, a in enumerate(sys.argv):
        if a == "--weights" and i + 1 < len(sys.argv):
            weights = [int(x) for x in sys.argv[i + 1].split(",")]

    text = collect_chars()
    print(f"站点用字 {len(text)} 个，开始裁剪（源：思源黑体 CN）：")
    total = 0
    for w in weights:
        if w not in SOURCES:
            print(f"  ! 不支持的权重 {w}，可选 {sorted(SOURCES)}")
            continue
        dst = build(w, SOURCES[w], text)
        if dst:
            kb = os.path.getsize(dst) / 1024
            total += kb
            print(f"  shs-{w}.woff2   {kb:6.1f} KB")
    print(f"合计 {total:.1f} KB → assets/fonts/")

    # 记录一份用字清单，方便日后核对
    meta = os.path.join(ROOT, "data", "font-chars.txt")
    with open(meta, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"用字清单 → data/font-chars.txt（{len(text)} 字）")


if __name__ == "__main__":
    main()
