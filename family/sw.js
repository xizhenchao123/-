/* 鸡蛋JD2611 PWA Service Worker
   策略：外壳（页面/图标/清单）network-first + 离线回缓存；
   东财/新浪等外域行情请求直连不缓存（实时数据不许陈旧，失败由页面降级提示）。
   电脑睡眠场景：隧道进程随宿主机暂停，Cloudflare边缘对死隧道返回5xx错误页——
   页面请求遇非200也降级回缓存外壳（否则用户看到的是Cloudflare错误页而不是APP）；
   /api/spot 同理回503 JSON，页面自动降级"预置(离线)"现货徽标 */
const CACHE = 'jd2611-shell-v4';   /* v17.30: 方向层双保险+防误导提示，升版本强制全设备刷新外壳缓存（1008复盘） */
const SHELL = ['jd2611.html', 'manifest.json', 'icon-192.png', 'icon-512.png', 'icon-180.png'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function offlineJson(err) {
  return new Response('{"ok":false,"err":"' + err + '"}', { status: 503, headers: { 'Content-Type': 'application/json' } });
}

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin || e.request.method !== 'GET') return;

  if (url.pathname === '/api/spot') {
    /* 现货代理：不缓存；不可达或非200（隧道休眠时Cloudflare回错误页）都回503 JSON */
    e.respondWith(
      fetch(e.request).then(r => r.ok ? r : offlineJson('proxy ' + r.status)).catch(() => offlineJson('offline'))
    );
    return;
  }

  /* v17.28b: 子目录部署（/-/family/）也要命中外壳——按最后一段文件名比对（根路径部署同样兼容） */
  const key = url.pathname.split('/').pop() || url.pathname;
  const isShell = SHELL.includes(key);
  const isPage = e.request.mode === 'navigate' || key.endsWith('.html');
  e.respondWith(
    fetch(e.request).then(r => {
      if (r && r.ok && isShell) {
        const cp = r.clone();
        caches.open(CACHE).then(c => c.put(e.request, cp));
      }
      if (isPage && (!r || !r.ok)) {
        return caches.match(e.request, { ignoreSearch: true })
          .then(m => m || caches.match('jd2611.html'))
          .then(m => m || r);
      }
      return r;
    }).catch(() => {
      if (isPage) {
        return caches.match(e.request, { ignoreSearch: true }).then(m => m || caches.match('jd2611.html'));
      }
      return caches.match(e.request, { ignoreSearch: true }).then(m => m || Response.error());
    })
  );
});
