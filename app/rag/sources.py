# app/rag/sources.py
from __future__ import annotations

RAG_SOURCES = [
    # USCIS Policy Manual EB-1A
    {
        "kind": "policy_manual",
        "title": "USCIS Policy Manual: Extraordinary Ability (EB-1A)",
        "url": "https://www.uscis.gov/policy-manual/volume-6-part-f-chapter-2",
    },

    # EB-1 overview
    {
        "kind": "uscis_overview",
        "title": "USCIS EB-1: Priority Workers",
        "url": "https://www.uscis.gov/working-in-the-united-states/permanent-workers/employment-based-immigration-first-preference-eb-1",
    },

    # Form I-140
    {
        "kind": "form_i140",
        "title": "Form I-140 (Immigrant Petition for Alien Worker)",
        "url": "https://www.uscis.gov/i-140",
    },

    # Premium processing I-907
    {
        "kind": "form_i907",
        "title": "Form I-907 (Request for Premium Processing Service)",
        "url": "https://www.uscis.gov/i-907",
    },

    # Fees + calculator
    {
        "kind": "fees",
        "title": "USCIS Fee Calculator",
        "url": "https://www.uscis.gov/feecalculator",
    },
    {
        "kind": "fees",
        "title": "USCIS Filing Fees",
        "url": "https://www.uscis.gov/forms/filing-fees",
    },

    # Filing addresses (на практике иногда отдельные страницы/разделы внутри формы)
    {
        "kind": "filing",
        "title": "USCIS Direct Filing Addresses (Forms)",
        "url": "https://www.uscis.gov/forms/direct-filing-addresses",
    },

    # CFR (если будешь подтягивать с eCFR — удобно для точных цитат)
    {
        "kind": "cfr",
        "title": "eCFR 8 CFR 204.5 (Immigrant petitions)",
        "url": "https://www.ecfr.gov/current/title-8/chapter-I/subchapter-B/part-204/section-204.5",
    },
]
