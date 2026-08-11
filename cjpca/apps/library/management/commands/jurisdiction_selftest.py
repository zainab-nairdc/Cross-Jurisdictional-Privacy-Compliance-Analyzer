"""Self-test for document-intelligence jurisdiction detection.

Guards the failure this was written for: the local model proposed "bahrain" for
a French GDPR privacy policy — a country that appears nowhere in the document.
Two things let that through. The model only ever saw the first 6000 chars, and
every France signal (Paris, France, GDPR, CNIL) sat past char 9600; and nothing
checked the model's answer against the text, so a confidently wrong country was
trusted while a blank one would have been questioned.

The offline checks stub the model, so they run anywhere and are the regression
net. --live additionally runs the real local model over a real document, which
needs Ollama up.

Run:  python manage.py jurisdiction_selftest
      python manage.py jurisdiction_selftest --live
"""

from django.core.management.base import BaseCommand

# A French/EU privacy policy whose country is named ONLY in the second half —
# the shape of document that produced the original bad suggestion.
_FRENCH_DOC = (
    "PRIVACY POLICY\n"
    "We recognize the importance of protecting the privacy of our customers. "
    "This policy details how we collect, use, disclose and protect personal "
    "information. Data is collected to provide financial services, comply with "
    "legal obligations, manage client relationships and prevent fraud. "
    + ("Personal data is retained only as long as necessary for the purposes for "
       "which it was collected, unless a longer retention period is required by "
       "law. Users may exercise access, rectification, deletion, limitation, "
       "portability and opposition rights at any time. ") * 30 +
    "\nWho is the Data controller?\n"
    "We - LinkCy, a SAS registered with the Paris Trade and Companies Register, "
    "whose registered office is located 42 Rue Boursault, 75017 Paris, France - "
    "are the controller of your Personal Data. In accordance with Article 37 of "
    "the GDPR, the institution has appointed a Data Protection Officer. "
    "The competent authority for data protection in France is the National "
    "Commission on Informatics and Liberty (CNIL).\n"
)

_BAHRAIN_DOC = (
    "Law No. 30 of 2018 with respect to Personal Data Protection. "
    "We, Hamad bin Isa Al Khalifa, King of the Kingdom of Bahrain. "
    "Issued by the Bahrain Personal Data Protection Authority."
)

_VIETNAM_DOC = (
    "This Decree on Personal Data Protection is issued by the Government of "
    "Vietnam and applies nationwide to all processing of personal data."
)


class Command(BaseCommand):
    help = 'Check that proposed jurisdictions are grounded in the document text.'

    def add_arguments(self, parser):
        parser.add_argument('--live', action='store_true',
                            help='also run the real local model (needs Ollama)')

    def handle(self, *args, **opts):
        from reasoning import doc_intel as di
        w = self.stdout.write
        results = []

        def check(label, got, want):
            ok = got == want
            results.append(ok)
            mark = self.style.SUCCESS('PASS') if ok else self.style.ERROR('FAIL')
            w(f'   [{mark}] {label}: got {got!r}, want {want!r}')

        def with_model(reply, text, **kw):
            """Run extraction against a stubbed model reply."""
            real = di._chat_json
            di._chat_json = lambda *a, **k: dict(reply)
            try:
                return di.extract_metadata(text, **kw)
            finally:
                di._chat_json = real

        w(self.style.MIGRATE_HEADING('\n1) The sampler reaches the country signals'))
        sample = di._meta_sample(_FRENCH_DOC)
        for kw in ('Paris', 'France', 'GDPR', 'CNIL'):
            check(f'{kw!r} visible to the model', kw in sample, True)

        w(self.style.MIGRATE_HEADING('2) Grounding accepts only what the text says'))
        for slug, want in (('france', True), ('eu', True),
                           ('bahrain', False), ('india', False), ('singapore', False)):
            check(f'{slug!r} grounded', di._is_grounded(slug, _FRENCH_DOC), want)

        w(self.style.MIGRATE_HEADING('3) A confident hallucination is rejected'))
        out = with_model(
            {'name': 'Privacy Policy', 'doc_type': 'policy', 'jurisdiction': 'bahrain',
             'confidence': 0.92},
            _FRENCH_DOC, full_scan=False)
        check('model says "bahrain" on a French doc', out['jurisdiction'] != 'bahrain', True)
        w(f'       -> resolved to {out["jurisdiction"]!r} instead')

        w(self.style.MIGRATE_HEADING('4) A grounded jurisdiction still survives'))
        out = with_model(
            {'name': 'Bahrain PDPL', 'doc_type': 'regulation', 'jurisdiction': 'bahrain',
             'confidence': 0.9},
            _BAHRAIN_DOC, full_scan=False)
        check('real Bahraini law', out['jurisdiction'], 'bahrain')

        w(self.style.MIGRATE_HEADING('5) An unlisted country is not clamped away'))
        out = with_model(
            {'name': 'PDPD', 'doc_type': 'regulation', 'jurisdiction': 'vietnam',
             'confidence': 0.9},
            _VIETNAM_DOC, full_scan=False)
        check('country absent from the hint table', out['jurisdiction'], 'vietnam')

        w(self.style.MIGRATE_HEADING('6) The sweep covers the whole document'))
        long_doc = _FRENCH_DOC + ('filler sentence to force multiple windows. ' * 2000)
        wins = di._windows(long_doc)
        check('more than one window', len(wins) > 1, True)
        covered = sum(len(x) for x in wins) - di._WINDOW_OVERLAP * (len(wins) - 1)
        check('every char reaches a window', covered >= len(long_doc.strip()), True)
        w(f'       {len(long_doc)} chars -> {len(wins)} windows')

        w(self.style.MIGRATE_HEADING('7) A per-window claim needs per-window evidence'))
        # The stub names bahrain for every window; no window contains it, so no
        # window may vote for it and the sweep must come back empty.
        real = di._chat_json
        di._chat_json = lambda *a, **k: {'jurisdiction': 'bahrain',
                                         'jurisdiction_evidence': 'invented',
                                         'key_topics': ['privacy']}
        try:
            scan = di.scan_document(_FRENCH_DOC)
        finally:
            di._chat_json = real
        check('ungrounded window votes discarded', scan.get('jurisdiction'), '')

        w(self.style.MIGRATE_HEADING('8) Progress covers every model call'))
        # A bar driven by sweep windows alone sat at 0 through the head pass and
        # hit 100% while structure inference was still running. The count has to
        # include every call, and the denominator has to be knowable up front.
        long_doc = _FRENCH_DOC + ('filler sentence to force several windows. ' * 2000)
        n_win = len(di._windows(long_doc))
        check('metadata_steps = head + windows',
              di.metadata_steps(long_doc), 1 + n_win)
        check('metadata_steps handles empty text', di.metadata_steps(''), 0)

        seen = []
        real = di._chat_json
        di._chat_json = lambda *a, **k: {'jurisdiction': '', 'key_topics': []}
        try:
            di.extract_metadata(long_doc, progress=lambda d, t, l='': seen.append((d, t)))
        finally:
            di._chat_json = real
        check('one progress event per model call', len(seen), 1 + n_win)
        check('denominator constant throughout',
              len({t for _, t in seen}), 1)
        check('counter starts at 1', seen[0][0] if seen else None, 1)
        check('counter ends at the total',
              seen[-1][0] if seen else None, seen[-1][1] if seen else None)
        check('monotonically increasing',
              all(b[0] == a[0] + 1 for a, b in zip(seen, seen[1:])), True)
        w(f'       {n_win} windows -> {len(seen)} events, total={seen[0][1] if seen else 0}')

        # A callback that throws must not take down an analysis that is working.
        di._chat_json = lambda *a, **k: {'jurisdiction': '', 'key_topics': []}
        try:
            boom = di.extract_metadata(_FRENCH_DOC,
                                       progress=lambda *a, **k: 1 / 0)
            check('a failing progress callback is survivable', isinstance(boom, dict), True)
        finally:
            di._chat_json = real

        w(self.style.MIGRATE_HEADING('9) Cancellation stops the work'))
        # A client that closes the upload must not leave the model grinding
        # through the rest of the document. Cancellation rides the progress
        # callback because that is the only point between model calls.
        calls = {'n': 0}
        real = di._chat_json

        def counting(*a, **k):
            calls['n'] += 1
            return {'jurisdiction': '', 'key_topics': []}

        def cancel_after_two(done, total, label=''):
            if done >= 2:
                raise di.AnalysisCancelled()

        di._chat_json = counting
        try:
            raised = False
            try:
                di.extract_metadata(long_doc, progress=cancel_after_two)
            except di.AnalysisCancelled:
                raised = True
        finally:
            di._chat_json = real
        check('AnalysisCancelled propagates out of the scan', raised, True)
        check('stopped early, did not read every window', calls['n'] < 1 + n_win, True)
        w(f'       stopped after {calls["n"]} of {1 + n_win} model calls')

        # An ordinary callback error must still be swallowed — only the
        # cancellation sentinel is allowed to abort an analysis.
        di._chat_json = lambda *a, **k: {'jurisdiction': '', 'key_topics': []}
        try:
            still = di.extract_metadata(_FRENCH_DOC,
                                        progress=lambda *a, **k: (_ for _ in ()).throw(ValueError('x')))
            check('a non-cancel callback error does NOT abort', isinstance(still, dict), True)
        finally:
            di._chat_json = real

        if opts['live']:
            w(self.style.MIGRATE_HEADING('10) LIVE — the real local model'))
            try:
                out = di.extract_metadata(_FRENCH_DOC)
                w(f'   jurisdiction : {out.get("jurisdiction")!r}')
                w(f'   authority    : {str(out.get("issuing_authority"))[:70]!r}')
                w(f'   scan         : {out.get("scan", {}).get("jurisdiction_votes")}')
                check('live model does not say bahrain',
                      out.get('jurisdiction') != 'bahrain', True)
            except Exception as exc:
                w(self.style.WARNING(f'   skipped — model unreachable ({exc})'))
        else:
            w('\n(pass --live to also run the real model against Ollama)')

        # ASCII only: this console is cp1252, and a '✓' here raises
        # UnicodeEncodeError the moment the output is piped or redirected.
        w(self.style.SUCCESS(f'\n[OK] JURISDICTION GROUNDING — {len(results)} checks passed')
          if all(results) else
          self.style.ERROR(f'\n[FAILED] {results.count(False)}/{len(results)} checks failed'))
