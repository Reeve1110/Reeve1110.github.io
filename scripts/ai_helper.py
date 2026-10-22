"""抓取时的 AI 辅助（可选）：给新笔记判定分类、提炼标签。

默认走 DeepSeek，也预留了任意 OpenAI 兼容服务商（字段留空，用时再填）。

配置文件 data/ai.json（不会进仓库）：
{
  "enabled": true,
  "provider": "deepseek",          // deepseek | custom
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "api_key": "",
  "timeout": 30,
  "batch_size": 12,
  "custom": {                      // 预留给自定义运营商，留空即可
    "name": "",
    "base_url": "",
    "model": "",
    "api_key": ""
  }
}

设计原则：
  · 不阻塞主流程：没有 key / 请求失败 / 超时，一律静默回落关键词规则
  · 批量：一批最多 batch_size 条塞进一次请求，14 条笔记通常 1~2 次请求
  · 只做「分类 + 标签」，不改标题与正文，避免模型改写内容
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "data", "ai.json")
EXAMPLE = os.path.join(ROOT, "data", "ai.example.json")

DEFAULT = {
    "enabled": True,
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "api_key": "",
    "timeout": 30,
    "batch_size": 12,
    "custom": {"name": "", "base_url": "", "model": "", "api_key": ""},
}

_TIPS = {"shown": False}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT))
    for path in (CONFIG, EXAMPLE):   # 正式配置优先，模板只兜底
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                user = json.load(f)
        except Exception:
            continue
        for k, v in (user or {}).items():
            if k == "custom" and isinstance(v, dict):
                cfg["custom"].update({kk: vv for kk, vv in v.items() if vv})
            elif k in cfg:
                cfg[k] = v
        break
    # 环境变量优先级最高，方便临时切换
    cfg["api_key"] = (os.environ.get("DEEPSEEK_API_KEY")
                      or os.environ.get("AI_API_KEY")
                      or cfg.get("api_key") or "").strip()
    return cfg


def resolve(cfg):
    """返回 (base_url, model, api_key)；自定义服务商缺字段时返回 None。"""
    if (cfg.get("provider") or "deepseek") == "custom":
        c = cfg.get("custom") or {}
        base = (c.get("base_url") or "").strip()
        model = (c.get("model") or "").strip()
        key = (c.get("api_key") or cfg.get("api_key") or "").strip()
        if not (base and model):
            return None
    else:
        base = (cfg.get("base_url") or DEFAULT["base_url"]).strip()
        model = (cfg.get("model") or DEFAULT["model"]).strip()
        key = cfg.get("api_key") or ""
    if not (base and model and key):
        return None
    return base.rstrip("/"), model, key


def status():
    cfg = load_config()
    if not cfg.get("enabled"):
        return "已关闭"
    got = resolve(cfg)
    if not got:
        return "未配置 key（用关键词规则）"
    return f"{cfg.get('provider')} · {got[1]}"


def _chat(cfg, messages, json_mode=True):
    got = resolve(cfg)
    if not got:
        return None
    base, model, key = got
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 900,
        "stream": False,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=cfg.get("timeout", 30)) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _parse_json(text):
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


SYS = (
    "你是照片作品集的分类助手。根据标题与正文，为每条笔记选一个最合适的分类，"
    "并提炼 2~3 个中文标签（名词优先，不要#号，不要情绪词）。"
    "只输出 JSON，格式：{\"results\":[{\"i\":序号,\"category\":\"分类key\",\"tags\":[\"标签\"]}]}"
)


def classify_works(items, allowed, cfg=None):
    """items: [{"i":int, "title":str, "desc":str}] → {i: {"category":[key],"tags":[...]}}

    allowed: {key: 显示名} 允许的分类。任何异常都返回 {}，由调用方回落关键词规则。
    """
    cfg = cfg or load_config()
    if not cfg.get("enabled") or not items:
        return {}
    if not resolve(cfg):
        if not _TIPS["shown"]:
            _TIPS["shown"] = True
            print("  [AI] 未配置 api_key，跳过 AI 分类（沿用关键词规则）。\n"
                  "       需要启用请填写 data/ai.json 或设置环境变量 DEEPSEEK_API_KEY", flush=True)
        return {}

    cats = "、".join(f"{k}（{v}）" for k, v in allowed.items())
    out = {}
    size = max(1, int(cfg.get("batch_size") or 12))
    batches = [items[i:i + size] for i in range(0, len(items), size)]
    t0 = time.time()

    for bi, batch in enumerate(batches, 1):
        payload = [{"i": it["i"], "title": it.get("title", "")[:60],
                    "desc": (it.get("desc") or "")[:220]} for it in batch]
        user = (f"可选分类：{cats}\n"
                f"注意：必须从上面的 key 里选，无法判断时选 other。\n"
                f"笔记列表：{json.dumps(payload, ensure_ascii=False)}")
        try:
            raw = _chat(cfg, [{"role": "system", "content": SYS},
                              {"role": "user", "content": user}])
            got = _parse_json(raw) or {}
            for r in got.get("results", []):
                try:
                    idx = int(r.get("i"))
                except Exception:
                    continue
                cat = str(r.get("category", "")).strip()
                if cat not in allowed:
                    cat = "other"
                tags = [str(t).strip().lstrip("#") for t in (r.get("tags") or [])]
                out[idx] = {"category": cat, "tags": [t for t in tags if t][:3]}
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:160]
            except Exception:
                pass
            print(f"  [AI] 第 {bi} 批失败 HTTP {e.code} {body}", flush=True)
            if e.code in (401, 403):
                print("  [AI] api_key 无效或没有权限，本次抓取直接回落关键词规则", flush=True)
                break
        except Exception as e:
            print(f"  [AI] 第 {bi} 批失败：{type(e).__name__} {str(e)[:120]}", flush=True)

        if bi < len(batches):
            time.sleep(0.3)          # 轻微间隔，避免触发限流

    if out:
        print(f"  [AI] {len(out)}/{len(items)} 条已分类，耗时 {time.time() - t0:.1f}s",
              flush=True)
    return out
