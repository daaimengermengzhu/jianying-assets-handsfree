"""Boundary checks: never submit a narration for invalid user input."""
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from client_services import material_summary


class MemberServicesTest(unittest.TestCase):
    def test_asset_search_has_boundaries_and_omits_signed_urls(self):
        module = importlib.import_module('client_services')
        with patch.object(module, 'HostBridge') as bridge, patch.object(module, 'client_request') as request:
            for kind, query, limit in [('unknown', '闪光', 3), ('effect', '', 3), ('effect', '闪光', 100)]:
                with self.assertRaises(ValueError):
                    module.search_materials(kind, query, limit)
            bridge.assert_not_called()
            request.return_value = {'effect_item_list': [{'common_attr': {
                'id': '1', 'title': '闪光', 'effect_type': 7, 'item_urls': ['PRIVATE'],
                'business_info': {'json_str': '{"is_vip":true}', 'sign': 'PRIVATE'}}}], 'has_more': True}
            result = module.search_materials('effect', '闪光', 3)
            self.assertEqual(result['materials'][0]['title'], '闪光')
            self.assertTrue(result['materials'][0]['is_vip'])
            self.assertNotIn('PRIVATE', str(result))

    def test_vip_voice_requires_active_membership_before_creating_task(self):
        module = importlib.import_module('tts')
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'HostBridge') as bridge, \
                patch.object(module, 'client_request') as request:
            def jsb(method, params):
                if method == 'getUserSubcriptionInfo':
                    return {'user_info': {'credits': 3200, 'is_svip': False, 'is_vip': False}}
                return {'resources': [{'name': '真人播客男', 'isClone': False, 'isVip': True,
                                        'supported': True, 'speakerId': 'public', 'effectId': 'public'}]}
            bridge.return_value.__enter__.return_value._jsb.side_effect = jsb
            with self.assertRaises(module.NativeError):
                module.synthesize('测试', folder, voice_name='真人播客男')
            request.assert_not_called()

    def test_nullable_collection_and_private_fields(self):
        item = {'common_attr': {'title': '示例', 'business_info': {
            'json_str': '{"is_vip":true}', 'sign': 'PRIVATE'},
            'item_urls': ['https://example.invalid/PRIVATE']}, 'collection': None}
        result = material_summary(item)
        self.assertTrue(result['is_vip'])
        self.assertEqual(result['collection_items'], [])
        self.assertNotIn('PRIVATE', str(result))

    def test_invalid_narration_never_reaches_host(self):
        module = importlib.import_module('tts')
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'HostBridge') as bridge:
            for text in ('', '   ', '字' * 121, None):
                with self.subTest(text_length=len(text) if text is not None else None):
                    with self.assertRaises(ValueError):
                        module.synthesize(text, Path(folder))
            bridge.assert_not_called()

    def test_completed_task_payload_saves_audio_without_recreating_task(self):
        module = importlib.import_module('tts')
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'HostBridge') as bridge, \
                patch.object(module, 'client_request') as request, patch.object(module, 'build_opener') as opener:
            def jsb(method, params):
                if method == 'getUserSubcriptionInfo':
                    return {'user_info': {'credits': 3200}}
                return {'resources': [{'name': '解说小帅', 'isClone': False, 'supported': True,
                                        'speakerId': 'public', 'effectId': 'public'}]}
            bridge.return_value.__enter__.return_value._jsb.side_effect = jsb
            request.side_effect = [{'tasks': [{'id': 'task', 'token': 'PRIVATE'}]},
                                   {'tasks': [{'status': 'succeed', 'payload': json.dumps({
                                       'media': {'url': 'https://example.invalid/audio.mp3'}})}]}]
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'ID3sample'
            result = module.synthesize('测试', folder)
            self.assertEqual(Path(result['output']).read_bytes(), b'ID3sample')
            self.assertEqual(request.call_count, 2)
            self.assertNotIn('PRIVATE', str(result))


if __name__ == '__main__':
    unittest.main()
