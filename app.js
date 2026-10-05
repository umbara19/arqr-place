// ARQR Place — pilih produk, lihat animasi 3D-nya, lalu taruh di ruangan lewat AR bawaan HP
// (iPhone: AR Quick Look memakai .usdz, Android: Scene Viewer/WebXR memakai .glb). Tanpa QR.

const viewer = document.getElementById('viewer');
const picker = document.getElementById('picker');
const details = document.querySelector('.details');
const $ = (id) => document.getElementById(id);

// Warna aksen per produk (teks di atas aksen memakai "ink")
const THEME = {
  'tiffany-setting-ring': { accent: '#81D8D0', ink: '#062623', glow: 'rgba(129,216,208,0.24)' },
  'tiffany-heart-tag': { accent: '#81D8D0', ink: '#062623', glow: 'rgba(129,216,208,0.24)' },
  'tiffany-hardwear-bracelet': { accent: '#E9C77B', ink: '#2a1d00', glow: 'rgba(233,199,123,0.22)' },
  'adidas-supernova': { accent: '#E8FF3A', ink: '#1a1d00', glow: 'rgba(232,255,58,0.18)' },
  'adidas-trionda': { accent: '#6F9BFF', ink: '#050d24', glow: 'rgba(111,155,255,0.26)' },
};

const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
let products = [];
let current = null;

async function init() {
  const data = await (await fetch('models/products.json')).json();
  products = data.products;

  for (const p of products) {
    const t = THEME[p.id] ?? THEME['tiffany-setting-ring'];
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'pick';
    b.setAttribute('role', 'listitem');
    b.dataset.id = p.id;
    b.style.setProperty('--c', t.accent);
    b.innerHTML = `
      <span class="pick-thumb"><img src="img/thumb-${p.id}.png" alt="" decoding="async" onerror="this.remove()"></span>
      <span class="pick-brand">${p.brand}</span>
      <span class="pick-name">${p.product}</span>`;
    // respons instan saat ditekan (pointerdown), ganti produk saat dilepas (click)
    b.addEventListener('click', () => select(p.id));
    picker.appendChild(b);
  }

  const fromUrl = new URLSearchParams(location.search).get('p');
  select(products.some((p) => p.id === fromUrl) ? fromUrl : products[0].id, { instant: true });
}

function select(id, { instant = false } = {}) {
  if (id === current) return;
  current = id;
  const p = products.find((x) => x.id === id);
  const t = THEME[id] ?? THEME['tiffany-setting-ring'];

  for (const b of picker.children) b.setAttribute('aria-pressed', String(b.dataset.id === id));
  // geser daftar produk secara horizontal saja (jangan menggulir seluruh halaman)
  const active = picker.querySelector(`[data-id="${id}"]`);
  if (active && picker.scrollWidth > picker.clientWidth) {
    picker.scrollTo({ left: active.offsetLeft - 16, behavior: reduceMotion || instant ? 'auto' : 'smooth' });
  }

  const root = document.documentElement.style;
  root.setProperty('--accent', t.accent);
  root.setProperty('--accent-ink', t.ink);
  root.setProperty('--glow', t.glow);
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', '#0a0b0d');

  const apply = () => {
    viewer.src = p.model;
    viewer.iosSrc = p.usdz;
    viewer.alt = `Model 3D ${p.brand} ${p.product} yang beranimasi`;
    $('brand').textContent = p.brand;
    $('product').textContent = p.product;
    $('tagline').textContent = p.tagline;
    document.title = `${p.product} · ARQR Place`;
    details.classList.remove('is-switching');
  };

  const url = new URL(location.href);
  url.searchParams.set('p', id);
  history.replaceState(null, '', url);

  if (instant || reduceMotion) { apply(); return; }
  viewer.classList.add('is-switching');
  details.classList.add('is-switching');
  setTimeout(apply, 220); // tunggu fade-out singkat, lalu ganti model
}

viewer.addEventListener('load', () => {
  viewer.classList.remove('is-switching');
  viewer.querySelector('.progress').classList.add('done');
  viewer.play({ repetitions: Infinity });
  // AR tidak tersedia di laptop → tampilkan QR untuk membuka di HP
  const canAR = viewer.canActivateAR;
  $('openOnPhone').hidden = canAR;
  $('stageHint').textContent = canAR ? 'Geser untuk memutar · cubit untuk zoom' : 'Seret untuk memutar · scroll untuk zoom';
});

viewer.addEventListener('progress', (e) => {
  const bar = viewer.querySelector('.progress');
  bar.style.setProperty('--p', `${Math.round(e.detail.totalProgress * 100)}%`);
  bar.classList.toggle('done', e.detail.totalProgress >= 1);
});

viewer.addEventListener('ar-status', (e) => {
  if (e.detail.status === 'failed') {
    $('stageHint').textContent = 'AR tidak tersedia di perangkat ini';
  }
});

init().catch((err) => {
  console.error(err);
  $('product').textContent = 'Gagal memuat data produk';
});
