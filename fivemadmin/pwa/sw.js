/* Admin Dispatch – minimaler Service Worker.
   Bewusst KEIN Caching des Panels/der API: ein Admin-Tool braucht frische Daten,
   und Updates sollen sofort greifen. Der SW existiert für die Installierbarkeit
   und liefert nur eine simple Offline-Seite bei Verbindungsverlust. */

self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });

self.addEventListener('fetch', function (e) {
  if (e.request.mode !== 'navigate') return; // API/Assets: normal durchreichen
  e.respondWith(
    fetch(e.request).catch(function () {
      return new Response(
        '<!DOCTYPE html><html lang="de"><meta charset="utf-8">' +
        '<meta name="viewport" content="width=device-width,initial-scale=1">' +
        '<body style="background:#0E141B;color:#8FA3B8;font-family:system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center">' +
        '<div><div style="color:#E8A33D;font-size:22px;font-weight:600;letter-spacing:.1em">DNP ADMIN</div>' +
        '<p>Keine Verbindung zur Synology.<br>Netz prüfen und neu laden.</p></div></body></html>',
        { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
      );
    })
  );
});
