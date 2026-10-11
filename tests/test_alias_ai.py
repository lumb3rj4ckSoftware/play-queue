import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import alias_ai


class AliasAITest(unittest.TestCase):
    def setUp(self):
        self.saved = (alias_ai._model, alias_ai._tokenizer, alias_ai._torch, alias_ai._status)
        alias_ai._model = alias_ai._tokenizer = alias_ai._torch = None
        alias_ai._status = {'state':'not_loaded','message':'test'}
        self.env = patch.dict(os.environ, {'PLAYQUEUE_AI_ENABLED':'1','PLAYQUEUE_AI_MODEL':alias_ai.DEFAULT_MODEL})
        self.env.start()

    def tearDown(self):
        alias_ai._model, alias_ai._tokenizer, alias_ai._torch, alias_ai._status = self.saved
        self.env.stop()

    def test_json_confidence_validation(self):
        for text, expected in [('```json\n{"confidence":0.98}\n```',.98), ('{"confidence":true}',None), ('{"confidence":2}',None), ('{"confidence":"0.96"}',None), ('{"confidence":NaN}',None), ('hello',None)]:
            with self.subTest(text=text):
                self.assertEqual(alias_ai.parse_confidence(text),expected)

    def test_disabled_never_loads(self):
        with patch.dict(os.environ,{'PLAYQUEUE_AI_ENABLED':'0'}),patch.object(alias_ai,'_load_locked') as load:
            self.assertIsNone(alias_ai.score('tessa','Tessa'))
            load.assert_not_called()
            self.assertEqual(alias_ai.status()['state'],'disabled')

    def test_direct_transformers_loading_cached_and_cpu(self):
        torch, transformers = MagicMock(), MagicMock()
        with patch.dict(sys.modules,{'torch':torch,'transformers':transformers}):
            self.assertTrue(alias_ai.prepare())
            self.assertTrue(alias_ai.prepare())
        transformers.AutoModelForCausalLM.from_pretrained.assert_called_once()
        kwargs=transformers.AutoModelForCausalLM.from_pretrained.call_args.kwargs
        self.assertTrue(kwargs['use_safetensors'])
        self.assertFalse(kwargs['trust_remote_code'])
        transformers.AutoModelForCausalLM.from_pretrained.return_value.to.assert_called_with('cpu')
        torch.set_num_threads.assert_called_with(2)
        self.assertEqual(alias_ai.status()['state'],'ready')

    def test_failed_loading_falls_back_without_repeated_import(self):
        transformers=MagicMock()
        transformers.AutoTokenizer.from_pretrained.side_effect=RuntimeError('offline test')
        with patch.dict(sys.modules,{'torch':MagicMock(),'transformers':transformers}):
            self.assertIsNone(alias_ai.score('tessa','Tessa'))
            self.assertIsNone(alias_ai.score('tessa','Tessa'))
        transformers.AutoTokenizer.from_pretrained.assert_called_once()
        self.assertEqual(alias_ai.status()['state'],'error')

    def test_inference_prompt_and_json_output(self):
        tokenizer, model, torch = MagicMock(), MagicMock(), MagicMock()
        ids=MagicMock();ids.shape=(1,12)
        tokenizer.return_value={'input_ids':ids}
        tokenizer.decode.return_value='{"confidence":0.97}'
        alias_ai._model,alias_ai._tokenizer,alias_ai._torch=model,tokenizer,torch
        score=alias_ai.score('tessa','XxT3ssaxX')
        self.assertEqual(score,.97)
        messages=tokenizer.apply_chat_template.call_args.args[0]
        self.assertEqual(json.loads(messages[1]['content'])['ingame_name'],'XxT3ssaxX')
        self.assertFalse(model.generate.call_args.kwargs['do_sample'])
        self.assertEqual(model.generate.call_args.kwargs['max_new_tokens'],48)

    def test_old_ollama_tag_maps_to_direct_model(self):
        with patch.dict(os.environ,{'PLAYQUEUE_AI_MODEL':'qwen2.5:0.5b'}):
            self.assertEqual(alias_ai.model_name(),alias_ai.DEFAULT_MODEL)
