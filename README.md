# 维护手册

仓库里同时放着**页面文件**和**维护脚本**。日常只需要动 `data/` 与 `images/`，
其余目录除非要改样式或逻辑，一般不用碰。

## 目录

```
.
├── index.html              页面骨架
├── 管理工具.bat            双击启动桌面管理工具（无控制台窗口）
├── assets/
│   ├── css/style.css       样式
│   ├── js/app.js           渲染逻辑
│   ├── fonts/              思源黑体子集（woff2）
│   └── img/                头像与二维码素材
├── data/
│   ├── works.json          ★ 作品数据（进仓库）
│   ├── profile.json        ★ 名字 / 签名 / 二维码（进仓库）
│   ├── ai.json             AI 配置（**不进仓库**，含 key；模板见 ai.example.json）
│   └── ...                 账号、登录态、抓取缓存（**不进仓库**）
├── images/works/           作品图片
└── scripts/                抓取、同步、自测、发布门禁
```

## 环境

- Python 3.13+（要带 tkinter 与 Pillow），本机用 `D:\tool\Python\Python314`
- 依赖：`pillow`、`playwright`（抓取用）、`fonttools` + `brotli`（重做字体子集用）
- 换机器时改一下 `管理工具.bat` 里的 `PY` 路径

## 管理工具

双击 `管理工具.bat`，三个标签页：

| 标签页 | 用途 |
|---|---|
| **作品同步** | 勾选哪些作品对外显示；「抓取新笔记」增量同步；「保存修改」「推送更新」 |
| **个人信息** | 名字、小标题、个性签名（自定义 / 同步小红书）、AI 接口配置 |
| **账号管理** | 添加账号并扫码登录、启用停用、移除、清除登录态 |

耗时操作都在后台线程执行，输出实时打在窗口下方的日志区。

## 抓取笔记

```bash
python scripts/xhs_login.py --account default          # 首次/掉登录时扫码一次
python scripts/xhs_fetch.py                            # 所有启用账号：抓元数据 + 下载图片
python scripts/xhs_fetch.py --account photo            # 只抓某个账号
python scripts/xhs_fetch.py --refresh                  # 刷新已有笔记的内容（发布日期不变）
python scripts/xhs_fetch.py --meta-only                # 只抓元数据（最快）
python scripts/xhs_fetch.py --images-only              # 只补图片（复用已有元数据）
python scripts/xhs_fetch.py --no-ai                    # 关闭 AI，强制走关键词分类
```

- 只抓公开笔记：卡片上标记「仅自己可见」的直接跳过，视频也跳过
- 增量：已有笔记按 ID 跳过，可反复运行；**手工改过的 `title` / `category` / `hidden` 不会被覆盖**
- 每抓到一条就落盘 `data/raw/notes_<账号>.json`，中途崩了不会丢进度
- 跑完会打印分阶段耗时，例如：
  `耗时：打开主页 1.0s · 滚动加载 3.5s · 详情 11 条 5.6s（均 0.51s/条）`

### `--refresh` 刷新笔记状态

笔记在小红书上编辑过（改标题、改正文、换图）后跑这个，**只更新内容，不动发布日期**：

| 更新 | 保持 |
|---|---|
| `title` / `caption` / `tags` | `date` / `year`（首次发布那天） |
| 图片（重新下载，多余的旧图会清掉） | `slug`（图片目录名） |
| `author`（统一取 `profile.json` 的 `name`） | `category`（人工分类）、`hidden`（显示/隐藏） |

下载失败的图会沿用旧文件，不会把一组图刷成残缺。管理工具里对应「刷新笔记状态」按钮。

### 速度相关的实现（别乱改）

| 做法 | 原因 |
|---|---|
| `page.goto(..., wait_until="commit")` | 小红书主页的 `DOMContentLoaded` 会被拖到 **≈28s**，而 DOM 0.5s 就到了；改成 commit 后自己轮询就绪 |
| 图片/字体/视频请求全部 abort | 只需要 DOM 与 `__INITIAL_STATE__`，没必要下载几 MB 图片 |
| 轮询代替固定 sleep | 详情页就绪通常 0.3~0.7s，原来固定等 1.9s |
| 私密笔记在列表阶段就跳过 | 省掉一整次页面加载 |
| 滚动：数量不再增长才判定到底 | 虚拟列表会回收节点，只按数量判断会误停 |

## AI 辅助分类（可选）

默认接 DeepSeek，也预留了任意 OpenAI 兼容服务商。

配置：仓库里只带一份空模板 `data/ai.example.json`，复制成 `data/ai.json` 再填 key（`ai.json` **不进仓库**）：

```bash
cp data/ai.example.json data/ai.json
```

`data/ai.json` 各字段：

```json
{
  "enabled": true,
  "provider": "deepseek",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "api_key": "填你自己的 key",
  "timeout": 30,
  "batch_size": 12,
  "custom": {
    "name": "",
    "base_url": "",
    "model": "",
    "api_key": ""
  }
}
```

- `provider` 填 `custom` 时，改用 `custom` 里的四个字段（默认全部留空，需要时再填）
- key 也可以走环境变量：`DEEPSEEK_API_KEY` / `AI_API_KEY`（优先级最高）
- 只给**新增作品**判定 `category` 与 `tags`，不改标题与正文
- 一批最多 `batch_size` 条塞进一次请求，14 条笔记通常 1~2 次请求
- 没填 key、超时、401、网络失败 → 静默回落关键词规则，抓取照常完成
- 关掉：`"enabled": false` 或命令行加 `--no-ai`

## 数据格式

### `data/works.json`

```json
{
  "site": { "title": "翎溯", "subtitle": "记录光与日常。", "authors": ["翎溯"] },
  "categories": [{ "key": "pets", "name": "萌宠" }],
  "works": [
    {
      "id": "6a110c550000000008032756",
      "slug": "2026-10-06-小狗当然要出去撒欢啦",
      "title": "小狗当然要出去撒欢啦",
      "caption": "正文……",
      "date": "2026-10-06",
      "year": "2026",
      "tags": ["狗", "公园"],
      "category": "pets",
      "author": "翎溯",
      "source": "",
      "thumb": "images/works/<目录>/01_t.webp",
      "images": [{ "src": "images/works/<目录>/01.webp",
                   "thumb": "images/works/<目录>/01_t.webp",
                   "w": 1600, "h": 2133 }],
      "hidden": false
    }
  ]
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 唯一标识，详情链接为 `#/work/<id>` |
| `title` | 是 | 标题 |
| `caption` | 否 | 正文，`\n` 换行 |
| `date` | 是 | `YYYY-MM-DD`，列表按它倒序 |
| `category` | 是 | 需与 `categories` 里的 `key` 对应 |
| `thumb` | 是 | 列表封面 |
| `images[].w/h` | 是 | 像素尺寸，排版依赖它，不能缺 |
| `hidden` | 否 | `true` 时不在页面出现（图片仍保留） |
| `author` | 否 | 多账号时在详情页显示 |
| `tags` / `source` / `slug` | 否 | 备注、原文链接、目录名 |

### `data/profile.json`

```json
{
  "name": "翎溯",
  "role": "Photography · 摄影",
  "bio": "第一行\n第二行",
  "bio_source": "custom",
  "avatar": "assets/img/avatar.png",
  "links": [
    { "key": "xiaohongshu", "label": "小红书", "qr": "assets/img/qr-xiaohongshu.png" },
    { "key": "douyin", "label": "抖音", "qr": "assets/img/qr-douyin.png" }
  ]
}
```

- `bio_source`：`custom` 用这里写的 `bio`；`xiaohongshu` 每次同步都用小红书简介覆盖
- `bio` 里的换行会原样显示
- `avatar` / `links[].qr` 只允许 `assets/` 或 `images/` 开头的站内路径

同步小红书简介：

```bash
python scripts/sync_profile.py                 # 用 bio_source=xiaohongshu 时才写入
python scripts/sync_profile.py --dry-run       # 只看抓到的内容
```

## 多账号

每个账号一个独立浏览器 profile，互不影响：

```bash
python scripts/xhs_login.py --account photo --name "小号"
python scripts/xhs_fetch.py                    # 默认同步所有 enabled 账号
```

`data/accounts.json` 里把 `enabled` 改成 `false` 即整体停用。

## 排除 / 隐藏

| 需要 | 做法 |
|---|---|
| 不下载、不进数据 | `data/exclude.json` 里写 `ids` 或 `title_keywords` |
| 图留着但不展示 | `works.json` 里该条加 `"hidden": true`（管理工具勾选框就是改这个） |
| 彻底不要 | 删 `works.json` 的条目 + 删对应 `images/works/<目录>/` |

## 发布

```bash
python scripts/guard_public.py     # 发布前门禁，必须通过
git add -A && git commit -m "同步：<说明>" && git push
```

`guard_public.py` 会检查对外文件里有没有手机号、身份证、邮箱、11 位以上连续数字
（账号/订单号）、敏感字段名，以及 `data/` 是否只跟踪了 `works.json` 与 `profile.json`、
`assets/img` 的图片是否已剥离 EXIF。任何一条命中都会以非零码退出。

## 字体

页面用思源黑体（Source Han Sans CN），按实际用字裁剪后自托管在 `assets/fonts/`：

```bash
python scripts/build_font_subset.py            # 重新生成 shs-400 / shs-500
```

- 需要本机装有 `SourceHanSansCN-Light/Regular/Medium.otf`
- 新增作品带来了新汉字时，重跑一次即可把缺字补进去
- 没跑也没关系：缺字会回落到系统里的思源黑体或微软雅黑，不会出现方块

## 素材

`scripts/make_brand_assets.py` 从 `data/brand-src/` 的原图生成头像与二维码，
**只抠图形本体**（不包含原卡片上的昵称、小红书号、抖音号等文字），
并重新编码为 PNG 以剥离 EXIF / GPS。

```bash
python scripts/make_brand_assets.py --preview
```

## 自测

```bash
python -m http.server 8765          # 另开一个终端
python scripts/test_site.py         # 页面三档视口 + 首屏 + 敏感信息断言，截图存 data/shots/
python scripts/test_site.py --url https://<你的域名>/    # 同一套断言跑线上
python scripts/test_gui.py --shot   # 管理工具控件与布局
```

## 隐私约定

- `data/` 下除 `works.json`、`profile.json`、`ai.example.json`（空模板）外**一律不进仓库**：
  账号 ID、登录态、AI key 都只在本地
- 页面上不渲染任何账号 ID / 手机号 / 邮箱；二维码素材在生成时就裁掉了这些文字
- `profile.json` 的字段是白名单，多余字段会被门禁拦下
