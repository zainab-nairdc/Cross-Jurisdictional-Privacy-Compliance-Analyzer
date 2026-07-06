"""Generate the consolidated APA 7 References document.

Output: thesis_docs/references_apa7.docx

The source thesis had references scattered across multiple sections
(Appendix 1, §2.1, §2.3, §2.4, §3.2, and chapter-level "References
cited in this chapter" blocks). This script deduplicates them, sorts
alphabetically by first author surname, and outputs a single APA 7
formatted list with hanging indent.

URL validity was spot-checked at compile time for the commercial
platform pages (OneTrust, Osano, Securiti, OCEG, Sprinto). DOI and
arXiv links are persistent identifiers and assumed valid.
"""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor


BLACK = RGBColor(0x00, 0x00, 0x00)
NAVY = BLACK


# Deduplicated, alphabetical APA 7 reference list.
# Each entry is one string formatted for APA 7 hanging-indent display.
REFERENCES = [
    'BigID. (2026). BigID pricing. '
    'https://home.bigid.com/pricing',

    'Bommasani, R., Hudson, D. A., Adeli, E., Altman, R., Arora, S., '
    'von Arx, S., Bernstein, M. S., Bohg, J., Bosselut, A., Brunskill, '
    'E., Brynjolfsson, E., Buch, S., Card, D., Castellon, R., Chatterji, '
    'N., Chen, A., Creel, K., Davis, J. Q., Demszky, D., ... Liang, P. '
    '(2021). On the opportunities and risks of foundation models '
    '(arXiv:2108.07258). arXiv. https://arxiv.org/abs/2108.07258',

    'Cabane, H., & Farias, K. (2024). On the impact of event-driven '
    'architecture on performance: An exploratory study. Future '
    'Generation Computer Systems, 153, 52-69. '
    'https://doi.org/10.1016/j.future.2023.10.021',

    'Chalkidis, I., Fergadiotis, M., Malakasiotis, P., Aletras, N., & '
    'Androutsopoulos, I. (2020). LEGAL-BERT: The muppets straight out '
    'of law school. In Findings of the Association for Computational '
    'Linguistics: EMNLP 2020 (pp. 2898-2904). Association for '
    'Computational Linguistics. '
    'https://doi.org/10.18653/v1/2020.findings-emnlp.261',

    'Chalkidis, I., Jana, A., Hartung, D., Bommarito, M., '
    'Androutsopoulos, I., Katz, D. M., & Aletras, N. (2022). LexGLUE: '
    'A benchmark dataset for legal language understanding in English. '
    'In Proceedings of the 60th Annual Meeting of the Association for '
    'Computational Linguistics (pp. 4310-4330). Association for '
    'Computational Linguistics. '
    'https://doi.org/10.18653/v1/2022.acl-long.297',

    'Dahl, M., Magesh, V., Suzgun, M., & Ho, D. E. (2024). Large legal '
    'fictions: Profiling legal hallucinations in large language '
    'models. Journal of Legal Analysis, 16(1), 64-93. '
    'https://doi.org/10.1093/jla/laae003',

    'Es, S., James, J., Espinosa-Anke, L., & Schockaert, S. (2024). '
    'RAGAS: Automated evaluation of retrieval augmented generation. '
    'In Proceedings of the 18th Conference of the European Chapter of '
    'the Association for Computational Linguistics: System '
    'Demonstrations (pp. 150-158). Association for Computational '
    'Linguistics. https://aclanthology.org/2024.eacl-demo.16/',

    'Gao, T., Yen, H., Yu, J., & Chen, D. (2023). Enabling large '
    'language models to generate text with citations. In Proceedings '
    'of the 2023 Conference on Empirical Methods in Natural Language '
    'Processing (pp. 6465-6488). Association for Computational '
    'Linguistics. https://aclanthology.org/2023.emnlp-main.398/',

    'Gao, Y., Xiong, Y., Gao, X., Jia, K., Pan, J., Bi, Y., Dai, Y., '
    'Sun, J., Wang, M., & Wang, H. (2024). Retrieval-augmented '
    'generation for large language models: A survey '
    '(arXiv:2312.10997). arXiv. https://arxiv.org/abs/2312.10997',

    'Greenleaf, G. (2021). Global data privacy laws 2021: Despite '
    'COVID delays, 145 laws show GDPR dominance. Privacy Laws & '
    'Business International Report, 169, 1, 3-5.',

    'Greenleaf, G. (2023). Global data privacy law developments and '
    'the GDPR effect. International Data Privacy Law, 13(2), 112-129.',

    'Greshake, K., Abdelnabi, S., Mishra, S., Endres, C., Holz, T., & '
    'Fritz, M. (2023). Not what you have signed up for: Compromising '
    'real-world LLM-integrated applications with indirect prompt '
    'injection. In Proceedings of the 16th ACM Workshop on Artificial '
    'Intelligence and Security (pp. 79-90). Association for '
    'Computing Machinery. https://doi.org/10.1145/3605764.3623985',

    'Guha, N., Nyarko, J., Ho, D. E., Re, C., Chilton, A., Narayana, '
    'A., Chohlas-Wood, A., Peters, A., Waldon, B., Rockmore, D. N., '
    'Zambrano, D., Talisman, D., Hoque, E., Surani, F., Fagan, F., '
    'Sarfaty, G., Dickinson, G. M., Porat, H., Hegland, J., ... '
    'Henderson, P. (2023). LegalBench: A collaboratively built '
    'benchmark for measuring legal reasoning in large language '
    'models. In Advances in Neural Information Processing '
    'Systems 36.',

    'Harkous, H., Fawaz, K., Lebret, R., Schaub, F., Shin, K. G., & '
    'Aberer, K. (2018). Polisis: Automated analysis and presentation '
    'of privacy policies using deep learning. In Proceedings of the '
    '27th USENIX Security Symposium (pp. 531-548). USENIX '
    'Association.',

    'Hassani, S., Sabetzadeh, M., Amyot, D., & Liao, J. (2024). '
    'Rethinking legal compliance automation: Opportunities with large '
    'language models. In Proceedings of the 32nd IEEE International '
    'Requirements Engineering Conference (pp. 507-516). IEEE. '
    'https://doi.org/10.1109/RE59067.2024.00059',

    'He, H., Zhang, H., & Roth, D. (2023). Rethinking with retrieval: '
    'Faithful large language model inference (arXiv:2301.00303). '
    'arXiv. https://arxiv.org/abs/2301.00303',

    'Hindi, M., Mohammed, L., Maaz, O., & Alwarafy, A. (2025). '
    'Enhancing the precision and interpretability of '
    'retrieval-augmented generation (RAG) in legal technology: A '
    'survey. IEEE Access, 13, 46171-46189. '
    'https://doi.org/10.1109/ACCESS.2025.3550145',

    'Honovich, O., Aharoni, R., Herzig, J., Taitelbaum, H., Kukliansy, '
    'D., Cohen, V., Scialom, T., & Szpektor, I. (2022). TRUE: '
    'Re-evaluating factual consistency evaluation. In Proceedings of '
    'the 2022 Conference of the North American Chapter of the '
    'Association for Computational Linguistics: Human Language '
    'Technologies (pp. 3905-3920). Association for Computational '
    'Linguistics. https://aclanthology.org/2022.naacl-main.287/',

    'Huang, L., Yu, W., Ma, W., Zhong, W., Feng, Z., Wang, H., Chen, '
    'Q., Peng, W., Feng, X., Qin, B., & Liu, T. (2025). A survey on '
    'hallucination in large language models: Principles, taxonomy, '
    'challenges, and open questions. ACM Transactions on Information '
    'Systems, 43(2), Article 42. https://doi.org/10.1145/3703155',

    'Jacovi, A., Wang, A., Alberti, C., Tao, C., Lipovetz, J., '
    'Olszewska, K., Haas, L., Liu, M., Keating, N., Bloniarz, A., '
    'Saroufim, C., Fry, C., Marcus, D., Kukliansky, D., Tomar, G. S., '
    'Swirhun, J., Xing, J., Wang, L., Gurumurthy, M., ... Das, D. '
    '(2025). The FACTS Grounding Leaderboard: Benchmarking LLMs '
    'ability to ground responses to long-form input '
    '(arXiv:2501.03200). arXiv. https://arxiv.org/abs/2501.03200',

    'Ji, Z., Lee, N., Frieske, R., Yu, T., Su, D., Xu, Y., Ishii, E., '
    'Bang, Y. J., Madotto, A., & Fung, P. (2023). Survey of '
    'hallucination in natural language generation. ACM Computing '
    'Surveys, 55(12), Article 248. '
    'https://doi.org/10.1145/3571730',

    'Kim, J., & Min, M. (2024). From RAG to QA-RAG: Integrating '
    'generative AI for pharmaceutical regulatory compliance process. '
    'In Proceedings of the 40th ACM/SIGAPP Symposium on Applied '
    'Computing (pp. 1295-1303). Association for Computing Machinery. '
    'https://doi.org/10.1145/3672608.3707749',

    'Kuner, C., Bygrave, L. A., & Docksey, C. (Eds.). (2020). The EU '
    'General Data Protection Regulation (GDPR): A commentary. Oxford '
    'University Press.',

    'Lai, J., Gan, W., Wu, J., Qi, Z., & Yu, P. S. (2024). Large '
    'language models in law: A survey. AI Open, 5, 181-196. '
    'https://doi.org/10.1016/j.aiopen.2024.09.002',

    'Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., '
    'Goyal, N., Kuttler, H., Lewis, M., Yih, W., Rocktaschel, T., '
    'Riedel, S., & Kiela, D. (2020). Retrieval-augmented generation '
    'for knowledge-intensive NLP tasks. In Advances in Neural '
    'Information Processing Systems 33 (pp. 9459-9474).',

    'Liu, Y., Jia, Y., Geng, R., Jia, J., & Gong, N. Z. (2024). '
    'Formalizing and benchmarking prompt injection attacks and '
    'defenses. In Proceedings of the 33rd USENIX Security Symposium '
    '(pp. 1831-1847). USENIX Association. '
    'https://www.usenix.org/conference/usenixsecurity24/'
    'presentation/liu-yupei',

    'Madaan, A., Tandon, N., Gupta, P., Hallinan, S., Gao, L., '
    'Wiegreffe, S., Alon, U., Dziri, N., Prabhumoye, S., Yang, Y., '
    'Gupta, S., Majumder, B. P., Hermann, K., Welleck, S., '
    'Yazdanbakhsh, A., & Clark, P. (2023). Self-Refine: Iterative '
    'refinement with self-feedback. In Advances in Neural Information '
    'Processing Systems 36. https://arxiv.org/abs/2303.17651',

    'Magesh, V., Surani, F., Dahl, M., Suzgun, M., Manning, C. D., & '
    'Ho, D. E. (2024). Hallucination-free? Assessing the reliability '
    'of leading AI legal research tools (arXiv:2405.20362). arXiv. '
    'https://arxiv.org/abs/2405.20362',

    'Malkov, Y. A., & Yashunin, D. A. (2020). Efficient and robust '
    'approximate nearest neighbor search using hierarchical navigable '
    'small world graphs. IEEE Transactions on Pattern Analysis and '
    'Machine Intelligence, 42(4), 824-836. '
    'https://doi.org/10.1109/TPAMI.2018.2889473',

    'McKay, K. A., & Cooper, D. A. (2019). Guidelines for the '
    'selection, configuration, and use of Transport Layer Security '
    '(TLS) implementations (NIST Special Publication 800-52 Rev. 2). '
    'National Institute of Standards and Technology. '
    'https://doi.org/10.6028/NIST.SP.800-52r2',

    'National Institute of Standards and Technology. (2024a). '
    'Artificial intelligence risk management framework: Generative '
    'artificial intelligence profile (NIST AI 600-1). U.S. Department '
    'of Commerce. https://doi.org/10.6028/NIST.AI.600-1',

    'National Institute of Standards and Technology. (2024b). The '
    'NIST Cybersecurity Framework (CSF) 2.0 (NIST Cybersecurity '
    'White Paper, NIST CSWP 29). '
    'https://doi.org/10.6028/NIST.CSWP.29',

    'Nogueira, R., & Cho, K. (2019). Passage re-ranking with BERT '
    '(arXiv:1901.04086). arXiv. https://arxiv.org/abs/1901.04086',

    'OneTrust. (2026). OneTrust pricing and packaging. '
    'https://www.onetrust.com/pricing/',

    'Open Compliance and Ethics Group. (2021). GRC capability model '
    '3.0 (OCEG Red Book). OCEG. '
    'https://www.oceg.org/grc-capability-model-red-book/',

    'Osano. (2026). Privacy compliance software: Your ultimate '
    'buyer\'s guide. '
    'https://www.osano.com/comparison/privacy-compliance-software-guide',

    'Ouyang, L., Wu, J., Jiang, X., Almeida, D., Wainwright, C. L., '
    'Mishkin, P., Zhang, C., Agarwal, S., Slama, K., Ray, A., '
    'Schulman, J., Hilton, J., Kelton, F., Miller, L., Simens, M., '
    'Askell, A., Welinder, P., Christiano, P., Leike, J., & Lowe, R. '
    '(2022). Training language models to follow instructions with '
    'human feedback. In Advances in Neural Information Processing '
    'Systems 35 (pp. 27730-27744). https://papers.nips.cc/paper_files/'
    'paper/2022/hash/b1efde53be364a73914f58805a001731-Abstract-'
    'Conference.html',

    'OWASP Foundation. (2021). OWASP Top 10:2021. '
    'https://owasp.org/Top10/2021/',

    'OWASP Foundation. (2025). OWASP Top 10 for Large Language Model '
    'applications 2025. https://genai.owasp.org/resource/'
    'owasp-top-10-for-llm-applications-2025/',

    'Ozkan, O., Babur, O., & van den Brand, M. (2025). Domain-driven '
    'design in software development: A systematic literature review '
    'on implementation, challenges, and effectiveness. Journal of '
    'Systems and Software, 228, Article 112473. '
    'https://doi.org/10.1016/j.jss.2025.112473',

    'Palmirani, M., Martoni, M., Rossi, A., Bartolini, C., & Robaldo, '
    'L. (2018). PrOnto: Privacy ontology for legal reasoning. In A. '
    'Ko & E. Francesconi (Eds.), Electronic Government and the '
    'Information Systems Perspective (EGOVIS 2018) (pp. 139-152). '
    'Springer. https://doi.org/10.1007/978-3-319-98349-3_11',

    'Rackauckas, Z. (2024). RAG-Fusion: A new take on '
    'retrieval-augmented generation. International Journal on Natural '
    'Language Computing, 13(1), 37-47. '
    'https://arxiv.org/abs/2402.03367',

    'Securiti. (n.d.). Bahrain Personal Data Protection Law solution. '
    'https://securiti.ai/solutions/bahrain-pdpl/',

    'Shinn, N., Cassano, F., Berman, E., Gopinath, A., Narasimhan, '
    'K., & Yao, S. (2023). Reflexion: Language agents with verbal '
    'reinforcement learning. In Advances in Neural Information '
    'Processing Systems 36 (pp. 8634-8652). '
    'https://proceedings.neurips.cc/paper_files/paper/2023/hash/'
    '1b44b878bb782e6954cd888628510e90-Abstract-Conference.html',

    'SmartSuite. (2025). OneTrust pricing: Is it worth it in 2026? '
    'https://www.smartsuite.com/blog/onetrust-pricing',

    'Sonani, R., & Lohalekar, P. (2025). Machine learning-driven '
    'convergence analysis in multijurisdictional compliance using '
    'BERT and K-means clustering (arXiv:2502.10413). arXiv. '
    'https://arxiv.org/abs/2502.10413',

    'Sprinto. (2025). Honest OneTrust review 2025: Features, pricing, '
    'and alternatives. https://sprinto.com/blog/onetrust-review/',

    'Tamber, M. S., Bao, F. S., Xu, C., Luo, G., Kazi, S., Bae, M., '
    'Li, M., Mendelevitch, O., Qu, R., & Lin, J. (2025). Benchmarking '
    'LLM faithfulness in RAG with evolving leaderboards. In Findings '
    'of the Association for Computational Linguistics: EMNLP 2025 '
    'Industry Track. https://arxiv.org/abs/2505.04847',

    'Tang, L., Laban, P., & Durrett, G. (2024). MiniCheck: Efficient '
    'fact-checking of LLMs on grounding documents. In Proceedings of '
    'the 2024 Conference on Empirical Methods in Natural Language '
    'Processing (pp. 8818-8847). Association for Computational '
    'Linguistics. https://aclanthology.org/2024.emnlp-main.499/',

    'Tarandach, I., & Coles, M. J. (2020). Threat modeling: A '
    'practical guide for development teams. O\'Reilly Media.',

    'Temoshok, D., Proud-Madruga, D., Choong, Y.-Y., Galluzzo, R., '
    'Gupta, S., LaSalle, C., Lefkovitz, N., & Regenscheid, A. (2025). '
    'Digital identity guidelines (NIST Special Publication 800-63-4). '
    'National Institute of Standards and Technology. '
    'https://doi.org/10.6028/NIST.SP.800-63-4',

    'Thakur, N., Reimers, N., Ruckle, A., Srivastava, A., & Gurevych, '
    'I. (2021). BEIR: A heterogeneous benchmark for zero-shot '
    'evaluation of information retrieval models. In Proceedings of '
    'the 35th Conference on Neural Information Processing Systems: '
    'Datasets and Benchmarks Track. '
    'https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/'
    'hash/65b9eea6e1cc6bb9f0cd2a47751a186f-Abstract-round2.html',

    'TrustArc. (2026). TrustArc software review 2026: Features, '
    'reviews, integrations, pros & cons. Capterra. '
    'https://www.capterra.com/p/174544/TrustArc/',

    'Wallat, J., Lange, T., Anand, A., & de Rijke, M. (2025). '
    'Correctness is not faithfulness in retrieval-augmented '
    'generation attributions. In Proceedings of the 2025 '
    'International ACM SIGIR Conference on Innovative Concepts and '
    'Theories in Information Retrieval. '
    'https://doi.org/10.1145/3731120.3744592',

    'Wen, T., Wang, C., Yang, X., Tang, H., Xie, Y., Lyu, L., Dou, '
    'Z., & Wu, F. (2025). Defending against indirect prompt injection '
    'by instruction detection. In Findings of the Association for '
    'Computational Linguistics: EMNLP 2025 (pp. 19472-19487). '
    'Association for Computational Linguistics. '
    'https://aclanthology.org/2025.findings-emnlp.1060/',

    'West, M., & Sartori, A. (2024). Content Security Policy Level 3 '
    '(W3C Working Draft, 22 November 2024). World Wide Web '
    'Consortium. https://www.w3.org/TR/2024/WD-CSP3-20241122/',

    'Wilson, S., Schaub, F., Dara, A. A., Liu, F., Cherivirala, S., '
    'Leon, P. G., Andersen, M. S., Zimmeck, S., Sathyendra, K. M., '
    'Russell, N. C., Norton, T. B., Hovy, E., Reidenberg, J. R., & '
    'Sadeh, N. (2016). The creation and analysis of a website '
    'privacy policy corpus. In Proceedings of the 54th Annual '
    'Meeting of the Association for Computational Linguistics '
    '(pp. 1330-1340). Association for Computational Linguistics. '
    'https://doi.org/10.18653/v1/P16-1126',

    'Wiratunga, N., Abeyratne, R., Jayawardena, L., Martin, K., '
    'Massie, S., Nkisi-Orji, I., Weerasinghe, R., Liret, A., & '
    'Fleisch, B. (2024). CBR-RAG: Case-based reasoning for retrieval '
    'augmented generation in LLMs for legal question answering. In '
    'Case-Based Reasoning Research and Development (ICCBR 2024) '
    '(Lecture Notes in Computer Science 14775, pp. 445-460). '
    'Springer. https://doi.org/10.1007/978-3-031-63646-2_29',

    'Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., '
    '& Cao, Y. (2023). ReAct: Synergizing reasoning and acting in '
    'language models. In Proceedings of the 11th International '
    'Conference on Learning Representations. '
    'https://openreview.net/forum?id=WE_vluYUL-X',

    'Zhang, J., Xiang, J., Yu, Z., Teng, F., Chen, X., Chen, J., '
    'Zhuge, M., Cheng, X., Hong, S., Wang, J., Zheng, B., Liu, B., '
    'Luo, Y., & Wu, C. (2025). AFlow: Automating agentic workflow '
    'generation [Conference paper]. International Conference on '
    'Learning Representations (ICLR) 2025. '
    'https://arxiv.org/abs/2410.10762',
]


def main():
    base = Path(__file__).resolve().parents[2]
    out_dir = base / 'thesis_docs'
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / 'references_apa7.docx'

    if out_path.exists():
        try:
            with open(out_path, 'ab'):
                pass
        except PermissionError:
            for n in range(2, 100):
                candidate = out_dir / f'references_apa7_v{n}.docx'
                if not candidate.exists():
                    out_path = candidate
                    break

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    # Heading
    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = h.add_run('References')
    run.font.bold = True
    run.font.size = Pt(14)
    run.font.color.rgb = NAVY
    h.paragraph_format.space_after = Pt(14)

    # Hanging-indent paragraphs (APA 7)
    for ref in REFERENCES:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(1.0)
        p.paragraph_format.first_line_indent = Cm(-1.0)
        p.paragraph_format.space_after = Pt(8)
        p.paragraph_format.line_spacing = 1.15
        r = p.add_run(ref)
        r.font.color.rgb = BLACK
        r.font.size = Pt(11)

    doc.save(out_path)
    print(f'Wrote {len(REFERENCES)} references to {out_path}')


if __name__ == '__main__':
    main()
