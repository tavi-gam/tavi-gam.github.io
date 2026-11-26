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
FINALS = str.maketrans('ךםןףץ', 'כמנפצ')
def stem(t):
    t = t.translate(FINALS)
    if len(t) >= 5 and t[-1] == 'י':
        t = t[:-1]
    if len(t) >= 5 and t[-2:] in ('ות', 'ימ'):
        return t[:-2]
    if len(t) >= 4 and t[-1] in 'הת':
        return t[:-1]
    return t
UNITS = {'גרם', 'גר', 'קג', 'ק"ג', 'ליטר', 'מל', 'יח', 'מ"ל', 'ל', 'ג', 'קילו', 'אריזה', 'מארז', 'ארוז', 'בתפזורת', 'שקיל', 'טרי', 'טריים', 'טריה'}
def tmatch(t, itset, itstr):
    if t not in itset and not any(ch.isdigit() for ch in t) and len(t) >= 4:
        st = stem(t)
        if any(stem(x) == st for x in itset):
            return True
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
        first2 = it['ns'].split()[:2]
        f2 = set(first2) | {t[1:] for t in first2 if len(t) >= 4 and t[0] in 'הבול'}
        if head not in f2 and stem(head) not in {stem(x) for x in f2} and not any(x.startswith(head) for x in first2 if len(head) >= 3):
            continue
        hit = sum(1 for t in ct if tmatch(t, it['ts'], it['ns']))
        sc = hit / len(ct)
        if sc < 0.67:
            continue
        words = [w for w in it['ns'].split() if not any(ch.isdigit() for ch in w) and w not in UNITS]
        extra = max(0, len(words) - hit)
        cands.append((sc, extra * 100 + len(it['ns']), it))
    if not cands:
        return None
    if aisle == 0 and any(c[2]['w'] for c in cands):
        cands = [c for c in cands if c[2]['w']]
    top = max(c[0] for c in cands)
    lead = lambda c: 0 if c[2]['ns'].startswith(head) else 1
    pool = sorted([c for c in cands if c[0] == top], key=lambda c: (lead(c), c[1]))[:7]
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
        w = (f.get('bisweighted') or f.get('isweighted') or '0').strip() in ('1', 'true')
        if name and 0.3 <= price <= 1000:
            items.append({'n': name, 'p': price, 'code': f.get('itemcode', ''), 'w': w,
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
    import inspect
    r = s.scrape(limit=1, files_types=['PRICE_FULL_FILE'], min_size=200_000, filter_null=True, filter_zero=True)
    print(f'[{chain}] scrape returned {type(r).__name__}')
    if inspect.isasyncgen(r) or inspect.iscoroutine(r):
        import asyncio
        async def _drain(x):
            if inspect.iscoroutine(x):
                return await x
            return [y async for y in x]
        r = asyncio.run(_drain(r))
    elif hasattr(r, '__next__'):
        r = list(r)
    print(f'[{chain}] result: {str(r)[:600]}')
    files = [f for f in glob.glob(out + '/**/*', recursive=True) if os.path.isfile(f) and f not in before]
    files = [f for f in files if 'pricefull' in os.path.basename(f).lower()]
    return sorted(files, key=os.path.getsize, reverse=True)

def main():
    prev, prevdoc = {}, {}
    if os.path.exists(OUT):
        try:
            prevdoc = json.load(open(OUT, encoding='utf-8'))
            prev = prevdoc.get('chains', {})
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
    # price changes vs the previous run (same chain and same branch only)
    now = int(time.time())
    changes = []
    for chain, cur in res.items():
        old = prev.get(chain)
        if not old or old is cur or old.get('store') != cur.get('store'):
            continue
        for n, v in cur['items'].items():
            o = old['items'].get(n)
            if not o or not o.get('p') or o.get('k') != v.get('k'):
                continue
            a, b = float(o['p']), float(v['p'])
            if abs(b - a) >= 0.3 and abs(b - a) / a >= 0.03:
                changes.append({'ch': chain, 'n': n, 'old': a, 'new': b})
    changes.sort(key=lambda c: -abs(c['new'] - c['old']) / c['old'])
    hist = [h for h in prevdoc.get('history', []) if now - h.get('t', 0) < 30 * 86400]
    if changes:
        hist.insert(0, {'t': now, 'list': changes[:300]})
    print(f'changes: {len(changes)}')
    json.dump({'updated': now, 'changes': {'t': now, 'count': len(changes), 'list': changes[:300]}, 'history': hist[:30], 'chains': res},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))

if __name__ == '__main__':
    main()
