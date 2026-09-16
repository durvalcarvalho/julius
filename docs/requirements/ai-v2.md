# Julius v2 — IA na prática: requisitos

> Brainstorm de 2026-09-15 (`/sc:brainstorm`). Saída: **requisitos e questões em aberto**, não design nem código.
> Insumos: `CLAUDE.md` (seção "Camada opcional de IA"), `claudedocs/research_llm_integration_best_practices_20260915.md`, `claudedocs/research_ia_chinesa_llm_20260915.md`, o estado real do catálogo (`julius mercados listar` / `julius produtos listar` após 5 notas) e o código em `julius/infra/llm_client.py`, `julius/services/suggestions.py`, `julius/services/guidance.py`.
> Próximo passo: responder as questões da §7 → `/sc:design` → tickets em `docs/tickets/julius-v2/`.

## 0. Ponto de partida — fatos verificados hoje

| # | Fato | Evidência |
|---|---|---|
| F1 | A camada de IA **já existe inteira**: `HttpLlmClient` (urllib, `temperature: 0`), `suggestions.suggest_merge/suggest_content/suggest_tags`, `ai_usage` com orçamento mensal. O `CLAUDE.md` ainda diz que o cliente HTTP "vem num ticket próprio" — está desatualizado. | `julius/infra/llm_client.py`, ticket 011 feito |
| F2 | Só **um** ponto chama IA: `julius produtos comparar`. `suggest_content` e `suggest_tags` não têm chamador. | `grep suggest_ julius/` |
| F3 | **Nunca foi feita uma chamada real** a provedor. Tudo testado com fake. | `CLAUDE.md` "Status" |
| F4 | O cliente **não pede JSON mode**, não fixa `max_tokens`, não faz retry, não loga nada. Extrai o JSON por regex (`_JSON_BLOCK`) — workaround pra ausência de `response_format`. O `json.loads` já está dentro do `try` dos chamadores (invariante "nunca lança" preservado). | `llm_client.py`, `suggestions.py` |
| F5 | Config do provedor está exportada **só no shell interativo do usuário**; `env \| grep JULIUS` dentro do Claude Code vem vazio. Smoke test real é tarefa do usuário, não do agente. | verificado nesta sessão |
| F6 | **Divergência modelo × preço**: a pesquisa recomendou `deepseek-flash` a US$0,15/0,60 por 1M; o ambiente tem `JULIUS_AI_MODEL=deepseek-v4-pro` **com os preços do flash**. Se o `pro` custa mais, o contador `ai_usage` subestima o gasto e o teto de US$5 não protege de verdade. | `research_ia_chinesa_llm_20260915.md` linhas 15/40–42 vs. env exportado |
| F7 | **Dona de Casa são duas filiais, não dois caixas.** As notas trazem endereços diferentes: `11.832.478/0002-85` → QUADRA QE 30, GUARÁ II; `11.832.478/0003-66` → QUADRA QR 5, CANDANGOLÂNDIA. A premissa "mesmo mercado, vários CNPJs" está errada **neste caso**; o desejo por trás ("quero ver como Dona de Casa") continua válido. | `tests/fixtures/qrcode-3.html`, `~/.local/share/julius/entrada/qrcode-4.html` |
| F8 | Filiais da mesma rede compartilham o **radical do CNPJ** (8 primeiros dígitos, `11832478`). Isso é regra da Receita, determinística — identifica "mesma empresa" sem comparar nome, sem fuzzy, sem IA. | estrutura do CNPJ |
| F9 | Catálogo real após 5 notas: **70 produtos, 0 tags, 0 conteúdos definidos.** A curadoria manual prevista no design (`produtos tag`, `definir-conteudo`) não aconteceu nem uma vez. Casos visíveis: `SACOLA REUTILIZAVEL UND` ×2 (ids 2 e 68, mercados diferentes — mesmo produto de verdade), `TOMATE ITALIANO` ×2, `CEBOLA` ×2, `AVEIA QUAK 450G FINO/REGU` (parecidos, **diferentes**). | `julius produtos listar` |
| F10 | **Não existe comando pra remover tag** — só `sqlite3` direto. Qualquer tag aplicada automaticamente e errada hoje não tem desfazer no CLI. | `grep -ri untag julius/` vazio |
| F11 | O parser **não extrai endereço** da nota; o schema não tem coluna pra isso. | `grep -i endere julius/parsers/df.py` vazio |
| F12 | `mercados listar` já ordena por CNPJ, então filiais da mesma rede **já saem adjacentes** (radical igual → prefixo igual). | tabela mostrada pelo usuário |

## 1. Objetivo revisado

O design v1 tratou IA como "opcional, rara, só sugere, nunca grava". A experiência real (F9) mostra que o gargalo do sistema virou **curadoria de catálogo que o usuário não faz**: sem tag e sem nome legível, `consultar --tag` é inútil e `consultar linguiça` não acha `LING FGO`. Com um provedor barato configurado, o objetivo passa a ser:

> **A IA faz a curadoria do catálogo que o usuário não faria à mão — de forma reversível, auditável e fora do caminho rápido de leitura.**

Metas do usuário, na ordem em que ele as trouxe:

- **G1** Provedor real funcionando com robustez (JSON confiável, log, retry). DeepSeek agora, OpenRouter possível depois, troca só por variável de ambiente.
- **G2** Reconhecer que mercados com CNPJs diferentes podem ser a mesma rede.
- **G3** Tags automáticas; quando incerto, o usuário confirma entre 3 opções ou digita uma.
- **G4** IA também na consulta, em casos específicos.

## 2. Princípios — o que continua e o que muda

**Continuam (não rediscutir):**
- Nem cliente nem serviço de IA lançam exceção; falha vira `None`/lista vazia.
- Orçamento mensal persistido em `ai_usage`, checado antes de cada chamada.
- Nenhuma dependência nova (`urllib`, `json`, `rich`/`typer` já cobrem prompt interativo).
- `importar` é **não interativo** (lote com `*.html`, canal Telegram futuro).
- `fundir` (produtos) **nunca** é automático — é irreversível.
- O caminho rápido de `consultar` (resultado não vazio) **nunca** chama IA.
- Identificadores em inglês; comandos, `--help` e mensagens em português.

**Muda (decisão nova, com base em F9):**
- De "IA nunca grava sozinha" para **"IA pode gravar o que é reversível por um comando do CLI"** — tag, nome canônico, apelido de mercado. Continua proibido gravar o irreversível: fusão de produtos/mercados e qualquer linha de `prices`.
- Corolário: **toda gravação automática exige comando de desfazer já existente** (`renomear` existe; remover tag não — F10, vira pré-requisito).

## 3. Requisitos funcionais

### RF-A — Robustez do cliente e do provedor (G1)

| # | Requisito | Origem |
|---|---|---|
| A1 | Pedir JSON mode (`response_format: {"type": "json_object"}`); todo prompt contém a palavra "json" e um exemplo literal do formato. Provedor que não suporta responde erro → `None` + linha no log (A6). | pesquisa §2 |
| A2 | `max_tokens` explícito por tipo de chamada (resposta truncada é indistinguível de "modelo divagou" sem isso). `temperature` entre 0 e 0,2 (já é 0). | pesquisa §3, §6 |
| A3 | **Um** retry em resposta vazia ou JSON inválido; na segunda falha, `None`. | pesquisa §3 |
| A4 | Validar campos, tipos e faixas antes de aceitar: `confidence ∈ [0,1]`, `unit ∈ {L,KG,UN}`, tag não vazia, id de produto existente. Fora disso → `None`. | pesquisa §3 |
| A5 | Prompts com papel → tarefa → formato exato com exemplo → 2 few-shot (**um negativo**). `rationale` **antes** de `same_product`/`confidence` dentro do JSON. Exemplos reais: `TOMATE ITALIANO kg` × `TOMATE ITALIANO UNIAO kg` (positivo/incerto), `REFRI PEPSI PET 2L` × `REFRI ANT GUARANA PET 1.5L` (negativo), `AVEIA QUAK 450G FINO` × `REGU` (negativo, F9). | pesquisa §4 |
| A6 | Log local **JSONL append-only** em `<pasta do prices.db>/ai_calls.jsonl` (derivado de `Config.db_path.parent`; sem variável nova). Uma linha por tentativa: `timestamp`, `call_kind`, `prompt_version`, `model`, `user_prompt`, `raw_response`, `parsed_ok`, `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms`, `error`. Nunca PII (só descrições de produto). Escrita nunca lança. | pesquisa §5 |
| A7 | `prompt_version` (string curta) por tipo de chamada, mudada à mão quando o texto do prompt muda. | pesquisa §5 |
| A8 | `produtos comparar` (e qualquer outro chamador) distingue três silêncios: **não configurada** / **orçamento do mês esgotado** / **falha na chamada (ver `ai_calls.jsonl`)**. Hoje as duas últimas saem juntas numa frase só. | `cli/products.py` |
| A9 | Corrigir F6 antes de qualquer código: ou `JULIUS_AI_MODEL=deepseek-flash`, ou preços do `pro` nas duas variáveis. Critério de aceite da rodada inclui o smoke test da §6. | F6 |
| A10 | Portabilidade OpenRouter: só documentação (base URL com `/v1`; headers `HTTP-Referer`/`X-Title` são opcionais e não entram; modelos `:free` podem rejeitar `response_format` — isso aparece no log). **Sem** fallback automático entre provedores, **sem** `reasoning`/streaming (irrelevantes para classificação). | pesquisa §7, docs OpenRouter |
| A11 | (aberto — Q8) `julius ia status`: configurada?, modelo, gasto do mês × orçamento, últimas chamadas com erro. Alternativa zero-código: `tail -n 5 ai_calls.jsonl` + `SELECT * FROM ai_usage`. | — |

### RF-B — Mercados e filiais (G2) — sem IA

| # | Requisito | Origem |
|---|---|---|
| B1 | "Mesma rede" = **mesmo radical de CNPJ** (8 primeiros dígitos). Exato, sem rapidfuzz, sem LLM. Razão social é idêntica entre filiais e diferente entre redes, então comparar nome não acrescenta nada. | F7, F8 |
| B2 | Dica no `importar` quando o mercado novo compartilha radical com um mercado já apelidado: "CNPJ X é outra filial de '<apelido>'. Sugestão: `julius mercados renomear X "<apelido> — <bairro>"`". Entra no módulo `guidance` como `HintKind` novo, mesmas regras (máx. 2 por comando, só em situação nova). | F7, módulo `guidance` |
| B3 | **Não fundir mercados.** Preços diferem por filial e fundir destruiria a informação sem volta. Se o usuário não quer distinguir, a solução é zero código: mesmo apelido nos dois CNPJs (`nickname` não é `UNIQUE`); `consultar` passa a mostrar "Dona de Casa" nas duas linhas. | design v1 ("filiais são CNPJs diferentes e isso é o comportamento certo") |
| B4 | (aberto — Q7) Parser passa a extrair **bairro/endereço** da nota; `stores` ganha coluna (migração `0002`); `mercados listar` mostra o bairro; B2 sugere o apelido já com bairro. Custo: parser + primeira migração real do projeto. Sem isso, B2 sugere só "<apelido> — filial 0003". | F11 |
| B5 | Agrupamento visual por rede em `mercados listar`: **já acontece** pela ordenação por CNPJ (F12). Nada a fazer. | F12 |

### RF-C — Tags e curadoria em lote (G3)

| # | Requisito | Origem |
|---|---|---|
| C1 | Novo comando **`julius produtos revisar`** (nome — Q9). Percorre produtos **sem tag** (opcionalmente também sem conteúdo), chama a IA em **lotes** (~30 produtos por chamada, uma lista JSON de volta) e, por produto: **aplica** a tag sem perguntar quando a IA devolve **uma única** categoria da lista controlada; **pergunta** quando devolve 2–3 candidatas ou "incerto" — mostra as opções numeradas + "outra (digitar)" + "pular". Flag `--sim/-y` aplica a melhor sugestão em tudo sem perguntar (script, Telegram futuro). | pedido do usuário, F9 |
| C2 | **Vocabulário controlado**: lista fixa de categorias-corredor no prompt (ordem de grandeza 12–15: `hortifruti`, `carnes`, `frios-laticinios`, `padaria`, `mercearia`, `bebidas`, `limpeza`, `higiene`, `congelados`, `temperos`, `doces`, `utilidades`, …) **mais** as tags que já existem no banco. O modelo escolhe da lista; o usuário pode sempre digitar uma custom. Sem lista fixa o vocabulário fragmenta (`carne`/`carnes`/`proteina`) e `--tag` deixa de funcionar. (Q2: lista fixa × livre; 1 categoria × várias.) | pesquisa §3, F9 |
| C3 | `importar` **continua não interativo**. No fim, dica nova: "N produtos novos sem categoria: `julius produtos revisar`". Convive com `PACKAGE_SIZE_IN_DESCRIPTION` respeitando o máximo de 2 dicas. Isso **fecha a questão em aberto nº 2 do `CLAUDE.md`** ("revisão periódica de produtos pendentes") — a resposta é `revisar`, com IA. | design v1 |
| C4 | **Pré-requisito de C1:** comando pra remover tag — `julius produtos tag ID TAG --remover` (ou `destag`). Sem desfazer, não há gravação automática (§2). | F10 |
| C5 | Na **mesma chamada em lote**, a IA pode devolver também, por produto: (a) **nome legível** expandindo abreviações (`LING FGO RESF AURORA kg` → "Linguiça de frango resfriada Aurora kg"); (b) **conteúdo da embalagem** quando inequívoco (`OVO BCO GRANDE C/30` → 30 UN; `CHA LEAO … 16G C/10UN` → incerto). Política: nome → Q5 (auto ou confirmar); conteúdo → **sempre confirmar** (decisão v1 mantida: números ambíguos). `suggest_content` ganha finalmente um chamador. A descrição crua nunca se perde: fica em `prices.description`. | design v1 "Preço por conteúdo", F9 |
| C6 | (aberto — Q6) **Duplicatas entre mercados**: `revisar` lista pares candidatos (pré-filtro rapidfuzz alto + IA julga, prompt de `suggest_merge`) e imprime `julius produtos fundir A B` pronto — **nunca executa**. É em lote, sob pedido, fora de `consultar`: não contradiz a rejeição v1 de sugestão automática não pedida. Caso real: ids 2 e 68. | F9 |
| C7 | Custo esperado: 70 produtos ≈ 3 chamadas ≈ 6–8k tokens ≈ **US$0,003**. Orçamento é irrelevante; o custo real é **latência** (2–5 s por lote) e **atenção do usuário** nas perguntas — daí lote, não uma chamada por produto. | conta de padaria |

### RF-D — IA na consulta (G4)

Restrição mantida: resultado **não vazio** de `consultar` nunca chama IA (roda várias vezes ao dia; latência de rede no caminho feliz é inaceitável).

| # | Requisito | Origem |
|---|---|---|
| D1 | IA **só como fallback quando o resultado determinístico vem vazio** — exatamente onde hoje saem `NO_MATCH_DID_YOU_MEAN`/`NO_MATCH_TRY_TAGS`. Envia termo + lista de nomes (+ tags) e pede os ids que casam. Se achar: mostra a tabela normal com aviso discreto "encontrado via IA" **e** a dica de tornar permanente (`produtos renomear`/`produtos tag`). Se não: dicas atuais. | pedido do usuário |
| D2 | **Não cachear** respostas de D1. A solução durável pra um miss é **corrigir o dado** (nome legível via C5, tag via C1): depois de `revisar`, `consultar linguiça` acha "Linguiça de frango…" pelo rapidfuzz, de graça e sem rede. D1 é rede de segurança, não mecanismo principal. | ladder: consertar o dado uma vez > chamar IA toda vez |
| D3 | Fora: veredito "caro/barato" (decisão v1 fechada), perguntas em linguagem natural livre, IA em resultado não vazio, `--sem-ia` (se não configurada, nada muda). | design v1 |
| D4 | (aberto — Q6) Fazer D1 **agora** ou **medir** primeiro quantos misses sobram depois de C5 rodar no catálogo real? Recomendação: C primeiro, D1 só se os misses continuarem incomodando. | — |

## 4. Requisitos não funcionais

- **N1** Invariante "nunca lança" cobre também escrita do log e parse do JSON (já cobre; formalizar em teste).
- **N2** Orçamento: US$5/mês (já exportado). Toda chamada, inclusive lote e fallback, passa por `is_available`.
- **N3** Zero dependência nova. Prompt interativo com `typer.prompt`/`rich.prompt`.
- **N4** Testes: `LlmClient` fake; log JSONL em `tmp_path`; nenhum teste toca a rede; teste de que **cada** silêncio de A8 gera a mensagem certa.
- **N5** Arquitetura DAG preservada: escrita do log é `infra`; decisão "aplicar × perguntar" é `services`; prompt interativo é `cli`. `tests/test_architecture.py` continua a fonte da verdade.
- **N6** Migração `0002` só se B4 entrar; primeira migração real exercita o backup `prices.db.bak-v1`.
- **N7** Nada de IA grava o irreversível (fusão, `prices`).
- **N8** `CLAUDE.md` atualizado ao fim do design: F1 (cliente HTTP já existe), F7 (evidência dos endereços), princípio revisado da §2.

## 5. Histórias de usuário e critérios de aceite

- **H1 — Primeira chamada real.** `julius produtos comparar 63 69` imprime veredito da IA com `rationale` sobre os dois tomates; `ai_calls.jsonl` ganha uma linha com tokens, custo e latência; `ai_usage` soma o custo do mês.
- **H2 — Filial reconhecida.** Importar uma nota de CNPJ novo com radical já conhecido imprime a dica de B2 com o comando `renomear` pronto pra copiar.
- **H3 — Revisão em lote.** Num catálogo com 70 produtos sem tag, `julius produtos revisar` termina em menos de 1 minuto, aplica ≥ 80% sem perguntar, pergunta o resto com 3 opções + custom + pular; depois, `julius consultar --tag carnes` retorna picanha, fraldinha, contra-filé, linguiça e bacon.
- **H4 — Desfazer.** `julius produtos tag 31 hortifruti --remover` remove a tag; `produtos listar` reflete.
- **H5 — Busca por abreviação.** Antes de revisar, com IA configurada, `julius consultar linguiça` acha `LING FGO RESF AURORA kg` via fallback e avisa; depois de revisar (nome expandido), acha pelo rapidfuzz sem chamar IA (verificável pelo log: nenhuma linha nova).
- **H6 — Falha silenciosa diagnosticável.** Com API key inválida, todos os comandos funcionam; `comparar` diz "falha na chamada (ver ai_calls.jsonl)"; o log tem a linha com `error` preenchido.
- **H7 — Orçamento.** Com `JULIUS_AI_BUDGET_USD=0.0001` e uma chamada já registrada, `comparar` diz "orçamento do mês esgotado" e **não** toca a rede (log sem linha nova).

## 6. Smoke test — antes de qualquer código (tarefa do usuário, F5)

1. Confirmar F6: ajustar `JULIUS_AI_MODEL` ou os dois preços.
2. `julius produtos comparar 63 69` — se imprimir a linha "IA: …", o caminho inteiro funciona.
3. Se disser "IA indisponível", isolar provedor × código com uma chamada direta (JSON mode incluído):

```bash
curl -s "$JULIUS_AI_BASE_URL/chat/completions" \
  -H "Authorization: Bearer $JULIUS_AI_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"'"$JULIUS_AI_MODEL"'","messages":[{"role":"user","content":"Responda em json: {\"ok\": true}"}],"response_format":{"type":"json_object"},"max_tokens":20}'
```

Resposta com `"content":"{\"ok\": true}"` e um bloco `usage` confirma modelo, chave e JSON mode de uma vez.

## 7. Questões em aberto (decisão do usuário)

| # | Questão | Recomendação |
|---|---|---|
| Q1 | `deepseek-v4-pro` com preço do `flash` foi intencional? | Conferir a página de preços da DeepSeek e alinhar as três variáveis; sem isso o teto de US$5 é fictício. |
| Q2 | Tags: lista fixa de categorias-corredor ou vocabulário livre? Uma categoria por produto ou várias? | Lista fixa + tags existentes + custom; **uma** categoria automática, outras à mão. |
| Q3 | Onde fica a interação: comando separado `produtos revisar` ou perguntar dentro do `importar`? | Separado. Preserva `importar` não interativo e o `*.html` em lote. |
| Q4 | Critério de "incerto": IA devolve 2+ candidatas, ou threshold em `confidence`? | Nº de candidatas. `confidence` de LLM é mal calibrado. |
| Q5 | Nome legível expandido: auto-renomear (crua fica em `prices.description`) ou confirmar cada um? | Auto-renomear com `--sim`; sem flag, mostra "antes → depois" e pede confirmação em lote (uma pergunta, não 70). |
| Q6 | Fallback de IA em `consultar` (D1) e detecção de duplicatas (C6): agora, ou depois de medir o efeito de C5 no catálogo real? | Depois. C5 resolve a maior parte dos misses de graça. |
| Q7 | Extrair bairro/endereço do mercado no parser (migração 0002) ou apelido manual basta? | Manual por enquanto; B2 já entrega o comando pronto. Reavaliar se surgirem mais redes com várias filiais. |
| Q8 | `julius ia status` vale um comando? | Não agora; `tail`/`sqlite3` cobrem. Volta se A8 não bastar. |
| Q9 | Nome do comando: `revisar`, `classificar` ou `curar`? | `revisar` — é o termo que já aparece no `CLAUDE.md` ("revisão periódica"). |

## 8. Fora do escopo desta rodada

Fallback automático entre provedores · `reasoning`/streaming/tool calling · dashboard ou rotação de log · fusão automática (produtos ou mercados) · veredito de preço · busca semântica/embeddings · Telegram/OCR · sugestão de IA em resultado não vazio de `consultar`.
