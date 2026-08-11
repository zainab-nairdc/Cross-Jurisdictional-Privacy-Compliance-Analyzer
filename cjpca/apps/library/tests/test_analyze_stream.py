"""Tests for the streamed analyze response.

These cover failures found reviewing the streaming implementation, not the happy
path (which the jurisdiction_selftest and a real upload exercise):

  - a client that disconnects mid-analysis used to leave the worker thread
    running the remaining model calls — minutes of GPU time for an upload
    nobody was waiting for;
  - a worker that died without reporting produced an empty *result* line, which
    the wizard reads as "analysis succeeded, found nothing" and walks the user
    straight on to indexing;
  - the non-streaming error responses (400s) had to keep working unchanged once
    the success path became a stream.

`_run_doc_intel` is patched throughout so nothing here needs Ollama.
"""

import json
import tempfile
import threading
import time

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, TransactionTestCase, override_settings

from apps.library import views as library_views
from apps.library.models import Document

_MEDIA = tempfile.mkdtemp(prefix='cjpca-test-media-')


def _lines(response):
    """Every JSON object in a streamed response, in order."""
    out = []
    for chunk in response.streaming_content:
        for line in chunk.decode('utf-8').splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


@override_settings(MEDIA_ROOT=_MEDIA)
class AnalyzeStreamTests(TestCase):

    def _upload(self, name='policy.txt', body=b'A short internal policy.'):
        return self.client.post('/library/analyze/', {
            'file': SimpleUploadedFile(name, body, content_type='text/plain')})

    # ---- non-streaming error responses still behave ------------------------

    def test_missing_file_is_a_plain_400(self):
        r = self.client.post('/library/analyze/', {})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(getattr(r, 'streaming', False))

    def test_legacy_doc_rejected_as_json_400(self):
        r = self.client.post('/library/analyze/', {
            'file': SimpleUploadedFile('old.doc', b'x',
                                       content_type='application/msword')})
        self.assertEqual(r.status_code, 400)
        self.assertIn('error', json.loads(r.content.decode()))

    # ---- failures on the streamed path -------------------------------------

    def test_failure_before_any_progress_yields_an_error_line(self):
        def blow_up(*a, **kw):
            raise RuntimeError('boom early')

        with self._patched(blow_up):
            lines = _lines(self._upload())

        self.assertEqual([l for l in lines if l['type'] == 'progress'], [])
        self.assertEqual(lines[-1]['type'], 'error')
        self.assertEqual(Document.objects.order_by('-pk').first().status,
                         Document.FAILED)

    def test_failure_after_progress_still_ends_in_an_error(self):
        def half_way(pdf_path, metadata_only=False, progress=None):
            for i in (1, 2, 3):
                progress(i, 9, f'step {i}')
            raise RuntimeError('boom midway')

        with self._patched(half_way):
            lines = _lines(self._upload())

        self.assertEqual(len([l for l in lines if l['type'] == 'progress']), 3)
        self.assertEqual(lines[-1]['type'], 'error')
        # The half-finished run must not also emit a result the wizard would act on.
        self.assertEqual([l for l in lines if l['type'] == 'result'], [])

    def test_worker_dying_without_a_result_is_an_error_not_an_empty_success(self):
        # BaseException rather than Exception: the worker exits in a way it
        # cannot report. This previously fell through to the default empty
        # result and looked like a successful, empty analysis.
        def vanish(*a, **kw):
            raise BaseException('hard exit')

        with self._patched(vanish):
            lines = _lines(self._upload())

        self.assertEqual(lines[-1]['type'], 'error')
        self.assertEqual([l for l in lines if l['type'] == 'result'], [])

    # ---- client disconnect --------------------------------------------------

    def test_disconnect_stops_the_worker(self):
        calls = {'n': 0}
        started = threading.Event()

        def slow(pdf_path, metadata_only=False, progress=None):
            for i in range(1, 40):
                calls['n'] += 1
                progress(i, 40, f'step {i}')     # raises once cancelled
                started.set()
                time.sleep(0.15)
            return {}, ''

        with self._patched(slow):
            r = self._upload()
            seen = 0
            for chunk in r.streaming_content:
                seen += len([l for l in chunk.decode().splitlines() if l.strip()])
                if seen >= 2:
                    break
            r.close()                    # what Django does when the client goes
            at_close = calls['n']
            time.sleep(1.2)              # room for ~8 more steps if uncancelled

        self.assertLessEqual(calls['n'] - at_close, 1,
                             'worker kept running after the client disconnected')
        self.assertEqual(
            [t for t in threading.enumerate() if t.name.startswith('doc-intel-')],
            [], 'analysis thread outlived the request')

    # ---- proxy header -------------------------------------------------------

    def test_streaming_headers_survive(self):
        with self._patched(lambda *a, **kw: ({}, '')):
            r = self._upload()
            self.assertTrue(r.streaming)
            self.assertEqual(r['Content-Type'], 'application/x-ndjson')
            # Without this a proxy may buffer the body and defeat the streaming.
            self.assertEqual(r['X-Accel-Buffering'], 'no')
            _lines(r)

    # ---- helper -------------------------------------------------------------

    def _patched(self, fn):
        """Swap _run_doc_intel for the duration of a block."""
        from contextlib import contextmanager

        @contextmanager
        def ctx():
            original = library_views._run_doc_intel
            library_views._run_doc_intel = fn
            try:
                yield
            finally:
                library_views._run_doc_intel = original

        return ctx()


@override_settings(MEDIA_ROOT=_MEDIA)
class AnalyzeConcurrencyTests(TransactionTestCase):
    """Two analyses at once must not see each other's counters.

    TransactionTestCase, not TestCase: TestCase holds every test open inside one
    transaction, which a thread using its own connection cannot join — the
    request threads fail before reaching the view and the test proves nothing.
    """

    def test_two_analyses_do_not_share_progress_state(self):
        def counted(pdf_path, metadata_only=False, progress=None):
            for i in range(1, 6):
                progress(i, 5, f'step {i}')
                time.sleep(0.02)
            return {}, ''

        results, errors = {}, []

        def run(tag):
            try:
                r = Client().post('/library/analyze/', {
                    'file': SimpleUploadedFile('p.txt', b'x',
                                               content_type='text/plain')})
                results[tag] = [l for l in _lines(r) if l['type'] == 'progress']
            except Exception as exc:          # surface it — a silent thread
                errors.append(f'{tag}: {exc!r}')   # failure would pass vacuously

        original = library_views._run_doc_intel
        library_views._run_doc_intel = counted
        try:
            threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
        finally:
            library_views._run_doc_intel = original

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        for tag, events in results.items():
            # Each stream counts 1..5 on its own; a shared queue would interleave.
            self.assertEqual([e['done'] for e in events], [1, 2, 3, 4, 5],
                             f'stream {tag} saw another analysis\'s counts')
