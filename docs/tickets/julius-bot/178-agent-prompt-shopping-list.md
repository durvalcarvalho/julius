# 178: `bot/agent.py` — prompt: escopo de `compare_stores`, pergunta pendente, acumular itens

> Três frases novas no `SYSTEM_PROMPT`, nenhum mecanismo novo: confiar primeiro no histórico que já existe (`HISTORY_TURNS = 3`) antes de construir qualquer estado de conversa.

## Contexto

`docs/design/shopping-list-conversation-context.md`, Decisão 1 (regra de quando chamar `compare_stores`) e Decisão 4 (RF4/RF5 — reforço de prompt, sem peça nova nesta rodada). Depende de **176** (a ação já precisa aceitar `items` pra este prompt fazer sentido) — dependência fraca, o texto do prompt não referencia código, só é sem propósito testar antes de 176 existir.

## Escopo

### Dentro
- `julius/bot/agent.py::SYSTEM_PROMPT`: três frases novas.
  1. **RF1** — "qual mercado é mais barato"/"onde devo ir" sem nenhum item citado (nesta mensagem nem nas recentes) não chama `compare_stores`; responde em texto perguntando o que a pessoa quer comprar.
  2. **RF4** — se a última mensagem do próprio bot nesta conversa foi uma pergunta, a próxima mensagem da pessoa deve ser tratada como resposta a ela antes de cogitar qualquer outra ação, mesmo que a resposta seja curta.
  3. **RF5** — ao montar `items` para `compare_stores`, juntar o que foi mencionado nas últimas mensagens da conversa, não só na mais recente.
- `BotOutput` (mesmo arquivo) ganha `ShoppingComparison` na união de tipos.

### Fora
- `ChatState`/`awaiting_topic` ou qualquer estado novo persistido — Decisão 4 do design deixa isso para depois de medir se o reforço de prompt já basta (ticket 180 mede).
- `HISTORY_TURNS` — continua 3.
- Qualquer teste automatizado que meça se o modelo *de fato* obedece às frases novas — não é testável por unidade (mesma nota do ticket 172, prompt `persona` v3); quem mede é o smoke real, ticket 180.

## Requisitos

### Funcionais
- As três frases entram na seção "Leitura" do prompt (hoje `bot/agent.py:34-39`), perto da linha existente `"qual mercado é mais barato", comparar mercados → compare_stores.`.
- `BotOutput = str | SearchOutcome | StoreComparison | ShoppingComparison | ProductListing | StoreListing | PendingWrite`.
- `build_agent`: nenhuma mudança de código além do tipo — `output_type=[str, *ALL_ACTIONS]` já cobre `ShoppingComparison` de graça, porque é o retorno de `compare_stores`, que já está em `ALL_ACTIONS` (só a assinatura da função mudou, no ticket 176).

### Validação e erros
- N/A — mudança de texto de prompt e de tipo, sem lógica nova.

## Especificação técnica

```
modificar julius/bot/agent.py — SYSTEM_PROMPT (3 frases novas), BotOutput
```

Import novo: `ShoppingComparison` de `julius.bot.actions` (já importa `PendingWrite`, `ProductListing`, `StoreListing` do mesmo módulo).

### Padrão a seguir
- O `SYSTEM_PROMPT` de hoje já usa bullets curtos e imperativos por tópico ("pergunta sobre preço... → search_prices.", "está caro? não é um veredito seu...") — as frases novas seguem o mesmo estilo, sem virar parágrafo.

## Testes obrigatórios

1. Nenhum teste de comportamento de prompt é exigido aqui (não testável por unidade — mesma nota do ticket 172).
2. Suíte inteira (`.venv/bin/pytest -q`) continua verde.
3. `tests/test_bot_agent.py`: se algum teste existente afirma o conteúdo/tamanho de `BotOutput` ou do `output_type`, ajustar pra incluir `ShoppingComparison` (sem criar teste novo só pra isso, a menos que já exista um afirmando a lista de tipos).

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n "ShoppingComparison" julius/bot/agent.py` não vazio.
- [ ] Leitura humana do prompt final: as três frases estão presentes, no lugar certo, e não contradizem nenhuma regra existente (em especial "está caro? não é um veredito seu" — RF4/RF5 não abrem exceção pra veredito de preço isolado, só pra escopo de itens).

## Notas para o agente

- Não reescreva o `SYSTEM_PROMPT` inteiro — inserção cirúrgica das três frases, mesma disciplina de todo ticket de prompt deste projeto (ver ticket 172: mudança pontual, não reescrita).
- A frase de RF4 é deliberadamente geral (vale para **qualquer** pergunta em aberto do bot, não só a de lista de compras) — não amarre o texto só ao caso de `compare_stores`.
- Não adicione instrução sobre `awaiting_topic` ou qualquer campo de estado — esse mecanismo não existe neste ticket (Decisão 4 do design é clara: só entra se o smoke, ticket 180, mostrar que falta).
