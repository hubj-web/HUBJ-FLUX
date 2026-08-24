// Service worker mínimo - permite instalar como PWA. Não faz cache
// agressivo de dados (o app precisa sempre buscar dados atualizados do
// servidor), só o essencial pra passar na checagem de instalabilidade.
self.addEventListener('install', (event) => {
  self.skipWaiting();
});
self.addEventListener('activate', (event) => {
  self.clients.claim();
});
self.addEventListener('fetch', (event) => {
  // Sempre busca da rede - sem cache de páginas, pra nunca mostrar dado desatualizado.
  event.respondWith(fetch(event.request).catch(() => new Response('Sem conexão.', { status: 503 })));
});
