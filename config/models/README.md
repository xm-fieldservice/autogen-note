# 模型快速集成指南（OpenAI 兼容）

本指南放置于模型配置同级目录，便于在任意应用中直接复用这些 JSON 模型。

目录位置：`docs/data/template/models/`

已提供的模型：
- `qwen_deepseek_r1.json`
- `qwen_deepseek_v3.json`
- `qwen_turbo_latest.json`
- `qwen_vl_plus_latest.json`
- `qwen2_5_vl_72b_instruct.json`
- `moonshot_kimi_k2.json`
- 索引：`index.json`

## 文档入口
- `openai_compat_runner_说明.md`
- `在其他应用中调用模型_快速集成指南.md`

## 0. 准备
- Python ≥ 3.10
- 依赖：`requests`
```powershell
pip install requests
```
- 设置密钥（示例，按模型 JSON 的 `config.api_key_env` 设置）：
```powershell
# Qwen/DashScope
$env:QWEN_API_KEY = "sk-..."
# Moonshot
$env:MOONSHOT_API_KEY = "sk-..."
```
- 可选：临时覆盖总超时（秒，不改 JSON）：
```powershell
$env:OPENAI_TIMEOUT = "60"
```
超时与优先级详见：`openai_compat_runner_说明.md`

## 1) 推荐：复用项目运行器的函数
```python
from backend.openai_compat_runner import chat_once

model_json = r"d:/AI-Projects/Autogen_CLI_Factory/refactoring/docs/data/template/models/qwen_deepseek_v3.json"
resp = chat_once(model_json, "用中文简要自我介绍")
print(resp.get("text"))
```
说明：
- `chat_once()` 会读取本目录的 JSON，并按 `config.api_key_env` 从环境变量取密钥。
- 返回字段包含：`ok/status_code/text/data/duration_ms`。

## 2) 通用：复制最小依赖调用函数（仅 requests）
```python
import os, json, requests

def call_openai_compatible(model_json_path: str, user_text: str) -> dict:
    cfg = json.loads(open(model_json_path, "r", encoding="utf-8").read())
    config = cfg.get("config", {})
    model = config.get("model") or config.get("deployment")
    base_url = (config.get("base_url") or config.get("endpoint") or "").rstrip("/")
    if not model or not base_url:
        raise ValueError("model/base_url is required in model json")
    api_key_env = config.get("api_key_env")
    api_key = os.getenv(api_key_env or "")
    if not api_key:
        raise RuntimeError(f"Environment variable {api_key_env} not set")

    params = config.get("parameters") or {}
    timeout = params.get("timeout") or 120
    for env_name in ("OPENAI_TIMEOUT", "OPENAI_COMPAT_TIMEOUT"):
        v = os.getenv(env_name)
        if v:
            try:
                tv = float(v)
                if tv > 0:
                    timeout = tv
                    break
            except Exception:
                pass

    url = f"{base_url}/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": cfg.get("system_message") or "You are a helpful assistant."},
            {"role": "user", "content": user_text},
        ],
    }
    for k in ("temperature", "max_tokens", "top_p", "presence_penalty", "frequency_penalty"):
        if k in params and params[k] is not None:
            payload[k] = params[k]

    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    out = {"status_code": r.status_code, "ok": r.ok}
    try:
        data = r.json()
        out["data"] = data
        if isinstance(data, dict):
            ch = (data.get("choices") or [])
            if ch and isinstance(ch, list):
                out["text"] = (ch[0].get("message") or {}).get("content")
    except Exception:
        out["text"] = r.text
    return out

# 使用示例
print(call_openai_compatible(
    r"d:/AI-Projects/Autogen_CLI_Factory/refactoring/docs/data/template/models/moonshot_kimi_k2.json",
    "给我5条高效工作的小建议"
).get("text"))
```

## 3) Node.js/TypeScript（可选）
```ts
import fetch from 'node-fetch';
import fs from 'fs';

async function callWithJson(modelJsonPath: string, userText: string) {
  const cfg = JSON.parse(fs.readFileSync(modelJsonPath, 'utf-8'));
  const baseUrl = (cfg.config.base_url || cfg.config.endpoint).replace(/\/$/, '');
  const model = cfg.config.model || cfg.config.deployment;
  const apiKeyEnv = cfg.config.api_key_env;
  const apiKey = process.env[apiKeyEnv];
  if (!apiKey) throw new Error(`Env ${apiKeyEnv} not set`);

  const body: any = {
    model,
    messages: [
      { role: 'system', content: cfg.system_message || 'You are a helpful assistant.' },
      { role: 'user', content: userText },
    ],
  };
  const p = cfg.config.parameters || {};
  for (const k of ['temperature','max_tokens','top_p','presence_penalty','frequency_penalty']){
    if (p[k] !== undefined && p[k] !== null) body[k] = p[k];
  }

  const timeout = Number(process.env.OPENAI_TIMEOUT || p.timeout || 120);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout * 1000);
  try {
    const resp = await fetch(`${baseUrl}/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}` },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    const data = await resp.json().catch(async () => ({ text: await resp.text() }));
    return { ok: resp.ok, status: resp.status, data, text: data?.choices?.[0]?.message?.content };
  } finally {
    clearTimeout(timer);
  }
}
```

## 4) cURL（调试）
```powershell
$MODEL = "deepseek-v3"
$BASE  = "https://dashscope.aliyuncs.com/compatible-mode/v1"
$KEY   = $env:QWEN_API_KEY

curl "$BASE/chat/completions" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer $KEY" `
  -d (@{ model=$MODEL; messages=@(@{role="user"; content="你是谁"}) } | ConvertTo-Json)
```

## 5) 常见问题
- API Key：按模型 JSON 的 `config.api_key_env` 设置真实 ASCII 密钥（避免中文/占位符）。
- 超时：默认以 JSON 中 `parameters.timeout` 为准；可用 `OPENAI_TIMEOUT` 临时覆盖。
- 乱码/编码：可参考 `openai_compat_runner_说明.md`，运行器已提供 `content_type/encoding/apparent_encoding/body_preview` 诊断字段。
