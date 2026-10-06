#!/usr/bin/env python3
"""Las Trampas Firewise - match KNOWN neighbor emails to roster households (local, private).

  python3 tools/match_emails.py          # read data/private inputs, write data/private outputs, print a summary

This script contains NO personal data. Every input and output lives in the git-ignored data/private/ folder.

Allowed sources (the only ones): Gene's own mail, lists that neighbors/organizers share with us, and public
county records (data/link_owner_names.csv). No people-search sites, data brokers, or email guessing. The script
never invents an email or an address; it only compares emails we already have against owner-of-record names.

Inputs (all optional except the owner file):
  data/link_owner_names.csv            public county deed-index owner names per roster home
  data/private/gmail_evidence.csv      email,display_name,self_identifying,evidence_date,thread_subject,role,source_list
  data/private/inbox/*.csv             lists to match. Columns: email[,display_name][,source_list][,address]
                                       Rows that also have a roster_status column are HAND-VERIFIED ("curated") and are
                                       taken as-is (needs: address, confidence, match_method, matched_owner_name, evidence,
                                       source_evidence[, street_hint][, note]); roster_status 'official' = not a resident.
  data/private/manual_facts.csv        email,kind,address,matched_owner_name,confidence,evidence,evidence_append
                                       kind = exact (self-/organizer-stated address) | corroborated | override
Outputs (data/private/):
  email_household_matches.csv  one row per email x home, with confidence, method, evidence and source_evidence
  unmatched_emails.csv         emails not placed on a roster home (not in roster / no owner match / officials)
  household_email_rollup.csv   one row per roster home

Rule order: exact stated address > display name = owner first+last > email local-part ~ owner name.
Then merge into the site data:  python3 tools/build_data.py --merge-emails data/private/email_household_matches.csv
"""
import csv, glob, os, re
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIV = os.path.join(ROOT, "data", "private")
OWN = os.path.join(ROOT, "data", "link_owner_names.csv")
P = lambda *p: os.path.join(PRIV, *p)

NICK = {'tom':'thomas','tommy':'thomas','ray':'raymond','bob':'robert','rob':'robert','bill':'william','will':'william',
        'jim':'james','jimmy':'james','mike':'michael','dave':'david','dan':'daniel','joe':'joseph','chris':'christopher',
        'kate':'katherine','katie':'katherine','liz':'elizabeth','beth':'elizabeth','sue':'susan','pat':'patrick',
        'rick':'richard','dick':'richard','steve':'steven','greg':'gregory','jen':'jennifer','jenny':'jennifer',
        'matt':'matthew','andy':'andrew','tony':'anthony','ed':'edward','ted':'edward'}
COMMON_SURNAMES = {'smith','johnson','williams','brown','jones','miller','davis','garcia','wilson','anderson','taylor',
                   'thomas','moore','martin','lee','white','harris','clark','lewis','young','hall','allen','king','wright','scott'}
SKIP = {'TRE','TR','TRS','TRUSTEE','TRUST','FAMILY','REVOCABLE','LIVING','THE','OF','AND','ET','AL','LLC','INC','F/TR','JR','SR',
        'II','III','IV','DI','SURVIVORS','SURVIVOR'}
RANK = {'high': 3, 'medium': 2, 'low': 1}

def rd(path):
    if not os.path.exists(path): return []
    with open(path, newline="", encoding="utf-8-sig") as f: return list(csv.DictReader(f))

def norm(s): return re.sub(r'[^a-z]', '', s.lower())

def parse_people(owner_names):
    """deed entries 'LAST FIRST M [TRE]' -> [(first, last, 'person')]; trust/LLC entries -> surnames only (first='')."""
    people = []
    for part in [p.strip() for p in owner_names.split(';') if p.strip()]:
        toks = [t for t in re.split(r'[\s,]+', part.upper()) if t]
        if any(t in ('TRUST','F/TR','LLC','INC','PARTNERSHIP','LP','&') for t in toks):   # '<SURNAME> FAMILY TRUST', '<A> & <B> <SURNAME> F/TR'
            words = [t for t in toks if t not in SKIP and t != '&' and not re.match(r'^\d', t) and len(t) > 1]
            for w in words: people.append(('', w.lower(), 'trust'))
            continue
        toks = [t for t in toks if t not in SKIP]
        if len(toks) >= 2:
            last = toks[0]
            for last_part in last.split('-'): people.append((toks[1].lower(), last_part.lower(), 'person'))
            if '-' in last: people.append((toks[1].lower(), norm(last), 'person'))
        elif toks:
            people.append(('', toks[0].lower(), 'person'))
    return people

def addr_key(s):
    s = s.lower().replace(',', ' ')
    m = re.match(r'\s*(\d+)\s+(.*)', s)
    if not m: return None
    num, rest = m.groups()
    street = re.sub(r'\b(lafayette|ca|94549|california)\b', '', rest)
    for pat, rep in ((r'\b(court|ct)\b', 'ct'), (r'\b(circle|cir)\b', 'cir'), (r'\b(drive|dr)\b', 'dr'),
                     (r'\b(road|rd)\b', 'rd'), (r'\b(lane|ln)\b', 'ln'), (r'\b(manor|mnr)\b', 'manor')):
        street = re.sub(pat, rep, street)
    street = street.replace('palo manor', 'palos manor').replace('colrados', 'colorados').replace('olivera', 'oliveira')
    return num + ' ' + ' '.join(street.split())

def match():
    owners = rd(OWN)
    for r in owners: r['_people'] = parse_people(r['owner_names'])
    by_addr = {addr_key(r['full_address']): r for r in owners}
    surname_addrs = defaultdict(set)
    for r in owners:
        for f, l, k in r['_people']: surname_addrs[l].add(r['full_address'])

    emails = {}
    def add(e, dn='', src='', addr='', selfid='', date='', subj='', role=''):
        e = e.strip().lower()
        if not e or '@' not in e: return
        d = emails.setdefault(e, {'display': set(), 'src': set(), 'addr': '', 'selfid': '', 'date': '', 'subj': '', 'role': ''})
        if dn: d['display'].add(dn.strip())
        if src: d['src'].add(src.strip())
        for k, v in (('addr', addr), ('selfid', selfid), ('date', date), ('subj', subj), ('role', role)):
            if v and not d[k]: d[k] = v
    for r in rd(P('gmail_evidence.csv')):
        add(r['email'], r['display_name'], r['source_list'], '', r['self_identifying'], r['evidence_date'], r['thread_subject'], r['role'])
    curated = {}
    for f in sorted(glob.glob(P('inbox', '*.csv'))):
        for r in rd(f):
            if r.get('roster_status'):
                e = r['email'].strip().lower()
                add(e, r.get('display_name', ''), r.get('source_list') or os.path.basename(f)); curated[e] = r
            else:
                add(r.get('email', ''), r.get('display_name', ''), r.get('source_list') or os.path.basename(f), r.get('address', ''))

    facts = rd(P('manual_facts.csv'))
    EXACT = {r['email'].strip().lower(): (r['address'], r['matched_owner_name']) for r in facts if r['kind'] == 'exact'}
    CORROB = {r['email'].strip().lower(): (r['address'], r['matched_owner_name'], r['confidence'] or 'medium', r['evidence'])
              for r in facts if r['kind'] == 'corroborated'}
    OVERRIDE = {r['email'].strip().lower(): r for r in facts if r['kind'] == 'override'}

    matches, unmatched = [], []
    def um(e, d, clue, reason, src, status, se, conf='', hint=''):
        unmatched.append({'email': e, 'display_names': '; '.join(sorted(d['display'])), 'partial_clue': clue, 'reason': reason,
                          'source_list': src, 'confidence': conf, 'street_hint': hint, 'roster_status': status, 'source_evidence': se})
    for e, d in sorted(emails.items()):
        src = '; '.join(sorted(d['src']))
        prior_src = f"Gene's Gmail: {d['subj']} ({d['date']})" if d['subj'] else ''
        if e in curated:
            c = curated[e]
            se = '; '.join(x for x in (c.get('source_evidence', ''), prior_src) if x)
            r = by_addr.get(addr_key(c['address'])) if c.get('address') else None
            if c['roster_status'] == 'official':
                um(e, d, c.get('evidence', ''), 'not a resident (agency/city contact) - excluded from household matching', src, 'official', se)
            elif r:
                matches.append({'email': e, 'matched_full_address': r['full_address'], 'matched_owner_name': c.get('matched_owner_name', ''),
                                'match_method': c.get('match_method', ''), 'confidence': c.get('confidence', ''), 'evidence': c.get('evidence', ''),
                                'source_list': src, 'source_evidence': se, 'note': c.get('note', '')})
            else:
                nir = bool(c.get('address'))
                um(e, d, (f"stated address: {c['address']} | " if nir else '') + c.get('evidence', '') + (f" | {c['note']}" if c.get('note') else ''),
                   'NOT IN ROSTER: stated address is not one of the 193 Firewise homes' if nir else
                   ('street hint only, no owner-of-record match' if c.get('confidence') == 'low' else 'no owner-of-record name or address matches'),
                   src, c['roster_status'], se, c.get('confidence', ''), c.get('street_hint', ''))
            continue
        if 'official' in d['role']:
            um(e, d, d['selfid'] or d['role'], 'not a resident (agency/city contact) - excluded from household matching', src, 'official', prior_src)
            continue
        found = []
        addr_stated = d['addr'] or EXACT.get(e, ('', ''))[0]
        if addr_stated:
            r = by_addr.get(addr_key(addr_stated))
            if r:
                found.append((r, EXACT.get(e, ('', ''))[1] or r['owner_names'], 'exact (self-stated/organizer-stated address)', 'high',
                              f"{d['selfid'] or 'address in list'} ({d['subj']} {d['date']})"))
        if e in CORROB:
            a, nm, conf, ev = CORROB[e]
            r = by_addr.get(addr_key(a))
            if r: found.append((r, nm, 'co-owner first+middle-initial local-part, corroborated by Gene forwarding Firewise mail', conf, ev))
        for dn in d['display']:   # display name = owner first + last
            toks = [norm(t) for t in re.split(r'[\s,()&]+', dn) if norm(t) and norm(t) not in ('and', 'the', 'family')]
            for r in owners:
                for f, l, k in r['_people']:
                    if l and l in toks:
                        firsts = {t for t in toks if t != l}
                        fm = f and (f in firsts or any(NICK.get(t) == f for t in firsts) or any(f.startswith(t) and len(t) >= 3 for t in firsts))
                        if fm:
                            n = len(surname_addrs[l])
                            found.append((r, f"{f.title()} {l.title()}", 'display name = owner first+last', 'high' if n == 1 else 'medium',
                                          f'display name "{dn}" ({d["subj"]} {d["date"]}); surname on {n} owner record(s)'))
        lp = norm(e.split('@')[0])   # email local-part ~ owner name (compares only; never generates addresses)
        for r in owners:
            for f, l, k in r['_people']:
                if len(l) < 3 or l not in lp: continue
                rest = lp.replace(l, '', 1)
                if f and (rest in (f, f[0], f[0] + 'r', f[0] + 'g') or rest.startswith(f) or (len(rest) <= 3 and rest and rest[0] == f[0])) \
                   or rest in ('family', 'fam', 'house', ''):
                    conf = 'low' if (l in COMMON_SURNAMES or len(surname_addrs[l]) > 1) else 'medium'
                    found.append((r, f"{f.title()} {l.title()}".strip(), 'email local-part ~ owner name', conf,
                                  f'local-part "{e.split("@")[0]}" ~ {l.upper()} {f.upper()}'))
        best = {}   # de-dup per address, keep best confidence
        for r, nm, meth, conf, ev in found:
            a = r['full_address']
            if a not in best or RANK[conf] > RANK[best[a][2]] or (RANK[conf] == RANK[best[a][2]] and meth.startswith('exact')):
                best[a] = (nm, meth, conf, ev)
            else:
                nm0, m0, c0, e0 = best[a]
                if RANK[conf] > RANK[c0]: nm0, c0 = nm, conf
                elif nm.split()[0].lower() not in nm0.lower() and not meth.startswith('email'): nm0 = nm0 + ' / ' + nm
                if meth not in m0: m0 = m0 + ' + ' + meth
                if ev not in e0: e0 = e0 + ' | ' + ev
                best[a] = (nm0, m0, c0, e0)
        if not best:
            um(e, d, d['selfid'] or d['role'], 'no owner-of-record name or address matches', src, 'no owner match', prior_src)
        for a, (nm, meth, conf, ev) in best.items():
            matches.append({'email': e, 'matched_full_address': a, 'matched_owner_name': nm, 'match_method': meth,
                            'confidence': conf, 'evidence': ev, 'source_list': src, 'source_evidence': prior_src, 'note': ''})
    for m in matches:
        o = OVERRIDE.get(m['email'])
        if o:
            if o.get('matched_owner_name'): m['matched_owner_name'] = o['matched_owner_name']
            if o.get('evidence_append'): m['evidence'] += o['evidence_append']
    return owners, emails, matches, unmatched

def write(owners, emails, matches, unmatched):
    F = ['email','matched_full_address','matched_owner_name','match_method','confidence','evidence','source_evidence','note','source_list']
    with open(P('email_household_matches.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, F); w.writeheader(); w.writerows(sorted(matches, key=lambda m: (m['matched_full_address'], m['email'])))
    UF = ['email','display_names','roster_status','confidence','street_hint','partial_clue','reason','source_evidence','source_list']
    order = {'NOT IN ROSTER': 0, 'no owner match': 1, 'official': 2}
    with open(P('unmatched_emails.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, UF); w.writeheader()
        w.writerows(sorted(unmatched, key=lambda u: (order.get(u['roster_status'], 1), u['confidence'] != 'low', u['email'])))
    by_email, by_addr = defaultdict(set), defaultdict(list)
    for m in matches: by_email[m['email']].add(m['matched_full_address']); by_addr[m['matched_full_address']].append(m)
    multi = {e for e, a in by_email.items() if len(a) > 1}
    clues = defaultdict(list)
    for r in rd(P('pdf_name_clues.csv')):
        if r.get('matched_full_address'): clues[r['matched_full_address']].append(f"{r['name']} ({r['source_evidence'].split('.pdf ')[-1]})")
    with open(P('household_email_rollup.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['full_address','owner_names','emails','best_confidence','needs_gene_review','name_clue_no_email'])
        for r in owners:
            ms = by_addr.get(r['full_address'], [])
            best = max((m['confidence'] for m in ms), key=lambda c: RANK[c], default='')
            review = 'Y' if any(m['confidence'] != 'high' or m['email'] in multi or m.get('note', '').startswith('WORK') for m in ms) else 'N'
            w.writerow([r['full_address'], r['owner_names'], ';'.join(sorted({m['email'] for m in ms})), best, review,
                        '; '.join(clues.get(r['full_address'], [])) if not ms else ''])
    best_conf = Counter(max((m['confidence'] for m in matches if m['email'] == e), key=lambda c: RANK[c]) for e in by_email)
    print('emails known:', len(emails), '| matched to a roster home:', len(by_email), dict(best_conf))
    print('unmatched by status:', dict(Counter((u['roster_status'], u['confidence']) for u in unmatched)))
    print('households with >=1 email:', len(by_addr), 'of', len(owners), '| emails on more than one home:', len(multi))
    print('households with a name clue but no email:', sum(1 for a in clues if a not in by_addr))
    print('wrote data/private/email_household_matches.csv, unmatched_emails.csv, household_email_rollup.csv')

if __name__ == '__main__':
    write(*match())
