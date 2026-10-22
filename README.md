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
└── images/
    └── works/<作品目录>/    作品图片
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
