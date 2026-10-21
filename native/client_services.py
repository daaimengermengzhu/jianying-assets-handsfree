"""Client-signed service requests for material research; credentials stay in host."""
import json
from urllib.parse import unquote

from native import NativeError
from host_bridge import HostBridge

CATALOG_PATHS = {
    '/artist/v1/panel/get_panel_info',
    '/artist/v1/effect/get_resources_by_category_id',
    '/artist/v1/effect/mget_item',
    '/artist/v1/effect/get_categories',
    '/artist/v1/effect/search',
}
TTS_PATHS = {'/lv/v1/web/common_task/new', '/lv/v1/web/common_task/query'}


def client_request(bridge, path, body, *, allow_tts=False):
    allowed = CATALOG_PATHS | (TTS_PATHS if allow_tts else set())
    if path not in allowed:
        raise ValueError('Unverified service route')
    result = bridge._request('POST', bridge._session + '/jsb', {
        'method': 'request', 'params': {
            'url': 'https://lv-pc-api.ulikecam.com' + path,
            'method': 'POST', 'needCommonParams': True, 'header_signing': True,
            'header': {'Content-Type': 'application/json'},
            'data': json.dumps(body, ensure_ascii=False),
        },
    })
    if result.get('code') != 1:
        raise NativeError('客户端未接受服务请求。')
    encoded = result.get('data', {}).get('encodeData')
    if not isinstance(encoded, str):
        raise NativeError('客户端未返回可解码的服务响应。')
    data = json.loads(unquote(encoded))
    response = data.get('response', {})
    if isinstance(response, str):
        response = json.loads(response)
    if data.get('httpCode') != 200 or str(response.get('ret')) != '0':
        raise NativeError(f'剪映服务拒绝请求（HTTP {data.get("httpCode")}，业务码 {response.get("ret")}）。')
    return response.get('data', {})


PANELS = {'filter': 'filter-c', 'sticker': 'default-c', 'text-template': 'text-template-c'}
SEARCH_TYPES = {'effect': 7, 'transition': 19, 'subtitle-template': 48, 'material': 201,
                'sound': 3, 'music': 4, 'sticker': 2, 'text-template': 6, 'recipe': 50}


def material_categories(kind):
    if kind not in PANELS:
        raise ValueError('已验证分类：filter、sticker、text-template。')
    with HostBridge() as bridge:
        data = client_request(bridge, '/artist/v1/panel/get_panel_info', {'panel': PANELS[kind]})
        def clean(category):
            return {**{k: category.get(k) for k in ('category_id', 'category_name', 'category_key')},
                    'sub_categories': [clean(c) for c in category.get('sub_categories') or []]}
        return {'kind': kind, 'categories': [clean(c) for c in data.get('categories', [])]}


def material_summary(item):
    common = item.get('common_attr', {})
    rights = json.loads(common.get('business_info', {}).get('json_str') or '{}')
    # Do not expose signed URLs, business signatures, or creator account data.
    return {**{k: common.get(k) for k in ('id', 'effect_id', 'effect_type', 'title', 'source')},
            'is_vip': rights.get('is_vip'), 'is_expired': rights.get('is_expired'),
            'paid_type': rights.get('paid_type'),
            'collection_items': [{k: child.get(k) for k in ('id', 'effect_type', 'source')}
                                 for child in (item.get('collection') or {}).get('resources', [])]}


def list_materials(category_id, limit=5, offset=0):
    if not isinstance(category_id, int) or isinstance(category_id, bool) or category_id <= 0:
        raise ValueError('需要目录返回的正整数 category_id。')
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise ValueError('limit 必须为 1–20。')
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError('offset 必须为非负整数。')
    with HostBridge() as bridge:
        data = client_request(bridge, '/artist/v1/effect/get_resources_by_category_id', {
            'category_id': category_id, 'offset': offset, 'count': limit})
        return {'category_id': category_id,
                'materials': [material_summary(item) for item in data.get('effect_item_list', [])[:limit]],
                'has_more': data.get('has_more'), 'next_offset': data.get('next_offset'),
                'downloaded': False, 'applied': False}


def search_materials(kind, keyword, limit=5, offset=0):
    if not isinstance(kind, str) or kind not in SEARCH_TYPES:
        raise ValueError('已验证检索类型：' + '、'.join(SEARCH_TYPES))
    if not isinstance(keyword, str) or not 1 <= len(keyword.strip()) <= 100:
        raise ValueError('请输入 1–100 字素材关键词。')
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise ValueError('limit 必须为 1–20。')
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError('offset 必须为非负整数。')
    options = {'filter_uncommercial': False}
    if kind == 'material':
        options.update(scene='material_lib_c_v2', sticker_type=0)
    with HostBridge() as bridge:
        data = client_request(bridge, '/artist/v1/effect/search', {
            'app_id': 3704, 'effect_type': SEARCH_TYPES[kind], 'query': keyword.strip(),
            'offset': offset, 'count': limit, 'need_recommend': False,
            'filter_optional': {'filter_paid_type': []},
            'pack_optional': {'need_contract': True, 'need_favorite_info': True},
            'search_id': '', 'search_option': options, 'statistics_optional': {}, 'strategy_extra': ''})
        return {'kind': kind, 'keyword': keyword.strip(),
                'materials': [material_summary(item) for item in (data.get('effect_item_list') or [])[:limit]],
                'has_more': data.get('has_more'), 'next_offset': data.get('next_offset'),
                'downloaded': False, 'applied': False}
