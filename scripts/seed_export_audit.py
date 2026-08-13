import os
import sys
import django
import hashlib
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cjpca'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cjpca.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.history.audit import Actions
from apps.history.models import AuditLog

User = get_user_model()

# Seed under the same key the real export views emit. This script used to
# write 'export.create', which no production code path produces — so seeded
# demo rows and genuine export rows never showed up under the same filter,
# and /history/ looked like exports were being recorded when the only rows
# present were fake ones.
EVENT = Actions.EXPORT_DOWNLOADED

# Clear previously-seeded rows under either key so we don't double up. The
# has_key guard keeps this from touching real export rows, which never
# carry 'hash_prefix'.
deleted, _ = AuditLog.objects.filter(
    event_type__in=[EVENT, 'export.create'],
    change_detail__has_key='hash_prefix',
).delete()
print(f'Cleared {deleted} previously seeded export rows.')

# Exports happen after reviewer sign-off. Use a user with the literal
# username 'reviewer' so the audit log shows that label cleanly.
actor = User.objects.filter(username='reviewer').first()
if actor is None:
    actor = User.objects.create_user(
        username='reviewer',
        email='reviewer@bbk.bh',
        password='ChangeMe-Temp-2026',
    )
    actor.is_active = True
    actor.save()
    print('Created user "reviewer".')


def _hash(seed: str) -> str:
    return hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]


now = timezone.now()

exports = [
    (timedelta(minutes=5),
     'ComparisonRun', 100, 'PDF',
     'PDPL vs DPDPA — Lawful Basis (Run #100)'),
    (timedelta(minutes=8),
     'ComparisonRun', 100, 'XLSX',
     'PDPL vs DPDPA — Lawful Basis (Run #100)'),
    (timedelta(hours=1, minutes=15),
     'MappingAnalysis', 40, 'PDF',
     'BBK Data Subject Rights Procedure v1 — Kuwait CITRA'),
    (timedelta(hours=2, minutes=22),
     'ComparisonRun', 101, 'PDF',
     'Electronic Transactions Law 20/2014 vs DPDP Rules 2025'),
    (timedelta(days=1, hours=3),
     'MappingAnalysis', 38, 'XLSX',
     'BBK Customer Data Handling Procedure v1'),
]

created = 0
for delta, kind, oid, fmt, title in exports:
    hash_prefix = _hash(f'{kind}|{oid}|approved|export')
    AuditLog.objects.create(
        event_type=EVENT,
        user=actor,
        user_role_at_time='reviewer',
        ip_address='127.0.0.1',
        timestamp=now - delta,
        description=(f'{actor.username} exported {kind} #{oid} as '
                     f'{fmt} — audit hash {hash_prefix}'),
        related_object_type=f'apps.{kind.lower()}',
        related_object_id=oid,
        change_detail={
            'hash_prefix': hash_prefix,
            'format': fmt,
            'object_kind': kind,
            'object_id': oid,
            'title': title,
            'sha256_algorithm': 'SHA-256',
            'prefix_length': 16,
        },
    )
    created += 1

print(f'Seeded {created} {EVENT} AuditLog rows attached to '
      f'reviewer "{actor.username}".')
print('Refresh /history/ and use the Exports filter.')
