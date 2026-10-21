"""Read-only catalog/account queries through Jianying's own local host bridge.

Uses the client-published discovery credential only in memory and only on loopback.
No desktop automation, account credential export, or generation requests.
"""
import http.client
import json
from pathlib import Path
import tempfile
from urllib.parse import quote

from native import NativeError


class HostBridge:
    def __init__(self):
        path = Path(tempfile.gettempdir()) / 'infinite-canvas-native-bridge.json'
        if not path.is_file():
            raise NativeError('剪映后台桥接未就绪，请打开剪映并保持登录。')
        config = json.loads(path.read_text(encoding='utf-8'))
        self.port = int(config.get('port', 0))
        self._token = config.get('token')
        if not 1 <= self.port <= 65535 or not isinstance(self._token, str) or not self._token:
            raise NativeError('剪映服务发现文件无效。')
        self._session = None

    def _request(self, method, path, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        try:
            connection.request(method, path,
                               body=json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None,
                               headers={'x-infinite-canvas-native-token': self._token,
                                        'Content-Type': 'application/json; charset=utf-8'})
            response = connection.getresponse()
            raw = response.read(4 * 1024 * 1024 + 1)
            if response.status != 200:
                raise NativeError(f'剪映桥接请求失败（HTTP {response.status}）。')
            if len(raw) > 4 * 1024 * 1024:
                raise NativeError('剪映桥接响应超出读取上限。')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise NativeError('剪映桥接返回格式异常。')
            return result
        except (OSError, http.client.HTTPException) as error:
            raise NativeError('剪映后台连接失败或超时，请确认客户端仍在运行。') from error
        finally:
            connection.close()

    def __enter__(self):
        health = self._request('GET', '/.infinite-canvas-native-bridge/health')
        if health.get('ok') is not True:
            raise NativeError('剪映后台健康检查未通过。')
        # Do not return local_agent_server: it may include internal credentials.
        self.health = {k: health.get(k) for k in ('ok', 'pid', 'version')}
        created = self._request('POST', '/infinite-canvas/session', {})
        sid = created.get('session_id')
        if not isinstance(sid, str) or not sid:
            raise NativeError('剪映未返回测试会话编号。')
        self._session = '/infinite-canvas/session/' + quote(sid, safe='')
        return self

    def _jsb(self, method, params):
        if method not in ('getUserSubcriptionInfo', 'getToneCategories', 'getToneList',
                          'extractMediaFrames', 'getAudioWaveformData'):
            raise ValueError('Only verified read-only host methods are allowed')
        result = self._request('POST', self._session + '/jsb', {'method': method, 'params': params})
        if result.get('code') != 1 or not isinstance(result.get('data'), dict):
            raise NativeError('剪映未接受该只读请求。')
        return result['data']

    def __exit__(self, exc_type, exc, traceback):
        try:
            if self._session:
                result = self._request('DELETE', self._session)
                if result.get('ok') is not True:
                    raise NativeError('剪映测试会话清理未确认。')
        except Exception as cleanup_error:
            if exc is None:
                raise
            exc.add_note('剪映测试会话清理未确认：' + type(cleanup_error).__name__)
        finally:
            self._session = None
            self._token = None


def host_status():
    with HostBridge() as bridge:
        user = bridge._jsb('getUserSubcriptionInfo', {}).get('user_info')
        if not isinstance(user, dict):
            raise NativeError('剪映未返回会员信息。')
        result = {'bridge': bridge.health,
                  'membership': {k: user.get(k) for k in ('is_svip', 'is_vip', 'is_ultra', 'is_teams', 'is_enterprise', 'credits')},
                  'generation_triggered': False, 'quota_note': '2026-09-28/29 解说小帅及会员真人播客男短句实测前后积分未变化；不代表所有音色免费或无限。'}
    return result


def voice_categories():
    with HostBridge() as bridge:
        data = bridge._jsb('getToneCategories', {})
        tabs = data.get('tabs')
        if not isinstance(tabs, list):
            raise NativeError('剪映未返回音色分类。')
        return {'categories': [{k: tab.get(k) for k in ('id', 'key', 'name', 'available', 'tabType')} for tab in tabs]}


def search_voices(keyword, limit=5):
    if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 100:
        raise ValueError('请输入 1–100 字的音色关键词。')
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise ValueError('limit 必须为 1–20。')
    keyword = keyword.strip()
    with HostBridge() as bridge:
        data = bridge._jsb('getToneList', {'keyword': keyword, 'offset': 0, 'count': limit, 'includeUnsupported': False})
        resources = data.get('resources')
        if data.get('keyword') != keyword or not isinstance(resources, list):
            raise NativeError('剪映未确认搜索关键词或返回格式异常。')
        # Native service may return a 50-item page regardless of count.
        public = [item for item in resources if item.get('isClone') is False]
        fields = ('name', 'resourceId', 'effectId', 'speakerId', 'supported', 'isVip', 'isCommercial', 'isLimitFree')
        return {'keyword': keyword, 'received_count': len(resources),
                'voices': [{k: item.get(k) for k in fields} for item in public[:limit]],
                'has_more': bool(data.get('hasMore')) or len(public) > limit,
                'private_clone_voices_omitted': True, 'generation_triggered': False}
