#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IPTV 直播源可用性测试脚本（通用版，支持本地与 GitHub Actions 运行）

用法: python check_iptv.py [仓库根目录]
  仓库根目录默认取脚本所在目录的上两级（即仓库根）。
  会读取 <root>/tv/iptv4.txt，输出 <root>/tv/iptv4_checked.txt 与 <root>/tv/iptv4_dead.txt。
"""
import io
import os
import sys
import socket
import ssl
import urllib.request
import urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ---- 路径定位 ----
if len(sys.argv) > 1:
    ROOT = os.path.abspath(sys.argv[1])
else:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SRC = os.path.join(ROOT, "tv", "iptv4.txt")
OUT_OK = os.path.join(ROOT, "tv", "iptv4_checked.txt")
OUT_DEAD = os.path.join(ROOT, "tv", "iptv4_dead.txt")

if not os.path.exists(SRC):
    print(f"[错误] 找不到源文件: {SRC}", flush=True)
    sys.exit(1)

TIMEOUT = 8
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "close",
}

# ---- 解析 ----
entries = []  # (group, name, url)
cur_group = "未分组"
with open(SRC, encoding="utf-8", errors="replace") as f:
    raw = f.read().splitlines()
for ln in raw:
    ln = ln.strip()
    if not ln:
        continue
    if "#genre#" in ln:
        cur_group = ln.replace("#genre#", "").replace(",", "").strip()
        continue
    if "," in ln:
        name, url = ln.split(",", 1)
        entries.append((cur_group, name.strip(), url.strip()))

urls = list(dict.fromkeys(e[2] for e in entries))
print(f"总条目: {len(entries)}  去重后 URL: {len(urls)}", flush=True)


def test(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            status = resp.status
            ctype = resp.headers.get("Content-Type", "")
            data = resp.read(4096)
        if status not in (200, 206):
            return url, False, f"HTTP {status}"
        low = data[:2048].lower()
        if b"<html" in low or b"<!doctype" in low:
            return url, False, "HTML错误页"
        if b"#extm3u" in low or b"m3u8" in low or b"#extinf" in low:
            return url, True, ctype.split(";")[0]
        if ctype and any(k in ctype for k in ("video", "octet-stream", "mpegurl", "mp2t", "x-mpeg")):
            return url, True, ctype.split(";")[0]
        if len(data) > 188 and data[0] == 0x47 and data[188] == 0x47:
            return url, True, "MPEG-TS"
        if len(data) < 512:
            return url, False, "内容过短"
        return url, False, "非流媒体内容"
    except urllib.error.HTTPError as e:
        return url, False, f"HTTP {e.code}"
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, ConnectionError, OSError) as e:
        return url, False, type(e).__name__
    except Exception as e:
        return url, False, type(e).__name__


results = {}
with ThreadPoolExecutor(max_workers=30) as ex:
    futs = {ex.submit(test, u): u for u in urls}
    done = 0
    for fut in as_completed(futs):
        url, ok, reason = fut.result()
        results[url] = (ok, reason)
        done += 1
        if done % 100 == 0:
            print(f"进度: {done}/{len(urls)}", flush=True)

ok_urls = {u for u, (ok, _) in results.items() if ok}
print(f"\n测试完成: 可用 {len(ok_urls)} / {len(urls)}", flush=True)
reasons = Counter(r for _, (ok, r) in results.items() if not ok)
print("失败原因 Top10:", reasons.most_common(10), flush=True)

# 写输出（保留原分组结构）
cur_g = None
with open(OUT_OK, "w", encoding="utf-8") as fo, open(OUT_DEAD, "w", encoding="utf-8") as fd:
    for group, name, url in entries:
        target = fo if url in ok_urls else fd
        if group != cur_g:
            target.write(f"{group},#genre#\n")
            cur_g = group
        target.write(f"{name},{url}\n")

group_stat = Counter(e[0] for e in entries if e[2] in ok_urls)
print("可用源分组分布:", dict(group_stat), flush=True)
print(f"可用列表: {OUT_OK}", flush=True)
print(f"失效列表: {OUT_DEAD}", flush=True)
