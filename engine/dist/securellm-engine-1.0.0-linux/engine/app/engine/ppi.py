"""Wave 1 — Proprietary/Product Information (PPI) anonymization.

Adapted from openclaw/bot/pii.js.  Replaces customer-specific proprietary
terms (product names, trademarks, brand names) with [PRODUCT_N] placeholders.

Each workspace can inject its own PPI term list, stored in Redis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Default ALE PPI terms (from openclaw) ────────────────

DEFAULT_PPI_TERMS: list[str] = [
    # Company names
    "Alcatel-Lucent Enterprise USA Inc.", "Alcatel-Lucent Enterprise", "ALE International",
    "ALE USA Inc.", "Alcatel-Lucent", "Nokia",
    # Trademarks with class designations
    "OPENTOUCH (cl. 09) (2nd filing)", "OPENTOUCH (cl. 09 & 38)",
    "OMNIACCESS (cl. 09)", "OMNIPCX (cl. 09)", "OMNIPCX (cl. 38)", "OMNIPCX (cl. 42)",
    "OMNITOUCH (cl. 09)", "OMNIVISTA (cl. 09)", "OPENTOUCH (cl. 09)", "OPENTOUCH (cl. 38)",
    "OPENTOUCH (cl.09)", "Rainbow (cl.38)", "Rainbow (cl.42)",
    "ALE (cl. 09)", "ALE (cl. 38)", "ALE (cl. 42)",
    # Full product names
    "OmniVista 8770 Network Management System", "OmniVista Network Management Platform",
    "OmniVista Network Advisor", "OmniVista Smart Tool",
    "OmniPCX Enterprise Communication Server", "OmniPCX Open Gateway", "OmniPCX RECORD Suite",
    "OpenTouch Enterprise Cloud", "OpenTouch Session Border Controller", "OpenTouch Conversation®",
    "OmniAccess Stellar AP1570 Series", "OmniAccess Stellar AP1360 Series",
    "OmniAccess Stellar AP1320-Series", "OmniAccess Stellar Asset Tracking",
    "OmniAccess Stellar AP1261", "OmniAccess Stellar AP1301H", "OmniAccess Stellar AP1301",
    "OmniAccess Stellar AP1311", "OmniAccess Stellar AP1331", "OmniAccess Stellar AP1351",
    "OmniAccess Stellar AP1411", "OmniAccess Stellar AP1431", "OmniAccess Stellar AP1451",
    "OmniAccess Stellar AP1501", "OmniAccess Stellar AP1511", "OmniAccess Stellar AP1521",
    "OmniAccess Stellar AP1561",
    "OmniSwitch Milestone Plugin",
    "OmniSwitch 6860(E and N)", "OmniSwitch 6560(E)",
    "OmniSwitch 2260", "OmniSwitch 2360", "OmniSwitch 6360", "OmniSwitch 6465T",
    "OmniSwitch 6465", "OmniSwitch 6570M", "OmniSwitch 6575", "OmniSwitch 6865",
    "OmniSwitch 6870", "OmniSwitch 6900", "OmniSwitch 6920", "OmniSwitch 9900",
    "SIP-DECT Base Stations", "DECT Base Stations", "SIP-DECT Handsets", "DECT Handsets",
    "WLAN Handsets", "Aries Series Headsets",
    "IP Desktop Softphone", "ALE SIP Deskphones", "ALE DeskPhones", "Smart DeskPhones",
    "Visual Automated Attendant", "Dispatch Console",
    "Rainbow Developer Platform", "Rainbow App Connector", "Rainbow Hospitality",
    "Rainbow cloud", "Rainbow open",
    "Unified Management Center", "Fleet Supervision",
    "Digital Age Networking", "Digital Age Communications",
    "Shortest Path Bridging (SPB)", "Purple on Demand", "SD-WAN & SASE",
    "Autonomous Network", "Hybrid POL", "OmniFabric",
    "WHERE EVERYTHING CONNECTS", "WO SICH ALLES VERBINDET", "Where Everything Connects",
    "R Rainbow (semi-figurative)", "R (semi-figurative)",
    "EXPERIENCE DAYS", "Enterprise Rainbow",
    "OXO Connect", "ALE Connect", "ALE Softphone",
    "OpenTouch Conversation", "OPENTOUCH CONVERSATION",
    # Core brand names / trademarks
    "al-enterprise.com",
    "IP Touch®", "My IC Phone®", "OmniAccess®", "OmniPCX®", "OmniSwitch®",
    "OmniTouch®", "OmniVista®", "OpenTouch®", "Rainbow™",
    "OMNIACCESS", "OMNIPCX", "OMNISTACK", "OMNISWITCH", "OMNITOUCH", "OMNIVISTA",
    "OPENTOUCH", "MY TEAMWORK", "MY IC PHONE", "IP TOUCH", "PIMPHONY", "PIMphony",
    "PAPILLON", "SUNBOW", "BLOOM", "Sipwse",
    "OpenRainbow", "Rainbow", "ALE",
]


def _escape_regex(s: str) -> str:
    return re.escape(s)


@dataclass
class PPIAnonymizer:
    """Stateful PPI anonymizer scoped to a workspace."""

    terms: list[str] = field(default_factory=lambda: list(DEFAULT_PPI_TERMS))

    def __post_init__(self) -> None:
        # Sort longest-first for greedy matching
        self.terms.sort(key=len, reverse=True)

    def anonymize(self, text: str) -> tuple[str, dict[str, str]]:
        """Replace PPI terms with [PRODUCT_N] placeholders.

        Returns (anonymized_text, mapping).
        """
        mapping: dict[str, str] = {}
        counter = 0
        result = text

        for term in self.terms:
            pattern = re.compile(_escape_regex(term), re.IGNORECASE)
            offset = 0
            for m in pattern.finditer(result):
                start = m.start() + offset
                end = m.end() + offset
                counter += 1
                placeholder = f"[PRODUCT_{counter}]"
                mapping[placeholder] = result[start:end]
                result = result[:start] + placeholder + result[end:]
                offset += len(placeholder) - (m.end() - m.start())
                # Re-search from after this placeholder on next iteration
            # After replacing all occurrences of this term, continue to next term

        return result, mapping

    @staticmethod
    def deanonymize(text: str, mapping: dict[str, str]) -> str:
        """Restore [PRODUCT_N] placeholders to original values."""
        if not mapping:
            return text
        result = text
        for ph in sorted(mapping.keys(), key=len, reverse=True):
            result = result.replace(ph, mapping[ph])
        return result
