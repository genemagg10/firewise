#!/usr/bin/env python3
"""Las Trampas Firewise - data builder.

  FIREWISE_PASSWORD='...' python3 tools/build_data.py
                                       # residents.csv + events.csv -> residents.json (PLAINTEXT, git-ignored),
                                       # residents.enc.json (encrypted), events.json, public-data.js
  python3 tools/build_data.py --no-encrypt   # plaintext residents.json only (local tooling; site won't update)
  python3 tools/build_data.py --seed   # (re)create residents.csv rows from geocoded.csv, KEEPING any names,
                                       # emails, status etc. already typed into residents.csv, then build.
  python3 tools/build_data.py --merge-owners data/link_owner_names.csv
                                       # fill BLANK owner_or_resident_names from a public-record owner file
                                       # (matched by APN, then by address). Never overwrites names already there.

residents.csv is the file you edit. Multi-value cells (names, emails, events_attended) are separated by ';'.
signed_up must be yes / no / unknown (blank = unknown).  last_contact: YYYY-MM-DD.
"""
import csv, json, os, sys, datetime, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, "data", *p)

RES_FIELDS = ["address", "number", "street", "apn", "lat", "lng", "geocode_quality", "owner_or_resident_names",
              "source_of_name", "emails", "phone", "signed_up", "events_attended", "last_contact", "notes", "flags"]
EVENT_FIELDS = ["id", "title", "date", "time", "location", "description", "status", "link"]
PERSON_FIELDS = ["owner_or_resident_names", "source_of_name", "emails", "phone", "signed_up",
                 "events_attended", "last_contact", "notes"]

def read_csv(path):
    if not os.path.exists(path): return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f)]

def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def split_multi(v):
    return [x.strip() for x in re.split(r"[;\n]", v or "") if x.strip()]

def seed():
    geo = read_csv(D("geocoded.csv"))
    existing = {r["address"]: r for r in read_csv(D("residents.csv"))}
    rows = []
    for g in geo:
        street = g.get("official_street") or g["street"]
        addr = f'{g["number"]} {street}'
        flags = "; ".join(x for x in [g.get("flags", ""), g.get("geocode_flag", "")] if x)
        r = {"address": addr, "number": g["number"], "street": street, "apn": g.get("county_apn", ""), "lat": g["lat"], "lng": g["lng"],
             "geocode_quality": g["match_quality"], "flags": flags, "signed_up": "unknown"}
        old = existing.pop(addr, None)
        if old:
            for k in PERSON_FIELDS:
                if old.get(k): r[k] = old[k]
            if old.get("lat") and old.get("geocode_quality", "").startswith("manual"):  # keep hand-fixed pins
                r.update(lat=old["lat"], lng=old["lng"], geocode_quality=old["geocode_quality"])
        rows.append(r)
    for addr, old in existing.items():  # rows Gene added by hand that aren't on the sheet: keep them
        rows.append(old)
    write_csv(D("residents.csv"), rows, RES_FIELDS)
    print(f"seeded data/residents.csv with {len(rows)} rows")

def norm_addr(a):
    a = (a or "").lower().split(",")[0]
    for k, v in {" court": " ct", " drive": " dr", " circle": " cir", " road": " rd", " lane": " ln", " way": " way", " manor": " mnr"}.items():
        a = a.replace(k, v)
    return " ".join(a.split())

def merge_owners(path):
    src = read_csv(path)
    rows = read_csv(D("residents.csv"))
    by_apn, by_addr = {}, {}
    for o in src:
        if not o.get("owner_names"): continue
        for apn in re.split(r"[;,]", o.get("apn", "")):
            apn = apn.replace("-", "").strip()
            if apn: by_apn.setdefault(apn, o)
        by_addr.setdefault(norm_addr(o.get("full_address")), o)
    filled = 0
    for r in rows:
        if r.get("owner_or_resident_names"): continue          # never overwrite what Gene typed
        o = by_apn.get(r.get("apn", "").replace("-", "")) or by_addr.get(norm_addr(r["address"]))
        if not o: continue
        r["owner_or_resident_names"] = "; ".join(x.strip() for x in o["owner_names"].split("|") if x.strip())
        r["source_of_name"] = (f"Public record owner ({o.get('source', '')}; as of {o.get('as_of_date', '')}; "
                               f"confidence {o.get('confidence', '')}) - owner, may not be the resident")
        filled += 1
    write_csv(D("residents.csv"), rows, RES_FIELDS)
    print(f"merged owner names into {filled} blank rows from {path}")

def build():
    res, problems = [], []
    for i, r in enumerate(read_csv(D("residents.csv")), start=2):
        su = (r.get("signed_up") or "unknown").lower()
        su = {"y": "yes", "true": "yes", "n": "no", "false": "no", "": "unknown"}.get(su, su)
        if su not in ("yes", "no", "unknown"):
            problems.append(f"row {i} ({r.get('address')}): signed_up '{r.get('signed_up')}' -> unknown"); su = "unknown"
        try:
            lat, lng = float(r["lat"]), float(r["lng"])
        except (ValueError, KeyError):
            lat = lng = None; problems.append(f"row {i} ({r.get('address')}): missing lat/lng (not shown on map)")
        lc = r.get("last_contact", "")
        if lc:
            try: datetime.date.fromisoformat(lc)
            except ValueError: problems.append(f"row {i} ({r.get('address')}): last_contact '{lc}' is not YYYY-MM-DD")
        res.append({
            "address": r.get("address", ""), "number": r.get("number", ""), "street": r.get("street", ""), "apn": r.get("apn", ""),
            "lat": lat, "lng": lng, "geocode_quality": r.get("geocode_quality", ""),
            "approximate": not (r.get("geocode_quality", "").startswith(("house", "manual"))),
            "owner_or_resident_names": split_multi(r.get("owner_or_resident_names")),
            "source_of_name": r.get("source_of_name", ""), "emails": split_multi(r.get("emails")),
            "phone": r.get("phone", ""), "signed_up": su, "events_attended": split_multi(r.get("events_attended")),
            "last_contact": lc, "notes": r.get("notes", ""), "flags": r.get("flags", ""),
        })
    events = [e for e in read_csv(D("events.csv")) if e.get("title")]
    meta = {"title": "Las Trampas Firewise Neighborhood", "area": "Evacuation Area 016, Lafayette, CA",
            "sheet_total": 198, "generated": datetime.datetime.now().isoformat(timespec="minutes")}
    json.dump(res, open(D("residents.json"), "w"), indent=1)          # PLAINTEXT - git-ignored, never published
    json.dump(events, open(D("events.json"), "w"), indent=1)
    if os.path.exists(D("site-data.js")): os.remove(D("site-data.js"))  # old plaintext bundle (pre-encryption)
    if "--no-encrypt" in sys.argv:
        print(f"built {len(res)} residents (plaintext only, NOT encrypted - site data not updated), {len(events)} events")
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from encrypt_data import encrypt_payload, decrypt_payload, get_password
        pw = get_password()
        env = encrypt_payload({"residents": res}, pw)
        assert decrypt_payload(env, pw)["residents"] == res            # round-trip self-check
        json.dump(env, open(D("residents.enc.json"), "w"))
        # public-data.js: public meta + events + the ENCRYPTED residents blob, so pages also work from file://
        with open(D("public-data.js"), "w") as f:
            f.write("/* GENERATED by tools/build_data.py - residents are encrypted (AES-256-GCM). Edit data/*.csv instead. */\n")
            f.write("window.FIREWISE_PUBLIC = " + json.dumps({"meta": meta, "events": events, "residents_enc": env}) + ";\n")
        print(f"built {len(res)} residents (encrypted -> data/residents.enc.json, data/public-data.js), {len(events)} events")
    for p in problems: print("  WARNING:", p)

if __name__ == "__main__":
    if "--seed" in sys.argv: seed()
    if "--merge-owners" in sys.argv: merge_owners(sys.argv[sys.argv.index("--merge-owners") + 1])
    build()
