
(function(){
  var data = window.__VIS_DATA__;
  var svg = document.getElementById('visNet');
  var panel = document.getElementById('visPanel');
  var tip = document.getElementById('visTip');
  if(!data || !svg || !panel || !window.d3) return;
  var d3v = window.d3;
  var W = 760, H = 640, cx = 380, cy = 322;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var byId = {};
  data.nodes.forEach(function(n){ byId[n.id] = n; });
  var pos = {};
  // 内环：六条线，均布
  var lineNodes = data.nodes.filter(function(n){ return n.type === 'line'; });
  lineNodes.forEach(function(n, i){
    var a = -Math.PI / 2 + i * (2 * Math.PI / lineNodes.length);
    pos[n.id] = {x: cx + Math.cos(a) * 96, y: cy + Math.sin(a) * 96};
  });
  // 中环：五卦，起于正上，顺时针
  var guaNodes = data.nodes.filter(function(n){ return n.type === 'gua'; });
  guaNodes.forEach(function(n, i){
    var a = -Math.PI / 2 + i * (2 * Math.PI / guaNodes.length);
    pos[n.id] = {x: cx + Math.cos(a) * 208, y: cy + Math.sin(a) * 208};
  });
  // 外环：每卦的三山，围绕本卦小幅展开
  guaNodes.forEach(function(g, i){
    var ga = -Math.PI / 2 + i * (2 * Math.PI / guaNodes.length);
    var kids = data.nodes.filter(function(n){ return n.type === 'shan' && n.gua === g.name; });
    kids.forEach(function(n, j){
      var spread = (j - (kids.length - 1) / 2) * 0.34;
      var a = ga + spread;
      pos[n.id] = {x: cx + Math.cos(a) * 318, y: cy + Math.sin(a) * 318};
    });
  });

  var root = d3v.select(svg);
  var gLinks = root.append('g').attr('class', 'v-links');
  var gNodes = root.append('g').attr('class', 'v-nodes');

  gLinks.selectAll('line').data(data.links).enter().append('line')
    .attr('x1', function(l){ return pos[l.s].x; })
    .attr('y1', function(l){ return pos[l.s].y; })
    .attr('x2', function(l){ return pos[l.t].x; })
    .attr('y2', function(l){ return pos[l.t].y; })
    .attr('stroke', function(l){ return l.color; })
    .attr('class', 'v-link');

  var node = gNodes.selectAll('g').data(data.nodes).enter().append('g')
    .attr('class', function(n){ return 'v-node v-' + n.type; })
    .attr('transform', function(n){ return 'translate(' + pos[n.id].x + ',' + pos[n.id].y + ')'; })
    .attr('data-id', function(n){ return n.id; })
    .attr('tabindex', function(n){ return n.type === 'shan' || n.type === 'line' ? 0 : null; })
    .attr('role', function(n){ return n.type === 'shan' || n.type === 'line' ? 'button' : null; });

  node.each(function(n){
    var g = d3v.select(this);
    if(n.type === 'line'){
      g.append('circle').attr('r', 27).attr('class', 'v-disc')
        .style('fill', '#eef1ee').style('stroke', '#9aa3a0');
      g.append('text').attr('class', 'v-line-n').text(n.name);
      g.append('text').attr('class', 'v-line-s').attr('y', 17).text(n.label);
    } else if(n.type === 'gua'){
      g.append('circle').attr('r', 33).attr('class', 'v-disc')
        .style('fill', n.color).style('stroke', n.color);
      g.append('text').attr('class', 'v-gua-n').text(n.name);
      g.append('text').attr('class', 'v-gua-s').attr('y', 17).text(n.badge);
    } else {
      g.append('circle').attr('r', 22).attr('class', 'v-disc')
        .style('fill', '#fbfaf6').style('stroke', n.color);
      g.append('text').attr('class', 'v-shan-n').style('fill', n.color).text(n.name);
      g.append('text').attr('class', 'v-shan-s').attr('y', 15).text(n.badge);
    }
  });

  var center = gNodes.append('g').attr('class', 'v-center')
    .attr('transform', 'translate(' + cx + ',' + cy + ')');
  center.append('circle').attr('r', 46).attr('class', 'v-core');
  center.append('text').attr('class', 'v-core-t').attr('y', -4).text('六线一体');
  center.append('text').attr('class', 'v-core-s').attr('y', 15).text('点山看落点');

  function showTip(n, evt){
    if(!tip) return;
    tip.textContent = n.type === 'shan' ? (n.name + '山 · ' + n.note)
      : n.type === 'gua' ? (n.name + '卦 · ' + n.note) : (n.name + ' ' + n.label);
    tip.hidden = false;
    var box = svg.getBoundingClientRect();
    var px = (pos[n.id].x / W) * box.width + box.left;
    var py = (pos[n.id].y / H) * box.height + box.top;
    var host = svg.parentNode.getBoundingClientRect();
    tip.style.left = Math.max(8, Math.min(px - host.left, host.width - tip.offsetWidth - 8)) + 'px';
    tip.style.top = Math.max(8, py - host.top - tip.offsetHeight - 14) + 'px';
  }
  function hideTip(){ if(tip) tip.hidden = true; }

  function focus(n){
    root.classed('v-focused', true);
    var keep = {};
    keep[n.id] = 1;
    (n.type === 'gua' ? data.nodes.filter(function(x){ return x.gua === n.name; }) : []).forEach(function(x){ keep[x.id] = 1; });
    data.links.forEach(function(l){
      if(l.s === n.id || l.t === n.id || keep[l.s] || keep[l.t]) return;
    });
    node.classed('v-dim', function(x){ return !keep[x.id]; });
    gLinks.selectAll('line').classed('v-dim', function(l){ return !keep[l.s] && !keep[l.t]; });
    node.classed('v-pick', function(x){ return x.id === n.id; });
  }
  function clearFocus(){
    root.classed('v-focused', false);
    node.classed('v-dim', false).classed('v-pick', false);
    gLinks.selectAll('line').classed('v-dim', false);
  }

  function renderShan(n){
    var rows = n.targets.map(function(t){
      return '<a class="vp-row" href="' + t.href + '">'
        + '<span class="vp-n">' + t.n + '</span>'
        + '<span class="vp-body"><b>' + t.t + '</b><em>' + t.d + '</em></span>'
        + '<span class="vp-go" aria-hidden="true">→</span></a>';
    }).join('');
    panel.innerHTML = '<div class="vp-head"><span class="vp-badge" style="background:' + n.color + '">' + n.badge + '</span>'
      + '<div><h2>' + n.name + '山</h2><p>' + n.gua + '卦 · ' + n.note + '</p></div></div>'
      + '<p class="vp-label">在六条线里的落点</p><div class="vp-rows">' + rows + '</div>';
  }
  function renderGua(n){
    var kids = data.nodes.filter(function(x){ return x.type === 'shan' && x.gua === n.name; });
    var rows = kids.map(function(s){
      return '<button type="button" class="vp-row vp-btn" data-go="' + s.id + '">'
        + '<span class="vp-n" style="color:' + n.color + '">' + s.badge + '</span>'
        + '<span class="vp-body"><b>' + s.name + '山</b><em>' + s.note + '</em></span>'
        + '<span class="vp-go" aria-hidden="true">→</span></button>';
    }).join('');
    panel.innerHTML = '<div class="vp-head"><span class="vp-badge" style="background:' + n.color + '">' + n.name + '</span>'
      + '<div><h2>' + n.name + '卦 · ' + n.badge + '</h2><p>' + n.note + '　统 ' + kids.length + ' 山</p></div></div>'
      + '<p class="vp-label">这一卦统哪三山（点山看六线落点）</p><div class="vp-rows">' + rows + '</div>';
    [].slice.call(panel.querySelectorAll('[data-go]')).forEach(function(b){
      b.addEventListener('click', function(){
        var s = byId[b.getAttribute('data-go')];
        focus(s); renderShan(s);
      });
    });
  }

  // d3 v7 事件回调签名是 (event, datum)，第一个参数是事件不是数据。
  node.on('mouseenter', function(ev, n){ focus(n); showTip(n); })
      .on('mouseleave', function(){ clearFocus(); hideTip(); })
      .on('click', function(ev, n){
        if(n.type === 'shan'){ focus(n); renderShan(n); }
        else if(n.type === 'gua'){ focus(n); renderGua(n); }
        else if(n.type === 'line' && n.href){ window.location.href = n.href; }
      })
      .on('keydown', function(ev, n){
        if(ev.key === 'Enter' || ev.key === ' '){
          ev.preventDefault();
          if(n.type === 'shan'){ focus(n); renderShan(n); }
          else if(n.type === 'gua'){ focus(n); renderGua(n); }
          else if(n.href){ window.location.href = n.href; }
        }
      });
})();
