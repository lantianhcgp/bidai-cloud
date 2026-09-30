#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bidai.py — 笔袋官方网盘 gaojiua.com/cloud CLI

链路（全部实测通过）:
  搜索分享 -> info -> file/list -> 转存(import, 根目录 parent=-1)
  -> 自己空间 pre-download(签名直链) -> HTTP 下载

鉴权: Authorization: Bearer <token>  (token 存 ~/.bidai_token, 有效期到 2036 年)
必需头: AppFingerprint: bidai / PlatformName: H5
"""
import argparse
import datetime
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.gaojiua.com/release"
HOME = os.path.expanduser("~")
TOKEN_PATH = os.path.join(HOME, ".bidai_token")
CFG_PATH = os.path.join(HOME, ".bidai_config.json")
ROOT = -1                       # 根目录 parent_id
UA = ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

BASE_HDR = {
    "User-Agent": UA,
    "AppFingerprint": "bidai",
    "PlatformName": "H5",
    "SoftVersion": "8000",
    "Referer": "https://gaojiua.com/",
    "Accept": "application/json, text/plain, */*",
}


# ---------------------------------------------------------------- 基础设施
def load_token():
    if not os.path.exists(TOKEN_PATH):
        return None
    t = open(TOKEN_PATH).read().strip()
    return t or None


def save_token(t):
    with open(TOKEN_PATH, "w") as f:
        f.write(t)
    os.chmod(TOKEN_PATH, 0o600)


def load_cfg():
    if os.path.exists(CFG_PATH):
        try:
            return json.load(open(CFG_PATH))
        except Exception:
            return {}
    return {}


def save_cfg(cfg):
    with open(CFG_PATH, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    os.chmod(CFG_PATH, 0o600)


def call(path, method="GET", params=None, body=None, auth=True,
         timeout=60, raw=False):
    """返回 (status, data)。raw=True 时 data 为 bytes。"""
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in BASE_HDR.items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    tok = load_token()
    if auth:
        if not tok:
            return 401, {"detail": "no token: run `bidai.py login <phone> <code>`"}
        req.add_header("Authorization", "Bearer " + tok)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        payload = r.read()
        if raw:
            return r.status, payload
        try:
            return r.status, json.loads(payload.decode("utf-8", "ignore"))
        except Exception:
            return r.status, {"raw": payload[:500].decode("utf-8", "ignore")}
    except urllib.error.HTTPError as e:
        payload = e.read()
        if raw:
            return e.code, payload
        try:
            return e.code, json.loads(payload.decode("utf-8", "ignore"))
        except Exception:
            return e.code, {"detail": payload[:300].decode("utf-8", "ignore")}
    except Exception as e:
        return 0, {"detail": repr(e)}


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def ok(data, as_json=True, human=None):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
    else:
        print(human if human is not None else data)
    sys.exit(0)


def unwrap(resp):
    """响应统一解包: {code,data,...} -> data"""
    if isinstance(resp, dict) and "data" in resp:
        return resp["data"]
    return resp


def ensure_ok(status, resp, what):
    if status == 401:
        die(f"{what}: 未登录或 token 失效 (401) -> 重新 login")
    if status == 403:
        die(f"{what}: 无权限 (403): {_detail(resp)}")
    if status < 200 or status >= 300:
        die(f"{what}: HTTP {status} {_detail(resp)}")


def _detail(resp):
    if isinstance(resp, dict):
        return str(resp.get("detail") or resp.get("code") or resp)[:300]
    return str(resp)[:300]


def list_rows(data):
    """兼容 data 直接是 list 或 {list/data: [...]}"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("list") or data.get("data") or []
    return []


# ---------------------------------------------------------------- 认证
def cmd_send_code(args):
    cfg = load_cfg()
    phone = args.phone or cfg.get("phone")
    if not phone:
        die("需要手机号")
    st, resp = call("/api/user/token/code/", method="POST",
                    body={"phone_number": phone, "system": "H5"}, auth=False)
    ensure_ok(st, resp, "send-code")
    cfg["phone"] = phone
    save_cfg(cfg)
    ok({"status": "sent", "phone": phone[-4:].rjust(11, "*")})


def cmd_login(args):
    cfg = load_cfg()
    phone = args.phone or cfg.get("phone")
    if not phone or not args.code:
        die("用法: login [phone] <code>")
    st, resp = call("/api/user/token/", method="POST",
                    body={"phone_number": phone, "password": args.code}, auth=False)
    ensure_ok(st, resp, "login")
    tok = resp.get("access")
    if not tok:
        die(f"login: 无 access 字段: {_detail(resp)}")
    save_token(tok)
    cfg["phone"] = phone
    save_cfg(cfg)
    exp = jwt_exp(tok)
    ok({"status": "ok", "token_len": len(tok), "exp": exp})


def jwt_exp(tok):
    try:
        p = tok.split(".")[1]
        p += "=" * (-len(p) % 4)
        d = json.loads(__import__("base64").urlsafe_b64decode(p))
        return datetime.datetime.fromtimestamp(d.get("exp", 0)).isoformat()
    except Exception:
        return None


def cmd_whoami(args):
    st, resp = call("/api/user/info/")
    ensure_ok(st, resp, "whoami")
    d = unwrap(resp)
    exp = jwt_exp(load_token() or "")
    ok(d, human=f"用户: {d.get('username')} (id={d.get('id')})  token 有效期至 {exp}")


# ---------------------------------------------------------------- 搜索（分享区）
def cmd_search(args):
    params = {"keyword": args.keyword, "page": args.page, "page_size": args.size}
    if args.tag:
        params["tags"] = args.tag
    st, resp = call("/api/cloud/share/search/", params=params, auth=False)
    ensure_ok(st, resp, "search")
    rows = list_rows(unwrap(resp))
    out = [{
        "share_id": r.get("id"),
        "title": r.get("title"),
        "user": (r.get("user") or {}).get("username"),
        "tags": r.get("tags"),
        "file_count": (r.get("file_count") if "file_count" in r else None),
        "star": (r.get("starring") or {}).get("count"),
    } for r in rows]
    if args.raw:
        ok(rows)
    lines = [f"{i+1:2d}. [share {o['share_id']}] {o['title']}  by {o['user']}"
             for i, o in enumerate(out)]
    ok(out, human="\n".join(lines) or "(无结果)")


def cmd_share_info(args):
    st, resp = call("/api/cloud/share/info/", params={"share_id": args.share_id}, auth=False)
    ensure_ok(st, resp, "share-info")
    d = unwrap(resp)
    ok(d, human=json.dumps({k: d.get(k) for k in
        ("id", "title", "desc", "share_file_id", "user", "tags", "file_count")},
        ensure_ascii=False))


def cmd_share_files(args):
    params = {"share_id": args.share_id, "page": args.page, "page_size": args.size}
    if args.parent is not None:
        params["parent_id"] = args.parent
    else:
        st, info = call("/api/cloud/share/info/", params={"share_id": args.share_id}, auth=False)
        ensure_ok(st, info, "share-info")
        params["parent_id"] = unwrap(info).get("share_file_id")
    st, resp = call("/api/cloud/share/file/list/", params=params, auth=False)
    ensure_ok(st, resp, "share-files")
    rows = list_rows(unwrap(resp))
    if args.raw:
        ok(rows)
    lines = []
    for r in rows:
        kind = "DIR " if r.get("file_type") == 1 else "FILE"
        size = r.get("size") or 0
        lines.append(f"{kind} {r.get('id')}  {fmt_size(size):>9s}  {r.get('name')}")
    ok(rows, human="\n".join(lines) or "(空)")


def cmd_star(args):
    st, resp = call("/api/async/cloud/share/star/", params={"share_id": args.share_id})
    ensure_ok(st, resp, "star")
    ok({"status": "starred", "share_id": args.share_id})


def cmd_unstar(args):
    st, resp = call("/api/async/cloud/share/unstar/", params={"share_id": args.share_id})
    ensure_ok(st, resp, "unstar")
    ok({"status": "unstarred", "share_id": args.share_id})


def cmd_upvote(args):
    st, resp = call("/api/async/cloud/share/upvote/", method="POST",
                    body={"share_id": args.share_id})
    ensure_ok(st, resp, "upvote")
    ok({"status": "upvoted", "share_id": args.share_id})


# ---------------------------------------------------------------- 自己空间
def cmd_ls(args):
    params = {"page": args.page, "page_size": args.size}
    params["parent_id"] = args.parent if args.parent is not None else ROOT
    st, resp = call("/api/cloud/file/list/", params=params)
    ensure_ok(st, resp, "ls")
    rows = list_rows(unwrap(resp))
    if args.raw:
        ok(rows)
    lines = []
    for r in rows:
        kind = "DIR " if r.get("file_type") == 1 else "FILE"
        lines.append(f"{kind} {r.get('id')}  {fmt_size(r.get('size') or 0):>9s}  "
                     f"{_ts(r.get('update_time'))}  {r.get('name')}")
    ok(rows, human="\n".join(lines) or "(空目录)")


def cmd_search_my(args):
    st, resp = call("/api/cloud/file/search/",
                    params={"keyword": args.keyword, "page": args.page, "page_size": args.size})
    ensure_ok(st, resp, "search-my")
    rows = list_rows(unwrap(resp))
    if args.raw:
        ok(rows)
    lines = []
    for r in rows:
        kind = "DIR " if r.get("file_type") == 1 else "FILE"
        lines.append(f"{kind} {r.get('id')}  {fmt_size(r.get('size') or 0):>9s}  {r.get('name')}")
    ok(rows, human="\n".join(lines) or "(无结果)")


def cmd_tree(args):
    st, resp = call("/api/cloud/file/list/",
                    params={"page": 1, "page_size": 500,
                            "parent_id": args.parent if args.parent is not None else ROOT})
    ensure_ok(st, resp, "tree")
    rows = list_rows(unwrap(resp))
    lines = []

    def walk(rows, depth, limit):
        for r in rows:
            if len(lines) >= limit:
                return
            pad = "  " * depth
            if r.get("file_type") == 1:
                lines.append(f"{pad}[D] {r.get('id')}  {r.get('name')}")
                if depth < args.depth:
                    st2, r2 = call("/api/cloud/file/list/",
                                   params={"page": 1, "page_size": 200, "parent_id": r.get("id")})
                    if st2 == 200:
                        walk(list_rows(unwrap(r2)), depth + 1, limit)
            else:
                lines.append(f"{pad}[F] {r.get('id')}  {fmt_size(r.get('size') or 0):>9s}  {r.get('name')}")

    walk(rows, 0, args.limit)
    print("\n".join(lines) or "(空)")
    sys.exit(0)


def cmd_recent(args):
    st, resp = call("/api/cloud/file/list-recent/",
                    params={"page": args.page, "page_size": args.size})
    ensure_ok(st, resp, "recent")
    rows = list_rows(unwrap(resp))
    lines = [f"{'DIR ' if r.get('file_type')==1 else 'FILE'} {r.get('id')}  "
             f"{fmt_size(r.get('size') or 0):>9s}  {r.get('name')}" for r in rows]
    ok(rows, human="\n".join(lines) or "(空)")


def cmd_trash(args):
    st, resp = call("/api/cloud/file/list-trash/",
                    params={"page": args.page, "page_size": args.size})
    ensure_ok(st, resp, "trash")
    rows = list_rows(unwrap(resp))
    lines = [f"{r.get('id')}  {fmt_size(r.get('size') or 0):>9s}  {r.get('name')}" for r in rows]
    ok(rows, human="\n".join(lines) or "(回收站空)")


# ---------------------------------------------------------------- 增删改
def cmd_mkdir(args):
    body = {"file_type": 1, "name": args.name, "parent_id":
            args.parent if args.parent is not None else ROOT, "file_path": []}
    st, resp = call("/api/async/cloud/file/create/", method="POST", body=body)
    ensure_ok(st, resp, "mkdir")
    ok({"status": "created", "name": args.name, "parent_id": body["parent_id"]},
       human=f"已创建文件夹: {args.name}")


def cmd_rename(args):
    st, resp = call("/api/cloud/file/rename/", method="POST",
                    body={"file_id": args.file_id, "new_name": args.new_name})
    ensure_ok(st, resp, "rename")
    ok({"status": "renamed", "file_id": args.file_id, "new_name": args.new_name},
       human=f"已重命名 -> {args.new_name}")


def cmd_mv(args):
    st, resp = call("/api/cloud/file/move/", method="POST",
                    body={"file_id_list": args.file_ids,
                          "target_parent_id": args.to})
    ensure_ok(st, resp, "mv")
    ok({"status": "moved", "count": len(args.file_ids), "to": args.to},
       human=f"已移动 {len(args.file_ids)} 项 -> {args.to}")


def cmd_cp(args):
    st, resp = call("/api/cloud/file/copy/", method="POST",
                    body={"file_id_list": args.file_ids, "target_parent_id": args.to})
    ensure_ok(st, resp, "cp")
    ok({"status": "copied", "count": len(args.file_ids), "to": args.to},
       human=f"已复制 {len(args.file_ids)} 项 -> {args.to}")


def cmd_rm(args):
    if args.hard:
        # destroy 只对回收站内的项生效 -> 先尽力入站（已在站内时忽略报错）再永久删除
        call("/api/cloud/file/delete/", method="POST",
             body={"file_id_list": args.file_ids})
        st, resp = call("/api/cloud/file/destroy/", method="POST",
                        body={"file_id_list": args.file_ids})
        what = "purge"
    else:
        st, resp = call("/api/cloud/file/delete/", method="POST",
                        body={"file_id_list": args.file_ids})
        what = "trash"
    ensure_ok(st, resp, what)
    ok({"status": what, "count": len(args.file_ids)},
       human=f"已{'永久删除' if args.hard else '移入回收站'} {len(args.file_ids)} 项")


def cmd_restore(args):
    st, resp = call("/api/cloud/file/recover/", method="POST",
                    body={"file_id_list": args.file_ids})
    ensure_ok(st, resp, "restore")
    ok({"status": "restored", "count": len(args.file_ids)},
       human=f"已恢复 {len(args.file_ids)} 项")


def cmd_import(args):
    body = {"file_id_list": args.file_ids, "share_id": args.share_id,
            "target_parent_id": args.to if args.to is not None else ROOT}
    st, resp = call("/api/cloud/share/import/", method="POST", body=body)
    ensure_ok(st, resp, "import")
    ok({"status": "imported", "share_id": args.share_id,
        "count": len(args.file_ids), "to": body["target_parent_id"]},
       human=f"已转存 {len(args.file_ids)} 项 -> parent {body['target_parent_id']}")


# ---------------------------------------------------------------- 下载/预览
def _find_mine_by_name(name, size=None):
    st, resp = call("/api/cloud/file/search/",
                    params={"keyword": name[:40], "page": 1, "page_size": 20})
    ensure_ok(st, resp, "search-my")
    for r in list_rows(unwrap(resp)):
        if r.get("file_type") == 0 and r.get("name") == name:
            if size is None or r.get("size") == size:
                return r
    return None


def _signed_url(file_id, file_url):
    st, resp = call("/api/cloud/file/pre-download/",
                    params={"file_id": file_id, "file_url": file_url})
    ensure_ok(st, resp, "pre-download")
    d = unwrap(resp)
    return d.get("signed_file_url"), d.get("md5")


def _http_get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    r = urllib.request.urlopen(req, timeout=timeout)
    return r.status, r.read()


def cmd_get_url(args):
    st, resp = call("/api/cloud/file/search/",
                    params={"keyword": args.keyword, "page": 1, "page_size": 20})
    ensure_ok(st, resp, "search-my")
    target = None
    for r in list_rows(unwrap(resp)):
        if r.get("file_type") == 0 and (args.file_id is None or r.get("id") == args.file_id):
            target = r
            break
    if args.file_id and not target:
        die("找不到该文件（可用 get-url 用关键词，或先 ls 拿 id）")
    if not target:
        die("关键词未命中文件")
    url, md5 = _signed_url(target["id"], target["file_url"])
    ok({"file_id": target["id"], "name": target["name"],
        "signed_url": url, "md5": md5},
       human=f"{target['name']}\n{url}")


def cmd_download(args):
    # 自己空间: 直接按 id 找
    target = None
    if args.file_id:
        # 通过 search 全量找 id 对应记录: 先搜同名不可行, 用 recent+trash 兜底 -> 直接要求 keyword
        if args.keyword:
            st, resp = call("/api/cloud/file/search/",
                            params={"keyword": args.keyword, "page": 1, "page_size": 50})
            ensure_ok(st, resp, "search-my")
            for r in list_rows(unwrap(resp)):
                if r.get("id") == args.file_id:
                    target = r
                    break
        if not target:
            die("按 id 下载需要 --keyword 配合（接口无按 id 查询文件信息的端点）")
    else:
        if not args.keyword:
            die("需要 --keyword 或 --id + --keyword")
        st, resp = call("/api/cloud/file/search/",
                        params={"keyword": args.keyword, "page": 1, "page_size": 20})
        ensure_ok(st, resp, "search-my")
        for r in list_rows(unwrap(resp)):
            if r.get("file_type") == 0:
                target = r
                break
        if not target:
            die("自己空间里没搜到该文件")

    url, md5 = _signed_url(target["id"], target["file_url"])
    out = args.out or os.path.join(HOME, os.path.basename(target["name"]))
    st, data = _http_get(url, timeout=args.timeout)
    if st != 200:
        die(f"下载失败 HTTP {st}")
    with open(out, "wb") as f:
        f.write(data)
    got = hashlib.md5(data).hexdigest()
    ok({"file_id": target["id"], "name": target["name"], "saved": out,
        "bytes": len(data), "md5_ok": (md5 == got if md5 else None)},
       human=f"已保存 {out} ({fmt_size(len(data))}) md5校验={'通过' if md5==got else '跳过'}")


def cmd_download_share(args):
    """转存 -> 下载 -> (可选) 移入回收站"""
    st, info = call("/api/cloud/share/info/", params={"share_id": args.share_id}, auth=False)
    ensure_ok(st, info, "share-info")
    st, resp = call("/api/cloud/share/file/list/",
                    params={"share_id": args.share_id,
                            "parent_id": unwrap(info).get("share_file_id"),
                            "page": 1, "page_size": 500}, auth=False)
    ensure_ok(st, resp, "share-files")
    rows = list_rows(unwrap(resp))
    target = None
    for r in rows:
        if r.get("file_type") == 0 and (args.file_id is None or r.get("id") == args.file_id):
            target = r
            break
    if not target:
        die("分享里没找到该文件（目录请先用 share-files 看，再 --parent 下钻）")

    # 转存（根目录）
    st, resp = call("/api/cloud/share/import/", method="POST",
                    body={"file_id_list": [target["id"]], "share_id": args.share_id,
                          "target_parent_id": ROOT})
    ensure_ok(st, resp, "import")

    # 找到转存后的自己副本
    mine = None
    for _ in range(5):
        mine = _find_mine_by_name(target["name"], target.get("size"))
        if mine:
            break
        time.sleep(0.6)
    if not mine:
        die("转存成功但没在自己空间搜到副本")

    url, md5 = _signed_url(mine["id"], mine["file_url"])
    st, data = _http_get(url, timeout=args.timeout)
    if st != 200:
        die(f"下载失败 HTTP {st}")
    out = args.out or os.path.join(HOME, os.path.basename(target["name"]))
    with open(out, "wb") as f:
        f.write(data)
    got = hashlib.md5(data).hexdigest()

    if args.cleanup:
        call("/api/cloud/file/delete/", method="POST", body={"file_id_list": [mine["id"]]})

    ok({"share_id": args.share_id, "name": target["name"], "saved": out,
        "bytes": len(data), "md5_ok": (md5 == got if md5 else None),
        "cleanup": bool(args.cleanup)},
       human=f"已保存 {out} ({fmt_size(len(data))}) "
             f"md5={'通过' if md5==got else '跳过'}"
             f"{'；副本已入回收站' if args.cleanup else ''}")


def cmd_preview(args):
    """PDF 预览: 返回渲染页图片 URL 列表"""
    params = {"url": args.url, "page": args.page, "page_size": args.size}
    st, resp = call("/api/cloud/doc/preview/", params=params)
    ensure_ok(st, resp, "preview")
    d = unwrap(resp)
    urls = d.get("urls") if isinstance(d, dict) else d
    ok(urls, human="\n".join(urls or []) or "(无)")


# ---------------------------------------------------------------- 分享管理
def cmd_shares(args):
    # 注意: tags 传 [] 会把结果全滤掉 -> 不给 --tag 时不要带这个参数
    params = {"page": args.page, "page_size": args.size}
    if args.tag:
        params["tags"] = args.tag
    st, resp = call("/api/cloud/share/list/", params=params)
    ensure_ok(st, resp, "shares")
    rows = list_rows(unwrap(resp))
    if args.mine:
        me = _my_id()
        rows = [r for r in rows if (r.get("user") or {}).get("id") == me]
    lines = []
    for r in rows:
        lines.append(f"[share {r.get('id')}] {r.get('title')}  "
                     f"tags={r.get('tags')}  star={(r.get('starring') or {}).get('count')}")
    ok(rows, human="\n".join(lines) or "(还没有分享)")


def cmd_share_create(args):
    body = {"file_id": args.file_id, "title": args.title,
            "desc": args.desc or "", "tags": args.tags or []}
    st, resp = call("/api/async/cloud/share/create-by-folder/", method="POST", body=body)
    ensure_ok(st, resp, "share-create")
    ok(unwrap(resp) or {"status": "created"}, human=f"已创建分享: {args.title}")


def cmd_share_update(args):
    body = {"share_id": args.share_id, "title": args.title,
            "desc": args.desc or "", "tags": args.tags or []}
    st, resp = call("/api/async/cloud/share/update/", method="POST", body=body)
    ensure_ok(st, resp, "share-update")
    ok({"status": "updated", "share_id": args.share_id})


def cmd_share_delete(args):
    st, resp = call("/api/async/cloud/share/delete/", method="POST",
                    body={"share_id_list": args.share_ids})
    ensure_ok(st, resp, "share-delete")
    ok({"status": "deleted", "count": len(args.share_ids)},
       human=f"已取消分享 {len(args.share_ids)} 个")


# ---------------------------------------------------------------- 上传
def _md5_file(path, chunk=1024 * 1024):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _cos_put(bucket, region, key, data, cred):
    """腾讯云 COS q-sign 签名直传（临时凭证）

    规范（逆向自 COS 403 报错里的 FormatString，实测 200）:
      FormatString = "put\\n{uri}\\n\\n{k=v&k=v}\\n"   # 方法小写, 值转义, 键不转义
      StringToSign = "sha1\\n{key_time}\\n{sha1(FormatString)}\\n"   # 注意末尾换行
      SignKey      = HMAC-SHA1(tmpSecretKey, key_time)
      q-signature  = HMAC-SHA1(SignKey, StringToSign)
    """
    host = f"{bucket}.cos.{region}.myqcloud.com"
    uri = urllib.parse.quote(key, safe="/-_.~%")
    now = int(time.time())
    key_time = f"{now - 300};{now + 3600}"
    token = cred["sessionToken"]
    hdrs = {"content-type": "application/octet-stream",
            "host": host,
            "x-cos-security-token": token}
    header_part = "&".join(
        f"{k}={urllib.parse.quote(v, safe='')}" for k, v in sorted(hdrs.items()))
    fmt = f"put\n{uri}\n\n{header_part}\n"
    sts = "sha1\n" + key_time + "\n" + hashlib.sha1(fmt.encode()).hexdigest() + "\n"
    sign_key = hmac.new(cred["tmpSecretKey"].encode(),
                        key_time.encode(), hashlib.sha1).hexdigest()
    sig = hmac.new(sign_key.encode(), sts.encode(), hashlib.sha1).hexdigest()
    auth = (f"q-sign-algorithm=sha1&q-ak={cred['tmpSecretId']}"
            f"&q-sign-time={key_time}&q-key-time={key_time}"
            f"&q-header-list={';'.join(sorted(hdrs))}"
            f"&q-url-param-list=&q-signature={sig}")

    req = urllib.request.Request("https://" + host + uri, data=data, method="PUT")
    for k, v in hdrs.items():
        req.add_header(k, v)
    req.add_header("Authorization", auth)
    try:
        r = urllib.request.urlopen(req, timeout=300)
        return r.status, r.read()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:400]


def cmd_upload(args):
    path = os.path.abspath(args.path)
    if not os.path.isfile(path):
        die(f"文件不存在: {path}")
    name = os.path.basename(path)
    ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
    size = os.path.getsize(path)
    if size > 100 * 1024 * 1024:
        die("单文件上限 100MB（平台限制）")
    md5 = _md5_file(path)

    body = {"md5": md5, "size": size, "name": name, "extension": ext,
            "file_path": [], "parent_id": args.parent if args.parent is not None else ROOT}
    st, resp = call("/api/async/cloud/file/pre-create/", method="POST", body=body)
    ensure_ok(st, resp, "pre-create")
    d = unwrap(resp)

    if d.get("exist"):
        # 秒传: 回传一段校验字节
        s, e = d.get("check_bytes_start", 0), d.get("check_bytes_end", 0)
        with open(path, "rb") as f:
            f.seek(s)
            chunk = f.read(e - s + 1)
        check = chunk.hex()
        body2 = {"md5": md5, "extension": ext, "file_type": 0, "name": name,
                 "file_path": [], "check_bytes": check, "req_id": d.get("req_id"),
                 "parent_id": body["parent_id"]}
        st2, r2 = call("/api/async/cloud/file/create/", method="POST", body=body2)
        ensure_ok(st2, r2, "create(秒传)")
        ok({"status": "instant", "name": name, "parent_id": body["parent_id"]},
           human=f"秒传完成: {name}")

    cred = ((d.get("credential") or {}).get("credentials")) or {}
    bucket = d.get("bucket_name")
    region = d.get("region")
    key = d.get("allow_prefix")
    if not (cred and bucket and key):
        die(f"pre-create 未返回上传凭证: {json.dumps(d, ensure_ascii=False)[:300]}")

    with open(path, "rb") as f:
        data = f.read()
    st, body_txt = _cos_put(bucket, region, key, data, cred)
    if st not in (200, 204):
        die(f"COS 上传失败 HTTP {st}: {body_txt}")

    st2, r2 = call("/api/async/cloud/file/complete-upload/", method="POST",
                   body={"upload_key": key})
    ensure_ok(st2, r2, "complete-upload")
    ok({"status": "uploaded", "name": name, "bytes": size, "parent_id": body["parent_id"]},
       human=f"上传完成: {name} ({fmt_size(size)})")


def cmd_quark_import(args):
    """转存夸克网盘分享链接到自己空间"""
    body = {"share_url": args.url}
    if args.to is not None:
        body["target_parent_id"] = args.to
    st, resp = call("/api/cloud/quark/import_shares/", method="POST", body=body)
    ensure_ok(st, resp, "quark-import")
    ok(unwrap(resp) or {"status": "imported"}, human="夸克链接已导入")


def cmd_shortlink(args):
    st, resp = call("/api/client/shortlink/create/", method="POST", body={"url": args.url})
    ensure_ok(st, resp, "shortlink")
    d = unwrap(resp)
    ok(d, human=str(d))


# ---------------------------------------------------------------- 工具
def _my_id():
    st, resp = call("/api/user/info/")
    if st == 200:
        return unwrap(resp).get("id")
    return None


def fmt_size(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def _ts(s):
    if not s:
        return " " * 16
    return str(s)[:16].replace("T", " ")


# ---------------------------------------------------------------- CLI
def build():
    p = argparse.ArgumentParser(prog="bidai", description="笔袋网盘 CLI")
    sub = p.add_subparsers(dest="cmd")

    def sp(name, fn, **kw):
        q = sub.add_parser(name, **kw)
        q.set_defaults(fn=fn)
        return q

    q = sp("send-code", cmd_send_code, help="发登录验证码短信")
    q.add_argument("phone", nargs="?")

    q = sp("login", cmd_login, help="用验证码登录")
    q.add_argument("phone", nargs="?")
    q.add_argument("code", nargs="?")

    sp("whoami", cmd_whoami, help="当前用户 + token 有效期")

    q = sp("search", cmd_search, help="搜索全站分享资源（试卷/资料）")
    q.add_argument("keyword")
    q.add_argument("--page", type=int, default=1)
    q.add_argument("--size", type=int, default=20)
    q.add_argument("--tag", action="append")
    q.add_argument("--raw", action="store_true")

    q = sp("share-info", cmd_share_info, help="分享详情")
    q.add_argument("share_id", type=int)

    q = sp("share-files", cmd_share_files, help="分享内文件列表（目录用 --parent 下钻）")
    q.add_argument("share_id", type=int)
    q.add_argument("--parent", type=int)
    q.add_argument("--page", type=int, default=1)
    q.add_argument("--size", type=int, default=100)
    q.add_argument("--raw", action="store_true")

    q = sp("import", cmd_import, help="转存分享文件到自己空间")
    q.add_argument("share_id", type=int)
    q.add_argument("file_ids", type=int, nargs="+")
    q.add_argument("--to", type=int, help="目标目录 id，默认根(-1)")

    q = sp("ls", cmd_ls, help="列自己空间目录")
    q.add_argument("--parent", type=int, help="目录 id，默认根(-1)")
    q.add_argument("--page", type=int, default=1)
    q.add_argument("--size", type=int, default=100)
    q.add_argument("--raw", action="store_true")

    q = sp("search-my", cmd_search_my, help="搜自己空间")
    q.add_argument("keyword")
    q.add_argument("--page", type=int, default=1)
    q.add_argument("--size", type=int, default=20)
    q.add_argument("--raw", action="store_true")

    q = sp("tree", cmd_tree, help="递归列目录")
    q.add_argument("--parent", type=int)
    q.add_argument("--depth", type=int, default=3)
    q.add_argument("--limit", type=int, default=300)

    q = sp("recent", cmd_recent, help="最近文件")
    q.add_argument("--page", type=int, default=1)
    q.add_argument("--size", type=int, default=20)
    q.add_argument("--raw", action="store_true")

    q = sp("trash", cmd_trash, help="回收站")
    q.add_argument("--page", type=int, default=1)
    q.add_argument("--size", type=int, default=50)
    q.add_argument("--raw", action="store_true")

    q = sp("mkdir", cmd_mkdir, help="建文件夹")
    q.add_argument("name")
    q.add_argument("--parent", type=int)

    q = sp("rename", cmd_rename, help="重命名")
    q.add_argument("file_id", type=int)
    q.add_argument("new_name")

    q = sp("mv", cmd_mv, help="移动")
    q.add_argument("file_ids", type=int, nargs="+")
    q.add_argument("--to", type=int, required=True)

    q = sp("cp", cmd_cp, help="复制")
    q.add_argument("file_ids", type=int, nargs="+")
    q.add_argument("--to", type=int, required=True)

    q = sp("rm", cmd_rm, help="删除（默认进回收站）")
    q.add_argument("file_ids", type=int, nargs="+")
    q.add_argument("--hard", action="store_true", help="永久删除")

    q = sp("restore", cmd_restore, help="从回收站恢复")
    q.add_argument("file_ids", type=int, nargs="+")

    q = sp("get-url", cmd_get_url, help="拿签名直链")
    q.add_argument("keyword")
    q.add_argument("--file-id", dest="file_id", type=int)

    q = sp("download", cmd_download, help="下载自己空间的文件")
    q.add_argument("--keyword", "-k")
    q.add_argument("--id", dest="file_id", type=int)
    q.add_argument("--out", "-o")
    q.add_argument("--timeout", type=int, default=300)

    q = sp("download-share", cmd_download_share, help="转存并下载分享文件")
    q.add_argument("share_id", type=int)
    q.add_argument("file_id", type=int, nargs="?")
    q.add_argument("--out", "-o")
    q.add_argument("--cleanup", action="store_true", help="下载后把转存副本移入回收站")
    q.add_argument("--timeout", type=int, default=300)

    q = sp("preview", cmd_preview, help="PDF 预览页图片 URL")
    q.add_argument("url")
    q.add_argument("--page", type=int, default=1)
    q.add_argument("--size", type=int, default=4)

    q = sp("shares", cmd_shares, help="分享列表/我创建的分享")
    q.add_argument("--page", type=int, default=1)
    q.add_argument("--size", type=int, default=20)
    q.add_argument("--tag", action="append")
    q.add_argument("--mine", action="store_true", help="只看自己创建的（跨页过滤）")
    q.add_argument("--raw", action="store_true")

    q = sp("share-create", cmd_share_create, help="把文件夹设为分享（需学段标签）")
    q.add_argument("file_id", type=int)
    q.add_argument("--title", required=True)
    q.add_argument("--desc")
    q.add_argument("--tags", nargs="*")

    q = sp("share-update", cmd_share_update, help="改分享信息")
    q.add_argument("share_id", type=int)
    q.add_argument("--title", required=True)
    q.add_argument("--desc")
    q.add_argument("--tags", nargs="*")

    q = sp("share-delete", cmd_share_delete, help="取消分享")
    q.add_argument("share_ids", type=int, nargs="+")

    q = sp("star", cmd_star, help="收藏共享空间")
    q.add_argument("share_id", type=int)

    q = sp("unstar", cmd_unstar, help="取消收藏")
    q.add_argument("share_id", type=int)

    q = sp("upvote", cmd_upvote, help="给分享点赞")
    q.add_argument("share_id", type=int)

    q = sp("upload", cmd_upload, help="上传文件（<=100MB，支持秒传）")
    q.add_argument("path")
    q.add_argument("--parent", type=int)

    q = sp("quark-import", cmd_quark_import, help="转存夸克网盘分享链接")
    q.add_argument("url")
    q.add_argument("--to", type=int, help="目标目录 id，默认根(-1)")

    q = sp("shortlink", cmd_shortlink, help="生成短链")
    q.add_argument("url")

    return p


def main():
    p = build()
    args = p.parse_args()
    if not getattr(args, "fn", None):
        p.print_help()
        sys.exit(0)
    try:
        args.fn(args)
    except SystemExit:
        raise
    except Exception as e:
        die(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
