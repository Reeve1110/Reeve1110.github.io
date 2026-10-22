"""从社交平台导出的「二维码卡片」里只抠出可扫描的本体，去掉所有文字信息。

处理原则（安全优先）：
  1. 只保留二维码图形本身与头像，**原卡片上的昵称、小红书号、抖音号、
     说明文字、Logo 区全部丢弃**——这些内容不会被截图进任何对外资源。
  2. 全部重新编码输出 PNG，不复制原始文件，EXIF / GPS / 设备信息随之丢失。
  3. 圆形/异形边缘用洪水填充取轮廓 + 羽化，做出抗锯齿的透明边。

用法：
  python scripts/make_brand_assets.py            # 生成 assets/img/*.png
  python scripts/make_brand_assets.py --preview  # 额外输出拼版预览
"""
import os
import sys
from collections import deque

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "brand-src")
OUT = os.path.join(ROOT, "assets", "img")
PREVIEW = os.path.join(ROOT, "data", "shots")

# 裁剪参数（原图像素坐标，已按实际卡片量过）
# 用户提供的 600x600 头像原图；裁掉右下角「小红书号」水印那条，再取正方形
AVATAR = dict(img="avatar-600.jpg", box=(32, 0, 568, 536), size=320)
XHS_QR = dict(img="xhs-card.jpg", box=(688, 1047, 893, 1252), pad=0.055)
DY_QR = dict(img="douyin-card.png", seed=(400, 900), bbox=(236, 280, 1074, 1118))

SS = 4  # 头像蒙版的超采样倍数


def _open(name):
    p = os.path.join(SRC, name)
    if not os.path.exists(p):
        raise SystemExit(f"缺少源图：{p}")
    return Image.open(p).convert("RGB")


def circle_mask(size):
    big = Image.new("L", (size * SS, size * SS), 0)
    ImageDraw.Draw(big).ellipse((0, 0, size * SS - 1, size * SS - 1), fill=255)
    return big.resize((size, size), Image.LANCZOS)


def cut_circle(im, cx, cy, r, out_size):
    crop = im.crop((cx - r, cy - r, cx + r, cy + r)).resize((out_size, out_size), Image.LANCZOS)
    out = crop.convert("RGBA")
    out.putalpha(circle_mask(out_size))
    return out


def blob_mask(im, seed, bbox):
    """把二维码圆盘从灰底上抠下来：洪水填充取连通域 → 行内补齐 → 羽化。"""
    a = np.asarray(im).astype(int)
    mx, mn = a.max(2), a.min(2)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    solid = ((mn > 200) & ((mx - mn) < 30)) | ((b - g > 18) & (r > 100))

    half = solid[::2, ::2]
    h, w = half.shape
    sy, sx = seed[1] // 2, seed[0] // 2
    if not half[sy, sx]:
        raise SystemExit("种子点不在二维码区域内，检查 DY_QR.seed")

    seen = np.zeros_like(half, bool)
    seen[sy, sx] = True
    q = deque([(sy, sx)])
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and half[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))

    # 行内补齐：把圆盘中间的图案/头像空洞填实（该形状逐行是凸的）
    for y in range(h):
        xs = np.nonzero(seen[y])[0]
        if len(xs):
            seen[y, xs.min():xs.max() + 1] = True

    m = Image.fromarray((seen * 255).astype(np.uint8)).resize(
        (half.shape[1] * 2, half.shape[0] * 2), Image.BILINEAR)
    m = m.filter(ImageFilter.GaussianBlur(1.6))

    left, top, right, bottom = bbox
    out = im.crop(bbox).convert("RGBA")
    out.putalpha(m.crop(bbox))
    return out


def cut_avatar():
    n = AVATAR["size"]
    a = _open(AVATAR["img"]).crop(AVATAR["box"]).resize((n, n), Image.LANCZOS)
    out = a.convert("RGBA")
    out.putalpha(circle_mask(n))
    return out.filter(ImageFilter.UnsharpMask(radius=1.4, percent=45, threshold=2))


def cut_qr_square():
    im = _open(XHS_QR["img"])
    left, top, right, bottom = XHS_QR["box"]
    pad = int((right - left) * XHS_QR["pad"])
    crop = im.crop((left - pad, top - pad, right + pad, bottom + pad)).convert("L")
    crop = crop.point(lambda v: 0 if v < 118 else (255 if v > 205 else v))
    return crop.convert("RGB").resize((480, 480), Image.LANCZOS)


def cut_qr_blob():
    return blob_mask(_open(DY_QR["img"]), DY_QR["seed"], DY_QR["bbox"]).resize(
        (640, 640), Image.LANCZOS)


def save(im, name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    im.save(path, "PNG", optimize=True)
    print(f"  {name:22} {im.size[0]}x{im.size[1]}  {os.path.getsize(path) // 1024} KB")
    return path


def main():
    print("生成对外素材（已剥离 EXIF，不含任何账号文字）：")
    save(cut_avatar(), "avatar.png")
    save(cut_qr_square(), "qr-xiaohongshu.png")
    save(cut_qr_blob(), "qr-douyin.png")

    if "--preview" in sys.argv:
        os.makedirs(PREVIEW, exist_ok=True)
        sheet = Image.new("RGB", (960, 400), "#f4f3f1")
        for name, x, s in (("avatar.png", 40, 200), ("qr-xiaohongshu.png", 300, 280),
                           ("qr-douyin.png", 620, 280)):
            im = Image.open(os.path.join(OUT, name)).convert("RGBA").resize((s, s))
            sheet.paste(im, (x, 60), im)
        sheet.save(os.path.join(PREVIEW, "brand-assets.png"))
        print("  预览 → data/shots/brand-assets.png")


if __name__ == "__main__":
    main()
