"""Held-out corpus for RAG overfitting check (2026-04-23).

Purpose
-------
`observe_rag_confidence.py` Section VI was used during 7a development (parser
prompt strengthening). Because the same corpus served as both diagnostic
source and evaluation target, the resulting gains may reflect prompt
overfitting rather than true generalization.

This fixture holds a separate set of 20 production first-inquiries
(`production_conversation_first_inquiries_sample20_v2.csv`, user-provided on
2026-04-23) that were NOT seen during 7a prompt iteration. Running the same
e2e pipeline against these yields an unbiased measurement.

Overlap analysis vs. v1 Section VI few-shots
--------------------------------------------
The 7a prompt carries 5 few-shot examples. None of the 20 v2 queries match
them verbatim, but three are structural neighbors worth watching:

  - v2 idx 11 (rat anti pimonidazole monoclonal) ~ "rabbit polyclonal"
    few-shot. Tests species/type generalization.
  - v2 idx 14 (bacteria-produced 84kDa protein for mouse) ~ "bacterial
    polyclonal" few-shot but different intent (protein_expression, not
    antibody). Tests whether the few-shot hijacks unrelated bacterial
    queries.
  - v2 idx 18 (oncologist database spam) ~ "investment spam" few-shot.
    Different spam pattern — tests spam-rejection generalization.

The remaining 17 are out-of-distribution relative to the 7a few-shots.

ctx policy
----------
Cold-start simulation: the only context passed is `business_line_hint`,
derived from `products_of_interest` (preferred) or `service_of_interest`
using this mapping:

  - "Monoclonal Antibodies" / "Human Monoclonal Antibodies" /
    "Bispecific Antibodies" / "Antibody Production"   -> antibody
  - "mRNA / LNP" / "mRNA / LNP Production"             -> mrna_lnp
  - "CAR-T Cells" / "Custom CAR-Macrophage Development"-> car_t_car_nk
  - "Stable Cell Line Development"                     -> protein_expression
  - "Animal Research" / empty                          -> "" (no hint)

Category hypotheses (high/medium/low/irrelevant) are predictions of where
the confidence distribution *should* land. They are NOT ground truth — the
observation decides whether reality matches.
"""
from __future__ import annotations

from typing import Any

CORPUS_HELDOUT_V2: list[tuple[str, str, dict[str, Any]]] = [
    # 1. Sarah Mansour, Emory — stable cell line for 84kDa protein, can't
    #    generate clones. Technical and specific.
    ("high",
     "Hello. I would like to receive a quote for the generation of a stable "
     "cell line expressing a 84kDa protein of interest in HEK293F cells or "
     "BHK cells. I can provide the plasmid. The protein readily expresses "
     "following a standard lipofectamine 3000 transfection procedure. "
     "However, we are unable to generate any stable clones.",
     {"business_line_hint": "protein_expression"}),

    # 2. Hiroko Masamune, Lassogen — extremely generic antibody synthesis.
    #    Should be low (needs clarification) but has antibody hint.
    ("low",
     "I am interested in a specific antibody synthesis.",
     {"business_line_hint": "antibody"}),

    # 3. Dianna DeVore, MBrace — custom mAb with proprietary CHO cells.
    ("high",
     "Hi, we are interested in custom monoclonal antibody production, but "
     "would need to use our own proprietary CHO cells - is that possible?",
     {"business_line_hint": "antibody"}),

    # 4. Kathleen Anders, Charite — antibody against neuroblastoma antigen,
    #    asks about services and budget. Semi-specific.
    ("medium",
     "Our group in Berlin is interested in developing a new antibody against "
     "an antigen expressed in neuroblastoma. We would like to know more about "
     "your services and get information about what budget we have to consider.",
     {"business_line_hint": "antibody"}),

    # 5. Patricia Hahn, Scripps — quote for 0.80 mg mRNA/LNP. Specific quantity.
    ("high",
     "Hi, we're interested in getting a quote for the production of around "
     "0.80 mg of mRNA/LNP.",
     {"business_line_hint": "mrna_lnp"}),

    # 6. Anna Deych, Celltzer — T-cell specificity assay, asks what to provide.
    #    No business_line hint (form empty).
    ("medium",
     "Hello, I am the Director of Business Development of an emerging company. "
     "We are looking for a quote on T-cell specificity assay. Please let us "
     "know what we need to provide as the basis for the quote.",
     {}),

    # 7. Chi Zhang, MIT — 20 custom lipids, mRNA LNP biodistribution in mice.
    #    Very specific technical intent.
    ("high",
     "We have ~20 custom lipids that we would like to formulate into mRNA "
     "lipid nanoparticles and we would like to test the resulting LNPs' "
     "biodistribution in mice.",
     {"business_line_hint": "mrna_lnp"}),

    # 8. Marjolijn, UMCG — bispecific HER2/4-1BB + two monospecific controls,
    #    50 mg each. Highly specific.
    ("high",
     "Could you give a kind of ballpark indication of the costs for a "
     "bispecific antibody (HER2/4-1BB) and two matching monospecific controls "
     "(HER2/xx), (xx/4-1BB), around 50 mg each.",
     {"business_line_hint": "antibody"}),

    # 9. Yakir Ophir, Cornell — one-line mAb inquiry. Extreme generic.
    ("low",
     "I am interested in developing new monoclonal antibodies.",
     {"business_line_hint": "antibody"}),

    # 10. Sophie de Seigneux, HUG — follow-up complaint about non-responsive
    #     coworker Ju Yeon Lee. NOT a technical inquiry; triage intent.
    ("low",
     "I was in contact with one of your coworker for synthesis of LNPs. "
     "She does not answer my emails anymore. I have questions to ask to one "
     "of you coworker. Would you be available?",
     {"business_line_hint": "mrna_lnp"}),

    # 11. Scott Raleigh, Hypoxyprobe — repeat order of rat anti-pimonidazole
    #     monoclonal. Structurally close to "rabbit polyclonal" few-shot.
    ("high",
     "We need more rat anti pimonidazole monoclonal antibody made please.",
     {"business_line_hint": "antibody"}),

    # 12. Alissa O'Connor, Alamar — hybridoma antibody sequencing quote.
    ("high",
     "We would like a quote for Hybridoma antibody sequencing services. "
     "Currently we have one mouse hybridoma cell line containing a mouse "
     "monoclonal antibody that needs to be sequenced. Would you provide "
     "quotes for the sequencing?",
     {}),

    # 13. Sagar Lahiri, Spectral — mouse ascites production for existing mAb.
    ("high",
     "Hi, I am interested to know the price of producing mouse ascites for "
     "one of our monoclonal antibodies.",
     {"business_line_hint": "antibody"}),

    # 14. Magali, Cedars-Sinai — E.coli protein expression (84kDa) for mouse
    #     model. Form field says CAR-Macrophage but intent is protein_expression.
    #     Structural neighbor to "bacterial polyclonal" few-shot but different
    #     intent — critical test for prompt not confusing protein with antibody.
    ("high",
     "We would like to see if it would be possible to produce a custom "
     "protein (84kDA) produced by a bacteria to use in a mouse model.",
     {"business_line_hint": "car_t_car_nk"}),

    # 15. Anna Bousquet, Ahus — asks about cost for therapeutic-use human
    #     antibody. Semi-specific (compliance/intent, no technical details).
    ("medium",
     "Hi, I noticed the approximate costs for custom human antibodies listed "
     "on your website. Could you please clarify how these costs might differ "
     "if the antibody is intended for therapeutic use? I understand that you "
     "might need more specifics, but I'm currently unable to provide detailed "
     "information. I'm just looking to get an approximate idea at this stage.",
     {"business_line_hint": "antibody"}),

    # 16. Lucas, CuraCell — one-line purchase inquiry for CAR-T vials.
    ("medium",
     "Hey, would like to buy some vials of CAR-T cells.",
     {"business_line_hint": "car_t_car_nk"}),

    # 17. Steven Bodovitz, GenEdit — mRNA-LNP bispecific antibody delivery
    #     study reference, ELISA validation. Rich technical context.
    ("high",
     "I am interested in your study using mRNA-LNPs To Deliver Bispecific "
     "Antibodies In Vivo For Anticancer Therapeutic Development. We have our "
     "own proprietary nanoparticle system and we'd like to test delivery of "
     "bispecific antibodies. Is it possible to purchase your mRNA encoding a "
     "bispecific antibody? Can we also purchase mRNA encoding monospecific "
     "antibodies? Do you also have an assay, such as an ELISA, to detect in "
     "vivo production of the antibodies?",
     {"business_line_hint": "mrna_lnp"}),

    # 18. Edward Mason — mailing-list (oncologist database) spam. Different
    #     pattern from "investment spam" few-shot.
    ("irrelevant",
     "Hi, Are you interested in acquiring database of 21,198 Oncologists "
     "with complete contact information for your upcoming trade show? Here "
     "are the counts based on sub-specialty: Dosimetry, Gynecologic "
     "Oncologist, Hematologist & Oncologist, Medical Oncologist, Oncologist, "
     "Radiation Oncologist, Surgical Oncologist. Total 21,198. All the "
     "contacts will have Company Name, Web Address, Contact Name, Title, "
     "Address, Phone Number, Email. Please let me know if you're interested. "
     "I can provide additional details, pricing, and a few samples for your "
     "review.",
     {}),

    # 19. Guruprasadh, NeuParadigmBio — multi-format recombinant antibody
    #     design (scFv-Fc, VHH-VHH-Fc, engineered fusion, cleavable linkers).
    ("high",
     "We are looking for specific help in design of Tandem scFv-Fc Format, "
     "VHH-VHH-Fc Format, Engineered Fusion Protein, Domain-Antibody Conjugate "
     "antibodies against two specific targets with ability to incorporate "
     "and stabilize the two target proteins with Cleavable and non-cleavable "
     "linker abilities.",
     {"business_line_hint": "antibody"}),

    # 20. Chuhua Zhong, Gencyte — stable cell pool for scFv-Fc fusion antibody.
    #     products="Monoclonal Antibodies" wins over service="Stable Cell Line".
    ("high",
     "We are seeking a CRO to generate a stable cell pool for the expression "
     "of an scFv-Fc fusion antibody.",
     {"business_line_hint": "antibody"}),
]
