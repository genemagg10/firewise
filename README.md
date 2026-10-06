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
Edit `data/events.csv` (`id,title,date,end_date,time,location,organizer,cost,description,link`, with dates as `YYYY-MM-DD`). Events move to a collapsed "Past events" list automatically the day after their `end_date` (or `date`).
Then rebuild and commit as above.

### Public-record owner names (optional)
```
FIREWISE_PASSWORD='<site password>' python3 tools/build_data.py --merge-owners data/link_owner_names.csv --merge-flags data/link_address_flags.csv
```
* Fills only blank name cells (matched by sheet address, then by parcel number). Names you typed yourself are never overwritten.
* The raw deed-index text is kept in `owner_of_record`; the Name(s) column gets a best-effort friendly version
  (e.g. `DOE JOHN & JANE TRE` becomes `John & Jane Doe (trustees)`; trusts and LLCs stay as written, in title case).
* Every such name is labeled "Owner of record (county deed index), may not be the current resident" in the roster and map.
* Also stored: `apn`, `owner_name_confidence` (high / medium / low), `owner_as_of_date` (deed recording date), `owner_source`.
* Address-check flags and lookup notes are appended to each home's `flags`. Re-running is safe (no duplicates).
* Roster: the "No name yet" checkbox and "Name confidence" filter show what is still missing or uncertain.
* `python3 tools/check_no_plaintext.py --tracked` scans every tracked file (not just staged ones) for names, emails, phones and the password.

### Adding neighbor emails
Matching runs locally. Every input and output stays in `data/private/`, which is git-ignored and never published. The
emails reach git only inside the encrypted `data/residents.enc.json`.

1. Drop each new list into `data/private/inbox/` as a CSV with an `email` column, plus optional `display_name`,
   `source_list` (where the list came from) and `address`. For example, a list an organizer shares, or an export from Gene's mail.
2. Match emails to homes:
   ```
   python3 tools/match_emails.py
   ```
   This writes `email_household_matches.csv` (with confidence, method, and evidence for each match), `unmatched_emails.csv`
   and `household_email_rollup.csv` in `data/private/`. Review them. To fix a match by hand, add a row to
   `data/private/manual_facts.csv` (`kind` = `exact`, `corroborated`, or `override`), or add a hand-checked inbox CSV
   with a `roster_status` column. Then re-run.
3. Merge and rebuild:
   ```
   FIREWISE_PASSWORD='<site password>' python3 tools/build_data.py --merge-emails data/private/email_household_matches.csv
   ```
   * Only **high** and **medium** confidence matches are attached to a home, with `email_confidence` and
     `email_source_evidence`. Low-confidence guesses are never attached.
   * Emails typed by hand into `residents.csv` are kept. Re-running is safe.
   * Emails that can't be tied to a home (agency and city contacts excluded) go into the encrypted data as
     "Unplaced contacts". They show in a collapsed section under the roster and are left out of Copy emails and CSV export.
   * In the roster and map, hover over an email to see how it was matched. Medium matches carry a pill.
4. Commit and push as usual. The pre-commit check also blocks any email, name, or evidence quote from the `data/private/` files.

**Sourcing rule:** matches come only from Gene's own mail, lists that neighbors and organizers share with us, and public
county records. Never use people-search sites, data brokers, or email guessing. The script only compares emails we already have
against owner-of-record names. It never generates an email or an address.

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
