# 163: `services/suggestions.py::narrate` — o ponto único de narração

<!-- status:done -->
<!-- adjustments: SYSTEM_PROMPTS["persona"] reescrito pra v2 em 18/09/2026, a partir de exemplo
real do usuário testando o bot pelo Telegram -- a v1 soava "funcional mas comedido". A v2 exige
duas partes na ordem (informação clara com unidade, depois o comentário do Julius, podendo ser
mais longo e com pergunta retórica) e explicitamente proíbe explicar a ausência de um dado. A
guarda de dinheiro não mudou -- o que mudou foi records_facts/comparison_facts (164) passarem a
entregar a diferença já calculada como fato, pra IA poder citá-la sem fazer conta. max_tokens de
narrate() subiu de 220 pra 380. PROMPT_VERSIONS["persona"] é "2". Ver CLAUDE.md "Prompt persona v2". -->

> Uma função, um prompt, uma guarda: pede à IA para dizer, na voz do Julius Rock, fatos que o chamador já calculou — e derruba a resposta se ela citar um valor em dinheiro que não veio desses fatos.

## Contexto

Segue o design "voz do Julius no bot (v2.7)" combinado na sessão de 2026-09-18 (brainstorm → design), em cima da v2.6 já fechada (tickets 150–162). Hoje o bot responde toda leitura com a mesma tabela que a CLI imprime (`bot/render.py`), sem personagem nenhum — é o problema relatado.

Esta é a única peça nova em `services/suggestions.py`, a mesma casa de `enrich_products`/`suggest_merges`/`match_products`/`suggest_packaging`/`suggest_trade_names`. Não depende de nenhum ticket novo; é o primeiro da trilha porque 167 e 168 (o uso em `turn.py`) dependem dela.

**Personagem**: ver `persona-julius-rock.md` na raiz do repo (não versionado ainda — copie o que precisar do tom, não o arquivo inteiro: o prompt do sistema deve ser conciso, para não inflar o custo por chamada).

## Escopo

### Dentro
- `PROMPT_VERSIONS["persona"] = "1"`.
- `SYSTEM_PROMPTS["persona"]`: a voz do Julius (pai pão-duro, direto, sem ironia fina) condensada — não a bíblia inteira — mais a regra de grounding ("todo preço na resposta tem que copiar um dos valores `R$ X,XX` recebidos, sem calcular nenhum novo") e o formato de saída `{"reply": "..."}`.
- `narrate(conn, config, client, context: str, facts: str, month: str | None = None) -> str | None`: monta `user_prompt = f"contexto: {context}\nfatos:\n{facts}"`, chama `_ask(conn, config, client, "persona", user_prompt, max_tokens=220, month=month)`, valida `data["reply"]` como string não vazia, aplica a guarda de dinheiro e devolve o texto ou `None`.
- Guarda: `_money_values(text) -> set[str]` via regex `R\$\s?\d{1,3}(?:\.\d{3})*,\d{2}`; a resposta só é aceita se `_money_values(reply) <= _money_values(facts)`. Fatos sem nenhum valor em dinheiro (o caso das escritas, ticket 168) tornam a guarda um no-op — não é um caminho especial.
- `facts` vazio (`not facts.strip()`) devolve `None` sem chamar `_ask` (sem custo, sem linha de log) — mesmo padrão de `match_products`/`suggest_trade_names` com entrada vazia.

### Fora
- Qualquer `_facts`/frase-molde em `render.py` (→ 164, 165).
- Qualquer chamada a partir de `bot/turn.py` ou `bot/actions.py` (→ 166, 167, 168).
- Guarda por identidade de produto/mercado (nome, id) além de dinheiro — não medido ainda; se aparecer um caso real de nome inventado, é ticket novo, não ampliação silenciosa deste.

## Requisitos

### Funcionais
- `narrate` nunca lança: qualquer falha de `_ask`/parsing vira `None`, dentro de um único `try/except Exception`, como todo outro `suggest_*`/`match_products` deste arquivo.
- `context` é uma frase curta que só entra no `user_prompt`, nunca no `SYSTEM_PROMPTS` (o prompt do sistema é fixo e compartilhado por todo chamador — busca, comparação, listagens, escrita).
- Custo e log passam por `_ask`/`record_usage` sem nenhum caminho novo: `call_kind="persona"`, `prompt_version` vem de `PROMPT_VERSIONS["persona"]`.

### Validação e erros
- `data` que não é `dict`, ou sem chave `"reply"`, ou `"reply"` não-string/vazia → `None`.
- Resposta com um valor `R$ X,XX` ausente dos fatos → `None`, mesmo que o resto da frase esteja correto (rejeição é da resposta inteira, não uma edição).
- Espaços diferentes dentro do mesmo valor (`"R$  9,99"` vs `"R$ 9,99"`) não escapam da guarda — normalize com `re.sub(r"\s+", " ", ...)` antes de comparar, como já é feito em `records_facts`/regex de outros formatadores deste projeto.

## Especificação técnica

```
modificar julius/services/suggestions.py — PROMPT_VERSIONS["persona"], SYSTEM_PROMPTS["persona"], narrate(), _money_values()
modificar tests/_fakes.py                — _KIND_MARKERS ganha '"reply"': "persona", para o ScriptedLlmClient(by_kind=...) rotear a chamada certa
modificar tests/test_services_suggestions.py — testes de narrate()
```

### Padrão a seguir
- `match_products`/`suggest_trade_names` (mesmo arquivo): entrada vazia → `None` sem chamar `_ask`; corpo inteiro em `try/except Exception: return None`.
- `_ask` já existe e não muda: orçamento, tentativas, cobrança e log são responsabilidade dela, `narrate` só monta o prompt e valida a resposta.
- `ScriptedLlmClient(by_kind={...})` (`tests/_fakes.py`) já detecta o `call_kind` pela marca no `system_prompt`; siga o padrão das outras cinco entradas de `_KIND_MARKERS`.

## Testes obrigatórios

1. `test_narrate_returns_grounded_text` — fatos com um `R$ 3,79`; resposta cita só esse valor → aceita, `_lines(cfg)[-1]["call_kind"] == "persona"`.
2. `test_narrate_rejects_a_price_not_in_the_facts` — resposta cita um `R$` ausente dos fatos → `None`.
3. `test_narrate_accepts_a_reply_with_no_price_mentioned` — fatos e resposta sem nenhum `R$` (o caso de escrita) → aceita.
4. `test_narrate_empty_facts_short_circuits` — `facts=""` → `None`, `client.calls == []`.
5. `test_narrate_not_configured_returns_none` — sem `ai_api_key` → `None`, `client.calls == []`.
6. `test_narrate_client_raises_returns_none` — `RaisingLlmClient()` → `None` (via `_ask`, sem propagar).
7. `test_narrate_malformed_json_shape_returns_none` — `{"reply": 123}` e `{"nope": "x"}` → `None` nos dois.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n '"persona"' julius/services/suggestions.py` mostra `PROMPT_VERSIONS`, `SYSTEM_PROMPTS` e a chamada em `narrate`.
- [ ] Nenhum outro arquivo fora dos três listados muda.

## Notas para o agente

- O prompt do sistema é o único lugar onde a persona "existe" — não escreva a voz do Julius em nenhum outro arquivo deste ticket.
- Não invente uma guarda de nome/id "por garantia" — o escopo é só dinheiro, medido no problema real (screenshot da busca de preço). Ampliar sem caso concreto é a mesma dívida que este projeto já rejeitou várias vezes em `CLAUDE.md` ("medido, não hipótese").
- `max_tokens=220` é chute de tamanho de frase curta (1–3 sentenças); não é medido — pode precisar de ajuste depois do smoke real (ticket 169).
