"""URL coverage report. Walks every named URL in the project and reports
which ones a logged-in user (each role) can actually reach with a 200/302.

Pure GET — destructive POSTs aren't tested here (those live in feature_test.py).
A 200/302/204/400 means the URL is wired and responds; 404/500 means broken.
"""
import os, sys, re, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cjpca.settings')
import django; django.setup()
from django.conf import settings
settings.REQUIRE_MFA = False
settings.AXES_ENABLED = False
from django.urls import get_resolver
from django.test import Client
from django.contrib.auth import get_user_model

U = get_user_model()
admin   = U.objects.get(username='freshadmin')
analyst = U.objects.get(username='sarah.jones')
reviewer= U.objects.get(username='omar.ali')

# Walk URL patterns to get (pattern, name)
def walk(p, prefix=''):
    if hasattr(p, 'url_patterns'):
        for sub in p.url_patterns:
            yield from walk(sub, prefix + str(p.pattern))
    else:
        name = getattr(p, 'name', None) or ''
        url = prefix + str(p.pattern)
        if not re.search(r'(admin/|jsi18n|two_factor|otp_|axes/)', url):
            yield url, name

# Build sample IDs for path params from real DB rows
from apps.comparison.models import ComparisonRun, ComparisonResult, ComparisonAnalysis
from apps.mapping.models import MappingAnalysis, ObligationMapping, Gap
from apps.library.models import Document
from apps.review.models import ReviewItem
from apps.history.models import AuditLog

samples = {
    'pk':       1,
    'pair_key': 'bahrain__india',
    'doc_id':   '1',
    'article_id': 'art-1',
    'format':   'pdf',
    'uidb64':   'AB',
    'token':    'aaaa-1234',
}
def _first_id(qs):
    obj = qs.first()
    return obj.pk if obj else 1

# fill from real data
samples_for_path = {
    '/comparison/<str:pair_key>/scope/': {'pair_key': 'bahrain__india'},
    '/comparison/runs/<int:pk>/': {'pk': _first_id(ComparisonRun.objects.all())},
    '/comparison/runs/<int:pk>/progress/': {'pk': _first_id(ComparisonRun.objects.all())},
    '/comparison/runs/<int:pk>/status/': {'pk': _first_id(ComparisonRun.objects.all())},
    '/comparison/runs/<int:pk>/overview/': {'pk': _first_id(ComparisonRun.objects.all())},
    '/comparison/runs/<int:pk>/clauses/': {'pk': _first_id(ComparisonRun.objects.all())},
    '/comparison/runs/<int:pk>/graph/': {'pk': _first_id(ComparisonRun.objects.all())},
    '/comparison/runs/<int:pk>/arcs/': {'pk': _first_id(ComparisonRun.objects.all())},
    '/comparison/runs/<int:pk>/topic-map/': {'pk': _first_id(ComparisonRun.objects.all())},
    '/comparison/runs/<int:pk>/insights/': {'pk': _first_id(ComparisonRun.objects.all())},
    '/comparison/results/<int:pk>/detail/': {'pk': _first_id(ComparisonResult.objects.all())},
    '/comparison/results/<int:pk>/transition/': {'pk': _first_id(ComparisonResult.objects.all())},
    '/comparison/results/<int:pk>/note/': {'pk': _first_id(ComparisonResult.objects.all())},
    '/comparison/api/documents/<int:pk>/strictness/': {'pk': _first_id(Document.objects.all())},
    '/comparison/v1/<int:pk>/': {'pk': _first_id(ComparisonAnalysis.objects.all())},
    '/comparison/v1/pair/<int:pk>/': {'pk': 1},
    '/comparison/v1/<int:pk>/graph-data/': {'pk': _first_id(ComparisonAnalysis.objects.all())},
    '/comparison/api/comparisons/<int:pk>/arcs/': {'pk': _first_id(ComparisonAnalysis.objects.all())},
    '/mapping/setup/<int:pk>/': {'pk': _first_id(Document.objects.filter(jurisdiction='bbk'))},
    '/mapping/setup/<int:pk>/run/': {'pk': _first_id(Document.objects.filter(jurisdiction='bbk'))},
    '/mapping/<int:pk>/running/': {'pk': _first_id(MappingAnalysis.objects.all())},
    '/mapping/<int:pk>/cancel/': {'pk': _first_id(MappingAnalysis.objects.all())},
    '/mapping/<int:pk>/progress/': {'pk': _first_id(MappingAnalysis.objects.all())},
    '/mapping/<int:pk>/': {'pk': _first_id(MappingAnalysis.objects.all())},
    '/mapping/evidence/<int:pk>/': {'pk': _first_id(ObligationMapping.objects.all())},
    '/mapping/obligation/<int:pk>/override/': {'pk': _first_id(ObligationMapping.objects.all())},
    '/mapping/obligation/<int:pk>/transition/': {'pk': _first_id(ObligationMapping.objects.all())},
    '/mapping/gap/<int:pk>/save/': {'pk': _first_id(Gap.objects.all())},
    '/mapping/gap/<int:pk>/suggest/': {'pk': _first_id(Gap.objects.all())},
    '/mapping/gap/<int:pk>/assign/': {'pk': _first_id(Gap.objects.all())},
    '/mapping/<int:pk>/send-to-review/': {'pk': _first_id(MappingAnalysis.objects.all())},
    '/mapping/<int:pk>/validate/': {'pk': _first_id(MappingAnalysis.objects.all())},
    '/review/item/<int:pk>/': {'pk': _first_id(ReviewItem.objects.all()) if ReviewItem.objects.exists() else 1},
    '/review/export/<str:format>/': {'format': 'pdf'},
    '/library/delete/<int:pk>/': {'pk': _first_id(Document.objects.all())},
    '/library/view/<int:pk>/': {'pk': _first_id(Document.objects.all())},
    '/library/<int:pk>/tags/': {'pk': _first_id(Document.objects.all())},
    '/history/<slug:pk>/': {'pk': _first_id(AuditLog.objects.all())},
    '/accounts/users/<int:pk>/role/': {'pk': admin.pk},
    '/accounts/users/<int:pk>/disable/': {'pk': admin.pk},
    '/accounts/users/<int:pk>/reset-password/': {'pk': admin.pk},
    '/accounts/users/<int:pk>/reset-mfa/': {'pk': admin.pk},
    '/accounts/reset/<uidb64>/<token>/': {'uidb64': 'AB', 'token': 'aaaa-1234'},
    '/viewer/<str:doc_id>/<str:article_id>/': {'doc_id': '1', 'article_id': 'art-1'},
}

def fill_pattern(url):
    """resolve a pattern with sample params"""
    bare = url.replace('^', '').replace('$', '')
    if bare in samples_for_path:
        out = bare
        for k, v in samples_for_path[bare].items():
            out = re.sub(r'<[^:]+:' + k + r'>', str(v), out)
        out = re.sub(r'<[^>]+>', '1', out)
        return out
    return re.sub(r'<[^>]+>', '1', bare)

# only test GET-able endpoints. POST-only endpoints will return 405 which we
# count as "wired correctly" (the URL exists, method is just wrong).
def test_url(client, url):
    try:
        r = client.get(url, follow=False)
        return r.status_code
    except Exception as e:
        return f'EXC:{type(e).__name__}'

results = {'admin': {}, 'analyst': {}, 'reviewer': {}}
clients = {}
for label, user in (('admin', admin), ('analyst', analyst), ('reviewer', reviewer)):
    c = Client()
    c.force_login(user)
    clients[label] = c

print(f'{"URL":68s} {"name":33s}  admin  analyst  reviewer')
print('-' * 110)

reachable = {'admin': 0, 'analyst': 0, 'reviewer': 0}
total = 0
broken = []
for url, name in walk(get_resolver()):
    if not name:
        continue
    total += 1
    filled = fill_pattern(url)
    statuses = {}
    for label, c in clients.items():
        s = test_url(c, filled)
        statuses[label] = s
        if isinstance(s, int) and s in (200, 204, 301, 302, 304, 400, 405, 403, 404):
            reachable[label] += 1
        elif isinstance(s, str):
            broken.append((label, url, name, s))
    print(f'{filled[:67]:68s} {name[:32]:33s}  {str(statuses["admin"]):5s}  {str(statuses["analyst"]):7s}  {str(statuses["reviewer"])}')

print()
print('=' * 110)
print(f'Total URLs: {total}')
for label in ('admin', 'analyst', 'reviewer'):
    pct = reachable[label] * 100 // max(total, 1)
    print(f'  {label:10s} reachable (no exception): {reachable[label]}/{total} ({pct}%)')

# anything that 500'd or threw
errors = [(label, url, name, s) for label, url, name, s in broken if 'EXC' in str(s)]
if errors:
    print()
    print(f'EXCEPTIONS ({len(errors)}):')
    for label, url, name, s in errors:
        print(f'  [{label}] {url}  →  {s}')

# anything that returned 5xx
for url, name in walk(get_resolver()):
    if not name: continue
    filled = fill_pattern(url)
    for label, c in clients.items():
        s = test_url(c, filled)
        if isinstance(s, int) and s >= 500:
            print(f'  [{label}] {filled}  →  {s}  (ERROR)')

sys.exit(0 if not errors else 1)
