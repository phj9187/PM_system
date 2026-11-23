import copy
import http.cookiejar
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from dashboard.server import Store, initial_state, start_server, validate


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'state.json'
    def tearDown(self):
        self.tmp.cleanup()
    def test_persistence_conflict_and_atomic_invalid_write(self):
        store=Store(self.path)
        s=store.read(); s['project']['title']='저장된 프로젝트'
        saved=store.save(s,0)
        self.assertEqual(Store(self.path).read(), saved)
        with self.assertRaises(RuntimeError): store.save(s,0)
        bad=copy.deepcopy(saved); bad['project']['end']='2000-01-01'
        with self.assertRaises(ValueError): store.save(bad,1)
        self.assertEqual(Store(self.path).read(), saved)
    def test_dependencies_and_import_validation(self):
        s=initial_state()
        a={'id':'a','title':'선행','start':'2026-11-01','end':'2026-11-04','owner':'',
           'status':'완료','note':'','predecessor':'','goal':''}
        b=dict(a,id='b',title='후속',start='2026-11-04',end='2026-11-06',predecessor='a')
        s['tasks']=[a,b]; validate(s)
        a['predecessor']='b'
        with self.assertRaises(ValueError): validate(s)
        a['predecessor']=''; b['start']='2026-11-02'
        with self.assertRaises(ValueError): validate(s)
        b['start']='2026-11-04'; b['goal']='missing'
        with self.assertRaises(ValueError): validate(s)
    def test_http_auth_save_export_and_restart(self):
        server=start_server(0,self.path,token='test-access')
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with self.assertRaises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(base+'/api/state')
            self.assertEqual(exc.exception.code,401)
            client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            self.assertIn('프로젝트 타임라인',client.open(base+'/?key=test-access').read().decode())
            script=client.open(base+'/app.js')
            self.assertIn('javascript',script.headers['Content-Type'])
            self.assertIn('function draw()',script.read().decode())
            # 설치형 앱 파일은 접속 키 없이 열리고, 데이터 API는 여전히 막혀 있다.
            manifest=urllib.request.urlopen(base+'/manifest.webmanifest')
            self.assertIn('manifest+json',manifest.headers['Content-Type'])
            self.assertEqual(json.load(manifest)['display'],'standalone')
            self.assertIn('serviceWorker',client.open(base+'/app.js').read().decode())
            self.assertIn("'/api/'",urllib.request.urlopen(base+'/sw.js').read().decode())
            self.assertIn('image/svg+xml',urllib.request.urlopen(base+'/icon.svg').headers['Content-Type'])
            s=json.load(client.open(base+'/api/state')); s['project']['title']='HTTP 편집'
            s['goals']=[{'id':'g','title':'목표','due':'2026-12-01','done':False,'note':''}]
            req=urllib.request.Request(base+'/api/state',json.dumps({'state':s,'revision':0}).encode(),
                                       {'Content-Type':'application/json'})
            self.assertEqual(json.load(client.open(req))['revision'],1)
            self.assertEqual(json.load(client.open(base+'/api/export'))['project']['title'],'HTTP 편집')
            self.assertEqual(Store(self.path).read()['goals'][0]['title'],'목표')
        finally:
            server.shutdown(); server.server_close()

    def test_notebook_contains_current_sources_and_no_outputs(self):
        import ast
        root=Path(__file__).resolve().parents[1]
        nb=json.loads((root/'notebooks/PM_system.ipynb').read_text(encoding='utf-8'))
        code=[c for c in nb['cells'] if c['cell_type']=='code']
        for c in code:
            self.assertEqual(c['outputs'],[])
            self.assertIsNone(c['execution_count'])
            ast.parse(''.join(c['source']))
        tree=ast.parse(''.join(code[0]['source']))
        files=next(n for n in ast.walk(tree) if isinstance(n,ast.Call)
                   and isinstance(n.func,ast.Attribute) and n.func.attr=='loads')
        sources=json.loads(ast.literal_eval(files.args[0]))
        for path,content in sources.items():
            self.assertEqual(content,(root/path).read_text(encoding='utf-8'))


if __name__=='__main__': unittest.main()
