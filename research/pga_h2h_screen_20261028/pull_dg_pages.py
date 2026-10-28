#!/usr/bin/env python3
"""Pull DataGolf free past-results pages for PGA Tour events, calendar years
2020-2025, event ids 1..130. Hash-pin every response into a manifest.
Free web pages only; no API key; polite pacing."""
import hashlib
import json
import os
import time
import urllib.request
import urllib.error

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulls", "dg_pages")
os.makedirs(OUT, exist_ok=True)
MANIFEST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulls", "dg_pages_manifest.json")

manifest = {}
if os.path.exists(MANIFEST_PATH):
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}

for year in range(2020, 2026):
    for eid in range(1, 131):
        key = f"pga-tour/{eid}/{year}"
        if key in manifest and manifest[key].get("http") == 200:
            continue
        url = f"https://datagolf.com/past-results/pga-tour/{eid}/{year}"
        path = os.path.join(OUT, f"pga_{eid}_{year}.html")
        import subprocess
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tf:
                tmp = tf.name
            proc = subprocess.run(
                ["curl", "-s", "-A", UA["User-Agent"], "-o", tmp, "-w", "%{http_code}", "--max-time", "45", url],
                capture_output=True, text=True, timeout=60,
            )
            code = int(proc.stdout.strip() or 0)
            with open(tmp, "rb") as f:
                body = f.read()
            os.unlink(tmp)
            if code != 200:
                manifest[key] = {"url": url, "http": code}
                continue
        except Exception as e:  # noqa: BLE001
            manifest[key] = {"url": url, "http": -1, "error": str(e)[:120]}
            continue
        with open(path, "wb") as f:
            f.write(body)
        manifest[key] = {
            "url": url,
            "http": code,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "file": os.path.basename(path),
        }
        time.sleep(0.8)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    ok = sum(1 for v in manifest.values() if v.get("http") == 200)
    print(f"year {year} done; total 200s so far: {ok}", flush=True)

ok = {k: v for k, v in manifest.items() if v.get("http") == 200}
print(f"DONE total pages pulled: {len(ok)}")
