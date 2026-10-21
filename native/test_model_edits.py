import copy
import unittest

from model_edits import edit_caption_snapshot, merge_model_result, delta_overlay


class ModelEditTests(unittest.TestCase):
    def fixture(self):
        return {'duration':3000000,'future':{'preserve':True}, 'tracks':[
            {'id':'vtrack','type':'video','segments':[{'id':'v','material_id':'vm','target_timerange':{'duration':3000000}}]},
            {'id':'txt','type':'text','segments':[{'id':'t','material_id':'tm','future_segment':7}]},
            {'id':'fx','type':'effect','segments':[{'id':'e','material_id':'em'}]},
            {'id':'au','type':'audio','segments':[{'id':'a','material_id':'am'}]}],
            'materials':{'texts':[{'id':'tm','type':'text','content':'{"text":"你好","styles":[{"range":[0,2],"size":15}]}',
                                  'text_to_audio_ids':['am'],'unknown_field':'keep'}],
                         'videos':[{'id':'vm'}],'audios':[{'id':'am'}], 'video_effects':[{'id':'em'}]}}

    def test_caption_utf16_preserves_audio_and_unknowns(self):
        old=self.fixture(); saved=copy.deepcopy(old)
        new=edit_caption_snapshot(old,'t','你好😀')
        import json
        rich=json.loads(new['materials']['texts'][0]['content'])
        self.assertEqual(rich['styles'][0]['range'],[0,4])
        self.assertEqual(new['tracks'],old['tracks'])
        self.assertEqual(new['materials']['audios'],old['materials']['audios'])
        self.assertEqual(new['materials']['texts'][0]['unknown_field'],'keep')
        self.assertEqual(new['materials']['texts'][0]['text_to_audio_ids'],['am'])
        self.assertEqual(old,saved)

    def test_ambiguous_rich_text_and_shared_material_fail(self):
        old=self.fixture()
        old['materials']['texts'][0]['content']='{"text":"你好","styles":[{"range":[0,1]},{"range":[1,2]}]}'
        with self.assertRaises(ValueError):edit_caption_snapshot(old,'t','新字幕')
        old=self.fixture();old['tracks'][1]['segments'].append({'id':'t2','material_id':'tm'})
        with self.assertRaises(ValueError):edit_caption_snapshot(old,'t','新字幕')

    def test_model_normalization_does_not_delete_existing_effects(self):
        old=self.fixture();before=copy.deepcopy(old)
        before['tracks']=[t for t in before['tracks'] if t['type']!='effect']
        before['materials']['texts'][0].pop('unknown_field')
        after=copy.deepcopy(before)
        after['tracks'].insert(1,{'id':'s-track','type':'sticker','segments':[{'id':'s','material_id':'sm','extra_material_refs':['sa'],'target_timerange':{'start':0,'duration':1000000}}]})
        after['materials']['stickers']=[{'id':'sm','resource_id':'123'}]
        after['materials']['material_animations']=[{'id':'sa'}]
        after['materials']['vocal_beautifys']=[{'id':'unrelated-normalization'}]
        new=merge_model_result(old,before,after,'sticker','s')
        self.assertEqual(new['tracks'][-2:],old['tracks'][-2:])
        self.assertEqual(new['materials']['texts'],old['materials']['texts'])
        self.assertNotIn('vocal_beautifys',new['materials'])
        self.assertEqual(new['materials']['material_animations'],[{'id':'sa'}])

    def test_template_only_overlays_real_action_delta(self):
        old=self.fixture();before=copy.deepcopy(old)
        before['materials']['texts'][0].pop('unknown_field')
        before['materials']['texts'][0]['font_size']=12 # normalization only
        after=copy.deepcopy(before)
        after['materials']['texts'][0]['caption_template_info']={'resource_id':'123'}
        after['tracks'][1]['segments'][0]['extra_material_refs']=['anim']
        after['materials']['material_animations']=[{'id':'anim'}]
        new=merge_model_result(old,before,after,'subtitle-template','t')
        self.assertEqual(new['materials']['texts'][0]['unknown_field'],'keep')
        self.assertNotIn('font_size',new['materials']['texts'][0])
        self.assertEqual(new['materials']['texts'][0]['caption_template_info']['resource_id'],'123')
        self.assertEqual(new['tracks'][0],old['tracks'][0])

    def test_noop_and_id_collision_are_not_success(self):
        old=self.fixture()
        with self.assertRaises(ValueError):merge_model_result(old,old,old,'sticker','absent')
        with self.assertRaises(ValueError):merge_model_result(old,old,old,'subtitle-template','t')

    def test_overlay_preserves_nested_unknown_fields(self):
        self.assertEqual(delta_overlay({'x':{'a':1,'unknown':2}}, {'x':{'a':1,'default':0}}, {'x':{'a':3,'default':0}}), {'x':{'a':3,'unknown':2}})


if __name__=='__main__':unittest.main()
