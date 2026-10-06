#!/usr/bin/env python3
"""Las Trampas Firewise - data builder.

  FIREWISE_PASSWORD='...' python3 tools/build_data.py
                                       # residents.csv + events.csv -> residents.json (PLAINTEXT, git-ignored),
                                       # residents.enc.json (encrypted), events.json, public-data.js
  python3 tools/build_data.py --no-encrypt   # plaintext residents.json only (local tooling; site won't update)
  python3 tools/build_data.py --seed   # (re)create residents.csv rows from geocoded.csv, KEEPING any names,
                                       # emails, status etc. already typed into residents.csv, then build.
  python3 tools/build_data.py --merge-owners data/link_owner_names.csv --merge-flags data/link_address_flags.csv
                                       # fill BLANK names from a public-record owner file (matched by sheet address,
                                       # then APN; raw name kept in owner_of_record) and append address-check flags.
                                       # Never overwrites names already there. Safe to re-run.

residents.csv is the file you edit. Multi-value cells (names, emails, events_attended) are separated by ';'.
signed_up must be yes / no / unknown (blank = unknown).  last_contact: YYYY-MM-DD.
"""
import csv, json, os, sys, datetime, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, "data", *p)

RES_FIELDS = ["address", "number", "street", "apn", "lat", "lng", "geocode_quality", "owner_or_resident_names",
              "source_of_name", "owner_of_record", "owner_name_confidence", "owner_as_of_date", "owner_source",
              "emails", "phone", "signed_up", "events_attended", "last_contact", "notes", "flags"]
OWNER_LABEL = "Owner of record (county deed index), may not be the current resident"
EVENT_FIELDS = ["id", "title", "date", "time", "location", "description", "status", "link"]
PERSON_FIELDS = ["owner_or_resident_names", "source_of_name", "owner_of_record", "owner_name_confidence",
                 "owner_as_of_date", "owner_source", "emails", "phone", "signed_up", "events_attended", "last_contact", "notes"]

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

# ---------------- public-record owner merge ----------------
SUFFIX_ABBR = {"CT": "Court", "DR": "Drive", "CIR": "Circle", "RD": "Road", "LN": "Lane", "WAY": "Way", "MNR": "Manor",
               "MANOR": "Manor", "COURT": "Court", "DRIVE": "Drive", "CIRCLE": "Circle", "ROAD": "Road", "LANE": "Lane"}
STREET_ALIASES = {"los palo manor": "los palos manor", "via los colrados": "via los colorados", "olivera lane": "oliveira lane"}

def norm_street(label):
    w = label.replace(".", "").split()
    if w and w[-1].upper() in SUFFIX_ABBR: w[-1] = SUFFIX_ABBR[w[-1].upper()]
    st = " ".join(w).lower()
    return STREET_ALIASES.get(st, st)

def parse_input_address(label):
    """'Glenside Cir 74(?)' / 'Olivera Ln 1-4' / 'Via Los Colrados 3549/3550' -> (street_norm, [numbers])"""
    m = re.match(r"^(.*?)\s+([\d/\-\s]+)(\(\?\))?\s*$", label.strip())
    if not m: return None, []
    nums = []
    for tok in m.group(2).replace(" ", "").split("/"):
        if re.fullmatch(r"\d+-\d+", tok):
            lo, hi = map(int, tok.split("-")); nums += [str(n) for n in range(lo, hi + 1)] if hi - lo < 50 else [tok]
        elif tok: nums.append(tok)
    return norm_street(m.group(1)), nums

ENTITY_WORDS = {"TRUST", "TRUS", "FAMILY", "LIVING", "REVOCABLE", "REV", "REVOC", "LLC", "INC", "LP", "LTD", "ESTATE", "CORP",
                "CO", "PARTNERSHIP", "SEPARATE", "PROPERTY", "VIVOS", "SURVIVORS", "IRREVOCABLE"}
TRUST_ABBR = ("F/TR", "R/TR", "L/TR")
ENTITY_ABBR = {"F/TR": "Family Trust", "R/TR": "Revocable Trust", "L/TR": "Living Trust", "TR": "Trust", "REV": "Revocable",
               "REVOC": "Revocable", "TRUS": "Trust", "LLC": "LLC", "LP": "LP", "INC": "Inc.", "LTD": "Ltd."}
KEEP_UPPER = {"II", "III", "IV", "LLC", "LP"}
TRUSTEE = ("TRE", "TR", "TTEE", "TRS")

def tc(word):
    if word in KEEP_UPPER or re.fullmatch(r"\d+", word): return word
    if "&" in word and len(word) <= 5: return word                       # K&B
    def one(x):
        if not x: return x
        if x.startswith("MC") and len(x) > 2: return "Mc" + x[2:].capitalize()
        if x.startswith("O'") and len(x) > 2: return "O'" + x[2:].capitalize()
        return x.capitalize()
    return "-".join(one(p) for p in word.split("-"))

def entity_name(part):
    out = []
    for t in part.replace(" /", "/").split():
        out.append(ENTITY_ABBR.get(t) or ("&" if t == "&" else "and" if t == "AND" else tc(t)))
    return " ".join(out).replace("Trust Trust", "Trust")

def friendly_owner_name(raw):
    """'DOE JOHN A TRE; DOE JANE TRE; DOE FAMILY TRUST' -> 'John A & Jane Doe (trustees)'.
    Best effort: the deed index lists people as LAST FIRST MIDDLE (often with TRE = trustee); trusts and companies are
    kept as written in title case and only shown when no individual is listed. The raw text stays in owner_of_record."""
    parts = [p.strip().upper() for p in re.split(r"[;|]", raw or "") if p.strip()]
    parts = [p for p in parts if not (re.match(r"^(AON|APN)\b", p) or re.search(r"\d{3}-\d{3}-\d{3}", p))]  # parcel refs
    # surnames we can trust: first token of parts written LAST FIRST ... TRE, or of plain 2-4 word parts
    surnames = {p.split()[0] for p in parts if p.split()[-1] == "TRE"} | {p.split()[0] for p in parts if 2 <= len(p.split()) <= 4 and not set(p.split()) & (ENTITY_WORDS | set(TRUST_ABBR) | {"TR", "&", "AND"})}
    people, entities, natural = [], [], []
    after_dba = False
    for part in parts:
        w = part.split()
        dba = "DBA" in w; w = [t for t in w if t != "DBA"]
        if after_dba: entities.append(entity_name(" ".join(w))); after_dba = dba; continue
        after_dba = dba
        if set(w) & ENTITY_WORDS or set(w) & set(TRUST_ABBR) or (w[-1] == "TR" and ("&" in w or "AND" in w or len(w) <= 2)) \
           or (w[-1] == "TR" and len(w) >= 3 and w[0] not in surnames and w[-2] in surnames):   # '<FIRST> <MI> <SURNAME> TR' = trust name
            entities.append(entity_name(" ".join(w))); continue
        if "AND" in w or "&" in w or any("-ETC" in t for t in w):
            natural.append(" ".join("&" if t == "&" else "and" if t == "AND" else tc(t) for t in w)); continue
        trustee = False
        while w and w[-1] in TRUSTEE: trustee = True; w.pop()
        sfx = w.pop() if len(w) > 2 and w[-1] in ("JR", "SR", "II", "III", "IV") else ""
        if len(w) < 2: natural.append(" ".join(tc(t) for t in w)); continue
        n_last = 2 if len(w) >= 3 and w[1] in surnames and w[0] not in surnames else 1      # '<SURNAME1> <SURNAME2> <FIRST> <MI>' (two-part surname)
        if len(w) >= 3 and w[1] in surnames and w[0] in surnames and w[1] != w[0]: n_last = 2
        last = " ".join(tc(t) for t in w[:n_last]); first = " ".join(tc(t) for t in w[n_last:])
        sfx = (sfx if sfx in KEEP_UPPER else tc(sfx) + ".") if sfx else ""
        people.append((last, first, sfx, trustee))
    groups = {}
    for last, first, sfx, tr in people:
        g = groups.setdefault(last, {"firsts": [], "tr": False, "sfx": ""})
        if first not in g["firsts"]: g["firsts"].append(first)
        g["tr"] |= tr; g["sfx"] = g["sfx"] or sfx
    out = []
    for last, g in groups.items():
        name = " & ".join(g["firsts"]) + " " + last + (" " + g["sfx"] if g["sfx"] else "")
        if g["tr"]: name += " (trustees)" if len(g["firsts"]) > 1 else " (trustee)"
        out.append(name)
    if not out: out = natural or entities
    return "; ".join(dict.fromkeys(out))

def resident_key(street, number):
    return (norm_street(street), str(number).strip())

def merge_owners(path):
    src = read_csv(path)
    rows = read_csv(D("residents.csv"))
    idx = {resident_key(r["street"], r["number"]): r for r in rows}
    by_apn = {r.get("apn", "").replace("-", ""): r for r in rows if r.get("apn")}
    filled = matched = 0
    for o in src:
        st, nums = parse_input_address(o.get("input_address", ""))
        r = idx.get((st, nums[0])) if st and len(nums) == 1 else None
        if not r:
            for apn in re.split(r"[;,]", o.get("apn", "")):
                r = by_apn.get(apn.replace("-", "").strip())
                if r: break
        if not r: print("  no resident row for owner record:", o.get("input_address")); continue
        matched += 1
        if not r.get("apn") and o.get("apn"): r["apn"] = o["apn"]
        note = (o.get("notes") or "").strip()
        if note and "see link_address_flags" not in note:
            add_flag(r, "Owner lookup: " + note)
        raw = (o.get("owner_names") or "").strip()
        if not raw: continue
        if not r.get("owner_of_record"):
            r.update(owner_of_record=raw, owner_name_confidence=(o.get("confidence") or "").lower(),
                     owner_as_of_date=o.get("as_of_date", ""), owner_source=o.get("source", ""))
        if not r.get("owner_or_resident_names"):           # never overwrite names Gene typed
            r["owner_or_resident_names"] = friendly_owner_name(raw)
            r["source_of_name"] = OWNER_LABEL
            filled += 1
    write_csv(D("residents.csv"), rows, RES_FIELDS)
    print(f"owner records matched to {matched} homes; filled names into {filled} blank rows")

def add_flag(r, text):
    if text and text not in (r.get("flags") or ""):
        r["flags"] = "; ".join(x for x in [r.get("flags", ""), text] if x)

def merge_flags(path):
    rows = read_csv(D("residents.csv"))
    idx = {resident_key(r["street"], r["number"]): r for r in rows}
    n = 0
    for f in read_csv(path):
        st, nums = parse_input_address(f.get("input_address", ""))
        text = f"Address check: {f.get('issue', '')}. Suggested: {f.get('suggested_correction', '')}. Evidence: {f.get('evidence', '')}"
        for num in nums:
            r = idx.get((st, num))
            if r: add_flag(r, text); n += 1
            else: print("  no resident row for flag:", f.get("input_address"), num)
    write_csv(D("residents.csv"), rows, RES_FIELDS)
    print(f"added address-check flags to {n} homes")

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
            "source_of_name": r.get("source_of_name", ""),
            "is_owner_of_record": r.get("source_of_name", "") == OWNER_LABEL,
            "owner_of_record": r.get("owner_of_record", ""), "owner_name_confidence": (r.get("owner_name_confidence") or "").lower(),
            "owner_as_of_date": r.get("owner_as_of_date", ""), "owner_source": r.get("owner_source", ""),
            "emails": split_multi(r.get("emails")),
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
    if "--merge-flags" in sys.argv: merge_flags(sys.argv[sys.argv.index("--merge-flags") + 1])
    build()
