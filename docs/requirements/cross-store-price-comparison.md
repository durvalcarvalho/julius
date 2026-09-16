# Julius — comparar preços entre lojas e ajudar a achar o melhor: requisitos

> **Q1–Q5 fechadas em `docs/requirements/comparability-closure.md` §5** (mesmo dia). Em resumo: sem whitelist de categoria — a regra é KG compara direto, UN exige `content`; comparação entre mercados sai agora com `n` e período explícitos; dia da semana vira só uma coluna, sem afirmação; a varredura de catálogo foi medida (19 pares) e o custo real migrou para o caminho de `enrich`.

> Brainstorm de 2026-09-16 (`/sc:brainstorm`), continuação da sessão anterior. O usuário rejeitou explicitamente o escopo "só mesmo produto, na mesma loja" da resposta anterior: quer comparar entre lojas, aceitar produtos "praticamente iguais" mesmo com descrição levemente diferente (tomate com tomate), saber se um mercado em geral é mais caro que outro, e se dia da semana influencia o preço — resumo do próprio usuário: "eu quero que a ferramenta me ajude a achar os melhores preços".
> Insumos: resposta do usuário; banco de produção real (`~/.local/share/julius/prices.db`); código de `julius/services/curation.py::duplicate_candidates`, `julius/services/search.py::_highlight_and_trim`; `CLAUDE.md` (seção "Identidade de produto e busca", decisão já registrada de rejeitar fusão automática por similaridade de texto).
> Próximo passo: `/sc:design` → tickets em `docs/tickets/julius-v2/` (117+). Ver também `docs/requirements/import-price-signal.md` (corrigido nesta sessão — o sinal de novo mínimo/máximo já compara entre lojas de graça quando o produto foi fundido).

## 0. Ponto de partida — fatos verificados

| # | Fato | Evidência |
|---|---|---|
| F1 | **O mecanismo pedido já existe e já foi usado.** `product_id` 5 (Cebola) e 63 (Tomate Italiano União) já têm SKUs em duas lojas diferentes cada — foram fundidos manualmente (`julius produtos fundir`) antes desta sessão, exatamente o caso do tomate já registrado no `CLAUDE.md` ("Confirmação real do caso que `produtos fundir` existe para resolver"). | `product_skus`/`prices` reais, query feita nesta sessão. |
| F2 | Depois de fundido, `julius consultar <nome>` já mostra as linhas das duas lojas juntas, com apelido e endereço, na mesma tabela — e `_highlight_and_trim` (`services/search.py:152-165`) já computa `lowest`/`highest` **através de todo o grupo da mesma unidade, independente de loja ou `product_id`** — não é preciso nenhum código novo pra "qual loja tá mais barata nesse produto já fundido". | Saída real de `julius consultar cebola`/`julius consultar tomate` nesta sessão; `services/search.py::_highlight_and_trim`. |
| F3 | O que falta **não é o mecanismo de fusão** — é descobrir candidatos a fundir sem depender só do fluxo de import. `curation.duplicate_candidates(conn, product_ids=None)` já varre o catálogo **inteiro** (não só produtos novos) quando chamado com `product_ids=None` — mas hoje nada no código chama essa função assim; ela só é usada dentro da revisão de import, restrita aos produtos daquele lote (`product_ids=<novos>`). É uma lacuna de "encanamento" (falta um ponto de entrada), não uma funcionalidade ausente. | `services/curation.py::duplicate_candidates`, `judge_duplicates`; uso atual em `cli/_review.py`. |
| F4 | Fusão via similaridade de texto pura já foi testada e rejeitada como automática — o próprio `CLAUDE.md` cita `SUCO ... UVA` vs `SUCO ... LARANJA` e `REFRI PEPSI PET 2L` vs `PET 1L` como casos onde nomes parecidos são produtos diferentes de propósito (sabor, tamanho). **Confirmado de novo hoje**, agora com dado real: a busca "tomate" retornou `TOMATE TREBESCHI 250G DUO` (R$ 9,90/UN = R$ 39,60/kg equivalente) numa tabela separada de `TOMATE ITALIANO ... kg` (R$ 11,89–14,99/kg) — mesma palavra, unidade e produto genuinamente diferentes; `search_prices` já os mantém separados por `unit`, mas não saberia (nem deveria, sem confirmação) que um tomate em caixinha de presente não é comparável a tomate a granel. | `julius consultar tomate`, saída real nesta sessão. |
| F5 | **Sobreposição real hoje é muito pequena**: de ~105 produtos no catálogo, só 2 (`Cebola`, `Tomate Italiano União`) têm SKU em mais de uma loja — o suficiente pra provar o mecanismo, não pra calcular um índice de preço por mercado com significância. | Query em `product_skus`/`products` nesta sessão. |
| F6 | **Não há repetição de dia da semana nos dados reais.** As 6 notas do banco caem em sexta, sábado, segunda, quinta, sábado, quarta — seis datas, seis dias da semana diferentes, zero repetição do mesmo produto no mesmo dia da semana em datas diferentes. | Query em `prices` (datas + `datetime.weekday()`) nesta sessão. |

## 1. Objetivo

Ajudar a decidir onde e quando comprar mais barato, indo além de "esse preço bateu meu próprio histórico nesta loja" (escopo da rodada anterior, já corrigido). Três perguntas distintas do usuário, com viabilidade bem diferente hoje:

1. **Entre lojas, pra produtos praticamente iguais** ("tomate com tomate") — mecanismo já existe (F1/F2); falta um jeito sistemático de achar os candidatos pra fundir, além de esperar o import sugerir.
2. **"Esse mercado em geral é mais caro?"** — cálculo novo, hoje sem dado suficiente pra ser mais que ruído (F5) — mesma lição já aprendida com "sem veredito automático" na rodada anterior, agora aplicada ao nível de loja em vez de produto.
3. **"Comprar verdura na quarta é mais barato que na sexta?"** — sem nenhuma repetição de dia da semana nos dados reais (F6); não é "pouco dado", é dado zero pra essa pergunta específica.

## 2. Requisitos funcionais

### 2.1 Achar candidatos a "mesmo produto" entre lojas, fora do fluxo de import

| # | Requisito |
|---|---|
| RF1 | Deve existir um jeito de rodar a varredura de duplicatas (`duplicate_candidates` com `product_ids=None`, já suportado hoje) sobre o **catálogo inteiro**, não só sobre produtos recém-importados — pra achar candidatos como Cebola/Tomate mesmo quando os dois lados já existiam há tempo no catálogo. |
| RF2 | O resultado continua sendo **sugestão, nunca fusão automática** — mesma disciplina de `produtos comparar`/`judge_duplicates` hoje: imprime o comando `fundir` pronto, quem decide roda. |
| RF3 | A varredura deve poder ser restrita por categoria/tag (ex.: só `hortifruti`) — ver F4/RF-scope abaixo: fora de hortifruti, "quase igual" é mais perigoso (sabor, tamanho da embalagem mudam o produto de propósito). |

### 2.2 Índice de preço por mercado

| # | Requisito |
|---|---|
| RF4 | Deve ser possível perguntar, para os produtos já fundidos entre lojas, qual loja tende a ser mais cara/barata — reaproveitando os mesmos preços que `consultar` já mostra, sem inventar uma nova fonte de dado. |
| RF5 | O cálculo deve deixar claro **quantos produtos** sustentam a comparação (hoje: 2) — não apresentar uma opinião de "mercado caro/barato" sem mostrar o tamanho da amostra, mesmo princípio já usado pra "sem veredito com histórico curto". |

### 2.3 Padrão por dia da semana

| # | Requisito |
|---|---|
| RF6 | Fica **registrado como pedido**, não como trabalho desta rodada (ver F6, Fora do escopo) — sem requisito funcional a especificar até haver dado real que sustente a pergunta. |

## 3. Requisitos não funcionais

- **N1** RF1–RF3 não reabrem "fusão automática": toda decisão de identidade continua manual, via `produtos fundir`, com ou sem opinião da IA — mesma linha vermelha já traçada no design (F4).
- **N2** RF4/RF5 não podem virar um número único e confiante ("mercado X é 12% mais caro") sem expor o tamanho da amostra — mesmo espírito do requisito de coverage já aplicado ao sinal de import.
- **N3** Zero dependência nova esperada — `duplicate_candidates`/`judge_duplicates` já existem; um índice por loja é agregação sobre `prices`/`product_skus`, SQL simples.
- **N4** Nenhuma mudança em `search_prices`/`consultar` — o comportamento hoje (F2) já serve de base, não precisa mudar pra isso funcionar.

## 4. Decisões do usuário (Q&A do brainstorm)

| Questão | Decisão |
|---|---|
| "Só mesmo produto, mesma loja" está certo? | **Não** — o usuário quer comparação entre lojas, e produtos "praticamente iguais" mesmo com descrição levemente diferente (ex.: tomate com tomate, independente da variedade). |
| O que o usuário quer que o Julius faça com isso? | Ajudar a achar os melhores preços — responder "esse mercado tá mais caro?" e "tem dia melhor pra comprar verdura?", não só "esse preço específico é bom". |

## 5. Histórias de usuário

- Como usuário, quero que o Julius me aponte quando dois produtos de lojas diferentes (ex.: dois tomates com descrições parecidas) provavelmente são o mesmo item pra fins de comparação de preço, sem eu precisar notar isso sozinho e sem esperar aparecer batendo um import.
- Como usuário, depois de fundir alguns produtos entre lojas, quero perguntar "esse mercado tá mais caro que aquele outro?" e ver uma resposta que já me diz em quantos produtos ela se baseia.
- Como usuário, gostaria um dia de saber se tem um dia da semana melhor pra comprar hortifruti — sabendo que hoje não tenho dado nenhum pra isso.

## 6. Questões em aberto (para `/sc:design`)

| # | Questão | Observação |
|---|---|---|
| Q1 | "Praticamente igual" (RF1/RF3) deve ser restrito a certas categorias (hortifruti, carnes por corte) ou vale pra qualquer produto? | F4 mostra o risco concreto fora de hortifruti (sabor/tamanho mudam o produto) — decidir se o escopo restrito é uma regra do sistema ou só uma recomendação de uso. |
| Q2 | RF1 é um comando novo (`julius produtos comparar-tudo`?), uma flag em `produtos revisar`, ou parte de um comando dedicado a "índice de mercado"? | Superfície de CLI é decisão de design, não desta lista. |
| Q3 | O índice de preço por mercado (RF4/RF5) deve esperar até haver mais produtos fundidos entre lojas (hoje: 2), ou vale mostrar já, sempre com o tamanho da amostra explícito? | Paralelo direto com a decisão já tomada pro sinal de import (`import-price-signal.md`): esperar mais dado é uma opção legítima, não é obrigatório resolver estatística com 2 pontos. |
| Q4 | Padrão por dia da semana (RF6): qual seria o gatilho mínimo de dado pra reabrir essa pergunta — X compras do mesmo produto em pelo menos 2 dias da semana diferentes? Depois de quanto tempo de uso isso é realista pra um catálogo pessoal? | Não decidir agora — só deixar registrado que a resposta de hoje é "sem dado", não "não". |
| Q5 | RF1 (varredura de catálogo inteiro) custa uma chamada de IA por par candidato (via `judge_duplicates`) — com ~105 produtos, quantos pares acima do corte de similaridade (`DUPLICATE_CANDIDATE_CUTOFF = 75`) existem hoje, e isso cabe no orçamento de US$5/mês se rodado sob demanda (não a cada import)? | Medir antes de desenhar — `duplicate_candidates` já limita a `MAX_DUPLICATE_PAIRS = 20` por chamada, mas nunca foi rodado com `product_ids=None` de verdade. |

## 7. Fora do escopo desta rodada

**Padrão por dia da semana** — não há dado real que sustente esse requisito hoje (F6); fica registrado como aspiração, não como trabalho a especificar, até o gatilho da Q4 ser decidido e atingido. **Índice de preço por mercado com poucos produtos fundidos** (RF4/RF5) pode virar, na prática, "esperar mais fusões" em vez de código novo — mesma resposta que "mais dado, não mais estatística" já dada na rodada anterior. **Fusão automática sem confirmação** continua rejeitada (N1) — RF1 amplia onde a sugestão é procurada, nunca quem decide aplicá-la.
