/* No admin/API caching: always use fresh server responses. */
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', function (e) {
  if (e.request.mode !== 'navigate') return;
  e.respondWith(fetch(e.request).catch(function () {
    return new Response('<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#172e47"><title>DNP Admin · Offline</title><body style="margin:0;min-height:100dvh;display:grid;place-items:center;background:radial-gradient(ellipse at 0 0,#2c5374,transparent 65%),#101b2b;color:#edf5ff;font:15px/1.7 system-ui;padding:24px;box-sizing:border-box"><main style="max-width:400px;background:#203954;border:1px solid #507a9f;border-radius:20px;padding:32px"><p style="color:#8ecaf5;font-size:11px;letter-spacing:.14em;font-weight:700">DARK NIGHT PROJEKT</p><h1 style="font-size:26px;line-height:1.3">Keine Verbindung</h1><p style="color:#bbcee4">Das Adminpanel ist gerade nicht erreichbar. Prüfe deine Verbindung und lade die Seite erneut.</p><p style="font-size:12px;color:#bbcee4">Diese Offlineansicht enthält keine Spieler- oder Verwaltungsdaten und führt keine Aufträge aus.</p><button onclick="location.reload()" style="font:inherit;background:#367fba;color:white;padding:11px 18px;border:1px solid #74b8ec;border-radius:10px;cursor:pointer">Erneut laden</button></main></body></html>',{status:503,headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}});
  }));
});
