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
  const context=vm.createContext({document,location:{protocol:'file:',pathname:'/test/index.html',href:'file:///test/index.html'},
    localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
    URL,Blob,Date,structuredClone,console,crypto:require('node:crypto').webcrypto,
    setTimeout:()=>0,clearTimeout(){},confirm:()=>true,
    fetch(){throw new Error('파일 모드에서 서버에 요청하면 안 됩니다.')}});
  vm.runInContext(source,context);
  return {context,nodes,storage,run:code=>vm.runInContext(code,context)};
}

test('파일 모드에서 초기화·목표 저장·재접속·타임라인 확대가 동작한다',async()=>{
  const app=browser();await Promise.resolve();
  assert.equal(app.nodes.get('projectTitle').textContent,'새 프로젝트');
  await app.run(`(async()=>{const next=structuredClone(state);next.project.title='검증 프로젝트';
    next.goals.push({id:'g',title:'저장된 목표',due:iso(today()+5),done:false,note:''});
    next.tasks.push({id:'t',title:'첫 작업',start:iso(today()),end:iso(today()+2),status:'진행 중',owner:'테스트',note:'',goal:'g',predecessor:''});await save(next)})()`);
  assert.equal(app.nodes.get('projectTitle').textContent,'검증 프로젝트');
  assert.equal(app.nodes.get('goals').children[0].textContent,'저장된 목표');
  app.run(`openEditor('goals','g')`);
  assert.equal(app.nodes.get('editor').open,true);
  app.nodes.get('zoomIn').onclick();
  assert.equal(app.nodes.get('zoom').textContent,'140%');
  const reloaded=browser(app.storage);await Promise.resolve();
  assert.equal(reloaded.nodes.get('projectTitle').textContent,'검증 프로젝트');
  assert.equal(reloaded.run('state.tasks[0].title'),'첫 작업');
});

test('로컬 모드에서도 잘못된 일정과 동시 수정은 기존 데이터를 덮어쓰지 않는다',async()=>{
  const app=browser();await Promise.resolve();
  await assert.rejects(app.run(`save({...structuredClone(state),project:{...state.project,end:'2000-01-01'}})`));
  assert.equal(app.storage.size,0);
  await app.run('save(structuredClone(state))');
  const before=[...app.storage.values()][0];
  await assert.rejects(app.run(`request('state',{method:'POST',body:JSON.stringify({state,revision:0})})`));
  assert.equal([...app.storage.values()][0],before);
});

test('개인별 임무 창은 담당자별로 지연·진행·예정·완료 작업을 나눠 보여 준다',async()=>{
  const app=browser();await Promise.resolve();
  await app.run(`(async()=>{const next=structuredClone(state);
    next.tasks.push({id:'a',title:'지연된 일',start:iso(today()-5),end:iso(today()-1),status:'진행 중',owner:'민지',note:'',goal:'',predecessor:''});
    next.tasks.push({id:'b',title:'진행 일',start:iso(today()),end:iso(today()+2),status:'진행 중',owner:'민지',note:'메모',goal:'',predecessor:''});
    next.tasks.push({id:'c',title:'다른 사람 일',start:iso(today()),end:iso(today()+2),status:'예정',owner:'준호',note:'',goal:'',predecessor:''});
    next.tasks.push({id:'d',title:'미정 일',start:iso(today()),end:iso(today()+2),status:'완료',owner:'',note:'',goal:'',predecessor:''});
    await save(next)})()`);
  assert.equal(app.run('JSON.stringify(members())'),JSON.stringify(['민지','준호','']));
  assert.equal(app.nodes.get('member').value,'민지');
  assert.equal(app.nodes.get('mIssue').textContent,1);
  assert.equal(app.nodes.get('mDoing').textContent,1);
  assert.equal(app.nodes.get('mTodo').textContent,0);
  const groups=app.nodes.get('missionList').children;
  assert.equal(groups.length,2);
  assert.equal(groups[0].children[1].children[0].textContent,'지연된 일');
  app.nodes.get('member').value='준호';app.nodes.get('member').onchange({target:app.nodes.get('member')});
  assert.equal(app.nodes.get('mTodo').textContent,1);
  assert.equal([...app.storage.values()].includes("준호"),true);
});
