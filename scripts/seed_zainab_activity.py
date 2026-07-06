import os
import sys
import django
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cjpca'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cjpca.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.history.models import AuditLog

User = get_user_model()

user = User.objects.filter(username='zainab-bbk').first()
if not user:
    print('User "zainab-bbk" not found. Make sure the user was created.')
    sys.exit(0)

now = timezone.now()

events = [
    (timedelta(minutes=2),  'auth.login',        'analyst',
     '127.0.0.1',
     'zainab-bbk signed in',
     {}),
    (timedelta(minutes=4),  'auth.mfa_enrolled', 'analyst',
     '127.0.0.1',
     'zainab-bbk enrolled TOTP device',
     {'device': 'TOTPDevice', 'confirmed': True}),
    (timedelta(minutes=5),  'auth.login',        'analyst',
     '127.0.0.1',
     'zainab-bbk signed in (forced password change)',
     {'first_login': True}),
    (timedelta(minutes=12), 'document.upload',   'analyst',
     '127.0.0.1',
     'zainab-bbk uploaded regulation "Bahrain PDPL 2018"',
     {'document_title': 'Bahrain PDPL 2018', 'jurisdiction': 'BH'}),
    (timedelta(minutes=18), 'comparison.run',    'analyst',
     '127.0.0.1',
     'zainab-bbk started comparison PDPL vs DPDPA on Consent',
     {'topic': 'consent', 'reg_a': 'PDPL', 'reg_b': 'DPDPA'}),
    (timedelta(minutes=22), 'comparison.complete', 'analyst',
     '127.0.0.1',
     'zainab-bbk completed comparison (5 obligations)',
     {'obligations': 5, 'verified': 5}),
]

created = 0
for delta, event_type, role, ip, desc, detail in events:
    AuditLog.objects.create(
        event_type=event_type,
        user=user,
        user_role_at_time=role,
        ip_address=ip,
        timestamp=now - delta,
        description=desc,
        related_object_type='',
        related_object_id=None,
        change_detail=detail,
    )
    created += 1

print(f'Seeded {created} audit events for {user.username}.')
print('Refresh /history/ to see her activity at the top of the list.')
