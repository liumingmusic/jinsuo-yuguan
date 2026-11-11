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

import os, re, sys, json, math, shutil, html, glob, time, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "内容")
MIND_DIR = os.path.join(ROOT, "脑图")
# 思维导图只按卦梳理：编号 00 的「九山总览」不生成页面、不进任何索引
# （md 文件保留不删；以后想放回来，把这个元组清空即可）。
MIND_HIDE_PREFIX = ("00",)
# Ⅳ 导图线的「线名」：脑图页不是从 内容/ 来的，而是从 脑图/ 来的，
# 但它和其它三条线一样有自己的编号、索引页、侧栏与页脚位置。
MIND_SECTION = "Ⅳ-导图线"
# Ⅴ 经文线的「线名」：经文页不是从 内容/ 来的，而是从 经文/ 来的。
# 它是全站经文的专页——一卦一页，每篇两栏并排对读。
JINGWEN_SECTION = "Ⅴ-经文线"
# 经文的唯一来源。经文/*.md 投影到 Ⅱ 卦山线、Ⅲ 作业线、Ⅳ 导图线三处，
# 三处内容必须一致，所以只此一份 md，别处不要另写。
#
# 一山一篇（壬山.md、子山.md…），另加三篇卦体（卦体坎.md…）。
# 每篇里固定两栏：「我的经文」与「老师经文」。
# 我的那栏只放我自己写的；老师那栏只放老师提供的版本。
# 还没给稿的地方留占位，不代写。
JINGWEN_DIR = os.path.join(ROOT, "经文")
JW_MINE = "我的经文"
JW_TEACHER = "老师经文"
JW_TBD = "〔待补〕"
JW_NOTE = ("经文分两栏：「我的经文」＝个人自编，「老师经文」＝老师的版本。"
           "老师没有给的一律留 〔待补〕，不代写。"
           "各山正文里的经文一、二、三是底本文献，不算谁的经文。")
OUT_DIR = os.path.join(ROOT, "站点")
IMG_DIR = os.path.join(ROOT, "_数据", "图片")
VENDOR_SRC = os.path.join(ROOT, "_工具", "vendor")

# 五条线的元信息：目录名 -> (编号, 标题, 短名, 主色)
# 顺序即导航顺序：Ⅰ 课程线 → Ⅱ 卦山线 → Ⅲ 作业线 → Ⅳ 导图线 → Ⅴ 经文线 → 附录
SECTIONS = [
    ("Ⅰ-课程线", "Ⅰ", "课程线", "理法 · 技法 · 案例", "#2c6a7c"),
    ("Ⅱ-卦山线", "Ⅱ", "卦山线", "坎 · 坤 · 震 · 巽 十二山", "#8a6a3a"),
    ("Ⅲ-作业线", "Ⅲ", "作业线", "回答原文 · 老师解答", "#7a4a52"),
    (MIND_SECTION, "Ⅳ", "导图线", "骨架 · 脉络 · 一卦一图", "#3f6b7a"),
    (JINGWEN_SECTION, "Ⅴ", "经文线", "我的经文 · 老师经文", "#5c4a72"),
    ("附录", "附", "附录", "技法 · 术语 · 速查", "#5a6068"),
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
    # 来源标记：渲染为中性注记，不上色。代码段里不包。
    parts = re.split(r"(<code>.*?</code>)", t)
    return "".join(p if p.startswith("<code>") else _src_tags(p) for p in parts)


# 来源标记 → 中性注记样式。〔待校〕/〔待核〕/〔待考〕/〔原文如此〕/〔?〕
# 都按同一中性注记呈现，不按来源分色。
SRC_TAG_RULES = [
    (re.compile(r"〔[^〕]*〕"), "src-note"),
]


def _src_tags(t):
    for pat, cls in SRC_TAG_RULES:
        def _wrap(m, cls=cls):
            # 短标记不许折行；长备注（>12 字）允许折行，否则 390px 会溢出
            extra = "" if len(m.group(0)) <= 12 else " src-long"
            return f'<span class="{cls}{extra}">{m.group(0)}</span>'
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
            # 首列若是短标签（如附录来源表里的「老师经文」「我的经文」），
            # 让它整行不折——否则三五个字被挤成一字一行，看着像断词。
            # 判据：首列最长不超过 6 字，且其它列明显更长。
            first_short = colw[0] <= 6 and len(colw) > 1 and max(colw[1:]) >= 12
            cls = []
            if wide:
                cls.append("wide")
            if first_short:
                cls.append("first-nowrap")
            cls_attr = f' class="{" ".join(cls)}"' if cls else ""
            t = [f'<div class="tbl-wrap{" stack" if stack else ""}">'
                 f"<table{cls_attr}><thead><tr>"]
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
        #   > 标注：扇区内标"壬山""子山""癸山"，缺口处标"必须补宫"
        #   > 风格：宣纸底墨线手绘，平面俯视，无阴影无立体
        #   > 读法：先定扇区，再跟两条箭头一进一出，缺口那侧就是要补宫的地方
        #   > 记一句：凹风从缺口进、气从缺口散，补宫补的是这个缺口
        # ｜后是图题；「> 画面/标注/风格/读法/记一句」五行紧随图行、不留空行。
        # 五段是完整的生图提示词：画面给构图，标注给图上文字，风格给画法，
        # 读法与记一句给这张图要教会人的东西。缺哪段就少写哪段，别空着占位。
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
            head_txt = f"{num} · {title}" if title else num
            # 新体例（2026-11-07）：图行下一行是整段「绘制要点：…建议尺寸：…」。
            # 这一整段就是要直接喂给画师或生图工具的那段话，所以源里不拆行、不换段，
            # 卡片里也原样显示成一段——【画布】【方位】【构图】【标注】【看点】只着色不切块，
            # 读的人框选那一整段就能拿去用。
            if i + 1 < n and lines[i + 1].strip().startswith("绘制要点"):
                one = lines[i + 1].strip()
                i += 2
                body = re.sub(r"【(画布|方位|构图|标注|看点)】",
                              r'<span class="ph-k">【\1】</span>', inline(one))
                body = re.sub(r"(建议尺寸：[^。]*)", r'<span class="ph-size">\1</span>', body)
                out.append(
                    f'<figure class="fig-ph" id="fig-{html.escape(fig_id)}">'
                    f'<div class="ph-frame">'
                    f'<div class="ph-head"><span class="ph-ico">{FIG_ICO}</span>'
                    f'<p class="ph-t">{inline(head_txt)}</p></div>'
                    f'<p class="ph-one">{body}</p>'
                    f'</div><figcaption>图待补 · 先读文字版</figcaption></figure>'
                )
                continue
            rows = [("画面", lead)] if lead else []
            # 紧随其后的「> 画面：… / > 标注：… / > 风格：… / > 读法：… / > 记一句：…」并入本图
            j = i + 1
            while j < n:
                m3 = re.match(r"^>\s*(画面|标注|风格|读法|怎么看|记一句)[:：]\s*(.*)$",
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
            # 固定渲染顺序：作者若写乱，按提示词的自然次序摆回去
            FIG_ORDER = ("画面", "标注", "风格", "读法", "记一句")
            merged.sort(key=lambda kv: FIG_ORDER.index(kv[0]) if kv[0] in FIG_ORDER else 99)
            out.append(
                f'<figure class="fig-ph" id="fig-{html.escape(fig_id)}">'
                f'<div class="ph-frame">'
                f'<div class="ph-head"><span class="ph-ico">{FIG_ICO}</span>'
                f'<p class="ph-t">{inline(head_txt)}</p></div>'
                + ('<dl class="ph-rows">'
                   + "".join(
                       f'<div class="ph-row{" ph-key" if k == "记一句" else ""}'
                       f'{" ph-prompt" if k in ("画面", "标注", "风格") else ""}'
                       f'{" ph-read" if k == "读法" else ""}">'
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
# status: full=已成篇（正文页已写全） / taught=已开讲（课上讲过，正文页未建） / none=未开讲（本课未讲）
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
    dict(g="巽", sz="辰巽巳", fang="东南", no="四绿", el="木", color="#3b6b66", studied=True,
         note="长女、风与入。三山中巽居中，主风评与相互作用。",
         shan=[("辰", "水库与抢夺", "full"),
               ("巽", "风评 · 慕强与自强", "full"),
               ("巳", "起 · 人间第一流", "full")]),
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


STAT_LABEL = {"full": "已成篇", "taught": "已开讲", "none": "未开讲"}


def build_nav(current=""):
    """顶栏导航：五条线 + 附录。"""
    parts = []
    for d, num, short, desc, color in SECTIONS:
        on = " on" if d == current else ""
        parts.append(f'<a class="{on.strip()}" href="section-{num}.html">{num} {short}</a>')
    return "".join(parts)


def mind_files():
    """参与构建的脑图文件：只按卦梳理，编号 00 的总览图隐藏（文件保留不删）。"""
    if not os.path.isdir(MIND_DIR):
        return []
    return sorted(f for f in os.listdir(MIND_DIR)
                  if f.endswith(".md") and not f.startswith(MIND_HIDE_PREFIX))


def build_drawer(current="", sub=""):
    """移动端抽屉导航。桌面隐藏，≤900px 由汉堡键拉出。

    侧栏在窄屏被隐藏，若不另给入口，手机上除了当前页哪都去不了——这是
    2026-11-03 用户反馈「作业线、卦山线都看不到」的直接原因。
    """
    items, extra = [], []
    for d, num, short, desc, color in SECTIONS:
        on = " on" if d == current else ""
        li = (f'<li><a class="d-line{on}" href="section-{num}.html" style="--c:{color}">'
              f'<b>{num}</b><span class="d-t">{short}<em>{desc}</em></span></a></li>')
        # 附录不是「线」，单列一组，免得「五 条 线」下面挂六条
        (extra if num == "附" else items).append(li)
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
        '<p class="side-title">五 条 线</p>'
        '<ul class="d-lines">' + "".join(items) + '</ul>'
        '<p class="side-title">附 录</p>'
        '<ul class="d-lines">' + "".join(extra) + '</ul>'
        + sub +
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
    """页脚导航：五条线 + 附录，与顶栏完全一致。"""
    return "".join(
        f'<a href="section-{num}.html">{num} {short}</a>' for d, num, short, desc, color in SECTIONS
    )


# ---------- 经文（唯一源：经文/*.md，一山一篇 + 卦体） ----------

def jingwen_files():
    """参与构建的经文文件。"""
    if not os.path.isdir(JINGWEN_DIR):
        return []
    return sorted(f for f in os.listdir(JINGWEN_DIR) if f.endswith(".md"))


def jingwen_gua(key):
    """条目名取所属卦：'壬山' -> 坎；'卦体坤' -> 坤。"""
    if key.startswith("卦体"):
        return key[2:]
    for g in ALL_GUA:
        if key[0] in g["sz"]:
            return g["g"]
    return ""


def jingwen_gua_of_file(fname):
    """从页面文件名取卦字：'01 坎卦 壬子癸.md' -> 坎。"""
    stem = os.path.splitext(fname)[0]
    for g in ALL_GUA:
        if g["g"] in stem:
            return g["g"]
    return stem


def load_jingwen():
    """读全部经文，返回 [(条目名, 卦字, md)]，按文件名排序。"""
    out = []
    for f in jingwen_files():
        key = os.path.splitext(f)[0]
        md = open(os.path.join(JINGWEN_DIR, f), encoding="utf-8").read()
        out.append((key, jingwen_gua(key), md))
    return out


_JW_CACHE = None


def jingwen_by_key():
    """经文按条目名索引：'壬山' -> (卦字, md)。"""
    global _JW_CACHE
    if _JW_CACHE is None:
        _JW_CACHE = {key: (g, md) for key, g, md in load_jingwen()}
    return _JW_CACHE


def jingwen_seq(key):
    """条目在卦内的序号：卦体 0，三山按先后天次序 1/2/3。"""
    gua = jingwen_gua(key)
    if key.startswith("卦体"):
        return 0
    for g in ALL_GUA:
        if g["g"] == gua and g.get("shan"):
            for i, (s, _, _) in enumerate(g["shan"]):
                if s == key[0]:
                    return i + 1
    return 9


def jingwen_gua_keys(gua):
    """一卦的条目清单：卦体 + 三山，次序固定。"""
    keys = [f"卦体{gua}"]
    for g in ALL_GUA:
        if g["g"] == gua and g.get("shan"):
            keys += [f"{s}山" for s, _, _ in g["shan"]]
    return keys


def jw_slug(text):
    """标题转锚点用的短名，规则与 render_md 里的 make_anchor 一致（这里不做去重，
    因为每篇经文各自渲染、各自有 jw-卦-序号- 前缀，不会撞）。"""
    return re.sub(r"[^\w一-龥]+", "-", text).strip("-") or "sec"


def jw_parse(md):
    """把一篇经文 md 拆开：(标题, 副标题, [(栏名, 栏内容行)])。

    md 的体例固定：h1 是条目名，h1 后面一段是「卦 · 山 · 定位」的副标题，
    再往后每个 h2 是一栏（我的经文 / 老师经文）。
    """
    title = ""
    sub = ""
    secs = []
    name = None
    body = []
    started = False
    for l in md.split("\n"):
        if l.startswith("# "):
            title = l[2:].strip()
            started = True
            continue
        if l.startswith("## "):
            if name is not None:
                secs.append((name, body))
            name = l[3:].strip()
            body = []
            continue
        if not started:
            continue
        if name is None:
            if l.strip() and not sub:
                sub = l.strip()
            continue
        body.append(l)
    if name is not None:
        secs.append((name, body))
    return title, sub, secs


def jw_is_empty(body):
    """一栏里除了〔待补〕这类占位标记以外没有实质内容，就算空栏。"""
    txt = "\n".join(body).strip()
    if not txt:
        return True
    return not re.sub(r"〔[^〕]*〕", "", txt).strip()


def jw_render(key, md, shift=1, with_title=False):
    """一条经文（一个山或一个卦体）渲染成 HTML 片段。

    两栏口径：我的经文收个人自编，老师经文没给的留 〔待补〕。
    空栏不撑标题——只留一行浅灰占位；有内容的栏照常出标题与正文，
    这样一页上不会因为空栏而留下十几个空标题。
    """
    gua = jingwen_gua(key)
    prefix = f"jw-{gua}-{jingwen_seq(key)}-"
    title, sub, secs = jw_parse(md)
    out = []
    if with_title and title:
        out.append(f'<h{1 + shift} id="{prefix}{jw_slug(title)}">{inline(title)}</h{1 + shift}>')
    if sub and with_title:
        # 副标题只在带条目名的场合出现（Ⅲ 总表、Ⅳ 脑图页）。
        # Ⅱ 线那一页上文已经写着「壬山 · 财富能力」，不必再重复一遍。
        out.append(f'<p class="jw-sub">{inline(sub)}</p>')
    empty_all = bool(secs) and all(jw_is_empty(b) for _, b in secs)
    for name, body in secs:
        anchor = prefix + jw_slug(name)
        if empty_all:
            # 两栏都空：合成一行占位，锚点仍各自保留，链接不会断
            if name == secs[0][0]:
                ids = "".join(f'<span id="{prefix}{jw_slug(n)}"></span>' for n, _ in secs)
                out.append(f'<p class="jw-tbd">{ids}〔待补〕</p>')
            continue
        if jw_is_empty(body):
            out.append(f'<p class="jw-tbd" id="{anchor}">{inline(name)}〔待补〕</p>')
            continue
        out.append(f'<h{2 + shift} id="{anchor}">{inline(name)}</h{2 + shift}>')
        html, _ = render_md("\n".join(body))
        out.append(html)
    return "".join(out)


def jw_entry(key, md, shift=1, with_title=False):
    """一条经文（一个山或一个卦体）渲染成 HTML 片段。"""
    return jw_render(key, md, shift, with_title)


# 卦画：自上而下三爻，1 为阳（连），0 为阴（断）。纯 SVG，不依赖字体图标。
TRIGRAM_ROWS = {"坎": (0, 1, 0), "坤": (0, 0, 0),
                "震": (0, 0, 1), "巽": (1, 1, 0)}


def _trigram(gua, cls="jw-tri"):
    """一枚卦爻角标。用 rect 画，避免八卦符号在某些字体下变豆腐块。"""
    rows = TRIGRAM_ROWS.get(gua, (0, 1, 0))
    parts = []
    for i, yang in enumerate(rows):
        y = 4 + i * 10
        if yang:
            parts.append(f'<rect x="2" y="{y}" width="26" height="3.4" rx="1.4"/>')
        else:
            parts.append(f'<rect x="2" y="{y}" width="11" height="3.4" rx="1.4"/>')
            parts.append(f'<rect x="17" y="{y}" width="11" height="3.4" rx="1.4"/>')
    return (f'<span class="{cls}" aria-hidden="true">'
            f'<svg viewBox="0 0 30 36" fill="currentColor">{"".join(parts)}</svg></span>')


def _jw_front(gua):
    """Ⅴ 线卷首题识：卦牌、竖排卷题、界行、朱印。

    纯装饰，不复述卦名与经文正文。卷题别写「一」字——竖排时那一横
    会变成一枚悬空短划，看起来像掉了一个字（2026-11-11 用户反馈）。
    """
    return ('<div class="jw-front">'
            + _trigram(gua, "jw-front-tri")
            + '<span class="jw-front-word">經文卷</span>'
            + '<span class="jw-front-rule"></span>'
            + f'<span class="seal">{_seal()}</span>'
            + '</div>')


def jw_pair(key, md, shift=1):
    """一条经文渲染成一轴绢纸（Ⅴ 经文线用）。

    Ⅱ 卦山线、Ⅲ 作业线、Ⅳ 导图线三处是行文里的一段，栏是上下接着走的；
    Ⅴ 线要的是并排对读——同一篇，我的在左、老师的在右，一眼比出高下。
    所以这里两栏永远都在，空栏也留框。

    卷轴化只加结构骨架（.jw-entry / 卦爻 / 上下木轴），经文正文、
    栏名、锚点前缀 jw-卦-序号- 一个字不动，样式全交给 .jw-scroll 作用域。
    """
    gua = jingwen_gua(key)
    prefix = f"jw-{gua}-{jingwen_seq(key)}-"
    title, sub, secs = jw_parse(md)
    out = ['<div class="jw-entry">']
    if title:
        out.append(f'<h{1 + shift} class="jw-pair-h" id="{prefix}{jw_slug(title)}">'
                   + _trigram(gua)
                   + f'<span class="jw-slip-name">{inline(title)}</span>'
                   + f'</h{1 + shift}>')
    if sub:
        out.append(f'<p class="jw-sub">{inline(sub)}</p>')
    out.append('<div class="jw-pair">')
    # 上下木轴：绝对定位，不参与 grid 的两栏布局
    out.append('<span class="jw-rod top" aria-hidden="true"><i></i><i></i></span>'
               '<span class="jw-rod bot" aria-hidden="true"><i></i><i></i></span>')
    for name, body in secs:
        anchor = prefix + jw_slug(name)
        if jw_is_empty(body):
            inner = f'<p class="jw-tbd" id="{anchor}">〔待补〕</p>'
        else:
            html, _ = render_md("\n".join(body))
            inner = html
        cls = "mine" if name == JW_MINE else "teacher"
        out.append(f'<div class="jw-pair-col {cls}">'
                   f'<p class="jw-pair-label">{inline(name)}</p>'
                   f'<div class="jw-pair-body">{inner}</div>'
                   f'</div>')
    out.append('</div></div>')
    return "".join(out)


def jw_pair_gua(gua, shift=1):
    """一卦的卦体 + 三山，逐篇渲染成两栏对照卡。"""
    JW = jingwen_by_key()
    out = []
    for k in jingwen_gua_keys(gua):
        if k in JW:
            out.append(jw_pair(k, JW[k][1], shift))
    return "".join(out)


def jingwen_gua_title(gua):
    """卦页的标题：跟 Ⅱ 线、Ⅳ 线同一口径——一白坎卦 · 壬子癸。"""
    for g in ALL_GUA:
        if g["g"] == gua:
            return f'{g["no"]}{g["g"]}卦 · {g["sz"]}'
    return gua


def jingwen_gua_lead(gua):
    """卦页的导语：一句话说清这卦三山各管什么。"""
    for g in ALL_GUA:
        if g["g"] == gua:
            return g["note"]
    return ""


def jw_pager(raw, cur_no):
    """Ⅴ 线页的上下页：上一卦 / 下一卦。"""
    idx = next((i for i, x in enumerate(raw) if x["no"] == cur_no), 0)
    out = ""
    if idx > 0:
        p = raw[idx - 1]
        out += (f'<a href="{p["slug"]}.html"><span class="dir">← 上一卦</span>'
                f'<span class="ttl">{html.escape(p["title"])}</span></a>')
    else:
        out += '<span class="empty"></span>'
    if idx + 1 < len(raw):
        p = raw[idx + 1]
        out += (f'<a class="next" href="{p["slug"]}.html"><span class="dir">下一卦 →</span>'
                f'<span class="ttl">{html.escape(p["title"])}</span></a>')
    else:
        out += '<span class="empty"></span>'
    return out


def build_jingwen(pages):
    """Ⅴ 经文线：一卦一页，两栏对照。

    这条线不是从 内容/ 来的，是从 经文/ 来的——经文/*.md 是全站经文的
    唯一源，这里只是把它按卦铺开、把两栏并排放，供对读。

    每页四篇：卦体在前，三山按先后天次序跟上。每篇一张两栏对照卡，
    我的在左、老师的在右。老师没给的留占位，不代写。
    """
    made = []
    if not os.path.isdir(JINGWEN_DIR):
        return made
    PAGE_TMPL = tpl("page.html")
    order = jingwen_gua_order()

    # 先扫一遍拿到全部卦，页面之间才能互相链接（侧栏「本 节」要用）
    raw = []
    for i, gua in enumerate(order, 1):
        title = jingwen_gua_title(gua)
        # 文件名跟 Ⅱ 线同一口径：卦名在前、三山在后，句点去掉，避免 URL 里出现 %C2%B7
        fname = re.sub(r"[^一-鿿A-Za-z0-9]", "", title)
        raw.append(dict(gua=gua, no=f"{i:02d}", title=title,
                        lead=jingwen_gua_lead(gua),
                        slug=f"Ⅴ-{i:02d}-{fname}"))

    for it in raw:
        gua = it["gua"]
        body = (
            _jw_front(gua)
            + f'<p class="jw-note">{JW_NOTE}</p>'
            + jw_pair_gua(gua, shift=2)
        )
        sub = ('<p class="side-title">本 节</p><ul class="d-sub">'
               + "".join(
                   f'<li><a class="{"on" if x["no"] == it["no"] else ""}" href="{x["slug"]}.html">'
                   f'<span class="n">{x["no"]}</span><span>{html.escape(x["title"])}</span></a></li>'
                   for x in raw)
               + '</ul>')
        tree = ('<div class="side-group"><p class="side-title">全部内容</p><ul>' + "".join(
            f'<li><a class="{"on" if s[0] == JINGWEN_SECTION else ""}" href="section-{s[1]}.html">'
            f'<span class="n">{s[1]}</span><span>{s[2]}</span></a></li>' for s in SECTIONS
        ) + '<li><a href="index.html"><span class="n">首</span>'
            '<span>返回首页</span></a></li></ul></div>')

        # 对照正文：本卦在 Ⅱ 卦山线的页
        cross = ""
        for pg in pages:
            if pg["section"] == "Ⅱ-卦山线" and jingwen_gua_of_file(pg["file"]) == gua:
                cross = ('<div class="side-group"><p class="side-title">对照正文</p><ul>'
                         f'<li><a href="{pg["slug"]}.html"><span class="n">Ⅱ</span>'
                         f'<span>{html.escape(pg["title"])}</span></a></li>'
                         '</ul><p class="side-tip">经文出自各山正文，这里只作对读。</p></div>')
                break

        page = (PAGE_TMPL
                .replace("@@TITLE@@", html.escape(it["title"]))
                .replace("@@SUBTITLE@@", f'Ⅴ 经文线　·　{it["lead"]}')
                .replace("@@NAV@@", build_nav(JINGWEN_SECTION))
                .replace("@@SIDE@@", tree + cross)
                .replace("@@CRUMB@@",
                         '<a href="index.html">总览</a><span class="sep">/</span>'
                         '<a href="section-Ⅴ.html">Ⅴ 经文线</a>')
                .replace("@@LAYOUT_CLASS@@", " jw-scroll")
                .replace("@@BODY@@", body)
                .replace("@@TOC_BLOCK@@", "")
                .replace("@@PAGER@@", jw_pager(raw, it["no"]))
                .replace("@@FOOT_LINE@@", "Ⅴ 经文线")
                .replace("@@FOOT_POS@@", f'第 {int(it["no"])} 卦 · 本节共 {len(raw)} 卦')
                .replace("@@FOOT_SECTIONS@@", foot_sections())
                .replace("@@DRAWER@@", build_drawer(JINGWEN_SECTION, sub)))
        open(os.path.join(OUT_DIR, it["slug"] + ".html"), "w", encoding="utf-8").write(page)
        made.append({"title": it["title"], "slug": it["slug"], "order": int(it["no"]),
                     "gua": gua, "lead": it["lead"], "no": it["no"]})
    return made


def jw_for_gua(gua, shift=1, with_title=False):
    """一卦的卦体 + 三山，按卦体、三山次序拼起来。"""
    JW = jingwen_by_key()
    out = []
    for k in jingwen_gua_keys(gua):
        if k in JW:
            out.append(jw_entry(k, JW[k][1], shift, with_title))
    return "".join(out)


def jw_section(gua, shift=2, with_title=False, heading="经文"):
    """一卦经文的整块：小节标题 + 来源说明 + 内容。"""
    return (f'<h2 class="chap" id="jw-{gua}-sec">{heading}</h2>'
            f'<p class="jw-note">{JW_NOTE}</p>'
            + jw_for_gua(gua, shift, with_title))


# ---------- 脑图节点里的「我的经文」：从经文唯一源自动同步 ----------
# 老脑图里每座山挂着「我的经文：〔待补〕」，那是经文还没入库时留下的占位；
# 新建的巽卦脑图干脆连节点都没有。网页导图与 导出/*.xmind 都读 脑图/*.md，
# 所以构建时把节点块同步写回 md（幂等），一次 build 两边一起变，不会各写一份。

MIND_JW_HEAD = "- 我的经文"
MIND_JW_TEACHER = "- 老师经文：〔待补〕"


def mind_jw_block(key, md):
    """一篇经文 → markmap 的缩进节点块，只收「我的经文」栏的诗句。"""
    _, _, secs = jw_parse(md)
    mine = next((b for n, b in secs if n == JW_MINE), [])
    groups, cur = [], None
    for l in mine:
        s = l.strip()
        if not s:
            continue
        m = re.match(r"^\*\*(.+?)\*\*$", s)
        if m:
            cur = (m.group(1), [])
            groups.append(cur)
        elif s.startswith("> ") and cur is not None:
            cur[1].append(s[2:].strip())
    if not groups:
        return [MIND_JW_HEAD + "：〔待补〕", MIND_JW_TEACHER]
    out = [MIND_JW_HEAD]
    for name, lines in groups:
        out.append("  - " + name)
        out += ["    - " + x for x in lines]
    out.append(MIND_JW_TEACHER)
    return out


def sync_mind_jingwen():
    """把 脑图/*.md 里的经文节点同步成经文唯一源的内容，写回 md。幂等。"""
    JW = jingwen_by_key()
    changed = []
    for f in mind_files():
        path = os.path.join(MIND_DIR, f)
        src = open(path, encoding="utf-8").read()
        gua = jingwen_gua_of_file(f)
        keys = jingwen_gua_keys(gua)

        # 按 ## 分支切块（第一段是文件标题与导语）
        segs, cur = [], []
        for l in src.split("\n"):
            if l.startswith("## ") and cur:
                segs.append(cur)
                cur = []
            cur.append(l)
        if cur:
            segs.append(cur)

        out_segs = []
        for seg in segs:
            head = seg[0]
            key = ""
            if head.startswith("## "):
                h = head[3:]
                if "卦论断" in h:
                    key = "卦体" + gua
                else:
                    for k in keys:
                        if k.endswith("山") and h.startswith(k[0] + "山"):
                            key = k
                            break
            body, i = [], 1
            while i < len(seg):
                l = seg[i]
                # 旧占位块（父节点 + 两行子节点）与已生成块（父节点 + 全部缩进行）都清掉
                if (l.startswith("- 我的经文与老师经文")
                        or l == MIND_JW_HEAD
                        or l.startswith(MIND_JW_HEAD + "：")):
                    i += 1
                    while i < len(seg) and seg[i].startswith("  "):
                        i += 1
                    continue
                if l.strip() == MIND_JW_TEACHER:
                    i += 1
                    continue
                body.append(l)
                i += 1
            while body and not body[-1].strip():
                body.pop()
            block = mind_jw_block(key, JW[key][1]) if key in JW else []
            new_seg = [head] + body
            if block:
                new_seg += [""] + block
            out_segs.append("\n".join(new_seg))

        text = "\n\n".join(out_segs).rstrip() + "\n"
        if text != src:
            open(path, "w", encoding="utf-8").write(text)
            changed.append(f)
    if changed:
        print("  脑图经文节点已同步：" + "、".join(changed))
    return changed


def jingwen_gua_order():
    """经文的卦序：跟 Ⅱ 卦山线的页面顺序走（坎、坤、震），不按八宫排。"""
    order = []
    d = os.path.join(ROOT, "内容", "Ⅱ-卦山线")
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if not f.endswith(".md"):
                continue
            g = jingwen_gua_of_file(f)
            if g and g not in order:
                order.append(g)
    return order


def jw_all():
    """全部经文按卦分组，给 Ⅲ 作业线的《经文总表》页用。

    按卦分组是因为一页装四卦十六篇，不分组就分不出谁是谁。
    """
    JW = jingwen_by_key()
    out = []
    for gua in jingwen_gua_order():
        rows = []
        for k in jingwen_gua_keys(gua):
            if k in JW:
                rows.append(jw_entry(k, JW[k][1], shift=2, with_title=True))
        if rows:
            out.append(f'<h2 class="chap" id="jw-gua-{gua}">{gua}卦</h2>' + "".join(rows))
    return "".join(out)


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
    # 纯静态站：加 .nojekyll 跳过 GitHub Pages 的 Jekyll 构建，避免偶发 Page build failed
    open(os.path.join(OUT_DIR, ".nojekyll"), "w", encoding="utf-8").close()
    os.makedirs(os.path.join(OUT_DIR, "资源", "vendor"), exist_ok=True)

    # 样式与脚本
    open(os.path.join(OUT_DIR, "style.css"), "w", encoding="utf-8").write(tpl("style.css"))

    # 站点图标：`_工具/theme/图标/` 由 make_icons.py 生成，这里复制到站点根目录。
    # favicon.ico 必须落在根上——浏览器会直接请求 /favicon.ico，找不到就显示空白页图标。
    # 只放页面真正引用到的几个，别把 9 张中间尺寸 PNG 全倒进根目录。
    ICON_FILES = ("favicon.ico", "favicon.svg", "favicon-32.png",
                  "apple-touch-icon.png", "favicon-192.png", "favicon-512.png")
    icon_dir = os.path.join(THEME, "图标")
    if os.path.isdir(icon_dir):
        for f in ICON_FILES:
            src = os.path.join(icon_dir, f)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(OUT_DIR, f))
    else:
        print("  ⚠ 缺少 theme/图标/，页面将没有站点图标"
              "（跑 python3 _工具/make_icons.py 生成）")
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

        # 经文：唯一源是 经文/*.md，投影到 Ⅱ 卦山线、Ⅲ 作业线、Ⅳ 导图线三处。
        # Ⅲ 线总表页一次挂全；Ⅱ 线卦页在山章节里按 @@JW:条目@@ 就地插入；
        # Ⅳ 线脑图页挂本卦那套。
        if "@@JINGWEN_ALL@@" in body_html:
            body_html = body_html.replace("<p>@@JINGWEN_ALL@@</p>", jw_all())
        JW = jingwen_by_key()

        def _jw_ph(m):
            key = m.group(1)
            if key not in JW:
                print(f"  ⚠ 经文条目不存在：{key}")
                return m.group(0)
            return jw_entry(key, JW[key][1], shift=1, with_title=False)

        body_html = re.sub(r"<p>@@JW:([^@]+)@@</p>", _jw_ph, body_html)

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
        side.append('<li><a href="index.html"><span class="n">首</span>'
                    '<span>返回首页</span></a></li>')
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

    # 脑图（Ⅳ 导图线）先建：章节索引页要用它出卡片
    # 建之前先把图内的「我的经文」节点同步成经文唯一源，网页与导出读的是同一份 md
    sync_mind_jingwen()
    mind_pages = build_minds(pages)

    # 经文（Ⅴ 经文线）同理：页子从 经文/ 来，章节索引页也要用
    jw_pages = build_jingwen(pages)

    # 章节索引页
    for d, num, short, desc, color in SECTIONS:
        if d == MIND_SECTION:
            # Ⅳ 导图线：条目是脑图页，不是 内容/ 下的正文
            items = [{"slug": m["slug"], "order": m["order"], "title": m["title"],
                      "file": m["file"], "lead": f"{m['nodes']} 个节点　·　{m['lead']}"} for m in mind_pages]
            cards = "".join(
                f'<a class="card" href="{p["slug"]}.html">'
                f'<div class="k">{num} · {p["order"]:02d}</div>'
                f'<h3>{html.escape(p["title"])}</h3>'
                f'<p>{html.escape(p["lead"])}</p></a>'
                for p in items
            )
            body = (f'<div class="cards">{cards}</div>' if cards
                    else '<div class="empty-note">还没有导图。等卦的骨架梳理完，这里会自动出现条目。</div>')
            body += ('<div class="mind-how">'
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
                     '<p>这两座卦另有老师版本的原图，已逐节点比对，差异记在备注，不与经文混在一起。</p>'
                     '</div></li>'
                     '</ul></div>')
        elif d == JINGWEN_SECTION:
            # Ⅴ 经文线：条目是经文卦页，不是 内容/ 下的正文
            items = [{"slug": j["slug"], "order": j["order"], "title": j["title"],
                      "file": j["slug"], "lead": f'卦体 + 三山 · {j["lead"]}'} for j in jw_pages]
            cards = "".join(
                f'<a class="card" href="{p["slug"]}.html">'
                f'<div class="k">{num} · {p["order"]:02d}</div>'
                f'<h3>{html.escape(p["title"])}</h3>'
                f'<p>{html.escape(p["lead"])}</p></a>'
                for p in items
            )
            body = (f'<div class="cards">{cards}</div>' if cards
                    else '<div class="empty-note">经文源还没建。先在 <code>经文/</code> 下放 md，这里会自动出现条目。</div>')
            body += ('<div class="mind-how">'
                     '<span class="eyebrow">怎 么 用</span>'
                     '<h2>一卦一页，两栏对着读</h2>'
                     '<p>每页四篇：卦体在前，三山跟上。每一篇左边是我的手笔，右边是老师给的版本，'
                     '并排放着，一眼比出高下。空着的地方留着框。</p>'
                     '<ul class="mh-list">'
                     '<li><span class="mh-k">左</span><div><h3>我的经文</h3>'
                     '<p>只放我自己写的。手笔不一样、句子不一样，都照实留。</p>'
                     '</div></li>'
                     '<li><span class="mh-k">右</span><div><h3>老师经文</h3>'
                     '<p>只放老师提供的版本。两栏不混写，也不用一处的内容顶另一处。</p>'
                     '</div></li>'
                     '<li><span class="mh-k">源</span><div><h3>改一处，四处一起变</h3>'
                     '<p>这份经文的唯一源是 <code>经文/</code> 下的 md。'
                     '卦山线各山章节、作业线总表、导图线图下、本线四页，都是它的投影。</p>'
                     '</div></li>'
                     '</ul></div>')
        else:
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
                    ) + '<li><a href="index.html"><span class="n">首</span>'
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

    # 首页
    build_index(pages, mind_pages, jw_pages)

    print(f"\n构建完成：{len(pages)} 页正文 + {len(mind_pages)} 张导图 -> {os.path.relpath(OUT_DIR, ROOT)}/")
    return pages, mind_pages


def mind_side(no, pages, minds=()):
    """导图页的左侧栏：本节各张图 + 全部内容树 + 对照正文跳转。

    和 section/正文页同一套侧栏体例——导图线既然是一条线，
    版式就得跟其它三条线一致（2026-11-03 用户反馈）。
    """
    mine = [m for m in minds if not no or m["no"] == no]
    sub = ""
    if minds:
        lis = "".join(
            f'<li><a class="{"on" if m["no"] == no else ""}" href="{m["slug"]}.html">'
            f'<span class="n">{m["no"]}</span><span>{html.escape(m["title"])}</span></a></li>'
            for m in minds
        )
        sub = '<p class="side-title">本 节</p><ul class="d-sub">' + lis + '</ul>'
    tree = ('<div class="side-group"><p class="side-title">全部内容</p><ul>' + "".join(
        f'<li><a class="{"on" if s[0] == MIND_SECTION else ""}" href="section-{s[1]}.html">'
        f'<span class="n">{s[1]}</span><span>{s[2]}</span></a></li>' for s in SECTIONS
    ) + '<li><a href="index.html"><span class="n">首</span>'
        '<span>返回首页</span></a></li></ul></div>')
    cross = ""
    for pg in pages:
        # 脑图文件编号 01/02/03 ↔ 卦山线同序号正文页（slug 形如 Ⅱ-01-坎卦壬子癸）
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

    # 先扫一遍拿到全部图，页面之间才能互相链接（侧栏「本 节」要用）
    raw = []
    for f in files:
        md = open(os.path.join(MIND_DIR, f), encoding="utf-8").read()
        title = extract_title(md, os.path.splitext(f)[0])
        nodes = sum(1 for l in md.split("\n")
                    if re.match(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s)", l))
        m = re.match(r"^(\d+)", f)
        no = m.group(1) if m else ""
        stem = os.path.splitext(f)[0]
        gua = jingwen_gua_of_file(f)
        # 文件名自带序号「01 坎卦 壬子癸」，序号已用在 Ⅳ-01 里，标题部分不再重复带号
        name = re.sub(r"^\d+[\s.、]*", "", stem)
        slug = "Ⅳ-" + no.zfill(2) + "-" + re.sub(r"\s+", "", name)
        lead = next((g["note"] for g in ALL_GUA if g["g"] == gua), "")
        raw.append(dict(md=md, title=title, nodes=nodes, no=no, stem=stem,
                        gua=gua, slug=slug, lead=lead, file=f))

    for it in raw:
        # 本卦的经文：与 Ⅱ 卦山线的卦页、Ⅲ 作业线的总表页同一份源
        note = jw_section(it["gua"], shift=1, with_title=True)
        sub = ("<p class=\"side-title\">本 节</p><ul class=\"d-sub\">"
               + "".join(
                   f'<li><a class="{"on" if x["no"] == it["no"] else ""}" href="{x["slug"]}.html">'
                   f'<span class="n">{x["no"]}</span><span>{html.escape(x["title"])}</span></a></li>'
                   for x in raw)
               + '</ul>')
        page = (MIND_TMPL
                .replace("@@TITLE@@", html.escape(it["title"]))
                .replace("@@SUBTITLE@@", f"Ⅳ 导图线　·　共 {it['nodes']} 个节点")
                .replace("@@NODES@@", str(it["nodes"]))
                .replace("@@NAV@@", build_nav(MIND_SECTION))
                .replace("@@SIDE@@", mind_side(it["no"], pages, raw))
                .replace("@@LAYOUT_CLASS@@", " two")
                .replace("@@MD@@", html.escape(it["md"]))
                .replace("@@FOOT_SECTIONS@@", foot_sections())
                .replace("@@DRAWER@@", build_drawer(MIND_SECTION, sub))
                .replace("@@MIND_NOTE@@", note))
        open(os.path.join(OUT_DIR, it["slug"] + ".html"), "w", encoding="utf-8").write(page)
        made.append({"title": it["title"], "slug": it["slug"], "file": it["file"],
                     "nodes": it["nodes"], "no": it["no"], "order": int(it["no"] or 0),
                     "lead": it["lead"], "gua": it["gua"]})
    return made


# ---------- 二十四山罗盘 ----------

def _polar(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.sin(a), cy - r * math.cos(a)


def _arc(cx, cy, r, a0, a1):
    """顺时针一段圆弧（角度沿用 _polar：0° 在正上方）。给彗尾光弧用。"""
    x0, y0 = _polar(cx, cy, r, a0)
    x1, y1 = _polar(cx, cy, r, a1)
    large = 1 if a1 - a0 > 180 else 0
    return (f"M{x0:.2f},{y0:.2f} A{r:.2f},{r:.2f} 0 {large} 1 "
            f"{x1:.2f},{y1:.2f}")


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


def shan_slug_map(pages):
    """山名 -> Ⅱ 卦山线页 slug。

    首页罗盘与「按卦读 / 按山读」两栏里，每一座山都要指到它自己的页，
    不能全指到同一页（此前九座山全链到第一讲预热课，是明显的错链）。
    """
    m = {}
    for pg in pages:
        if pg["section"] != "Ⅱ-卦山线":
            continue
        stem = os.path.splitext(pg["file"])[0]
        for ch in stem:
            if ch in "壬子癸甲卯乙未坤申辰巽巳":
                m.setdefault(ch, pg["slug"])
    return m


def _compass(slan):
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
        if st == "full" and slan.get(m["name"]):
            o.append(f'<a href="{slan[m["name"]]}.html" class="mnt-link">'
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
             '坎 · 坤 · 震 · 巽 已成篇</text>')
    o.append("</svg>")
    return "".join(o)


def _hero_wheel():
    """首屏背景：二十四山转盘。纯装饰，不可交互，不抢标题。

    ⚠️ 方位有含义：二十四山（w-outer）与八卦（w-gua）两层**永远静止**，
    子在下、午在上、乾在右下，跟着转就把方位读错了。
    「在转」的观感全部交给装饰层：刻度环、星点环、彗尾游标、
    环带光扫、柔光环与光晕，各走各的周期，错开才像仪器在运转。
    缩放由 script.js 按滚动位置调 --hs，动画不碰 svg 本身的 transform。
    """
    cx = cy = 400.0
    R_LAB, R_OUT, R_MID, R_IN = 334.0, 374.0, 300.0, 262.0
    o = ['<svg viewBox="0 0 800 800" role="presentation">']

    # 光晕与柔光滤镜。滤镜只挂在静态层上，动画一律只动 transform / opacity，
    # 否则每帧都要重算整张大圆的 blur，滚动时必掉帧。
    o.append('<defs>'
             '<radialGradient id="hw-halo" cx="50%" cy="50%" r="50%">'
             '<stop offset="0%" stop-color="#4aa2b6" stop-opacity=".30"/>'
             '<stop offset="34%" stop-color="#2c6a7c" stop-opacity=".26"/>'
             '<stop offset="70%" stop-color="#1c4453" stop-opacity=".13"/>'
             '<stop offset="100%" stop-color="#1c4453" stop-opacity="0"/>'
             '</radialGradient>'
             '<radialGradient id="hw-core" cx="50%" cy="50%" r="50%">'
             '<stop offset="0%" stop-color="#f0d9a6" stop-opacity=".44"/>'
             '<stop offset="42%" stop-color="#c9a86a" stop-opacity=".18"/>'
             '<stop offset="100%" stop-color="#c9a86a" stop-opacity="0"/>'
             '</radialGradient>'
             '<filter id="hw-soft" x="-60%" y="-60%" width="220%" height="220%">'
             '<feGaussianBlur stdDeviation="5"/>'
             '</filter>'
             '<filter id="hw-soft-lg" x="-60%" y="-60%" width="220%" height="220%">'
             '<feGaussianBlur stdDeviation="14"/>'
             '</filter>'
             '</defs>')
    # 中心暖光只收到 132：铺到 190 会在标题下方散成一团雾，反而显脏
    o.append(f'<g class="w-halo"><circle cx="{cx}" cy="{cy}" r="396" fill="url(#hw-halo)"/>'
             f'<circle cx="{cx}" cy="{cy}" r="132" fill="url(#hw-core)" opacity=".5"/></g>')

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

    # 柔光环：把三道主环线模糊复制一份，给盘一层"被照亮"的厚度。
    # 这层不做位移动画，只呼吸 opacity；滤镜套在静态层上才不会掉帧。
    o.append(f'<g class="w-glow" filter="url(#hw-soft)">'
             f'<circle cx="{cx}" cy="{cy}" r="{R_OUT}" fill="none" '
             'stroke="rgba(216,189,130,.62)" stroke-width="3.4"/>'
             f'<circle cx="{cx}" cy="{cy}" r="{R_MID}" fill="none" '
             'stroke="rgba(90,178,198,.50)" stroke-width="2.8"/>'
             f'<circle cx="{cx}" cy="{cy}" r="{R_IN}" fill="none" '
             'stroke="rgba(90,178,198,.34)" stroke-width="2.2"/>'
             '</g>')
    # 清晰的铜金细边压在柔光之上，金属质感来自这一层
    o.append(f'<g class="w-edge">'
             f'<circle cx="{cx}" cy="{cy}" r="{R_OUT}" fill="none" '
             'stroke="rgba(216,189,130,.26)" stroke-width="1"/>'
             f'<circle cx="{cx}" cy="{cy}" r="{R_OUT + 7}" fill="none" '
             'stroke="rgba(216,189,130,.10)" stroke-width=".8"/>'
             '</g>')

    # 星点环：一圈极淡虚线 + 八个方位亮点，反向慢转。
    # 只放装饰点、不放文字——山与卦的方位有含义，转了就读错。
    orb = ['<g class="w-orbit">',
           f'<circle cx="{cx}" cy="{cy}" r="390" fill="none" '
           'stroke="rgba(216,189,130,.20)" stroke-width="1" stroke-dasharray="1.5 11"/>']
    for k in range(8):
        x, y = _polar(cx, cy, 390, k * 45 + 22.5)
        orb.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.6" '
                   'fill="rgba(232,205,148,.55)" filter="url(#hw-soft)"/>')
        orb.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.7" '
                   'fill="rgba(255,240,206,.92)"/>')
    orb.append('</g>')
    o.append("".join(orb))

    # 铜盘刻线：给发光环补上罗盘该有的「形制」。
    # 原先只有刻度环 + 光晕，观感像星盘；这一层是静止的铜色同心圈、
    # 二十四道分格线与一圈密刻度，让盘读起来是一面铜罗盘。
    # ⚠️ 纯静态、不参与任何动画，也不写字——方位文字仍在下面两层，永不旋转。
    plate = ['<g class="w-plate">']
    for r, op in ((R_MID + 8, ".13"), (R_MID + 20, ".09"),
                  (R_LAB + 20, ".12"), (R_LAB + 34, ".16"),
                  (R_LAB + 48, ".10"), (R_OUT - 12, ".08")):
        plate.append(f'<circle cx="{cx}" cy="{cy}" r="{r:.0f}" fill="none" '
                     f'stroke="rgba(216,189,130,{op})" stroke-width=".8"/>')
    for k in range(24):
        a = k * 15 - 7.5 + ROT
        x1, y1 = _polar(cx, cy, R_MID + 8, a)
        x2, y2 = _polar(cx, cy, R_LAB + 48, a)
        plate.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     f'stroke="rgba(216,189,130,.14)" stroke-width=".8"/>')
    for deg in range(0, 360, 2):
        if deg % 10 == 0:
            r1, r2, op = R_LAB + 44, R_LAB + 52, ".24"
        else:
            r1, r2, op = R_LAB + 47, R_LAB + 52, ".10"
        x1, y1 = _polar(cx, cy, r1, deg)
        x2, y2 = _polar(cx, cy, r2, deg)
        plate.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     f'stroke="rgba(216,189,130,{op})" stroke-width=".6"/>')
    plate.append('</g>')
    o.append("".join(plate))

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
        col = "rgba(216,189,130,.96)" if hit else "rgba(255,255,255,.52)"
        wgt = ' font-weight="600"' if hit else ""
        fs = 15 if hit else 14
        out.append(f'<g transform="rotate({a:.2f} {cx} {cy})">'
                   f'<text x="{cx}" y="{cy - R_LAB + 5:.1f}" text-anchor="middle" '
                   f'font-family="Songti SC,serif" font-size="{fs}" fill="{col}"{wgt}>'
                   f'{m["name"]}</text></g>')
    out.append('</g>')
    o.append("".join(out))

    # 内环：八卦（静止，方位不可转）
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
        col = "rgba(216,189,130,.94)" if g["studied"] else "rgba(255,255,255,.48)"
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

    # 中心光核：铜金脉冲。不透明度压得很低，别把正中那段宣言盖住。
    o.append(f'<g class="w-core">'
             f'<circle cx="{cx}" cy="{cy}" r="72" fill="url(#hw-core)"/>'
             f'<circle cx="{cx}" cy="{cy}" r="30" fill="none" '
             'stroke="rgba(216,189,130,.22)" stroke-width="1"/>'
             f'<circle cx="{cx}" cy="{cy}" r="48" fill="none" '
             'stroke="rgba(216,189,130,.13)" stroke-width=".8" stroke-dasharray="2 8"/>'
             f'<circle cx="{cx}" cy="{cy}" r="7" fill="none" '
             'stroke="rgba(240,217,166,.55)" stroke-width="1.2"/>'
             f'<circle cx="{cx}" cy="{cy}" r="3" fill="#f0d9a6" filter="url(#hw-soft)"/>'
             f'<circle cx="{cx}" cy="{cy}" r="1.6" fill="#fff4d8"/>'
             '</g>')

    # 内层青色光弧：与外层金色游标反向、慢一档。作用是让任一时刻盘上
    # 都有一道光在走（外层转到上下会被首屏裁掉），也把内外两层的反向
    # 转动显出来。亮度只取外层一半，不做第二主角。
    r2, c2 = R_MID - 4, 250.0
    inner = ['<g class="w-comet-2">']
    inner.append(f'<path d="{_arc(cx, cy, r2, c2 - 52, c2 + 1)}" fill="none" '
                 'stroke="rgba(90,178,198,.20)" stroke-width="8" '
                 'stroke-linecap="round" filter="url(#hw-soft-lg)"/>')
    for i in range(8):
        a0 = c2 - 48 + i * 6
        a1 = a0 + 6.3
        t = (i + 1) / 8
        op = 0.03 + 0.46 * t ** 2
        w = 0.8 + 1.6 * t ** 2
        inner.append(f'<path d="{_arc(cx, cy, r2, a0, a1)}" fill="none" '
                     f'stroke="rgba(140,208,224,{op:.3f})" stroke-width="{w:.2f}" '
                     'stroke-linecap="round"/>')
    ix, iy = _polar(cx, cy, r2, c2 + 1)
    inner.append(f'<circle cx="{ix:.1f}" cy="{iy:.1f}" r="5" '
                 'fill="rgba(140,208,224,.45)" filter="url(#hw-soft)"/>')
    inner.append(f'<circle cx="{ix:.1f}" cy="{iy:.1f}" r="1.8" fill="#cdeef5"/>')
    inner.append('</g>')
    o.append("".join(inner))

    # 彗尾游标：绕最外环跑的一道渐隐光弧，是"盘在转"最直观的线索。
    # 18s 一圈，比刻度环快得多，但只是一段细光，不抢文字。
    # ⚠️ 亮头起点必须在右侧（100°）：盘比首屏高，正上方那段被 hero 的
    # overflow:hidden 裁掉，若从 0° 起转，刚打开页面根本看不见游标。
    c0 = 100.0
    comet = ['<g class="w-comet">']
    comet.append(f'<path d="{_arc(cx, cy, R_OUT + 7, c0 - 45, c0 + 1)}" fill="none" '
                 'stroke="rgba(216,189,130,.34)" stroke-width="10" '
                 'stroke-linecap="round" filter="url(#hw-soft-lg)"/>')
    for i in range(8):
        a0 = c0 - 41 + i * 5
        a1 = a0 + 5.3
        t = (i + 1) / 8
        op = 0.05 + 0.85 * t ** 2.1
        w = 1.0 + 2.6 * t ** 2
        comet.append(f'<path d="{_arc(cx, cy, R_OUT + 7, a0, a1)}" fill="none" '
                     f'stroke="rgba(240,217,166,{op:.3f})" stroke-width="{w:.2f}" '
                     'stroke-linecap="round"/>')
    hx, hy = _polar(cx, cy, R_OUT + 7, c0 + 1)
    comet.append(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="7" '
                 'fill="rgba(240,217,166,.62)" filter="url(#hw-soft)"/>')
    comet.append(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="2.6" fill="#fff4d8"/>')
    comet.append('</g>')
    o.append("".join(comet))
    o.append("</svg>")
    return "".join(o)


def _map_side():
    ms = mountains()
    taught = [m["name"] for m in ms if m["st"] == "taught"]
    full_names = "　".join(m["name"] for m in ms if m["st"] == "full")
    n_none = sum(1 for m in ms if m["st"] == "none")
    items = ['<li><span class="sw full"></span><div><b>已成篇</b>'
             f'<em>{full_names}</em><p>正文写全，图上可点，进正文。</p></div></li>']
    # taught 为空时不要摆一个空图例（曾经出现「已开讲」后面空一片的尴尬）
    if taught:
        items.append(
            '<li><span class="sw taught"></span><div><b>已开讲</b>'
            f'<em>{"　".join(taught)}</em><p>课上讲到了，正文页还在补。</p></div></li>')
    items.append(
        '<li><span class="sw none"></span><div><b>未开讲</b>'
        f'<em>其余 {n_none} 山</em><p>这一轮课没讲到，图上留位。</p></div></li>')
    return (
        '<h3>这张图怎么看</h3>'
        '<ul class="lg">' + "".join(items) + '</ul>'
        '<div class="map-note">'
        '<p><b>卦和山不是两套东西。</b>卦管一段四十五度的格局，山是这段格局里十五度的落点。'
        '说「坎卦」，讲的是水与肾的总体倾向；落到「壬山」，才说得上财商、说得出应期。</p>'
        '<p>下面四种读法指向同一份内容：按卦读，是把三山放在一起看关系与分工；'
        '按山读，是带着一座山的问题直接找答案；按导图读先看骨架，按经文读回到原句两栏对读。</p>'
        '</div>'
    )


# ---------- 四种读法 ----------

def _by_gua(slan):
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
            if st == "full" and slan.get(name):
                rows.append(f'<a class="row full" href="{slan[name]}.html">'
                            f'<b>{name}</b><span>{label}</span><i>已成篇</i></a>')
            else:
                rows.append(f'<span class="row {st}"><b>{name}</b>'
                            f'<span>{label}</span>'
                            f'<i>{STAT_LABEL[st]}</i></span>')
        if g["studied"]:
            done = bool(g["shan"]) and all(s[2] == "full" for s in g["shan"])
            tag = ('<span class="g8-tag on">已成篇</span>' if done
                   else '<span class="g8-tag on">已开讲</span>')
        else:
            tag = '<span class="g8-tag">未开讲</span>'
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


def _by_shan(slan):
    cols = []
    for g in ALL_GUA:
        rows = []
        for i in range(3):
            name = g["sz"][i]
            label, st = (g["shan"][i][1], g["shan"][i][2]) if g["shan"] else ("", "none")
            tip = name + "山" + ("　" + label if label else "")
            inner = f'<b>{name}</b><i>{STAT_LABEL[st]}</i>'
            if st == "full" and slan.get(name):
                rows.append(f'<a class="mc full" href="{slan[name]}.html" title="{tip}">{inner}</a>')
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
    stat = [f'<span><i class="sw full"></i>已成篇 {n_full} 山</span>']
    if n_taught:
        stat.append(f'<span><i class="sw taught"></i>已开讲 {n_taught} 山</span>')
    stat.append(f'<span><i class="sw none"></i>未开讲 {n_none} 山</span>')
    legend = ('<div class="m24-foot">' + "".join(stat) +
              '<span class="m24-tip">一列一卦，自上而下为前山、中山、后山；'
              '卦名与山名同字的（艮、巽、坤、乾）指的是那一山，不是整卦；'
              '列序从坎起按课程排，不是盘面方位。</span>'
              '</div>')
    return '<div class="m24">' + "".join(cols) + "</div>" + legend


# 四种读法 · 后两种（Ⅳ 导图 / Ⅴ 经文）共用一套入口卡。
# 条目从 build_minds() / build_jingwen() 的返回值来，日后加一卦自动多一张，
# 不在模板里写死页名。

def _gua_color(gua, fallback):
    return next((g["color"] for g in ALL_GUA if g["g"] == gua), fallback)


def _way_card(no, title, desc, href, go, color):
    return (
        f'<a class="way" style="--wc:{color}" href="{href}">'
        f'<span class="n">{no}</span>'
        f'<b>{html.escape(title)}</b>'
        f'<span class="d">{desc}</span>'
        f'<span class="go">{go}'
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none">'
        '<path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" stroke="currentColor" stroke-width="1.6" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg></span></a>'
    )


def _by_mind(mind_pages):
    cards = [
        _way_card(f'Ⅳ-{m["order"]:02d}', m["title"],
                  f'{m["nodes"]} 个节点　·　先看这一卦的骨架与层级',
                  m["slug"] + ".html", "看这张导图",
                  _gua_color(m.get("gua", ""), "#3f6b7a"))
        for m in mind_pages
    ]
    cards.append(_way_card(
        "Ⅳ 线", "导图线 · 全部",
        "一卦一图，逐层展开；图下附本卦经文，与正文同一份源",
        "section-Ⅳ.html", "进入导图线", "#3f6b7a"))
    return ('<div class="ways-grid">' + "".join(cards) + '</div>'
            + '<p class="ways-foot">导图只给骨架与层级，细目仍回 Ⅱ 卦山线。'
              '先立住一卦三山的分工，再带着问题回到正文。</p>')


def _by_jw(jw_pages, pages):
    cards = [
        _way_card(f'Ⅴ-{j["order"]:02d}', j["title"],
                  f'{html.escape(j["lead"])}<br>卦体加三山，左右两栏并排对读',
                  j["slug"] + ".html", "对读这一卦",
                  _gua_color(j.get("gua", ""), "#5c4a72"))
        for j in jw_pages
    ]
    cards.append(_way_card(
        "Ⅴ 线", "经文线 · 全部",
        "全站经文集中在这里：一卦一页，四篇并排；没有的留 〔待补〕",
        "section-Ⅴ.html", "进入经文线", "#5c4a72"))
    total = next((p["slug"] for p in pages
                  if p["section"] == "Ⅲ-作业线" and "经文总表" in p["title"]), None)
    more = (f'另见 <a href="{total}.html">Ⅲ 作业线《经文总表》</a>，按卦通读一整份。'
            if total else "")
    return ('<div class="ways-grid">' + "".join(cards) + '</div>'
            + '<p class="ways-foot">左栏「我的经文」＝个人自编，右栏「老师经文」＝老师的版本；'
              '老师没有给的一律留 〔待补〕，不代写。' + more + '</p>')


def _stats(pages, mind_pages):
    n_full = sum(1 for m in mountains() if m["st"] == "full")
    items = [(24, "山 · 全图"), (8, "宫 · 分卦"),
             (n_full, "山 · 已成篇"), (len(pages), "篇 · 正文")]
    return "".join(f'<div class="st"><b>{n}</b><em>{lab}</em></div>' for n, lab in items)


def _parts(pages, mind_pages, jw_pages):
    meta = {
        "Ⅰ": ("按课次，一课不落",
               "老师每节课不只讲山，理法、技法、案例、答疑都在这里，按讲课顺序记。",
               ["理法与砂水本质", "技法与做局", "案例复盘与答疑"], "篇"),
        "Ⅱ": ("一山一页，七段讲透",
 "每山固定七段：山性、见水、见砂、形煞叠加、技法布局、经文、自查与理解。",
 ["每山一句论断", "三版经文对照", "我的经文与老师经文两栏"], "篇"),
        "Ⅲ": ("只引用，不重复",
               "正文里已讲过的只给锚点。这里只写老师批语、未做题目拆解、题目到章节的映射表。",
               ["老师批语汇总", "未做题面拆解", "题目映射表"], "篇"),
        "Ⅳ": ("一卦一张骨架图",
               "把一卦三山的层级收成一张图：先看主干，再逐层展开。与正文同一套内容，不是另一份材料。",
               ["逐层展开的节点", "与卦山线一一对应", "图下附本卦经文"], "张"),
        "Ⅴ": ("一卦一页，两栏对读",
               "全站经文集中在这里：一卦一页，每篇左边我的、右边老师的，并排比。空着的框先留着。",
               ["卦体加三山逐页排开", "我的与老师并排对照", "全站只此一份，不另抄一遍"], "页"),
    }
    cards = []
    for d, num, short, desc, color in SECTIONS:
        if num == "附":
            continue
        if d == MIND_SECTION:
            cnt, unit = len(mind_pages), "张"
        elif d == JINGWEN_SECTION:
            cnt, unit = len(jw_pages), "页"
        else:
            cnt, unit = len([p for p in pages if p["section"] == d]), "篇"
        title, text, bullets, unit = meta.get(num, (short, desc, [], unit))
        lis = "".join(f"<li>{b}</li>" for b in bullets)
        cards.append(
            f'<a class="part" href="section-{num}.html">'
            f'<div class="rnum">{num}</div>'
            f'<h3>{title}</h3>'
            f'<p class="desc">{text}</p>'
            f'<ul>{lis}</ul>'
            f'<span class="go">{(str(cnt) + " " + unit) if cnt else "待整理"}　进入'
            f'<svg width="14" height="14" viewBox="0 0 16 16" fill="none">'
            f'<path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round"/></svg></span></a>'
        )
    return "".join(cards)


def _recent(pages, mind_pages, jw_pages):
    """五条线轮流取样，避免首页只出现课程线。"""
    if not pages:
        return '<div class="empty-note">还没有正文。</div>'
    groups = {}
    for p in pages:
        groups.setdefault(p["section"], []).append(p)
    # Ⅳ 导图线不在 内容/ 里，单独补一组，首页才能看到它
    if mind_pages:
        groups[MIND_SECTION] = [
            {"slug": m["slug"], "title": m["title"], "num": "Ⅳ",
             "order": m["order"], "unit": "张"} for m in mind_pages
        ]
    # Ⅴ 经文线同理：页子从 经文/ 来，也不在 内容/ 里
    if jw_pages:
        groups[JINGWEN_SECTION] = [
            {"slug": j["slug"], "title": j["title"], "num": "Ⅴ",
             "order": j["order"], "unit": "页"} for j in jw_pages
        ]
    picked, i = [], 0
    while len(picked) < 6 and any(len(v) > i for v in groups.values()):
        for d, num, short, desc, color in SECTIONS:
            if num == "附":
                continue          # 附录不是一条线，不进「成篇内容」轮换
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
            # 标题与「第几篇」之间拉一条引导线，宽屏下才不会在中间空一大段
            f'<span class="lead" aria-hidden="true"></span>'
            f'<span class="d">第 {p["order"]:02d} {p.get("unit", "篇")}</span></a>'
        )
    return "".join(rows)


def _seal():
    """朱砂方印。纯 SVG 画方框与印文，不依赖字体图标，不会出现豆腐块。"""
    return ('<svg viewBox="0 0 64 64" aria-hidden="true">'
            '<rect x="1.5" y="1.5" width="61" height="61" rx="5" '
            'fill="#a3543a" stroke="#8d452e" stroke-width="1.5"/>'
            '<rect x="6.5" y="6.5" width="51" height="51" rx="3" fill="none" '
            'stroke="rgba(255,246,238,.62)" stroke-width="1.2"/>'
            '<text x="32" y="28" text-anchor="middle" fill="#fff6ee" '
            'font-family="Songti SC,serif" font-size="20" font-weight="600">金鎖</text>'
            '<text x="32" y="50" text-anchor="middle" fill="#fff6ee" '
            'font-family="Songti SC,serif" font-size="20" font-weight="600">玉關</text>'
            '</svg>')


def _verse_leaf(jw_pages):
    """首页「经文一叶」：从经文唯一源取壬山见砂第一联，一字不改。

    原句不写死在模板里——经文只有一个源，改了 source 首页自动跟随。
    这里是首页内的一屏展示带，不是新页面，也不复述整篇经文。
    """
    with open(os.path.join(ROOT, "经文", "壬山.md"), encoding="utf-8") as f:
        lines = [l.strip() for l in f]
    mine, in_mine = [], False
    for l in lines:
        if l.startswith("## "):
            in_mine = (l[3:].strip() == "我的经文")
            continue
        if in_mine and l.startswith("> "):
            mine.append(l[2:].strip())
    if len(mine) < 2:
        raise RuntimeError("经文一叶：壬山.md 里取不到两句经文")
    a, b = html.escape(mine[0]), html.escape(mine[1])
    first = f'{jw_pages[0]["slug"]}.html' if jw_pages else "section-Ⅴ.html"
    return (
        '<div class="leaf-in">'
        '<div class="leaf-side">'
        '<span class="leaf-kicker">经文一叶</span>'
        '<span class="leaf-side-sub">一山十五度　·　原句不改</span>'
        '</div>'
        f'<div class="leaf-verse"><p>{a}</p><p>{b}</p></div>'
        '<div class="leaf-note">'
        '<span class="leaf-tag">Ⅴ 经文线　·　壬山　·　见砂</span>'
        '<p>我的经文与老师经文两栏并排，一卦一页逐篇对读。</p>'
        f'<a href="{first}">读全篇　→</a>'
        f'<span class="seal">{_seal()}</span>'
        '</div>'
        '</div>'
    )


def build_index(pages, mind_pages, jw_pages):
    first_slug = pages[0]["slug"] if pages else "index"
    slan = shan_slug_map(pages)
    page = fill(tpl("index.html"),
                nav=build_nav(""),
                stats=_stats(pages, mind_pages),
                parts=_parts(pages, mind_pages, jw_pages),
                compass=_compass(slan),
                hero_wheel=_hero_wheel(),
                map_side=_map_side(),
                bygua=_by_gua(slan),
                byshan=_by_shan(slan),
                bymind=_by_mind(mind_pages),
                byjw=_by_jw(jw_pages, pages),
                recent=_recent(pages, mind_pages, jw_pages),
                verse_leaf=_verse_leaf(jw_pages),
                seal=_seal(),
                first_link=f"{first_slug}.html",
                foot_sections=foot_sections(),
                page_count=len(pages),
                mind_count=len(mind_pages),
                drawer=build_drawer("__home__",
                                    '<p class="side-title">本 页</p><ul class="d-sub">'
                                    '<li><a href="#shan"><span class="n">图</span>'
                                    '<span>二十四山全图</span></a></li>'
                                    '<li><a href="#read"><span class="n">读</span>'
                                    '<span>四种读法</span></a></li>'
                                    '<li><a href="#lines"><span class="n">体</span>'
                                    '<span>五条线怎么分</span></a></li></ul>'),
                )
    open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8").write(page)

    # ---- 给 style.css 的引用打内容哈希 ----
    # GitHub Pages 的 CDN 会把 style.css 缓存十几分钟，改了样式用户刷新还是旧版，
    # 看上去像"没生效"。用 css 内容的 md5 做查询串：样式一变地址就变，
    # 浏览器当新文件拿，一次构建即可生效，不用等缓存过期。
    # 正则允许已有 ?v=xxx，所以重复构建是幂等的。
    css_file = os.path.join(OUT_DIR, "style.css")
    if os.path.exists(css_file):
        ver = hashlib.md5(open(css_file, "rb").read()).hexdigest()[:8]
        pat = re.compile(r'href="style\.css(?:\?v=[0-9a-f]+)?"')
        for fn in glob.glob(os.path.join(OUT_DIR, "*.html")):
            with open(fn, encoding="utf-8") as fh:
                src = fh.read()
            out = pat.sub(f'href="style.css?v={ver}"', src)
            if out != src:
                with open(fn, "w", encoding="utf-8") as fh:
                    fh.write(out)



if __name__ == "__main__":
    t0 = time.time()
    build()
    print(f"耗时 {time.time()-t0:.1f}s")
