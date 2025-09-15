from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from datetime import datetime

app = FastAPI(title="Mock API for Local Testing")

@app.get('/healthz')
async def healthz():
    return PlainTextResponse('ok', status_code=200)

@app.post('/preprocess')
async def preprocess(req: Request):
    data = await req.json()
    topic_id = data.get('topic_id')
    raw_md = data.get('raw_md') or ''
    mode = data.get('mode') or 'note'
    agent_cfg = data.get('agent_config_path')

    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    result = f"【预处理成功 @ {stamp} · mode={mode} · agent={agent_cfg}】\n\n" + str(raw_md).strip()
    return JSONResponse({
        'ok': True,
        'markdown': result,
        'agent_used': agent_cfg,
        'mode': mode,
        'topic_id': topic_id,
        'length': len(raw_md or ''),
    })

@app.post('/chat/completions')
async def chat_completions(req: Request):
    try:
        data = await req.json()
    except Exception:
        data = {}
    model = (data or {}).get('model') or 'mock-model'
    messages = (data or {}).get('messages') or []
    user = ''
    for m in messages:
        if isinstance(m, dict) and m.get('role') == 'user':
            user = str(m.get('content') or '')
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    content = f"# 结果整理\n\n> mock@{stamp} · model={model}\n\n" + (user or '')
    return JSONResponse({
        'id': 'chatcmpl-mock',
        'object': 'chat.completion',
        'created': int(datetime.now().timestamp()),
        'model': model,
        'choices': [
            {
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': content,
                },
                'finish_reason': 'stop',
            }
        ],
    })

