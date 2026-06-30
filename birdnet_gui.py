#!/usr/bin/env python3
"""BirdNET Dashboard — Google Dark Material aesthetic web GUI."""

import json, os, sqlite3, subprocess, sys, time, urllib.request, socket, re
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HOST = "127.0.0.1"
PORT = 8090

LISTENER_DB = os.path.expanduser("~/.birdnet-listener/detections.db")
SOUNDSCAPE_DB = os.path.expanduser("~/.openclaw/workspace/ears/soundscape.db")

SYD_TZ = timezone(timedelta(hours=10))

# ── Queries ──────────────────────────────────────────────────────────

def q_listener(query, params=()):
    try:
        conn = sqlite3.connect(LISTENER_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        return []

def api_summary():
    rows = q_listener("SELECT species, confidence, source, timestamp FROM detections")
    # Today in AEST (UTC+10) — compute UTC range properly
    now_syd = datetime.now(SYD_TZ)
    today_start = now_syd.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    today_utc_start = (today_start - SYD_TZ.utcoffset(None)).strftime("%Y-%m-%d %H:%M")
    today_utc_end = (today_end - SYD_TZ.utcoffset(None)).strftime("%Y-%m-%d %H:%M")
    today_rows = [r for r in rows if r.get("timestamp","")[:16] >= today_utc_start and r.get("timestamp","")[:16] < today_utc_end]
    species_set = set(); cam_stats = {}; top_species = {}
    for r in rows:
        species_set.add(r["species"])
        src = r.get("source", "unknown"); cam_stats[src] = cam_stats.get(src, 0) + 1
        top_species[r["species"]] = top_species.get(r["species"], 0) + 1
    top3 = sorted(top_species.items(), key=lambda x: x[1], reverse=True)[:3]
    latest = today_rows[-1] if today_rows else None
    return {"total_detections": len(rows), "total_species": len(species_set),
            "today_detections": len(today_rows), "today_species": len(set(r["species"] for r in today_rows)),
            "cameras": cam_stats, "top_species": [{"name": n, "count": c} for n, c in top3],
            "latest_time": latest["timestamp"] if latest else None, "latest_species": latest["species"] if latest else None}

def api_timeline():
    rows = q_listener("SELECT species, confidence, source, timestamp FROM detections")
    hours = {}
    for r in rows:
        ts = r.get("timestamp", "")
        if ts:
            h = ts[:13]
            hours.setdefault(h, {"count": 0, "species": set()})
            hours[h]["count"] += 1; hours[h]["species"].add(r["species"])
    return [{"hour": h, "count": d["count"], "species_count": len(d["species"])}
            for h, d in sorted(hours.items())][-168:]

def api_aggregate(period):
    rows = q_listener("SELECT species, confidence, source, timestamp FROM detections")
    now_syd = datetime.now(SYD_TZ)
    if period == 'hour':
        start = now_syd - timedelta(hours=24)
        fmt = "%Y-%m-%d %H"
        prev_start = start - timedelta(hours=24)
        label_fmt = lambda k: k[11:13] + ':00'
        max_buckets = 24
    elif period == 'week':
        start = now_syd - timedelta(weeks=12)
        prev_start = start - timedelta(weeks=12)
        fmt = "%G-W%V"
        label_fmt = lambda k: 'W' + k.split('W')[1] if 'W' in k else k
        max_buckets = 12
    elif period == 'month':
        start = now_syd - timedelta(days=365)
        prev_start = start - timedelta(days=365)
        fmt = "%Y-%m"
        label_fmt = lambda k: k[5:7] + '/' + k[2:4]
        max_buckets = 12
    else:  # day
        start = now_syd - timedelta(days=30)
        prev_start = start - timedelta(days=30)
        fmt = "%Y-%m-%d"
        label_fmt = lambda k: k[5:10]
        max_buckets = 30
    start_utc = (start - SYD_TZ.utcoffset(None)).strftime("%Y-%m-%d %H:%M")
    prev_utc = (prev_start - SYD_TZ.utcoffset(None)).strftime("%Y-%m-%d %H:%M")
    # Current period buckets
    buckets = {}
    for r in rows:
        ts = r.get("timestamp", "")
        if ts and ts >= start_utc:
            dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
            dt_syd = dt.replace(tzinfo=timezone.utc).astimezone(SYD_TZ)
            k = dt_syd.strftime(fmt)
            buckets.setdefault(k, {"count": 0, "species": set()})
            buckets[k]["count"] += 1; buckets[k]["species"].add(r["species"])
    # Previous period buckets
    prev_buckets = {}
    for r in rows:
        ts = r.get("timestamp", "")
        if ts and prev_utc <= ts < start_utc:
            dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
            dt_syd = dt.replace(tzinfo=timezone.utc).astimezone(SYD_TZ)
            k = dt_syd.strftime(fmt)
            prev_buckets.setdefault(k, {"count": 0})
            prev_buckets[k]["count"] += 1
    # Species breakdown for current period
    species = {}
    for r in rows:
        ts = r.get("timestamp", "")
        if ts and ts >= start_utc:
            sp = r["species"]
            species[sp] = species.get(sp, 0) + 1
    top_species = sorted(species.items(), key=lambda x: x[1], reverse=True)
    total = sum(v for _, v in species.items())
    unique = len(species)
    prev_total = sum(d["count"] for d in prev_buckets.values())
    # Build timeline
    tl = [{"label": label_fmt(k), "label_raw": k, "count": d["count"], "species_count": len(d["species"])}
          for k, d in sorted(buckets.items())][-max_buckets:]
    return {"period": period, "total": total, "unique": unique,
            "prev_total": prev_total,
            "top_species": [{"name": n, "count": c} for n, c in top_species[:50]],
            "timeline": tl}

def api_species():
    rows = q_listener("SELECT species, confidence, source, timestamp FROM detections")
    species = {}
    for r in rows:
        sp = r["species"]
        if sp not in species:
            species[sp] = {"count": 0, "total_conf": 0, "cameras": set(), "last_seen": None}
        species[sp]["count"] += 1; species[sp]["total_conf"] += r["confidence"]
        species[sp]["cameras"].add(r.get("source", "unknown"))
        ts = r.get("timestamp", "")
        if ts and (species[sp]["last_seen"] is None or ts > species[sp]["last_seen"]):
            species[sp]["last_seen"] = ts
    return sorted([{"name": n, "count": d["count"], "avg_confidence": round(d["total_conf"] / d["count"], 3),
                     "cameras": list(d["cameras"]), "last_seen": d["last_seen"]}
                   for n, d in species.items()], key=lambda x: x["count"], reverse=True)

def api_recent(limit=50):
    return q_listener("SELECT species, confidence, source, timestamp FROM detections ORDER BY id DESC LIMIT ?", (limit,))

def api_cameras():
    rows = q_listener("SELECT species, confidence, source, timestamp FROM detections")
    cams = {}
    for r in rows:
        src = r.get("source", "unknown")
        cams.setdefault(src, {"count": 0, "species": set(), "total_conf": 0})
        cams[src]["count"] += 1; cams[src]["species"].add(r["species"]); cams[src]["total_conf"] += r["confidence"]
    return {cam: {"detections": d["count"], "species_count": len(d["species"]),
                  "avg_confidence": round(d["total_conf"] / d["count"], 3) if d["count"] else 0}
            for cam, d in cams.items()}

# ── Wikipedia Image (server-side, cached, rate-limited) ──────────────

import urllib.error, threading
WIKI_CACHE = {}
WIKI_LOCK = threading.Lock()
WIKI_LAST = 0.0
WIKI_DELAY = 0.3  # 300ms between requests to avoid 429

def wiki_image(species):
    with WIKI_LOCK:
        if species in WIKI_CACHE:
            return WIKI_CACHE[species]

    global WIKI_LAST
    for attempt in range(3):
        elapsed = time.time() - WIKI_LAST
        if elapsed < WIKI_DELAY:
            time.sleep(WIKI_DELAY - elapsed)
        WIKI_LAST = time.time()

        for name in [species, species.replace(" ", "_"), species.replace("-", " ")]:
            try:
                q = urllib.request.quote(name.replace(" ", "_"))
                url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{q}"
                req = urllib.request.Request(url, headers={"User-Agent": "Chirpa/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                    title = data.get("title", "")
                    page = (data.get("content_urls") or {}).get("desktop", {}).get("page", "")
                    img = (data.get("thumbnail") or {}).get("source") or (data.get("originalimage") or {}).get("source")
                    full = (data.get("originalimage") or {}).get("source") or img
                    extract = data.get("extract", "") or data.get("description", "")
                    # If page exists but no thumbnail, try pageimages API
                    if not img and title:
                        img = _wiki_pageimage(title)
                        full = img
                    if img:
                        with WIKI_LOCK:
                            WIKI_CACHE[species] = {"image": img, "url": page, "title": title, "full": full, "extract": extract}
                        return WIKI_CACHE[species]
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(2 * (attempt + 1))
                    break
                continue
            except Exception:
                continue

    # Fallback: Wikipedia search API
    for attempt in range(2):
        elapsed = time.time() - WIKI_LAST
        if elapsed < WIKI_DELAY:
            time.sleep(WIKI_DELAY - elapsed)
        WIKI_LAST = time.time()
        try:
            sq = urllib.request.quote(species.replace(" ", "_"))
            sr_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={sq}&format=json&srlimit=1"
            req = urllib.request.Request(sr_url, headers={"User-Agent": "Chirpa/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                sr = json.loads(resp.read())
                pages = sr.get("query", {}).get("search", [])
                if pages:
                    return wiki_image(pages[0]["title"])
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 * (attempt + 1))
        except Exception:
            pass

    # Final fallback: Wikimedia Commons
    img = _wiki_commons(species)
    if img:
        with WIKI_LOCK:
            WIKI_CACHE[species] = {"image": img, "url": None, "title": "", "full": img, "extract": ""}
        return WIKI_CACHE[species]
    # Don't cache MISS — allow retry on next request
    return {"image": None, "url": None, "title": "", "full": None}

def _wiki_commons(species):
    """Search Wikimedia Commons for a bird image."""
    global WIKI_LAST
    elapsed = time.time() - WIKI_LAST
    if elapsed < WIKI_DELAY:
        time.sleep(WIKI_DELAY - elapsed)
    WIKI_LAST = time.time()
    try:
        q = urllib.request.quote(species)
        url = f"https://commons.wikimedia.org/w/api.php?action=query&list=search&srsearch={q}&srnamespace=6&format=json&srlimit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Chirpa/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            files = data.get("query", {}).get("search", [])
            if files:
                elapsed2 = time.time() - WIKI_LAST
                if elapsed2 < WIKI_DELAY:
                    time.sleep(WIKI_DELAY - elapsed2)
                WIKI_LAST = time.time()
                fq = urllib.request.quote(files[0]["title"])
                url2 = f"https://commons.wikimedia.org/w/api.php?action=query&titles={fq}&prop=imageinfo&iiprop=url&iiurlwidth=400&format=json"
                req2 = urllib.request.Request(url2, headers={"User-Agent": "Chirpa/1.0"})
                with urllib.request.urlopen(req2, timeout=10) as resp2:
                    data2 = json.loads(resp2.read())
                    for pid, pg in data2.get("query", {}).get("pages", {}).items():
                        ii = pg.get("imageinfo", [{}])[0]
                        thumb = ii.get("thumburl") or ii.get("url")
                        if thumb:
                            return thumb
    except Exception:
        pass
    return None

def _wiki_pageimage(title):
    """Get main image from Wikipedia pageimages API (catches infobox images)."""
    global WIKI_LAST
    elapsed = time.time() - WIKI_LAST
    if elapsed < WIKI_DELAY:
        time.sleep(WIKI_DELAY - elapsed)
    WIKI_LAST = time.time()
    try:
        q = urllib.request.quote(title.replace(" ", "_"))
        url = f"https://en.wikipedia.org/w/api.php?action=query&titles={q}&prop=pageimages&format=json&pithumbsize=400"
        req = urllib.request.Request(url, headers={"User-Agent": "Chirpa/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            pages = data.get("query", {}).get("pages", {})
            for pid, page in pages.items():
                thumb = page.get("thumbnail", {})
                if thumb.get("source"):
                    return thumb["source"]
    except Exception:
        pass
    return None

# Pre-warm top species images (throttled)
def prewarm_images():
    top = api_species()[:30]
    print(f"Pre-warming images for {len(top)} species...", file=sys.stderr)
    for i, s in enumerate(top):
        if s["name"] not in WIKI_CACHE:
            wiki_image(s["name"])
        if i % 5 == 0 and i > 0:
            print(f"  {i}/{len(top)}...", file=sys.stderr)
    print(f"  done ({len(WIKI_CACHE)} cached)", file=sys.stderr)

# ── Local Species Cache ──────────────────────────────────────────────

LOCAL_DB = os.path.expanduser("~/.skyrats/species.db")
LOCAL_IMG = os.path.expanduser("~/.skyrats/images")

def local_species(species):
    """Get species data from local cache. Returns dict or None."""
    try:
        conn = sqlite3.connect(LOCAL_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM species WHERE name = ?", (species,)
        ).fetchone()
        conn.close()
        if row:
            d = dict(row)
            d['numeric_stats'] = json.loads(d.get('numeric_stats', '{}'))
            d['categorical_stats'] = json.loads(d.get('categorical_stats', '{}'))
            return d
    except:
        pass
    return None

def local_image_url(species):
    """Returns URL path for locally cached image, or None."""
    data = local_species(species)
    if data and data.get('image_path') and os.path.exists(data['image_path']):
        return f"/img/{os.path.basename(data['image_path'])}"
    return None

def local_bird_detail(species):
    """Get full bird detail from local cache."""
    data = local_species(species)
    if not data:
        return None
    # Format numeric stats for frontend
    num = []
    for name, val in data.get('numeric_stats', {}).items():
        unit = ''
        if 'cm' in name: unit = 'cm'
        elif 'g' in name: unit = 'g'
        elif 'days' in name: unit = 'days'
        elif 'years' in name: unit = 'yrs'
        num.append({'name': name, 'value': val, 'unit': unit})
    cat = [{'name': k, 'value': v} for k, v in data.get('categorical_stats', {}).items()]
    # Check for pre-rendered stat infographic
    slug = species.lower().replace(' ', '_').replace("'", '').replace('-', '_')
    stats_svg = f"/img/{slug}_stats.svg"
    svg_full = os.path.join(LOCAL_IMG, f"{slug}_stats.svg")
    if not os.path.isfile(svg_full):
        stats_svg = None
    # Get detection stats
    rows = q_listener("SELECT COUNT(*) as cnt, AVG(confidence) as avg FROM detections WHERE species = ?", (species,))
    d_stats = rows[0] if rows else {}
    return {
        'image': local_image_url(species),
        'full': data.get('full_image_url', ''),
        'url': data.get('wiki_url', ''),
        'extract': data.get('extract', ''),
        'detections': d_stats.get('cnt', 0),
        'avg_confidence': round(d_stats.get('avg', 0), 3) if d_stats.get('avg') else 0,
        'wikistats': {'num': num, 'cat': cat},
        'stats_svg': stats_svg,
        'status': SPECIES_STATUS.get(species, 'native'),
        'cached': True
    }

WIKIDATA_CACHE = {}
WIKIDATA_NUM = {'P2043':'Length','P2048':'Height','P2067':'Mass','P2050':'Wingspan','P7725':'Clutch','P7770':'Incubation'}
WIKIDATA_CAT = {'P141':'IUCN','P1403':'Trend'}
UNIT_MAP = {'Q174728':'cm','Q11573':'m','Q41803':'g','Q11570':'kg','Q199':'days','Q11574':'s'}

# Species status: native, introduced, or pest
SPECIES_STATUS = {
    'Common Myna': 'pest',
    'European Starling': 'pest',
    'Rock Pigeon': 'pest',
    'House Sparrow': 'pest',
    'European Goldfinch': 'introduced',
    'Red-whiskered Bulbul': 'introduced',
    'Eurasian Blackbird': 'introduced',
    'Spotted Dove': 'introduced',
    'Peaceful Dove': 'native',
    'Bar-shouldered Dove': 'native',
    'Crested Pigeon': 'native',
}

def wikidata_stats(species):
    if species in WIKIDATA_CACHE: return WIKIDATA_CACHE[species]
    try:
        q = urllib.request.quote(species)
        url = f'https://www.wikidata.org/w/api.php?action=wbsearchentities&search={q}&language=en&format=json&limit=1'
        req = urllib.request.Request(url, headers={'User-Agent':'Chirpa/1.0'})
        with urllib.request.urlopen(req,timeout=8) as r:
            results = json.loads(r.read()).get('search',[])
            if not results: WIKIDATA_CACHE[species]={}; return {}
            qid = results[0]['id']
        time.sleep(0.25)
        url2 = f'https://www.wikidata.org/wiki/Special:EntityData/{qid}.json'
        req2 = urllib.request.Request(url2, headers={'User-Agent':'Chirpa/1.0'})
        with urllib.request.urlopen(req2,timeout=8) as r2:
            claims = json.loads(r2.read()).get('entities',{}).get(qid,{}).get('claims',{})
            stats={'num':{},'cat':{}}
            for pid,label in WIKIDATA_NUM.items():
                if pid in claims:
                    v = claims[pid][0].get('mainsnak',{}).get('datavalue',{}).get('value',{})
                    if isinstance(v,dict) and 'amount' in v:
                        try: stats['num'][label]={'val':float(v['amount']),'unit':v.get('unit','').split('/')[-1]}
                        except: pass
            for pid,label in WIKIDATA_CAT.items():
                if pid in claims:
                    v = claims[pid][0].get('mainsnak',{}).get('datavalue',{}).get('value',{})
                    if isinstance(v,dict) and 'id' in v: stats['cat'][label]=v['id']
            WIKIDATA_CACHE[species]=stats; return stats
    except: WIKIDATA_CACHE[species]={}; return {}

def _wd_label(qid):
    if not qid: return '?'
    try:
        time.sleep(0.15)
        url = f'https://www.wikidata.org/wiki/Special:EntityData/{qid}.json'
        req = urllib.request.Request(url, headers={'User-Agent':'Chirpa/1.0'})
        with urllib.request.urlopen(req,timeout=5) as r:
            return json.loads(r.read()).get('entities',{}).get(qid,{}).get('labels',{}).get('en',{}).get('value',qid)
    except: return qid

def format_stats(stats):
    num=[{'name':n,'value':d['val'],'unit':UNIT_MAP.get(d['unit'],'')} for n,d in stats.get('num',{}).items()]
    cat=[{'name':n,'value':_wd_label(qid)} for n,qid in stats.get('cat',{}).items()]
    return {'num':num,'cat':cat}

SETTINGS_FILE = os.path.expanduser("~/.skyrats/cameras.json")

def get_settings():
    """Load camera + birdnet settings from JSON."""
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except:
        return {"cameras": [], "birdnet": {}, "display": {}}

def save_settings(cfg):
    """Save settings to JSON file."""
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

def test_camera_stream(cam_id):
    """Quick connectivity test for a camera stream."""
    cfg = get_settings()
    cam = next((c for c in cfg.get("cameras", []) if c["id"] == cam_id), None)
    if not cam:
        return {"ok": False, "error": "Camera not found"}
    result = {"ok": False, "id": cam_id, "name": cam["name"], "checks": {}}
    # Test snapshot URL
    snap = cam.get("snapshot", "")
    if snap:
        try:
            req = urllib.request.Request(snap, headers={"User-Agent": "Chirpa/1.0"})
            with urllib.request.urlopen(req, timeout=4) as r:
                data = r.read()
                result["checks"]["snapshot"] = {"ok": True, "size": len(data), "content_type": r.headers.get("Content-Type", "?")}
        except Exception as e:
            result["checks"]["snapshot"] = {"ok": False, "error": str(e)}
    # Test stream URL (just check if the host is reachable)
    stream = cam.get("stream", "")
    if stream and stream.startswith("rtsp://"):
        # Extract host:port
        import re
        m = re.search(r'rtsp://(?:[^@]+@)?([^:/]+)(?::(\d+))?', stream)
        if m:
            host = m.group(1)
            port = int(m.group(2) or 554)
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            try:
                s.connect((host, port))
                s.close()
                result["checks"]["rtsp_port"] = {"ok": True, "host": host, "port": port}
            except Exception as e:
                result["checks"]["rtsp_port"] = {"ok": False, "error": str(e)}
    result["ok"] = any(v.get("ok") for v in result["checks"].values())
    return result

# ── HTTP Handler ─────────────────────────────────────────────────────

# ── Location lookup (server-side IP geolocation) ────────────────────

def get_location(ip):
    if ip in ('127.0.0.1', '::1', 'localhost'):
        return 'Home'
    try:
        r = subprocess.run(['curl', '-s', '--max-time', '3',
            f'https://ipinfo.io/{ip}/json'],
            capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout:
            d = json.loads(r.stdout)
            city = d.get('city','')
            region = d.get('region','')
            if city and region:
                return f'{city}, {region}'
            if city:
                return city
            if d.get('country'):
                return d['country']
    except:
        pass
    # Fallback: try server's own IP
    try:
        r = subprocess.run(['curl', '-s', '--max-time', '3',
            'https://ipinfo.io/json'],
            capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout:
            d = json.loads(r.stdout)
            city = d.get('city','')
            region = d.get('region','')
            if city:
                return f'{city}, {region}' if region else city
    except:
        pass
    return ''

# ── Handler ──────────────────────────────────────────────────────────

def test_connection(handler):
    """Test camera connectivity: ping + port check."""
    body_len = int(handler.headers.get('Content-Length', 0))
    if body_len == 0:
        return {"ok": False, "error": "No data received"}
    try:
        cfg = json.loads(handler.rfile.read(body_len))
    except:
        return {"ok": False, "error": "Invalid JSON"}
    ip = cfg.get("ip", "").strip()
    port = cfg.get("port", "554")
    path = cfg.get("path", "/stream2")
    user = cfg.get("user", "").strip()
    pw = cfg.get("pass", "").strip()
    errors = []
    warnings = []
    if not ip:
        errors.append("IP address is required")
        return {"ok": False, "errors": errors}
    if not re.match(r'^(\d{1,3}\.){3}\d{1,3}$', ip):
        errors.append(f"'{ip}' is not a valid IP address")
        return {"ok": False, "errors": errors}
    # Ping
    ping_ok = os.system(f"ping -c 1 -W 2 {ip} > /dev/null 2>&1") == 0
    if not ping_ok:
        errors.append(f"Cannot ping {ip} — camera may be offline or blocking ICMP")
    # Port check
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((ip, int(port)))
        sock.close()
        if result != 0:
            errors.append(f"Port {port} is not open on {ip} — RTSP may be disabled")
    except Exception as e:
        errors.append(f"Connection error: {str(e)}")
    # Optional RTSP handshake check
    if ping_ok and not errors:
        try:
            url = f"rtsp://{user}:{pw}@{ip}:{port}{path}"
            # Use ffprobe to test RTSP reachability (quick, no streaming)
            rc = os.system(f"timeout 5 ffprobe -v quiet -show_streams -rtsp_transport tcp \"{url}\" >/dev/null 2>&1")
            if rc != 0:
                warnings.append("RTSP stream not responding — check path and credentials")
                errors.append(f"RTSP stream unreachable at {path}")
        except:
            warnings.append("Could not verify RTSP stream — ffprobe unavailable")
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, f, *a): print(f"[{datetime.now():%H:%M:%S}] {self.client_address[0]} {f % a}", flush=True)

    def json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self):
        p = urlparse(self.path)
        path, q = p.path, parse_qs(p.query)
        if path == "/": return self.send_html()
        if path == "/api/summary": return self.json(api_summary())
        if path == "/api/timeline": return self.json(api_timeline())
        if path == "/api/aggregate": return self.json(api_aggregate(q.get("period",["day"])[0]))
        if path == "/api/species": return self.json(api_species())
        if path == "/api/recent": return self.json(api_recent(int(q.get("limit", [50])[0])))
        if path == "/api/cameras": return self.json(api_cameras())
        if path == "/api/bird-image":
            sp = q.get("species", [""])[0]
            if not sp: return self.json({})
            # Serve from local cache first
            local = local_image_url(sp)
            if local: return self.json({'image': local, 'url': None, 'local': True})
            return self.json(wiki_image(sp) if sp else {})
        if path == "/api/bird-detail":
            sp = q.get("species", [""])[0]
            if not sp: return self.json({})
            # Local cache first
            local = local_bird_detail(sp)
            if local: return self.json(local)
            # Fallback to live
            img = wiki_image(sp)
            rows = q_listener("SELECT COUNT(*) as cnt, AVG(confidence) as avg FROM detections WHERE species = ?", (sp,))
            stats = rows[0] if rows else {}
            wd = format_stats(wikidata_stats(sp))
            return self.json({**img, "detections": stats.get("cnt", 0), "avg_confidence": round(stats.get("avg", 0), 3) if stats.get("avg") else 0, "wikistats": wd, "status": SPECIES_STATUS.get(sp, 'native'), "cached": False})
        # ── Settings API ─────────────────────────────────────────
        if path == "/api/settings":
            return self.json(get_settings())
        if path == "/api/settings/save":
            body_len = int(self.headers.get('Content-Length', 0))
            if body_len > 0:
                try:
                    new_cfg = json.loads(self.rfile.read(body_len))
                    save_settings(new_cfg)
                    return self.json({"ok": True})
                except:
                    return self.json({"ok": False, "error": "Invalid JSON"})
            return self.json({"ok": False})
        if path == "/api/settings/test-camera":
            cam_id = q.get("id", [""])[0]
            return self.json(test_camera_stream(cam_id))
        if path == "/api/test-connection" and self.command == "POST":
            return self.json(test_connection(self))
        # Serve local images
        if path == "/chart-js":
            chart_path = os.path.join(os.path.dirname(LOCAL_IMG), "chart.min.js")
            if os.path.isfile(chart_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                with open(chart_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404)
            return
        if path.startswith("/img/"):
            fname = os.path.basename(path[5:])
            if not fname or ".." in fname:
                self.send_error(400)
                return
            fpath = os.path.join(LOCAL_IMG, fname)
            if os.path.isfile(fpath):
                ext = os.path.splitext(fname)[1].lower()
                mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                           ".svg": "image/svg+xml", ".gif": "image/gif", ".webp": "image/webp"}
                self.send_response(200)
                self.send_header("Content-Type", mime_map.get(ext, "application/octet-stream"))
                self.send_header("Cache-Control", "max-age=3600")
                self.end_headers()
                with open(fpath, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404)
            return

    def send_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ip = self.client_address[0]
        loc = get_location(ip)
        self.wfile.write(HTML.replace('__location__', loc).encode())

# ── HTML ─────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Chirpa — Homelab</title>
<style>
/* System font stack — no external font CDN needed */
@font-face{font-family:'Google Sans';src:local('Roboto'),local('sans-serif')}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,sans-serif;background:#202124;color:#e8eaed;min-height:100vh}
.topbar{background:#303134;border-bottom:1px solid#3c4043;padding:0 24px;height:64px;display:flex;align-items:center;gap:14px;position:sticky;top:0;z-index:100}
.topbar h1{font-family:'Google Sans',sans-serif;font-size:22px;font-weight:500;color:#8ab4f8;display:flex;align-items:center;gap:8px}
.topbar .sub{font-size:13px;color:#9aa0a6}
.topbar .chip{background:rgba(138,180,248,.15);color:#8ab4f8;padding:4px 12px;border-radius:16px;font-size:12px;font-weight:500}
.topbar .dot{width:8px;height:8px;border-radius:50%;background:#34a853;display:inline-block;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
@keyframes shimmer{0%{background-position:-400px 0}100%{background-position:400px 0}}
.skeleton{background:linear-gradient(90deg,#303134 25%,#3c4043 50%,#303134 75%);background-size:800px 100%;animation:shimmer 1.8s ease-in-out infinite;border-radius:8px}
.sk-stat{width:60px;height:28px;margin-bottom:4px}.sk-sub{width:80px;height:14px}
.sk-chart{width:100%;height:280px}.sk-card{height:200px}.sk-row{display:flex;gap:12px;margin-bottom:8px}.sk-avatar{width:56px;height:56px;border-radius:12px;flex-shrink:0}.sk-lines{flex:1;display:flex;flex-direction:column;gap:8px}.sk-line{height:14px}.sk-line.s{width:60%}.sk-line.m{width:80%}.sk-line.l{width:90%}
.fade-in{animation:fadeIn .4s ease-out forwards}@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}.species-card.fade-in{animation-delay:calc(var(--i,0)*40ms)}
.container{max-width:1440px;margin:24px auto;padding:0 24px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px}
.grid3{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-bottom:24px}
.card{background:#303134;border-radius:20px;padding:24px;border:1px solid#3c4043}
.card:hover{border-color:#5f6368}
.stat-value{font-family:'Google Sans',sans-serif;font-size:38px;font-weight:500;color:#e8eaed;line-height:1.2}
.stat-label{font-size:13px;color:#9aa0a6;margin-top:4px}
.stat-sub{font-size:12px;color:#80868b;margin-top:2px}
.card h2{font-family:'Google Sans',sans-serif;font-size:18px;font-weight:500;margin-bottom:16px;color:#e8eaed !important}
.card h3{font-family:'Google Sans',sans-serif;font-size:15px;font-weight:500}
.chart-wrap{position:relative;height:300px}.chart-wrap.tall{height:380px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:12px;border-bottom:2px solid#3c4043;color:#9aa0a6;font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
td{padding:12px;border-bottom:1px solid#3c4043;vertical-align:middle}
tr:hover td{background:rgba(255,255,255,.03)}
.conf-pill{display:inline-flex;align-items:center;gap:8px;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:500}
.conf-high{background:rgba(129,201,149,.15);color:#81c995}
.conf-mid{background:rgba(251,188,4,.15);color:#fdd663}
.conf-low{background:rgba(242,139,130,.15);color:#f28b82}
.badge{display:inline-block;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:500}
.badge-c230{background:rgba(138,180,248,.15);color:#8ab4f8}
.badge-c246{background:rgba(197,138,249,.15);color:#c58af9}
.badge-unknown{background:rgba(154,160,166,.15);color:#9aa0a6}
.species-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}
.species-card{background:#303134;border-radius:16px;overflow:hidden;border:1px solid#3c4043;cursor:pointer;transition:all .2s}
.species-card:hover{border-color:#8ab4f8;transform:translateY(-2px)}
.species-card .img-wrap{width:100%;height:140px;overflow:hidden;background:#202124;position:relative}
.species-card .img-wrap .spinner{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none;z-index:3}
.species-card .img-wrap .spinner::after{content:'';width:28px;height:28px;border:3px solid #3c4043;border-top-color:#8ab4f8;border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.species-card .img-wrap.loaded .spinner{display:none}
.species-card .img-wrap img{width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .5s ease,transform .5s ease;transform:scale(1.08)}
.species-card .img-wrap img.loaded{opacity:1;transform:scale(1)}
.species-card .img-wrap .placeholder{display:flex;align-items:center;justify-content:center;height:100%;font-size:48px;opacity:.3}
.species-card .info{padding:14px}
.species-card .name{font-weight:500;font-size:14px;margin-bottom:6px;color:#e8eaed}
.species-card .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.species-card .count{font-size:12px;color:#8ab4f8;font-weight:500}
.species-card .perf{font-size:12px;color:#9aa0a6}
.species-card .mini-bar{flex:1;min-width:60px;height:4px;background:#3c4043;border-radius:2px;overflow:hidden}
.species-card .mini-fill{height:100%;border-radius:2px}
.tab-bar{display:flex;gap:4px;background:#202124;border-radius:24px;padding:4px;margin-bottom:20px;width:fit-content}
.tab-btn{padding:8px 20px;border-radius:20px;border:none;background:transparent;font-size:13px;font-weight:500;color:#9aa0a6;cursor:pointer;transition:all .2s}
.tab-btn.active{background:#303134;color:#8ab4f8;box-shadow:0 1px 3px rgba(0,0,0,.3)}
.per-btn{padding:6px 14px;border-radius:16px;border:1px solid #3c4043;background:transparent;font-size:12px;font-weight:500;color:#9aa0a6;cursor:pointer;transition:all .15s}
.per-btn:hover{border-color:#8ab4f8;color:#e8eaed}
.per-btn.active{background:#303134;color:#8ab4f8;border-color:#8ab4f8}
.inp{width:100%;padding:10px 12px;background:#202124;border:1px solid #3c4043;border-radius:8px;color:#e8eaed;font-size:13px;font-family:inherit;outline:none;transition:border .2s}
.inp:focus{border-color:#8ab4f8}
.inp::placeholder{color:#5f6368}
select.inp{cursor:pointer}
.wiz-step:hover{border-color:#8ab4f8 !important}
.wiz-card:hover{border-color:#8ab4f8 !important;transform:translateY(-2px)}
/* modal */
#detail-overlay{visibility:hidden;opacity:0;position:fixed;z-index:2147483647;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.7);padding:80px 20px 20px;overflow-y:auto;-webkit-overflow-scrolling:touch;transition:opacity .15s;will-change:transform}
#detail-overlay.active{visibility:visible;opacity:1}
#detail-card{background:#303134;border-radius:24px;max-width:560px;margin:0 auto;width:100%;max-height:none;overflow-y:visible;border:1px solid#3c4043}
#detail-card .hero{position:relative}
#detail-card .hero img{width:100%;height:240px;object-fit:cover;border-radius:24px 24px 0 0;background:#202124}
#detail-card .hero .close{position:absolute;top:14px;right:14px;background:rgba(0,0,0,.6);color:#fff;border:none;width:36px;height:36px;border-radius:50%;font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .2s}
#detail-card .hero .close:hover{background:rgba(0,0,0,.85)}
#detail-card .body{padding:24px}
#detail-card .body h2{font-family:'Google Sans',sans-serif;font-size:22px;font-weight:500;margin-bottom:8px}
#detail-card .body .meta{color:#9aa0a6;font-size:13px;margin-bottom:16px;line-height:1.6}
#detail-card .body .stat-row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:16px}
#detail-card .body .mini{background:#202124;border-radius:12px;padding:14px;text-align:center}
#detail-card .body .mini .val{font-family:'Google Sans',sans-serif;font-size:24px;color:#8ab4f8}
#detail-card .body .mini .lbl{font-size:11px;color:#9aa0a6;margin-top:2px}
.wiki-link{display:inline-flex;align-items:center;gap:6px;color:#8ab4f8;text-decoration:none;font-size:13px;font-weight:500;padding:8px 16px;border-radius:20px;background:rgba(138,180,248,.1);transition:background .2s}
.wiki-link:hover{background:rgba(138,180,248,.2)}
.empty-state{text-align:center;padding:48px 24px;color:#5f6368}
.empty-state .icon{font-size:48px;margin-bottom:12px;opacity:.5}
@media(max-width:900px){.grid4{grid-template-columns:repeat(2,1fr)}.grid2,.grid3{grid-template-columns:1fr}}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9999;display:flex;align-items:center;justify-content:center}
.modal-overlay.hidden{display:none}
.modal-card{background:#2d2d30;border:1px solid #3c4043;border-radius:16px;width:560px;max-width:95vw;max-height:85vh;overflow-y:auto;padding:0;box-shadow:0 16px 48px rgba(0,0,0,.5);animation:modalIn .25s ease-out}
@keyframes modalIn{from{opacity:0;transform:scale(.95) translateY(16px)}to{opacity:1;transform:scale(1) translateY(0)}}
.modal-header{padding:20px 24px 12px;display:flex;align-items:center;justify-content:space-between}
.modal-header h3{font-size:16px;font-weight:500;margin:0}
.modal-body{padding:0 24px 20px}
.modal-steps{display:flex;gap:4px;padding:8px 24px 16px}
.modal-step-dot{flex:1;height:4px;border-radius:2px;background:#3c4043;transition:background .2s}
.modal-step-dot.active{background:#8ab4f8}
.modal-step-dot.done{background:#81c995}
.step-content{display:none}
.step-content.active{display:block}
.brand-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.brand-card{padding:14px 8px;background:#202124;border:2px solid #3c4043;border-radius:10px;cursor:pointer;text-align:center;transition:all .15s;font-size:11px}
.brand-card:hover{border-color:#8ab4f8;background:#252528}
.brand-card.selected{border-color:#8ab4f8;background:#1a2a3a}
.brand-card .brand-icon{font-size:26px;margin-bottom:4px}
.brand-card .brand-name{font-weight:600;color:#e8eaed}
.brand-card .brand-sub{font-size:10px;color:#9aa0a6;margin-top:2px}
.modal-footer{padding:16px 24px;display:flex;gap:8px;justify-content:flex-end;border-top:1px solid #3c4043}
.modal-footer button{padding:8px 20px;border-radius:8px;font-size:13px;font-weight:500;cursor:pointer;border:none;transition:all .15s}
.modal-btn-prev{background:#303134;color:#e8eaed}
.modal-btn-prev:hover{background:#3c4043}
.modal-btn-next{background:#8ab4f8;color:#202124}
.modal-btn-next:hover{background:#aecbfa}
.modal-btn-done{background:#34a853;color:#fff}
.modal-btn-done:hover{background:#46b964}
</style>
<script src="/chart-js?v=2"></script>
</head>
<body>

<div class="topbar">
  <h1><a href="/" onclick="switchTab('dashboard');return false" style="text-decoration:none"><img src="/img/chirpa_logo.png" alt="Chirpa" style="height:32px;vertical-align:middle"></a></h1><span id="location-tag" class="sub">__location__</span>

  <span class="chip"><span class="dot"></span> Live</span>
</div>

<div class="tab-bar">
  <button class="tab-btn active" onclick="switchTab('dashboard')">🏠 Dashboard</button>
  <button class="tab-btn" onclick="switchTab('settings')">⚙️ Settings</button>
</div>

<div id="tab-dashboard" class="container">
  <div class="period-bar" style="display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap">
    <button class="per-btn active" data-p="hour" onclick="switchPeriod('hour')">⏱ Hourly</button>
    <button class="per-btn" data-p="day" onclick="switchPeriod('day')">📅 Daily</button>
    <button class="per-btn" data-p="week" onclick="switchPeriod('week')">📊 Weekly</button>
    <button class="per-btn" data-p="month" onclick="switchPeriod('month')">🗓 Monthly</button>
  </div>
  <div class="grid4" id="stats-row">
    <div class="card"><div class="skeleton sk-stat" id="sk-total"></div><div class="stat-value fade-in" id="st-total" style="display:none">—</div><div class="stat-label">Total Detections</div></div>
    <div class="card"><div class="skeleton sk-stat" id="sk-species"></div><div class="stat-value fade-in" id="st-species" style="display:none">—</div><div class="stat-label">Unique Species</div></div>
    <div class="card"><div class="skeleton sk-stat" id="sk-today"></div><div class="stat-value fade-in" id="st-today" style="display:none">—</div><div class="stat-label">Today</div><div class="stat-sub" id="st-today-sp"></div></div>
    <div class="card"><div class="skeleton sk-stat" id="sk-cams"></div><div class="stat-value fade-in" id="st-cams" style="display:none">—</div><div class="stat-label">Active Cameras</div></div>
  </div>

  <div class="grid2">
    <div class="card"><h2>📈 Detection Timeline</h2><div class="chart-wrap"><canvas id="chart-timeline"></canvas><div class="skeleton sk-chart" id="sk-timeline"></div></div></div>
    <div class="card"><h2>🥧 Species Breakdown</h2><div class="chart-wrap"><canvas id="chart-pie"></canvas><div class="skeleton sk-chart" id="sk-pie"></div></div></div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <h2>🦜 All Species</h2>
    <div class="species-grid" id="species-grid">
      <div class="species-card skeleton"><div class="sk-row"><div class="skeleton sk-avatar"></div><div class="sk-lines"><div class="skeleton sk-line m"></div><div class="skeleton sk-line s"></div></div></div><div class="skeleton sk-line" style="width:100%;height:8px;border-radius:4px;margin-top:8px"></div></div>
      <div class="species-card skeleton"><div class="sk-row"><div class="skeleton sk-avatar"></div><div class="sk-lines"><div class="skeleton sk-line m"></div><div class="skeleton sk-line s"></div></div></div><div class="skeleton sk-line" style="width:100%;height:8px;border-radius:4px;margin-top:8px"></div></div>
      <div class="species-card skeleton"><div class="sk-row"><div class="skeleton sk-avatar"></div><div class="sk-lines"><div class="skeleton sk-line m"></div><div class="skeleton sk-line s"></div></div></div><div class="skeleton sk-line" style="width:100%;height:8px;border-radius:4px;margin-top:8px"></div></div>
      <div class="species-card skeleton"><div class="sk-row"><div class="skeleton sk-avatar"></div><div class="sk-lines"><div class="skeleton sk-line m"></div><div class="skeleton sk-line s"></div></div></div><div class="skeleton sk-line" style="width:100%;height:8px;border-radius:4px;margin-top:8px"></div></div>
      <div class="species-card skeleton"><div class="sk-row"><div class="skeleton sk-avatar"></div><div class="sk-lines"><div class="skeleton sk-line m"></div><div class="skeleton sk-line s"></div></div></div><div class="skeleton sk-line" style="width:100%;height:8px;border-radius:4px;margin-top:8px"></div></div>
      <div class="species-card skeleton"><div class="sk-row"><div class="skeleton sk-avatar"></div><div class="sk-lines"><div class="skeleton sk-line m"></div><div class="skeleton sk-line s"></div></div></div><div class="skeleton sk-line" style="width:100%;height:8px;border-radius:4px;margin-top:8px"></div></div>
      <div class="species-card skeleton"><div class="sk-row"><div class="skeleton sk-avatar"></div><div class="sk-lines"><div class="skeleton sk-line m"></div><div class="skeleton sk-line s"></div></div></div><div class="skeleton sk-line" style="width:100%;height:8px;border-radius:4px;margin-top:8px"></div></div>
      <div class="species-card skeleton"><div class="sk-row"><div class="skeleton sk-avatar"></div><div class="sk-lines"><div class="skeleton sk-line m"></div><div class="skeleton sk-line s"></div></div></div><div class="skeleton sk-line" style="width:100%;height:8px;border-radius:4px;margin-top:8px"></div></div>
    </div>
  </div>

  <div class="grid2">
    <div class="card" style="overflow:hidden">
      <h2>📋 Recent Detections</h2>
      <div id="tab-recent"><div class="empty-state"><div class="icon">🔍</div>Loading...</div></div>
    </div>
    <div class="card">
      <h2>📷 Camera Breakdown</h2>
      <div class="chart-wrap tall"><canvas id="chart-cam"></canvas></div>
      <div style="margin-top:16px" id="cam-legend"></div>
    </div>
  </div>
</div>
<!-- end tab-dashboard -->
</div>

<!-- Settings Tab -->
<div id="tab-settings" class="container" style="display:none">
  <div class="card" style="margin-bottom:16px">
    <h2 style="margin-bottom:12px">📹 Camera Streams</h2>
    <div id="camera-list"></div>
    <button class="tab-btn" onclick="openWizard()" style="margin-top:12px;background:#8ab4f8;color:#202124;font-weight:600">+ Add Camera</button>
  </div>

  <div class="card" style="margin-bottom:16px">
    
<!-- Camera Wizard Modal -->
<div class="modal-overlay hidden" id="cam-modal">
  <div class="modal-card">
    <div class="modal-header">
      <h3 id="modal-title">🧪 Add Camera</h3>
      <button onclick="closeWizard()" style="background:none;border:none;color:#9aa0a6;font-size:20px;cursor:pointer;padding:0 4px">&times;</button>
    </div>
    <div class="modal-steps" id="modal-steps">
      <div class="modal-step-dot active" data-step="0"></div>
      <div class="modal-step-dot" data-step="1"></div>
      <div class="modal-step-dot" data-step="2"></div>
      <div class="modal-step-dot" data-step="3"></div>
    </div>
    <div class="modal-body">
      <div class="step-content active" id="step-0">
        <p style="font-size:12px;color:#9aa0a6;margin-bottom:14px">Select your camera brand</p>
        <div class="brand-grid" id="brand-grid">
        </div>
      </div>
      <div class="step-content" id="step-1">
        <p style="font-size:12px;color:#9aa0a6;margin-bottom:14px">Connection details</p>
        <div style="display:grid;gap:10px">
          <div><label style="display:block;font-size:11px;color:#9aa0a6;margin-bottom:3px">Name</label><input id="wiz-name" class="inp" placeholder="e.g. Front Yard"></div>
          <div style="display:grid;grid-template-columns:2fr 1fr;gap:10px">
            <div><label style="display:block;font-size:11px;color:#9aa0a6;margin-bottom:3px">IP Address</label><input id="wiz-ip" class="inp" placeholder="192.168.1.x"></div>
            <div><label style="display:block;font-size:11px;color:#9aa0a6;margin-bottom:3px">Port</label><input id="wiz-port" class="inp" value="554"></div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
            <div><label style="display:block;font-size:11px;color:#9aa0a6;margin-bottom:3px">Username</label><input id="wiz-user" class="inp" placeholder="admin"></div>
            <div><label style="display:block;font-size:11px;color:#9aa0a6;margin-bottom:3px">Password</label><input id="wiz-pass" class="inp" type="password"></div>
          </div>
        </div>
      </div>
      <div class="step-content" id="step-2">
        <p style="font-size:12px;color:#9aa0a6;margin-bottom:12px">📖 Setup guide</p>
        <div id="wiz-guide" style="font-size:11px;color:#bdc1c6;line-height:1.7;background:#202124;border-radius:10px;padding:14px">
        </div>
      </div>
      <div class="step-content" id="step-3">
        <p style="font-size:12px;color:#9aa0a6;margin-bottom:14px">Stream configuration</p>
        <div style="display:grid;gap:10px">
          <div><label style="display:block;font-size:11px;color:#9aa0a6;margin-bottom:3px">RTSP Stream Path</label><input id="wiz-path" class="inp" value="/stream2"><span style="font-size:10px;color:#5f6368">Full URL: <code style="color:#8ab4f8" id="wiz-preview">rtsp://user:pass@192.168.1.x:554/stream2</code></span></div>
          <div><label style="display:block;font-size:11px;color:#9aa0a6;margin-bottom:3px">Snapshot URL <span style="color:#5f6368">(optional)</span></label><input id="wiz-snap" class="inp" placeholder="http://ip/cgi-bin/snapshot.cgi"></div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
            <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:#9aa0a6"><input type="checkbox" id="wiz-audio" checked> Has audio (BirdNET)</label>
            <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:#9aa0a6"><input type="checkbox" id="wiz-enabled" checked> Enabled</label>
          </div>
        </div>
      </div>
      <div class="step-content" id="step-4">
        <p style="font-size:12px;color:#9aa0a6;margin-bottom:14px">Review, test, &amp; save</p>
        <div id="wiz-summary" style="font-size:12px;color:#bdc1c6;line-height:1.8;background:#202124;border-radius:10px;padding:16px">
        </div>
        <div style="margin-top:12px">
          <button onclick="testConnection()" id="wiz-test-btn" style="padding:8px 16px;border-radius:8px;border:1px solid #8ab4f8;background:transparent;color:#8ab4f8;font-size:12px;cursor:pointer;transition:all .15s">🔌 Test Connection</button>
          <span id="wiz-test-result" style="margin-left:10px;font-size:12px"></span>
        </div>
      </div>
    </div>
    <div class="modal-footer">
      <button class="modal-btn-prev" id="wiz-prev" onclick="wizPrev()" style="visibility:hidden">← Back</button>
      <div style="flex:1"></div>
      <button class="modal-btn-next" id="wiz-next" onclick="wizNext()">Next →</button>
      <button class="modal-btn-done hidden" id="wiz-done" onclick="wizSave()">✓ Add Camera</button>
    </div>
  </div>
</div>

  <div class="card" style="margin-bottom:16px">
    <h2 style="margin-bottom:12px">🔧 BirdNET Settings</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div><label style="font-size:11px;color:#9aa0a6">Min Confidence</label><input class="inp" id="bn-conf" type="number" min="0.1" max="0.99" step="0.05" value="0.60"></div>
      <div><label style="font-size:11px;color:#9aa0a6">Auto Refresh (sec)</label><input class="inp" id="bn-refresh" type="number" min="10" max="300" value="30"></div>
      <div><label style="font-size:11px;color:#9aa0a6">Latitude</label><input class="inp" id="bn-lat" type="number" step="0.1" value="-33.5"></div>
      <div><label style="font-size:11px;color:#9aa0a6">Longitude</label><input class="inp" id="bn-lon" type="number" step="0.1" value="150.7"></div>
    </div>
    <button class="tab-btn" style="margin-top:12px;background:#303134;color:#8ab4f8" onclick="saveBirdnetSettings()">Save BirdNET Settings</button>
  </div>
</div>

<!-- Detail Modal -->
<div id="detail-overlay" onclick="if(event.target===this)closeDetail()">
  <div id="detail-card" style="position:relative">
    <button class="close-btn" onclick="closeDetail()" style="position:absolute;top:14px;right:14px;z-index:10;background:rgba(0,0,0,.7);color:#fff;border:none;width:36px;height:36px;border-radius:50%;font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center">×</button>
    <div class="hero">
      <img id="det-img" src="" alt="" style="cursor:zoom-in" onclick="openFull(event)" title="Click for full-size">
      <button class="close" onclick="closeDetail()">×</button>
    </div>
    <div class="body">
      <h2 id="det-name"></h2>
      <div class="meta" id="det-extract" style="font-size:13px;line-height:1.7;max-height:200px;overflow-y:auto;margin-bottom:12px;padding:12px;background:#202124;border-radius:12px"></div>
      <div class="stat-row">
        <div class="mini"><div class="val" id="det-count">—</div><div class="lbl">Detections</div></div>
        <div class="mini"><div class="val" id="det-conf">—</div><div class="lbl">Avg Confidence</div></div>
        <div class="mini"><div class="val" id="det-last">—</div><div class="lbl">Last Seen</div></div>
      </div>
      <div id="det-stats" style="display:none;margin-bottom:16px">
        <h3 style="margin-bottom:10px;font-size:13px;color:#9aa0a6;text-transform:uppercase;letter-spacing:.5px">📊 Species Stats</h3>
        <img id="det-infographic" src="" style="width:100%;max-width:540px;border-radius:10px;display:none;margin:0 auto" alt="Stats infographic">
        <div id="det-num-bars"></div>
        <div id="det-cat-tags" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px"></div>
      </div>
      <span id="det-status" style="display:none;font-size:10px;font-weight:600;padding:2px 8px;border-radius:8px;margin-bottom:10px;display:inline-block"></span>
      <a class="wiki-link" id="det-wiki" href="#" target="_blank">📖 Wikipedia →</a>
    </div>
  </div>
</div>

<script>
const C=['#4a6fa5','#8b3a3a','#9e7d27','#3d6b4f','#b55a30','#2d6e6e','#6b3d7a','#a34a4a','#4d6b4a','#3d5a80'];
const api=u=>fetch(u).then(r=>r.json());
let chartTL,chartPie,chartCam;

function cc(c){if(c>=0.7)return'conf-high';if(c>=0.4)return'conf-mid';return'conf-low'}
function cp(c){if(c>=0.7)return'#81c995';if(c>=0.4)return'#fdd663';return'#f28b82'}

function switchTab(tab){
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-dashboard').style.display=tab==='dashboard'?'block':'none';
  document.getElementById('tab-settings').style.display=tab==='settings'?'block':'none';
  if(tab==='dashboard') document.querySelector('.tab-btn:first-child').classList.add('active');
  else document.querySelector('.tab-btn:last-child').classList.add('active');
  if(tab==='settings') loadSettings();
}

async function loadSettings(){
  const s=await api('/api/settings');
  if(!s)return;
  document.getElementById('bn-conf').value=(s.birdnet||{}).min_confidence||0.60;
  document.getElementById('bn-refresh').value=(s.display||{}).auto_refresh||30;
  document.getElementById('bn-lat').value=(s.birdnet||{}).lat||-33.5;
  document.getElementById('bn-lon').value=(s.birdnet||{}).lon||150.7;
  renderCameraList(s.cameras||[]);
}

function renderCameraList(cams){
  const el=document.getElementById('camera-list');
  if(!cams.length){el.innerHTML='<div class="empty-state"><div class="icon">📷</div>No cameras configured</div>';return;}
  el.innerHTML=cams.map(c=>`<div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:#202124;border-radius:10px;margin-bottom:6px;border:1px solid ${c.enabled?'#3c4043':'#2a2a2e'}">
    <div style="flex:1">
      <div style="font-weight:600;font-size:13px">${c.enabled?'🟢':'⏸️'} ${c.name.replace(/'/g,"\\'")}</div>
      <div style="font-size:11px;color:#9aa0a6">${c.type?.toUpperCase()||'RTSP'} · ${c.audio?'🎤 Audio':'📹 Video only'}${c.detection_source?' · 🐦 Detection':''}</div>
      <div style="font-size:10px;color:#5f6368;word-break:break-all">${(c.stream||'').replace(/rtsp:\/\/[^@]+@/, 'rtsp://***@')}</div>
    </div>
    <div style="display:flex;gap:6px">
      <button class="tab-btn" style="padding:6px 14px;font-size:11px;background:#252528" onclick="testCamera('${c.id}')">🔍 Test</button>
      <button class="tab-btn" style="padding:6px 14px;font-size:11px;background:#252528" onclick="editCamera('${c.id}')">✏️</button>
      <button class="tab-btn" style="padding:6px 14px;font-size:11px;background:rgba(229,115,115,.15);color:#e57373" onclick="deleteCamera('${c.id}')">🗑️</button>
    </div>
  </div>`).join('');
}

// ── Camera Wizard ──────────────────────────────────────────────
const BRANDS=[
  {id:'tapo-c230',name:'Tapo C230',icon:'📹',sub:'Pan/Tilt • 2K',type:'tapo',path:'/stream2',port:554,snap:'http://[IP]/cgi-bin/snapshot.cgi',
   guide:'<b>1.</b> Open <b>Tapo app</b> → tap camera → ⚙️ → <b>Advanced Settings</b><br><b>2.</b> Tap <b>Camera Account</b> → create username & password<br><b>3.</b> Stream: <code>rtsp://user:pass@IP:554/stream2</code><br><b>4.</b> Snapshot: <code>http://IP/cgi-bin/snapshot.cgi</code><br>💡 Stream1=HD, Stream2=SD. Use stream2 for BirdNET.'},
  {id:'tapo-c210',name:'Tapo C210',icon:'📷',sub:'Pan/Tilt • 3MP',type:'tapo',path:'/stream2',port:554,snap:'http://[IP]/cgi-bin/snapshot.cgi',
   guide:'<b>1.</b> <b>Tapo app</b> → camera settings → <b>Advanced</b> → <b>Camera Account</b><br><b>2.</b> Set username & password<br><b>3.</b> Same RTSP path as C230: <code>rtsp://user:pass@IP:554/stream2</code><br>💡 Works with any Tapo that supports Camera Account feature.'},
  {id:'tapo-c110',name:'Tapo C110',icon:'📹',sub:'Indoor • 2K',type:'tapo',path:'/stream2',port:554,snap:'http://[IP]/cgi-bin/snapshot.cgi',
   guide:'<b>1.</b> <b>Tapo app</b> → ⚙️ → <b>Advanced</b> → <b>Camera Account</b><br><b>2.</b> Create account credentials<br><b>3.</b> RTSP: <code>rtsp://user:pass@IP:554/stream2</code><br>💡 Indoor cam — great for laundry/garage audio monitoring.'},
  {id:'tapo-c246',name:'Tapo C246D',icon:'🎥',sub:'Dual Lens 4MP',type:'tapo',path:'/stream2',port:554,snap:'http://[IP]/cgi-bin/snapshot.cgi',
   guide:'<b>1.</b> <b>Tapo app</b> → camera → ⚙️ → <b>Advanced</b> → <b>Camera Account</b><br><b>2.</b> Create separate account (not Tapo login)<br><b>3.</b> Each lens may have its own stream — try stream1/stream2<br><b>4.</b> RTSP: <code>rtsp://user:pass@IP:554/stream2</code><br>💡 4MP dual lens — use sub stream for BirdNET audio.'},
  {id:'reolink-rlc',name:'Reolink RLC',icon:'🔴',sub:'RLC Series',type:'reolink',path:'/h264Preview_01_main',port:554,snap:'http://[IP]/cgi-bin/api.cgi?cmd=Snap',
   guide:'<b>1.</b> RTSP is <b>enabled by default</b> on most Reolink cameras<br><b>2.</b> Main stream: <code>rtsp://admin:pass@IP:554/h264Preview_01_main</code><br><b>3.</b> Sub stream: <code>rtsp://admin:pass@IP:554/h264Preview_01_sub</code><br><b>4.</b> Find IP in Reolink desktop client or router DHCP<br>💡 Use sub stream for BirdNET — lower CPU load.'},
  {id:'reolink-duo',name:'Reolink Duo',icon:'🔴',sub:'Dual Lens',type:'reolink',path:'/h264Preview_01_main',port:554,snap:'http://[IP]/cgi-bin/api.cgi?cmd=Snap',
   guide:'<b>1.</b> Same as RLC — RTSP enabled by default<br><b>2.</b> Wide+tele lens each have separate channels<br><b>3.</b> Try: <code>rtsp://admin:pass@IP:554/h264Preview_01_main</code><br>💡 Duo 2 has two independent RTSP feeds — add both cameras.'},
  {id:'kogan',name:'Kogan IP Cam',icon:'📟',sub:'Various models',type:'kogan',path:'/11',port:554,snap:'http://[IP]/cgi-bin/snapshot.cgi',
   guide:'<b>1.</b> Kogan uses <b>XMEye / ICsee</b> app — not the Kogan app<br><b>2.</b> In XMEye: Camera Settings → <b>Network</b> → enable RTSP<br><b>3.</b> Default login: <code>admin</code> / no password or <code>admin</code><br><b>4.</b> RTSP path varies: try <code>/11</code>, <code>/12</code>, or <code>/cam/realmonitor</code><br><b>5.</b> Stream: <code>rtsp://admin@IP:554/11</code><br>💡 Kogan rebrands multiple manufacturers — test paths if /11 does not work.'},
  {id:'hikvision-ds2',name:'Hikvision DS-2',icon:'🏢',sub:'DS-2CD Series',type:'hikvision',path:'/Streaming/Channels/101',port:554,snap:'http://[IP]/ISAPI/Streaming/channels/101/picture',
   guide:'<b>1.</b> Web UI at <code>http://IP</code> — default: <code>admin</code>/password printed on camera<br><b>2.</b> Config → Network → Advanced → <b>Integration Protocol</b> → enable RTSP<br><b>3.</b> Main: <code>rtsp://admin:pass@IP:554/Streaming/Channels/101</code><br><b>4.</b> Sub stream: Ch <b>102</b> for lower resolution<br>💡 Use Channel 102 (sub) for BirdNET audio analysis.'},
  {id:'hikvision-ds3',name:'Hikvision DS-3',icon:'🏢',sub:'Value Series',type:'hikvision',path:'/Streaming/Channels/101',port:554,snap:'http://[IP]/ISAPI/Streaming/channels/101/picture',
   guide:'<b>1.</b> Same as DS-2 — web UI at <code>http://IP</code><br><b>2.</b> Enable RTSP in Network settings<br><b>3.</b> Default: <code>admin/admin</code> or <code>admin/12345</code><br><b>4.</b> RTSP: <code>rtsp://admin:pass@IP:554/Streaming/Channels/101</code><br>💡 DS-3 is the budget Hikvision line — RTSP is often disabled by default.'},
  {id:'dahua-ipc',name:'Dahua IPC',icon:'🏛️',sub:'IPC-HDW Series',type:'dahua',path:'/cam/realmonitor?channel=1&subtype=0',port:554,snap:'http://[IP]/cgi-bin/snapshot.cgi',
   guide:'<b>1.</b> Web UI: <code>http://IP</code> (default: <code>admin/admin</code>)<br><b>2.</b> Settings → Network → <b>RTSP</b> → enable<br><b>3.</b> Main: <code>rtsp://admin:pass@IP:554/cam/realmonitor?channel=1&subtype=0</code><br><b>4.</b> Sub stream: <code>subtype=1</code><br>💡 Also works with Amcrest and many Dahua OEM cameras.'},
  {id:'amcrest',name:'Amcrest',icon:'📸',sub:'IP Series',type:'amcrest',path:'/cam/realmonitor?channel=1&subtype=0',port:554,snap:'http://[IP]/cgi-bin/snapshot.cgi',
   guide:'<b>1.</b> Web UI: <code>http://IP</code> (default: <code>admin/admin</code>)<br><b>2.</b> Setup → Network → <b>RTSP</b> → enable<br><b>3.</b> RTSP: <code>rtsp://admin:pass@IP:554/cam/realmonitor?channel=1&subtype=0</code><br><b>4.</b> ONVIF port: 80 (default) or 8999<br>💡 Amcrest = Dahua OEM — same RTSP path format.'},
  {id:'wyze-v3',name:'Wyze Cam v3',icon:'🔲',sub:'RTSP FW RTSP required',type:'wyze',path:'/live',port:554,snap:'http://[IP]/cgi-bin/snapshot.cgi',
   guide:'<b>1.</b> ⚠️ <b>Requires RTSP firmware!</b> Download from <u>support.wyze.com</u><br><b>2.</b> Flash RTSP firmware via microSD card<br><b>3.</b> Wyze app → camera → ⚙️ → Advanced → <b>RTSP</b> → enable<br><b>4.</b> RTSP: <code>rtsp://user:pass@IP:554/live</code><br>⚠️ RTSP firmware disables cloud features — cannot revert.'},
  {id:'wyze-v4',name:'Wyze Cam v4',icon:'🔲',sub:'RTSP FW RTSP required',type:'wyze',path:'/live',port:554,snap:'http://[IP]/cgi-bin/snapshot.cgi',
   guide:'<b>1.</b> ⚠️ Same as v3 — requires RTSP firmware from Wyze site<br><b>2.</b> Flash via microSD, enable RTSP in app<br><b>3.</b> RTSP: <code>rtsp://user:pass@IP:554/live</code><br>💡 v4 has better low-light — good for night BirdNET audio.'},
  {id:'generic-rtsp',name:'Generic RTSP',icon:'🔌',sub:'ONVIF / RTSP',type:'rtsp',path:'/stream',port:554,snap:'',
   guide:'<b>1.</b> Search <code>[camera model] rtsp url</code> for your model<br><b>2.</b> Use <b>ONVIF Device Manager</b> to discover RTSP URLs<br><b>3.</b> Test in VLC: Media → Open Network Stream → paste URL<br><b>4.</b> Common paths: <code>/stream</code>, <code>/11</code>, <code>/live</code>, <code>/h264</code><br>💡 Most ONVIF cameras work with port 554 and a username/password.'},
  {id:'http-mjpeg',name:'HTTP/MJPEG',icon:'🌐',sub:'Webcam / IP Cam',type:'http',path:'/video.cgi',port:80,snap:'',
   guide:'<b>1.</b> For USB webcams: use <code>/dev/video0</code> with ffmpeg<br><b>2.</b> For IP cams with MJPEG: <code>http://IP:port/video.cgi</code><br><b>3.</b> Test in browser first — paste URL to verify stream<br><b>4.</b> ⚠️ No audio over MJPEG — BirdNET needs RTSP for audio<br>💡 Use RTSP instead for BirdNET — MJPEG is video-only.'},
];

let wizStep=0,wizBrand=null;

function openWizard(){
  wizStep=0;wizBrand=null;window._connTested=false;window._lastTestedId=null;
  document.getElementById('cam-modal').classList.remove('hidden');
  // Build brand grid
  const g=document.getElementById('brand-grid');
  g.innerHTML=BRANDS.map(b=>`<div class="brand-card" onclick="pickBrand('${b.id}')" data-id="${b.id}">
    <div class="brand-icon">${b.icon}</div><div class="brand-name">${b.name}</div>
    <div class="brand-sub">${b.sub}</div></div>`).join('');
  // Reset form
  document.getElementById('wiz-name').value='';
  document.getElementById('wiz-ip').value='';
  document.getElementById('wiz-port').value='554';
  document.getElementById('wiz-user').value='admin';
  document.getElementById('wiz-pass').value='';
  document.getElementById('wiz-path').value='/stream2';
  document.getElementById('wiz-snap').value='';
  document.getElementById('wiz-audio').checked=true;
  document.getElementById('wiz-enabled').checked=true;
  updateStep();
}

function closeWizard(){document.getElementById('cam-modal').classList.add('hidden');}

function pickBrand(id){
  wizBrand=BRANDS.find(b=>b.id===id);
  document.querySelectorAll('.brand-card').forEach(c=>c.classList.remove('selected'));
  document.querySelector(`.brand-card[data-id="${id}"]`)?.classList.add('selected');
  // Autofill
  if(wizBrand){
    document.getElementById('wiz-name').value=wizBrand.name;
    document.getElementById('wiz-port').value=wizBrand.port;
    document.getElementById('wiz-path').value=wizBrand.path;
    if(wizBrand.id.startsWith('http'))document.getElementById('wiz-audio').checked=false;
    // Show guide
    document.getElementById('wiz-guide').innerHTML=wizBrand.guide||'No specific guide — configure RTSP as per manufacturer instructions.';
  }
  wizNext(); // go to step 1 (guide)
}

function updateStep(){
  document.querySelectorAll('.step-content').forEach(s=>s.classList.remove('active'));
  document.getElementById('step-'+wizStep)?.classList.add('active');
  document.querySelectorAll('.modal-step-dot').forEach((d,i)=>{
    d.classList.remove('active','done');
    if(i<wizStep)d.classList.add('done');
    if(i===wizStep)d.classList.add('active');
  });
  // Nav buttons
  const prev=document.getElementById('wiz-prev'),next=document.getElementById('wiz-next'),done=document.getElementById('wiz-done');
  prev.style.visibility=wizStep===0?'hidden':'';
  if(wizStep>=4){next.classList.add('hidden');done.classList.remove('hidden');
    // Disable save until connection tested
    if(!window._connTested){done.style.opacity='0.5';done.style.pointerEvents='none';done.title='Test connection first';
    }else{done.style.opacity='';done.style.pointerEvents='';done.title='';}
    // Reset test state on re-entry
    if(!window._lastTestedId){document.getElementById('wiz-test-result').textContent='';window._connTested=false;}
    // Build summary
    const u=document.getElementById('wiz-user').value||'admin',pw=document.getElementById('wiz-pass').value||'password',
      ip=document.getElementById('wiz-ip').value||'192.168.1.x',p=document.getElementById('wiz-port').value||'554',
      path=document.getElementById('wiz-path').value||'/stream';
    const url=`rtsp://${u}:${pw}@${ip}:${p}${path}`;
    document.getElementById('wiz-summary').innerHTML=`<b>Name:</b> ${document.getElementById('wiz-name').value||'Camera'}<br>
      <b>Brand:</b> ${wizBrand?.name||'Custom'}<br>
      <b>Stream URL:</b> <code style="color:#8ab4f8;word-break:break-all">${url}</code><br>
      <b>Snapshot:</b> ${document.getElementById('wiz-snap').value||'None'}<br>
      <b>Audio:</b> ${document.getElementById('wiz-audio').checked?'Yes':'No'} &bull; <b>Enabled:</b> ${document.getElementById('wiz-enabled').checked?'Yes':'No'}`;
  }else{next.classList.remove('hidden');done.classList.add('hidden');}
  // Live preview on step 2
  if(wizStep===2){
    const u=document.getElementById('wiz-user').value||'admin',pw=document.getElementById('wiz-pass').value||'password',
      ip=document.getElementById('wiz-ip').value||'192.168.1.x',p=document.getElementById('wiz-port').value||'554',
      path=document.getElementById('wiz-path').value||'/stream';
    document.getElementById('wiz-preview').textContent=`rtsp://${u}:${pw}@${ip}:${p}${path}`;
  }
}

function wizNext(){if(wizStep<4){wizStep++;updateStep();}}
function wizPrev(){if(wizStep>0){wizStep--;updateStep();}}

async function testConnection(){
  const result=document.getElementById('wiz-test-result');
  const btn=document.getElementById('wiz-test-btn');
  btn.disabled=true;btn.textContent='⏳ Testing...';
  result.innerHTML='<span style="color:#9aa0a6">Testing...</span>';
  try{
    const resp=await fetch('/api/test-connection',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ip:document.getElementById('wiz-ip').value,
        port:document.getElementById('wiz-port').value||'554',
        path:document.getElementById('wiz-path').value||'/stream2',
        user:document.getElementById('wiz-user').value||'admin',
        pass:document.getElementById('wiz-pass').value||''})});
    const d=await resp.json();
    if(d.ok){
      window._connTested=true;window._lastTestedId=Date.now();
      result.innerHTML='<span style="color:#81c995">✓ Connected'+ (d.warnings?.length?' (with warnings)':'') +'</span>';
      const done=document.getElementById('wiz-done');
      done.style.opacity='';done.style.pointerEvents='';done.title='';
    }else{
      window._connTested=false;
      const es=(d.errors||[]).map(e=>'<br>· '+e).join('');
      result.innerHTML='<span style="color:#f28b82">✗ '+es+'</span>';
    }
  }catch(e){
    result.innerHTML='<span style="color:#f28b82">✗ Test failed: '+e.message+'</span>';
  }
  btn.disabled=false;btn.textContent='🔌 Test Connection';
}

async function wizSave(){
  if(!window._connTested){alert('Please test the connection first before adding the camera.');return;}
  const name=document.getElementById('wiz-name').value||'Camera';
  const u=document.getElementById('wiz-user').value||'admin',pw=document.getElementById('wiz-pass').value||'',
    ip=document.getElementById('wiz-ip').value||'',p=document.getElementById('wiz-port').value||'554',
    path=document.getElementById('wiz-path').value||'/stream';
  const stream=`rtsp://${u}:${pw}@${ip}:${p}${path}`.replace(/:[ ]+@/,'@');
  const snap=document.getElementById('wiz-snap').value.replace('[IP]',ip);
  const cam={
    id:'cam_'+Date.now(),
    name:name,
    type:wizBrand?.type||'rtsp',
    stream:stream,
    snapshot:snap,
    audio:document.getElementById('wiz-audio').checked,
    enabled:document.getElementById('wiz-enabled').checked,
    detection_source:document.getElementById('wiz-audio').checked
  };
  const s=await api('/api/settings');
  s.cameras.push(cam);
  await fetch('/api/settings/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(s)});
  closeWizard();
  renderCameraList(s.cameras);
}

async function editCamera(id){
  const s=await api('/api/settings');
  const c=s.cameras.find(x=>x.id===id);if(!c)return;
  // Open wizard pre-filled
  openWizard();
  wizStep=1;
  document.getElementById('wiz-name').value=c.name||'';
  document.getElementById('wiz-port').value='554';
  document.getElementById('wiz-user').value='admin';
  document.getElementById('wiz-path').value='/stream2';
  document.getElementById('wiz-audio').checked=c.audio!==false;
  document.getElementById('wiz-enabled').checked=c.enabled!==false;
  // Store edit ID for save
  document.getElementById('cam-modal').dataset.editId=id;
  s.cameras=s.cameras.filter(x=>x.id!==id);
  await fetch('/api/settings/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(s)});
  renderCameraList(s.cameras);
  updateStep();
}

async function deleteCamera(id){
  if(!confirm('Remove this camera?'))return;
  const s=await api('/api/settings');
  s.cameras=s.cameras.filter(x=>x.id!==id);
  await fetch('/api/settings/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(s)});
  renderCameraList(s.cameras);
}

async function testCamera(id){
  const btn=event.target;
  btn.textContent='...';btn.disabled=true;
  const res=await api('/api/settings/test-camera?id='+encodeURIComponent(id));
  btn.textContent='🔍 Test';btn.disabled=false;
  if(!res)return;
  const ok=res.ok?'✅':'❌';
  let msg=ok+' '+res.name+'\n';
  for(const[k,v]of Object.entries(res.checks||{})){
    msg+='  '+(v.ok?'✅':'❌')+' '+k+(v.error?' — '+v.error:'')+'\n';
  }
  alert(msg);
}

async function saveBirdnetSettings(){
  const s=await api('/api/settings');
  s.birdnet=s.birdnet||{};s.display=s.display||{};
  s.birdnet.min_confidence=parseFloat(document.getElementById('bn-conf').value)||0.6;
  s.birdnet.lat=parseFloat(document.getElementById('bn-lat').value)||-33.5;
  s.birdnet.lon=parseFloat(document.getElementById('bn-lon').value)||150.7;
  s.display.auto_refresh=parseInt(document.getElementById('bn-refresh').value)||30;
  await fetch('/api/settings/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(s)});
  alert('✅ Settings saved');
}

let currentPeriod='hour';
let aggregateData=null;

async function switchPeriod(p){
  currentPeriod=p;
  document.querySelectorAll('.per-btn').forEach(b=>b.classList.toggle('active',b.dataset.p===p));
  load();
}

async function load(){
  const periodLabels={hour:'Last 24h',day:'Last 30d',week:'Last 12w',month:'Last 12m'};
  const pld=periodLabels[currentPeriod]||'Period';
  const[a,rc,ca]=await Promise.all([
    api('/api/aggregate?period='+currentPeriod),
    api('/api/recent?limit=60'),api('/api/cameras')
  ]);
  aggregateData=a;
  const sp=a.top_species||[];
  const tl=a.timeline||[];
  const total=a.total||0;
  const unique=a.unique||0;
  const prev=a.prev_total||0;
  const delta=prev?((total-prev)/prev*100).toFixed(1):null;

  ['sk-total','sk-species','sk-today','sk-cams','sk-timeline','sk-pie'].forEach(id=>{const e=document.getElementById(id);if(e)e.remove()});
  ['st-total','st-species','st-today','st-cams'].forEach(id=>{const e=document.getElementById(id);if(e){e.style.display='';e.classList.add('fade-in')}});
  const deltaHTML=delta!==null?`<span style="font-size:14px;color:${delta>=0?'#81c995':'#f28b82'}"> ${delta>=0?'\u25B2':'\u25BC'}${Math.abs(delta)}%</span>`:'';
  document.getElementById('st-total').innerHTML=total.toLocaleString()+deltaHTML;
  document.getElementById('st-species').textContent=unique;
  document.getElementById('st-today').textContent=pld;
  document.getElementById('st-today-sp').innerHTML=currentPeriod.charAt(0).toUpperCase()+currentPeriod.slice(1)+' stats<br><span style="font-size:11px;color:#80868b">'+unique+' species \u00B7 '+total.toLocaleString()+' detections</span>';
  document.getElementById('st-cams').textContent=Object.keys(ca).filter(k=>k!=='unknown').length||1;

  // Timeline
  const lbs=tl.map(d=>d.label||'');
  if(chartTL)chartTL.destroy();
  chartTL=new Chart(document.getElementById('chart-timeline'),{type:'bar',
    data:{labels:lbs,datasets:[{data:tl.map(d=>d.count),backgroundColor:'#8ab4f8',
      borderRadius:4,borderSkipped:false}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false}},
      scales:{x:{grid:{color:'#3c4043'},ticks:{maxTicksLimit:12,font:{size:10},color:'#9aa0a6'}},
        y:{grid:{color:'#3c4043'},ticks:{color:'#9aa0a6'},beginAtZero:true}}}});

    // Google-style doughnut
  const top=sp.slice(0,8),other=sp.slice(8).reduce((a,b)=>a+b.count,0);
  const pl=top.map(d=>d.name);if(other)pl.push('Other');
  const pv=top.map(d=>d.count);if(other)pv.push(other);
  const chartTotal=pv.reduce((a,b)=>a+b,0);
  if(chartPie)chartPie.destroy();
  chartPie=new Chart(document.getElementById('chart-pie'),{type:'doughnut',
    data:{labels:pl,datasets:[{data:pv,backgroundColor:C,borderWidth:0,
      hoverBorderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'68%',
      animation:{duration:400},
      plugins:{legend:{position:'bottom',align:'center',
        labels:{padding:12,font:{size:10,family:'-apple-system,sans-serif'},color:'#e8eaed',
          usePointStyle:true,pointStyleWidth:8,boxWidth:8,
          generateLabels:function(chart){const d=chart.data;return d.labels.map((l,i)=>({
            text:l,fillStyle:d.datasets[0].backgroundColor[i],strokeStyle:'transparent',
            fontColor:'#e8eaed',color:'#e8eaed',pointStyle:'circle',index:i}))}}},
        tooltip:{backgroundColor:'#2d2d30',titleColor:'#e8eaed',bodyColor:'#9aa0a6',
          borderColor:'transparent',borderWidth:0,cornerRadius:6,padding:10,
          displayColors:false,callbacks:{label:ctx=>`${ctx.label}: ${ctx.raw.toLocaleString()} detections`}}}},
    plugins:[{id:'centerText',afterDraw(chart){const{ctx,chartArea:{top,bottom,left,right}}=chart;
      ctx.save();ctx.font='500 26px -apple-system,sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';
      ctx.fillStyle='#e8eaed';ctx.fillText(chartTotal.toLocaleString(),(left+right)/2,(top+bottom)/2-6);
      ctx.font='11px -apple-system,sans-serif';ctx.fillStyle='#bdc1c6';
      ctx.fillText('detections',(left+right)/2,(top+bottom)/2+16);ctx.restore()}}]});

  // Species grid
  const g=document.getElementById('species-grid');
  g.innerHTML=sp.slice(0,30).map((d,i)=>{
    const pct=sp.length?d.count/sp[0].count:0;const cached=window._imgCache?.[d.name];
    return`<div class="species-card fade-in" style="--i:${i}" onclick="detail('${d.name.replace(/'/g,"\\'")}')">
      <div class="img-wrap">
        <div class="spinner"></div>
        <div class="placeholder">🐦</div>
        <img src="${cached||''}" data-sp="${d.name.replace(/'/g,"\\'")}" loading="lazy" style="${cached?'display:block;opacity:1;transform:scale(1)':'display:none'}" onload="this.classList.add('loaded');this.style.display='block';this.parentElement.classList.add('loaded');this.previousElementSibling.style.display='none'" onerror="this.remove()">
      </div>
      <div class="info">
        <div class="name">${d.name}</div>
        <div class="row">
          <span class="count">${d.count}</span>
          <span class="perf">${((d.avg_confidence||0)*100).toFixed(0)}%</span>
          <span class="mini-bar"><span class="mini-fill" style="width:${(pct*100).toFixed(0)}%;background:${C[sp.indexOf(d)%10]}"></span></span>
        </div>
      </div>
    </div>`}).join('');

  // Recent table — compact & scrollable
  document.getElementById('tab-recent').innerHTML=rc.length?`<div style="max-height:300px;overflow-y:auto"><table><thead><tr><th></th><th>Time</th><th>Species</th><th>Conf</th><th>Camera</th></tr></thead><tbody>
    ${rc.map(d=>{const c=d.confidence;const cached=window._imgCache?.[d.species];return`<tr onclick="detail('${d.species.replace(/'/g,"\\'")}')" style="cursor:pointer">
      <td style="width:30px;padding:4px"><img src="${cached||''}" data-sp="${d.species.replace(/'/g,"\\'")}" style="width:24px;height:24px;border-radius:50%;object-fit:cover;background:#202124;opacity:0;transition:opacity .3s ease;${cached?'':'display:none'}" onload="this.style.opacity='1';this.style.display='block'" onerror="this.remove()"></td>
      <td style="font-size:11px;color:#9aa0a6;white-space:nowrap;padding:4px 6px">${(d.timestamp||'').slice(5,16).replace('T',' ')}</td>
      <td style="font-size:12px;padding:4px 6px"><strong>${d.species}</strong></td>
      <td style="padding:4px 6px"><span class="conf-pill ${cc(c)}">${(c*100).toFixed(0)}%</span></td>
      <td style="padding:4px 6px"><span class="badge ${d.source==='tapo_c230'?'badge-c230':d.source?.startsWith('tapo_c246')?'badge-c246':'badge-unknown'}">${d.source||'?'}</span></td>
    </tr>`}).join('')}</tbody></table></div>`:`<div class="empty-state"><div class="icon">🔇</div>No detections yet</div>`;


  // Camera chart
  const cn=Object.keys(ca).filter(k=>k!=='unknown'),cd=cn.map(n=>ca[n].detections),cs=cn.map(n=>ca[n].species_count);
  if(chartCam)chartCam.destroy();
  chartCam=new Chart(document.getElementById('chart-cam'),{type:'bar',
    data:{labels:cn,datasets:[
      {label:'Detections',data:cd,backgroundColor:'#8ab4f8',borderRadius:6},
      {label:'Species',data:cs,backgroundColor:'#c58af9',borderRadius:6}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{position:'bottom',labels:{padding:16,color:'#9aa0a6',usePointStyle:true}}},
      scales:{x:{grid:{color:'#3c4043'},ticks:{color:'#9aa0a6'}},
        y:{grid:{color:'#3c4043'},ticks:{color:'#9aa0a6'},beginAtZero:true}}}});
  document.getElementById('cam-legend').innerHTML=cn.map(n=>`<div style="margin-bottom:10px">
    <span class="badge ${n==='tapo_c230'?'badge-c230':'badge-c246'}">${n}</span>
    <span style="font-size:13px;color:#9aa0a6;margin-left:8px">${ca[n].detections} detections · ${ca[n].species_count} species · ${((ca[n].avg_confidence||0)*100).toFixed(0)}% avg</span>
  </div>`).join('');

  // Lazy-load any missing images after each refresh
  lazyImages();

  function lazyImages(){
    if(!window._imgCache)window._imgCache={};
    const imgs=[...document.querySelectorAll('#species-grid img[data-sp]'),...document.querySelectorAll('#tab-recent img[data-sp]')];
    const empty=imgs.filter(img=>!img.src||img.src===window.location.href);
    const needed=new Set(empty.map(img=>img.dataset.sp));
    needed.forEach(async sp=>{
      if(window._imgCache[sp]){
        document.querySelectorAll('img[data-sp="'+sp.replace(/"/g,'\\"')+'"]').forEach(img=>{img.src=window._imgCache[sp]});
      }else{
        try{
          const info=await api('/api/bird-image?species='+encodeURIComponent(sp));
          if(info&&info.image){
            window._imgCache[sp]=info.image;
            document.querySelectorAll('img[data-sp="'+sp.replace(/"/g,'\\"')+'"]').forEach(img=>{img.src=info.image});
          }
        }catch(e){}
      }
    });
  }
}

async function detail(species){
  const data=await api('/api/bird-detail?species='+encodeURIComponent(species));
  if(!data)return;
  document.getElementById('det-name').textContent=species;
  // Status badge
  const st=document.getElementById('det-status');
  st.style.display='inline-block';
  if(data.status==='pest'){st.textContent='⚠️ Declared Pest';st.style.background='rgba(242,139,130,.15)';st.style.color='#f28b82'}
  else if(data.status==='introduced'){st.textContent='🌍 Introduced Species';st.style.background='rgba(251,188,4,.15)';st.style.color='#fdd663'}
  else{st.textContent='🦘 Native';st.style.background='rgba(129,201,149,.15)';st.style.color='#81c995'}
  const ext=data.extract||'';
  document.getElementById('det-extract').innerHTML=ext?ext.slice(0,600)+(ext.length>600?'...':''):'<span style="color:#9aa0a6">No description available</span>';
  document.getElementById('det-img').src=data.image||'';
  document.getElementById('det-img').dataset.full=data.full||'';
  document.getElementById('det-wiki').href=data.url||'#';
  document.getElementById('det-count').textContent=data.detections;
  document.getElementById('det-conf').textContent=((data.avg_confidence||0)*100).toFixed(0)+'%';
  document.getElementById('det-last').textContent='...';
  document.getElementById('detail-overlay').classList.add('active');
  // Wikidata stats — prefer pre-rendered infographic
  const ws=data.wikistats||{};
  const hasStats=(ws.num||[]).length>0||(ws.cat||[]).length>0;
  const infographic=document.getElementById('det-infographic');
  const numBars=document.getElementById('det-num-bars');
  const catTags=document.getElementById('det-cat-tags');
  document.getElementById('det-stats').style.display=hasStats?'block':'none';
  if(data.stats_svg){
    // Use pre-rendered SVG infographic — instant, no rendering
    infographic.src=data.stats_svg;
    infographic.style.display='block';
    numBars.innerHTML='';
    catTags.innerHTML='';
  }else if(hasStats){
    // Fallback: client-side bars
    infographic.style.display='none';
    const maxVal=Math.max(...ws.num.map(d=>d.value),1);
    numBars.innerHTML=ws.num.map(d=>{
      const pct=Math.min((d.value/maxVal)*100,100);
      const hue=[210,150,30,0,280,120][ws.num.indexOf(d)%6];
      return`<div style="margin-bottom:8px">
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:2px">
          <span style="color:#9aa0a6">${d.name}</span>
          <span style="color:#e8eaed;font-weight:500">${d.value} ${d.unit}</span>
        </div>
        <div style="height:6px;background:#3c4043;border-radius:3px;overflow:hidden">
          <div style="height:100%;width:${pct}%;border-radius:3px;background:hsl(${hue},60%,55%)"></div>
        </div>
      </div>`}).join('');
    document.getElementById('det-cat-tags').innerHTML=ws.cat.map(d=>
      `<span style="padding:4px 10px;border-radius:12px;font-size:11px;background:rgba(197,138,249,.15);color:#c58af9">${d.name}: ${d.value}</span>`
    ).join('');
  }
  // Last seen
  setTimeout(async()=>{
    const sp=await api('/api/species');
    const s=sp.find(d=>d.name===species);
    if(s)document.getElementById('det-last').textContent=(s.last_seen||'').slice(0,16);
  },50);
}
function closeDetail(){document.getElementById('detail-overlay').classList.remove('active')}
function openFull(e){
  e.stopPropagation();
  const url=document.getElementById('det-img').dataset.full;
  if(url)window.open(url,'_blank');
}
switchPeriod('hour');setInterval(load,30000);
// Lightweight device GPS override for location tag
(function(){
  var tag=document.getElementById('location-tag');
  if(!navigator.geolocation)return;
  navigator.geolocation.getCurrentPosition(function(pos){
    var lat=pos.coords.latitude.toFixed(2),lng=pos.coords.longitude.toFixed(2);
    tag.textContent=lat+', '+lng;
    // Reverse geocode via lightweight Nominatim
    var x=new XMLHttpRequest();
    x.open('GET','https://nominatim.openstreetmap.org/reverse?format=json&lat='+lat+'&lon='+lng+'&zoom=10');
    x.timeout=5000;
    x.onload=function(){try{var d=JSON.parse(x.responseText);tag.textContent=d.address.city||d.address.town||d.address.village||d.address.suburb||tag.textContent}catch(e){}}
    x.onerror=function(){}
    x.send();
  },function(){},{timeout:5000,maximumAge:3600000});
})();
</script>
</body>
</html>"""

if __name__ == "__main__":
    import threading
    # Pre-warm images in background
    threading.Thread(target=prewarm_images, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"BirdNET Dashboard → http://localhost:{PORT} (also Tailscale)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
