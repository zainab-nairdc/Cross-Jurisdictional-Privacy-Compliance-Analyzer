import os
import sys
import django
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cjpca'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cjpca.settings')
django.setup()

from django.utils import timezone

from apps.history.models import AuditLog


denials = [
    ('203.0.113.45',   'RU', 'Russia',         'GET /accounts/login/'),
    ('198.51.100.22',  'CN', 'China',          'GET /'),
    ('192.0.2.88',     'KP', 'North Korea',    'POST /accounts/login/'),
    ('203.0.113.91',   'IR', 'Iran',           'GET /api/copilot/message/'),
    ('198.51.100.7',   'RU', 'Russia',         'GET /comparison/'),
]

now = timezone.now()
created = 0
for i, (ip, code, country, path) in enumerate(denials):
    AuditLog.objects.create(
        event_type='geofence.deny',
        user=None,
        user_role_at_time='',
        ip_address=ip,
        timestamp=now - timedelta(hours=i, minutes=i * 7),
        description=f'GeoFence blocked request from {country} ({code}) to {path}',
        related_object_type='',
        related_object_id=None,
        change_detail={
            'country_code': code,
            'country_name': country,
            'ip': ip,
            'path': path,
            'allowlist': ['BH', 'IN', 'KW'],
            'reason': 'country_not_in_allowlist',
        },
    )
    created += 1

print(f'Seeded {created} geofence.deny AuditLog rows.')
print('Refresh /history/?type=geofence.deny to see the filtered view.')
