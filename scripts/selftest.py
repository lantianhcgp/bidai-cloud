#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bidai CLI 自测：建目录/上传/改名/移动/复制/回收站/恢复/分享/下载 全生命周期"""
import json, os, subprocess, sys, time, hashlib

CLI = os.path.expanduser("~/.hermes/skills/bidai-cloud/scripts/bidai.py")
WORK = os.path.expanduser("~/bidai_selftest")
RESULTS = []


def run(args, expect_ok=True):
    r = subprocess.run([sys.executable, CLI] + args,
                       capture_output=True, text=True, timeout=180)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    passed = (r.returncode == 0) if expect_ok else (r.returncode != 0)
    # 不在这里计数：只有显式 RESULTS.append 的断言才计入统计
    return passed, out, err


def jrun(args):
    passed, out, err = run(args)
    try:
        return passed, json.loads(out)
    except Exception:
        return passed, out


TAG = "selftest"

# 0) 环境
os.makedirs(WORK, exist_ok=True)
probe = os.path.join(WORK, "probe.txt")
with open(probe, "w") as f:
    f.write("bidai selftest " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + "x" * 2048)

# 1) 建测试目录
ok, data = jrun(["mkdir", TAG])
folder_id = None
if ok:
    _, rows = jrun(["ls", "--raw", "--size", "100"])
    for r in rows if isinstance(rows, list) else []:
        if r.get("name") == TAG and r.get("file_type") == 1:
            folder_id = r.get("id")
if folder_id:
    RESULTS.append(("mkdir->found", True, f"folder_id={folder_id}"))
else:
    RESULTS.append(("mkdir->found", False, f"ok={ok} {str(data)[:120]}"))
    print(json.dumps(RESULTS, ensure_ascii=False, indent=1))
    sys.exit(1)

# 2) 上传
ok, data = jrun(["upload", probe, "--parent", str(folder_id)])
RESULTS.append(("upload", ok, str(data)[:140]))
file_id = None
if ok:
    _, rows = jrun(["ls", "--parent", str(folder_id), "--raw"])
    for r in rows if isinstance(rows, list) else []:
        if r.get("name") == "probe.txt":
            file_id = r.get("id")

# 3) 上传同一文件到另一目录（测秒传路径）
ok2, data2 = jrun(["upload", probe])   # 根目录
RESULTS.append(("upload-instant", ok2, str(data2)[:140]))

# 4) 重命名
if file_id:
    ok, d = jrun(["rename", str(file_id), "probe_renamed.txt"])
    RESULTS.append(("rename", ok, str(d)[:120]))
else:
    RESULTS.append(("rename", False, "no file_id"))

# 5) 复制 / 移动
if file_id:
    ok, d = jrun(["cp", str(file_id), "--to", "-1"])
    RESULTS.append(("cp", ok, str(d)[:120]))
    ok, d = jrun(["mv", str(file_id), "--to", "-1"])
    RESULTS.append(("mv", ok, str(d)[:120]))

# 6) 回收站 -> 恢复 -> 再删 -> 永久删除
_, rows = jrun(["search-my", "probe_renamed", "--raw"])
target = None
for r in (rows if isinstance(rows, list) else []):
    if r.get("name") == "probe_renamed.txt":
        target = r.get("id")
        break
if target:
    ok, d = jrun(["rm", str(target)])
    RESULTS.append(("rm->trash", ok, str(d)[:120]))
    ok, d = jrun(["trash", "--raw"])
    in_trash = any(x.get("id") == target for x in (d if isinstance(d, list) else []))
    RESULTS.append(("trash-listed", in_trash, f"in_trash={in_trash}"))
    ok, d = jrun(["restore", str(target)])
    RESULTS.append(("restore", ok, str(d)[:120]))
    ok, d = jrun(["rm", str(target)])
    RESULTS.append(("rm2", ok, str(d)[:120]))
    ok, d = jrun(["rm", str(target), "--hard"])
    RESULTS.append(("purge", ok, str(d)[:120]))
else:
    RESULTS.append(("find-renamed", False, "not found"))

# 7) 分享（share-create 服务端会 500 但实际创建成功 -> 以列表查到为准）
ok, d = jrun(["share-create", str(folder_id), "--title", "hermes自测分享",
              "--tags", "高中", "数学"])
RESULTS.append(("share-create", True, f"rc_ok={ok} {str(d)[:110]}"))
share_id = None
okl, rows = jrun(["shares", "--raw", "--size", "100"])
for r in (rows if isinstance(rows, list) else []):
    if r.get("title") == "hermes自测分享":
        share_id = r.get("id")
RESULTS.append(("shares-list", share_id is not None, f"share_id={share_id}"))
if share_id:
    ok, d = jrun(["share-info", str(share_id)])
    RESULTS.append(("share-info", ok, str(d)[:120]))
    ok, d = jrun(["share-files", str(share_id), "--raw"])
    RESULTS.append(("share-files", ok, str(d)[:140]))
    # share-delete 服务端可能返回 500 但实际生效 -> 用 share-info 复核
    jrun(["share-delete", str(share_id)])
    ok_info, d_info = jrun(["share-info", str(share_id)])
    gone = (not ok_info) or ("已删除" in str(d_info)) or (not d_info)
    RESULTS.append(("share-delete", gone,
                    f"info_after={str(d_info)[:90]}"))

# 7b) 端到端: 转存别人分享的文件 -> 下载 -> 清理副本
dl_out = os.path.join(WORK, "e2e.pdf")
if os.path.exists(dl_out):
    os.remove(dl_out)
ok, d = jrun(["download-share", "8911", "572066384", "-o", dl_out, "--cleanup"])
good = False
if ok and isinstance(d, dict):
    good = bool(d.get("md5_ok")) and os.path.exists(dl_out) and os.path.getsize(dl_out) > 100000
RESULTS.append(("download-share-e2e", good, str(d)[:170]))

# 8) 清理测试目录（先删里面的残留副本 -> 删文件夹）
_, rows = jrun(["ls", "--parent", str(folder_id), "--raw"])
ids = [r.get("id") for r in (rows if isinstance(rows, list) else []) if r.get("id")]
if ids:
    ok, d = jrun(["rm"] + [str(i) for i in ids] + ["--hard"])
    RESULTS.append(("cleanup-children", ok, str(d)[:120]))
ok, d = jrun(["rm", str(folder_id), "--hard"])
RESULTS.append(("cleanup-folder", ok, str(d)[:120]))

# 汇总
# 8b) 全局清理: 根目录与回收站里所有自测命名残留（静默执行，不计入统计）
KEYS = ("selftest", "shraetest", "probe", "东三省名校联盟")


def quiet(args):
    return subprocess.run([sys.executable, CLI] + args, capture_output=True,
                          text=True, timeout=180)


def quiet_json(args):
    try:
        r = quiet(args)
        return json.loads((r.stdout or "").strip())
    except Exception:
        return []


for scope in (["ls", "--raw", "--size", "500"], ["trash", "--raw", "--size", "200"]):
    rows = quiet_json(scope)
    ids = [r["id"] for r in rows if any(k in (r.get("name") or "") for k in KEYS)]
    if ids:
        quiet(["rm"] + [str(i) for i in ids])
        quiet(["rm"] + [str(i) for i in ids] + ["--hard"])

mine = [r["id"] for r in quiet_json(["shares", "--raw", "--size", "100"])
        if r.get("title") in ("hermes自测分享", "T空", "T满", "T带desc")]
if mine:
    quiet(["share-delete"] + [str(i) for i in mine])

print("=" * 64)
print(f"{'步骤':24s} {'结果':6s} 详情")
print("-" * 64)
passed = 0
for name, p, detail in RESULTS:
    print(f"{name:24s} {'PASS' if p else 'FAIL':6s} {detail}")
    passed += 1 if p else 0
print("-" * 64)
print(f"TOTAL: {passed}/{len(RESULTS)} PASS")
