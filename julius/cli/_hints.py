from __future__ import annotations

from collections.abc import Iterable

from julius.cli._common import console, error_console
from julius.domain.models import Hint, HintKind

# {details} is the hint's details joined by ", " ("nenhuma" when empty). Only source of hint wording.
TEXTS: dict[HintKind, str] = {
    "NO_RECEIPTS_IMPORTED": "Nenhum recibo importado ainda. Comece com: julius importar ARQUIVO.html",
    "NO_MATCH_DID_YOU_MEAN": "Nenhum produto bate com esse nome. Parecidos: {details}",
    "NO_MATCH_TRY_TAGS": (
        "Nenhum produto com nome parecido. A busca é por nome, não por categoria; pra agrupar (ex.: carne), "
        "marque cada produto com julius produtos tag ID carne e consulte com julius consultar --tag carne. "
        "Tags que já existem: {details}"
    ),
    "UNKNOWN_TAG": "Essa tag não existe. Tags atuais: {details}. Crie uma com: julius produtos tag ID TAG",
    "FIRST_IMPORT_NAME_STORES": (
        "{details} mercado(s) ainda com a razão social como nome. Dê apelidos: "
        'julius mercados listar e depois julius mercados renomear CNPJ "Apelido"'
    ),
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
}


def print_hints(hints: Iterable[Hint], *, to_stderr: bool = False) -> None:
    target = error_console if to_stderr else console
    for hint in hints:
        template = TEXTS.get(hint.kind)
        if template is None:
            continue
        line = "Dica: " + template.format(details=", ".join(hint.details) or "nenhuma")
        # soft_wrap keeps each suggested command on one line so it can be copied as is.
        target.print(line, style="dim", markup=False, highlight=False, soft_wrap=True)
