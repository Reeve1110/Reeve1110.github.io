# Reeve — 摄影作品站

个人摄影作品展示站，纯静态，托管于 GitHub Pages。
线上地址：<https://reeve1110.github.io/>

## 技术形态

- 纯 HTML / CSS / JavaScript，无构建步骤、无后端、无第三方依赖
- 单一数据源：`data/works.json`
- 打开 `index.html` 即可运行（建议用本地服务器，见下）

```
.
├── index.html              页面结构（一般不用改）
├── assets/
│   ├── css/style.css       样式
│   └── js/app.js           渲染逻辑：网格 / 分类 / 详情
├── data/
│   └── works.json          ★ 作品数据，唯一需要维护的文件
├── images/
│   └── works/<作品目录>/    作品图片
└── scripts/                小红书导入与自测脚本（不参与页面运行）
```

## 新增一组作品

只需两步，**不需要改任何页面代码**。

**1. 放图片**

在 `images/works/` 下新建一个目录，例如 `images/works/2026-11-02-厦门/`，
把图片放进去（建议命名 `01.webp`、`02.webp`…，长边 1600px 左右，宽高比保持原样）。

**2. 追加一条数据**

在 `data/works.json` 的 `works` 数组**最前面**加一个对象：

```json
{
  "id": "2026-11-02-xiamen",
  "slug": "2026-11-02-厦门",
  "title": "厦门三日",
  "caption": "海风把云吹得很低。\n第二天下午下了雨。",
  "date": "2026-11-02",
  "year": "2026",
  "tags": ["海", "胶片"],
  "category": "2026",
  "source": "",
  "thumb": "images/works/2026-11-02-厦门/01.webp",
  "images": [
    { "src": "images/works/2026-11-02-厦门/01.webp",
      "thumb": "images/works/2026-11-02-厦门/01_t.webp",
      "w": 1600, "h": 2133 },
    { "src": "images/works/2026-11-02-厦门/02.webp",
      "thumb": "images/works/2026-11-02-厦门/02_t.webp",
      "w": 1600, "h": 1067 }
  ]
}
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 唯一标识，用于详情页链接 `#/work/<id>` |
| `title` | 是 | 作品标题 |
| `caption` | 否 | 正文，`\n` 换行 |
| `date` | 是 | `YYYY-MM-DD`，列表按它倒序 |
| `category` | 是 | 分类 key，需与 `categories` 中某项对应 |
| `thumb` | 是 | 列表封面（取第一张的 `_t` 缩略图即可） |
| `images` | 是 | 图片数组，`w`/`h` 为像素尺寸（用于瀑布流排版，必填） |
| `hidden` | 否 | `true` 时不在站点显示（图片仍保留），默认 `false` |
| `author` | 否 | 作者/账号名，多账号时在详情页显示 |
| `tags` / `source` / `slug` | 否 | 备注、原文链接、目录名 |

**分类**：在 `categories` 里登记，`key` 供数据引用，`name` 是显示名：

```json
"categories": [
  { "key": "2026", "name": "2026 年" },
  { "key": "street", "name": "街头" }
]
```

`category` 只要在 `works` 里出现而 `categories` 未登记，也会自动按 key 显示。

**缩略图**：`w ≤ 720` 的 webp，用于列表首屏加速；没有的话把 `thumb` 指向原图也能用，只是加载慢些。

## 本地预览

```bash
python -m http.server 8000
# 打开 http://127.0.0.1:8000/
```

直接双击 `index.html` 会因浏览器跨域策略读不到 `works.json`，必须走本地服务器。

## 页面特性

- 瀑布流按图片原始宽高比排版，不裁切
- 分类筛选、作品详情覆盖层（`Esc` 关闭、`←/→` 切图、手机左右滑动）
- 深浅色主题，跟随系统，可手动切换并记忆
- 移动端 2 列 / 桌面 3–5 列自适应
- 详情页链接可直接分享（`#/work/<id>`）

## 部署

仓库 `Reeve1110/Reeve1110.github.io`，推送到 `main` 分支即自动发布：

```bash
git add -A
git commit -m "新增：厦门三日"
git push
```

## 数据来源

初始作品由本人小红书公开笔记导入（`scripts/xhs_fetch.py`），
图片版权归作者所有。

## 从小红书导入（可选）

脚本用独立浏览器 profile 保存登录态，**只抓公开笔记**：私密（仅自己可见）与视频自动跳过。

```bash
python scripts/xhs_login.py                 # 登录默认账号（扫码一次）
python scripts/xhs_fetch.py                 # 抓取 + 下载图片 + 生成 works.json
```

- 已有作品按笔记 ID 跳过，可反复运行做增量同步
- **手工改过的条目不会被覆盖**：`title` / `category` / `hidden` 都以 `works.json` 里现值为准
- `data/accounts.json`、`data/profiles/`、`data/exclude.json` 都在 `.gitignore` 内，不会进仓库

### 两个（或多个）账号

每个账号有独立登录态，互不干扰：

```bash
python scripts/xhs_login.py --account photo --name "小号"   # 第二个账号登录一次
python scripts/xhs_fetch.py                                # 之后默认同步所有 enabled 账号
python scripts/xhs_fetch.py --account photo                # 只同步某一个
```

账号表 `data/accounts.json`：

```json
{ "accounts": [
  { "key": "default", "name": "Reeve", "user_id": "625fb...", "enabled": true },
  { "key": "photo",   "name": "小号",   "user_id": "69xxx...", "enabled": true }
]}
```

把 `enabled` 改 `false` 即可整体停用某个账号。两个账号的作品会混排在同一条时间线上，
作品详情页的作者名只在存在多个账号时显示。

### 某些笔记不想同步

两层机制，按需求选：

**① 永久排除（不下载、不进数据）** — 编辑 `data/exclude.json`：

```json
{
  "ids": ["68a2fa63000000001c007770"],
  "title_keywords": ["领养", "宿舍", "考试"]
}
```

`ids` 是笔记链接里 `/explore/<这一串>`；`title_keywords` 命中标题或正文就排除。
改完重跑 `xhs_fetch.py`。已经导入过的，还要从 `works.json` 里删掉那一条。

**② 临时隐藏（图还在，只是不显示）** — 在 `data/works.json` 对应作品里加一行：

```json
{ "id": "...", "title": "...", "hidden": true }
```

改完刷新页面即可，随时改回 `false` 恢复。

**③ 彻底不要** — 直接删掉 `works.json` 里的条目和 `images/works/<目录>/`。

## 自测

```bash
python -m http.server 8765          # 另开一个终端
python scripts/test_site.py         # 桌面 / 手机 / 平板三档逐项校验，截图存 data/shots/
```
