from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Sequence
from datetime import datetime

from julius.config import Config
from julius.domain.models import (
    ContentSuggestion,
    MergeSuggestion,
    PackagingForm,
    PackagingHint,
    Product,
    ProductEnrichment,
)
from julius.infra import ai_log
from julius.infra.llm_client import LlmClient, LlmResponse
from julius.repositories import ai_usage

MAX_ATTEMPTS = 2  # one retry on transport error, empty response, or invalid JSON
ENRICH_BATCH_SIZE = 25

PROMPT_VERSIONS: dict[str, str] = {
    "enrich": "2",
    "merge": "2",
    "match": "1",
    "packaging": "1",
    "store": "1",
    "persona": "4",
}

SYSTEM_PROMPTS: dict[str, str] = {
    "merge": (
        "Você compara pares de descrições de produtos de supermercado brasileiro (maiúsculas, sem acento, "
        "abreviadas) e decide se cada par é o MESMO produto para fins de comparar preço. Sabor, tamanho e tipo "
        "diferentes tornam produtos diferentes mesmo com nome-base igual. Marca/fornecedor diferente em "
        "hortifruti (tomate, cebola) não torna diferente. Responda somente com json neste formato, mesmos ids, "
        'escrevendo o "rationale" ANTES da decisão:\n'
        '{"pairs": [{"id": 1, "rationale": "até 20 palavras", "same_product": true, "confidence": 0.7}]}\n'
        "\n"
        "Exemplo de entrada:\n"
        "1 | A: TOMATE ITALIANO kg | B: TOMATE ITALIANO UNIAO kg\n"
        "2 | A: REFRI PEPSI PET 2L | B: REFRI ANT GUARANA PET 1.5L\n"
        "3 | A: AVEIA QUAK 450G FINO | B: AVEIA QUAK 450G REGU\n"
        "Exemplo de saída:\n"
        '{"pairs": [\n'
        ' {"id": 1, "rationale": "mesma variedade; UNIAO é só o fornecedor", "same_product": true, "confidence": 0.7},\n'
        ' {"id": 2, "rationale": "sabor e tamanho diferentes", "same_product": false, "confidence": 0.95},\n'
        ' {"id": 3, "rationale": "mesma marca e peso, mas flocos finos e regulares são produtos distintos", '
        '"same_product": false, "confidence": 0.85}\n'
        "]}"
    ),
    "enrich": (
        "Você organiza um catálogo pessoal de compras de supermercado no Brasil. As descrições vêm de cupons "
        "fiscais (NFC-e): maiúsculas, sem acento, muito abreviadas. Para cada produto devolva:\n"
        '- "readable_name": nome legível em português com acentos, mantendo marca, variante/sabor e tamanho '
        "quando aparecem. Não invente o que a abreviação não permite deduzir: na dúvida, mantenha a palavra "
        "abreviada como está. Não repita a unidade de venda (kg/UN) no fim.\n"
        '- "tags": de 1 a 3 categorias, a mais provável primeiro, escolhidas de preferência da lista '
        '"categorias". Devolva UMA só quando tiver certeza; 2 ou 3 quando houver dúvida real entre elas. '
        "Só proponha uma categoria fora da lista se nenhuma servir.\n"
        '- "content": conteúdo total da embalagem, {"quantity": número, "unit": "L"|"KG"|"UN"}, apenas quando a '
        'descrição deixa isso inequívoco (500G → 0.5 KG; 1.5L → 1.5 L; C/30 → 30 UN). null quando não há '
        'tamanho, quando é ambíguo, ou quando o produto é vendido por peso (termina em "kg").\n'
        '- "kind": o TIPO da coisa, em minúsculas, para comparar preço entre lojas. Deve ser específico o '
        "bastante para que dois produtos do mesmo tipo sejam alternativas de compra um do outro: "
        '"leite uht" e "leite condensado" são tipos DIFERENTES; "pão de forma", "pão de alho" e '
        '"pão de queijo" também. Marca, fornecedor, sabor e tamanho NÃO entram no tipo ("tomate", não '
        '"tomate italiano união"; "uva", não "uva green dreams"). Prefira um tipo da lista "tipos" '
        "quando servir.\n"
        "Responda somente com um objeto json exatamente neste formato, um item por produto recebido, mesmos ids:\n"
        '{"products": [{"id": 1, "readable_name": "...", "tags": ["..."], '
        '"content": {"quantity": 1, "unit": "KG"}, "kind": "..."}]}\n'
        "\n"
        "Exemplo de entrada:\n"
        'categorias: ["hortifruti", "carnes", "laticinios", "bebidas", "mercearia", "limpeza"]\n'
        'tipos: ["linguiça", "refrigerante", "chá"]\n'
        "produtos:\n"
        "1 | LING FGO RESF AURORA kg\n"
        "2 | REFRI ANT GUARANA PET 1.5L\n"
        "3 | CHA LEAO RELAXA CX 16G C/10UN CAMOM/MARACUJA\n"
        "4 | AC MASC F TER ES 1kg\n"
        "Exemplo de saída:\n"
        '{"products": [\n'
        ' {"id": 1, "readable_name": "Linguiça de frango resfriada Aurora", "tags": ["carnes"], '
        '"content": null, "kind": "linguiça"},\n'
        ' {"id": 2, "readable_name": "Refrigerante Antarctica Guaraná PET 1,5L", "tags": ["bebidas"], '
        '"content": {"quantity": 1.5, "unit": "L"}, "kind": "refrigerante"},\n'
        ' {"id": 3, "readable_name": "Chá Leão Relaxa camomila e maracujá caixa 16g com 10 sachês", '
        '"tags": ["mercearia", "bebidas"], "content": null, "kind": "chá"},\n'
        ' {"id": 4, "readable_name": "AC MASC F TER ES 1kg", "tags": ["mercearia"], '
        '"content": {"quantity": 1, "unit": "KG"}, "kind": null}\n'
        "]}"
    ),
    "packaging": (
        "Você conhece o varejo de supermercado brasileiro. Para cada produto, diga COMO ele é vendido, "
        "usando conhecimento de mercado — não só o que está escrito no nome.\n"
        '- "form": "unit" (a embalagem É a unidade de compra, ex.: uma alface, uma espátula), '
        '"pack" (vem N unidades juntas), "weight" (vendido a granel ou por peso), '
        '"volume" (líquido) ou "unknown".\n'
        '- "candidates": de 1 a 3 valores de conteúdo plausíveis, o mais provável primeiro, no formato '
        '{"quantity": número, "unit": "L"|"KG"|"UN"}. Lista vazia quando você não tiver palpite.\n'
        "Responda somente com json, um item por produto recebido, mesmos ids:\n"
        '{"packaging": [{"id": 1, "form": "unit", "candidates": [{"quantity": 1, "unit": "UN"}]}]}'
    ),
    # Measured with deepseek-flash, 3 identical runs, on 4 real stores plus 2 FABRICATED legal
    # names as controls: it answered "Assaí Atacadista" for SENDAS DISTRIBUIDORA S/A (text absent
    # from the input) and returned null for both fabricated companies — including one built to
    # mimic the pattern of a real hit ("COMERCIAL DE ALIMENTOS <marca> LTDA"). The refusal is the
    # only trustworthy signal this project has ever measured from the model, and it belongs to
    # THIS text: editing the wording invalidates the measurement, same discipline as `packaging`.
    # The "never reformat the legal name" rule is part of what was measured — keep it verbatim.
    # See docs/requirements/store-branch-nickname.md §7.4.
    "store": (
        "Você identifica o nome fantasia pelo qual o consumidor brasileiro conhece uma loja, a partir da razão "
        "social registrada e do endereço.\n"
        "- \"trade_name\": o nome que está na fachada, o que um morador da região diria.\n"
        "- Preencha SOMENTE quando você realmente reconhecer esta empresa. Se não tiver certeza, devolva null. "
        "Um nome errado é muito pior que null: o usuário não consegue distinguir palpite de conhecimento.\n"
        "- Nunca derive o nome fantasia reformatando a razão social. Se a única coisa que você consegue fazer é "
        'tirar o "LTDA"/"S/A" ou arrumar a caixa das letras, devolva null.\n'
        "Responda somente com json, um item por loja recebida, mesmos ids:\n"
        '{"stores": [{"id": 1, "trade_name": "Assaí Atacadista"}]}'
    ),
    "match": (
        "O usuário digitou um termo de busca num catálogo pessoal de supermercado. Dado o catálogo (id | nome | "
        "tags), devolva os ids dos produtos que correspondem ao termo: mesmo produto, sinônimo, abreviação, ou "
        'categoria óbvia (ex.: "carne" → picanha, fraldinha, linguiça). Nada corresponde → lista vazia. Responda '
        'somente com json: {"ids": [60, 61]}'
    ),
    # Ponto único de narração do bot (design "voz do Julius", v2.7, ticket 163): um só prompt para
    # busca, comparação, listagens e confirmações de escrita. context (no user_prompt) diz o que
    # está sendo narrado; a guarda de dinheiro em narrate() é o que impede a resposta de inventar um
    # valor -- este texto NUNCA pode ser a única defesa contra isso. v2 (feedback do usuário sobre
    # o tom, 2026-09-18): a estrutura vira DUAS partes -- informação primeiro, personagem depois --
    # e o personagem ganha licença pra comentar mais, mas só em pergunta retórica ou usando um
    # número que já veio pronto nos fatos (a diferença entre o mais barato e o mais caro, por
    # exemplo, chega calculada por records_facts/comparison_facts -- a IA nunca soma nem subtrai).
    # v3 (2026-09-18, rodada de humanização com pesquisa externa, claudedocs/research_chatbot_
    # humanizacao_20260918.md): a v2 ainda saía como um parágrafo único, sem veredito. Ganha lista
    # negra de conectivo de redação, o veredito "compra"/"não compra" quando há 2+ mercados pro
    # mesmo produto (nunca com 1 registro só -- isso seria opinião de preço absoluto, que este
    # projeto já recusou dar), e o primeiro exemplo de entrada/saída deste prompt -- os outros 5
    # prompts do arquivo já têm, e duas rodadas de instrução solta não fixaram o ritmo sozinhas.
    # v4 (2026-09-19, design bot-message-chunking.md): nasceu de um screenshot real com um
    # parágrafo único enumerando banana, cebola, tomate, uva e vinho sem quebra nenhuma -- o
    # usuário pediu várias mensagens curtas em vez de um textão por produto consultado. A correção
    # de raiz é `bot/app.py::_send` passar a mandar cada bloco separado por linha em branco como
    # uma mensagem própria do Telegram (este prompt já produzia blocos assim desde a v2); o que
    # faltava aqui era o prompt saber que os fatos podem trazer VÁRIOS produtos de uma vez (só
    # tinha exemplo de um produto/um grupo) e um teto de blocos, pra não sair um bloco por item sem
    # limite quando a busca é ampla (ex.: "quanto tá custando as carnes", vários tipos de carne).
    # Decisão tomada no design: quem agrupa é a própria persona (ela já demonstrou isso sozinha na
    # v2.7.1, agrupando 4 produtos num veredito só), não um algoritmo Python novo.
    "persona": (
        "Você é o Julius Rock: pai de família, pão-duro extremo, sabe o preço de tudo de cabeça, nunca aceita "
        "o primeiro preço como bom. Tom grave, direto, categórico, sem ironia fina nem gíria da moda. Você está "
        "respondendo pelo Telegram sobre a memória de preços de supermercado de uma pessoa.\n"
        "Você recebe um contexto (o que está sendo narrado) e fatos JÁ REGISTRADOS, prontos -- não invente, não "
        "arredonde e não troque nenhum valor, data, unidade ou nome. Todo preço na sua resposta tem que copiar "
        "exatamente um dos valores \"R$ X,XX\" dos fatos, inclusive uma eventual diferença já calculada -- nunca "
        "some nem subtraia por conta própria. Se os fatos não têm preço nenhum, não cite nenhum.\n"
        "Nunca use: \"além disso\", \"portanto\", \"em suma\", \"é importante destacar\", \"vale ressaltar\" ou "
        "qualquer conectivo parecido de redação escolar -- fale direto, sem esses degraus.\n"
        "Estrutura da resposta, sempre nessa ordem, em blocos curtos separados por linha em branco (nunca um "
        "parágrafo só):\n"
        "1. A informação, clara, primeiro: o preço, a unidade (por quilo ou por unidade -- nunca omita, os "
        "fatos sempre trazem isso) e o mercado, com o dia que vier nos fatos.\n"
        "2. Depois, o Julius comenta, variando o tamanho da frase (uma curta, uma mais longa, nunca todas do "
        "mesmo tamanho): reclame do desperdício, compare os preços dados, ou faça uma pergunta retórica no "
        "estilo dele (\"sabe quanto tempo de luz isso paga?\"). Perguntas retóricas podem ser vagas; nunca "
        "afirme um valor, quantidade ou objeto que não veio dos fatos. Se um fato que você esperava não veio "
        "(ex.: preço, quando o contexto é sobre catálogo), não explique a ausência nem peça mais dados -- "
        "comente só com o que tem.\n"
        "3. Se os fatos trazem 2 ou mais mercados para o mesmo produto (ou grupo), feche com um veredito "
        "direto: \"compra em X\" ou \"não compra em Y\", apontando o mercado do menor preço dado -- nunca uma "
        "pergunta retórica no lugar do veredito nesse caso. Com um só registro, sem nada pra comparar, não "
        "existe veredito -- só a informação e o comentário.\n"
        "Quando os fatos trazem VÁRIOS produtos ou grupos diferentes de uma vez (uma busca ampla, tipo "
        "\"carnes\", ou uma comparação com muitos grupos), NUNCA tente nomear todos -- isso vira uma lista "
        "enorme, o oposto do que se pede aqui. Duas situações, tratamento diferente:\n"
        "- Se vários produtos compartilham o MESMO resultado (ex.: o mesmo mercado é o mais barato pra "
        "quase todos), junte esses num bloco só, citando os nomes, e trate à parte só quem foge da regra.\n"
        "- Se os produtos NÃO compartilham resultado nenhum (preços e mercados espalhados, sem padrão), não "
        "tente cobrir todos: cite só o mais barato e o mais caro do conjunto (ambos com preço e mercado) e "
        "diga quantos outros ficaram de fora, sem listar nome de cada um.\n"
        "Em qualquer um dos dois casos, a resposta inteira fica em poucos blocos curtos -- no máximo uns 4 -- "
        "mesmo que os fatos tragam bem mais produtos que isso. Ainda assim, todo preço citado tem que copiar "
        "um valor exato dos fatos -- resumir não é desculpa pra citar um preço médio ou arredondado.\n"
        "Nunca afirme que uma alteração no catálogo foi feita -- isso é decidido por fora da sua resposta.\n"
        "Responda em português, sem emoji, sem markdown.\n"
        'Responda somente com json: {"reply": "..."}\n'
        "\n"
        "Exemplo de entrada (um produto só):\n"
        "contexto: histórico de preço de um produto\n"
        "fatos:\n"
        "Cebola · R$ 7,89 o quilo (mais barato) · quarta-feira · Costa Atacadao ADE Aguas Claras\n"
        "Cebola · R$ 9,99 o quilo (mais caro) · quinta-feira passada · DONA DE CASA CANDANGOLANDIA\n"
        "diferença entre o mais barato e o mais caro: R$ 2,10\n"
        "Exemplo de saída:\n"
        '{"reply": "Compra no Costa Atacadao. R$ 7,89 o quilo.\\n\\nNo Dona de Casa tava R$ 9,99 — R$ 2,10 a '
        'mais, sem motivo nenhum, cebola é cebola.\\n\\nNão compra lá."}\n'
        "\n"
        "Exemplo de entrada (vários produtos de uma vez):\n"
        "contexto: comparação de preço entre mercados\n"
        "fatos:\n"
        "banana · Costa Atacadao ADE Aguas Claras · R$ 3,79 o quilo (mais barato) · quarta-feira\n"
        "banana · Assai Atacadista Guará · R$ 5,99 o quilo (mais caro) · há 14 dias\n"
        "banana: diferença entre o mais barato e o mais caro: R$ 2,20\n"
        "cebola · Costa Atacadao ADE Aguas Claras · R$ 7,89 o quilo (mais barato) · quarta-feira\n"
        "cebola · DONA DE CASA CANDANGOLANDIA · R$ 9,99 o quilo (mais caro) · quinta-feira passada\n"
        "cebola: diferença entre o mais barato e o mais caro: R$ 2,10\n"
        "tomate · Costa Atacadao ADE Aguas Claras · R$ 11,89 o quilo (mais barato) · quarta-feira\n"
        "tomate · Dona de Casa Guará · R$ 14,99 o quilo (mais caro) · há 11 dias\n"
        "tomate: diferença entre o mais barato e o mais caro: R$ 3,10\n"
        "uva · Assai Atacadista Guará · R$ 11,90 o quilo (mais barato) · há 14 dias\n"
        "uva · Costa Atacadao ADE Aguas Claras · R$ 13,98 o quilo (mais caro) · quarta-feira\n"
        "uva: diferença entre o mais barato e o mais caro: R$ 2,08\n"
        "Exemplo de saída:\n"
        '{"reply": "Compra no Costa Atacadao pra banana, cebola e tomate -- os três mais baratos lá, com '
        'folga.\\n\\nA uva inverte: mais barato no Assai Atacadista, R$ 11,90 o quilo, contra R$ 13,98 no '
        'Costa.\\n\\nCompra no Assai só pra uva; o resto, no Costa Atacadao."}\n'
        "\n"
        "Exemplo de entrada (vários produtos SEM resultado em comum -- não tente nomear todos):\n"
        "contexto: histórico de preço de um produto\n"
        "fatos:\n"
        "Laranja pera · R$ 2,49 o quilo (mais barato) · quarta-feira · Costa Atacadao ADE Aguas Claras\n"
        "Repolho · R$ 2,89 o quilo · quarta-feira · Costa Atacadao ADE Aguas Claras\n"
        "Cenoura · R$ 3,99 o quilo · quarta-feira · Costa Atacadao ADE Aguas Claras\n"
        "Tomate Italiano · R$ 11,89 o quilo · quarta-feira · Costa Atacadao ADE Aguas Claras\n"
        "Alho · R$ 49,90 o quilo (mais caro) · quinta-feira passada · Dona de Casa Candangolândia\n"
        "diferença entre o mais barato e o mais caro: R$ 47,41\n"
        "Exemplo de saída:\n"
        '{"reply": "5 preços de hortifruti registrados, de R$ 2,49 (laranja pera, Costa Atacadao) a R$ 49,90 '
        '(alho, Dona de Casa Candangolândia).\\n\\nR$ 47,41 de diferença entre o mais barato e o mais caro -- '
        'alho não é fruta rara, é assalto.\\n\\nOs outros três ficam no meio, sem nada que grite mais alto que '
        'isso."}'
    ),
}


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _configured_with_prices(config: Config) -> bool:
    return (
        config.ai_configured
        and config.ai_input_price_usd_per_1m is not None
        and config.ai_output_price_usd_per_1m is not None
    )


def is_available(conn: sqlite3.Connection, config: Config, month: str | None = None) -> bool:
    try:
        if not _configured_with_prices(config):
            return False
        return ai_usage.spent_in_month(conn, month or _current_month()) < config.ai_budget_usd
    except Exception:
        return False


def spent_this_month(conn: sqlite3.Connection, month: str | None = None) -> float:
    return ai_usage.spent_in_month(conn, month or _current_month())


def _log(
    config: Config,
    call_kind: str,
    *,
    attempt: int,
    user_prompt: str,
    raw_response: str | None,
    parsed_ok: bool,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    latency_ms: int,
    error: str | None,
    prompt_version: str | None = None,
) -> None:
    ai_log.append(
        config.ai_log_path,
        {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "call_kind": call_kind,
            "prompt_version": PROMPT_VERSIONS.get(call_kind, "") if prompt_version is None else prompt_version,
            "model": config.ai_model,
            "attempt": attempt,
            "user_prompt": user_prompt,
            "raw_response": raw_response,
            "parsed_ok": parsed_ok,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "error": error,
        },
    )


def record_usage(
    conn: sqlite3.Connection,
    config: Config,
    call_kind: str,
    *,
    attempt: int,
    user_prompt: str,
    raw_response: str | None,
    parsed_ok: bool,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    error: str | None,
    month: str | None = None,
    prompt_version: str | None = None,
) -> float:
    """Charges the month and appends one line to ai_calls.jsonl; returns the cost in USD.

    Public because the bot spends from the same budget and writes to the same log, and it may not
    import repositories. `prompt_version` is explicit so the bot can name its own prompt without
    entering PROMPT_VERSIONS, which belongs to the curation prompts."""
    if config.ai_input_price_usd_per_1m is None or config.ai_output_price_usd_per_1m is None:
        cost = 0.0
    else:
        cost = (
            input_tokens / 1e6 * config.ai_input_price_usd_per_1m
            + output_tokens / 1e6 * config.ai_output_price_usd_per_1m
        )
    if cost > 0:
        with conn:
            ai_usage.add_spent(conn, month or _current_month(), cost)
    _log(
        config,
        call_kind,
        attempt=attempt,
        user_prompt=user_prompt,
        raw_response=raw_response,
        parsed_ok=parsed_ok,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        latency_ms=latency_ms,
        error=error,
        prompt_version=prompt_version,
    )
    return cost


def _ask(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    call_kind: str,
    user_prompt: str,
    *,
    max_tokens: int,
    month: str | None = None,
) -> object | None:
    """Checks budget, tries up to MAX_ATTEMPTS times, charges and logs every attempt, returns parsed JSON or None."""
    month = month or _current_month()
    if not _configured_with_prices(config):
        return None
    if ai_usage.spent_in_month(conn, month) >= config.ai_budget_usd:
        record_usage(
            conn,
            config,
            call_kind,
            attempt=0,
            user_prompt=user_prompt,
            raw_response=None,
            parsed_ok=False,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            error="budget_exhausted",
            month=month,
        )
        return None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            response = client.complete(SYSTEM_PROMPTS[call_kind], user_prompt, max_tokens=max_tokens)
        except Exception as exc:
            response = LlmResponse("", 0, 0, error=f"client raised {type(exc).__name__}")
        latency_ms = int((time.monotonic() - started) * 1000)
        parsed: object | None = None
        parsed_ok = False
        error = response.error
        if error is None:
            try:
                parsed = json.loads(response.text)
                parsed_ok = True
            except ValueError:
                error = "invalid json"
        record_usage(
            conn,
            config,
            call_kind,
            attempt=attempt,
            user_prompt=user_prompt,
            raw_response=response.text,
            parsed_ok=parsed_ok,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=latency_ms,
            error=error,
            month=month,
        )
        if error is None:
            return parsed
    return None


def _valid_merge_item(item: object) -> MergeSuggestion | None:
    if not isinstance(item, dict):
        return None
    same_product = item.get("same_product")
    confidence = item.get("confidence")
    rationale = item.get("rationale")
    if not isinstance(same_product, bool):
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    if not (0 <= confidence <= 1):
        return None
    if not isinstance(rationale, str):
        return None
    return MergeSuggestion(same_product=same_product, confidence=float(confidence), rationale=rationale)


def suggest_merges(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    pairs: Sequence[tuple[str, str]],
    month: str | None = None,
) -> list[MergeSuggestion | None]:
    if not pairs:
        return []
    try:
        user_prompt = "\n".join(f"{i} | A: {a} | B: {b}" for i, (a, b) in enumerate(pairs, start=1))
        max_tokens = 80 * len(pairs) + 100
        data = _ask(conn, config, client, "merge", user_prompt, max_tokens=max_tokens, month=month)
        items = data.get("pairs") if isinstance(data, dict) else None
        result: list[MergeSuggestion | None] = [None] * len(pairs)
        if not isinstance(items, list):
            return result
        for item in items:
            index = item.get("id") if isinstance(item, dict) else None
            if not isinstance(index, int) or isinstance(index, bool) or not (1 <= index <= len(pairs)):
                continue
            if result[index - 1] is not None:
                continue  # first item for a given id wins
            result[index - 1] = _valid_merge_item(item)
        return result
    except Exception:
        return [None] * len(pairs)


def _valid_content(raw: object) -> ContentSuggestion | None:
    if not isinstance(raw, dict):
        return None
    quantity = raw.get("quantity")
    unit = raw.get("unit")
    if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or quantity <= 0:
        return None
    if not isinstance(unit, str):
        return None
    unit = unit.strip().upper()
    if unit not in ("L", "KG", "UN"):
        return None
    return ContentSuggestion(quantity=float(quantity), unit=unit)  # type: ignore[arg-type]


def _valid_kind(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    return raw.strip().lower() or None


def _valid_tags(raw: object) -> tuple[str, ...] | None:
    if not isinstance(raw, list):
        return None
    tags: list[str] = []
    for tag in raw:
        if not isinstance(tag, str):
            continue
        cleaned = tag.strip().lower()
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    return tuple(tags[:3]) if tags else None


def _valid_enrichment(item: object, valid_ids: set[int]) -> tuple[int, ProductEnrichment] | None:
    if not isinstance(item, dict):
        return None
    product_id = item.get("id")
    if not isinstance(product_id, int) or isinstance(product_id, bool) or product_id not in valid_ids:
        return None
    readable_name = item.get("readable_name")
    if not isinstance(readable_name, str) or not readable_name.strip():
        return None
    tags = _valid_tags(item.get("tags"))
    if tags is None:
        return None
    content = _valid_content(item.get("content"))
    return product_id, ProductEnrichment(
        readable_name=readable_name.strip(), tags=tags, content=content, kind=_valid_kind(item.get("kind"))
    )


def enrich_products(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    products: Sequence[Product],
    known_tags: Sequence[str],
    known_kinds: Sequence[str] = (),
    month: str | None = None,
) -> dict[int, ProductEnrichment]:
    if not products:
        return {}
    result: dict[int, ProductEnrichment] = {}
    for start in range(0, len(products), ENRICH_BATCH_SIZE):
        batch = products[start : start + ENRICH_BATCH_SIZE]
        try:
            user_prompt = (
                f"categorias: {json.dumps(list(known_tags), ensure_ascii=False)}\n"
                f"tipos: {json.dumps(list(known_kinds), ensure_ascii=False)}\n"
                "produtos:\n" + "\n".join(f"{p.id} | {p.canonical_name}" for p in batch)
            )
            max_tokens = 140 * len(batch) + 200
            data = _ask(conn, config, client, "enrich", user_prompt, max_tokens=max_tokens, month=month)
            items = data.get("products") if isinstance(data, dict) else None
            if not isinstance(items, list):
                continue
            valid_ids = {p.id for p in batch}
            for item in items:
                parsed = _valid_enrichment(item, valid_ids)
                if parsed is None:
                    continue
                product_id, enrichment = parsed
                if product_id not in result:
                    result[product_id] = enrichment
        except Exception:
            continue
    return result


_PACKAGING_FORMS = ("unit", "pack", "weight", "volume", "unknown")


def _valid_packaging(item: object, valid_ids: set[int]) -> tuple[int, PackagingHint] | None:
    if not isinstance(item, dict):
        return None
    product_id = item.get("id")
    if not isinstance(product_id, int) or isinstance(product_id, bool) or product_id not in valid_ids:
        return None
    raw_form = item.get("form")
    form: PackagingForm = raw_form if raw_form in _PACKAGING_FORMS else "unknown"  # type: ignore[assignment]
    raw = item.get("candidates")
    candidates: list[ContentSuggestion] = []
    if isinstance(raw, list):
        for entry in raw:
            content = _valid_content(entry)
            if content is not None:
                candidates.append(content)
    return product_id, PackagingHint(form=form, candidates=tuple(candidates[:3]))


def suggest_packaging(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    products: Sequence[Product],
    month: str | None = None,
) -> dict[int, PackagingHint]:
    """Retail intuition: what the model guesses a package holds. It never refuses, so it is never
    written — the CLI turns it into options a human picks from (design §4)."""
    if not products:
        return {}
    result: dict[int, PackagingHint] = {}
    for start in range(0, len(products), ENRICH_BATCH_SIZE):
        batch = products[start : start + ENRICH_BATCH_SIZE]
        try:
            user_prompt = "produtos:\n" + "\n".join(f"{p.id} | {p.canonical_name}" for p in batch)
            max_tokens = 70 * len(batch) + 200
            data = _ask(conn, config, client, "packaging", user_prompt, max_tokens=max_tokens, month=month)
            items = data.get("packaging") if isinstance(data, dict) else None
            if not isinstance(items, list):
                continue
            valid_ids = {p.id for p in batch}
            for item in items:
                parsed = _valid_packaging(item, valid_ids)
                if parsed is None:
                    continue
                product_id, hint = parsed
                if product_id not in result:
                    result[product_id] = hint
        except Exception:
            continue
    return result


def suggest_trade_names(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    stores: Sequence[tuple[str, str, str | None]],
    month: str | None = None,
) -> dict[str, str]:
    """The trade name the model recognises, keyed by CNPJ. Stores it refuses are simply absent.

    Called only for stores whose CNPJ registry has no trade name — measured at 1 in 5, which is
    what keeps this inside the project's frequency rule. Never raises; no answer means no answer.
    """
    if not stores:
        return {}
    by_index = {index: cnpj for index, (cnpj, _, _) in enumerate(stores, start=1)}
    result: dict[str, str] = {}
    try:
        lines = [
            json.dumps(
                {"id": index, "legal_name": legal_name, "address": address or ""},
                ensure_ascii=False,
            )
            for index, (_, legal_name, address) in enumerate(stores, start=1)
        ]
        user_prompt = "lojas:\n" + "\n".join(lines)
        data = _ask(
            conn, config, client, "store", user_prompt, max_tokens=60 * len(stores) + 200, month=month
        )
        items = data.get("stores") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return {}
        for item in items:
            if not isinstance(item, dict):
                continue
            index = item.get("id")
            trade_name = item.get("trade_name")
            if not isinstance(index, int) or isinstance(index, bool) or index not in by_index:
                continue
            if not isinstance(trade_name, str) or not trade_name.strip():
                continue
            result.setdefault(by_index[index], trade_name.strip())
        return result
    except Exception:
        return {}


def match_products(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    term: str,
    catalog: Sequence[tuple[int, str, tuple[str, ...]]],
    month: str | None = None,
) -> list[int]:
    if not catalog or not term or not term.strip():
        return []
    try:
        lines = [f"{product_id} | {name} | {', '.join(tags)}" for product_id, name, tags in catalog]
        user_prompt = f"termo: {term}\ncatálogo:\n" + "\n".join(lines)
        data = _ask(conn, config, client, "match", user_prompt, max_tokens=200, month=month)
        ids = data.get("ids") if isinstance(data, dict) else None
        if not isinstance(ids, list):
            return []
        valid_ids = {product_id for product_id, _, _ in catalog}
        result: list[int] = []
        for item in ids:
            if isinstance(item, int) and not isinstance(item, bool) and item in valid_ids and item not in result:
                result.append(item)
        return result
    except Exception:
        return []


_MONEY_RE = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*,\d{2}")


def _money_values(text: str) -> set[str]:
    return {re.sub(r"\s+", " ", match) for match in _MONEY_RE.findall(text)}


def narrate(
    conn: sqlite3.Connection,
    config: Config,
    client: LlmClient,
    context: str,
    facts: str,
    month: str | None = None,
) -> str | None:
    """O ponto único de narração do bot (voz do Julius, ticket 163): pede à IA para dizer, em até
    algumas frases, os fatos que o chamador já calculou. `context` é uma linha dizendo o que está
    sendo narrado ("histórico de preço de um produto", "confirmação de uma alteração no
    catálogo"...); `facts` é texto plano, já pronto -- o único material que a resposta pode citar.

    Nunca é confiável por conta própria: qualquer "R$ X,XX" na resposta que não esteja em `facts`
    derruba a resposta inteira, e o chamador cai para o texto determinístico de sempre. Fatos sem
    nenhum valor em dinheiro (o caso das confirmações de escrita) tornam a guarda um no-op -- não é
    um caminho especial."""
    if not facts.strip():
        return None
    try:
        allowed = _money_values(facts)
        user_prompt = f"contexto: {context}\nfatos:\n{facts}"
        data = _ask(conn, config, client, "persona", user_prompt, max_tokens=900, month=month)
        reply = data.get("reply") if isinstance(data, dict) else None
        if not isinstance(reply, str) or not reply.strip():
            return None
        reply = reply.strip()
        if not _money_values(reply) <= allowed:
            return None
        return reply
    except Exception:
        return None
