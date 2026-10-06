"""Generate data/addresses.csv from the verbatim sheet transcription, with flags."""
import csv, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from transcription import SHEET

from transcription import FLAGS, STREET_FLAGS  # local-only file (contains the address list)
rows = []; seen = {}
for item, sheet_name, street, cnt, nums in SHEET:
    for pos, n in enumerate(nums.split(","), 1):
        n = n.strip()
        flags = []
        key = (street, n)
        if key in seen:
            flags.append(f"DUPLICATE: {n} {sheet_name} appears twice on sheet (positions {seen[key]} and {pos}); kept once")
            rows[-1:]  # noop
            # mark the earlier row too
            for r in rows:
                if r["street"] == street and r["number"] == n and "DUPLICATE" not in r["flags"]:
                    r["flags"] = "; ".join(x for x in [r["flags"], "DUPLICATE on sheet (listed twice)"] if x)
            continue
        seen[key] = pos
        if (sheet_name, n) in FLAGS: flags.append(FLAGS[(sheet_name, n)])
        if sheet_name in STREET_FLAGS: flags.append(STREET_FLAGS[sheet_name])
        rows.append(dict(sheet_item=item, sheet_street=sheet_name, street=street, number=n,
                         full_address=f"{n} {street}, Lafayette, CA 94549", flags="; ".join(flags)))
os.makedirs("data", exist_ok=True)
with open("data/addresses.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print(len(rows), "unique addresses written")
