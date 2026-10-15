/* Non-invasive launcher for existing Character Studio frontends. */
(function () {
  if (window.location.pathname.startsWith('/roleplay')) return;
  function render() {
    if (document.getElementById('rpplus-shortcut')) return;
    const link = document.createElement('a');
    link.id = 'rpplus-shortcut';
    link.href = '/roleplay/';
    link.title = '管理角色卡、世界书与叙事预设';
    link.textContent = '✦ 角色设定';
    link.style.cssText = 'position:fixed;top:16px;right:96px;z-index:200000;' +
      'background:#2f3945dd;color:#ffe5bc;border:1px solid #b38b5e;' +
      'border-radius:10px;padding:8px 13px;text-decoration:none;' +
      'font:13px system-ui,Microsoft YaHei,sans-serif;box-shadow:0 2px 9px #0005';
    document.body.appendChild(link);
  }
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',render);
  else render();
})();
