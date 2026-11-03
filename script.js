
(function(){
  // 首页顶栏：滚过首屏转成实心
  var nav = document.getElementById('nav');
  if(nav && document.body.classList.contains('home')){
    var onScroll = function(){ nav.classList.toggle('scrolled', window.scrollY > 26); };
    onScroll();
    window.addEventListener('scroll', onScroll, {passive:true});
  }
  // 按卦 / 按山 切换
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
  // 页内目录滚动高亮
  var heads = [].slice.call(document.querySelectorAll('.doc h2[id],.doc h3[id]'));
  var links = [].slice.call(document.querySelectorAll('.toc a'));
  if(heads.length && links.length){
    var map = {};
    links.forEach(function(a){ map[a.getAttribute('href').slice(1)] = a; });
    var io = new IntersectionObserver(function(es){
      es.forEach(function(e){
        if(e.isIntersecting){
          links.forEach(function(a){ a.classList.remove('on'); });
          var a = map[e.target.id]; if(a) a.classList.add('on');
        }
      });
    }, {rootMargin:'-90px 0px -70% 0px'});
    heads.forEach(function(h){ io.observe(h); });
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
