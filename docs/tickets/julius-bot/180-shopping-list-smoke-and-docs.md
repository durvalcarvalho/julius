# 180: smoke real + docs — medir o corte de `kind`, testar RF1/RF4/RF5 de verdade

<!-- adjustments: a medição não só ajustou o número de KIND_MATCH_CUTOFF -- ela achou que o
mecanismo (fuzz.ratio na string inteira, como o ticket 176 tinha implementado) repetia o defeito
do WRatio pré-v2.3.1 (termo curto perde contra kind composto: "leite" pontuava 71 contra "leite
uht", "agua" pontuava mais em "manga" que em "água mineral"). Corrigido trocando pra _name_score
(o scorer palavra-a-palavra que a busca de produto já usa), não só o corte. Ver CLAUDE.md "v2.10"
e o docstring de KIND_MATCH_CUTOFF (julius/services/search.py) para os números completos. -->


> Fecha a trilha: mede o corte que o ticket 176 chutou, roda a suíte real de IA, e pede ao usuário os três testes que só o Telegram de verdade confirma.

## Contexto

Fecha `docs/design/shopping-list-conversation-context.md`. Depende de **179** (a trilha inteira precisa estar integrada). Mesma disciplina de todo ticket de fechamento deste projeto (162, 169, 174): medir contra cópia do banco de produção, nunca contra o banco de verdade; documentar o resultado real, não a expectativa.

## Escopo

### Dentro
- Medir `KIND_MATCH_CUTOFF` (ticket 176, valor provisório) contra `products.all_kinds(conn)` do banco de produção real (cópia) — candidatos reais (erro de digitação plausível) e falsos positivos conhecidos, mesmo processo de `MATCH_SCORE_CUTOFF`/`TAG_MATCH_CUTOFF`/`NEAR_MISS_CUTOFF`. Fixar o valor medido no código, com docstring citando os números, não deixar o chute do ticket 176.
- `tests/test_real_ai.py`: um teste novo cobrindo `compare_stores` com `items` reais (roteamento + narração), mesmo padrão dos testes existentes (marcador `real_ai`, roda só com `--real-ai`).
- `docs/como-testar-o-bot.md`: três passos novos, pedindo ao usuário testar manualmente RF1 ("qual mercado é mais barato" sem lista → o bot deve perguntar o que comprar, nunca despejar o catálogo), RF4 (responder algo curto/ambíguo a uma pergunta do bot e ver se ele religa os dois) e RF5 (mencionar itens em mensagens separadas antes de perguntar "qual mercado").
- `CLAUDE.md`: novo parágrafo de versão (v2.10) resumindo a rodada — o que mudou, o que foi medido, e a Decisão 4/5 do design registradas explicitamente como pendência (não implementadas, condicionadas ao resultado do smoke manual).
- `docs/tickets/julius-bot/index.md`: marcar 175–180 como feitos, com commit de cada um.

### Fora
- Qualquer mudança de código de produção além de fixar `KIND_MATCH_CUTOFF` com o valor medido — este ticket mede e documenta, não implementa feature nova.
- Implementar a Decisão 4 (`awaiting_topic`/estado de pergunta pendente) ou a Decisão 5 (lembrar além da janela) mesmo que o smoke mostre necessidade — se aparecer um caso real de falha, **documentar** no `CLAUDE.md` como gatilho para reabrir essas decisões num ticket futuro, não implementar aqui por baixo do capô.

## Requisitos

### Funcionais
- A medição de `KIND_MATCH_CUTOFF` roda contra **cópia** do banco de produção (`cp ~/.local/share/julius/prices.db /tmp/...` ou equivalente) — nunca o arquivo real.
- O docstring final da constante segue o formato de `MATCH_SCORE_CUTOFF`/`TAG_MATCH_CUTOFF`/`NEAR_MISS_CUTOFF` (`services/search.py`): números reais medidos, pior caso conhecido, por que o corte escolhido não é maior nem menor.
- O parágrafo novo do `CLAUDE.md` segue o estilo dos parágrafos de versão existentes (o que motivou, o que foi medido, custo real em `ai_calls.jsonl`, o que ficou de fora e por quê).

### Validação e erros
- N/A — ticket de medição e documentação.

## Especificação técnica

```
modificar julius/services/search.py       — KIND_MATCH_CUTOFF (valor final medido + docstring)
modificar tests/test_real_ai.py           — teste novo
modificar docs/como-testar-o-bot.md
modificar CLAUDE.md
modificar docs/tickets/julius-bot/index.md
```

### Padrão a seguir
- `tests/test_real_ai.py` já tem o padrão de teste real (marcador, `MIN_ROUTING_HITS`, custo em `ai_calls.jsonl`) — seguir a mesma estrutura dos testes existentes no arquivo, não inventar um harness novo.
- O parágrafo do `CLAUDE.md` de fechamento da v2.7.1 (`docs/tickets/julius-bot/174-humanization-smoke-and-docs.md`, e o texto correspondente no `CLAUDE.md` já lido nesta sessão) é o modelo de tom e de conteúdo.

## Testes obrigatórios

1. Um teste novo em `test_real_ai.py`, seguindo o padrão dos existentes (marcador `real_ai`, só roda com `--real-ai`), cobrindo: mensagem tipo "qual mercado é mais barato pra tomate e cebola" roteia para `compare_stores` com os itens certos, e a narração sai grounded (sem `R$` fora dos fatos).
2. Suíte inteira verde (`.venv/bin/pytest -q`).
3. Suíte real (`pytest tests/test_real_ai.py --real-ai`) com taxa de acerto de roteamento ≥ `MIN_ROUTING_HITS`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `make test-ia` (ou equivalente) executado; custo real registrado no `CLAUDE.md`, mesmo formato das rodadas anteriores.
- [ ] `KIND_MATCH_CUTOFF` tem docstring com números reais medidos, não o chute do ticket 176.
- [ ] `docs/como-testar-o-bot.md` tem os três passos novos (RF1/RF4/RF5), redigidos para o usuário executar manualmente no Telegram de verdade.
- [ ] `CLAUDE.md` tem o parágrafo de versão novo, incluindo a nota explícita de que as Decisões 4/5 do design (estado de pergunta pendente, memória além de 3 turnos) **não** foram implementadas nesta rodada.

## Notas para o agente

- Isto é o ticket que decide se a Decisão 4 do design (estado de pergunta pendente) precisa mesmo ser construída — se RF4/RF5 falharem no teste real ou no smoke manual do usuário, documente o caso exato (mensagem enviada, resposta errada recebida) no `CLAUDE.md` como gatilho pra reabrir a Decisão 4 num ticket futuro, em vez de já implementar a peça nova por conta própria aqui.
- Não amplie o escopo do smoke manual além dos três passos pedidos — RF2/RF3 (veredito agregado, segundo colocado) já são cobertos pelos testes automatizados dos tickets 175–179; o manual é só para o que só um humano digitando no Telegram consegue confirmar (RF1/RF4/RF5, comportamento de prompt).
