// MT Indent PO alerts (26 Nov): shows a pushed alert even when the app is closed.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (x) { d = {body: e.data ? e.data.text() : ''}; }
  e.waitUntil(self.registration.showNotification(d.title || 'MT Indent', {
    body: d.body || '', tag: d.tag || undefined, renotify: !!d.tag,
    data: {url: d.url || 'https://indent-salesapp.streamlit.app/'}
  }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(self.clients.openWindow((e.notification.data || {}).url || 'https://indent-salesapp.streamlit.app/'));
});
