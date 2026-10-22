/* ===========================================================
   Reeve Photography — 前端逻辑
   单一数据源：data/works.json
   路由：#/           全部
         #/c/<key>   分类
         #/work/<id> 作品详情（覆盖层）
   =========================================================== */
(function () {
  'use strict';

  var DATA_URL = 'data/works.json';

  var el = {
    gallery: document.getElementById('gallery'),
    empty: document.getElementById('empty'),
    intro: document.getElementById('intro'),
    introSub: document.getElementById('introSub'),
    introMeta: document.getElementById('introMeta'),
    sectionTitle: document.getElementById('sectionTitle'),
    nav: document.getElementById('nav'),
    menuBtn: document.getElementById('menuBtn'),
    themeBtn: document.getElementById('themeBtn'),
    header: document.getElementById('siteHeader'),
    progress: document.getElementById('headerProgress'),
    year: document.getElementById('year'),
    viewer: document.getElementById('viewer'),
    viewerStage: document.getElementById('viewerStage'),
    viewerImg: document.getElementById('viewerImg'),
    viewerInfo: document.getElementById('viewerInfo'),
    viewerTitle: document.getElementById('viewerTitle'),
    viewerCaption: document.getElementById('viewerCaption'),
    viewerDate: document.getElementById('viewerDate'),
    viewerCount: document.getElementById('viewerCount'),
    viewerClose: document.getElementById('viewerClose'),
    viewerPrev: document.getElementById('viewerPrev'),
    viewerNext: document.getElementById('viewerNext')
  };

  var state = {
    site: {},
    works: [],
    categories: [],
    authors: [],
    filtered: [],
    currentCat: 'all',
    viewing: null,     // 当前作品
    imgIndex: 0,
    ready: false
  };

  /* ---------------- 工具 ---------------- */

  function fmtDate(iso) {
    if (!iso) return '';
    var m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return String(iso);
    return m[1] + '.' + m[2] + '.' + m[3];
  }

  function catName(key) {
    for (var i = 0; i < state.categories.length; i++) {
      if (state.categories[i].key === key) return state.categories[i].name;
    }
    return key || '';
  }

  function findWork(id) {
    for (var i = 0; i < state.works.length; i++) {
      if (state.works[i].id === id) return state.works[i];
    }
    return null;
  }

  /* ---------------- 数据加载 ---------------- */

  function load() {
    return fetch(DATA_URL, { cache: 'no-cache' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(init)
      .catch(function (e) {
        console.error('[site] 作品数据加载失败：', e);
        el.gallery.innerHTML =
          '<p class="empty">作品数据加载失败（' + e.message + '）。<br>' +
          '请检查 data/works.json 是否存在且格式正确。</p>';
        el.gallery.style.display = 'block';
      });
  }

  function init(data) {
    state.site = data.site || {};
    // hidden: true 的作品不对外显示（图仍在仓库里，随时可恢复）
    state.works = (data.works || []).filter(function (w) {
      return w && !w.hidden;
    });
    state.authors = (state.site.authors || []).filter(Boolean);
    if (!state.authors.length) {
      state.works.forEach(function (w) {
        if (w.author && state.authors.indexOf(w.author) < 0) state.authors.push(w.author);
      });
    }

    // 分类：优先用数据里声明的顺序，其次自动收集
    var declared = data.categories || [];
    var seen = {};
    state.categories = declared.filter(function (c) {
      if (!c || !c.key || seen[c.key]) return false;
      seen[c.key] = 1;
      return true;
    });
    state.works.forEach(function (w) {
      if (w.category && !seen[w.category]) {
        seen[w.category] = 1;
        state.categories.push({ key: w.category, name: w.category });
      }
    });

    // 按日期倒序
    state.works.sort(function (a, b) {
      return String(b.date || '').localeCompare(String(a.date || ''));
    });

    if (state.site.subtitle) el.introSub.textContent = state.site.subtitle;
    el.introMeta.textContent =
      state.works.length + ' WORKS · ' + state.categories.length + ' SERIES';

    state.ready = true;
    buildNav();
    render();
  }

  /* ---------------- 导航 ---------------- */

  function buildNav() {
    var html = '<a class="nav-link" href="#/" data-nav="all">全部' +
      '<span class="n">' + state.works.length + '</span></a>';
    state.categories.forEach(function (c) {
      var n = state.works.filter(function (w) { return w.category === c.key; }).length;
      if (!n) return;
      html += '<a class="nav-link" href="#/c/' + encodeURIComponent(c.key) + '"' +
        ' data-nav="' + c.key + '">' + esc(c.name) +
        '<span class="n">' + n + '</span></a>';
    });
    el.nav.innerHTML = html;
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function markNav() {
    var key = state.currentCat;
    var links = el.nav.querySelectorAll('.nav-link');
    for (var i = 0; i < links.length; i++) {
      if (links[i].getAttribute('data-nav') === key) {
        links[i].setAttribute('aria-current', 'page');
      } else {
        links[i].removeAttribute('aria-current');
      }
    }
  }

  /* ---------------- 网格渲染 ---------------- */

  function render() {
    var list = state.currentCat === 'all'
      ? state.works
      : state.works.filter(function (w) { return w.category === state.currentCat; });

    state.filtered = list;
    markNav();

    if (state.currentCat === 'all') {
      el.intro.hidden = false;
      el.sectionTitle.hidden = true;
    } else {
      el.intro.hidden = true;
      el.sectionTitle.hidden = false;
      el.sectionTitle.innerHTML = esc(catName(state.currentCat)) +
        '<span class="count">' + list.length + ' 件</span>';
    }

    el.gallery.innerHTML = '';
    el.empty.hidden = list.length > 0;

    var frag = document.createDocumentFragment();
    list.forEach(function (w, i) {
      frag.appendChild(buildCard(w, i));
    });
    el.gallery.appendChild(frag);

    layout();
    observeImages();
  }

  function buildCard(w, i) {
    var a = document.createElement('a');
    a.className = 'card';
    a.href = '#/work/' + encodeURIComponent(w.id);
    a.setAttribute('data-id', w.id);
    a.setAttribute('aria-label', w.title || '作品');

    var media = document.createElement('div');
    media.className = 'card-media';

    var img = document.createElement('img');
    img.alt = w.title || '';
    img.loading = i < 6 ? 'eager' : 'lazy';
    img.decoding = 'async';
    img.src = w.thumb || (w.images && w.images[0] && (w.images[0].thumb || w.images[0].src)) || '';
    if (w.images && w.images[0]) {
      img.width = w.images[0].w || 1080;
      img.height = w.images[0].h || 1440;
    }
    img.addEventListener('load', function () { img.classList.add('loaded'); });
    if (img.complete && img.naturalWidth) img.classList.add('loaded');

    media.appendChild(img);
    a.appendChild(media);

    if (w.images && w.images.length > 1) {
      var badge = document.createElement('span');
      badge.className = 'card-badge';
      badge.textContent = w.images.length + ' 张';
      a.appendChild(badge);
    }

    var meta = document.createElement('div');
    meta.className = 'card-meta';
    meta.innerHTML = '<div class="card-title">' + esc(w.title || '无题') + '</div>' +
      '<div class="card-date">' + fmtDate(w.date) + '</div>';
    a.appendChild(meta);

    return a;
  }

  /* ---------------- 瀑布流：按图片宽高比算 grid 跨度 ---------------- */

  function layout() {
    var cards = el.gallery.children;
    if (!cards.length) return;

    var cs = getComputedStyle(el.gallery);
    var colW = parseFloat(cs.gridTemplateColumns.split(' ')[0]);
    var rowH = parseFloat(cs.gridAutoRows) || 4;
    var gap = parseFloat(cs.columnGap) || 0;
    if (!colW || isNaN(colW)) return;

    for (var i = 0; i < cards.length; i++) {
      var card = cards[i];
      var img = card.querySelector('img');
      var w = parseFloat(img.getAttribute('width')) || 3;
      var h = parseFloat(img.getAttribute('height')) || 4;
      var mediaH = colW * (h / w);
      // 卡片总高 = mediaH + 行间留白(gap)，按 rowH 取整
      var span = Math.ceil((mediaH + gap) / rowH);
      card.style.gridRowEnd = 'span ' + span;
    }
  }

  /* ---------------- 图片懒加载兜底（老浏览器） ---------------- */

  var io = null;
  function observeImages() {
    if (!('IntersectionObserver' in window)) return;
    if (!io) {
      io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (!en.isIntersecting) return;
          var img = en.target;
          img.classList.add('loaded');
          io.unobserve(img);
        });
      }, { rootMargin: '200px' });
    }
    var imgs = el.gallery.querySelectorAll('img');
    for (var i = 0; i < imgs.length; i++) io.observe(imgs[i]);
  }

  /* ---------------- 详情层 ---------------- */

  function openViewer(id) {
    var w = findWork(id);
    if (!w) return;
    state.viewing = w;
    state.imgIndex = 0;
    el.viewerInfo.style.maxWidth = '';
    el.viewer.hidden = false;
    document.body.classList.add('locked');
    fillViewer();
    el.viewerClose.focus({ preventScroll: true });
  }

  function closeViewer() {
    el.viewer.hidden = true;
    document.body.classList.remove('locked');
    state.viewing = null;
    el.viewerImg.removeAttribute('src');
  }

  function fillViewer() {
    var w = state.viewing;
    if (!w) return;
    var imgs = w.images || [];
    var cur = imgs[state.imgIndex] || {};

    el.viewerImg.classList.remove('ready');
    el.viewerImg.alt = (w.title || '') + (imgs.length > 1 ? '（' + (state.imgIndex + 1) + '）' : '');
    el.viewerImg.onload = function () {
      el.viewerImg.classList.add('ready');
      syncInfoWidth();
    };
    el.viewerImg.src = cur.src || cur.thumb || '';

    el.viewerTitle.textContent = w.title || '无题';
    el.viewerCaption.textContent = w.caption || '';
    el.viewerCaption.hidden = !w.caption;

    var meta = [];
    if (state.authors.length > 1 && w.author) meta.push(w.author);
    if (w.date) meta.push(fmtDate(w.date));
    if (w.category) meta.push(catName(w.category));
    el.viewerDate.textContent = meta.join(' · ');

    var multi = imgs.length > 1;
    el.viewerCount.textContent = multi ? (state.imgIndex + 1) + ' / ' + imgs.length : '';
    el.viewerPrev.disabled = !multi;
    el.viewerNext.disabled = !multi;
    el.viewerPrev.style.display = multi ? '' : 'none';
    el.viewerNext.style.display = multi ? '' : 'none';

    // 预加载相邻图
    if (multi) {
      [state.imgIndex + 1, state.imgIndex - 1].forEach(function (idx) {
        if (imgs[idx]) { var p = new Image(); p.src = imgs[idx].src; }
      });
    }
  }

  function syncInfoWidth() {
    var w = el.viewerImg.getBoundingClientRect().width;
    if (!w) return;
    el.viewerInfo.style.maxWidth = Math.min(Math.max(Math.round(w), 300), 720) + 'px';
  }

  function step(d) {
    var w = state.viewing;
    if (!w || !w.images || w.images.length < 2) return;
    var n = w.images.length;
    state.imgIndex = (state.imgIndex + d + n) % n;
    fillViewer();
  }

  /* ---------------- 路由 ---------------- */

  function route() {
    if (!state.ready) return;
    var hash = location.hash || '#/';

    if (hash.indexOf('#/work/') === 0) {
      var id = decodeURIComponent(hash.slice('#/work/'.length));
      if (!findWork(id)) {          // 无效 ID 静默回首页，不留下死链接
        location.replace('#/');
        return;
      }
      openViewer(id);
      return;
    }

    if (state.viewing) closeViewer();

    if (hash.indexOf('#/c/') === 0) {
      state.currentCat = decodeURIComponent(hash.slice('#/c/'.length));
    } else {
      state.currentCat = 'all';
    }
    render();
    window.scrollTo({ top: 0, behavior: 'auto' });
  }

  /* ---------------- 事件绑定 ---------------- */

  function bind() {
    window.addEventListener('hashchange', route);

    el.viewerClose.addEventListener('click', function () {
      if (history.length > 1) history.back();
      else location.hash = '#/';
    });
    el.viewerPrev.addEventListener('click', function () { step(-1); });
    el.viewerNext.addEventListener('click', function () { step(1); });

    // 点击图片区空白处关闭
    el.viewerStage.addEventListener('click', function (e) {
      if (e.target === el.viewerStage) {
        if (history.length > 1) history.back(); else location.hash = '#/';
      }
    });

    document.addEventListener('keydown', function (e) {
      if (el.viewer.hidden) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        if (history.length > 1) history.back(); else location.hash = '#/';
      } else if (e.key === 'ArrowLeft') { step(-1); }
      else if (e.key === 'ArrowRight') { step(1); }
    });

    // 触摸滑动
    var tx = 0, ty = 0, tt = 0;
    el.viewerStage.addEventListener('touchstart', function (e) {
      var t = e.changedTouches[0];
      tx = t.clientX; ty = t.clientY; tt = Date.now();
    }, { passive: true });

    el.viewerStage.addEventListener('touchend', function (e) {
      var t = e.changedTouches[0];
      var dx = t.clientX - tx, dy = t.clientY - ty;
      var dt = Date.now() - tt;
      if (dt > 800) return;
      if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy)) {
        step(dx < 0 ? 1 : -1);
      } else if (dy > 110 && Math.abs(dy) > Math.abs(dx)) {
        if (history.length > 1) history.back(); else location.hash = '#/';
      }
    }, { passive: true });

    // 主题
    el.themeBtn.addEventListener('click', function () {
      var cur = document.documentElement.getAttribute('data-theme');
      var next = cur === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('theme', next); } catch (err) {}
      var meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.setAttribute('content', next === 'dark' ? '#0d0c0b' : '#ffffff');
    });

    // 移动端菜单
    el.menuBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = el.nav.classList.toggle('is-open');
      el.menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    el.nav.addEventListener('click', function (e) {
      if (e.target.closest('a')) {
        el.nav.classList.remove('is-open');
        el.menuBtn.setAttribute('aria-expanded', 'false');
      }
    });
    document.addEventListener('click', function (e) {
      if (!el.nav.classList.contains('is-open')) return;
      if (e.target.closest('#nav') || e.target.closest('#menuBtn')) return;
      el.nav.classList.remove('is-open');
      el.menuBtn.setAttribute('aria-expanded', 'false');
    });

    // 滚动：头部状态 + 进度条
    var ticking = false;
    function onScroll() {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () {
        var y = window.scrollY || document.documentElement.scrollTop;
        el.header.classList.toggle('is-scrolled', y > 8);
        var max = document.documentElement.scrollHeight - window.innerHeight;
        el.progress.style.width = (max > 0 ? (y / max) * 100 : 0) + '%';
        ticking = false;
      });
    }
    window.addEventListener('scroll', onScroll, { passive: true });

    // 尺寸变化重算
    var rt = null;
    window.addEventListener('resize', function () {
      clearTimeout(rt);
      rt = setTimeout(function () {
        layout();
        if (!el.viewer.hidden) syncInfoWidth();
      }, 120);
    });
    if ('ResizeObserver' in window) {
      new ResizeObserver(function () { layout(); }).observe(el.gallery);
    }

    // 图片加载完成后若有高度差异再校正一次
    el.gallery.addEventListener('load', function (e) {
      if (e.target.tagName === 'IMG') layout();
    }, true);

    el.year.textContent = new Date().getFullYear();
  }

  /* ---------------- 启动 ---------------- */

  bind();
  load().then(function () { route(); });

  // 暴露给测试脚本
  window.__site = state;
})();
