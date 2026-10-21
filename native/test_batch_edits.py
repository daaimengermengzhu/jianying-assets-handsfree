import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from native import NativeError, PROJECT
from model_edits import _save
from workflow import sha256


class AtomicSaveTests(unittest.TestCase):
    def test_output_created_concurrently_is_never_replaced(self):
        root = PROJECT/'work'; root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='atomic-collision-test-', dir=root) as temp:
            folder = Path(temp).resolve()
            self.assertTrue(folder.is_relative_to(root.resolve()))
            source = folder/'source.json'; source.write_text('original', encoding='utf-8')
            output = folder/'output'
            class RacingDestination:
                saved = None
                def write_new(self, path, snapshot):
                    self.saved = copy.deepcopy(snapshot)
                    Path(path).write_text('encrypted', encoding='utf-8')
                def read(self, path):
                    output.mkdir()
                    (output/'user.txt').write_text('keep me', encoding='utf-8')
                    return {'encrypted':True, 'content':json.dumps(self.saved)}
            with self.assertRaises(OSError):
                _save(RacingDestination(), source, output, sha256(source),
                      {'tracks':[], 'materials':{}, 'duration':1}, True, {'kind':'test'})
            self.assertEqual((output/'user.txt').read_text(encoding='utf-8'), 'keep me')
            self.assertFalse((output/'draft_content.json').exists())
            self.assertFalse(list(folder.glob('.jy-draft-building-*')))

    def test_failed_readback_never_exposes_final_draft(self):
        root=PROJECT/'work';root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='atomic-save-test-',dir=root) as temp:
            folder=Path(temp).resolve();self.assertTrue(folder.is_relative_to(root.resolve()))
            source=folder/'source.json';source.write_text('unchanged',encoding='utf-8')
            output=folder/'output'
            class BrokenNative:
                def write_new(self,path,snapshot):
                    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text('partial',encoding='utf-8')
                def read(self,path):return {'encrypted':True,'content':'{}'}
            with self.assertRaises(NativeError):
                _save(BrokenNative(),source,output,sha256(source),{'tracks':[],'materials':{},'duration':1},True,{'kind':'test'})
            self.assertFalse((output/'draft_content.json').exists(),'A failed readback left a deliverable-looking draft')
            self.assertEqual(source.read_text(encoding='utf-8'),'unchanged')

    def test_concurrent_source_change_never_publishes(self):
        root=PROJECT/'work';root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='atomic-source-test-',dir=root) as temp:
            folder=Path(temp).resolve();self.assertTrue(folder.is_relative_to(root.resolve()))
            source=folder/'source.json';source.write_text('original',encoding='utf-8')
            output=folder/'output'
            class RacingNative:
                saved=None
                def write_new(self,path,snapshot):
                    self.saved=copy.deepcopy(snapshot);path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text('encrypted',encoding='utf-8')
                def read(self,path):
                    source.write_text('user changed the source',encoding='utf-8')
                    return {'encrypted':True,'content':json.dumps(self.saved)}
            with self.assertRaises(NativeError):
                _save(RacingNative(),source,output,sha256(source),{'tracks':[],'materials':{},'duration':1},True,{'kind':'test'})
            self.assertFalse(output.exists())
            self.assertEqual(source.read_text(encoding='utf-8'),'user changed the source')


class BatchPrimitiveTests(unittest.TestCase):
    def fixture(self):
        return {'duration':3000000,'future':{'keep':True},'tracks':[
            {'id':'v','type':'video','segments':[{'id':'v1','material_id':'vm','target_timerange':{'duration':3000000},'clip':{'rotation':12,'future':7}}]},
            {'id':'a','type':'audio','segments':[{'id':'a1','material_id':'am','volume':0.5,'future':8}]}],
            'materials':{'videos':[{'id':'vm'}],'audios':[{'id':'am'}]}}

    def test_transform_and_volume_preserve_unrelated_data(self):
        from batch_edits import apply_basic_edit
        old=self.fixture()
        new=apply_basic_edit(old,{'action':'transform','segment_id':'v1','scale':1.6,'x':0.2,'y':-0.5})
        self.assertEqual(new['tracks'][0]['segments'][0]['clip']['scale'],{'x':1.6,'y':1.6})
        self.assertEqual(new['tracks'][0]['segments'][0]['clip']['rotation'],12)
        self.assertEqual(new['tracks'][1],old['tracks'][1])
        updated=apply_basic_edit(new,{'action':'volume','segment_id':'a1','volume':0.15})
        self.assertEqual(updated['tracks'][1]['segments'][0]['volume'],0.15)
        self.assertEqual(updated['materials'],old['materials'])
        self.assertEqual(old,self.fixture())

    def test_reject_invalid_or_unknown_operations(self):
        from batch_edits import validate_operations, apply_basic_edit
        for ops in ([],[{'action':'export'}],[{'action':'volume','segment_id':'a1','volume':0.2,'typo':2}], [{}]*101):
            with self.assertRaises(ValueError):validate_operations(ops)
        for value in (float('nan'),float('inf'),-1,True):
            with self.assertRaises(ValueError):apply_basic_edit(self.fixture(),{'action':'volume','segment_id':'a1','volume':value})
        with self.assertRaises(ValueError):apply_basic_edit(self.fixture(),{'action':'transform','segment_id':'a1','scale':2})

    def test_missing_font_is_reported_as_a_dependency_gap(self):
        from batch_edits import resource_issues
        draft=self.fixture()
        draft['materials']['videos'][0]['font_path']='Z:/definitely-missing-test-font.ttf'
        problems=resource_issues(draft,PROJECT)
        self.assertTrue(any('definitely-missing-test-font.ttf' in p for p in problems['missing_paths']))

    def test_unused_cache_and_official_ids_are_not_missing_dependencies(self):
        from batch_edits import resource_issues
        draft = self.fixture()
        draft['materials']['videos'][0]['material_id'] = '7011354844199980325'
        draft['materials']['videos'].append({'id':'unused', 'path':'Z:/missing-unused-cache.mp4'})
        issues = resource_issues(draft, PROJECT)
        self.assertEqual(issues['missing_paths'], [])
        self.assertEqual(issues['missing_material_refs'], [])
        draft['tracks'][0]['segments'][0]['extra_material_refs'] = ['missing-real-ref']
        self.assertEqual(resource_issues(draft, PROJECT)['missing_material_refs'], ['missing-real-ref'])


class WorkerFailureTests(unittest.TestCase):
    def test_model_timeout_and_mismatch_close_private_worker(self):
        from model_session import ModelSession
        for reply in (None, {'id':999, 'ok':True, 'model':{}}):
            session = ModelSession(timeout=0.001)
            if reply:
                session.messages.put(reply)
            with patch.object(session, 'process') as process, patch.object(session, 'close') as close:
                with self.assertRaises(NativeError):
                    session.apply({'tracks':[], 'materials':{}}, 'sticker', {})
                close.assert_called_once()

    def test_failed_later_batch_action_never_saves_earlier_edits(self):
        from batch_edits import edit_batch
        draft = BatchPrimitiveTests().fixture()
        with patch('batch_edits.NativeSession'), patch('batch_edits._prepare') as prepare, patch('batch_edits._save') as save:
            prepare.return_value = (PROJECT/'dummy.json', PROJECT/'work/dummy', 'hash', draft, True)
            with self.assertRaises(ValueError):
                edit_batch('unused', 'unused', [
                    {'action':'transform', 'segment_id':'v1', 'scale':1.6},
                    {'action':'transform', 'segment_id':'a1', 'scale':2}])
            save.assert_not_called()
            self.assertEqual(draft, BatchPrimitiveTests().fixture())


if __name__=='__main__':unittest.main()
