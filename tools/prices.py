"""Nightly: download one full price file per chain (a big branch), match our catalog by name, write prices.json."""
import glob, gzip, io, json, os, re, statistics, sys, time, traceback, zipfile
from xml.etree import ElementTree as ET

from il_supermarket_scarper.scrappers_factory import ScraperFactory

CHAINS = {  # app chain name -> scraper
    'רמי לוי': 'RAMI_LEVY',
    'שופרסל דיל': 'SHUFERSAL',
    'אושר עד': 'OSHER_AD',
    'יוחננוף': 'YOHANANOF',
    'ויקטורי': 'VICTORY_NEW_SOURCE',
    'קרפור היפר': 'YAYNO_BITAN_AND_CARREFOUR',
    'מחסני השוק': 'MAHSANI_ASHUK_NEW_SOURCE',
    'טיב טעם': 'TIV_TAAM',
    'סלאח דבאח': 'SALACH_DABACH',
    'קשת טעמים': 'KESHET',
    'חצי חינם': 'HAZI_HINAM',
    'קינג סטור': 'KING_STORE',
}
ONLY = [c for c, v in CHAINS.items() if v in sys.argv[1:]] or list(CHAINS)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = json.load(open(os.path.join(ROOT, 'tools', 'catalog.json'), encoding='utf-8'))
OUT = os.path.join(ROOT, 'prices.json')

# ---------- text matching ----------
STRIP = re.compile(r'[״׳"\'`´’‘\(\)\[\]\.,/\\\-_+*:;!?|]')
def norm(s):
    s = STRIP.sub(' ', s or '').replace('%', '% ').lower()
    return re.sub(r'\s+', ' ', s).strip()
def toks(s):
    out = []
    for t in norm(s).split():
        if len(t) >= 4 and t[0] in 'הבול' and not t[1:].isdigit():
            out.append(t[1:])
        out.append(t)
    return out
def ttoks(s):  # base tokens for the catalog name (no prefix-stripped duplicates)
    res = []
    for t in norm(s).split():
        if len(t) >= 4 and t[0] in 'בול' and not t[1:].isdigit():
            t = t[1:]
        res.append(t)
    return res
def tmatch(t, itset, itstr):
    if t in itset:
        return True
    if any(ch.isdigit() for ch in t):
        return False
    return len(t) >= 3 and (' ' + t) in (' ' + itstr)

def best_price(name, aisle, items):
    ct = ttoks(name)
    if not ct:
        return None
    head = ct[0]
    cands = []
    for it in items:
        if not tmatch(head, it['ts'], it['ns']):
            continue
        hit = sum(1 for t in ct if tmatch(t, it['ts'], it['ns']))
        sc = hit / len(ct)
        if sc < 0.67:
            continue
        cands.append((sc, len(it['ns']), it))
    if not cands:
        return None
    top = max(c[0] for c in cands)
    pool = sorted([c for c in cands if c[0] == top], key=lambda c: c[1])[:7]
    prices = sorted(c[2]['p'] for c in pool)
    med = statistics.median(prices)
    rep = min(pool, key=lambda c: abs(c[2]['p'] - med))[2]
    return {'p': round(med, 2), 'n': rep['n'][:60], 'k': rep['code'], 'm': round(top, 2), 'c': len(pool)}

# ---------- XML parsing ----------
def opener(path):
    raw = open(path, 'rb').read()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    if raw[:2] == b'PK':
        z = zipfile.ZipFile(io.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    return raw

def parse(path):
    raw = opener(path)
    items, store = [], ''
    for ev, el in ET.iterparse(io.BytesIO(raw), events=('end',)):
        tag = el.tag.split('}')[-1].lower()
        if tag in ('storeid', 'storename') and not store and el.text:
            store = el.text.strip()
        if tag not in ('item', 'product'):
            continue
        f = {c.tag.split('}')[-1].lower(): (c.text or '').strip() for c in el}
        name = f.get('itemname') or f.get('itemnm') or f.get('manufactureritemdescription') or ''
        try:
            price = float(f.get('itemprice') or f.get('price') or 0)
        except ValueError:
            price = 0
        if name and 0.3 <= price <= 1000:
            items.append({'n': name, 'p': price, 'code': f.get('itemcode', ''),
                          'ns': norm(name), 'ts': set(toks(name))})
        el.clear()
    return items, store

def fetch(chain, scr):
    cls = ScraperFactory.get(scr) if hasattr(ScraperFactory, 'get') else getattr(ScraperFactory, scr).value
    out = os.path.join(ROOT, 'dumps', scr)
    os.makedirs(out, exist_ok=True)
    before = set(glob.glob(out + '/**/*', recursive=True))
    from il_supermarket_scarper.engines import engine as _eng
    s = cls(file_output=_eng.DiskFileOutput(storage_path=out))
    try:
        s.scrape(limit=1, files_types=['PRICE_FULL_FILE'], min_size=200_000, filter_null=True, filter_zero=True)
    except TypeError:
        s.scrape(limit=1, files_types=['PRICE_FULL_FILE'])
    files = [f for f in glob.glob(ROOT + '/dumps/**/*', recursive=True) if os.path.isfile(f) and f not in before]
    files += [f for f in glob.glob(ROOT + '/**/*PriceFull*', recursive=True) if os.path.isfile(f) and f not in files and '/.git/' not in f]
    files = [f for f in files if 'pricefull' in os.path.basename(f).lower()]
    return sorted(files, key=os.path.getsize, reverse=True)

def main():
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT, encoding='utf-8')).get('chains', {})
        except Exception:
            prev = {}
    res = dict(prev)
    for chain in ONLY:
        scr = CHAINS[chain]
        t0 = time.time()
        try:
            files = fetch(chain, scr)
            if not files:
                print(f'[{chain}] no files'); continue
            items, store = parse(files[0])
            print(f'[{chain}] file={os.path.basename(files[0])} items={len(items)} store={store}')
            if len(items) < 500:
                print(f'[{chain}] too few items, keeping previous'); continue
            got = {}
            for row in CAT['items']:
                m = best_price(row['n'], row['c'], items)
                if m:
                    got[row['n']] = m
            res[chain] = {'store': store, 'file': os.path.basename(files[0]), 't': int(time.time()), 'items': got}
            print(f'[{chain}] matched {len(got)}/{len(CAT["items"])} in {time.time()-t0:.0f}s')
            for k in list(got)[:8]:
                print('   ', k, '->', got[k]['n'], got[k]['p'])
        except Exception:
            print(f'[{chain}] FAILED'); traceback.print_exc()
    json.dump({'updated': int(time.time()), 'chains': res}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))

if __name__ == '__main__':
    main()
