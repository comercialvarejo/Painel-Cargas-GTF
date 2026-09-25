/* Service worker do Painel de Cargas.
 *
 * O que ele faz: guarda o painel no aparelho para que o aplicativo abra rápido
 * e continue funcionando sem internet (mostrando o último conteúdo carregado).
 *
 * IMPORTANTE: sempre que você publicar uma atualização das cargas, mude o número
 * da versão abaixo (a parte "v1" do CACHE). É isso que faz o celular de todo mundo baixar a
 * versão nova em vez de continuar mostrando a antiga.
 * O script painel.py já faz isso sozinho ao atualizar os dados.
 */
// O prefixo separa este painel de qualquer outro que a conta publique no mesmo
// endereço github.io — sem isso, um apagaria o cache do outro ao ativar.
const PREFIXO = "cargas-gtf-";
const CACHE = PREFIXO + "v16";

const ARQUIVOS = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./icone-192.png",
  "./icone-512.png",
  "./icone-maskable-512.png",
  "./apple-touch-icon.png",
  "./favicon-32.png",
  "https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js",
  "https://www.gstatic.com/firebasejs/10.12.2/firebase-database-compat.js"
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      // addAll falha inteiro se um arquivo falhar; salvamos um a um para o app
      // instalar mesmo se o CDN do Firebase estiver fora do ar no momento.
      .then((c) => Promise.all(ARQUIVOS.map((u) => c.add(u).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((nomes) => Promise.all(
        // apaga só versões antigas DESTE painel, nunca o cache de outro site da conta
        nomes.filter((n) => n.startsWith(PREFIXO) && n !== CACHE).map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // O banco de status é tempo real: nunca passa pelo cache.
  if (url.hostname.endsWith("firebaseio.com") || url.hostname.endsWith("firebasedatabase.app")) return;

  // A página em si: rede primeiro, para pegar as cargas atualizadas assim que
  // houver internet; sem rede, abre a última versão guardada.
  if (req.mode === "navigate" || url.pathname.endsWith("/index.html")) {
    e.respondWith(
      fetch(req)
        .then((resp) => {
          const copia = resp.clone();
          caches.open(CACHE).then((c) => c.put("./index.html", copia));
          return resp;
        })
        .catch(() => caches.match("./index.html").then((r) => r || caches.match("./")))
    );
    return;
  }

  // Ícones, manifesto e biblioteca do Firebase: cache primeiro (mudam pouco).
  e.respondWith(
    caches.match(req).then((cache) => {
      if (cache) return cache;
      return fetch(req).then((resp) => {
        if (resp && (resp.ok || resp.type === "opaque")) {
          const copia = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copia));
        }
        return resp;
      });
    })
  );
});
