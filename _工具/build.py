#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py — 把 `内容/` 下的 Markdown 渲染成静态站点（本地双击可看，也能直接推 GitHub Pages）。

设计原则：
  1. 内容只有一份，就是 Markdown；本脚本只做渲染，绝不反向写回内容。
  2. 零运行时依赖：正文在构建时预渲染成 HTML，不靠 fetch、不靠 CDN。
  3. 脑图用 markmap（开源通用插件）在浏览器里渲染，库文件已内置 `站点/资源/vendor/`。
  4. 同一份 md 同时供 md2mind.py 导出 .xmind / .mm / .opml，三者不会走样。

用法：
  python3 _工具/build.py             # 构建到 站点/
  python3 _工具/build.py --serve     # 构建后起本地服务（默认不用，双击也能看）
"""

import os, re, sys, json, math, shutil, html, glob, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "内容")
MIND_DIR = os.path.join(ROOT, "脑图")
# 思维导图只按卦梳理：编号 00 的「九山总览」不生成页面、不进任何索引
# （md 文件保留不删；以后想放回来，把这个元组清空即可）。
MIND_HIDE_PREFIX = ("00",)
OUT_DIR = os.path.join(ROOT, "站点")
IMG_DIR = os.path.join(ROOT, "_数据", "图片")
VENDOR_SRC = os.path.join(ROOT, "_工具", "vendor")

# 三大部分的元信息：目录名 -> (编号, 标题, 短名, 主色)
SECTIONS = [
    ("Ⅰ-课程线", "Ⅰ", "课程线", "理法 · 技法 · 案例", "#2c6a7c"),
    ("Ⅱ-卦山线", "Ⅱ", "卦山线", "坎 · 坤 · 震 九山", "#8a6a3a"),
    ("Ⅲ-作业线", "Ⅲ", "作业线", "题面 · 批语 · 拆解", "#7a4a52"),
    ("附录", "附", "附录", "经文 · 技法 · 存疑", "#5a6068"),
]

# 配图占位的小罗盘图标（跟随 CSS currentColor，占位框里是金色）
FIG_ICO = (
    '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true">'
    '<circle cx="8" cy="8" r="6.1" stroke="currentColor" stroke-width="1.2"/>'
    '<path d="M8 2.1 L9.3 8 L8 13.9 L6.7 8 Z" fill="currentColor"/>'
    '<path d="M2.1 8 L8 6.7 L13.9 8 L8 9.3 Z" fill="currentColor" opacity=".38"/>'
    '<circle cx="8" cy="8" r="1.2" fill="currentColor"/></svg>'
)


# ============ Markdown 渲染 ============

def inline(t):
    """行内标记。顺序有讲究：先代码，再图片链接，再粗斜体。"""
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
               lambda m: f'<img src="{m.group(2)}" alt="{m.group(1)}" loading="lazy">', t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
    # 来源徽章：蓝＝老师口播，金＝整理者试作，灰＝待核。代码段里不包。
    parts = re.split(r"(<code>.*?</code>)", t)
    return "".join(p if p.startswith("<code>") else _src_tags(p) for p in parts)


# 来源标记 → 徽章样式类。认颜色就知道这段话是谁的话：
# src-oral 老师嘴里出的；src-draft 整理者手上写的；src-tbd 还没核实。
SRC_TAG_RULES = [
    (re.compile(r"〔(口播[^〕]*)〕"), "src-oral"),
    (re.compile(r"〔(待校[^〕]*)〕"), "src-tbd"),
    (re.compile(r"试作"), "src-draft"),
]


def _src_tags(t):
    for pat, cls in SRC_TAG_RULES:
        def _wrap(m, cls=cls):
            # 短徽章不许折行（〔口播〕这类）；长备注（>12 字）允许折行，否则 390px 会溢出
            extra = "" if len(m.group(0)) <= 12 else " src-long"
            return f'<span class="src {cls}{extra}">{m.group(0)}</span>'
        t = pat.sub(_wrap, t)
    return t


def split_row(line):
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def render_md(md, base_title=""):
    """渲染 markdown 为 HTML 片段。支持标题/段落/列表/表格/引用/代码/分隔线/图片。"""
    lines = md.split("\n")
    out = []
    i = 0
    n = len(lines)
    list_stack = []   # [(type, indent, is_checklist)]
    in_quote = False
    in_code = False
    code_buf = []
    para = []
    seen_h1 = False

    toc = []            # [(层级, 文本, 锚点)]
    used_anchor = {}

    def make_anchor(text):
        """同名的节在很多山里都会重复，必须全局去重，否则锚点会串。"""
        base = re.sub(r"[^\w\u4e00-\u9fa5]+", "-", text).strip("-") or "sec"
        n = used_anchor.get(base, 0)
        used_anchor[base] = n + 1
        return base if n == 0 else f"{base}-{n + 1}"

    def flush_para():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    def close_lists(to_indent=-1):
        nonlocal list_stack
        while list_stack and list_stack[-1][1] > to_indent:
            out.append("</li></%s>" % list_stack[-1][0])
            list_stack.pop()

    def close_quote():
        nonlocal in_quote
        if in_quote:
            flush_para()
            out.append("</blockquote>")
            in_quote = False

    while i < n:
        raw = lines[i]
        line = raw.rstrip()
        s = line.strip()

        # 代码块
        if s.startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
                code_buf = []
                in_code = False
            else:
                flush_para(); close_lists(); close_quote()
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(raw)
            i += 1
            continue

        if not s:
            flush_para(); close_lists(); close_quote()
            i += 1
            continue

        # 分隔线
        if re.fullmatch(r"[-*_]{3,}", s):
            flush_para(); close_lists(); close_quote()
            out.append("<hr>")
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush_para(); close_lists(); close_quote()
            lv = len(m.group(1))
            raw_txt = m.group(2)
            txt = inline(raw_txt)
            if lv == 1 and not seen_h1:
                # 首个 h1 由页面模板渲染成大标题
                seen_h1 = True
                i += 1
                continue
            plain = re.sub(r"[*`]", "", raw_txt).strip()
            anchor = make_anchor(raw_txt)
            if lv == 1:
                # 其后的 h1 是「章」（如 壬山 / 子山 / 癸山）
                out.append(f'<h2 class="chap" id="{anchor}">{txt}</h2>')
                toc.append((1, plain, anchor))
            else:
                out.append(f'<h{lv} id="{anchor}">{txt}</h{lv}>')
                if lv <= 3:
                    toc.append((lv, plain, anchor))
            i += 1
            continue

        # 表格
        if s.startswith("|") and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            flush_para(); close_lists(); close_quote()
            head = split_row(s)
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i].strip()))
                i += 1
            # 六列以上的表在正文栏里会挤成一字一行，加类放宽、末列不折行
            wide = len(head) >= 6
            # 窄屏是否改卡片堆叠：按内容估算自然宽度，跟列数无关。
            # 「巽4｜离9｜坤2」这种三列数字格必须留着当表格，
            # 而「句｜象｜现代转译」三列长文在 390px 下横滑读不成句，必须堆叠。
            # 估算：每列取「表头与所有单元格」的最长字数 ×13.5px + 26px 内边距，
            # 总和超过 300px（约 360px 视口下的可用宽度）就判放不下。
            colw = []
            for j in range(len(head)):
                cells_j = [head[j]] + [r[j] for r in rows if j < len(r)]
                colw.append(max((len(re.sub(r"<[^>]+>", "", inline(c)).strip())
                                 for c in cells_j), default=0))
            est = sum(w * 13.5 + 26 for w in colw)
            stack = est > 300
            t = [f'<div class="tbl-wrap{" stack" if stack else ""}">'
                 f'<table{" class=\"wide\"" if wide else ""}><thead><tr>']
            t += [f"<th>{inline(c)}</th>" for c in head]
            t.append("</tr></thead><tbody>")
            # data-label 给窄屏堆叠用（见 CSS 里的 ≤640px 分支）
            labels = [re.sub(r"<[^>]+>", "", inline(c)).strip() for c in head]
            for r in rows:
                cells = []
                for j, c in enumerate(r):
                    lb = labels[j] if j < len(labels) else ""
                    cells.append(f'<td data-label="{html.escape(lb)}">{inline(c)}</td>')
                t.append("<tr>" + "".join(cells) + "</tr>")
            t.append("</tbody></table></div>")
            out.append("".join(t))
            continue

        # 配图占位（图未画出时，文字版就是图的内容）：
        #   ![图 3-1｜子山方位示意](fig:3-1)
        #   > 画面：正北十五度扇区，两条箭头一指出龙、一指凹风，凹处注"必须补宫"
        #   > 读法：先定扇区，再跟两条箭头一进一出，缺口那侧就是要补宫的地方
        #   > 记一句：凹风从缺口进、气从缺口散，补宫补的是这个缺口
        # ｜后是图题；「> 画面/读法/记一句」三行紧随图行、不留空行。
        # 有图了把整组换成 ![说明](图片/xxx.png) 即可。
        fm = re.fullmatch(r"!\[([^\]]+)\]\(fig:([^)]*)\)", s)
        if fm:
            flush_para(); close_lists(); close_quote()
            label = fm.group(1).strip()
            fig_id = fm.group(2).strip() or label
            num, title, lead = label, "", ""
            if "｜" in label:
                num, rest = label.split("｜", 1)
                m2 = re.split(r"[:：]", rest, maxsplit=1)
                title = m2[0].strip()
                if len(m2) > 1:
                    lead = m2[1].strip()
            num = num.strip()
            rows = [("画面", lead)] if lead else []
            # 紧随其后的「> 画面：… / > 读法：… / > 记一句：…」并入本图
            j = i + 1
            while j < n:
                m3 = re.match(r"^>\s*(画面|读法|怎么看|记一句)[:：]\s*(.*)$",
                              lines[j].strip())
                if not m3:
                    break
                key = "读法" if m3.group(1) == "怎么看" else m3.group(1)
                rows.append((key, m3.group(2).strip()))
                j += 1
            i = j
            merged = []
            for k, v in rows:
                if merged and merged[-1][0] == k:
                    merged[-1] = (k, merged[-1][1] + "；" + v)
                else:
                    merged.append((k, v))
            head_txt = f"{num} · {title}" if title else num
            out.append(
                f'<figure class="fig-ph" id="fig-{html.escape(fig_id)}">'
                f'<div class="ph-frame">'
                f'<div class="ph-head"><span class="ph-ico">{FIG_ICO}</span>'
                f'<p class="ph-t">{inline(head_txt)}</p></div>'
                + ('<dl class="ph-rows">'
                   + "".join(
                       f'<div class="ph-row{" ph-key" if k == "记一句" else ""}">'
                       f'<dt>{k}</dt><dd>{inline(v)}</dd></div>'
                       for k, v in merged if v)
                   + "</dl>" if merged else "")
                + '</div><figcaption>图待补 · 先读文字版</figcaption></figure>'
            )
            continue

        # 引用块
        if s.startswith(">"):
            flush_para(); close_lists()
            if not in_quote:
                out.append("<blockquote>")
                in_quote = True
            content = s.lstrip(">").strip()
            if content:
                # 引用块内的警示标记
                cls = ""
                if content.startswith("[!WARN]") or content.startswith("⚠"):
                    cls = ' class="warn-line"'
                out.append(f"<p{cls}>{inline(content)}</p>")
            i += 1
            continue
        else:
            close_quote()

        # 列表（含任务清单 - [ ] / - [x]）
        m = re.match(r"^([ \t]*)([-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            flush_para()
            indent = len(m.group(1).replace("\t", "    "))
            ordered = m.group(2) not in "-*+"
            typ = "ol" if ordered else "ul"
            content = m.group(3)
            ck = re.match(r"^\[([ xX])\]\s+(.*)$", content)
            is_ck = ck is not None
            if ck:
                # 任务清单一律按无序表渲染，勾选框由 CSS 画，点一下能打勾
                typ = "ul"
                content = ck.group(2)
            while list_stack and list_stack[-1][1] > indent:
                out.append("</li></%s>" % list_stack.pop()[0])
            if list_stack and list_stack[-1][1] == indent and (
                    list_stack[-1][0] != typ or list_stack[-1][2] != is_ck):
                out.append("</li></%s>" % list_stack.pop()[0])
            if not list_stack or list_stack[-1][1] < indent:
                out.append('<ul class="ck-list">' if is_ck else f"<{typ}>")
                list_stack.append((typ, indent, is_ck))
            else:
                out.append("</li>")
            if is_ck:
                on = " on" if ck.group(1).lower() == "x" else ""
                out.append('<li class="ck">'
                           f'<button class="ck-box{on}" type="button" '
                           'aria-label="标为已掌握"></button>'
                           + "<span>" + inline(content) + "</span>")
            else:
                out.append("<li>" + inline(content))
            i += 1
            continue

        # 普通段落
        close_lists()
        para.append(s)
        i += 1

    flush_para()
    close_lists()
    close_quote()
    if in_code:
        out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
    return "\n".join(out), toc


# ---------- 作业与批阅状态 ----------
# 状态只有一份数据源：_数据/作业状态.json。页面上的徽标与总表看板都由它生成，
# 改完重跑 build.py 即可，不要在 md 里手写状态，否则两处会走样。

HW_DATA = os.path.join(ROOT, "_数据", "作业状态.json")


def homework_items():
    try:
        with open(HW_DATA, encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except Exception as e:
        print(f"  ⚠ 读不到 {os.path.relpath(HW_DATA, ROOT)}：{e}")
        return []


def hw_badge(it):
    """作业页顶部：这一项交没交、批没批。"""
    if not it:
        return ""
    sub_ok = it.get("submit") == "已交"
    rev_ok = it.get("review") == "已批阅"
    return (
        '<div class="hw-status">'
        '<div class="hw-cell"><span class="hw-k">作业状态</span>'
        + (f'<b class="hw-v {"ok" if sub_ok else "no"}">'
           + ("已完成" if sub_ok else "未完成") + "</b>")
        + "</div>"
        '<div class="hw-cell"><span class="hw-k">批阅状态</span>'
        + (f'<b class="hw-v {"ok" if rev_ok else "no"}">'
           + ("已批阅" if rev_ok else "未批阅") + "</b>")
        + "</div>"
        f'<div class="hw-cell grow"><span class="hw-k">备注</span>'
        f'<span class="hw-note">{inline(it.get("note", ""))}</span></div>'
        '</div>'
    )


def hw_board(items):
    """总表页：把 11 次作业的状态汇成一张看板，替代手写表格。"""
    if not items:
        return ('<div class="empty-note">还没有状态数据。建 '
                '<code>_数据/作业状态.json</code> 后重跑 build.py。</div>')
    n = len(items)
    n_sub = sum(1 for i in items if i.get("submit") == "已交")
    n_rev = sum(1 for i in items if i.get("review") == "已批阅")
    nums = [(n, "次作业"), (n_sub, "已完成"), (n_rev, "已批阅"),
            (max(0, n_sub - n_rev), "待批阅")]
    head = ('<div class="hw-nums">'
            + "".join(f'<div><b>{v}</b><em>{lab}</em></div>' for v, lab in nums)
            + "</div>")
    rows = []
    for i in items:
        sub_ok = i.get("submit") == "已交"
        rev_ok = i.get("review") == "已批阅"
        rows.append(
            "<tr>"
            f'<td class="c" data-label="次">{i["no"]}</td>'
            f'<td data-label="作业">{html.escape(i.get("title", ""))}</td>'
            f'<td class="c dim" data-label="对应讲次">{html.escape(i.get("lecture", ""))}</td>'
            f'<td class="dim" data-label="题面要求">{html.escape(i.get("req", ""))}</td>'
            f'<td class="c" data-label="作业状态"><span class="tag {"ok" if sub_ok else "no"}">'
            f'{"已完成" if sub_ok else "未完成"}</span></td>'
            f'<td class="c" data-label="批阅状态"><span class="tag {"ok" if rev_ok else "no"}">'
            f'{"已批阅" if rev_ok else "未批阅"}</span></td>'
            f'<td class="dim" data-label="备注">{html.escape(i.get("note", ""))}</td>'
            "</tr>")
    table = ('<div class="tbl-wrap hw-wrap"><table class="hw-table"><thead><tr>'
             '<th class="c">次</th><th>作业</th><th class="c">对应讲次</th>'
             '<th>题面要求</th><th class="c">作业状态</th><th class="c">批阅状态</th>'
             "<th>备注</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")
    tip = ('<p class="hw-tip">状态是活的：批阅推进后，各页徽标与本表一起更新，两处都以本表为准。</p>')
    return head + table + tip


def extract_toc(md):
    """抽取 h2/h3 做右侧页内目录。"""
    items = []
    for m in re.finditer(r"^(#{2,3})\s+(.*)$", md, re.M):
        lv = len(m.group(1))
        txt = re.sub(r"[*`]", "", m.group(2)).strip()
        anchor = re.sub(r"[^\w\u4e00-\u9fa5]+", "-", m.group(2)).strip("-")
        items.append((lv, txt, anchor))
    return items


def extract_title(md, fallback):
    m = re.search(r"^#\s+(.*)$", md, re.M)
    if m:
        return re.sub(r"[*`]", "", m.group(1)).strip()
    return fallback


# ============ 站点骨架 ============

JS = """
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
"""

THEME = os.path.join(ROOT, "_工具", "theme")


def tpl(name):
    """模板与样式放在 theme/ 下，改版式不必动脚本。"""
    with open(os.path.join(THEME, name), encoding="utf-8") as f:
        return f.read()


def fill(tmpl, **kw):
    """用 @@KEY@@ 占位替换，避开 CSS/JS 里的花括号。"""
    for k, v in kw.items():
        tmpl = tmpl.replace("@@" + k.upper() + "@@", str(v))
    return tmpl


# 八宫二十四山。顺序按顺时针，起于坎（正北）。
# status: full=已成篇 / taught=课已讲、页待补 / none=本阶段未及
ALL_GUA = [
    dict(g="坎", sz="壬子癸", fang="北", no="一白", el="水", color="#1f4f5e", studied=True,
         note="主财与肾。三山中子居中，主精气神。",
         shan=[("壬", "财富能力 · 财商", "full"),
               ("子", "财库 · 家运", "full"),
               ("癸", "理财 · 主阴", "full")]),
    dict(g="艮", sz="丑艮寅", fang="东北", no="八白", el="土", color="#6d6a46", studied=False,
         note="少男、山与止。", shan=None),
    dict(g="震", sz="甲卯乙", fang="东", no="三碧", el="木", color="#3f6b52", studied=True,
         note="主长男与奋起。三山中卯居中，主肝。",
         shan=[("甲", "行动力 · 长房", "full"),
               ("卯", "人脉 · 桃花", "full"),
               ("乙", "文昌 · 自处", "full")]),
    dict(g="巽", sz="辰巽巳", fang="东南", no="四绿", el="木", color="#3b6b66", studied=False,
         note="长女、风与入。", shan=None),
    dict(g="离", sz="丙午丁", fang="南", no="九紫", el="火", color="#8a4436", studied=False,
         note="中女、火与明。", shan=None),
    dict(g="坤", sz="未坤申", fang="西南", no="二黑", el="土", color="#8a6a3a", studied=True,
         note="主母与田土。三山中坤居中，主脾胃与妇科。",
         shan=[("未", "利润 · 副业", "full"),
               ("坤", "家运 · 妇科", "full"),
               ("申", "链接 · 文昌", "full")]),
    dict(g="兑", sz="庚酉辛", fang="西", no="七赤", el="金", color="#6b6257", studied=False,
         note="少女、泽与口。", shan=None),
    dict(g="乾", sz="戌乾亥", fang="西北", no="六白", el="金", color="#48525a", studied=False,
         note="父、天与刚。", shan=None),
]

# 每山在罗盘上的角度：子＝0°，顺时针递增，一山 15°
def mountains():
    out = []
    for gi, g in enumerate(ALL_GUA):
        sz = g["sz"]
        for i in range(3):
            label, st = (g["shan"][i][1], g["shan"][i][2]) if g["shan"] else ("", "none")
            out.append(dict(name=sz[i], gua=g, gi=gi, idx=i, label=label, st=st,
                            deg=gi * 45 - 22.5 + 7.5 + i * 15))
    return out


STAT_LABEL = {"full": "已成篇", "taught": "待补", "none": "未及"}


def build_nav(current=""):
    """顶栏导航：三部分 + 思维导图。"""
    parts = []
    for d, num, short, desc, color in SECTIONS:
        on = " on" if d == current else ""
        parts.append(f'<a class="{on.strip()}" href="section-{num}.html">{num} {short}</a>')
    on = " on" if current == "__mind__" else ""
    parts.append(f'<a class="{on.strip()}" href="mind-index.html">思维导图</a>')
    return "".join(parts)


def mind_files():
    """参与构建的脑图文件：只按卦梳理，编号 00 的总览图隐藏（文件保留不删）。"""
    if not os.path.isdir(MIND_DIR):
        return []
    return sorted(f for f in os.listdir(MIND_DIR)
                  if f.endswith(".md") and not f.startswith(MIND_HIDE_PREFIX))


def mind_file_count():
    """脑图张数：只数要展示的（总览已隐藏），别再手写「五张」这种会过期的字。"""
    return len(mind_files())


def build_drawer(current="", sub=""):
    """移动端抽屉导航。桌面隐藏，≤900px 由汉堡键拉出。

    侧栏在窄屏被隐藏，若不另给入口，手机上除了当前页哪都去不了——这是
    2026-11-03 用户反馈「作业线、卦山线都看不到」的直接原因。
    """
    items = []
    for d, num, short, desc, color in SECTIONS:
        on = " on" if d == current else ""
        items.append(
            f'<li><a class="d-line{on}" href="section-{num}.html" style="--c:{color}">'
            f'<b>{num}</b><span class="d-t">{short}<em>{desc}</em></span></a></li>'
        )
    on_home = " on" if current == "__home__" else ""
    return (
        '<div class="drawer" id="drawer" aria-hidden="true" aria-label="站点导航">'
        '<div class="drawer-head">'
        '<a class="logo" href="index.html"><span class="mark">'
        '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true">'
        '<circle cx="8" cy="8" r="6.1" stroke="currentColor" stroke-width="1.2"/>'
        '<path d="M8 2.1 L9.3 8 L8 13.9 L6.7 8 Z" fill="currentColor"/>'
        '<path d="M2.1 8 L8 6.7 L13.9 8 L8 9.3 Z" fill="currentColor" opacity=".38"/>'
        '<circle cx="8" cy="8" r="1.2" fill="var(--gold-2)"/>'
        '</svg></span>金锁玉关</a>'
        '<button class="drawer-close" id="drawerClose" type="button" aria-label="关闭导航">'
        '&times;</button>'
        '</div>'
        '<div class="drawer-body">'
        f'<a class="d-home{on_home}" href="index.html"><span>总览 · 二十四山全图</span>'
        '<em>首页</em></a>'
        '<p class="side-title">四 条 线</p>'
        '<ul class="d-lines">' + "".join(items) + '</ul>'
        + sub +
        '<p class="side-title">图</p>'
        f'<a class="d-home" href="mind-index.html"><span>思维导图</span>'
        f'<em>{mind_file_count()} 张</em></a>'
        '</div></div>'
    )


def drawer_sub(items, active_file=""):
    """抽屉里的「本节」页面列表。"""
    if not items:
        return ""
    lis = "".join(
        f'<li><a class="{"on" if it["file"] == active_file else ""}" '
        f'href="{it["slug"]}.html"><span class="n">{it["order"]:02d}</span>'
        f'<span>{html.escape(it["title"])}</span></a></li>'
        for it in items
    )
    return f'<p class="side-title">本 节</p><ul class="d-sub">{lis}</ul>'


def foot_sections():
    out = "".join(
        f'<a href="section-{num}.html">{num} {short}</a>' for d, num, short, desc, color in SECTIONS
    )
    return out + '<a href="mind-index.html">思维导图</a>'


def extract_lead(md, fallback=""):
    """取卡片导语：优先正文第一段引用，没有就退回第一段正文，再没有才用文件名。"""
    lines = [l.strip() for l in md.split("\n")]
    for line in lines:
        t = line
        if not t.startswith(">"):
            continue
        t = t.lstrip("> ").strip()
        t = re.sub(r"^\*\*[^*]+\*\*[:：]\s*", "", t)
        t = re.sub(r"^一句话[:：]\s*", "", t)
        t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
        t = re.sub(r"[*`]", "", t)
        if len(t) >= 10:
            return t[:78] + ("…" if len(t) > 78 else "")
    # 没有引用块的页面（如附录），退到第一段正文
    for t in lines:
        if not t or t.startswith(("#", "|", "-", "*", "!", ">", "```")):
            continue
        t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
        t = re.sub(r"[*`]", "", t)
        if len(t) >= 12:
            return t[:78] + ("…" if len(t) > 78 else "")
    return fallback


def collect_pages():
    """扫描 内容/ 目录，返回页面元信息列表。"""
    pages = []
    for d, num, short, desc, color in SECTIONS:
        p = os.path.join(SRC_DIR, d)
        if not os.path.isdir(p):
            continue
        files = sorted([f for f in os.listdir(p) if f.endswith(".md")])
        for idx, f in enumerate(files, 1):
            fp = os.path.join(p, f)
            md = open(fp, encoding="utf-8").read()
            title = extract_title(md, os.path.splitext(f)[0])
            pages.append({
                "section": d, "num": num, "short": short, "color": color,
                "file": f, "path": fp, "title": title, "order": idx,
                "slug": f"{num}-{idx:02d}-" + re.sub(r"\s+", "", os.path.splitext(f)[0]),
                "lead": extract_lead(md),
            })
    return pages


def build():
    if not os.path.isdir(SRC_DIR):
        print("找不到 内容/ 目录")
        return

    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)
    os.makedirs(os.path.join(OUT_DIR, "资源", "vendor"), exist_ok=True)

    # 样式与脚本
    open(os.path.join(OUT_DIR, "style.css"), "w", encoding="utf-8").write(tpl("style.css"))
    open(os.path.join(OUT_DIR, "script.js"), "w", encoding="utf-8").write(JS)
    for f in ("d3.js", "markmap-view.js", "markmap-lib.js"):
        s = os.path.join(VENDOR_SRC, f)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(OUT_DIR, "资源", "vendor", f))
        else:
            print(f"  ⚠ 缺少 vendor/{f}，脑图将无法渲染")

    # 图片：只复制正文真正引用到的
    used = set()
    for base in (SRC_DIR, MIND_DIR):
        if not os.path.isdir(base):
            continue
        for f in glob.glob(os.path.join(base, "**", "*.md"), recursive=True):
            for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", open(f, encoding="utf-8").read()):
                if m.group(1).startswith("fig:"):
                    continue      # 占位图不指向真实文件
                used.add(os.path.basename(m.group(1)))
    if used and os.path.isdir(IMG_DIR):
        os.makedirs(os.path.join(OUT_DIR, "图片"), exist_ok=True)
        for name in used:
            src = os.path.join(IMG_DIR, name)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(OUT_DIR, "图片", name))
            else:
                print(f"  ⚠ 引用了不存在的图片：{name}")
    if used:
        print(f"  复制图片 {len(used)} 张")

    pages = collect_pages()
    if not pages:
        print("内容/ 下没有 md 文件")
        return

    PAGE_TMPL = tpl("page.html")
    HW_ITEMS = homework_items()

    for idx, pg in enumerate(pages):
        md = open(pg["path"], encoding="utf-8").read()
        body_html, toc_items = render_md(md)
        body_html = re.sub(r'(src=")[^"]*?/(?:图片)/', r'\1图片/', body_html)
        body_html = re.sub(r'(src=")_数据/图片/', r'\1图片/', body_html)

        # 作业线：状态只有一份数据源，页顶徽标与总表看板都从它生成
        if pg["section"] == "Ⅲ-作业线":
            if pg["order"] == 1:
                body_html = body_html.replace("<p>@@HOMEWORK_BOARD@@</p>",
                                              hw_board(HW_ITEMS))
            else:
                k = pg["order"] - 2
                body_html = hw_badge(HW_ITEMS[k] if 0 <= k < len(HW_ITEMS) else None) + body_html

        toc_html = "".join(
            f'<a class="lv{lv}" href="#{a}" title="{t}">{t}</a>' for lv, t, a in toc_items
        )
        toc_block = ""
        if toc_items:
            # 移动端「本页目录」折叠条：默认只露一行钮（标题 + 当前小节 + 箭头），
            # 点开才是竖列表；桌面端 .toc-toggle 隐藏、显示 .toc-title，仍是右侧竖栏。
            toc_block = ('<aside class="toc" id="pageToc">'
                         '<p class="toc-title">本 页 目 录</p>'
                         '<button class="toc-toggle" type="button" aria-expanded="false" aria-controls="tocPanel">'
                         '<span class="toc-t">本页目录</span>'
                         '<span class="toc-cur"></span>'
                         '<svg class="toc-chev" viewBox="0 0 10 6" aria-hidden="true">'
                         '<path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" '
                         'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
                         '</button>'
                         '<div class="toc-panel" id="tocPanel">'
                         + toc_html + '</div></aside>')

        # 左栏：本节 + 全站
        same = [q for q in pages if q["section"] == pg["section"]]
        side = [f'<div class="side-group"><p class="side-title">{pg["num"]} {pg["short"]}</p><ul>']
        for q in same:
            on = " on" if q["file"] == pg["file"] else ""
            side.append(
                f'<li><a class="{on.strip()}" href="{q["slug"]}.html">'
                f'<span class="n">{q["order"]:02d}</span><span>{q["title"]}</span></a></li>'
            )
        side.append("</ul></div>")
        side.append('<div class="side-group"><p class="side-title">全部内容</p><ul>')
        for d, num, short, desc, color in SECTIONS:
            if d == pg["section"]:
                continue
            side.append(f'<li><a href="section-{num}.html"><span class="n">{num}</span>'
                        f'<span>{short}</span></a></li>')
        side.append('<li><a href="mind-index.html"><span class="n">图</span><span>思维导图</span></a></li>')
        side.append("</ul></div>")

        # 上下页
        prev_p = pages[idx - 1] if idx > 0 else None
        next_p = pages[idx + 1] if idx + 1 < len(pages) else None
        pager = ""
        pager += (f'<a href="{prev_p["slug"]}.html"><span class="dir">← 上一节</span>'
                  f'<span class="ttl">{html.escape(prev_p["title"])}</span></a>' if prev_p
                  else '<span class="empty"></span>')
        pager += (f'<a class="next" href="{next_p["slug"]}.html"><span class="dir">下一节 →</span>'
                  f'<span class="ttl">{html.escape(next_p["title"])}</span></a>' if next_p
                  else '<span class="empty"></span>')

        sec_desc = next((x[3] for x in SECTIONS if x[0] == pg["section"]), "")
        subtitle = f'{pg["num"]} {pg["short"]}　·　{sec_desc}'
        crumb = (f'<a href="index.html">总览</a><span class="sep">/</span>'
                 f'<a href="section-{pg["num"]}.html">{pg["num"]} {pg["short"]}</a>')

        html_out = fill(PAGE_TMPL,
                        title=html.escape(pg["title"]),
                        nav=build_nav(pg["section"]),
                        side="".join(side),
                        crumb=crumb,
                        subtitle=html.escape(subtitle),
                        body=body_html,
                        toc_block=toc_block,
                        layout_class="",
                        pager=pager,
                        foot_line=f'{pg["num"]} {pg["short"]}',
                        foot_pos=f'第 {pg["order"]} 篇 · 本节共 {len(same)} 篇',
                        foot_sections=foot_sections(),
                        drawer=build_drawer(pg["section"], drawer_sub(same, pg["file"])),
                        )
        open(os.path.join(OUT_DIR, pg["slug"] + ".html"), "w", encoding="utf-8").write(html_out)

    # 章节索引页
    for d, num, short, desc, color in SECTIONS:
        items = [p for p in pages if p["section"] == d]
        cards = "".join(
            f'<a class="card" href="{p["slug"]}.html">'
            f'<div class="k">{num} · {p["order"]:02d}</div>'
            f'<h3>{html.escape(p["title"])}</h3>'
            f'<p>{html.escape(p["lead"] or os.path.splitext(p["file"])[0])}</p></a>'
            for p in items
        )
        body = (f'<div class="cards">{cards}</div>' if cards
                else '<div class="empty-note">本节内容尚未开始整理。等课程推进或笔记补全后，这里会自动出现条目。</div>')
        page = fill(PAGE_TMPL,
                    title=f"{num} {short}",
                    nav=build_nav(d),
                    side='<div class="side-group"><p class="side-title">全部内容</p><ul>' + "".join(
                        f'<li><a class="{"on" if s[0] == d else ""}" href="section-{s[1]}.html">'
                        f'<span class="n">{s[1]}</span><span>{s[2]}</span></a></li>' for s in SECTIONS
                    ) + '<li><a href="mind-index.html"><span class="n">图</span>'
                        '<span>思维导图</span></a></li>'
                        '<li><a href="index.html"><span class="n">首</span>'
                        '<span>返回首页</span></a></li></ul></div>',
                    crumb='<a href="index.html">总览</a>',
                    subtitle=html.escape(desc),
                    body=body,
                    toc_block="",
                    layout_class=" two",
                    pager='<span class="empty"></span>',
                    foot_line=f"{num} {short}",
                    foot_pos=f"本节共 {len(items)} 篇",
                    foot_sections=foot_sections(),
                    drawer=build_drawer(d, drawer_sub(items)),
                    )
        open(os.path.join(OUT_DIR, f"section-{num}.html"), "w", encoding="utf-8").write(page)

    # 脑图
    mind_pages = build_minds(pages)

    # 首页
    build_index(pages, mind_pages)

    print(f"\n构建完成：{len(pages)} 页正文 + {len(mind_pages)} 张脑图 -> {os.path.relpath(OUT_DIR, ROOT)}/")
    return pages, mind_pages


def mind_side(no, pages):
    """思维导图页的左侧栏：全部内容树 + 对照正文跳转。

    和 section/正文页同一套侧栏体例——此前导图页是全站唯一没有侧栏的
    两类页面，版式与其他内容页不一致（2026-11-03 用户反馈）。
    """
    tree = ('<div class="side-group"><p class="side-title">全部内容</p><ul>' + "".join(
        f'<li><a class="{"on" if s[0] == "__mind__" else ""}" href="section-{s[1]}.html">'
        f'<span class="n">{s[1]}</span><span>{s[2]}</span></a></li>' for s in SECTIONS
    ) + '<li><a class="on" href="mind-index.html"><span class="n">图</span>'
        '<span>思维导图</span></a></li>'
        '<li><a href="index.html"><span class="n">首</span>'
        '<span>返回首页</span></a></li></ul></div>')
    cross = ""
    for pg in pages:
        # 脑图文件编号 01/02/03 ↔ 卦山线同序号正文页（slug 形如 Ⅱ-01-01坎卦壬子癸）
        if pg["section"] == "Ⅱ-卦山线" and no and pg["slug"].startswith("Ⅱ-" + no.zfill(2) + "-"):
            cross = ('<div class="side-group"><p class="side-title">对照正文</p><ul>'
                     f'<li><a href="{pg["slug"]}.html"><span class="n">Ⅱ</span>'
                     f'<span>{html.escape(pg["title"])}</span></a></li>'
                     '</ul><p class="side-tip">图按层级收拢，正文按条目铺开，同一份内容。</p></div>')
            break
    return tree + cross


def build_minds(pages):
    """把 脑图/*.md 渲染成 markmap 页面。"""
    made = []
    if not os.path.isdir(MIND_DIR):
        return made
    MIND_TMPL = tpl("mind.html")
    files = mind_files()
    for f in files:
        p = os.path.join(MIND_DIR, f)
        md = open(p, encoding="utf-8").read()
        title = extract_title(md, os.path.splitext(f)[0])
        slug = "mind-" + os.path.splitext(f)[0].replace(" ", "-")
        nodes = sum(1 for l in md.split("\n") if re.match(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s)", l))
        m = re.match(r"^(\d+)", f)
        page = (MIND_TMPL
                .replace("@@TITLE@@", html.escape(title))
                .replace("@@SUBTITLE@@", f"共 {nodes} 个节点")
                .replace("@@NODES@@", str(nodes))
                .replace("@@NAV@@", build_nav("__mind__"))
                .replace("@@SIDE@@", mind_side(m.group(1) if m else "", pages))
                .replace("@@LAYOUT_CLASS@@", " two")
                .replace("@@MD@@", html.escape(md))
                .replace("@@FOOT_SECTIONS@@", foot_sections())
                .replace("@@DRAWER@@", build_drawer("__mind__"))
                .replace("@@MIND_NOTE@@", ""))
        open(os.path.join(OUT_DIR, slug + ".html"), "w", encoding="utf-8").write(page)
        made.append({"title": title, "slug": slug, "file": f, "nodes": nodes,
                     "no": m.group(1) if m else ""})
    return made


# ---------- 二十四山罗盘 ----------

def _polar(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.sin(a), cy - r * math.cos(a)


def _sector(cx, cy, r1, r2, a1, a2):
    x1, y1 = _polar(cx, cy, r2, a1)
    x2, y2 = _polar(cx, cy, r2, a2)
    x3, y3 = _polar(cx, cy, r1, a2)
    x4, y4 = _polar(cx, cy, r1, a1)
    lg = 1 if a2 - a1 > 180 else 0
    return (f"M{x1:.2f} {y1:.2f}A{r2:.2f} {r2:.2f} 0 {lg} 1 {x2:.2f} {y2:.2f}"
            f"L{x3:.2f} {y3:.2f}A{r1:.2f} {r1:.2f} 0 {lg} 0 {x4:.2f} {y4:.2f}Z")


# 后天八卦方位：上南下北、左东右西。
# 内部角度仍按「子＝0°、顺时针」算，绘制时统一加 180° 转到屏上，
# 字不跟着转（单字倒过来不好认），于是乾卦自然落在右下角。
ROT = 180.0


def _compass(full_slug):
    """二十四山罗盘（后天八卦，上南下北）。卦带 45°，山带 15°，单字直立不旋转。"""
    cx = cy = 380.0
    R_OUT, R_MID, R_IN = 338.0, 270.0, 208.0
    o = ['<svg class="lsp" viewBox="0 0 760 760" role="img" '
         'aria-label="二十四山罗盘：后天八卦方位，上南下北，八宫各统三山">']

    # 盘底与刻度环
    o.append(f'<circle cx="{cx}" cy="{cy}" r="{R_OUT}" fill="#fbfaf5"/>')
    o.append(f'<circle cx="{cx}" cy="{cy}" r="{R_OUT + 9}" fill="none" '
             f'stroke="#eae7dc" stroke-width="1"/>')
    for deg in range(0, 360, 5):
        r1 = R_OUT + (2 if deg % 15 == 0 else 5)
        x1, y1 = _polar(cx, cy, r1, deg)
        x2, y2 = _polar(cx, cy, R_OUT + 8, deg)
        o.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                 f'stroke="#d8d4c6" stroke-width=".8"/>')

    # 四正：上南、下北、左东、右西
    for lab, ang in (("南", 0), ("西", 90), ("北", 180), ("东", 270)):
        lx, ly = _polar(cx, cy, R_OUT + 24, ang)
        o.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                 f'dominant-baseline="central" font-family="Songti SC,serif" '
                 f'font-size="14" fill="#a67c3d" opacity=".9">{lab}</text>')

    # 八卦带
    for gi, g in enumerate(ALL_GUA):
        a1 = gi * 45 - 22.5 + ROT
        d = _sector(cx, cy, R_IN, R_MID, a1, a1 + 45)
        if g["studied"]:
            o.append(f'<path d="{d}" fill="{g["color"]}" fill-opacity=".13" '
                     f'stroke="#e4e0d4" stroke-width=".9"/>')
        else:
            o.append(f'<path d="{d}" fill="#fbfaf6" stroke="#ece9df" stroke-width=".9"/>')
        ga, gr = a1 + 22.5, (R_IN + R_MID) / 2 + 8
        gx, gy = _polar(cx, cy, gr, ga)
        gc = g["color"] if g["studied"] else "#b8b09f"
        o.append(f'<text x="{gx:.1f}" y="{gy:.1f}" text-anchor="middle" '
                 f'dominant-baseline="central" font-family="Songti SC,serif" '
                 f'font-size="26" fill="{gc}">{g["g"]}</text>')

    # 二十四山带
    for m in mountains():
        a1 = m["deg"] - 7.5 + ROT
        d = _sector(cx, cy, R_MID, R_OUT, a1, a1 + 15)
        st, col = m["st"], m["gua"]["color"]
        if st == "full":
            fill = f'fill="{col}" fill-opacity="1"'
            tcol, tw = "#ffffff", ' font-weight="600"'
        elif st == "taught":
            fill = f'fill="{col}" fill-opacity=".20"'
            tcol, tw = col, ""
        else:
            fill = 'fill="#ffffff"'
            tcol, tw = "#a8a191", ""
        o.append(f'<path d="{d}" {fill} stroke="#e5e1d4" stroke-width=".9"/>')
        tx, ty = _polar(cx, cy, (R_MID + R_OUT) / 2, m["deg"] + ROT)
        txt = (f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="middle" '
               f'dominant-baseline="central" font-family="Songti SC,serif" '
               f'font-size="21" fill="{tcol}"{tw}>{m["name"]}</text>')
        if st == "full":
            o.append(f'<a href="{full_slug}.html" class="mnt-link">'
                     f'<title>{m["name"]}山 · {m["label"]}</title>{txt}</a>')
        else:
            o.append(txt)

    # 内芯
    o.append('<radialGradient id="coreg" cx="50%" cy="42%" r="62%">'
             '<stop offset="0%" stop-color="#ffffff"/>'
             '<stop offset="100%" stop-color="#f8f7f1"/></radialGradient>')
    o.append(f'<circle cx="{cx}" cy="{cy}" r="{R_IN}" fill="url(#coreg)" '
             f'stroke="#e6e3d8" stroke-width="1"/>')
    o.append(f'<circle cx="{cx}" cy="{cy}" r="{R_IN - 16}" fill="none" '
             f'stroke="#efece3" stroke-width="1"/>')
    o.append('<text x="380" y="316" text-anchor="middle" font-size="11.5" '
             'letter-spacing="6" fill="#b3ada0" font-family="PingFang SC,sans-serif">八 宫</text>')
    o.append('<text x="380" y="368" text-anchor="middle" font-family="Songti SC,serif" '
             'font-size="44" letter-spacing="3" fill="#12181b">二十四山</text>')
    o.append('<text x="380" y="404" text-anchor="middle" font-size="12.5" '
             'letter-spacing="1.5" fill="#8a9499" font-family="PingFang SC,sans-serif">每山十五度</text>')
    o.append('<line x1="330" y1="424" x2="430" y2="424" stroke="#e4ddca" stroke-width="1"/>')
    o.append('<text x="380" y="446" text-anchor="middle" font-size="12.5" '
             'letter-spacing="3" fill="#a67c3d" font-family="PingFang SC,sans-serif">'
             '坎 · 坤 · 震 已开讲</text>')
    o.append("</svg>")
    return "".join(o)


def _hero_wheel():
    """首屏背景：二十四山转盘。纯装饰，不可交互，不抢标题。

    三环各走各的速：外环（二十四山）240s 顺行，内环（八卦）360s 逆行，
    最外刻度 520s 逆行；光晕 11s 呼吸一次。缩放由 script.js 按滚动位置调 --hs。
    """
    cx = cy = 400.0
    R_LAB, R_OUT, R_MID, R_IN = 334.0, 374.0, 300.0, 262.0
    o = ['<svg viewBox="0 0 800 800" role="presentation">']

    # 光晕
    o.append('<defs>'
             '<radialGradient id="hw-halo" cx="50%" cy="50%" r="50%">'
             '<stop offset="0%" stop-color="#2c6a7c" stop-opacity=".55"/>'
             '<stop offset="46%" stop-color="#2c6a7c" stop-opacity=".16"/>'
             '<stop offset="100%" stop-color="#2c6a7c" stop-opacity="0"/>'
             '</radialGradient>'
             '<radialGradient id="hw-core" cx="50%" cy="50%" r="50%">'
             '<stop offset="0%" stop-color="#c9a86a" stop-opacity=".30"/>'
             '<stop offset="100%" stop-color="#c9a86a" stop-opacity="0"/>'
             '</radialGradient>'
             '</defs>')
    o.append(f'<g class="w-halo"><circle cx="{cx}" cy="{cy}" r="392" fill="url(#hw-halo)"/>'
             f'<circle cx="{cx}" cy="{cy}" r="150" fill="url(#hw-core)"/></g>')

    # 最外刻度环
    ticks = ['<g class="w-ring">']
    ticks.append(f'<circle cx="{cx}" cy="{cy}" r="{R_OUT}" fill="none" '
                 f'stroke="rgba(255,255,255,.13)" stroke-width=".8"/>')
    ticks.append(f'<circle cx="{cx}" cy="{cy}" r="{R_OUT + 7}" fill="none" '
                 f'stroke="rgba(255,255,255,.06)" stroke-width=".7"/>')
    for deg in range(0, 360, 5):
        r1 = R_OUT + (2 if deg % 15 == 0 else 4.5)
        x1, y1 = _polar(cx, cy, r1, deg)
        x2, y2 = _polar(cx, cy, R_OUT + 7, deg)
        w = ".9" if deg % 15 == 0 else ".6"
        op = ".20" if deg % 15 == 0 else ".10"
        ticks.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     f'stroke="rgba(255,255,255,{op})" stroke-width="{w}"/>')
    ticks.append('</g>')
    o.append("".join(ticks))

    # 外环：二十四山
    out = ['<g class="w-outer">']
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{R_LAB + 36}" fill="none" '
               f'stroke="rgba(255,255,255,.075)" stroke-width=".8"/>')
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{R_MID}" fill="none" '
               f'stroke="rgba(255,255,255,.075)" stroke-width=".8"/>')
    for m in mountains():
        a = m["deg"] + ROT
        x1, y1 = _polar(cx, cy, R_MID, a)
        x2, y2 = _polar(cx, cy, R_LAB + 36, a)
        out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                   f'stroke="rgba(255,255,255,.055)" stroke-width=".7"/>')
        hit = m["st"] != "none"
        col = "rgba(216,189,130,.92)" if hit else "rgba(255,255,255,.34)"
        wgt = ' font-weight="600"' if hit else ""
        fs = 15 if hit else 14
        out.append(f'<g transform="rotate({a:.2f} {cx} {cy})">'
                   f'<text x="{cx}" y="{cy - R_LAB + 5:.1f}" text-anchor="middle" '
                   f'font-family="Songti SC,serif" font-size="{fs}" fill="{col}"{wgt}>'
                   f'{m["name"]}</text></g>')
    out.append('</g>')
    o.append("".join(out))

    # 内环：八卦，反向转
    gua = ['<g class="w-gua">']
    gua.append(f'<circle cx="{cx}" cy="{cy}" r="{R_MID - 4}" fill="none" '
               f'stroke="rgba(255,255,255,.07)" stroke-width=".8"/>')
    gua.append(f'<circle cx="{cx}" cy="{cy}" r="{R_IN}" fill="none" '
               f'stroke="rgba(255,255,255,.07)" stroke-width=".8"/>')
    for gi, g in enumerate(ALL_GUA):
        a = gi * 45 - 22.5 + ROT
        d = _sector(cx, cy, R_IN, R_MID - 4, a, a + 45)
        gua.append(f'<path d="{d}" fill="none" stroke="rgba(255,255,255,.075)" '
                   f'stroke-width=".7"/>')
        ga = a + 22.5
        gx, gy = _polar(cx, cy, (R_IN + R_MID) / 2 + 6, ga)
        col = "rgba(216,189,130,.82)" if g["studied"] else "rgba(255,255,255,.30)"
        gua.append(f'<g transform="rotate({ga:.2f} {cx} {cy})">'
                   f'<text x="{cx}" y="{cy - ((R_IN + R_MID) / 2 + 6):.1f}" '
                   f'text-anchor="middle" font-family="Songti SC,serif" '
                   f'font-size="23" fill="{col}">{g["g"]}</text></g>')
    gua.append('</g>')
    o.append("".join(gua))

    # 内芯：两圈细环 + 十字准线
    o.append(f'<circle cx="{cx}" cy="{cy}" r="{R_IN - 14}" fill="none" '
             f'stroke="rgba(255,255,255,.05)" stroke-width=".7"/>')
    for x1, y1, x2, y2 in ((cx - 240, cy, cx - 96, cy), (cx + 96, cy, cx + 240, cy),
                           (cx, cy - 240, cx, cy - 96), (cx, cy + 96, cx, cy + 240)):
        o.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
                 f'stroke="rgba(255,255,255,.055)" stroke-width=".7"/>')
    o.append("</svg>")
    return "".join(o)


def _map_side():
    ms = mountains()
    taught = [m["name"] for m in ms if m["st"] == "taught"]
    full_names = "　".join(m["name"] for m in ms if m["st"] == "full")
    n_none = sum(1 for m in ms if m["st"] == "none")
    return (
        '<h3>这张图怎么看</h3>'
        '<ul class="lg">'
        '<li><span class="sw full"></span><div><b>已成篇</b>'
        f'<em>{full_names}</em><p>八段写满，图上可点，进正文。</p></div></li>'
        f'<li><span class="sw taught"></span><div><b>已讲、页待补</b>'
        f'<em>{"　".join(taught)}</em><p>课上讲到了，正文还空着。</p></div></li>'
        '<li><span class="sw none"></span><div><b>本阶段未及</b>'
        f'<em>其余 {n_none} 山</em><p>不在这次课的范围内，图上留位。</p></div></li>'
        '</ul>'
        '<div class="map-note">'
        '<p><b>卦和山不是两套东西。</b>卦管一段四十五度的格局，山是这段格局里十五度的落点。'
        '说「坎卦」，讲的是水与肾的总体倾向；落到「壬山」，才说得上财商、说得出应期。</p>'
        '<p>所以下面两种读法指向同一份内容：按卦读，是把三山放在一起看关系与分工；'
        '按山读，是带着一座山的问题直接找答案。</p>'
        '</div>'
    )


# ---------- 两种读法 ----------

def _by_gua(full_slug):
    cards = []
    for g in ALL_GUA:
        sz = g["sz"]
        rows = []
        for i in range(3):
            name = sz[i]
            if g["shan"]:
                label, st = g["shan"][i][1], g["shan"][i][2]
            else:
                label, st = "", "none"
            if st == "full":
                rows.append(f'<a class="row full" href="{full_slug}.html">'
                            f'<b>{name}</b><span>{label}</span><i>已成篇</i></a>')
            else:
                rows.append(f'<span class="row {st}"><b>{name}</b>'
                            f'<span>{label}</span>'
                            f'<i>{STAT_LABEL[st]}</i></span>')
        tag = ('<span class="g8-tag on">已开讲</span>' if g["studied"]
               else '<span class="g8-tag">待续</span>')
        cards.append(
            f'<div class="g8{" studied" if g["studied"] else ""}" '
            f'style="--gc:{g["color"]}">'
            f'<div class="g8-h"><span class="g8-c">{g["g"]}</span>'
            f'<div class="g8-m"><b>{g["g"]}卦</b>'
            f'<em>{g["fang"]} · {g["no"]} · {g["el"]}</em></div>'
            f'{tag}</div>'
            f'<p class="g8-n">{g["note"]}</p>'
            f'<div class="g8-l">{"".join(rows)}</div></div>')
    return '<div class="g8-grid">' + "".join(cards) + "</div>"


def _by_shan(full_slug):
    cols = []
    for g in ALL_GUA:
        rows = []
        for i in range(3):
            name = g["sz"][i]
            label, st = (g["shan"][i][1], g["shan"][i][2]) if g["shan"] else ("", "none")
            tip = name + "山" + ("　" + label if label else "")
            inner = f'<b>{name}</b><i>{STAT_LABEL[st] if st != "none" else "未及"}</i>'
            if st == "full":
                rows.append(f'<a class="mc full" href="{full_slug}.html" title="{tip}">{inner}</a>')
            else:
                rows.append(f'<span class="mc {st}" title="{tip}">{inner}</span>')
        cols.append(
            f'<div class="m24-col{" studied" if g["studied"] else ""}" style="--gc:{g["color"]}">'
            f'<div class="m24-h"><b>{g["g"]}</b><em>{g["sz"]}</em></div>'
            + "".join(rows) + '</div>')
    ms = mountains()
    n_full = sum(1 for m in ms if m["st"] == "full")
    n_taught = sum(1 for m in ms if m["st"] == "taught")
    n_none = sum(1 for m in ms if m["st"] == "none")
    legend = ('<div class="m24-foot">'
              f'<span><i class="sw full"></i>已成篇 {n_full} 山</span>'
              f'<span><i class="sw taught"></i>已讲待补 {n_taught} 山</span>'
              f'<span><i class="sw none"></i>本阶段未及 {n_none} 山</span>'
              '<span class="m24-tip">一列一卦，自上而下为前山、中山、后山；'
              '卦名与山名同字的（艮、巽、坤、乾）指的是那一山，不是整卦；'
              '列序从坎起按课程排，不是盘面方位。</span>'
              '</div>')
    return '<div class="m24">' + "".join(cols) + "</div>" + legend


def _stats(pages, mind_pages):
    n_full = sum(1 for m in mountains() if m["st"] == "full")
    items = [(24, "山 · 全图"), (8, "宫 · 分卦"),
             (n_full, "山 · 已成篇"), (len(pages), "篇 · 正文")]
    return "".join(f'<div class="st"><b>{n}</b><em>{lab}</em></div>' for n, lab in items)


def _parts(pages):
    meta = {
        "Ⅰ": ("按课次，一课不落",
               "老师每节课不只讲山，理法、技法、案例、答疑都在这里，按讲课顺序记。",
               ["理法与砂水本质", "技法与做局", "案例复盘与答疑"]),
        "Ⅱ": ("一山一页，八段讲透",
               "每山固定八段：论断、见水、见砂、兼卦、形煞、应期、自译经文、速查。",
               ["每山一句论断", "三版经文对照", "两种自译经文"]),
        "Ⅲ": ("只引用，不重复",
               "正文里已讲过的只给锚点。这里只写老师批语、未做题目拆解、题目到章节的映射表。",
               ["老师批语汇总", "未做题面拆解", "题目映射表"]),
    }
    cards = []
    for d, num, short, desc, color in SECTIONS:
        if num == "附":
            continue
        cnt = len([p for p in pages if p["section"] == d])
        title, text, bullets = meta.get(num, (short, desc, []))
        lis = "".join(f"<li>{b}</li>" for b in bullets)
        cards.append(
            f'<a class="part" href="section-{num}.html">'
            f'<div class="rnum">{num}</div>'
            f'<h3>{title}</h3>'
            f'<p class="desc">{text}</p>'
            f'<ul>{lis}</ul>'
            f'<span class="go">{(str(cnt) + " 篇") if cnt else "待整理"}　进入'
            f'<svg width="14" height="14" viewBox="0 0 16 16" fill="none">'
            f'<path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round"/></svg></span></a>'
        )
    return "".join(cards)


def _recent(pages):
    """三条线轮流取样，避免首页只出现课程线。"""
    if not pages:
        return '<div class="empty-note">还没有正文。</div>'
    groups = {}
    for p in pages:
        groups.setdefault(p["section"], []).append(p)
    picked, i = [], 0
    while len(picked) < 6 and any(len(v) > i for v in groups.values()):
        for d, num, short, desc, color in SECTIONS:
            v = groups.get(d, [])
            if len(v) > i:
                picked.append(v[i])
                if len(picked) == 6:
                    break
        i += 1
    rows = []
    for p in picked:
        rows.append(
            f'<a href="{p["slug"]}.html">'
            f'<span class="k">{p["num"]} 线</span>'
            f'<span class="t">{html.escape(p["title"])}</span>'
            f'<span class="d">第 {p["order"]:02d} 篇</span></a>'
        )
    return "".join(rows)


def build_index(pages, mind_pages):
    first_slug = pages[0]["slug"] if pages else "index"
    page = fill(tpl("index.html"),
                nav=build_nav(""),
                stats=_stats(pages, mind_pages),
                parts=_parts(pages),
                compass=_compass(first_slug),
                hero_wheel=_hero_wheel(),
                map_side=_map_side(),
                bygua=_by_gua(first_slug),
                byshan=_by_shan(first_slug),
                recent=_recent(pages),
                first_link=f"{first_slug}.html",
                foot_sections=foot_sections(),
                page_count=len(pages),
                mind_count=len(mind_pages),
                drawer=build_drawer("__home__",
                                    '<p class="side-title">本 页</p><ul class="d-sub">'
                                    '<li><a href="#shan"><span class="n">图</span>'
                                    '<span>二十四山全图</span></a></li>'
                                    '<li><a href="#read"><span class="n">读</span>'
                                    '<span>两种读法</span></a></li>'
                                    '<li><a href="#lines"><span class="n">体</span>'
                                    '<span>三条线怎么分</span></a></li></ul>'),
                )
    open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8").write(page)

    # 脑图索引
    if mind_pages:
        cards = "".join(
            f'<a class="card mind-card" href="{m["slug"]}.html" '
            f'title="{html.escape(m["title"])}">'
            f'<div class="k">{m["no"] or "图"}</div>'
            f'<h3>{html.escape(m["title"])}</h3>'
            f'<p>{m["nodes"]} 个节点</p></a>'
            for m in mind_pages
        )
        # 底部说明：纵向三步，窄屏也不挤成竖排单字（原来三列大卡片在手机上就是一列一个字）
        mind_body = ('<div class="mind-cards">' + cards + '</div>'
                     '<div class="mind-how">'
                     '<span class="eyebrow">怎 么 用</span>'
                     '<h2>图和正文是同一套内容的两种排法</h2>'
                     '<p>不是另一份材料。正文按讲次铺开，图按层级收拢；看完图，回正文看细目。</p>'
                     '<ul class="mh-list">'
                     '<li><span class="mh-k">看</span><div><h3>点圆点逐层展开</h3>'
                     '<p>默认只展开两级。点节点前的圆点看下一层，双指缩放、拖动平移，手机上同样适用。</p>'
                     '</div></li>'
                     '<li><span class="mh-k">对</span><div><h3>每张图对应一座卦</h3>'
                     '<p>坎、坤、震各一张，与卦山线里的条目一一对应。</p>'
                     '</div></li>'
                     '<li><span class="mh-k">据</span><div><h3>坎、坤有老师原图</h3>'
                     '<p>这两座卦另有老师版本的原图，已逐节点比对，差异记在备注，不与自译混在一起。</p>'
                     '</div></li>'
                     '</ul></div>')
        mind_sub = f"共 {len(mind_pages)} 张　·　一卦一张，按卦梳理"
        mind_md = "# 思维导图"
    else:
        mind_body = '<div class="empty-note">还没有脑图。</div>'
        mind_sub = "总览与分卦图"
        mind_md = "# 思维导图"

    page = (tpl("mind.html")
            .replace("@@TITLE@@", "思维导图")
            .replace("@@SUBTITLE@@", html.escape(mind_sub))
            .replace("@@NAV@@", build_nav("__mind__"))
            .replace("@@SIDE@@", mind_side("", pages))
            .replace("@@LAYOUT_CLASS@@", " two")
            .replace("@@MD@@", html.escape(mind_md))
            .replace("@@FOOT_SECTIONS@@", foot_sections())
            .replace("@@DRAWER@@", build_drawer("__mind__"))
            .replace("@@MIND_NOTE@@", ""))
    # 索引页自己就是导图区，右上角按钮换成回首页，别做成自环
    page = page.replace('<a class="btn btn-line btn-sm" href="mind-index.html">思维导图</a>',
                        '<a class="btn btn-line btn-sm" href="index.html">回首页</a>')
    # 这一页是导图总览，页脚「本图」一栏换成总数与读法
    page = page.replace("<h6>本图</h6>", "<h6>导图</h6>")
    page = page.replace("@@NODES@@", f"共 {len(mind_pages)} 张")
    page = page.replace("读法　默认展开两级，点圆点再看下一层",
                        "坎、坤、震各一张")
    # 换成卡片列表，保留工具栏隐藏
    page = page.replace('<div class="mind-wrap">', '<div style="display:none">')
    page = page.replace('</article>', mind_body + '</article>')
    # 这一页本身就叫「思维导图」，标题与面包屑不要再套一层同名
    page = page.replace("<title>思维导图 · 思维导图 · 金锁玉关</title>",
                        "<title>思维导图 · 金锁玉关</title>")
    page = page.replace('<a href="mind-index.html">思维导图</a>'
                        '<span class="sep">/</span>思维导图',
                        '<a href="mind-index.html">思维导图</a>')
    open(os.path.join(OUT_DIR, "mind-index.html"), "w", encoding="utf-8").write(page)


if __name__ == "__main__":
    t0 = time.time()
    build()
    print(f"耗时 {time.time()-t0:.1f}s")
