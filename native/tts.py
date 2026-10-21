"""Short SystemTTS narration through the running, logged-in Jianying client."""
import json
import time
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler

from client_services import client_request
from host_bridge import HostBridge
from native import NativeError


VOICES = ('解说小帅', '真人播客男')


def synthesize(text, output_root, voice_name='解说小帅'):
    """Generate one short sample with a named public catalog voice. No create retry."""
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 120:
        raise ValueError('当前只支持 1–120 字短配音。')
    if voice_name not in VOICES:
        raise ValueError('当前支持音色：' + '、'.join(VOICES))
    text = text.strip()
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / (voice_name + '_' + uuid4().hex + '.mp3')
    report = {'text': text, 'voice': voice_name, 'model': 'SystemTTS', 'generated': False}
    with HostBridge() as bridge:
        def credits():
            return bridge._jsb('getUserSubcriptionInfo', {}).get('user_info', {}).get('credits')
        account = bridge._jsb('getUserSubcriptionInfo', {}).get('user_info', {})
        report['credits_before'] = account.get('credits')
        tones = bridge._jsb('getToneList', {'keyword': report['voice'], 'offset': 0,
                                          'count': 5, 'includeUnsupported': False})
        voice = next((v for v in tones.get('resources', [])
                      if v.get('name') == report['voice'] and v.get('isClone') is False
                      and v.get('supported')), None)
        if not voice or not voice.get('speakerId') or not voice.get('effectId'):
            raise NativeError('当前客户端未返回已验证的公开音色。')
        report['voice_is_vip'] = voice.get('isVip')
        if voice.get('isVip') and not any(account.get(k) for k in ('is_vip', 'is_svip', 'is_ultra')):
            raise NativeError('当前帐号未确认会员权益，未提交会员配音任务。')
        cap = {'biz_scene': 'tts', 'model': 'SystemTTS', 'text': text,
               'tone_info': {'tone_speaker': voice['speakerId'], 'tone_effect_id': voice['effectId']}}
        created = client_request(bridge, '/lv/v1/web/common_task/new', {
            'bind_id': str(uuid4()), 'enter_from': 'pc_canvas',
            'tasks': [{'context': str(uuid4()), 'type': 10000, 'req_key': 'pc_canvas_tool',
                       'task_version': 'v3', 'payload': json.dumps({
                           'cap_key': 'pc_canvas_tool_collect', 'cap_json': cap}, ensure_ascii=False)}],
            'request_extra': json.dumps({'generate_id': str(uuid4())}),
        }, allow_tts=True)
        tasks = created.get('tasks') or []
        if not tasks:
            codes = [t.get('err_code') for t in created.get('failed_tasks', [])]
            raise NativeError(f'剪映未创建配音任务，错误码：{codes}；未自动重试。')
        handle = {k: tasks[0][k] for k in ('id', 'token')}
        handle.update(req_key='pc_canvas_tool', task_version='v3')
        deadline = time.monotonic() + 90
        while True:
            queried = client_request(bridge, '/lv/v1/web/common_task/query', {'tasks': [handle]}, allow_tts=True)
            task = (queried.get('tasks') or [{}])[0]
            state = task.get('status')
            if state == 'succeed':
                result = task.get('result', task.get('payload', {}))
                if isinstance(result, str):
                    result = json.loads(result)
                media = result.get('media') or {}
                url = media.get('url', '')
                parts = urlsplit(url)
                if parts.scheme != 'https' or not parts.hostname:
                    raise NativeError('配音任务完成，但没有有效音频下载地址。')
                # Service-issued media URL only; no account headers or proxy credentials.
                try:
                    with build_opener(ProxyHandler({})).open(url, timeout=30) as response:
                        audio = response.read(25 * 1024 * 1024 + 1)
                except Exception:
                    raise NativeError('配音已生成，音频下载失败；未重新提交生成任务。') from None
                if len(audio) > 25 * 1024 * 1024 or len(audio) < 4:
                    raise NativeError('音频大小异常。')
                if not (audio.startswith(b'ID3') or (audio[0] == 255 and audio[1] & 224 == 224)):
                    raise NativeError('下载结果不是预期 MP3 文件。')
                with output.open('xb') as target:
                    target.write(audio)
                report.update(generated=True, output=str(output), bytes=len(audio))
                break
            if state not in ('queueing', 'processing'):
                raise NativeError(f'配音任务未成功，状态 {state}，错误码 {task.get("err_code")}；未重试。')
            if time.monotonic() >= deadline:
                raise NativeError('配音查询超时，服务端任务可能仍在继续；未重复创建任务。')
            time.sleep(3)
        # A failed balance query must not conceal a successfully saved narration.
        try:
            report['credits_after'] = credits()
        except NativeError:
            report['credits_after'] = None
        report['quota_note'] = '仅记录本次前后余额；不代表所有音色永久免费或无限使用。'
    return report
