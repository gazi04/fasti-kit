document.body.addEventListener('htmx:configRequest', (e) => {
  const m = document.cookie.match(/(?:^|;\s*)csrf_access_token=([^;]+)/);
  if (m) e.detail.headers['X-CSRF-TOKEN'] = decodeURIComponent(m[1]);
});
