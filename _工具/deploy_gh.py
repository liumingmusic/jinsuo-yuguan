#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本项目推到 GitHub，并开 Pages。

为什么要绕开 git：本机 `git push`（HTTPS+token 或 SSH）会无输出挂死数分钟，
`git pull` 在沙箱里会被 SIGKILL。这里直接走 REST objects API，只上传不下载历史。

分支分工：
  main      —— 源码（内容/脑图/_工具/导出/_数据 的 md 与 json）
  gh-pages  —— 站点/ 的构建产物，放在分支根目录，Pages 服务它

用法：
  python3 _工具/deploy_gh.py            # 建仓（若不存在）+ 推两个分支 + 开 Pages
  python3 _工具/deploy_gh.py --site     # 只重推 gh-pages（改了内容重建后跑这个）
  python3 _工具/deploy_gh.py --dry      # 只列出将上传的文件，不联网
"""

import os
import sys
import json
import base64
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWNER = "liumingmusic"
REPO = "jinsuo-yuguan"
KEYCHAIN_ACCOUNT = "7837372"
API = "https://api.github.com"

# 源码分支不收录：站点产物（走 gh-pages）、课件原始图片（34M，且属讲义扫描件）
SRC_EXCLUDE_DIRS = {"站点", "_数据/图片"}


def token():
    out = subprocess.check_output(
        ["security", "find-internet-password", "-s", "github.com",
         "-a", KEYCHAIN_ACCOUNT, "-w"], text=True).strip()
    if not out:
        raise SystemExit("取不到 GitHub token")
    return out


TOKEN = None


def api(method, path, body=None, ok=(200, 201, 204)):
    url = path if path.startswith("http") else API + path
    # 本机沙箱会拦 python urllib 的 TLS（UNEXPECTED_EOF_WHILE_READING），
    # 同一 shell 里 curl 却正常，所以统一走 curl 子进程发请求。
    cmd = ["curl", "-sS", "-X", method, url,
           "-H", "Authorization: Bearer " + TOKEN,
           "-H", "Accept: application/vnd.github+json",
           "-H", "User-Agent: jinsuo-deploy",
           "-w", "\n%{http_code}"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json",
                "--data-binary", json.dumps(body)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        raise SystemExit("curl %s %s -> rc=%d %s"
                         % (method, path, out.returncode, out.stderr[:300]))
    # rpartition 返回 (头, 分隔符, 尾)：-w 把状态码写在最后，正文在前
    payload, _, code_s = out.stdout.rpartition("\n")
    try:
        code = int(code_s.strip())
    except ValueError:
        raise SystemExit("curl %s %s -> 无法解析响应: %s"
                         % (method, path, out.stdout[:300]))
    if code not in ok:
        raise SystemExit("API %s %s -> %s\n%s"
                         % (method, path, code, payload[:400]))
    try:
        return json.loads(payload) if payload.strip() else {}
    except json.JSONDecodeError:
        return {}


def walk(base, excludes=()):
    """返回 [(相对 base 的路径, 本地绝对路径)]。excludes 是相对 base 的目录路径。"""
    items = []
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = os.path.relpath(dirpath, base).replace(os.sep, "/")
        prefix = "" if rel_dir == "." else rel_dir + "/"
        keep = []
        for d in sorted(dirnames):
            if (prefix + d) in excludes or d.startswith("."):
                continue
            keep.append(d)
        dirnames[:] = keep
        for fn in sorted(filenames):
            if fn == ".DS_Store" or fn.endswith(".pyc"):
                continue
            ab = os.path.join(dirpath, fn)
            items.append((os.path.relpath(ab, base).replace(os.sep, "/"), ab))
    return items


def upload_blob(ab):
    with open(ab, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    res = api("POST", "/repos/%s/%s/git/blobs" % (OWNER, REPO),
              {"content": b64, "encoding": "base64"})
    return res["sha"]


def push_branch(branch, files, message, prune=True):
    """把 files 作为该分支的完整内容推上去（整树替换，不做 diff）。

    prune=True 时会把远端已有、而本地这次没有的路径一并删掉（sha: null）。
    否则改名/删文件只会新增，旧路径永远留在分支上（脑图改编号后就踩过）。
    """
    ref_path = "/repos/%s/%s/git/ref/heads/%s" % (OWNER, REPO, branch)
    parent = None
    try:
        ref = api("GET", ref_path)
        parent = ref["object"]["sha"]
    except SystemExit:
        parent = None

    base_tree = None
    if parent:
        base_tree = api("GET", "/repos/%s/%s/git/commits/%s" % (OWNER, REPO, parent))["tree"]["sha"]

    print("  上传 %d 个 blob ..." % len(files))
    with ThreadPoolExecutor(max_workers=8) as ex:
        shas = list(ex.map(lambda it: upload_blob(it[1]), files))

    entries = [{"path": rel, "mode": "100644", "type": "blob", "sha": sha}
               for (rel, _), sha in zip(files, shas)]

    if prune and base_tree:
        keep = {rel for rel, _ in files}
        tree_now = api("GET", "/repos/%s/%s/git/trees/%s?recursive=1"
                       % (OWNER, REPO, base_tree))
        gone = [e["path"] for e in tree_now.get("tree", [])
                if e["type"] == "blob" and e["path"] not in keep]
        for p in gone:
            entries.append({"path": p, "mode": "100644", "type": "blob", "sha": None})
        if gone:
            print("  删除远端多余 %d 个（改名/废弃的旧路径）" % len(gone))
            for p in gone:
                print("    - " + p)

    tree = api("POST", "/repos/%s/%s/git/trees" % (OWNER, REPO),
               {"tree": entries, "base_tree": base_tree} if base_tree
               else {"tree": entries})
    # GitHub 偶发「树已创建但还没就绪」：紧接着建 commit 会报 Tree SHA does not exist。
    # 隔两秒重试一次即可，多数情况第一次就过。
    commit = None
    for attempt in range(2):
        try:
            commit = api("POST", "/repos/%s/%s/git/commits" % (OWNER, REPO),
                         {"message": message, "tree": tree["sha"],
                          "parents": [parent] if parent else []})
            break
        except SystemExit as e:
            if attempt == 0 and "Tree SHA does not exist" in str(e):
                print("  树未就绪，2 秒后重试建 commit ...")
                time.sleep(2)
                continue
            raise

    if parent:
        # 注意：GitHub 这两个端点不对称 —— GET 用单数 /git/ref/，PATCH 用复数 /git/refs/
        api("PATCH", "/repos/%s/%s/git/refs/heads/%s" % (OWNER, REPO, branch),
            {"sha": commit["sha"], "force": True})
    else:
        api("POST", "/repos/%s/%s/git/refs" % (OWNER, REPO),
            {"ref": "refs/heads/" + branch, "sha": commit["sha"]})
    print("  %s -> %s (%d 文件)" % (branch, commit["sha"][:10], len(files)))
    return commit["sha"]


def ensure_repo():
    try:
        api("GET", "/repos/%s/%s" % (OWNER, REPO))
        print("仓库已存在：%s/%s" % (OWNER, REPO))
        return
    except SystemExit:
        pass
    print("创建仓库 %s/%s ..." % (OWNER, REPO))
    api("POST", "/user/repos", {
        "name": REPO,
        "description": "金锁玉关 · 二十四山研习库 —— 课程线 / 卦山线 / 作业线 / 附录，单一 Markdown 源生成网站与思维导图",
        "private": False,
        "has_issues": True,
        "has_wiki": False,
        "has_projects": False,
    })


def ensure_pages():
    path = "/repos/%s/%s/pages" % (OWNER, REPO)
    try:
        p = api("GET", path)
        if p.get("source", {}).get("branch") != "gh-pages":
            api("PUT", path, {"source": {"branch": "gh-pages", "path": "/"}})
            print("Pages 源改为 gh-pages /")
        else:
            print("Pages 已开启：%s" % p.get("html_url", ""))
        return p
    except SystemExit:
        pass
    print("开启 Pages（gh-pages 分支 / 根目录）...")
    try:
        p = api("POST", path, {"source": {"branch": "gh-pages", "path": "/"}})
        print("Pages 已创建：%s" % p.get("html_url", ""))
        return p
    except SystemExit as e:
        print("开启失败：%s" % e)
        return {}


def main():
    global TOKEN
    site_only = "--site" in sys.argv
    dry = "--dry" in sys.argv
    TOKEN = token()

    src = walk(ROOT, SRC_EXCLUDE_DIRS)
    site_dir = os.path.join(ROOT, "站点")
    site = walk(site_dir)
    if not os.path.isdir(site_dir):
        raise SystemExit("没有 站点/ 目录，先跑 python3 _工具/build.py")

    if dry:
        print("源码文件 %d 个：" % len(src))
        for rel, _ in src[:200]:
            print("   ", rel)
        print("站点文件 %d 个：" % len(site))
        for rel, _ in site[:200]:
            print("   ", rel)
        return

    if not site_only:
        ensure_repo()
        print("推 main（源码）...")
        push_branch("main", src, "金锁玉关研习库：课程线 12 讲 / 卦山线九山 / 作业线 11 次 / 附录 5 篇 / 脑图 4 张")
    print("推 gh-pages（站点）...")
    push_branch("gh-pages", site, "发布站点：%d 个页面" % len(site))
    if not site_only:
        ensure_pages()

    print("\n完成。站点地址（构建需 1–2 分钟）：")
    print("  https://%s.github.io/%s/" % (OWNER.lower(), REPO))


if __name__ == "__main__":
    main()
