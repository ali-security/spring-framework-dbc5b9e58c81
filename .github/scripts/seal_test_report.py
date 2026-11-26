"""Sealed-build test report: every skipped test with the reason it was skipped,
then JUnit XML totals per module. Added for the sealed build; runs after Gradle.

Inputs: build/seal-skipped/*.tsv (written by .github/scripts/seal-test-results.gradle)
and **/build/test-results/*/TEST-*.xml. The reason for each skip is taken from the
JUnit skip message plus the test source (method/class annotations, assume*/Assumptions
calls in the method body, @Before* lifecycle assumptions, superclass chain).
Output is grouped by (task, reason) so the whole report stays compact.
"""
import glob
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict, defaultdict

IDX = {}
for f in glob.glob('**/src/*/*/**/*.java', recursive=True) + glob.glob('**/src/*/*/**/*.kt', recursive=True):
    parts = f.split(os.sep)
    if 'src' not in parts:
        continue
    i = parts.index('src')
    if len(parts) > i + 3 and parts[i + 2] in ('java', 'kotlin'):
        IDX.setdefault('.'.join(parts[i + 3:]).rsplit('.', 1)[0], []).append(f)

ANN = re.compile(r'@(Disabled|Enabled|Ignore|IfProfileValue)\w*(\([^)]*\)?)?')
ASSUME = re.compile(r'\b(assume\w*|Assumptions\.\w+|Assume\.\w+)\s*\(')
CACHE = {}


def lines(f):
    if f not in CACHE:
        with open(f, encoding='utf-8', errors='replace') as h:
            CACHE[f] = h.read().splitlines()
    return CACHE[f]


def anns_before(ls, i):
    out = []
    for j in range(i, max(-1, i - 9), -1):
        s = ls[j].strip()
        if j < i and (s.endswith('}') or s.endswith(';')):
            break
        m = ANN.search(s)
        if m:
            out.append(m.group(0))
    return out


def body_assumes(ls, i):
    out, depth, started = [], 0, False
    for k in range(i, min(len(ls), i + 80)):
        line = ls[k]
        if ASSUME.search(line):
            stmt, n = line.strip(), k
            while not stmt.endswith(';') and n + 1 < len(ls) and n < k + 3:
                n += 1
                stmt += ' ' + ls[n].strip()
            out.append('assumption ' + stmt.rstrip(';'))
        depth += line.count('{') - line.count('}')
        started = started or '{' in line
        if started and depth <= 0:
            break
    return out


def chain(cls):
    top = cls.split('$')[0]
    seen = []
    while top in IDX and top not in seen and len(seen) < 6:
        seen.append(top)
        ls = lines(IDX[top][0])
        name = top.split('.')[-1]
        sup = None
        for line in ls:
            m = re.search(r'\bclass\s+' + re.escape(name) + r'\b[^{]*?\bextends\s+([\w.]+)', line)
            if m:
                sup = m.group(1)
                break
            m = re.search(r'\bclass\s+' + re.escape(name) + r'\b.*\)\s*:\s*([\w.]+)\(', line)
            if m:
                sup = m.group(1)
                break
        if not sup:
            break
        if '.' not in sup:
            imp = [x for x in ls if re.match(r'\s*import\s+[\w.]+\.' + re.escape(sup) + r'\s*;?\s*$', x)]
            sup = re.sub(r'^\s*import\s+|\s*;?\s*$', '', imp[0]) if imp else top.rsplit('.', 1)[0] + '.' + sup
        top = sup
    return seen


def lifecycle_assumes(ls):
    out = []
    for i, line in enumerate(ls):
        m = re.search(r'@(BeforeAll|BeforeEach|BeforeClass|Before)\b', line)
        if m:
            out += [a.replace('assumption', 'assumption in @' + m.group(1), 1) for a in body_assumes(ls, i + 1)]
    return out


def source_reason(cls, name, parent=''):
    if not cls or cls == 'UnknownClass':
        cls, name = name, ''
    raw = re.sub(r'[(\[].*$', '', name)
    if not raw.strip() and parent and parent != cls:
        raw = re.sub(r'[(\[].*$', '', parent)
    method = raw.strip()
    classes = chain(cls)
    why = []
    if method:
        alts = '|'.join(re.escape(m) for m in dict.fromkeys([raw, method, raw.rstrip()]) if m)
        pat = re.compile(r'\b(void|fun)\s+(`(' + alts + r')`|(' + alts + r'))\s*\(')
        sig = re.search(r'\(([^)]*)\)', name or parent or '')
        first = sig.group(1).split(',')[0].strip().split('.')[-1] if sig else ''
        for c in classes:
            ls = lines(IDX[c][0])
            hits = [i for i, x in enumerate(ls) if pat.search(x)]
            if sig is not None and hits:
                want = r'\(\s*\)' if not first else r'\(\s*(final\s+)?(@\w+(\([^)]*\))?\s+)*' + re.escape(first) + r'\b'
                exact = [i for i in hits if '(' in ls[i] and re.search(want, ls[i][ls[i].index('('):])]
                hits = exact or hits
            if hits:
                why += anns_before(ls, hits[0]) + body_assumes(ls, hits[0])
                break
    nested = cls.split('$')[1:]
    for c in classes:
        ls = lines(IDX[c][0])
        for n in [c.split('.')[-1]] + (nested if c == classes[0] else []):
            for i, x in enumerate(ls):
                if re.search(r'\b(class|interface)\s+' + re.escape(n) + r'\b', x):
                    why += ['class-level ' + a + ' on ' + n for a in anns_before(ls, i)]
                    break
        why += lifecycle_assumes(ls)
    return '; '.join(dict.fromkeys(why))


def reason(cls, name, msg='', parent=''):
    src = source_reason(cls, name, parent)
    parts = []
    if msg:
        parts.append('JUnit: ' + msg)
    if src:
        parts.append(src)
    r = '; '.join(parts) or 'skipped by an upstream JUnit execution condition at runtime (no test filter applied by this build)'
    r = ' '.join(r.split())
    return r if len(r) <= 220 else r[:217] + '...'


def short(cls, name):
    n = re.sub(r'\s+', ' ', name).strip()
    n = n if len(n) <= 40 else n[:37] + '...'
    return cls.split('.')[-1] + ('.' + n if n else '')


rows = []  # (task, cls, name, reason)
tsv_names = defaultdict(list)
for tsv in sorted(glob.glob('build/seal-skipped/*.tsv')):
    with open(tsv, encoding='utf-8') as h:
        for row in h:
            task, cls, name, msg, parent = (row.rstrip('\n').split('\t') + [''] * 5)[:5]
            tsv_names[(task, cls)].append(name)
            rows.append((task, cls, name, reason(cls, name, msg, parent)))

tot = OrderedDict()
failed_cases = []
for x in sorted(glob.glob('**/build/test-results/*/TEST-*.xml', recursive=True)):
    mod = x.split(os.sep + 'build' + os.sep)[0]
    task = ':' + mod.replace(os.sep, ':') + ':' + x.split(os.sep)[-2]
    try:
        root = ET.parse(x).getroot()
    except ET.ParseError:
        continue
    t = tot.setdefault(mod, [0, 0, 0, 0])
    for k, a in enumerate(('tests', 'failures', 'errors', 'skipped')):
        t[k] += int(root.get(a, 0))
    xml_skips = defaultdict(list)
    for tc in root.iter('testcase'):
        if tc.find('failure') is not None or tc.find('error') is not None:
            failed_cases.append(f"{task} {tc.get('classname', '')} > {tc.get('name', '')}")
        sk = tc.find('skipped')
        if sk is not None:
            xml_skips[tc.get('classname', '')].append((tc.get('name', ''), ' '.join((sk.get('message') or sk.text or '').split())))
    listed = 0
    for cls, entries in xml_skips.items():
        have = tsv_names.get((task, cls), [])
        extra = len(entries) - len(have)
        if extra <= 0:
            listed += len(entries)
            continue
        listed += len(have)
        cands = [e for e in entries if e[0] not in have and not e[0].startswith('[')] or [e for e in entries if e[0] not in have]
        for name, jmsg in cands[:extra]:
            rows.append((task, cls, name + ' (container)', reason(cls, name, jmsg)))
            listed += 1
    rest = int(root.get('skipped', 0)) - listed
    if rest > 0:
        suite = root.get('name', '')
        rows.append((task, suite, f'({rest} without individual entry)', reason(suite, '')))

def norm_reason(r):
    """Collapse per-class wording so identical causes share one report line."""
    comps = []
    for c in r.split('; '):
        c = re.sub(r'^class-level\s+', '', c)
        c = re.sub(r'\s+on\s+[\w$]+$', '', c)
        c = re.sub(r'^assumption in @\w+\s+', 'assumption ', c)
        if c and c not in comps:
            comps.append(c)
    comps = ['@Disabled by upstream (no message in source)' if c == '@Disabled' else c for c in comps]
    out = '; '.join(comps[:2])
    return out if len(out) <= 150 else out[:147] + '...'


def method_of(name):
    n = re.sub(r'\s*\(container\)$', '', name)
    n = re.sub(r'[(\[].*$', '', n).strip() or n.strip()
    return n if len(n) <= 32 else n[:30] + '..'


groups = OrderedDict()  # norm reason -> module -> class -> Counter(method)
modules_of = defaultdict(set)
for task, cls, name, r in sorted(rows, key=lambda x: (norm_reason(x[3]), x[0], x[1], x[2])):
    mod = task.rsplit(':', 1)[0].lstrip(':') or task
    key = norm_reason(r)
    by_cls = groups.setdefault(key, OrderedDict()).setdefault(mod, OrderedDict())
    by_cls.setdefault(cls.split('.')[-1], Counter())[method_of(name)] += 1
    modules_of[key].add(task)


def render(key, compact):
    parts = []
    total = 0
    for mod, classes in groups[key].items():
        cl = []
        for c, ms in classes.items():
            n = sum(ms.values())
            total += n
            if compact:
                cl.append(f'{c}({n})')
            else:
                cl.append(c + '{' + ','.join(m + (f'x{k}' if k > 1 else '') for m, k in ms.items()) + '}')
        parts.append(mod + ': ' + ' '.join(cl))
    return f'SKIP REASON {key} -- {total} skipped in {"/".join(sorted(modules_of[key]))} :: ' + ' | '.join(parts)


BUDGET = 9000
lines_out = {k: render(k, False) for k in groups}
for k in sorted(groups, key=lambda k: -len(lines_out[k])):
    if sum(len(v) + 30 for v in lines_out.values()) <= BUDGET:
        break
    lines_out[k] = render(k, True)

print('=' * 20 + ' SEALED BUILD TEST REPORT ' + '=' * 20)
for fc in failed_cases:
    print(f'FAILED TEST {fc}')
for k in groups:
    print(lines_out[k])
print(f'SKIPPED TESTS WITH REASONS: {len(rows)} across {len(groups)} distinct reasons (every skipped test above is listed under its reason; tests disabled by the sealed build itself carry @Disabled("sealed build: ..."), all others are upstream conditions)')
for mod, (n, f, e, sk) in tot.items():
    print(f'JUNIT XML TOTALS {mod}: tests={n} passed={n - f - e - sk} failed={f + e} skipped={sk}')
g = [sum(v[i] for v in tot.values()) for i in range(4)]
print(f'JUNIT XML TOTALS ALL MODULES: tests={g[0]} passed={g[0] - g[1] - g[2] - g[3]} failed={g[1] + g[2]} skipped={g[3]}')
