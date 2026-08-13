"""Approved comparison runs — identity, source snapshots, and approval.

An approved run is a VERSIONED COMPLIANCE ASSESSMENT, not a cached response.
Everything here follows from that distinction:

  - it records exactly which document versions were compared, because an
    approved result is only valid relative to its sources;
  - it groups versions of the same question so v1 stays available for audit
    when v2 supersedes it;
  - it refuses to describe anything as current unless a real snapshot proves
    it, because presenting a stale assessment as current is the single most
    damaging thing this feature could do.

Two identifiers, doing different jobs:

  assessment_key      the QUESTION. Built from the version FAMILY of each
                      document, so re-running after a regulation is updated
                      produces a new VERSION of the same assessment rather
                      than an unrelated row.
  source_fingerprint  the ANSWER'S BASIS. Built from the specific document
                      versions and their content hashes, so it changes the
                      moment a source does. This is what later phases will
                      compare to detect drift.

Orientation is part of both. A→B and B→A are different assessments, never two
views of one — the narrative depends on which regulation is the baseline.
"""

from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger(__name__)


# Snapshots written before this revision used a different field set. Recorded
# in the snapshot so a future reader can tell what it is looking at.
SNAPSHOT_SCHEMA = 1


def _sha(payload) -> str:
    """Stable hash of a JSON-serialisable structure.

    sort_keys so dictionary ordering can never change the identity of an
    otherwise identical assessment.
    """
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()


def _scope_signature(topics, scope_mode: str = '') -> dict:
    """Canonical description of what the comparison was asked to cover."""
    clean = sorted({str(t).strip() for t in (topics or []) if str(t).strip()})
    return {'mode': 'topics' if clean else (scope_mode or 'full'),
            'topics': clean}


def document_descriptor(doc) -> dict:
    """The identifying facts about one document at a point in time.

    `content_hash` is the load-bearing field: it is the sha256 of the file
    bytes, so it changes when the document is re-uploaded even if the name,
    version string and pk all stay the same. Name and version are recorded for
    the human reading the audit record, not for the machine comparing it.
    """
    if doc is None:
        return {}
    try:
        family_root = doc.family_root_id
    except Exception:
        family_root = doc.pk
    return {
        'pk':              doc.pk,
        'document_id':     doc.document_id or '',
        'name':            doc.name,
        'version':         doc.version or '',
        'jurisdiction':    doc.jurisdiction or '',
        'content_hash':    doc.content_hash or '',
        'chunk_doc_title': doc.chunk_doc_title or '',
        'family_root':     family_root,
        'superseded':      bool(doc.superseded),
    }


def build_assessment_key(reg_a, reg_b, *, topics=None, scope_mode: str = '') -> str:
    """Stable identity of the comparison QUESTION.

    Uses each document's family root, so every version of the same law maps to
    the same assessment. Includes orientation and scope: a reversed comparison
    is a different question, and a topic-scoped run must not present itself as
    a newer version of a full-scope one.
    """
    try:
        root_a = reg_a.family_root_id
        root_b = reg_b.family_root_id
    except Exception:
        root_a, root_b = getattr(reg_a, 'pk', None), getattr(reg_b, 'pk', None)
    return _sha({
        'v': SNAPSHOT_SCHEMA,
        'a': root_a,
        'b': root_b,
        'orientation': 'a_to_b',
        'scope': _scope_signature(topics, scope_mode),
    })[:40]


def build_source_snapshot(reg_a, reg_b, *, topics=None, scope_mode: str = '',
                          include_orphans: bool = False,
                          model_version: str = '', prompt_version: str = '',
                          taxonomy_version: str = '') -> dict:
    """The immutable record of what a run was based on.

    Written once at run creation. Never updated — the moment it is rewritten
    it stops being evidence of what the assessment was actually based on and
    becomes a description of the present, which is the opposite of its purpose.
    """
    if not taxonomy_version:
        try:
            from reasoning.taxonomy import TAXONOMY_VERSION
            taxonomy_version = TAXONOMY_VERSION
        except Exception:
            taxonomy_version = ''
    return {
        'schema':      SNAPSHOT_SCHEMA,
        'orientation': 'a_to_b',
        'reg_a':       document_descriptor(reg_a),
        'reg_b':       document_descriptor(reg_b),
        'scope':       {**_scope_signature(topics, scope_mode),
                        'include_orphans': bool(include_orphans)},
        'engine':      {'model': model_version, 'prompt': prompt_version,
                        'taxonomy': taxonomy_version},
    }


def fingerprint_snapshot(snapshot: dict) -> str:
    """sha256 over the MATERIAL subset of a snapshot.

    Material = the documents (identity + content hash), the orientation, and
    the scope. Everything that determines whether an answer still stands.

    The engine block is deliberately EXCLUDED. A human approved this output; a
    later model or prompt change does not retroactively invalidate their
    judgement, and folding it in would mark every approved assessment stale on
    the next model bump — which would make approval worthless.
    """
    if not snapshot:
        return ''
    a, b = snapshot.get('reg_a') or {}, snapshot.get('reg_b') or {}
    material = {
        'v': snapshot.get('schema', SNAPSHOT_SCHEMA),
        'orientation': snapshot.get('orientation', 'a_to_b'),
        'a': {'pk': a.get('pk'), 'document_id': a.get('document_id', ''),
              'content_hash': a.get('content_hash', '')},
        'b': {'pk': b.get('pk'), 'document_id': b.get('document_id', ''),
              'content_hash': b.get('content_hash', '')},
        'scope': {'mode': (snapshot.get('scope') or {}).get('mode', 'full'),
                  'topics': (snapshot.get('scope') or {}).get('topics', [])},
    }
    return _sha(material)


def stamp_run(run, reg_a, reg_b, *, topics=None, scope_mode: str = '',
              include_orphans: bool = False, model_version: str = '',
              prompt_version: str = '', save: bool = True) -> dict:
    """Attach identity + snapshot + fingerprint to a freshly created run.

    Metadata only: this records what a run WAS, and changes nothing about how
    comparisons execute. A run that is never stamped simply cannot be
    established as current later — which is the honest outcome, not a failure.
    """
    snapshot = build_source_snapshot(
        reg_a, reg_b, topics=topics, scope_mode=scope_mode,
        include_orphans=include_orphans, model_version=model_version,
        prompt_version=prompt_version)

    run.source_snapshot     = snapshot
    run.source_fingerprint  = fingerprint_snapshot(snapshot)
    run.assessment_key      = build_assessment_key(
        reg_a, reg_b, topics=topics, scope_mode=scope_mode)
    run.model_version       = model_version
    run.prompt_version      = prompt_version
    run.taxonomy_version    = snapshot['engine']['taxonomy']

    # Currency is ASSESSED at stamp time, not assumed.
    #
    # Capturing a snapshot does not by itself make a run verifiable: if a
    # source document has no content_hash, the snapshot records an empty hash
    # and nothing will ever be able to prove the document unchanged. Declaring
    # such a run `current` here would be the same false-current the assessment
    # logic exists to prevent — and it would disagree with the very first
    # re-check, breaking idempotency.
    #
    # At this instant the snapshot mirrors the live documents exactly, so the
    # assessment reduces to "is there evidence to compare?".
    verdict = assess_currency(run)
    run.currency_state  = verdict.state
    run.outdated_reason = verdict.reason[:300] if verdict.state != 'current' else ''
    if save:
        run.save(update_fields=[
            'source_snapshot', 'source_fingerprint', 'assessment_key',
            'model_version', 'prompt_version', 'taxonomy_version',
            'currency_state', 'outdated_reason'])
    return snapshot


# ── currency detection ──────────────────────────────────────────────────────
#
# THE INVARIANT THIS SECTION EXISTS TO HOLD:
#
#     Currency is established by POSITIVE EVIDENCE OF SAMENESS,
#     never by the absence of evidence of change.
#
# The tempting implementation — recompute the fingerprint, compare, call it
# current if equal — is wrong, and wrong in the dangerous direction. Most
# documents in this corpus have no content_hash (it is written only by the
# upload wizard's finalize step), so an empty hash compared against an empty
# hash matches, and a fingerprint built from two empty hashes matches too. That
# would report "Current" for an assessment nothing can actually vouch for.
#
# So a field that cannot be compared makes its side UNVERIFIABLE, which makes
# the run UNKNOWN. Only a side proven unchanged counts toward CURRENT.
#
# The fingerprint is computed and recorded as a diagnostic, but never allowed
# to short-circuit the field walk: with small numbers of approved runs, an
# auditable answer is worth more than a fast one.

from dataclasses import dataclass, field as _field

# Per-side outcomes.
SIDE_VERIFIED     = 'verified'      # proven to still match the stamped state
SIDE_CHANGED      = 'changed'       # proven to differ
SIDE_UNVERIFIABLE = 'unverifiable'  # cannot be established either way


@dataclass(frozen=True)
class SideVerdict:
    side:   str          # 'A' or 'B'
    state:  str          # SIDE_*
    name:   str          # document name, for the human-readable reason
    reason: str = ''

    @property
    def changed(self) -> bool:
        return self.state == SIDE_CHANGED

    @property
    def verified(self) -> bool:
        return self.state == SIDE_VERIFIED


@dataclass(frozen=True)
class CurrencyVerdict:
    """What a currency check concluded, and why.

    Pure data. Producing one writes nothing — see apply_currency().
    """
    state:  str                 # ComparisonRun.CURRENT | OUTDATED | UNKNOWN
    reason: str = ''            # '' when current
    sides:  tuple = _field(default_factory=tuple)
    fingerprint_matched: bool = False
    live_fingerprint: str = ''

    @property
    def is_current(self) -> bool:
        return self.state == 'current'

    @property
    def changed_sides(self) -> list:
        return [s for s in self.sides if s.changed]


def _assess_side(label: str, snapshot: dict, live) -> SideVerdict:
    """Compare one side's stamped state against the live document.

    Ordered so the strongest and most human-meaningful signal wins: an
    explicitly superseded document is reported as superseded even if its bytes
    happen to be unchanged.

    The free-form `version` string is deliberately NOT a signal. It holds
    '1.0', '42/2020' and 'DBR.AML.BC.No.81/14.01.001/2015-16' across this
    corpus, and a change to it alone is not evidence of anything.
    """
    name = (snapshot.get('name') or getattr(live, 'name', '') or f'Regulation {label}')

    if live is None:
        return SideVerdict(label, SIDE_CHANGED, name,
                           f'{name} is no longer in the library')

    # Identity. The run's FK points at the document, so a mismatch means the
    # snapshot was taken against a different row entirely.
    snap_pk = snapshot.get('pk')
    if snap_pk is not None and snap_pk != live.pk:
        return SideVerdict(label, SIDE_CHANGED, name,
                           f'{name} has been replaced by a different document')

    # Supersession — the document itself declaring it has been replaced. Set
    # only through Document.supersede_with(), a single choke point, which makes
    # it the most trustworthy signal available.
    if not snapshot.get('superseded') and getattr(live, 'superseded', False):
        return SideVerdict(label, SIDE_CHANGED, name,
                           f'{name} has been superseded by a newer version')

    # Explicit lineage. Normally set alongside `superseded`, so this is a
    # backstop for a version_of link established outside supersede_with().
    #
    # If the snapshot recorded the document as ALREADY superseded, the run was
    # knowingly made against an old version and a newer one existing is not
    # news. Otherwise a newer version is treated as a change — which may be a
    # false positive if that version already existed when the run was stamped
    # (the snapshot does not record it). False OUTDATED is the safe direction:
    # it prompts a re-run rather than vouching for stale analysis.
    if not snapshot.get('superseded'):
        try:
            if live.newer_versions.exists():
                return SideVerdict(label, SIDE_CHANGED, name,
                                   f'a newer version of {name} exists')
        except Exception:
            pass

    # Content. THE EMPTY-HASH RULE: an absent hash on either side proves
    # nothing, so the side is unverifiable rather than matching.
    snap_hash = (snapshot.get('content_hash') or '').strip()
    live_hash = (getattr(live, 'content_hash', '') or '').strip()
    if not snap_hash and not live_hash:
        return SideVerdict(label, SIDE_UNVERIFIABLE, name,
                           f'{name} has no content hash on either side')
    if not snap_hash:
        return SideVerdict(label, SIDE_UNVERIFIABLE, name,
                           f'{name} had no content hash when the run was stamped')
    if not live_hash:
        return SideVerdict(label, SIDE_UNVERIFIABLE, name,
                           f'{name} no longer has a content hash to compare')
    if snap_hash != live_hash:
        return SideVerdict(label, SIDE_CHANGED, name,
                           f'{name} content has changed')

    return SideVerdict(label, SIDE_VERIFIED, name)


def assess_currency(run) -> CurrencyVerdict:
    """Is this run still based on the sources it was stamped against?

    PURE — reads the run and its documents, writes nothing. Never raises.

    Deliberately blind to model, prompt and taxonomy versions: a human approved
    an OUTPUT, and re-pointing the engine does not change what the analysis was
    based on.

    Reads `run.reg_a` / `run.reg_b`, which Django caches on the instance. Pass
    a freshly loaded run — every caller here does — or a document mutated after
    the run was loaded will be assessed against the stale copy still attached
    to it.
    """
    from apps.comparison.models import ComparisonRun

    # No verified capture — legacy runs, backfilled snapshots, stamping
    # failures. Their currency is not merely unchecked, it is unknowable, and
    # no amount of comparing today's documents can establish it.
    if not run.currency_is_verifiable:
        return CurrencyVerdict(
            ComparisonRun.UNKNOWN,
            'This assessment predates source-version tracking, so the document '
            'versions it was based on were not recorded.')

    snapshot = run.source_snapshot or {}
    sides = (
        _assess_side('A', snapshot.get('reg_a') or {}, run.reg_a),
        _assess_side('B', snapshot.get('reg_b') or {}, run.reg_b),
    )

    # Recorded for audit; NEVER used to short-circuit. Two empty hashes
    # fingerprint identically, so a match here is not proof of sameness.
    live_fp = ''
    try:
        live_fp = fingerprint_snapshot(build_source_snapshot(
            run.reg_a, run.reg_b,
            topics=(snapshot.get('scope') or {}).get('topics') or run.topics,
            scope_mode=(snapshot.get('scope') or {}).get('mode', '')))
    except Exception:
        logger.exception('live fingerprint failed for run %s', run.pk)
    matched = bool(live_fp) and live_fp == run.source_fingerprint

    changed = [s for s in sides if s.changed]
    if changed:
        return CurrencyVerdict(
            ComparisonRun.OUTDATED,
            '; '.join(s.reason for s in changed),
            sides, matched, live_fp)

    unverifiable = [s for s in sides if s.state == SIDE_UNVERIFIABLE]
    if unverifiable:
        return CurrencyVerdict(
            ComparisonRun.UNKNOWN,
            '; '.join(s.reason for s in unverifiable),
            sides, matched, live_fp)

    return CurrencyVerdict(ComparisonRun.CURRENT, '', sides, matched, live_fp)


def apply_currency(run, verdict=None, *, save: bool = True) -> CurrencyVerdict:
    """Persist a currency verdict onto the run.

    Writes THREE fields and nothing else: `currency_state`, `outdated_reason`,
    `currency_checked_at`. It never touches `lifecycle`, `approved_at`,
    results, or the feedback loop — currency is an observation about sources,
    not a review decision.

    `outdated_reason` is cleared whenever the state is not outdated: a stale
    reason sitting next to a "Current" badge is worse than no reason at all.

    Stateless and idempotent — a document reverted to its stamped state moves
    the run back to `current`, because a sticky verdict would outlive the fact.
    """
    from django.utils import timezone

    if verdict is None:
        verdict = assess_currency(run)

    run.currency_state      = verdict.state
    run.outdated_reason     = verdict.reason[:300] if verdict.state != 'current' else ''
    run.currency_checked_at = timezone.now()
    if save:
        run.save(update_fields=['currency_state', 'outdated_reason',
                                'currency_checked_at'])
    return verdict


def refresh_currency_for(runs, *, save: bool = True) -> dict:
    """Re-check a collection of runs. Returns a count per resulting state.

    One run failing must not stop the rest: a currency check is diagnostic, and
    a partial refresh is more useful than none.
    """
    from apps.comparison.models import ComparisonRun

    counts = {ComparisonRun.CURRENT: 0, ComparisonRun.OUTDATED: 0,
              ComparisonRun.UNKNOWN: 0, 'errors': 0, 'changed': 0}
    for run in runs:
        before = run.currency_state
        try:
            verdict = apply_currency(run, save=save)
        except Exception:
            logger.exception('currency check failed for run %s', run.pk)
            counts['errors'] += 1
            continue
        counts[verdict.state] = counts.get(verdict.state, 0) + 1
        if verdict.state != before:
            counts['changed'] += 1
    return counts


def invalidate_runs_for_document(document, *, save: bool = True) -> dict:
    """Re-check every run that used `document`, after that document changed.

    The PUSH path: called when a document is superseded, so dependent
    assessments are marked immediately instead of waiting for someone to open
    the Approved Runs page.

    It defines NO currency logic of its own. It selects the affected runs and
    hands each to `apply_currency()`, so the push path and the pull path can
    never disagree about what "current" means — there is one definition, in
    `assess_currency()`, and this is a trigger for it.

    Selection is by FK, so only runs that genuinely reference this document are
    touched. Orientation falls out of that naturally: a document used as A
    matches `reg_a`, as B matches `reg_b`, and `assess_currency` names whichever
    side actually changed.

    Idempotent, because the assessment it delegates to is: re-running it
    recomputes the same verdict from the same facts and rewrites the same
    reason. A run whose snapshot was never verifiable stays `unknown` rather
    than being forced to `outdated` — `unknown` already blocks reuse, and
    overriding the assessment here would fork the definition of currency.
    """
    from django.db.models import Q
    from apps.comparison.models import ComparisonRun

    if document is None or not getattr(document, 'pk', None):
        return {'errors': 0, 'changed': 0}
    runs = (ComparisonRun.objects
            .filter(Q(reg_a=document) | Q(reg_b=document))
            .select_related('reg_a', 'reg_b'))
    return refresh_currency_for(runs, save=save)


# ── reuse ───────────────────────────────────────────────────────────────────
#
# Reuse means: an analyst asked for a comparison that an approved assessment
# already answers, so we OFFER that assessment instead of spending an LLM run
# on it. Offering is the limit of what happens automatically — a person always
# chooses, and "re-run anyway" is always available.
#
# `is_reusable` is the ONLY eligibility rule (approved AND current AND
# currency-verifiable). Nothing here re-derives, relaxes or shadows it; the
# functions below add the two questions it does not answer:
#
#     is this assessment about the SAME comparison?   (documents + orientation)
#     does it cover the SAME scope?                   (verify_scope_coverage)
#
# Both are exact-match by design. A near-miss is not a reuse candidate.

SCOPE_MATCH        = 'match'
SCOPE_MODE_DIFFERS = 'mode_differs'
SCOPE_TOPICS_DIFFER = 'topics_differ'
SCOPE_UNVERIFIABLE = 'unverifiable'


def verify_scope_coverage(run, requested_topics=None, scope_mode: str = ''):
    """Does `run` cover EXACTLY the requested scope? Returns (bool, code, detail).

    EXACT MATCHING ONLY. A full-scope assessment is NOT treated as covering a
    narrower request, even though it intuitively "contains" it. Proving that
    would mean inferring coverage from per-result evidence, and that evidence
    is incomplete in this corpus — asserting coverage from partial data is how
    a reused assessment ends up silently missing an obligation the analyst
    asked about. Cross-scope reuse is deliberately left for a later decision.

    Scope is read from the run's OWN persisted snapshot, not from `run.topics`:
    the snapshot is the immutable record of what the run was actually asked to
    cover. A run whose snapshot carries no scope block is unverifiable and
    therefore not reusable — silence is not evidence of a full-scope run.

    Normalisation is shared with the identity helpers via `_scope_signature`,
    so topic ORDER and duplicates never change the answer, and nothing
    persisted is modified.

    PURE — reads only, never raises.
    """
    snapshot = getattr(run, 'source_snapshot', None) or {}
    stored = snapshot.get('scope')
    if not isinstance(stored, dict) or 'mode' not in stored:
        return False, SCOPE_UNVERIFIABLE, (
            'the run does not record what scope it was asked to cover')

    requested = _scope_signature(requested_topics, scope_mode)
    stored_sig = _scope_signature(stored.get('topics'), stored.get('mode', ''))

    if requested['mode'] != stored_sig['mode']:
        return False, SCOPE_MODE_DIFFERS, (
            f'the approved assessment is {stored_sig["mode"]}-scope and the '
            f'request is {requested["mode"]}-scope')
    if requested['topics'] != stored_sig['topics']:
        return False, SCOPE_TOPICS_DIFFER, (
            'the approved assessment covers a different set of topics')
    return True, SCOPE_MATCH, ''


def find_reusable_run(reg_a, reg_b, topics=None, scope_mode: str = ''):
    """The approved assessment that already answers this request, or None.

    PURE — no writes, no LLM, no mutation of any run or its currency.

    Every one of these must hold, and each is checked explicitly:

      1. `is_reusable` — approved AND current AND currency-verifiable. The
         single gate, evaluated as the property, never re-implemented.
      2. same assessment identity — `assessment_key` encodes both documents'
         version FAMILY, the orientation and the scope, so a reversed
         comparison can never match.
      3. same ACTUAL documents — the key is family-based, so two versions of
         the same law share it. The requested version must be the one that was
         compared, not merely a relative of it.
      4. exact scope coverage — see verify_scope_coverage().

    When several candidates qualify, the NEWEST approved version wins:
    ordered by version_no, then approved_at, then pk, all descending. Ties
    cannot occur on pk, so the choice is deterministic.
    """
    from apps.comparison.models import ComparisonRun

    if reg_a is None or reg_b is None:
        return None
    if not getattr(reg_a, 'pk', None) or not getattr(reg_b, 'pk', None):
        return None

    try:
        key = build_assessment_key(reg_a, reg_b, topics=topics,
                                   scope_mode=scope_mode)
        candidates = list(ComparisonRun.objects
                          .filter(assessment_key=key,
                                  lifecycle=ComparisonRun.APPROVED,
                                  reg_a=reg_a, reg_b=reg_b)
                          .select_related('reg_a', 'reg_b', 'approved_by')
                          .order_by('-version_no', '-approved_at', '-pk'))
    except Exception:
        logger.exception('reuse lookup failed for %s vs %s',
                         getattr(reg_a, 'pk', None), getattr(reg_b, 'pk', None))
        return None

    for run in candidates:
        # Orientation is already encoded in assessment_key AND pinned by the
        # reg_a/reg_b filter above; asserted here so a future change to either
        # cannot quietly admit a reversed assessment.
        if run.reg_a_id != reg_a.pk or run.reg_b_id != reg_b.pk:
            continue
        if not run.is_reusable:
            continue
        ok, _code, _detail = verify_scope_coverage(run, topics, scope_mode)
        if not ok:
            continue
        return run
    return None


# ── deletion protection ─────────────────────────────────────────────────────

def deletion_blockers(document) -> list[dict]:
    """Comparison work that must be resolved before `document` can be deleted.

    A comparison run is only meaningful in terms of the two documents it
    compared, so deleting one destroys the assessment. For an APPROVED
    assessment that is an audit failure: a signed-off compliance record would
    disappear because somebody tidied up the library.

    Draft runs block too. They represent real analysis someone has not finished
    with, and they are never removed automatically — a deletion should not
    quietly take work with it. The reviewer is told exactly what is in the way
    and decides what to do about it.

    PURE — reads only, writes nothing, never raises. Returns [] when the
    document is free to delete.

    This mirrors the database-level PROTECT on ComparisonRun.reg_a/reg_b; it
    exists so the refusal can be explained BEFORE anything destructive runs,
    rather than surfacing as a raw ProtectedError naming an unrelated model.
    """
    from django.db.models import Q
    from apps.comparison.models import ComparisonRun

    if document is None or not getattr(document, 'pk', None):
        return []

    try:
        runs = list(ComparisonRun.objects
                    .filter(Q(reg_a=document) | Q(reg_b=document))
                    .select_related('reg_a', 'reg_b')
                    .order_by('-approved_at', '-created_at'))
    except Exception:
        logger.exception('deletion_blockers failed for document %s', document.pk)
        return []

    if not runs:
        return []

    approved = [r for r in runs
                if r.lifecycle in (ComparisonRun.APPROVED, ComparisonRun.SUPERSEDED)]
    other    = [r for r in runs if r not in approved]

    def _describe(run):
        return {
            'id':        run.pk,
            'label':     f'{run.reg_a.name} → {run.reg_b.name}',
            'side':      'A' if run.reg_a_id == document.pk else 'B',
            'lifecycle': run.get_lifecycle_display(),
            'version':   run.version_no,
            'approved_at': run.approved_at,
        }

    blockers = []
    if approved:
        blockers.append({
            'kind':     'approved_assessment',
            'severity': 'hard',
            'count':    len(approved),
            'label':    (f'{len(approved)} approved comparison assessment'
                         f'{"" if len(approved) == 1 else "s"} were signed off '
                         f'using this document'),
            'detail':   'Deleting it would destroy a signed-off compliance '
                        'record. Approved assessments are retained for audit.',
            'runs':     [_describe(r) for r in approved],
        })
    if other:
        blockers.append({
            'kind':     'comparison_run',
            'severity': 'hard',
            'count':    len(other),
            'label':    (f'{len(other)} comparison run'
                         f'{"" if len(other) == 1 else "s"} reference this document'),
            'detail':   'These runs are not finished. They are never removed '
                        'automatically — delete the runs you no longer need '
                        'first, then delete the document.',
            'runs':     [_describe(r) for r in other],
        })
    return blockers


def refresh_approved_currency(*, save: bool = True) -> dict:
    """Re-check every run that claims to be an approved assessment.

    Scoped to approved + superseded runs: those are the ones whose currency is
    asserted to a user. Drafts make no claim, so checking them would be work
    without a consumer.
    """
    from apps.comparison.models import ComparisonRun
    runs = (ComparisonRun.objects
            .filter(lifecycle__in=[ComparisonRun.APPROVED, ComparisonRun.SUPERSEDED])
            .select_related('reg_a', 'reg_b'))
    return refresh_currency_for(runs, save=save)


# ── approval ────────────────────────────────────────────────────────────────

class ApprovalError(ValueError):
    """Raised when a run cannot be approved. Message is shown to the reviewer."""


def can_approve(run) -> tuple[bool, str]:
    """May this run be certified as a compliance assessment?

    Gated on the per-result workflow having finished. Certifying an assessment
    while some obligations are still undecided would put a half-reviewed
    result on a page whose entire promise is that a human signed it off.
    """
    if run.lifecycle == run.APPROVED:
        return False, 'This run is already approved.'
    if run.lifecycle == run.SUPERSEDED:
        return False, 'This run has been superseded by a newer version.'
    if run.status not in (run.COMPLETE, run.PARTIALLY_FAILED):
        return False, (f'The comparison has not finished running '
                       f'(status: {run.get_status_display()}).')
    state = run.review_state()
    if not state['total']:
        return False, 'This run produced no comparison results to review.'
    if not state['all_decided']:
        return False, (f'{state["undecided"]} of {state["total"]} results are '
                       f'still awaiting review. Every result must be decided '
                       f'before the assessment can be approved.')
    return True, ''


def approve_run(run, *, actor=None, note: str = ''):
    """Certify a run as an approved compliance assessment.

    Assigns its version within the assessment and supersedes the previous
    approved version, which is RETAINED — superseding preserves history, it
    does not delete it. A superseded run stays openable for audit.

    Currency is NOT invented here. A run with no verified snapshot stays
    `unknown` even once approved: approval records a human judgement about the
    analysis, it cannot establish which document versions were compared.
    """
    from django.utils import timezone

    ok, why = can_approve(run)
    if not ok:
        raise ApprovalError(why)

    previous = None
    if run.assessment_key:
        previous = (run.__class__.objects
                    .filter(assessment_key=run.assessment_key,
                            lifecycle=run.APPROVED)
                    .exclude(pk=run.pk)
                    .order_by('-version_no', '-approved_at').first())

    run.version_no  = (previous.version_no + 1) if previous else 1
    run.supersedes  = previous
    run.lifecycle   = run.APPROVED
    run.approved_at = timezone.now()
    run.approved_by = actor if (actor and actor.is_authenticated) else None
    if note:
        run.analyst_note = (run.analyst_note + '\n' if run.analyst_note else '') + note
    run.save(update_fields=['version_no', 'supersedes', 'lifecycle',
                            'approved_at', 'approved_by', 'analyst_note'])

    if previous is not None:
        previous.lifecycle = run.SUPERSEDED
        previous.save(update_fields=['lifecycle'])

    _audit(run, actor, 'approved',
           f'approved comparison assessment v{run.version_no}',
           {'assessment_key': run.assessment_key, 'version_no': run.version_no,
            'superseded_run': previous.pk if previous else None,
            'currency_state': run.currency_state})
    return run


def reject_run(run, *, actor=None, note: str = ''):
    """Record that the assessment as a whole was not accepted."""
    if run.lifecycle == run.APPROVED:
        raise ApprovalError(
            'This run is already approved. Approve a newer run to supersede it '
            'rather than rejecting the approved version.')
    run.lifecycle = run.REJECTED
    if note:
        run.analyst_note = (run.analyst_note + '\n' if run.analyst_note else '') + note
    run.save(update_fields=['lifecycle', 'analyst_note'])
    _audit(run, actor, 'rejected', 'rejected comparison assessment', {})
    return run


def _audit(run, actor, action, description, metadata):
    """Best-effort audit. Never raises into the review flow."""
    try:
        from apps.history.audit import log_event, Actions
        action_map = {'approved': Actions.REVIEW_ACCEPT,
                      'rejected': Actions.REVIEW_REJECT}
        log_event(
            actor, action_map.get(action, Actions.REVIEW_MODIFY),
            target_type='comparison.ComparisonRun', target_id=run.pk,
            description=(f'{getattr(actor, "username", "system")} '
                         f'{description}: {run.reg_a.name} vs {run.reg_b.name}'),
            metadata={'run_id': run.pk, **metadata})
    except Exception:
        logger.exception('audit for run %s failed', run.pk)


# ── reading ─────────────────────────────────────────────────────────────────

def approved_assessments(limit: int | None = None) -> list[dict]:
    """Approved runs grouped into assessments, newest version first.

    One entry per assessment_key: the newest approved version as `latest`, and
    every older approved-or-superseded version as `history`. History is kept
    visible on purpose — a superseded assessment is still the record of what
    was certified at the time, and audit needs it.
    """
    from apps.comparison.models import ComparisonRun

    runs = list(ComparisonRun.objects
                .filter(lifecycle__in=[ComparisonRun.APPROVED,
                                       ComparisonRun.SUPERSEDED])
                .exclude(approved_at=None)
                .select_related('reg_a', 'reg_b', 'approved_by', 'supersedes')
                .order_by('-approved_at'))

    grouped: dict[str, list] = {}
    for run in runs:
        # A run with no assessment_key (possible only for legacy rows) still
        # deserves a place rather than being silently dropped, so it forms its
        # own single-version group.
        key = run.assessment_key or f'run:{run.pk}'
        grouped.setdefault(key, []).append(run)

    out = []
    for key, versions in grouped.items():
        versions.sort(key=lambda r: (r.version_no, r.approved_at), reverse=True)
        latest = versions[0]
        out.append({
            'assessment_key': key,
            'latest':         latest,
            'history':        versions[1:],
            'version_count':  len(versions),
        })
    out.sort(key=lambda e: e['latest'].approved_at, reverse=True)
    return out[:limit] if limit else out
