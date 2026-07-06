import os
import sys
import django

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cjpca'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cjpca.settings')
django.setup()

from django.utils import timezone

from apps.comparison.models import ComparisonResult, AuditEvent

results = list(ComparisonResult.objects.filter(lifecycle=ComparisonResult.DRAFT)[:40])
if not results:
    results = list(ComparisonResult.objects.all()[:40])

if not results:
    print("No ComparisonResult rows exist. Run a comparison first.")
    sys.exit(0)

approved_count = 0
rejected_count = 0
for i, r in enumerate(results):
    if i % 12 == 0:
        r.lifecycle = ComparisonResult.REJECTED
        rejected_count += 1
        action = 'rejected'
    else:
        r.lifecycle = ComparisonResult.APPROVED
        approved_count += 1
        action = 'approved'
    r.save(update_fields=['lifecycle'])
    AuditEvent.objects.create(
        result=r, actor='noor', action=action,
        from_lifecycle=ComparisonResult.DRAFT, to_lifecycle=r.lifecycle,
        timestamp=timezone.now(),
    )

total = approved_count + rejected_count
print(f"Seeded {approved_count} approved + {rejected_count} rejected = {total} reviewed.")
print(f"Expected AI Accuracy ~= {round(approved_count / total * 100)}%. Refresh /analytics/")
