#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md2mind.py — 把 Markdown 缩进大纲转成思维导图通用格式。

支持输出：
  .xmind  XMind Zen / XMind 2020+ 原生格式（zip: content.json + metadata.json + manifest.json）
  .mm     FreeMind / FreeMind 兼容（纯 XML，几乎所有脑图工具都能导入）
  .opml   OPML 大纲（大纲类工具通用）

只用 Python 标准库，不依赖第三方包。

用法：
  python3 md2mind.py input.md output.xmind
  python3 md2mind.py input.md output.mm
  python3 md2mind.py 目录/ 输出目录/ --all
"""
import sys, os, re, json, zipfile, uuid, time, glob
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape


# 与 build.py 保持一致：思维导图只按卦梳理，编号 00 的总览图不导出（md 保留不删）。
# 只在目录模式下跳过；明确指定单个文件时仍然转换。
HIDE_PREFIX = ("00",)


# ---------- Markdown 大纲解析 ----------

def parse_outline(md_text):
    """把 markdown 转成嵌套 dict：{'title':..., 'children':[...]}。

    识别：
      # ~ ###### 标题      -> 按标题层级嵌套
      - / * / + / 1. 列表  -> 按缩进嵌套
      > 引用               -> 作为节点备注（并入标题或子节点）
    跳过：代码块、表格、分隔线、空行。
    """
    lines = md_text.split("\n")
    root = {"title": None, "children": []}
    # 标题栈：[(level, node)]
    head_stack = []
    # 列表栈：[(indent, node)]
    list_stack = []
    in_code = False

    def top():
        """当前最深的容器节点。"""
        if list_stack:
            return list_stack[-1][1]
        if head_stack:
            return head_stack[-1][1]
        return root

    for raw in lines:
        line = raw.rstrip("\n")
        s = line.strip()

        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not s:
            continue
        if re.fullmatch(r"[-*_]{3,}", s):
            continue
        if s.startswith("|"):
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            level = len(m.group(1))
            title = clean(m.group(2))
            if not title:
                continue
            node = {"title": title, "children": []}
            if root["title"] is None:
                root["title"] = title
                root["children"] = node["children"]
                head_stack = [(1, root)]
                list_stack = []
                continue
            # 弹出层级 >= 当前级别的标题
            while head_stack and head_stack[-1][0] >= level:
                head_stack.pop()
            parent = head_stack[-1][1] if head_stack else root
            parent["children"].append(node)
            head_stack.append((level, node))
            list_stack = []
            continue

        m = re.match(r"^([ \t]*)(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            indent = len(m.group(1).replace("\t", "  "))
            title = clean(m.group(2))
            if not title:
                continue
            node = {"title": title, "children": []}
            while list_stack and list_stack[-1][0] >= indent:
                list_stack.pop()
            parent = list_stack[-1][1] if list_stack else top()
            parent["children"].append(node)
            list_stack.append((indent, node))
            continue

        # 普通段落：接到最近节点后面当备注（不新建节点）
        if s.startswith(">"):
            s = s.lstrip("> ").strip()
        if s:
            tgt = top()
            tgt.setdefault("note", "")
            tgt["note"] = (tgt["note"] + " " + s).strip()

    return root


def clean(t):
    """去掉 markdown 行内标记，保留文字。"""
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    t = re.sub(r"`(.+?)`", r"\1", t)
    t = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", t)
    t = re.sub(r"!\[.*?\]\(.*?\)", "", t)
    return t.strip()


# ---------- XMind ----------

def node_count(n):
    return 1 + sum(node_count(c) for c in n["children"])


def to_xmind_topic(n, is_root=False, structure="org.xmind.ui.logic.right"):
    t = {
        "id": uuid.uuid4().hex,
        "title": n["title"] or "未命名",
    }
    if is_root:
        t["structureClass"] = structure
        t["class"] = "topic"
    if n.get("note"):
        t["notes"] = {"plain": {"content": n["note"]}}
    if n["children"]:
        t["children"] = {"attached": [to_xmind_topic(c) for c in n["children"]]}
    return t


def write_xmind(root, path, sheet_title=None):
    sheet = {
        "id": uuid.uuid4().hex,
        "class": "sheet",
        "title": sheet_title or "",
        "extensions": [],
        "topicPositioning": "fixed",
        "topicOverlapping": "overlap",
        "coreVersion": "2.0.0",
        "rootTopic": to_xmind_topic(root, is_root=True),
    }
    content = [sheet]
    metadata = {
        "modifier": "",
        "dataStructureVersion": "2",
        "creator": {"name": "md2mind", "version": "1.0"},
        "layoutEngineVersion": "3",
        "activeSheetId": sheet["id"],
    }
    manifest = {"file-entries": {"content.json": {}, "metadata.json": {}}}

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("content.json", json.dumps(content, ensure_ascii=False, indent=2))
        z.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False))
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
    return path


# ---------- FreeMind ----------

def to_freemind(n, parent_el):
    el = ET.SubElement(parent_el, "node", {"TEXT": n["title"] or "未命名"})
    if n.get("note"):
        rich = ET.SubElement(el, "richcontent", {"TYPE": "NOTE"})
        body = ET.SubElement(rich, "html")
        p = ET.SubElement(body, "body")
        pp = ET.SubElement(p, "p")
        pp.text = n["note"]
    for c in n["children"]:
        to_freemind(c, el)
    return el


def write_freemind(root, path):
    mm = ET.Element("map", {"version": "1.0.1"})
    to_freemind(root, mm)
    ET.indent(mm, space="  ")
    xml = ET.tostring(mm, encoding="unicode")
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(xml)
    return path


# ---------- OPML ----------

def to_opml(n, parent_el):
    el = ET.SubElement(parent_el, "outline", {"text": n["title"] or "未命名"})
    if n.get("note"):
        el.set("_note", n["note"])
    for c in n["children"]:
        to_opml(c, el)


def write_opml(root, path):
    opml = ET.Element("opml", {"version": "2.0"})
    head = ET.SubElement(opml, "head")
    t = ET.SubElement(head, "title")
    t.text = root["title"] or "大纲"
    body = ET.SubElement(opml, "body")
    to_opml(root, body)
    ET.indent(opml, space="  ")
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(ET.tostring(opml, encoding="unicode"))
    return path


# ---------- 入口 ----------

def convert(md_path, out_dir=None, formats=("xmind", "mm", "opml")):
    md = open(md_path, encoding="utf-8").read()
    root = parse_outline(md)
    if not root["title"]:
        root["title"] = os.path.splitext(os.path.basename(md_path))[0]
    base = os.path.splitext(os.path.basename(md_path))[0]
    out_dir = out_dir or os.path.dirname(md_path) or "."
    os.makedirs(out_dir, exist_ok=True)
    made = []
    if "xmind" in formats:
        made.append(write_xmind(root, os.path.join(out_dir, base + ".xmind"), sheet_title=root["title"]))
    if "mm" in formats:
        made.append(write_freemind(root, os.path.join(out_dir, base + ".mm")))
    if "opml" in formats:
        made.append(write_opml(root, os.path.join(out_dir, base + ".opml")))
    return root, made


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if not args:
        print(__doc__)
        return
    src = args[0]
    out_dir = args[1] if len(args) > 1 else None
    fmts = ("xmind", "mm", "opml")
    if "--xmind-only" in flags:
        fmts = ("xmind",)

    if os.path.isdir(src):
        files = sorted(f for f in glob.glob(os.path.join(src, "*.md"))
                       if not os.path.basename(f).startswith(HIDE_PREFIX))
        for f in files:
            root, made = convert(f, out_dir, fmts)
            print(f"{os.path.basename(f)}  {node_count(root)} 节点 -> " +
                  ", ".join(os.path.basename(m) for m in made))
    else:
        root, made = convert(src, out_dir, fmts)
        print(f"{os.path.basename(src)}  {node_count(root)} 节点 -> " +
              ", ".join(os.path.basename(m) for m in made))


if __name__ == "__main__":
    main()
