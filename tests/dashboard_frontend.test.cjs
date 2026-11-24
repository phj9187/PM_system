// 파일 직접 실행 모드의 실제 앱 코드를 실행한다. 외부 패키지는 필요하지 않다.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('dashboard/app.js','utf8');

function browser(storage=new Map()){
  const nodes=new Map();
  const node=()=>({style:{},classList:{add(){},remove(){},toggle(){}},children:[],
    clientWidth:1200,scrollLeft:0,scrollTop:0,
    append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},
    addEventListener(){},showModal(){this.open=true},close(){this.open=false},
    click(){this.clicked=true},remove(){}});
  const document={getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)},
    createElement:node,querySelector:()=>node(),querySelectorAll:()=>[],body:node()};
  const context=vm.createContext({document,location:{protocol:'file:',pathname:'/test/index.html',href:'file:///test/index.html',hash:''},
    localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
    URL,Blob,Date,structuredClone,console,crypto:require('node:crypto').webcrypto,
    setTimeout:()=>0,clearTimeout(){},confirm:()=>true,
    fetch(){throw new Error('파일 모드에서 서버에 요청하면 안 됩니다.')}});
  vm.runInContext(source,context);
  const run=code=>vm.runInContext(code,context);
  // 새 프로젝트를 만들고 그 프로젝트의 처음 시작 창으로 들어간다.
  const open=async()=>{await new Promise(r=>setImmediate(r));const id=run('projects[0]?.id');if(id)await run(`go('home','${id}')`);else{await run(`createProject('새 프로젝트')`);await new Promise(r=>setImmediate(r))}};
  return {context,nodes,storage,run,open};
}


const settle=()=>new Promise(r=>setImmediate(r));

test('파일 모드에서 프로젝트 생성·목표 저장·재접속·타임라인 확대가 동작한다',async()=>{
  const app=browser();await settle();
  assert.equal(app.run('parseHash().view'),'projects');
  await app.open();
  assert.equal(app.nodes.get('projectTitle').textContent,'새 프로젝트');
  await app.run(`(async()=>{const next=structuredClone(state);next.project.title='검증 프로젝트';
    next.goals.push({id:'g',title:'저장된 목표',due:iso(today()+5),done:false,note:''});
    next.tasks.push({id:'t',title:'첫 작업',start:iso(today()),end:iso(today()+2),status:'진행 중',owner:'테스트',note:'',goal:'g',predecessor:''});await save(next)})()`);
  assert.equal(app.nodes.get('projectTitle').textContent,'검증 프로젝트');
  assert.equal(app.nodes.get('crumb').textContent,'검증 프로젝트');
  assert.equal(app.nodes.get('goals').children[0].textContent,'저장된 목표');
  app.run(`openEditor('goals','g')`);
  assert.equal(app.nodes.get('editor').open,true);
  app.nodes.get('zoomIn').onclick();
  assert.equal(app.nodes.get('zoom').textContent,'140%');
  const reloaded=browser(app.storage);await settle();
  assert.equal(reloaded.run('projects.length'),1);
  await reloaded.open();
  assert.equal(reloaded.nodes.get('projectTitle').textContent,'검증 프로젝트');
  assert.equal(reloaded.run('state.tasks[0].title'),'첫 작업');
});

test('로컬 모드에서도 잘못된 일정과 동시 수정은 기존 데이터를 덮어쓰지 않는다',async()=>{
  const app=browser();await settle();await app.open();
  const key=[...app.storage.keys()].find(k=>k.startsWith('pm-system-project:'));
  const before=app.storage.get(key);
  await assert.rejects(app.run(`save({...structuredClone(state),project:{...state.project,end:'2000-01-01'}})`));
  assert.equal(app.storage.get(key),before);
  await app.run('save(structuredClone(state))');
  const saved=app.storage.get(key);
  await assert.rejects(app.run(`request(statePath(),{method:'POST',body:JSON.stringify({state,revision:0})})`));
  assert.equal(app.storage.get(key),saved);
});

test('개인별 임무 창은 내 이름을 기본으로 담당자별 작업을 나눠 보여 준다',async()=>{
  const app=browser(new Map([['pm-system-me:/test/index.html','준호']]));await settle();await app.open();
  await app.run(`(async()=>{const next=structuredClone(state);
    next.tasks.push({id:'a',title:'지연된 일',start:iso(today()-5),end:iso(today()-1),status:'진행 중',owner:'민지',note:'',goal:'',predecessor:''});
    next.tasks.push({id:'b',title:'진행 일',start:iso(today()),end:iso(today()+2),status:'진행 중',owner:'민지',note:'메모',goal:'',predecessor:''});
    next.tasks.push({id:'c',title:'다른 사람 일',start:iso(today()),end:iso(today()+2),status:'예정',owner:'준호',note:'',goal:'',predecessor:''});
    next.tasks.push({id:'d',title:'미정 일',start:iso(today()),end:iso(today()+2),status:'완료',owner:'',note:'',goal:'',predecessor:''});
    await save(next)})()`);
  assert.equal(app.run('JSON.stringify(members())'),JSON.stringify(['민지','준호','']));
  assert.equal(app.nodes.get('member').value,'준호');
  assert.equal(app.nodes.get('mTodo').textContent,1);
  app.nodes.get('member').value='민지';app.nodes.get('member').onchange({target:app.nodes.get('member')});
  assert.equal(app.nodes.get('mIssue').textContent,1);
  assert.equal(app.nodes.get('mDoing').textContent,1);
  const groups=app.nodes.get('missionList').children;
  assert.equal(groups.length,2);
  assert.equal(groups[0].children[1].children[0].textContent,'지연된 일');
});

test('이름 변경 전 키로 저장된 브라우저 데이터는 첫 프로젝트로 옮겨진다',async()=>{
  const old=new Map([['roh'+'ang-dashboard-v1:/test/index.html',JSON.stringify({version:1,revision:3,project:{title:'이전 데이터',purpose:'',success:'',start:'2026-11-01',end:'2026-11-30'},goals:[],tasks:[],decisions:[]})]]);
  const app=browser(old);await settle();
  assert.equal(app.run('projects[0].state.project.title'),'이전 데이터');
  await app.open();
  assert.equal(app.nodes.get('projectTitle').textContent,'이전 데이터');
  await app.run('save(structuredClone(state))');
  assert.equal(app.storage.has('pm-system-project:local-1:/test/index.html'),true);
});

test('처음 시작 창은 두 하위 창의 요약과 지금 확인할 일을 보여 주고 각 창으로 이동한다',async()=>{
  const app=browser(new Map([['pm-system-me:/test/index.html','민지']]));await settle();await app.open();
  await app.run(`(async()=>{const next=structuredClone(state);
    next.tasks.push({id:'a',title:'지연된 일',start:iso(today()-5),end:iso(today()-1),status:'진행 중',owner:'민지',note:'',goal:'',predecessor:''});
    next.decisions.push({id:'d',title:'예산 결정',due:iso(today()+3),done:false,note:''});await save(next)})()`);
  assert.equal(app.run('currentView()'),'home');
  assert.equal(app.nodes.get('missionEntryTitle').textContent,'민지 님의 임무');
  const todo=app.nodes.get('homeTodo').children.map(b=>b.children[0].textContent);
  assert.equal(JSON.stringify(todo),JSON.stringify(['지연된 일','예산 결정']));
  app.nodes.get('homeTodo').children[1].onclick();
  assert.equal(app.nodes.get('editor').open,true);
  await app.nodes.get('goMissions').onclick();
  assert.match(app.run('location.hash'),/\/missions$/);
});

test('내 프로젝트 목록은 프로젝트마다 내 임무를 세고 내 작업이 있는 프로젝트를 먼저 보여 준다',async()=>{
  const app=browser(new Map([['pm-system-me:/test/index.html','민지']]));await settle();
  for(const [title,owner] of [['다른 팀 프로젝트','준호'],['내 프로젝트','민지']]){
    await app.run(`createProject(${JSON.stringify(title)})`);await settle();
    await app.run(`(async()=>{const next=structuredClone(state);
      next.tasks.push({id:'t',title:'일',start:iso(today()),end:iso(today()+2),status:'진행 중',owner:${JSON.stringify(owner)},note:'',goal:'',predecessor:''});await save(next)})()`);
  }
  await app.run(`go('projects')`);await settle();
  assert.equal(app.run('projects.length'),2);
  const cards=app.nodes.get('projectList').children;
  assert.equal(cards[0].children[1].textContent,'내 프로젝트');
  assert.equal(cards[0].children[3].children[0].children[0].textContent,'1');
  await cards[1].onclick();
  assert.equal(app.nodes.get('projectTitle').textContent,'다른 팀 프로젝트');
});

test('새 프로젝트는 이름을 받아 만들고, 같은 이름은 막으며, 프로젝트 안에서 목록으로 돌아갈 수 있다',async()=>{
  const app=browser();await settle();
  app.nodes.get('newProject').onclick();
  assert.equal(app.nodes.get('newProjectDialog').open,true);
  app.nodes.get('newProjectTitle').value='  ';
  await app.nodes.get('newProjectForm').onsubmit({preventDefault(){}});
  assert.match(app.nodes.get('newProjectError').textContent,/이름을 입력/);
  app.nodes.get('newProjectTitle').value='첫째';
  await app.nodes.get('newProjectForm').onsubmit({preventDefault(){}});
  assert.equal(app.nodes.get('projectTitle').textContent,'첫째');
  await app.nodes.get('backToProjects').onclick();
  assert.equal(app.run('parseHash().view'),'projects');
  app.nodes.get('newProject').onclick();app.nodes.get('newProjectTitle').value='첫째';
  await app.nodes.get('newProjectForm').onsubmit({preventDefault(){}});
  assert.match(app.nodes.get('newProjectError').textContent,/같은 이름/);
  app.nodes.get('newProjectTitle').value='둘째';
  await app.nodes.get('newProjectForm').onsubmit({preventDefault(){}});
  await app.nodes.get('backToProjects').onclick();
  assert.equal(app.run('projects.length'),2);
  const titles=app.nodes.get('projectList').children.map(c=>c.children[1].textContent).sort();
  assert.equal(JSON.stringify(titles),JSON.stringify(['둘째','첫째']));
  await app.nodes.get('projectList').children.find(c=>c.children[1].textContent==='둘째').onclick();
  assert.equal(app.nodes.get('projectTitle').textContent,'둘째');
});
