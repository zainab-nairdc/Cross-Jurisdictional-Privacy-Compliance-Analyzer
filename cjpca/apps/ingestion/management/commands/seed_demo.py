"""Management command: python manage.py seed_demo"""
import random
from datetime import timedelta
from collections import Counter

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.comparison.models import ComparisonRun, ComparisonResult, AuditEvent
from apps.library.models import Document


BH_ARTICLES = [
    ("Article 3",  "Processing of personal data shall be lawful only if the data subject has given explicit consent or if processing is necessary for the performance of a contract to which the data subject is party."),
    ("Article 5",  "Personal data shall be collected for specified, explicit and legitimate purposes and not further processed in a manner incompatible with those purposes."),
    ("Article 6",  "Personal data shall be adequate, relevant and limited to what is necessary in relation to the purposes for which it is processed."),
    ("Article 8",  "Personal data shall not be kept in a form which permits identification of data subjects for longer than is necessary for the purposes for which the personal data are processed."),
    ("Article 10", "The data controller shall implement appropriate technical and organisational measures to ensure a level of security appropriate to the risk."),
    ("Article 12", "Where a personal data breach is likely to result in a high risk to the rights and freedoms of individuals, the controller shall communicate the breach to the data subject without undue delay."),
    ("Article 14", "Data subjects shall have the right to obtain confirmation as to whether personal data concerning them are being processed, and where that is the case, access to the personal data."),
    ("Article 16", "The data subject shall have the right to obtain from the controller the erasure of personal data concerning them without undue delay."),
    ("Article 20", "Transfers of personal data to a third country shall take place only if the country ensures an adequate level of data protection."),
    ("Article 22", "The controller shall maintain a record of processing activities under its responsibility containing the name of the controller and the purposes of the processing."),
    ("Article 24", "Where a type of processing is likely to result in a high risk to the rights and freedoms of individuals, the controller shall carry out a data protection impact assessment."),
    ("Article 27", "The data subject shall have the right to object to processing of personal data concerning them which is based on legitimate interests of the controller."),
]

IN_SECTIONS = [
    ("Section 4",    "A Data Fiduciary shall process personal data of a Data Principal only for a lawful purpose for which the Data Principal has given her consent."),
    ("Section 6",    "Consent of the Data Principal shall be free, specific, informed, unconditional and unambiguous with a clear affirmative action, and shall signify an agreement to the processing of her personal data."),
    ("Section 8(1)", "Every Data Fiduciary shall make reasonable efforts to ensure the accuracy and completeness of personal data that is likely to be used to make a decision that affects the Data Principal."),
    ("Section 8(5)", "Every Data Fiduciary shall retain personal data only for so long as may be necessary to satisfy the purpose for which it was collected."),
    ("Section 8(7)", "Every Data Fiduciary shall protect personal data in its possession or under its control by taking reasonable security safeguards to prevent personal data breach."),
    ("Section 8(9)", "Every Data Fiduciary shall, in the event of a personal data breach, give the Board and each affected Data Principal notice of such breach in such form and manner as may be prescribed."),
    ("Section 11",   "A Data Principal shall have the right to obtain from the Data Fiduciary a summary of personal data being processed and the processing activities undertaken by that Data Fiduciary."),
    ("Section 12",   "A Data Principal shall have the right to correction, completion, updating and erasure of personal data."),
    ("Section 16",   "The Central Government may notify certain countries or territories outside India to which a Data Fiduciary may transfer personal data."),
    ("Section 18",   "The Central Government may specify the threshold for the number of Data Principals whose personal data is processed above which a Data Fiduciary shall be registered."),
    ("Section 27",   "No person shall process the personal data of a child without obtaining verifiable consent of the parent of such child or the lawful guardian of such child."),
    ("Section 35",   "The Board shall be deemed to be a civil court for purposes of receiving evidence, administering oaths, enforcing the attendance of witnesses and compelling production of documents."),
]

KW_ARTICLES = [
    ("Article 4",  "Personal data shall be processed in a lawful, fair and transparent manner in relation to the data subject."),
    ("Article 5",  "The controller shall ensure that personal data are collected for specified, explicit and legitimate purposes and shall not be further processed in a manner incompatible with those purposes."),
    ("Article 7",  "Personal data shall be kept in a form which permits identification of data subjects for no longer than is necessary for the purposes for which the personal data are processed."),
    ("Article 9",  "The controller shall implement appropriate technical and organisational measures taking into account the state of the art, the costs of implementation, and the nature of the personal data to be protected."),
    ("Article 11", "The controller shall notify the supervisory authority of a personal data breach without undue delay and, where feasible, not later than 72 hours after having become aware of it."),
    ("Article 13", "The data subject shall have the right to obtain from the controller confirmation as to whether personal data concerning them are being processed and, where applicable, access to the personal data."),
    ("Article 15", "The data subject shall have the right to erasure without undue delay where the personal data are no longer necessary in relation to the purposes for which they were collected."),
    ("Article 19", "Personal data shall only be transferred to a third country if that country or international organisation ensures an adequate level of protection."),
    ("Article 21", "Controllers processing data that poses high risk shall conduct a Data Protection Impact Assessment prior to processing."),
    ("Article 23", "Where processing is carried out on behalf of a controller, the controller shall use only processors providing sufficient guarantees to implement appropriate technical and organisational measures."),
]

BH_PRINCIPLES = {
    "Article 3":  ["consent", "processing_grounds"],
    "Article 5":  ["processing_grounds", "data_controller"],
    "Article 6":  ["data_controller", "data_subject"],
    "Article 8":  ["retention"],
    "Article 10": ["data_controller"],
    "Article 12": ["breach"],
    "Article 14": ["data_subject"],
    "Article 16": ["data_subject"],
    "Article 20": ["cross_border_transfer", "adequacy"],
    "Article 22": ["data_controller"],
    "Article 24": ["dpia"],
    "Article 27": ["data_subject", "processing_grounds"],
}

IN_PRINCIPLES = {
    "Section 4":    ["consent", "processing_grounds"],
    "Section 6":    ["consent"],
    "Section 8(1)": ["data_subject", "data_controller"],
    "Section 8(5)": ["retention"],
    "Section 8(7)": ["data_controller"],
    "Section 8(9)": ["breach"],
    "Section 11":   ["data_subject"],
    "Section 12":   ["data_subject"],
    "Section 16":   ["cross_border_transfer", "adequacy"],
    "Section 18":   ["data_controller", "supervisory_authority"],
    "Section 27":   ["consent", "data_subject"],
    "Section 35":   ["supervisory_authority"],
}

KW_PRINCIPLES = {
    "Article 4":  ["processing_grounds", "data_controller"],
    "Article 5":  ["processing_grounds"],
    "Article 7":  ["retention"],
    "Article 9":  ["data_controller"],
    "Article 11": ["breach", "supervisory_authority"],
    "Article 13": ["data_subject"],
    "Article 15": ["data_subject"],
    "Article 19": ["cross_border_transfer", "adequacy"],
    "Article 21": ["dpia"],
    "Article 23": ["vendor_processor"],
}

# Scenarios: (a_idx, b_idx, relationship, confidence, similarity, key_diff, rationale)
BH_IN_SCENARIOS = [
    (0,  0,  "equivalent",       0.91, 0.88, "Both require lawful basis and consent for data processing.", "Both laws establish consent as a primary lawful basis. Language is functionally equivalent."),
    (1,  None,"additional_in_a", 0.78, 0.45, "Bahrain explicitly mandates purpose limitation; DPDPA is silent.", "Article 5 of Bahrain PDPL contains explicit purpose limitation. No direct DPDPA equivalent."),
    (2,  2,  "equivalent",       0.87, 0.85, "Both laws require data minimisation relative to processing purpose.", "Both regulations align on data minimisation requiring only necessary data."),
    (3,  3,  "stricter_in_a",   0.83, 0.72, "Bahrain is more prescriptive on deletion timelines than India.", "Both address retention but Bahrain's PDPL is more prescriptive about controller deletion obligations."),
    (4,  4,  "equivalent",       0.89, 0.86, "Both require appropriate technical and organisational security measures.", "Security obligations are functionally equivalent across both laws."),
    (5,  5,  "stricter_in_b",   0.82, 0.75, "India requires dual notification (Board + principals); Bahrain only to data subjects.", "India's breach notification scope is broader — dual notification requirement vs Bahrain's single-channel."),
    (6,  6,  "equivalent",       0.93, 0.91, "Both provide data subjects access rights to their personal data.", "Access rights are substantially equivalent. Minor procedural differences don't affect compliance."),
    (7,  7,  "equivalent",       0.88, 0.84, "Both grant the right to erasure of personal data.", "Right to erasure is present in both laws with similar grounds and scope."),
    (8,  8,  "equivalent",       0.85, 0.80, "Both restrict cross-border transfers to countries with adequate protection.", "Transfer restriction frameworks are substantively aligned on adequacy basis."),
    (9,  None,"additional_in_a", 0.72, 0.38, "Bahrain requires records of processing activities; India has no equivalent.", "Bahrain PDPL Article 22 mandates controller record-keeping. No matching DPDPA obligation."),
    (None,10,"additional_in_b",  0.74, 0.40, "India has specific child consent rules; Bahrain is silent.", "DPDPA Section 27 introduces verifiable parental consent. Bahrain PDPL has no equivalent."),
    (11, 10, "conflicting",      0.67, 0.55, "Right to object scope differs — Bahrain is broader.", "Bahrain allows objection to any legitimate interest processing. India has no general objection right."),
    (0,  1,  "stricter_in_a",   0.79, 0.66, "Bahrain requires explicit consent; India allows deemed consent scenarios.", "India allows certain deemed consent exceptions that Bahrain's stricter standard does not permit."),
    (2,  7,  "conflicting",      0.61, 0.48, "Data minimisation interpretation differs on aggregated datasets.", "Bahrain applies minimisation to all stages. India partially delegates standards to sub-rules."),
]

BH_KW_SCENARIOS = [
    (0,  0,  "equivalent",       0.92, 0.89, "Both require lawful processing basis including consent.", "Consent requirements are functionally equivalent across both frameworks."),
    (1,  1,  "equivalent",       0.88, 0.85, "Purpose limitation is functionally identical across both laws.", "Purpose limitation provisions are substantively equivalent."),
    (2,  None,"additional_in_a", 0.76, 0.42, "Bahrain has explicit data minimisation; Kuwait infers it.", "Bahrain's explicit data minimisation is not directly replicated in Kuwait Resolution 42."),
    (3,  2,  "stricter_in_b",   0.84, 0.73, "Kuwait specifies retention more prescriptively than Bahrain.", "Kuwait's retention language is marginally stricter in requiring explicit justification for retention."),
    (4,  3,  "equivalent",       0.90, 0.87, "Both mandate appropriate security measures for personal data.", "Security obligations are substantively equivalent across both frameworks."),
    (5,  4,  "stricter_in_b",   0.81, 0.69, "Kuwait requires 72-hour notification; Bahrain is vague on timeline.", "Kuwait Resolution 42 explicitly mandates 72-hour breach notification. Bahrain lacks this specificity."),
    (6,  5,  "equivalent",       0.91, 0.88, "Right of access is equivalent in both jurisdictions.", "Both laws provide substantially equivalent access rights to data subjects."),
    (7,  6,  "equivalent",       0.86, 0.83, "Both provide right to erasure.", "Erasure rights are aligned in scope and grounds across both laws."),
    (8,  7,  "equivalent",       0.87, 0.81, "Both restrict cross-border transfers to adequate countries.", "Transfer restrictions are substantively equivalent."),
    (9,  None,"additional_in_a", 0.71, 0.36, "Bahrain mandates controller records; Kuwait does not.", "Bahrain PDPL requires record-keeping by controllers. No equivalent in Kuwait Resolution 42."),
    (10, 8,  "equivalent",       0.85, 0.79, "DPIA requirements are similar in scope and trigger.", "Both laws require impact assessments for high-risk processing activities."),
    (11, 9,  "conflicting",      0.64, 0.51, "Vendor processor obligations differ in scope.", "Kuwait requires stronger processor due diligence. Bahrain's requirements are less prescriptive."),
]

IN_KW_SCENARIOS = [
    (0,  0,  "equivalent",       0.90, 0.87, "Both require lawful processing including consent.", "Consent requirements are functionally equivalent across both frameworks."),
    (2,  1,  "equivalent",       0.86, 0.83, "Purpose limitation aligned.", "Both laws express purpose limitation in similar terms."),
    (3,  2,  "stricter_in_b",   0.82, 0.71, "Kuwait specifies retention more prescriptively.", "Kuwait's retention obligation is more specific than India's delegated-rule approach."),
    (4,  3,  "equivalent",       0.89, 0.86, "Security obligations are equivalent.", "Both impose equivalent security safeguard requirements."),
    (5,  4,  "stricter_in_a",   0.83, 0.74, "India requires dual notification (Board + principals).", "India's breach notification is broader in scope than Kuwait's single-authority requirement."),
    (6,  5,  "equivalent",       0.91, 0.89, "Access rights are equivalent.", "Right of access is substantially equivalent in scope across both laws."),
    (7,  6,  "equivalent",       0.87, 0.84, "Erasure rights are equivalent.", "Both laws provide comparable erasure rights."),
    (8,  7,  "equivalent",       0.88, 0.82, "Transfer restrictions are aligned.", "Cross-border transfer frameworks are substantively equivalent."),
    (10, 8,  "stricter_in_b",   0.78, 0.65, "Kuwait DPIA triggers are broader than India's.", "Kuwait's DPIA requirements apply to a wider range of processing activities."),
    (11, 9,  "conflicting",      0.63, 0.49, "Processor obligations differ significantly.", "India's Data Fiduciary processor framework differs materially from Kuwait's controller-processor model."),
    (None,9, "additional_in_b",  0.73, 0.41, "Kuwait has explicit processor due-diligence rules; India is silent.", "Kuwait Resolution 42 Article 23 requires explicit controller guarantees. India DPDPA lacks equivalent."),
]

REVIEWERS = ["noor.al-rashidi", "sara.khalid", "ahmed.mansoor", "fatima.ibrahim"]


class Command(BaseCommand):
    help = "Seed demo analytics data for CJPCA"

    def handle(self, *args, **options):
        random.seed(42)

        bh = Document.objects.get(pk=75)
        ind = Document.objects.get(pk=88)
        kw = Document.objects.get(pk=95)

        runs_spec = [
            # (pair, reg_a, reg_b, scenarios, art_a, art_b, princ_a, princ_b, days_ago, lc_dist)
            ("bh_in", bh, ind, BH_IN_SCENARIOS,      BH_ARTICLES, IN_SECTIONS, BH_PRINCIPLES, IN_PRINCIPLES, 165, dict(approved=0.35, rejected=0.10, reviewed=0.10)),
            ("bh_in", bh, ind, BH_IN_SCENARIOS[:10], BH_ARTICLES, IN_SECTIONS, BH_PRINCIPLES, IN_PRINCIPLES, 130, dict(approved=0.40, rejected=0.08, reviewed=0.12)),
            ("bh_in", bh, ind, BH_IN_SCENARIOS[2:12],BH_ARTICLES, IN_SECTIONS, BH_PRINCIPLES, IN_PRINCIPLES,  95, dict(approved=0.45, rejected=0.10, reviewed=0.05)),
            ("bh_in", bh, ind, BH_IN_SCENARIOS[1:11],BH_ARTICLES, IN_SECTIONS, BH_PRINCIPLES, IN_PRINCIPLES,  60, dict(approved=0.50, rejected=0.12, reviewed=0.08)),
            ("bh_in", bh, ind, BH_IN_SCENARIOS[3:],  BH_ARTICLES, IN_SECTIONS, BH_PRINCIPLES, IN_PRINCIPLES,  20, dict(approved=0.30, rejected=0.05, reviewed=0.15)),

            ("bh_kw", bh, kw,  BH_KW_SCENARIOS,      BH_ARTICLES, KW_ARTICLES, BH_PRINCIPLES, KW_PRINCIPLES, 150, dict(approved=0.38, rejected=0.08, reviewed=0.10)),
            ("bh_kw", bh, kw,  BH_KW_SCENARIOS[:8],  BH_ARTICLES, KW_ARTICLES, BH_PRINCIPLES, KW_PRINCIPLES, 110, dict(approved=0.42, rejected=0.09, reviewed=0.07)),
            ("bh_kw", bh, kw,  BH_KW_SCENARIOS[2:10],BH_ARTICLES, KW_ARTICLES, BH_PRINCIPLES, KW_PRINCIPLES,  75, dict(approved=0.48, rejected=0.11, reviewed=0.06)),
            ("bh_kw", bh, kw,  BH_KW_SCENARIOS[4:],  BH_ARTICLES, KW_ARTICLES, BH_PRINCIPLES, KW_PRINCIPLES,  35, dict(approved=0.33, rejected=0.07, reviewed=0.13)),

            ("in_kw", ind, kw, IN_KW_SCENARIOS,       IN_SECTIONS, KW_ARTICLES, IN_PRINCIPLES, KW_PRINCIPLES, 140, dict(approved=0.36, rejected=0.09, reviewed=0.11)),
            ("in_kw", ind, kw, IN_KW_SCENARIOS[:7],   IN_SECTIONS, KW_ARTICLES, IN_PRINCIPLES, KW_PRINCIPLES,  85, dict(approved=0.43, rejected=0.10, reviewed=0.08)),
            ("in_kw", ind, kw, IN_KW_SCENARIOS[2:],   IN_SECTIONS, KW_ARTICLES, IN_PRINCIPLES, KW_PRINCIPLES,  30, dict(approved=0.35, rejected=0.08, reviewed=0.12)),
        ]

        for i, (pair, reg_a, reg_b, scenarios, art_a_lib, art_b_lib, pA, pB, days_ago, lc_dist) in enumerate(runs_spec):
            run = self._make_run(pair, reg_a, reg_b, scenarios, art_a_lib, art_b_lib, pA, pB, days_ago, lc_dist)
            self.stdout.write(f"  [{i+1}/{len(runs_spec)}] Run pk={run.pk} pair={pair} results={run.results.count()}")

        self.stdout.write("")
        self.stdout.write("=== Summary ===")
        self.stdout.write(f"Complete runs:    {ComparisonRun.objects.filter(status='complete').count()}")
        self.stdout.write(f"Total results:    {ComparisonResult.objects.count()}")
        self.stdout.write(f"Total events:     {AuditEvent.objects.count()}")
        rels = Counter(ComparisonResult.objects.values_list("relationship", flat=True))
        for rel, cnt in sorted(rels.items()):
            self.stdout.write(f"  {rel}: {cnt}")
        self.stdout.write(self.style.SUCCESS("Done."))

    def _make_run(self, pair_key, reg_a, reg_b, scenarios, art_a_lib, art_b_lib, pA, pB, days_ago, lc_dist):
        run = ComparisonRun.objects.create(
            pair_key=pair_key, reg_a=reg_a, reg_b=reg_b, topics=[],
            status=ComparisonRun.COMPLETE,
            completed_pairs=len(scenarios), total_pairs=len(scenarios),
        )
        ComparisonRun.objects.filter(pk=run.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago)
        )

        collected = []
        for sc in scenarios:
            a_idx, b_idx, rel, conf, sim, key_diff, rationale = sc

            art_a = art_a_lib[a_idx] if a_idx is not None else None
            art_b = art_b_lib[b_idx] if b_idx is not None else None

            cit_a = f"{reg_a.name} \u2014 {art_a[0]}" if art_a else ""
            cit_b = f"{reg_b.name} \u2014 {art_b[0]}" if art_b else ""

            principles = list(set(
                (pA.get(art_a[0], []) if art_a else []) +
                (pB.get(art_b[0], []) if art_b else [])
            ))

            conf_v = max(0.50, min(0.98, conf + random.uniform(-0.05, 0.05)))
            sim_v  = max(0.30, min(0.99, sim  + random.uniform(-0.04, 0.04)))

            roll = random.random()
            if roll < lc_dist["approved"]:
                lc = ComparisonResult.APPROVED
            elif roll < lc_dist["approved"] + lc_dist["rejected"]:
                lc = ComparisonResult.REJECTED
            elif roll < lc_dist["approved"] + lc_dist["rejected"] + lc_dist["reviewed"]:
                lc = ComparisonResult.REVIEWED
            else:
                lc = ComparisonResult.DRAFT

            r = ComparisonResult.objects.create(
                run=run, relationship=rel,
                confidence=round(conf_v, 3),
                similarity_score=round(sim_v, 3),
                citation_a=cit_a, citation_b=cit_b,
                citation_verified=random.random() > 0.2,
                preview_a=art_a[1][:200] if art_a else "",
                preview_b=art_b[1][:200] if art_b else "",
                clause_text_a=art_a[1] if art_a else "",
                clause_text_b=art_b[1] if art_b else "",
                key_difference=key_diff, rationale=rationale,
                principle_ids=principles, lifecycle=lc,
            )
            result_age = days_ago - random.randint(0, 2)
            ComparisonResult.objects.filter(pk=r.pk).update(
                created_at=timezone.now() - timedelta(days=result_age)
            )
            collected.append((r, lc, days_ago))

        for r, lc, run_days in collected:
            if lc in (ComparisonResult.APPROVED, ComparisonResult.REJECTED, ComparisonResult.REVIEWED):
                reviewer = random.choice(REVIEWERS)
                event_days = max(0, run_days - random.randint(1, 5))
                ev = AuditEvent.objects.create(
                    result=r, actor=reviewer, action=lc,
                    from_lifecycle=ComparisonResult.DRAFT, to_lifecycle=lc,
                )
                AuditEvent.objects.filter(pk=ev.pk).update(
                    timestamp=timezone.now() - timedelta(days=event_days)
                )

        return run
