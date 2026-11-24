'use strict';
// 앱 화면 파일만 보관한다. 대시보드 데이터(api/)는 보관하지 않고 항상 서버에서 받는다.
const CACHE='pm-system-shell-v1';
const SHELL=['./','app.js','manifest.webmanifest','icon.svg'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).catch(()=>{}));self.skipWaiting()});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
self.addEventListener('fetch',e=>{
  const url=new URL(e.request.url);
  if(e.request.method!=='GET'||url.origin!==location.origin||url.pathname.includes('/api/')||url.search.includes('key='))return;
  // 최신 화면을 먼저 받고, 연결이 끊겼을 때만 보관한 화면을 쓴다.
  e.respondWith(fetch(e.request).then(r=>{if(r.ok){const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy))}return r}).catch(()=>caches.match(e.request,{ignoreSearch:true})));
});
