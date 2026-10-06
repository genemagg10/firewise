#!/usr/bin/env python3
"""Geocode data/addresses.csv -> data/geocoded.csv  (and data/county_reconciliation.json)

Source order for each address:
  1. US Census batch geocoder (geocoding.geo.census.gov)   - tried first; skipped if unreachable/rejected
  2. Contra Costa County Assessor parcel layer (situs address -> parcel centroid), public ArcGIS REST:
     https://gis.cccounty.us/arcgis/rest/services/CCMAP/Assessment_Parcels_ArcPro/MapServer/0
     Only situs address fields + parcel geometry are requested (no owner fields).
  3. Nominatim / OpenStreetMap (1 request/second, identifying User-Agent, cached in work/)
  4. Street centroid (flagged UNMATCHED) if nothing matches the house number.
"""
import csv, io, json, math, os, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
UA = "LasTrampasFirewiseMap/1.0 (private neighborhood firewise map, Lafayette CA)"
COUNTY_URL = "https://gis.cccounty.us/arcgis/rest/services/CCMAP/Assessment_Parcels_ArcPro/MapServer/0/query"
CACHE = "work/nominatim_cache.json"
os.makedirs("work", exist_ok=True)
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}

# sheet/normalized street -> (official street name per County Assessor, county S_STR_NM, S_STR_SUF, OSM name variants)
STREETS = {
 "Arroyo Court":        ("Arroyo Court", "ARROYO", "CT", ["Arroyo Court"]),
 "Diablo Oaks Way":     ("Diablo Oaks Way", "DIABLO OAKS", "WAY", ["Diablo Oaks Way"]),
 "Dianne Court":        ("Dianne Court", "DIANNE", "CT", ["Dianne Court", "Diane Court"]),
 "Glenside Circle":     ("Glenside Circle", "GLENSIDE", "CIR", ["Glenside Circle"]),
 "Glenside Drive":      ("Glenside Drive", "GLENSIDE", "DR", ["Glenside Drive"]),
 "Los Palos Circle":    ("Los Palos Circle", "LOS PALOS", "CIR", ["Los Palos Circle"]),
 "Los Palos Drive":     ("Los Palos Drive", "LOS PALOS", "DR", ["Los Palos Drive"]),
 "Los Palos Manor":     ("Los Palos Manor", "LOS PALOS", "MNR", ["Los Palos Manor"]),
 "Las Trampas Road":    ("Las Trampas Road", "LAS TRAMPAS", "RD", ["Las Trampas Road"]),
 "Olivera Lane":        ("Oliveira Lane", "OLIVEIRA", "LN", ["Olivera Lane", "Oliveira Lane"]),
 "Phillips Road":       ("Phillips Road", "PHILLIPS", "RD", ["Phillips Road"]),
 "Richelle Court":      ("Richelle Court", "RICHELLE", "CT", ["Richelle Court"]),
 "Roxanne Lane":        ("Roxanne Lane", "ROXANNE", "LN", ["Roxanne Lane"]),
 "Reliez Station Road": ("Reliez Station Road", "RELIEZ STATION", "RD", ["Reliez Station Road"]),
 "Via Los Colrados":    ("Via Los Colorados", "VIA LOS COLORADOS", "", ["Via Los Colorados"]),
}

def get_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

# ---------- 1. Census ----------
def census_batch(rows):
    buf = io.StringIO(); w = csv.writer(buf)
    for i, r in enumerate(rows): w.writerow([i, f"{r['number']} {STREETS[r['street']][0]}", "Lafayette", "CA", "94549"])
    b = "----fw%d" % time.time()
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"benchmark\"\r\n\r\nPublic_AR_Current\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"addressFile\"; filename=\"a.csv\"\r\nContent-Type: text/csv\r\n\r\n"
            f"{buf.getvalue()}\r\n--{b}--\r\n").encode()
    req = urllib.request.Request("https://geocoding.geo.census.gov/geocoder/locations/addressbatch", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}", "User-Agent": UA})
    try:
        txt = urllib.request.urlopen(req, timeout=180).read().decode()
    except Exception as e:
        print("Census geocoder unreachable:", e); return {}, f"unreachable ({e})"
    if "Request Rejected" in txt or txt.lstrip().lower().startswith("<html"):
        print("Census geocoder rejected requests from this network (F5 'Request Rejected' page)."); return {}, "rejected by Census WAF from this network"
    out = {}
    for rec in csv.reader(io.StringIO(txt)):
        if len(rec) >= 6 and rec[2] == "Match":
            lng, lat = map(float, rec[5].split(","))
            out[int(rec[0])] = (lat, lng, rec[3], rec[4])
    return out, "ok"

# ---------- 2. County parcels ----------
def ring_centroid(ring):
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        f = x1 * y2 - x2 * y1; a += f; cx += (x1 + x2) * f; cy += (y1 + y2) * f
    if abs(a) < 1e-15:
        xs, ys = zip(*ring); return sum(xs) / len(xs), sum(ys) / len(ys)
    return cx / (3 * a), cy / (3 * a)

def county_parcels():
    names = sorted({v[1] for v in STREETS.values()})
    where = "S_CTY_ABBR='LAF' AND (" + " OR ".join(f"S_STR_NM='{n}'" for n in names) + ")"
    feats, off = [], 0
    while True:
        q = urllib.parse.urlencode(dict(where=where, outFields="APN,S_STR_NM,S_STR_SUF,S_STR_NBR,S_ZIP,USE_CODE",
                                        returnGeometry="true", outSR=4326, f="json", resultOffset=off, resultRecordCount=1000))
        d = get_json(COUNTY_URL + "?" + q)
        if "error" in d: raise RuntimeError(d["error"])
        feats += d["features"]
        if not d.get("exceededTransferLimit"): break
        off += 1000
    idx = {}
    for f in feats:
        a = f["attributes"]
        if not a.get("S_STR_NBR") or not f.get("geometry"): continue
        ring = max(f["geometry"]["rings"], key=len)
        lng, lat = ring_centroid(ring)
        key = (a["S_STR_NM"].strip(), (a["S_STR_SUF"] or "").strip(), a["S_STR_NBR"].strip())
        idx.setdefault(key, []).append(dict(lat=lat, lng=lng, apn=a["APN"], zip=a.get("S_ZIP"), use=a.get("USE_CODE")))
    return idx

# ---------- 3. Nominatim ----------
last = [0.0]
def nom(params):
    key = json.dumps(params, sort_keys=True)
    if key in cache: return cache[key]
    wait = 1.1 - (time.time() - last[0])
    if wait > 0: time.sleep(wait)
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        dict(params, format="jsonv2", addressdetails=1, limit=3, countrycodes="us"))
    data = []
    for _ in range(3):
        try: data = get_json(url, 30); break
        except Exception as e: print("  nominatim retry:", e, file=sys.stderr); time.sleep(5)
    last[0] = time.time(); cache[key] = data; json.dump(cache, open(CACHE, "w"))
    return data

def nom_house(num, variants):
    for s in variants:
        for params in ({"street": f"{num} {s}", "city": "Lafayette", "state": "CA"}, {"q": f"{num} {s}, Lafayette, CA"}):
            for d in nom(params):
                a = d.get("address", {})
                nums = [x.strip() for x in a.get("house_number", "").replace(",", ";").split(";")]
                if num in nums and a.get("road", "").lower() in [v.lower() for v in variants] and \
                   a.get("town", a.get("city", "")) == "Lafayette":
                    return d
    return None

def nom_street(variants):
    for s in variants:
        for d in nom({"street": s, "city": "Lafayette", "state": "CA"}):
            if d.get("address", {}).get("road", "").lower() in [v.lower() for v in variants]:
                return d
    return None

def dist_m(a, b, c, d):
    return math.hypot((a - c) * 111320, (b - d) * 111320 * math.cos(math.radians(a)))

def main():
    rows = list(csv.DictReader(open("data/addresses.csv")))
    census, census_status = census_batch(rows)
    parcels = county_parcels()
    print(f"county parcels indexed: {sum(len(v) for v in parcels.values())}")
    out, street_pts = [], {}
    for i, r in enumerate(rows):
        official, cnm, csuf, variants = STREETS[r["street"]]
        num = r["number"]
        rec = dict(r, official_street=official, official_address=f"{num} {official}, Lafayette, CA 94549",
                   lat="", lng="", match_quality="", geocode_source="", county_apn="", nominatim_check_m="", geocode_flag="")
        c = parcels.get((cnm, csuf, num))
        nh = None
        if i in census:
            lat, lng, q, m = census[i]
            rec.update(lat=f"{lat:.6f}", lng=f"{lng:.6f}", match_quality=f"house (Census {q})", geocode_source="US Census")
        elif c:
            p = c[0]
            rec.update(lat=f"{p['lat']:.6f}", lng=f"{p['lng']:.6f}", match_quality="house (parcel centroid)",
                       geocode_source="Contra Costa County Assessor parcels", county_apn=p["apn"])
            if len(c) > 1: rec["geocode_flag"] = f"county has {len(c)} parcels with this situs address; used first"
        else:
            nh = nom_house(num, variants)
            if nh:
                interp = nh.get("osm_type") == "way" and nh.get("category") == "place" and nh.get("type") == "house"
                rec.update(lat=f"{float(nh['lat']):.6f}", lng=f"{float(nh['lon']):.6f}",
                           match_quality=("interpolated (approximate - OSM address range)" if interp else "house (OSM address point)"),
                           geocode_source="Nominatim/OpenStreetMap",
                           geocode_flag="NOT FOUND in County Assessor situs addresses; " +
                                        ("position interpolated along the street by OSM, not a confirmed house" if interp else "OSM has an address point") +
                                        " - verify number")
            else:
                if official not in street_pts:
                    pts = [p for (n, s, _), ps in parcels.items() if n == cnm and s == csuf for p in ps]
                    if pts:
                        street_pts[official] = (sum(p["lat"] for p in pts) / len(pts), sum(p["lng"] for p in pts) / len(pts), "County parcels on street (mean)")
                    else:
                        ns = nom_street(variants)
                        street_pts[official] = (float(ns["lat"]), float(ns["lon"]), "Nominatim street") if ns else None
                sp = street_pts[official]
                if sp:
                    rec.update(lat=f"{sp[0]:.6f}", lng=f"{sp[1]:.6f}", match_quality="street (approximate - street centroid)",
                               geocode_source=sp[2], geocode_flag="UNMATCHED: house number not found in County parcels or OSM; placed at street centroid")
                else:
                    rec.update(match_quality="none", geocode_flag="UNMATCHED: street not found")
        # cross-check county point against OSM (cache only - no extra requests unless already fetched)
        if rec["geocode_source"].startswith("Contra Costa"):
            for s in variants:
                k = json.dumps({"city": "Lafayette", "state": "CA", "street": f"{num} {s}"}, sort_keys=True)
                for d in cache.get(k, []):
                    if d.get("address", {}).get("house_number") == num:
                        rec["nominatim_check_m"] = str(round(dist_m(float(rec["lat"]), float(rec["lng"]), float(d["lat"]), float(d["lon"])))); break
                if rec["nominatim_check_m"]: break
        out.append(rec)
        print(f"{i:3d} {num:>5} {official:<20} {rec['match_quality']}", flush=True)
    with open("data/geocoded.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    # reconciliation helper: county situs numbers on each street that are NOT on the sheet
    recon = {}
    for sheet_street, (official, cnm, csuf, _) in STREETS.items():
        county_nums = sorted({n for (a, b, n) in parcels if a == cnm and b == csuf}, key=lambda x: int(x) if x.isdigit() else 0)
        sheet_nums = [r["number"] for r in rows if r["street"] == sheet_street]
        recon[official] = {"sheet": sheet_nums, "county_situs": county_nums,
                           "on_sheet_not_in_county": [n for n in sheet_nums if n not in county_nums],
                           "in_county_not_on_sheet": [n for n in county_nums if n not in sheet_nums]}
    json.dump({"census_status": census_status, "streets": recon}, open("data/county_reconciliation.json", "w"), indent=1)
    print("census:", census_status)

if __name__ == "__main__":
    main()
