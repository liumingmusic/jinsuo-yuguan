
(function(){
  // 首页顶栏：滚过首屏转成实心
  var nav = document.getElementById('nav');
  if(nav && document.body.classList.contains('home')){
    var onScroll = function(){ nav.classList.toggle('scrolled', window.scrollY > 26); };
    onScroll();
    window.addEventListener('scroll', onScroll, {passive:true});
  }
  // 首屏「大道之术五十」题句：CSS 动画在每次新载入时自动播一遍；
  // 从别的页面按返回键回来时浏览器走 bfcache，不会重跑，这里手动重启一次。
  window.addEventListener('pageshow', function(e){
    if(!e.persisted) return;
    var mf = document.querySelector('.home .manifesto');
    if(!mf) return;
    mf.style.animation = 'none';
    void mf.offsetWidth;
    mf.style.animation = '';
  });
  // 四种读法切换（按卦 / 按山 / 按导图 / 按经文）
  var tbs = [].slice.call(document.querySelectorAll('.tab-btn'));
  if(tbs.length){
    tbs.forEach(function(b){
      b.addEventListener('click', function(){
        tbs.forEach(function(x){ x.classList.remove('on'); });
        b.classList.add('on');
        [].slice.call(document.querySelectorAll('.tab-panel')).forEach(function(p){
          p.classList.remove('on');
        });
        var t = document.getElementById('tab-' + b.getAttribute('data-tab'));
        if(t) t.classList.add('on');
      });
    });
  }
  // 全图罗盘：悬停 / 键盘聚焦读意象，已成篇的扇区由 CSS 抬起放大。
  // 触屏没有 hover，轻点未开讲的山或任一卦也能读到意象；可点的山照常进正文。
  var compass = document.querySelector('.compass');
  if(compass){
    var tip = document.getElementById('lspTip');
    var readout = document.getElementById('lspReadout');
    var targets = [].slice.call(compass.querySelectorAll('[data-tip]'));
    var defaultTip = readout ? readout.textContent : '';
    var placeTip = function(el){
      if(!tip) return;
      var cb = compass.getBoundingClientRect(), eb = el.getBoundingClientRect();
      var x = eb.left - cb.left + eb.width / 2, y = eb.top - cb.top;
      var w = tip.offsetWidth, h = tip.offsetHeight;
      tip.style.left = Math.max(6, Math.min(cb.width - w - 6, x - w / 2)) + 'px';
      tip.style.top = Math.max(6, y - h - 12) + 'px';
    };
    // 八卦悬停时要真正凸显：SVG 后画的盖前画的，卦带在绘制顺序上靠前，
    // 放大后会被相邻卦/山带压住。悬停时把该卦移到同层最后，离开时插回原位。
    // 山带本来就在卦带之后绘制，且是向外抬起，不需要提层。
    var lifted = null;
    var liftGua = function(el){
      if(!el.classList.contains('lsp-gua')) return;
      if(lifted && lifted !== el) dropGua(lifted);
      if(el.__home === undefined){
        el.__next = el.nextSibling;
        el.__home = el.parentNode;
      }
      el.__home.appendChild(el);            // 移到最后 = 画在最上层
      lifted = el;
    };
    var dropGua = function(el){
      if(!el || !el.__home) return;
      // 插回原来的后一个兄弟之前；那个兄弟若已不在就退到末尾
      if(el.__next && el.__next.parentNode === el.__home) el.__home.insertBefore(el, el.__next);
      else el.__home.appendChild(el);
      el.__home = undefined; el.__next = undefined;
      if(lifted === el) lifted = null;
    };
    var showTip = function(el){
      liftGua(el);
      var s = el.getAttribute('data-tip') || '';
      if(tip){ tip.innerHTML = '<b>意象</b>' + s; tip.hidden = false; placeTip(el); }
      if(readout) readout.textContent = s;
    };
    var hideTip = function(el){
      if(el) dropGua(el);
      else if(lifted) dropGua(lifted);
      if(tip) tip.hidden = true;
      if(readout) readout.textContent = defaultTip;
    };
    targets.forEach(function(el){
      el.addEventListener('mouseenter', function(){ showTip(el); });
      el.addEventListener('mouseleave', function(){ hideTip(el); });
      el.addEventListener('focusin', function(){ showTip(el); });
      el.addEventListener('focusout', function(){ hideTip(el); });
      if(!el.querySelector('a')){
        el.addEventListener('click', function(e){ e.preventDefault(); hideTip(el); showTip(el); });
      }
    });
    document.addEventListener('click', function(e){
      if(tip && !tip.hidden && !compass.contains(e.target)) hideTip();
    });
    if(readout && window.matchMedia && window.matchMedia('(hover: none)').matches){
      defaultTip = '卦看一段格局，山看十五度落点；轻点山或卦读一句意象。';
      readout.textContent = defaultTip;
    }
  }
  // 页内目录滚动高亮（同时把当前小节名同步到折叠条的 .toc-cur）
  var heads = [].slice.call(document.querySelectorAll('.doc h2[id],.doc h3[id]'));
  var links = [].slice.call(document.querySelectorAll('.toc a'));
  var tocCur = document.querySelector('.toc-cur');
  if(heads.length && links.length){
    if(tocCur && !tocCur.textContent) tocCur.textContent = links[0].textContent;
    var map = {};
    links.forEach(function(a){ map[a.getAttribute('href').slice(1)] = a; });
    var io = new IntersectionObserver(function(es){
      es.forEach(function(e){
        if(e.isIntersecting){
          links.forEach(function(a){ a.classList.remove('on'); });
          var a = map[e.target.id];
          if(a){
            a.classList.add('on');
            if(tocCur) tocCur.textContent = a.textContent;
          }
        }
      });
    }, {rootMargin:'-90px 0px -70% 0px'});
    heads.forEach(function(h){ io.observe(h); });
  }
  // 页内目录折叠条：点标题行开合，点条目跳转后顺手收起
  var tocBox = document.getElementById('pageToc');
  var tocBtn = document.querySelector('.toc-toggle');
  if(tocBox && tocBtn){
    tocBtn.addEventListener('click', function(){
      var open = tocBox.classList.toggle('open');
      tocBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    [].slice.call(tocBox.querySelectorAll('.toc-panel a')).forEach(function(a){
      a.addEventListener('click', function(){
        tocBox.classList.remove('open');
        tocBtn.setAttribute('aria-expanded', 'false');
      });
    });
  }
  // 首屏二十四山转盘：滚过首屏时缓慢放大并淡出（缩放走 CSS 变量 --hs）
  var wheel = document.querySelector('.hero-wheel');
  if(wheel){
    var heroBox = wheel.parentNode, ticking = false;
    var wheelTick = function(){
      var h = heroBox.offsetHeight || 1;
      var p = Math.min(1, Math.max(0, window.scrollY / h));
      wheel.style.setProperty('--hs', (1 + p * 0.26).toFixed(3));
      wheel.style.opacity = (0.92 * (1 - p * 0.92)).toFixed(3);
      ticking = false;
    };
    window.addEventListener('scroll', function(){
      if(!ticking){ ticking = true; requestAnimationFrame(wheelTick); }
    }, {passive:true});
    wheelTick();
  }
  // 移动端抽屉：≤900px 时侧栏与顶部导航都被隐藏，这里是唯一入口
  var toggle = document.getElementById('navToggle');
  var drawer = document.getElementById('drawer');
  var scrim = document.getElementById('scrim');
  var drawerClose = document.getElementById('drawerClose');
  function setDrawer(open){
    document.body.classList.toggle('drawer-open', open);
    if(toggle) toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if(drawer) drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
  }
  if(toggle){
    toggle.addEventListener('click', function(){
      setDrawer(!document.body.classList.contains('drawer-open'));
    });
  }
  if(drawerClose){ drawerClose.addEventListener('click', function(){ setDrawer(false); }); }
  if(scrim){ scrim.addEventListener('click', function(){ setDrawer(false); }); }
  document.addEventListener('keydown', function(e){ if(e.key === 'Escape') setDrawer(false); });
  if(drawer){
    [].slice.call(drawer.querySelectorAll('a')).forEach(function(a){
      a.addEventListener('click', function(){ setDrawer(false); });
    });
  }
  window.addEventListener('resize', function(){
    if(window.innerWidth > 900) setDrawer(false);
  });
  // 自检清单：点方框打勾，再点取消
  [].slice.call(document.querySelectorAll('.ck-box')).forEach(function(b){
    b.addEventListener('click', function(){
      var on = b.classList.toggle('on');
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  });
  // 宽表在窄屏要横滑：加一句提示，免得以为内容被截断
  window.addEventListener('load', function(){
    [].slice.call(document.querySelectorAll('.doc .tbl-wrap')).forEach(function(w){
      if(w.scrollWidth - w.clientWidth > 8){
        var s = document.createElement('span');
        s.className = 'tbl-scroll-hint';
        s.textContent = '← 左右滑动查看完整表格 →';
        w.parentNode.insertBefore(s, w.nextSibling);
      }
    });
  });
})();
