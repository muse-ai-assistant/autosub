// autosub web: 只缓存应用外壳，不缓存 AI 模型（模型由浏览器 Cache Storage 按 transformers.js 默认策略管理）
const CACHE = 'autosub-web-v1';
const ASSETS = ['./index.html', './manifest.json'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});
self.addEventListener('fetch', (e) => {
  // 模型和 wasm 走网络（transformers.js 自己管理缓存），只对应用文件用缓存优先
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin || !ASSETS.some((a) => url.pathname.endsWith(a.replace('./', '/')))) {
    return; // 非应用文件：直接走网络
  }
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
