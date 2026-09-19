from __future__ import annotations

from collections.abc import Iterable

from julius.cli._common import console, error_console
from julius.domain.formatting import plural
from julius.domain.models import Hint, HintKind

# {details} is the hint's details joined by " · " ("nenhuma" when empty). {count}/{s} are only set
# when details is a single digit string (see print_hints) -- {s} is "" or "s", for templates whose
# only variation between one and many is the trailing "s" (reused for every word that needs it).
# FIRST_IMPORT_NAME_STORES and SAME_CHAIN_BRANCHES are not here: _RENAME_HINTS renders those, one
# ready `renomear` command per line, because a command joined into a single "Dica:" line can't be
# copy-pasted on its own.
TEXTS: dict[HintKind, str] = {
    "NO_RECEIPTS_IMPORTED": "Nenhum recibo importado ainda. Comece com: julius importar ARQUIVO.html",
    "NO_MATCH_DID_YOU_MEAN": "Nenhum produto bate com esse nome. Parecidos: {details}",
    "NO_MATCH_TRY_TAGS": (
        "Nenhum produto com nome parecido. A busca é por nome, não por categoria; pra agrupar (ex.: carne), "
        "marque cada produto com julius produtos tag ID carne e consulte com julius consultar --tag carne. "
        "Tags que já existem: {details}"
    ),
    "UNKNOWN_TAG": "Essa tag não existe. Tags atuais: {details}. Crie uma com: julius produtos tag ID TAG",
    "PACKAGE_SIZE_IN_DESCRIPTION": (
        "Produtos novos com tamanho no nome: {details}. Pra comparar por litro/kg/unidade: "
        "julius produtos definir-conteudo ID QTD UNIDADE"
    ),
    "IMPORT_FILE_NOT_FOUND": (
        "Arquivo não encontrado: {details}. Se usou *.html, nenhum arquivo casou com o padrão nessa pasta."
    ),
    "IMPORT_NOT_A_RECEIPT": (
        "{details} não parece a página de NFC-e da Receita/DF salva como HTML (PDF e .har não servem). "
        'Abra o link do QR code no navegador e use "Salvar página como…".'
    ),
    "IMPORT_UNKNOWN_UNIT": (
        "Código de unidade novo: {details}. Adicione uma linha em UNIT_MAP (julius/domain/normalization.py). "
        "O import desse arquivo foi ignorado, nada gravado."
    ),
    "AI_NOT_CONFIGURED": (
        "Pra ter a opinião da IA, defina JULIUS_AI_API_KEY, JULIUS_AI_BASE_URL, JULIUS_AI_MODEL, "
        "JULIUS_AI_INPUT_PRICE_USD_PER_1M e JULIUS_AI_OUTPUT_PRICE_USD_PER_1M (ver README)."
    ),
    "PRODUCTS_PENDING_REVIEW": (
        "{count} produto{s} novo{s} sem categoria. Nome legível, categoria e conteúdo com ajuda da IA: "
        "julius produtos revisar"
    ),
    "FOUND_VIA_AI": (
        "Encontrado pela IA, não pelo nome: {details}. Pra achar direto na próxima, renomeie ou marque: "
        'julius produtos renomear ID "Nome" / julius produtos tag ID TAG'
    ),
}

# Intro sentence for the two hints rendered as a ready command per line (see TEXTS docstring above).
_RENAME_HINTS: dict[HintKind, str] = {
    "FIRST_IMPORT_NAME_STORES": "ainda com a razão social como nome",
    "SAME_CHAIN_BRANCHES": "de filiais da mesma rede sem apelido",
}


def _rename_command(detail: str) -> str:
    """`detail` is "cnpj\\tapelido sugerido" -- see `guidance.py::_naming_detail`. Building the
    literal CLI command here, not in guidance.py, keeps command syntax owned by the CLI layer."""
    cnpj, nickname = detail.split("\t", 1)
    return f'julius mercados renomear {cnpj} "{nickname}"'


def print_hints(hints: Iterable[Hint], *, to_stderr: bool = False) -> None:
    target = error_console if to_stderr else console
    for hint in hints:
        if hint.kind in _RENAME_HINTS:
            count = len(hint.details)
            target.print(
                f"Dica: {count} {plural(count, 'mercado')} {_RENAME_HINTS[hint.kind]}:",
                style="dim", markup=False, highlight=False,
            )
            for detail in hint.details:
                # soft_wrap keeps the command on one line so it can be copied as is.
                target.print(f"  {_rename_command(detail)}", style="dim", markup=False, highlight=False, soft_wrap=True)
            continue
        template = TEXTS.get(hint.kind)
        if template is None:
            continue
        kwargs: dict[str, object] = {"details": " · ".join(hint.details) or "nenhuma"}
        if len(hint.details) == 1 and hint.details[0].isdigit():
            count = int(hint.details[0])
            kwargs["count"] = count
            kwargs["s"] = "" if count == 1 else "s"
        line = "Dica: " + template.format(**kwargs)
        # soft_wrap keeps each suggested command on one line so it can be copied as is.
        target.print(line, style="dim", markup=False, highlight=False, soft_wrap=True)
