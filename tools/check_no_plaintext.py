#!/usr/bin/env python3
"""Refuse to commit plaintext resident data. Run before every commit (installed as .git/hooks/pre-commit).

Checks every STAGED file (git index) for:
  * forbidden paths (plaintext data, owner research, Link's scripts)
  * any email address
  * any name / email / phone / note value that appears in the local data/residents.csv or data/link_owner_names.csv
  * phone-number patterns
  * the site password, if FIREWISE_PASSWORD is set in the environment
Exit code 1 (commit blocked) on any hit.
"""
import csv, os, re, subprocess, sys

ROOT = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
os.chdir(ROOT)
ALLOWED = {".gitignore", ".nojekyll", "README.md", "index.html", "map.html", "roster.html", "events.html",
           "data/residents.enc.json", "data/public-data.js", "data/events.json", "data/events.csv"}
ALLOWED_PREFIX = ("assets/", "tools/")
FORBIDDEN_TOOLS = {"tools/transcription.py"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\d.])\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")
ALLOWED_EMAIL_FILES = ("assets/vendor/",)   # third-party library headers
# Public organizational contacts deliberately published on the events page (NOT residents):
PUBLIC_CONTACT_EMAILS = {"lafayettefirewise@gmail.com"}

def staged():
    out = subprocess.check_output(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], text=True)
    return [p for p in out.splitlines() if p]

def secrets():
    vals = set()
    for path, cols in (("data/residents.csv", ["owner_or_resident_names", "emails", "phone", "notes", "events_attended"]),
                       ("data/link_owner_names.csv", ["owner_names"])):
        if not os.path.exists(path): continue
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            for c in cols:
                for v in re.split(r"[;|\n]", r.get(c) or ""):
                    v = v.strip()
                    if len(v) >= 4: vals.add(v)
    pw = os.environ.get("FIREWISE_PASSWORD")
    if pw: vals.add(pw)
    return vals

def main():
    files, bad = staged(), []
    vals = secrets()
    for p in files:
        if not (p in ALLOWED or p.startswith(ALLOWED_PREFIX)) or p in FORBIDDEN_TOOLS:
            bad.append(f"{p}: path is not on the publish allow-list"); continue
        blob = subprocess.run(["git", "show", f":{p}"], capture_output=True).stdout
        try: text = blob.decode("utf-8")
        except UnicodeDecodeError: continue  # binary (images): skip content checks
        if not p.startswith(ALLOWED_EMAIL_FILES):
            for m in EMAIL.findall(text):
                if m.lower() not in PUBLIC_CONTACT_EMAILS: bad.append(f"{p}: contains an email address ({m[:3]}...)")
            for m in PHONE.findall(text): bad.append(f"{p}: contains a phone-number pattern")
        low = text.lower()
        for v in vals:
            if v.lower() in low: bad.append(f"{p}: contains a private value from residents/owner data or the password")
    if bad:
        print("BLOCKED - plaintext private data in staged files:\n  " + "\n  ".join(sorted(set(bad))))
        sys.exit(1)
    print(f"check_no_plaintext: OK ({len(files)} staged files scanned, {len(vals)} private values checked)")

if __name__ == "__main__":
    main()
