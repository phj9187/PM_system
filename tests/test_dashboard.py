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
            # 이전 단일 파일이 없으면 프로젝트 목록은 비어 있고, 새 프로젝트를 만들어 편집한다.
            self.assertEqual(json.load(client.open(base+'/api/projects')),[])
            post=lambda path,body: client.open(urllib.request.Request(base+path,json.dumps(body).encode(),
                                                                      {'Content-Type':'application/json'}))
            created=json.load(post('/api/projects',{'title':'첫 프로젝트'}))
            pid=created['id']
            self.assertEqual(created['state']['revision'],1)
            s=json.load(client.open(base+f'/api/projects/{pid}/state')); s['project']['title']='HTTP 편집'
            s['goals']=[{'id':'g','title':'목표','due':'2026-12-01','done':False,'note':''}]
            self.assertEqual(json.load(post(f'/api/projects/{pid}/state',{'state':s,'revision':1}))['revision'],2)
            with self.assertRaises(urllib.error.HTTPError) as exc:
                post(f'/api/projects/{pid}/state',{'state':s,'revision':1})
            self.assertEqual(exc.exception.code,409)
            self.assertEqual(json.load(client.open(base+f'/api/projects/{pid}/export'))['project']['title'],'HTTP 편집')
            for bad in ('missing','../x'):
                with self.assertRaises(urllib.error.HTTPError) as exc:
                    client.open(base+f'/api/projects/{bad}/state')
                self.assertEqual(exc.exception.code,404)
            json.load(post('/api/projects',{'title':'둘째'}))
            self.assertEqual([p['state']['project']['title'] for p in json.load(client.open(base+'/api/projects'))].count('HTTP 편집'),1)
            self.assertEqual(Store(self.path.parent/'projects'/f'{pid}.json').read()['goals'][0]['title'],'목표')
        finally:
            server.shutdown(); server.server_close()

    def test_legacy_single_file_becomes_first_project(self):
        store=Store(self.path); s=store.read(); s['project']['title']='이전 프로젝트'; store.save(s,0)
        from dashboard.server import Projects
        projects=Projects(self.path.parent/'projects',self.path)
        listed=projects.list()
        self.assertEqual(len(listed),1)
        self.assertEqual(listed[0]['state']['project']['title'],'이전 프로젝트')
        self.assertTrue(self.path.exists())
        # 다시 열어도 한 번만 옮긴다.
        self.assertEqual(len(Projects(self.path.parent/'projects',self.path).list()),1)
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
