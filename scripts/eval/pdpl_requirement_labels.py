"""Hand-labelled recall set: Bahrain PDPL (document 98).

`expected` is the number of distinct obligation-bearing provisions in the chunk.

METHODOLOGY, and a correction worth recording. The first version of this file
was labelled from 620-character excerpts, because that is all the labelling pass
printed. Twelve of the twenty chunks carry binding language past that point, so
the counts were systematically too low — which inflates recall (a low bar is
easy to clear) and deflates precision (correct extractions beyond the excerpt
look like false positives). Every count below has now been re-derived from the
FULL chunk text. The `was` column records the discarded first-pass number so the
size of that error stays visible rather than being quietly overwritten.

Counting rules, applied consistently:

  - a rule stated with exceptions counts as ONE ("processing is prohibited
    unless ..." is one prohibition, not one plus five);
  - a list specifying the CONTENT of a duty (what a notice must contain) is part
    of that duty, not separate duties;
  - a numbered list of separate DUTIES counts once per duty;
  - a permission or power ("the Authority may authorise ...") counts, because it
    is a rule a compliance reviewer must know about;
  - definitions, scope statements and descriptive text count 0;
  - obligations binding the Authority itself count, and are marked
    institutional=True so recall can be reported with and without them.

These are judgements about legal text, not ground truth from anywhere
authoritative, and they are recorded here to be argued with.

Chunks are identified by node_id prefix, stable while the document is not
re-ingested.
"""

# node_id,     article,                                expected, institutional, was
LABELS = [
    ('40a3396b', 'Article (1) Definitions',                    0, False,  0),
    # +2: tail imposes "shall appoint a representative" and "shall immediately
    # notify the Authority about such appointment". The opening is scope only.
    ('116f11cd', 'Article (2) Scope of Application',           2, False,  0),
    ('b3bafc4d', 'Article (4) General Conditions',             1, False,  1),
    # +8: the excerpt stopped after the six Guardian duties. The chunk continues
    # into independence, the Authority's Guardians Register, the Board
    # resolution, three fee provisions, the appointment permission and the
    # three-working-day notification.
    ('a42a25cd', 'Article (10) Data Protection Guardian',     16, False,  8),
    ('149e4be0', 'Article (11) Registers Data',                2, False,  2),
    # +1: "the level of protection shall be assessed in the light of all the
    # circumstances" is a duty on the Authority.
    ('189c7f1b', 'Article (12) Transfer outside Kingdom',      2, False,  1),
    # +2: the Authority may authorise a transfer where safeguards are adduced,
    # and shall subject that authorisation to conditions.
    ('15564367', 'Article (13) Exemptions',                    3, False,  1),
    # +3: Board resolution determining notification rules; Board power to allow a
    # simplified notification; the simplified notification's submission duty.
    ('b8ed9b6d', 'Article (14) Notification (part 1)',         5, False,  2),
    # +1: notifications shall be promptly recorded in the Article (16) register.
    ('e5fe56cc', 'Article (14) Notification (part 2)',         4, False,  3),
    # +6: request submission; Authority may instruct completion within 5 days;
    # applicant shall complete within 5 days; Authority decides on the
    # information given; Authority shall grant where conditions are met;
    # Authority shall rule and notify within thirty days.
    ('a1219b4a', 'Article (15) Prior Authorisation',           7, False,  1),
    # +4: Authority shall keep the Register updated; any person may inspect it
    # free of charge; any person may obtain printouts on payment; the Minister
    # shall issue a decision prescribing the fee.
    ('6192e7ec', 'Article (16) The Register',                  5, True,   1),
    ('91c9a6ec', 'Article (17) Information to Data Subject',   2, False,  2),
    # +5: controller may notify of deficiency within 10 days; may reject
    # incomplete requests; may reject on misuse; shall notify a reasoned decision
    # within 15 working days; data subject may complain to the Authority.
    ('3fd9c202', 'Article (18) Request to be notified',        7, False,  2),
    ('1e17c68e', 'Article (19) Direct marketing notice',       1, False,  1),
    ('cfe6f780', 'Article (20) Right to Object',               3, False,  3),
    # +5: this chunk runs past Article (26) into Article (27) — legal personality
    # and Ministerial oversight; a Legislative-Decree to determine the
    # administrative body; the Decree identifying who exercises the powers; the
    # Board resolving on the logo; the Authority's exclusive right to the logo.
    ('fd86fc7f', 'Article (26) Submission of requests',        5, True,   0),
    # +1: the Authority's financial year shall correspond to the State's.
    ('992e2391', 'Article (29) Budget of the Authority',       2, True,   1),
    ('08e21c98', 'Article (31) Exercising of Duties',          1, True,   1),
    ('f4cf2ed3', "Article (33) Authority's Annual Reports",    2, True,   2),
    ('9a75097d', 'Article (59) Liability of legal person',     1, False,  1),
]

TOTAL_EXPECTED = sum(x[2] for x in LABELS)
TOTAL_EXPECTED_NON_INSTITUTIONAL = sum(x[2] for x in LABELS if not x[3])
TOTAL_FIRST_PASS = sum(x[4] for x in LABELS)


def label_for(node_id: str):
    """(article, expected, institutional) for a node_id, or None if unlabelled."""
    for prefix, article, expected, inst, _was in LABELS:
        if node_id.startswith(prefix):
            return article, expected, inst
    return None
