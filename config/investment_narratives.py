"""Long-term research prompts for the dashboard narrative panel.

These prompts describe what would matter to an investing thesis over years.
They are not live news summaries, price predictions, or trading signals.
"""

from __future__ import annotations


INVESTMENT_NARRATIVES: dict[str, dict[str, object]] = {
    "SPY": {
        "asset_type": "Broad market ETF",
        "thesis_focus": "Track the durability of broad U.S. corporate earnings and economic conditions rather than individual headlines.",
        "monitoring_themes": [
            {"label": "Earnings breadth", "detail": "Whether profit growth extends beyond a small set of large companies."},
            {"label": "Rates and inflation", "detail": "Whether financing conditions support or pressure equity valuations."},
            {"label": "Economic resilience", "detail": "Employment and demand trends that can affect broad earnings power."},
        ],
        "review_questions": [
            "Is the long-term earnings base broadening or narrowing?",
            "Has the risk/reward changed enough to affect diversified exposure?",
        ],
    },
    "QQQ": {
        "asset_type": "Growth and technology ETF",
        "thesis_focus": "Monitor durable innovation-led earnings while recognizing concentration and valuation risk.",
        "monitoring_themes": [
            {"label": "Large-cap growth earnings", "detail": "Whether key holdings continue converting demand into cash flow."},
            {"label": "AI investment returns", "detail": "Whether large infrastructure spending produces lasting revenue growth."},
            {"label": "Valuation sensitivity", "detail": "Whether interest rates or crowded positioning pressure multiples."},
        ],
        "review_questions": [
            "Are growth expectations supported by reported results?",
            "Is concentration becoming a greater portfolio risk?",
        ],
    },
    "NVDA": {
        "asset_type": "Semiconductor company",
        "thesis_focus": "Evaluate whether AI-compute leadership can remain durable as spending cycles and competition evolve.",
        "monitoring_themes": [
            {"label": "Data-center demand", "detail": "Orders, guidance, and customer adoption of accelerator platforms."},
            {"label": "Margins and supply", "detail": "Pricing power and the ability to supply advanced products profitably."},
            {"label": "Competition and regulation", "detail": "Alternative chips, customer in-house designs, and export restrictions."},
        ],
        "review_questions": [
            "Is demand recurring enough to support the long-term thesis?",
            "Are competition or restrictions causing permanent impairment?",
        ],
    },
    "TSLA": {
        "asset_type": "Automotive and energy company",
        "thesis_focus": "Assess whether scale, software, and energy businesses offset vehicle competition and margin pressure.",
        "monitoring_themes": [
            {"label": "Deliveries and margins", "detail": "Whether volume growth is profitable rather than discount-driven."},
            {"label": "Autonomy execution", "detail": "Measured progress, regulatory approval, and monetizable capability."},
            {"label": "Competition and brand", "detail": "Market-share pressure and consumer demand across major regions."},
        ],
        "review_questions": [
            "Is the business becoming more profitable and diversified over time?",
            "Are key assumptions supported by reported operating results?",
        ],
    },
    "AMD": {
        "asset_type": "Semiconductor company",
        "thesis_focus": "Monitor durable share gains and AI accelerator opportunity against strong semiconductor competition.",
        "monitoring_themes": [
            {"label": "Server market share", "detail": "Adoption and profitability of data-center CPU products."},
            {"label": "AI accelerator traction", "detail": "Customer wins and revenue durability in AI compute."},
            {"label": "Gross margin discipline", "detail": "Whether product mix improves long-run earnings quality."},
        ],
        "review_questions": [
            "Are product wins becoming recurring earnings power?",
            "Has competition weakened the long-term opportunity?",
        ],
    },
    "AAPL": {
        "asset_type": "Consumer technology company",
        "thesis_focus": "Watch whether the installed-base ecosystem continues producing durable cash flow and defensible demand.",
        "monitoring_themes": [
            {"label": "Device and services demand", "detail": "Upgrade cycles and recurring services growth across the ecosystem."},
            {"label": "Margins and capital returns", "detail": "Cash generation, buybacks, and durability of premium pricing."},
            {"label": "Regulation and supply chain", "detail": "Platform restrictions, geographic demand, and manufacturing exposure."},
        ],
        "review_questions": [
            "Is ecosystem loyalty continuing to translate into earnings?",
            "Do regulation or supply risks materially alter the thesis?",
        ],
    },
}
