from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# One provider, not three. The four public providers measured (BrasilAPI, ReceitaWS, CNPJá,
# publica.cnpj.ws, minhareceita) returned identical values for the same CNPJ — including the
# identical absence — because they all derive from the Receita Federal open dataset. Racing
# several buys uptime, never coverage, and this lookup only runs when a new store appears
# (5 stores in months of use): a failure just means the store keeps its legal name and shows
# up in the rename hint again, which is today's behaviour. See docs/requirements/
# store-branch-nickname.md §7.2.
BASE_URL = "https://brasilapi.com.br/api/cnpj/v1"


def fetch_trade_name(cnpj: str, *, timeout_seconds: float = 10.0) -> str | None:
    """The trade name (nome fantasia) on record for a CNPJ, or None when the registry has none.

    Never raises: any network, HTTP or payload problem reads as "no trade name", the same way the
    LLM client turns every failure into an empty answer. The field is declaratory and optional, so
    an empty value is a normal answer, not an error (measured: empty for SENDAS/Assaí).
    """
    request = Request(
        f"{BASE_URL}/{cnpj}",
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "julius/1.0"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if not 200 <= response.status < 300:
                return None
            payload = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    trade_name = payload.get("nome_fantasia")
    if not isinstance(trade_name, str):
        return None
    # Kept verbatim, like stores.address: it is display text from an outside source, and this
    # project does not invent casing rules (str.title() mangles "FL 3" and "S/A").
    return trade_name.strip() or None
