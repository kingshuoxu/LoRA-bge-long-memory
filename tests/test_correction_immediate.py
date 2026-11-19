"""Confirmed correction is a durable fact, not a successful training side effect."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import torch
from memory_core.service import MemoryService, ServiceError
from memory_core.extract import expand_training_fact
from memory_core.store import atomic_write_json, read_json
from memory_core.correction_store import active_corrections


class ImmediateCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.models = Path(self.temp.name) / 'models'
        self.service = self.open_service()
        self.original = self.service.create_conversation('original')
        self.correction = self.service.create_conversation('correction elsewhere')
        self.service.convos.add_message(self.original['id'], 'user', 'Mira Chen lives in Qinglan.')
        self.service.convos.add_message(self.correction['id'], 'user', 'Mira Chen lives in Starport, not Qinglan.')
        facts = []
        for i, (attr, val, statement, question) in enumerate([
            ('where they live', 'Qinglan', 'Mira Chen lives in Qinglan.', 'Where does Mira Chen live?'),
            ("cat's name", 'Snow', "Mira Chen's cat's name is Snow.", "What is Mira Chen's cat's name?"),
        ]):
            f = expand_training_fact(dict(entity='Mira Chen', attr=attr, value=val, answer=val, statement=statement, question=question))
            f.update(id=f'expert_1000-f{i+1}', source_conversations=[self.original])
            facts.append(f)
        d = self.service.experts_dir / 'expert_1000'; d.mkdir()
        torch.save(torch.zeros(1, 8), d / 'router_key.pt')
        atomic_write_json(d/'fact_memory.json', {'facts':facts,'entities':['Mira Chen'],'sources':[self.original],'display_name':'Mira Chen'})
        atomic_write_json(d/'key_texts.json', [])
        (self.service.experts_dir/'router.jsonl').write_text(json.dumps({'expert':'expert_1000','key_path':str(d/'router_key.pt'),'batch':1000})+'\n')
        self.proposal = dict(expert='expert_1000',fact_id='expert_1000-f1',new_value='Starport',source_text='Mira Chen lives in Starport, not Qinglan.')

    def open_service(self):
        s = MemoryService(home=self.home, models_dir=self.models, use_repo_experts=False, device='cpu')
        self.addCleanup(s.convos.close)
        s.chat.ensure = Mock(side_effect=AssertionError('model must not load'))
        s.ensure_ready = Mock(side_effect=AssertionError('models not required'))
        return s

    def commit(self, fail=False):
        with patch.object(self.service, '_spawn', side_effect=OSError('cannot start') if fail else None), patch.object(self.service, 'job_status', side_effect=lambda jid:read_json(self.service.jobs_dir/jid/'status.json')):
            return self.service.commit_correction(self.proposal, self.correction['id'])

    def ask(self, service, question):
        c=service.create_conversation('fresh chat')
        return service.send_message(c['id'],question)

    def test_immediate_during_pending_failed_and_reopen(self):
        job=self.commit()
        self.assertEqual(job['status'],'running')
        with patch.object(self.service,'job_running',return_value=True):
            result=self.ask(self.service,'Where does Mira Chen live?')
            self.assertIn('Starport',result['assistant']['content'])
            self.assertNotIn('Qinglan',result['assistant']['content'])
            self.assertFalse(result['recall']['mounted'])
            self.assertIn('Snow',self.ask(self.service,"What is Mira Chen's cat's name?")['assistant']['content'])
            with self.assertRaises(ServiceError):
                self.ask(self.service,'What is the weather?')
        status=self.service.jobs_dir/job['id']/'status.json'
        atomic_write_json(status,{**job,'status':'failed','phase':'failed'})
        reopened=self.open_service()
        self.assertIn('Starport',self.ask(reopened,'Where does Mira Chen live?')['assistant']['content'])
        self.assertTrue(reopened.expert_records()[0].correction_pending)

    def test_spawn_failure_keeps_confirmed_fact_and_provenance(self):
        job=self.commit(fail=True)
        self.assertEqual(job['status'],'failed')
        row=active_corrections(self.home)[0]
        self.assertEqual(row['new_fact']['source_conversations'][0]['id'],self.correction['id'])
        self.assertEqual(row['new_fact']['original_source_conversations'][0]['id'],self.original['id'])
        self.assertIn('Starport',self.ask(self.service,'Where does Mira Chen live?')['assistant']['content'])
        with self.assertRaises(ServiceError):
            self.service.commit_correction(self.proposal,self.correction['id'])

    def test_history_error_is_not_true_previous_state(self):
        self.commit(fail=True)
        reply=self.ask(self.service,'Where did Mira Chen live previously?')['assistant']['content']
        self.assertIn('not confirmed as a past fact',reply)
        self.assertIn('Starport',reply)

    def test_explicit_previous_state_preserved(self):
        self.proposal['source_text']='Mira Chen previously lived in Qinglan and now lives in Starport.'
        self.service.convos.add_message(self.correction['id'], 'user', self.proposal['source_text'])
        self.commit(fail=True)
        reply=self.ask(self.service,'Where did Mira Chen live previously?')['assistant']['content']
        self.assertEqual(reply,'Previously Qinglan; now Starport.')

    def test_missing_adapter_still_has_authoritative_fact(self):
        self.commit(fail=True)
        (self.service.experts_dir/'expert_1000'/'router_key.pt').unlink()
        self.assertIn('Starport',self.ask(self.open_service(),'Where does Mira Chen live?')['assistant']['content'])

    def test_unknown_subject_not_intercepted(self):
        self.commit(fail=True)
        from memory_core.correction_reply import confirmed_reply
        self.assertIsNone(confirmed_reply(self.home,'Where does Elena Brooks live?',self.service.expert_records()))

    def test_chinese_pending_correction_polar_and_unrelated_fact(self):
        path=self.service.experts_dir/'expert_1000'/'fact_memory.json'
        memory=read_json(path)
        memory['entities']=['沈星河']
        memory['facts']=[
            dict(expand_training_fact(dict(entity='沈星河',attr='住址',value='青岚镇',answer='青岚镇',statement='沈星河的住址是青岚镇。',question='沈星河住在哪里？')),id='expert_1000-f1',source_conversations=[self.original]),
            dict(expand_training_fact(dict(entity='沈星河',attr='猫的名字',value='云朵',answer='云朵',statement='沈星河的猫的名字是云朵。',question='沈星河的猫叫什么？')),id='expert_1000-f2',source_conversations=[self.original]),
        ]
        atomic_write_json(path,memory)
        self.proposal.update(new_value='星港',source_text='沈星河不是住在青岚镇，是星港。')
        self.service.convos.add_message(self.correction['id'],'user',self.proposal['source_text'])
        self.commit(fail=True)
        with patch.object(self.service,'job_running',return_value=True):
            self.assertIn('星港',self.ask(self.service,'沈星河住在哪里？')['assistant']['content'])
            self.assertIn('云朵',self.ask(self.service,'沈星河的猫叫什么？')['assistant']['content'])
            self.assertIn('不是',self.ask(self.service,'沈星河是不是住在青岚镇？')['assistant']['content'])
            self.assertIn('不能据此认定',self.ask(self.service,'沈星河以前住在哪里？')['assistant']['content'])

    def test_duplicate_old_fact_from_other_expert_does_not_override(self):
        self.commit(fail=True)
        from memory_core.correction_reply import confirmed_reply
        import copy
        current=self.service.expert_records()[0]
        duplicate=copy.copy(current)
        duplicate.name='expert_old_document'
        old=read_json(current.directory/'fact_memory.json')['facts'][0]
        duplicate.fact_memory={'facts':[dict(old,id='document-old')]}
        answer=confirmed_reply(self.home,'Where does Mira Chen live?',[duplicate,current])
        self.assertIn('Starport',answer['text'])
        self.assertNotIn('Qinglan',answer['text'])

    def test_delete_after_partial_registration_removes_authority(self):
        self.commit(fail=True)
        (self.service.experts_dir/'expert_1000'/'router_key.pt').unlink()
        self.service.delete_expert('expert_1000')
        self.assertEqual(active_corrections(self.home),[])

    def test_no_extra_expert_scan_without_relevant_correction(self):
        from memory_core.correction_reply import confirmed_reply
        load=Mock(side_effect=AssertionError('no expert/tensor reads'))
        self.assertIsNone(confirmed_reply(self.home,'Where does Mira Chen live?',load))
        self.commit(fail=True)
        self.assertIsNone(confirmed_reply(self.home,'What is the weather?',load))
        self.assertIsNone(confirmed_reply(self.home,'Where does Elena Brooks live?',load))
        load.assert_not_called()

    def test_imported_old_document_cannot_override_fresh_chat_after_restart(self):
        from memory_core.documents import import_document, load_indexed_docs
        source=Path(self.temp.name)/'Mira.md'
        source.write_text('# Mira Chen\n\nMira Chen lives in Qinglan.\n',encoding='utf-8')
        import_document(self.home,source,embed=None,ask=None)
        docs=load_indexed_docs(self.home)
        self.assertTrue(docs)
        self.assertIn('Qinglan',json.dumps(docs))
        self.commit(fail=True)
        reopened=self.open_service()
        with patch.object(reopened,'_document_reply',side_effect=AssertionError('stale retrieval must not run')):
            answer=self.ask(reopened,'Where does Mira Chen live?')['assistant']['content']
        self.assertIn('Starport',answer)
        self.assertNotIn('Qinglan',answer)
        self.assertIn('Qinglan',json.dumps(load_indexed_docs(self.home)))

    def test_false_conversation_provenance_rejected(self):
        with self.assertRaises(ServiceError):
            self.service.commit_correction(self.proposal, self.original['id'])
        self.assertEqual(active_corrections(self.home), [])

    def test_editor_does_not_claim_active_chat_as_source(self):
        with patch.object(self.service, '_spawn', side_effect=OSError('offline')):
            self.service.commit_correction(self.proposal)
        fact=active_corrections(self.home)[0]['new_fact']
        self.assertEqual(fact['source_conversations'], [])
        self.assertEqual(fact['correction_source'], 'memory_editor')

    def test_process_restart_reads_ledger_without_models(self):
        self.commit(fail=True)
        import subprocess, sys
        code = """from pathlib import Path
from memory_core.service import MemoryService
from unittest.mock import Mock
s=MemoryService(home=Path(__import__('sys').argv[1]),models_dir=Path(__import__('sys').argv[2]),use_repo_experts=False,device='cpu')
s.chat.ensure=Mock(side_effect=AssertionError('no models'))
s.ensure_ready=Mock(side_effect=AssertionError('no models'))
c=s.create_conversation('process restart')
print(s.send_message(c['id'],'Where does Mira Chen live?')['assistant']['content'])
s.convos.close()
"""
        result=subprocess.run([sys.executable,'-c',code,str(self.home),str(self.models)],capture_output=True,text=True,check=True)
        self.assertIn('Starport',result.stdout)
        self.assertNotIn('Qinglan',result.stdout)

    def test_stale_bank_not_loaded(self):
        self.commit(fail=True)
        record=self.service.expert_records()[0]
        (record.directory/'fact_spans.pt').write_bytes(b'old index')
        from memory_core.fact_span import ensure_fact_bank
        with patch('memory_core.fact_span.load_fact_bank',side_effect=AssertionError('old bank')), patch('memory_core.fact_span.build_fact_bank',return_value='fresh') as build:
            self.assertEqual(ensure_fact_bank(record),'fresh')
            values=[f['value'] for f in build.call_args.args[0]]
            self.assertIn('Starport',values);self.assertNotIn('Qinglan',values)


if __name__=='__main__':unittest.main()
