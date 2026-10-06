# Las Trampas Firewise Neighborhood: organizer site

Evacuation Area 016, Lafayette, CA. A static site (no server code) published with GitHub Pages.

## What's public and what's encrypted
| Public (anyone with the link) | Password-protected (encrypted) |
|---|---|
| `events.html`: upcoming events and resources | `map.html`: every home, with names, emails, and status |
| `index.html` page shell (counts appear only after unlock) | `roster.html`: the table, Copy emails, and CSV export |
| Site code (`assets/`, `tools/`) | All household data: addresses, map positions, names, emails, phones, sign-up status, events attended, notes, owner names |

**How the protection works.** Household data is committed **only** as ciphertext (`data/residents.enc.json`, plus a copy inside
`data/public-data.js`). It is encrypted with AES-256-GCM, and the key is derived from the site password with PBKDF2-SHA256
(600,000 iterations, random salt and IV, both regenerated on every build). The browser derives the same key with WebCrypto and
decrypts in the page. The key is kept in `sessionStorage`, so it is forgotten when the tab or browser closes; the **Lock** button forgets it immediately.
A wrong password fails the GCM integrity check and shows an error. The password is **never** stored in this repo.
Share it with organizers privately, not in email threads with neighbors.

The plaintext working files (`data/residents.csv`, `data/residents.json`, the address list, and any public-record owner research)
stay on the organizer's machine. `.gitignore` is deny-by-default, and `tools/check_no_plaintext.py` (installed as the
pre-commit hook) blocks any commit that contains an email address, a phone number, a name or email from `residents.csv`, or the password.

## Updating the data
1. Edit `data/residents.csv` (local only) in Excel, Numbers, or Google Sheets. There is one row per home.
   * `owner_or_resident_names`: separate multiple people with `;`
   * `source_of_name`
   * `emails`: separate multiple emails with `;`
   * `phone`
   * `signed_up`: `yes`, `no`, or blank (not known yet)
   * `events_attended`: separate events with `;`
   * `last_contact`: `YYYY-MM-DD`
   * `notes`
   * Leave the address, geocode, and `flags` columns alone. To hand-fix a pin, edit `lat`/`lng` and set `geocode_quality` to `manual`.
   * Blank cells show as blank on the site, so it's obvious what's missing.
2. Save as CSV (UTF-8), then rebuild. You'll be prompted for the password if the variable isn't set:
   ```
   FIREWISE_PASSWORD='<site password>' python3 tools/build_data.py
   ```
   This writes `data/residents.enc.json` and `data/public-data.js` (encrypted) plus `data/events.json`.
3. Commit and push:
   ```
   git add -A && git commit -m "Update neighborhood data" && git push
   ```
   The pre-commit check runs automatically. GitHub Pages redeploys in about a minute.

**Changing the password:** rebuild with the new password, then commit. Old copies of the encrypted file remain in git history
and still open with the old password, so treat a password change as protecting future data only.

### Events
Edit `data/events.csv` (`id,title,date,time,location,description,status,link`, where `status` is `upcoming` or `past`, and `past` is hidden).
Then rebuild and commit as above.

### Public-record owner names (optional)
```
FIREWISE_PASSWORD='<site password>' python3 tools/build_data.py --merge-owners data/link_owner_names.csv
```
This fills only blank name cells (matched by parcel number, then by address). Each name is labeled as a public-record owner, who may not be the resident.

### Fixing the address list (local working copy only)
1. Edit `tools/transcription.py`, a local-only verbatim copy of the address sheet.
2. Run:
   ```
   python3 tools/make_addresses.py && python3 tools/geocode.py && python3 tools/build_data.py --seed
   ```
   `--seed` keeps everything already typed into `residents.csv`.

## Geocoding sources
1. US Census geocoder. Its firewall rejected requests from our build machine.
2. Contra Costa County Assessor parcel situs addresses (parcel centroid). Only address fields are requested.
3. Nominatim/OpenStreetMap (1 request per second).
4. Street centroid, flagged.

Approximate pins are drawn with a dashed ring.

## Local preview
```
python3 -m http.server 8765 --bind 127.0.0.1
```
Then open http://127.0.0.1:8765/. Opening `index.html` straight from disk also works.
