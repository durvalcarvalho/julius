# precos-dos-mercados

## Objetivo

Ferramenta pessoal (CLI) para registrar os preços pagos em compras de mercado (a partir de recibos NFC-e) e depois **comparar** um preço com o histórico — "R$12/kg de banana tá caro?" — junto com o local onde cada preço foi pago.

Não é uma ferramenta de comparação entre mercados em geral nem de controle de gastos: é memória de preços + decisão de compra.

## Status

Fase: **v2.7 em implementação** — a voz do Julius no bot, tickets 163–168 de `docs/tickets/julius-bot/` feitos (169, docs+smoke, é o que fecha a trilha; parágrafo próprio abaixo). Antes dela, **v2.6 implementada** — o bot no Telegram, tickets 150–162, um commit por ticket, sem migração (parágrafo próprio abaixo). Antes dela vieram a v2.4, a v2.5 e a v2.5.1, depois dos 36 tickets da v2: a v2.5 é a nomeação automática de mercado e a v2.5.1 a data legível, as duas sem ticket numerado em `docs/tickets/` e sem migração — ver abaixo. Em paralelo, os tickets 147–148 entregaram o **RF0** da frente "nenhuma comparação sem os dois nomes" (coluna "Produto" no `mercados comparar`, nome do produto batido no sinal do `importar`); o RF1 e o RF2 dessa frente seguem abertos por decisão do próprio design (`docs/design/differentiated-kinds.md` §7). Os 36 tickets de `docs/tickets/julius-v2/` estão feitos (101–114 da v2, 115–116 da v2.1, 117–130 da v2.2, 131–136 da v2.3), um commit por ticket. Somando tudo: **949 testes verdes** (`.venv/bin/pytest -q`), nenhum `NotImplementedError`, nenhum identificador em português. Provedor de IA: DeepSeek, modelo `deepseek-flash`, `thinking` desligado via `JULIUS_AI_REQUEST_EXTRAS='{"thinking":{"type":"disabled"}}'` (sem isso o modelo raciocina em vez de responder — ver "Fatos e pegadinhas"). Orçamento US$5/mês.

Ambiente: `make install` instala `julius` global via `pipx install --editable .` (aponta pro código do diretório — editar ou trocar de branch já vale, sem reinstalar; rode de novo só se o `pyproject.toml` mudar). `make install-bot` faz o mesmo com o extra `bot`, e é o que deixa o executável `julius-bot` disponível. `make test` cria o `.venv/` na primeira vez e roda o pytest. `make uninstall` remove. **O `.venv` desta máquina é Python 3.14**; se `VIRTUAL_ENV` estiver exportado apontando para outro projeto, `python3 -m venv` do Makefile pega o interpretador errado — use `env -u VIRTUAL_ENV /usr/bin/python3` ao recriar o `.venv` do zero.

**v1.1 (módulo de dicas de uso)** — tickets 015 e 016 (v1). Nasceu do primeiro uso real (`consultar` num banco vazio dizia só "Nenhum resultado."). Ver "Dicas de uso (`guidance`)"; a única diferença em relação ao design original está registrada lá (`closest_names` compara palavra a palavra, não por faixa de WRatio).

**v2 (IA na prática)** — tickets 101–114. A IA passou de "só testada com fake" para uso real: `julius produtos revisar`/`importar` aplicam nome legível e categoria automaticamente (reversível), sugerem conteúdo de embalagem e candidatos a duplicata; `consultar` cai para a IA só quando a busca determinística vem vazia; endereço do mercado aparece em `mercados listar`/`consultar`/`exportar`. Ver "Camada opcional de IA" (contrato atual) e "Dicas de uso" (3 dicas novas).

**v2.2 (comparabilidade: comparar antes de opinar)** — tickets 117–130, migração 0003. Três trilhas que se juntam: (1) **grupo de comparação** — `products.kind` ("que tipo de coisa isso é": `tomate`, `leite uht`), proposto pela IA e aplicado automaticamente, com `julius produtos tipo ID [--remover]` pra corrigir e a coluna "Tipo" em `produtos listar` pra ver o erro; (2) **comparar de verdade** — `domain/comparison_basis.py` corrige a base do mínimo/máximo (ver "Preço por conteúdo"), `julius mercados comparar` responde "esse mercado é mais caro?" por grupo com `n` e período, e `importar` termina com o sinal "Nesta compra:" dos itens que bateram recorde; (3) **arquivamento** — `julius importar` sem argumento varre `entrada/` e move cada nota importada pra `entrada/importados/<data>_<chave>.html`. Toda gravação automática vira uma linha em `~/.local/share/julius/actions.jsonl`, com o comando de desfazer, lida por `julius produtos revisar --ultimas-acoes`. Contrato completo em `docs/design/comparability-v2.2.md`.

**v2.3 (escopo da revisão e HITL de conteúdo)** — tickets 131–136, sem migração. Duas mudanças que se puxam: (1) **pendência por campo faltando** — `curation.pending_product_ids` deixou de ser "produto sem tag" e passou a ser `products.incomplete_product_ids`: falta tipo, falta categoria, **ou** falta conteúdo num produto vendido por UN. Medido no banco real: **86 dos 105 produtos** entram na fila, contra 4 pelo critério antigo. Conteúdo só é cobrado de quem é vendido por UN porque R$/kg **já é** preço por conteúdo (ramo 1 de `comparison_basis`); sem essa exceção, 26 produtos ficariam pendentes para sempre sem nada a ganhar. (2) **a revisão parou de perguntar categoria e passou a perguntar conteúdo** — a categoria aplicada é a primeira candidata **que já existe** no vocabulário (ver "Camada opcional de IA"), sem pergunta nenhuma; a única pergunta que sobrou é o conteúdo que a IA **se recusou** a afirmar, alimentada por uma segunda chamada de intuição de varejo que nunca grava. A tabela também parou de mentir: valor atual em cinza distingue "já resolvido" de "a IA não soube" (das 25 linhas da tela real, 9 em branco **já tinham** conteúdo), e a coluna "Cupom" mostra `prices.description` em vez de `canonical_name`, que deixa de ser o texto do cupom no primeiro `renomear`. `--sim` mudou de sentido: agora é "não perguntar nada". Contrato completo em `docs/design/review-scope-v2.3.md`.

**v2.3.1 (a busca por termo estava invertida)** — sem ticket, correção vinda do primeiro uso real do catálogo já enriquecido pela IA. `julius consultar pao` devolvia 12 frutas e 1 pão, e `consultar pao padaria` devolvia 1 linha de 4 possíveis. Causa: `fuzz.WRatio` penaliza termo curto contra nome longo, e os nomes legíveis escritos pela IA são longos — o corte de 70 passou a barrar os acertos e aceitar o ruído. Trocado por comparação palavra a palavra com corte 80 (`_name_score`, `MATCH_SCORE_CUTOFF`), medido contra os 105 produtos do banco real. Detalhes e números em "Identidade de produto e busca".

**Rodada real da v2.3** (16/09/2026, contra cópia do banco de produção, `deepseek-flash`): 86 produtos na fila, 4 chamadas `enrich` + 1 `merge` + 1 `packaging`, **US$ 0,0095** no total. Aplicou 1 nome, 5 categorias, 18 conteúdos e 79 tipos sozinha; sobraram **5 perguntas de conteúdo** (Sacola reutilizável, Brócolis Ninja, Filme PVC, Prato descartável, Espátula). `OVOS IANA 30UN MEDIO BCO` recebeu `30 UN` automaticamente — fecha a questão 5 dos requisitos: o caso que motivou o preço por conteúdo se conserta sozinho, porque o rótulo é inequívoco. A pergunta do Filme PVC saiu com o candidato errado conhecido (`[1] 30 UN · unidade`, de "30m x 28cm"): é o desenho funcionando, pular é a resposta certa.

**v2.4 (fusão reversível e a leitura por unidade base)** — tickets 137–146, migração 0004. Duas frentes independentes: (1) **fundir deixou de ser destrutivo** — `products.merged_into` mais a view `product_group` fazem da fusão um *estado*: nada é apagado, nenhuma linha de `prices` troca de `product_id`, e `julius produtos desfundir ID` devolve o estado anterior por construção. Com o desfazer existindo, a revisão passou a **fundir o que a IA confirma e pedir conferência**, em vez de imprimir comandos (ver "Identidade de produto e busca"). (2) **a tabela do `consultar` parou de mentir e passou a responder** — linhas idênticas (mesmo produto, dia, mercado e preço) colapsam, a ordem dentro do grupo segue a base que `comparison_basis` já escolhe, e uma linha final diz qual embalagem compensa. Contrato completo em `docs/design/merge-and-unit-price-v2.4.md`.

**Rodada real da v2.4** (17/09/2026, contra cópia do banco de produção reprocessada do zero — 108 produtos, todos pendentes): aplicou 104 nomes, 108 categorias, 72 conteúdos e 107 tipos, e fez **4 fusões automáticas, todas corretas**, por **US$ 0,0100**. Três delas (`Tomate italiano`, `Cebola`, `Sacola reutilizável`) são exatamente as fusões que o usuário já tinha feito à mão — o sistema reproduziu o julgamento humano registrado. Nenhum falso positivo, nenhuma das 132 linhas de preço reatribuída, e `produtos desfundir 82` devolveu o produto separado. No banco curado, `consultar agua` caiu de **9 para 4 linhas** e termina com *"Mais barato por litro: Água mineral Indaiá 1,5L a R$ 2,46/L — contra R$ 3,58/L de Água Crystal com gás 500ml"*.

**v2.5 (o apelido do mercado já nasce reconhecível)** — sem ticket, sem migração. Nasceu de dois usos reais seguidos: ele rodou `mercados renomear` duas vezes para separar as filiais da Dona de Casa, e depois resumiu o problema — "razão social é uma merda, o que o usuário sabe mesmo é o nome fantasia, e o lugar onde ele foi; se `consultar` retornar um nome estranho ele nem vai saber onde é". O apelido faz **dois** trabalhos e só um tinha fonte local: o **lugar** já estava em `stores.address` (bairro = segmento `[-3]`, medido 5/5; a **cidade é `BRASILIA` em 5 de 5**, e é por isso que o campo "município" de uma API de CNPJ não separaria filial nenhuma), o **nome fantasia** não está em fonte local nenhuma (0 ocorrências nos 6 HTMLs; o PDF é imagem única, exigiria OCR). Duas fontes externas foram medidas e são **complementares, não redundantes**: o registro de CNPJ cobre 4/5 (acerta `COMERCIAL DE ALIMENTOS HTP LTDA` → **SUPERMERCADO VENEZA**, a única loja que ele nunca conseguiu renomear porque não dava para saber o que era) e a IA cobre 2/5 (acerta `SENDAS DISTRIBUIDORA S/A` → **Assaí Atacadista**, que o registro deixa vazio) — **a união cobre 5/5**. A ordem é registro → IA só para o que sobrar; `importar` roda **só o registro** (grátis, e reimportar não pode gastar orçamento), a IA roda em `julius mercados revisar`. Contrato completo em `docs/requirements/store-branch-nickname.md`.

**As 2–3 APIs em paralelo que ele pediu foram medidas e recusadas, não por cautela.** Os 4 provedores públicos (BrasilAPI, ReceitaWS, CNPJá, `publica.cnpj.ws`, `minhareceita.org`) devolvem valores **idênticos** para o mesmo CNPJ, inclusive a ausência idêntica — derivam todos do dump aberto da Receita. Correr três compra disponibilidade, nunca cobertura; e a consulta só roda quando aparece loja nova (5 em meses de uso), então redundância contra indisponibilidade é máquina para um problema que não chega a existir. Falha = a loja fica com a razão social e volta na dica que já existe.

**v2.5.1 (a data parou de exigir conta de cabeça)** — ticket 149 (a numeração vive só na mensagem de commit; `docs/tickets/julius-v2/` para em 146, e o mesmo vale para 147–148), sem migração. Nasceu de um uso real: ele rodou `julius mercados comparar`, viu `2026-09-16` na coluna Data e fez duas reclamações numa frase — "não tá no formato do Brasil" e "é difícil saber quantos dias atrás foi, se foi até 15 dias ou se faz 3, 4 semanas ou 1 2 3 meses ou 1 ano e 3 meses". As duas precisam de resposta, então a célula passou a levar `16/09/2026` com `ontem` em cinza embaixo, nos **5** lugares onde uma data é lida (`mercados comparar`, `consultar`, `--ultimas-acoes`, o rodapé `base:` e o sinal "Nesta compra:"); `_day_month`, que estava duplicado literalmente em `cli/stores.py` e `cli/receipts.py`, virou `br_date`/`relative_age`/`date_cell` em `cli/_common.py`. **Uma unidade só acima de semanas**, não um divisor por faixa: com `dias // 365` o dia 364 lê "há 12 meses" com "há 1 ano" a um dia de distância, e limitar meses em 11 faria **essa** faixa subestimar, quebrando o arredondamento para baixo que vale em todas as outras — derivar anos de meses (`meses = dias // 30`, `anos = meses // 12`) mantém o floor honesto e põe a fronteira do ano no dia 360, coerente com o mês já ser 30 dias (aproximação deliberada: a faixa **é** a informação, calendário exato custaria dependência). A idade acompanha data que descreve **uma observação cuja validade o usuário precisa julgar** — linha de tabela e o sinal do `importar` — e **não** acompanha intervalo, e é por isso que o rodapé ganhou só o ano. Medido: a coluna não engordou (`16/09/2026` e `há 13 dias` têm os mesmos 10 caracteres que `2026-09-16` ocupava) e no `consultar` não custou altura, porque `_store_cell` já rendia duas linhas onde a loja tem endereço. **O que limita o que os testes provam**: o banco real tem 6 datas distintas, todas dentro de 13 dias — toda faixa acima de "dias" é sintética em `tests/test_cli_common.py`, mesmo motivo de `synthetic_eggs.html` existir. Contrato completo em `docs/design/readable-dates.md`.

**O bug de fuso que apareceu no caminho** (v2.5.1, fora do pedido e dentro do mesmo código): `cli/_review.py` e `cli/stores.py::log_namings` gravavam `at` em UTC e `--ultimas-acoes` exibia o instante cru — **22:31 para uma ação feita às 19:31**. Formatar aquilo daria autoridade a um número errado, então os dois escritores passaram a gravar local ingênuo, como `prices.purchased_at` já é, e `.astimezone()` na leitura cobre as linhas UTC que já estão no arquivo (converte o que é aware, devolve intacto o que é ingênuo — uma expressão, os dois casos). `query_log.jsonl` **continua UTC**: campo diferente (`ts`), arquivo diferente, nenhum caminho de exibição.

**Regra de teste que a v2.5.1 tornou obrigatória:** teste de nível CLI afirma só a **parte absoluta** da data. Os pontos de chamada não injetam `today`, então um teste que afirme `há 10 dias` passa hoje e quebra quando a fixture cruzar 15 dias — toda afirmação de faixa vive em `tests/test_cli_common.py` com `today` fixo. No caminho apareceu o inverso, que é pior que quebrar: `tests/test_cli_receipts.py` afirmava `"07/09"`, que casa como substring de `"07/09/2026"` e por isso ficaria verde **sem discriminar mais nada**; foi apertado, não deixado passar.

**A recusa da IA foi medida de novo, e é o que autoriza gravar sozinho.** O prompt `store` foi testado com 4 lojas reais **mais 2 razões sociais fabricadas** como controle (uma imitando de propósito o padrão do acerto do registro): recusou as duas, 3 rodadas idênticas, US$ 0,0003 por rodada. Quinta confirmação de que o único sinal confiável do modelo é a recusa — e a primeira fora do domínio de conteúdo. **Mexer no texto do prompt `store` invalida essa medição**, mesma disciplina do `packaging`. Deliberadamente **não** existe detector de "isto é só a razão social reformatada" (`DONA DE CASA S/A` → `Dona de Casa` é indistinguível disso): a ordem das fontes já resolve o caso, e o detector seria heurística nova sem medição.

**Dois defeitos achados pelos testes, anotados porque voltam.** (1) Nomear só com o bairro fazia `nickname != legal_name` e a loja parecia pronta — o nome fantasia nunca era buscado de novo, então uma falha de rede passageira custaria o nome para sempre; hoje `domain.normalization.is_unnamed` trata apelido só-com-lugar como **provisório**, e é a mesma função que as dicas `FIRST_IMPORT_NAME_STORES`/`SAME_CHAIN_BRANCHES` consultam (uma definição só, elas não podem discordar). (2) `fetch_trade_name` como **valor default de parâmetro** é avaliado uma vez no import, então o `monkeypatch` não pegava e **a suíte inteira consultava a API de verdade** (103 s; 11 s depois de corrigir) — resolver pelo módulo na hora da chamada, mais o `_no_cnpj_lookup` autouse no `conftest`.

**v2.6 (o bot no Telegram: uma segunda interface, a mesma camada de serviços)** — tickets 150–162, sem migração. O Julius ganhou uma interface por mensagem, para um usuário só, num PC doméstico que liga e desliga. Cada mensagem passa pela IA (as mesmas três `JULIUS_AI_*` de sempre) que **escolhe uma ação** de um menu fechado de **catorze** funções — quatro de leitura, dez de escrita reversível — e o **código** executa e responde. O texto que chega ao usuário é renderizado do que o banco devolveu; prosa do modelo só chega quando **nenhuma** ação foi escolhida. Nasceram: `julius/bot/` (L4, irmão de `cli/`; nada importa `bot`, e `cli` e `bot` não se conhecem), `domain/formatting.py` (os sete formatadores puros que as duas interfaces precisam — `cli/_common.py` os reexporta), `suggestions.record_usage` (cobrança e log públicos, porque o bot não pode importar `repositories`), `Config.bot_token`/`bot_allowed_chat_id` e o executável `julius-bot` (extra `bot`; `julius` sozinho continua sem `telegram`/`pydantic_ai`, com teste provando). Contrato completo em `docs/design/telegram-bot.md`.

**As decisões que sustentam o bot, e o que cada uma custou.** (1) **Escrita é sempre duas passadas**: a ação resolve os alvos, lê os nomes **do banco** e devolve uma `PendingWrite` — nada é gravado; só o toque no botão chama `execute`. O `undo` é calculado do estado **imediatamente antes** de gravar, não do preview: o usuário pode ter mexido pela CLI enquanto o botão esperava, e há teste que renomeia no meio. (2) **TTL de 300 s**, não 120: o `majordomo` mediu um toque real chegando aos 121 s e sendo derrubado; quem quiser 120 precisa de dado novo. A pendência é limpa num `finally` escrito **antes** dos ramos — uma pendência não limpa trava o chat para sempre. Um nonce velho **não** limpa a pendência nova. (3) **`HISTORY_TURNS = 3`, em turnos inteiros**, nunca mensagens soltas: cortar dentro de um turno deixa uma chamada de ferramenta sem retorno e a API recusa a história. O número veio do custo de tokens, sem medição de uso — ajustar quando `ai_calls.jsonl` mostrar o custo real. (4) **`drop_pending_updates=True`**: o que chegou com o PC desligado não é respondido na volta. (5) **Allowlist é o primeiro `if`** de todo handler, e fora dela é **silêncio** — responder "acesso negado" confirmaria que há alguém aqui. `JULIUS_BOT_ALLOWED_CHAT_ID=0` é o bootstrap: nenhum chat real tem id 0, então o bot sobe configurado e fechado e só registra quem escreveu, e é assim que o usuário lê o próprio id sem depender de um terceiro bot.

**Dois achados de biblioteca que valem mais que o código que geraram.** (1) O PydanticAI expõe uma *output function* como **`final_result_<nome>`**, não pelo nome da função. A receita de teste dos tickets chamava o nome nu, o que cai no caminho de "Unknown tool" — que **ainda assim termina o run**, com a prosa do modelo como saída: um teste descuidado passa pela razão errada. O helper deriva o nome de `__name__` e um teste afirma a convenção, então nem um rename nem uma troca de versão da biblioteca os tornam vazios. (2) `result.usage` é **propriedade** no pydantic-ai 2.44, não `result.usage()`; os nomes dos campos (`input_tokens`/`output_tokens`) estavam certos.

**O que a camada de serviços ensinou ao bot, e não o contrário.** `catalog.get_product` resolve para a **raiz do grupo**, então `Product.merged_into` nunca chega preenchido por `services` — a pré-checagem que o ticket do `unmerge_product` pedia é impossível sem furar a DAG. A pergunta é respondida dentro da camada pedindo por id e comparando o que volta: **id diferente é a fusão**. Duas consequências medidas, as duas mais seguras do que o desenho supunha: um **ciclo de fusão não pode nem ser proposto** (resolver o id absorvido devolve a raiz, então os dois lados voltam iguais e a ação recusa antes do serviço), e **desfundir por nome não pode errar de linha** (depois da fusão o grupo mostra um nome só). Limite anotado no código: o `undo` do desfundir refunde na **raiz**, que é o pai direto de toda fusão feita em um passo; numa cadeia `A→B→C` montada à mão ele poria A sob C — mesmo grupo, nada visível muda, mas um desfundir posterior de B não levaria A junto. Reversão exata exigiria o pai direto, que nenhum serviço expõe.

**Onde está o que, na v2.6:** contrato e decisões em `docs/design/telegram-bot.md` (§9.1/§9.2 guardam o que a implementação descobriu contra o que o design supunha); tickets em `docs/tickets/julius-bot/`, cada um com o commit no bloco `<!-- status:done … -->`; **roteiro de teste manual em `docs/como-testar-o-bot.md`** — é ele que fecha a v2.6, e o resultado volta para o §9.1 do design.

**v2.7 (a voz do Julius) — nasceu de um uso real.** Uma busca de preço pelo bot ("quanto paguei de banana?") respondia com a mesma tabela `<pre>` que a CLI imprime — correto, mas nenhuma pessoa fala assim. O pedido (via brainstorm → design → tickets 163–169, sessão de 2026-09-18) foi usar a IA de verdade para narrar, no tom do personagem (character bible em `docs/requirements/julius-rock-persona.md`), sem deixar isso vazar pro núcleo já testado (`domain/`, `services/catalog|search|comparison`, `repositories/`, `cli/` não mudaram uma linha).

Ponto único: `services/suggestions.py::narrate(conn, config, client, context, facts)` — um prompt (`SYSTEM_PROMPTS["persona"]`), uma guarda (nenhum `R$ X,XX` na resposta que não esteja em `facts` sobrevive), reaproveitado por toda leitura e escrita. `bot/render.py` ganhou o par de cada `render_X`: `*_facts` (texto plano pro prompt) e, só para busca/comparação, `*_fallback_line` (frase determinística, sem IA, pro caminho em que o modelo falha).

**Dois modos, decididos por tamanho.** Busca (≤6 registros) e comparação (≤3 grupos) — Modo A: a narração **substitui** a tabela inteira; sem IA, a frase-molde substitui, **nunca** a tabela crua (é o critério que fecha o problema original). Acima do corte, e para as duas listagens (`produtos listar`/`mercados listar`), Modo B: um comentário curto **por cima** da tabela de sempre, que não muda uma vírgula. As confirmações de escrita (`PendingWrite`/`WriteResult`/`WriteFailed`) entram no Modo B: o preview, o resumo e o `<code>` de desfazer nunca são reescritos, só cercados — narrar antes de `execute()` resolver contradiria "nunca afirme que algo já foi feito", regra que o próprio prompt carrega.

**O achado real do smoke automatizado (via testes, não o smoke do usuário — esse é o ticket 169/passo 16+ de `docs/como-testar-o-bot.md`):** `asyncio.to_thread(suggestions.narrate, deps.conn, ...)`, como o design original pedia pra não bloquear o loop, **lança dentro da thread** — `sqlite3.Connection` recusa ser usada fora da thread que a abriu (`check_same_thread`, ligado por padrão), e o `except Exception` de `narrate()` engolia o erro em silêncio: toda chamada parecia "a IA não disse nada". Corrigido chamando `narrate()` direto, sem thread — o bot já processa updates sequencialmente por desenho (v2.6), então bloquear por uma chamada HTTP curta não custa nada que este projeto não aceite em outro lugar. Ver ajuste anotado em `docs/tickets/julius-bot/167-turn-narration-reads.md`.

**Rodada real da v2.7** (18/09/2026, contra cópia do banco de produção — 105 produtos, 132 preços, 5 mercados, 7 chamadas `persona`, **US$ 0,0014**). Mediu o que a rodada anterior só chutava: `NARRATE_FULL_MAX_RECORDS = 6` cobre **69 das 72 buscas possíveis** (96%, uma palavra por produto, até 50 resultados); o único `mercados comparar` real do catálogo tem **exatamente 6 grupos**, e a IA narrou os 6 inteiros, grounded (nenhum valor fora dos fatos), sem a guarda rejeitar nada — `NARRATE_FULL_MAX_GROUPS` subiu de 3 (chute) para **6** (medido). O caso de 12 registros (mais temperos do catálogo) confirmou o Modo B funcionando como desenhado: a IA resumiu só o mais barato e o mais caro, a tabela ficou intacta embaixo.

**Prompt `persona` v2 (18/09/2026), reescrito a partir de exemplo real do usuário testando o bot de verdade no Telegram.** A v1 lia como "funcional mas comedido" — citava preço, mas sem a personalidade do character bible. O usuário trouxe o corretivo: a resposta tem que vir em **duas partes, sempre nessa ordem** — (1) a informação clara primeiro (preço, **unidade** — nunca omitir se é por quilo ou por unidade — e mercado, com a data), (2) só depois o Julius comenta, podendo usar várias frases, comparação e pergunta retórica ("sabe quanto tempo de luz isso paga?"). Duas mudanças de fundo sustentam isso sem abrir a guarda de dinheiro: (a) `records_facts`/`comparison_facts` (ticket 164, revisado) agora calculam e entregam a **diferença** entre o mais barato e o mais caro como um fato pronto — a IA nunca soma nem subtrai, só cita um valor que já veio nos fatos, mesma disciplina de sempre; (b) a unidade (`o quilo`/`a unidade`/`o litro`) entra explicitamente em cada linha de fato, porque sem ela a IA não tinha como dizer "por quilo" de forma confiável. `search_fallback_line`/`compare_fallback_line` (sem IA) ganharam a mesma unidade e diferença, por consistência — nenhum dos dois precisa de IA pra fazer uma subtração determinística. Reprovado por medição: uma frase que o modelo às vezes soltava explicando por que um dado faltava ("não veio nenhum preço nos fatos...") — quebrava o personagem; uma linha nova no prompt ("não explique a ausência, comente só com o que tem") resolveu, confirmado numa segunda rodada real. `max_tokens` subiu de 220 para 380 (respostas mais longas custam mais tokens de saída; o custo por chamada ainda ficou na casa de **US$ 0,0002 a 0,0007**). `PROMPT_VERSIONS["persona"]` é `"2"`.

**O que essa rodada não cobre**: os botões, a edição de mensagem e o roteiro dentro do Telegram de verdade (passos 1–15 e 19 de `docs/como-testar-o-bot.md`) — só a chamada a `narrate()` foi exercitada diretamente, fora do `python-telegram-bot`. Isso continua sendo do usuário — mas ele já testou o suficiente pelo Telegram de verdade pra saber que o tom da v1 não estava bom, o que é exatamente o tipo de achado que só o uso real revela.

**v2.7.1 (humanização: dia da semana, veredito, dedup, "digitando...")** — tickets 170–174, 2026-09-18. Nasceu de um screenshot real do bot (um parágrafo único, sem quebra de linha, repetindo "Costa Atacadao" duas vezes com o mesmo preço em datas diferentes) e de uma pesquisa externa (`claudedocs/research_chatbot_humanizacao_20260918.md`) que validou os 7 pontos trazidos pelo usuário contra literatura de burstiness, especificidade, Teoria da Relevância e um estudo publicado sobre erro corrigido — com a ressalva de não automatizar esse último sem teste real primeiro (fica fora desta rodada, só anotado). `domain/formatting.py::weekday_phrase` (170) substitui data+"há X dias" por "hoje"/"ontem"/dia da semana/dia da semana passada, reaproveitando o corte de 15 dias que `relative_age` já tinha (nenhum corte novo inventado); acima disso delega pra `relative_age` de sempre. `bot/render.py::_collapse_repeated_prices` (171) colapsa por `(loja, preço)` antes de virar fato — o prompt `persona` v3 (172) ganha lista negra de conectivo de redação, veredito ("compra em X"/"não compra em Y") só com 2+ mercados comparáveis, e o primeiro exemplo de entrada/saída deste prompt (`merge` e `enrich` já tinham; `packaging`/`store`/`match` continuam sem). `bot/app.py::_show_typing` (173) manda o indicador nativo do Telegram antes de responder, sem `asyncio.sleep` — a latência real da IA (~1,3–2,1s, medida nesta rodada) já cobre a janela que a pesquisa aponta como ideal.

**Rodada real da v2.7.1** (18/09/2026, mesma cópia do banco de produção, 15 chamadas `persona`, **US$ 0,0060**). Confirmou o caso que abriu a frente inteira: `_collapse_repeated_prices` colapsa **Cebola de 3 para 2 registros** no catálogo real — exatamente a repetição da screenshot original. Achado que corrigiu um chute: `max_tokens = 260` (o valor inicial do ticket 172, pensado pra respostas mais curtas) truncava (`finish_reason: length`, nas duas tentativas) a narração de uma comparação de 6 grupos — o único `mercados comparar` real do catálogo; `narrate()` devolveu `None` corretamente (a guarda nunca viu um JSON malformado) e o turno caiu pro `compare_fallback_line` desenhado pra isso. Em **500** a comparação completa inteira, grounded, com veredito por grupo ("Compra no Costa Atacadao... pra banana, cebola, tomate e vinho. Compra no Assaí... pra uva."). Exemplo real de busca pequena, já com o formato novo:

> Acém bovino sem osso peça no Costa Atacadao ADE Aguas Claras, quarta-feira: R$ 34,99 o quilo.
>
> Já o AC MASC F TER ES 1kg no Assai Atacadista Guará, sexta-feira passada, saiu R$ 14,85 a unidade, R$ 14,85 por quilo. É mais que o dobro de diferença. Sabe quanto tempo de luz isso paga?
>
> Compra no Assai Atacadista Guará.

**Achado qualitativo, sem métrica**: em contextos sem preço nenhum (catálogo, confirmação de tag), a IA às vezes explica a ausência do veredito ("Sem preço registrado, não tem veredito") em vez de só comentar — não quebra a guarda (não inventa valor), mas é um resquício do mesmo hábito "explicativo" que a v2 já tinha corrigido para ausência de preço; não ajustado nesta rodada por ainda soar dentro do personagem ("sem valor, sem conversa"), mas é candidato a nota de prompt se incomodar no uso real. **O que esta rodada não cobre**: o indicador "digitando..." em si é visual — só aparece dentro do Telegram de verdade, não em `ai_calls.jsonl` — e continua sendo o usuário quem confirma se a janela de 1–2s soa natural na prática.

**v2.8 (várias mensagens curtas, não um textão) — `docs/requirements/bot-message-chunking.md` → `docs/design/bot-message-chunking.md`, 2026-09-19.** Nasceu de um screenshot real: uma pergunta sobre carnes voltou um parágrafo único + duas tabelas `<pre>`, e a seguinte ("qual mercado") voltou outro parágrafo único enumerando banana, cebola, tomate, uva e vinho sem quebra nenhuma. Achado que decidiu o design inteiro: o prompt `persona` **já** separava a resposta em blocos com `\n\n` desde a v2.7 — o bug nunca foi o modelo escrever demais, era `bot/app.py::_send` mandar essa string inteira como uma bolha só do Telegram (`\n\n` vira parágrafo dentro da mesma mensagem, não mensagens novas). Correção de raiz, um lugar só: `bot/app.py::_chunks` fatia por linha em branco e `_send` manda uma `reply_text` por pedaço, teclado de confirmação só no último. Isso sozinho já divide em bolhas toda resposta que a persona já narra (busca de um produto, confirmação de escrita, comentário de listagem), sem tocar em `render.py`.

Para buscas/comparações com muitos itens, `bot/turn.py::_render_output` parou de colar o comentário curto em cima da tabela crua (o antigo corte Modo A/Modo B, `NARRATE_FULL_MAX_RECORDS`/`GROUPS = 6`): a narração agora é sempre tentada, e só cola com a tabela quando não há resposta nenhuma da IA. Sobrou um teto de sanidade novo (`NARRATE_MAX_RECORDS = 40`, `NARRATE_MAX_GROUPS = 20`, ainda placeholder — nenhum caso real do catálogo chega perto) acima do qual a chamada nem é tentada, e o corte de 6 original virou `FALLBACK_LINE_MAX_RECORDS`/`GROUPS`, decidindo só o fallback SEM IA (`search_fallback_line` supõe implicitamente um produto só — não é seguro reaproveitá-lo fora do corte onde isso já tinha sido medido).

Quem agrupa os itens é a própria persona (prompt `persona` v4), não um algoritmo Python novo — decisão do design, porque ela já tinha demonstrado sozinha, na v2.7.1, a habilidade de juntar vários produtos num veredito só. **Medição real corrigiu a primeira tentativa**: com só "agrupe por resultado igual", a tag `hortifruti` (29 registros reais, sem nenhum resultado em comum entre os produtos) truncou (`finish_reason: length`, `max_tokens=500`) — o modelo tentava listar todo mundo agrupado por loja, e cada bloco virava o textão de novo, só que por loja em vez de um parágrafo só. Causa: "agrupar por resultado igual" só funciona quando existe resultado compartilhado (comparação entre mercados quase sempre tem; uma busca ampla por categoria quase nunca tem). O prompt final distingue as duas situações — agrupa quando há padrão, cita só o mais barato/mais caro e a contagem do resto quando não há — com um segundo exemplo de entrada/saída que foi o que fixou o comportamento (só a instrução em prosa não bastou). `max_tokens` subiu de 500 para 900 (headroom puro — nenhuma resposta medida passou de 150 tokens de saída depois da correção). `PROMPT_VERSIONS["persona"] = "4"`.

**Rodada real da v2.8** (19/09/2026, cópia do banco de produção): busca "hortifruti" (29 registros, sem padrão) → 3 blocos, 147 tokens, US$ 0,0010; busca "carnes" (8 registros, o caso exato do screenshot) → 3 blocos, US$ 0,0008, resposta *"Filé de peito de frango Seara... É o mais barato da lista. [...] JERK TRAS FRIB 500G... R$ 24,00 de diferença... Os outros seis ficam no meio, sem nada que grite mais alto que isso."*; `compare_stores` real inteiro (6 grupos, com padrão: Costa Atacadao ganha 4 de 6) → 3 blocos, veredito por grupo. Suíte `real_ai` completa (`pytest tests/test_real_ai.py --real-ai`, ganhou `test_narration_of_many_dissimilar_products_stays_short` fixando este achado): **8 testes, 14 chamadas, US$ 0,01205**, roteamento 5/5. Suíte padrão: **987 passam, 8 pulam** (só os `real_ai`) — sem migração de banco.

**O que esta rodada não cobre**: o roteiro de teste manual dentro do Telegram de verdade (como toda mudança de UI deste bot) — só a divisão em mensagens (`_chunks`/`_send`, testado direto) e a narração (testada com IA real) foram exercitadas fora do Telegram; ver `docs/como-testar-o-bot.md`. Fora de escopo por decisão explícita do usuário no brainstorm: renderizar a tabela como imagem, e cortar o comentário do Julius a ponto de virar resposta só-fato.

**v2.9 (a dica virou comando, e "travou" parou de acontecer em silêncio) — sem ticket, sem migração, 2026-09-19.** Nasceu de um `julius importar` real de 9 arquivos que pareceu travado: na verdade tinha terminado de aplicar 27 nomes/28 categorias/15 conteúdos/28 tipos sozinho e caído direto numa pergunta interativa (conteúdo do produto 109) sem nenhuma linha marcando a virada de "aplicando sozinho" pra "esperando você" — a pergunta lia como mais uma linha de status parada. Na mesma sessão, o usuário reclamou de duas coisas na dica de mercado sem apelido: `julius mercados listar` **e depois** `julius mercados renomear CNPJ "Apelido"` obriga a ir buscar o CNPJ à mão, e "1 mercado(s)" nunca varia com a quantidade que o próprio código já tem em mãos.

Três correntes, uma sessão: (1) `domain/normalization.py::suggest_nickname(legal_name, address)` — o apelido cai pronto pra copiar mesmo quando nem o registro do CNPJ nem a IA sabem o nome fantasia: razão social em Title Case + bairro (`compose_nickname` já dava esse formato pro caso "registro/IA sabem"; este é o terceiro degrau, zero custo, para quando nenhum dos dois sabe). Não é `compose_nickname(legal_name, None, place)` — esse caminho é o que `is_unnamed` já trata como "ainda sem nome" (v2.5), então colar o comando sugerido teria que produzir um texto *diferente* daquele pra realmente fechar a dica; `suggest_nickname` garante isso por constar Title Case, não a razão social crua. (2) `FIRST_IMPORT_NAME_STORES` e `SAME_CHAIN_BRANCHES` (`services/guidance.py`) passaram a carregar CNPJ + apelido sugerido por mercado (não mais uma contagem), e `cli/_hints.py` — que é quem tem a palavra final sobre sintaxe de comando (mesma régra do `_undo_command` de `_review.py`) — vira isso em uma linha `julius mercados renomear CNPJ "Apelido"` pronta por mercado, uma por linha (uma "Dica:" de uma linha só não dava pra colar comando nenhum sozinho). O mesmo tratamento foi replicado em `julius mercados revisar` (`cli/stores.py`) para quem sobra sem nome depois da própria IA tentar. (3) `domain/formatting.py::plural(count, singular, plural_word=None)` (generaliza o `plural_groups` que já existia) resolveu as **nove** ocorrências de `"palavra(s)"` encontradas por grep no projeto inteiro — inclusive dois casos de concordância verbal que só ficaram visíveis depois de consertar o substantivo (`"1 mercado ganharam apelido"`, `"1 mercado continuam com a razão social"`): sem o `(s)` escondendo o problema, a frase parava de fazer sentido em português pra qualquer contagem.

A pergunta interativa em si ganhou uma linha de aviso (`cli/_review.py::_ask_pending_content`, estilo `bold` — todo o resto do bloco de revisão é `dim`, e é essa mudança de estilo que marca a virada): "N produto(s) sem conteúdo — responda ou Enter pra pular:", impressa antes da primeira pergunta, nunca dentro do loop (senão repetiria a cada produto). Medido: **995 testes verdes**, todos os testes que checavam texto de hint/resumo por substring precisaram de ajuste de string (não de lógica) — sinal de que o formato antigo nunca tinha sido pensado para variar com a quantidade.

**v2.10 (veredito por lista de compras, e o mínimo de memória de conversa) — tickets 175–180, sem migração, 2026-09-19.** Nasceu de um screenshot real: "qual mercado eu devo ir? qual é mais barato?" voltou um textão enumerando os **16** grupos do catálogo inteiro — tudo que o usuário já comprou alguma vez, não uma lista de compras. Medido em `ai_calls.jsonl` (17:42:52–57): a narração tentou dar um veredito sobre os 16 juntos e truncou duas vezes (`finish_reason: length`, `max_tokens=500`), caindo na tabela crua por `NARRATE_MAX_GROUPS` já ter sido ultrapassado. Um segundo screenshot ("sim" sem contexto da pergunta anterior do bot) apontou uma causa relacionada: o bot já reenvia histórico bruto (`HISTORY_TURNS = 3`), mas não tinha nenhuma forma de escopar uma comparação — cada pergunta de mercado comparava tudo.

Duas pesquisas (`claudedocs/research_conversation_context_management_20260919.md`, `claudedocs/research_conversation_design_telegram_deepseek_20260919.md`) confirmaram: o problema é *dialogue state tracking*, resolvido desde os anos 1970-80, e o histórico de 3 turnos que já existe provavelmente já cobre a maior parte dos casos de acumular item/responder pergunta pendente — a peça cara (tabela de estado de conversa persistido) não se justificava sem medir primeiro. `docs/design/shopping-list-conversation-context.md` fechou em cinco decisões: (1) `compare_stores` **exige** itens, nunca compara o catálogo inteiro a partir do bot (a CLI, `julius mercados comparar`, continua sem filtro); (2) o veredito ("N de M itens mais baratos em X" + o mercado do resto) é **conta feita em código** (`shopping_verdict`, reaproveitando a mesma técnica de contagem de vitórias que a tabela crua já fazia), nunca a IA somando; (3) empate no topo nomeia as duas lojas, nunca escolhe uma à toa; (4) responder curto a uma pergunta do bot e acumular itens em várias mensagens (RF4/RF5) ganharam só reforço de prompt, **sem** estado novo — decisão explícita de medir o que já existe antes de construir; (5) lembrar além da janela de 3 turnos ficou **fora desta rodada**, sem evidência medida de necessidade real.

`match_kind` (`services/search.py`) casa um item de lista ("leite") com um `kind` conhecido ("leite uht") — e a medição contra os **98 kinds** do catálogo real corrigiu a implementação, não só o número: a primeira tentativa (`fuzz.ratio` na string inteira, o mesmo mecanismo de `detect_tag`) repetiu exatamente o defeito que `WRatio` já tinha causado em busca de produto antes da v2.3.1 — termo curto penalizado contra nome composto. Medido: "leite" pontuava 71 contra "leite uht" (abaixo de qualquer corte seguro) e "agua" pontuava mais em "manga" (67) do que em "água mineral" (50) — um corte mais baixo teria casado errado, não só deixado de casar. Trocado por `_name_score` (o mesmo scorer palavra-a-palavra com bônus de prefixo que a busca de produto já usa): toda palavra genérica testada (leite, pão, água, carne, arroz, queijo, creme, suco, maçã) foi pra 92–100 contra o `kind` certo, e o pior falso positivo real entre termos sem relação ficou em 66,7 — `KIND_MATCH_CUTOFF = 75` cabe exatamente na folga entre os dois, mesma margem que `TAG_MATCH_CUTOFF` já usa pra essa família de scorer.

**Rodada real da v2.10** (19/09/2026, contra cópia do banco de produção, `tests/test_real_ai.py --real-ai`): **9 testes, 16 chamadas, US$ 0,015**. Roteamento **6 de 6** — inclusive os dois casos novos: "qual mercado tá mais barato?" (sozinho) roteou para **texto** (o bot perguntou em vez de comparar tudo — o achado que fecha o incidente original), e "qual mercado é mais barato pra tomate e cebola?" roteou para `compare_stores` com os itens certos. Exemplo real do veredito, grounded (nenhum valor fora dos fatos): *"Cebola: R$ 7,89 o quilo no Costa Atacadao ADE Aguas Claras, na quarta-feira. É o mais barato dos três. [...] Compra no Costa Atacadao."*

**O que esta rodada não cobre**: os passos 21–23 de `docs/como-testar-o-bot.md` (responder curto a uma pergunta do bot e montar a lista em várias mensagens dentro do Telegram de verdade, não só via `handle_text` direto) — o teste real confirma que o *roteamento* com itens explícitos funciona, mas RF4 (religar "sim" à pergunta anterior) e RF5 (acumular menções entre mensagens) são comportamento de prompt que só o uso real, turno a turno, confirma. Se algum dos dois falhar lá, é o gatilho documentado no design para reabrir a Decisão 4 (estado explícito de pergunta pendente) — não implementada nesta rodada.

**v2.11 (a resposta abre com a decisão, item que some vira frase, e um sim/não pro preço visto ao vivo) — `docs/requirements/shopping-verdict-shape.md` → `docs/design/shopping-verdict-shape.md`, 2026-09-19.** Nasceu de três screenshots reais, todos depois da v2.10 já em produção: uma lista de 20 itens terminou em "leva 4 dos 6 itens" (lido como se a lista tivesse 6, não 20); "qual mercado é mais barato pra tomate e cebola?" nunca mencionou tomate; "os ovos tão 14 reais, tá bom?" voltou uma comparação entre lojas em vez de sim/não. **Causa raiz medida ao vivo contra o banco de produção, não suposta**: `match_kind("tomate")` devolvia `"passata de tomate"` — as duas pontuam 100 no scorer palavra-a-palavra, e o desempate por ordem alfabética escolhia a errada (`p` antes de `t`); confirmado batendo o log real (`ai_calls.jsonl`, 2026-09-19T20:52:43) contra a chamada da função ao vivo. O mesmo sintoma já estava, sem ter sido notado, no próprio exemplo "real" da v2.10 duas linhas acima — tomate nunca aparece ali também.

Cinco correções, tamanhos bem diferentes: (1) **`match_kind` corrigido** (`services/search.py`) — entre tipos empatados no score, prefere aquele cujo texto normalizado é EXATAMENTE igual ao termo, antes do desempate alfabético; medido contra os 98 tipos reais e os termos genéricos já documentados no código, só `tomate` e `maca` mudam de resultado, os outros 14 continuam idênticos. (2) **Nenhum item pedido some em silêncio** — `ShoppingComparison` (`bot/actions.py`) ganha `single_store_kinds`/`requested_count`: um termo que casa um tipo mas não tem 2+ mercados agora vira uma frase própria na resposta ("só tem preço de um mercado ainda: X"), distinta de "não reconheço esse item"; e a chamada inteira (itens pedidos, tipos casados, tipos sem comparação) passa a ser gravada em `query_log.jsonl` — o rastro que faltou nesta própria investigação, que precisou rodar `match_kind` manualmente contra produção pra achar a causa. (3) **A resposta abre com a instrução** — o prompt `persona` ganha uma exceção de ordem: nos contextos "veredito de lista de compras" e no novo "conferência de preço ao vivo", a resposta ABRE com a decisão (pra que mercado ir, ou sim/não) e só depois vem a justificativa; nos outros contextos a ordem de sempre (informação, comentário, veredito por último) continua. `PROMPT_VERSIONS["persona"] = "5"`. (4) **Ação nova `check_price`** (`bot/actions.py`, `services/comparison.py`) — confere um preço que a pessoa está vendo agora no mercado contra o mais barato já registrado do mesmo tipo e responde sim/não: a única exceção deste projeto a "nunca dar veredito de preço absoluto" (ver "Requisitos-chave" acima), estreita de propósito — só quando a própria pessoa informa o preço ao vivo, nunca para "está caro?" sem valor nenhum dito (isso continua em `search_prices`, sem opinião). Corte `LIVE_PRICE_TOLERANCE_PCT = 15%`, dentro da faixa 11–42% dos dois únicos exemplos reais do usuário — não uma distribuição, recalibrar no terceiro caso real. A referência é o menor preço já pago, histórico inteiro (mesma semântica do `highlight` de `search_prices`, deliberadamente não a coleta "mais barato por loja" de `compare_stores`, que resolve outro problema); um preço de referência antigo não é escondido — `reference_at` viaja junto nos fatos, e a pessoa julga a validade olhando a data, mesma regra de sempre deste projeto. Nunca adivinha a base de comparação: um tipo com histórico em mais de um `unit` (achado real: "tomate" tem tanto o solto por KG quanto um combo empacotado por UN, `TOMATE TREBESCHI 250G DUO`) devolve `reason="ambiguous_unit"`; um tipo cujo único histórico é UN de produtos diferentes sem conteúdo declarado (mesma regra de "Preço por conteúdo" que já existia) é `reason="no_comparable_basis"`, nunca rotulado como "sem histórico" — há histórico, só não é comparável ainda (achado do próprio processo de teste desta rodada: bati nisso duas vezes escrevendo fixtures antes de nomear o motivo certo). (5) **Agrupar por categoria, no máximo 2 mercados** — `shopping_verdict` (`services/comparison.py`) ganha `category_of` opcional (`products.kind_categories`, nova função, medida contra o catálogo real: **98 de 98 tipos já têm tag**, só 4 com tags divergentes entre produtos do mesmo tipo); quando informado, o veredito agrupa por categoria inteira antes de somar vitórias — nunca fatia a mesma categoria (ex.: hortifruti) entre o vencedor e o segundo colocado — e capa em no máximo 2 mercados, realocando qualquer categoria fora do top 2 para o finalista que venceu mais dela, nunca para um terceiro mercado. `category_of=None` (o default, e o que `julius mercados comparar` da CLI continua recebendo) preserva o algoritmo antigo, sem restrição de mercados.

**1053 testes verdes** (`.venv/bin/pytest -q`; os 9 pulados são só a suíte `real_ai`), incluindo os que reproduzem os três screenshots com fixtures sintéticas — o desempate tomate/passata, a categoria hortifruti fatiada entre 2 lojas por engano, o corte de 3 mercados pra 2.

**Rodada real da v2.11** (19/09/2026, `make test-ia` contra cópia do banco de produção, depois da v2.12 já estar implementada): **9 testes, 16 chamadas, US$ 0,0173**, roteamento **6 de 6 (100%)**. Confirma ao vivo, com o modelo de verdade, os dois pontos que só tinham exemplo escrito à mão: a resposta de "qual mercado é mais barato pra tomate e cebola?" **abriu com a instrução** — *"Compra no Costa Atacadao pra cebola e tomate.\n\nCebola lá tá R$ 7,89 o quilo..."* — e o veredito ("2 de 2 itens mais baratos em Costa Atacadao") saiu certo, grounded, sem a guarda da v2.12 disparar uma vez sequer nas 16 chamadas. `check_price` (RF4) não foi exercitado nesta rodada — nenhum caso de `ROUTING_CASES` cobre "preço visto ao vivo" ainda; fica para a próxima medição real.

**v2.12 (o bot nunca mais afirma o que não checou, e o motivo da variação de rota) — `docs/design/agent-output-honesty.md`, 2026-09-19.** Nasceu de um incidente real: "qual mercado é mais barato pra tomate e cebola?" — a mesmíssima pergunta que tinha funcionado 68 minutos antes na mesma conversa — voltou *"Não consegui ver os resultados — as buscas voltaram vazias... o histórico de cupons ainda não foi importado (ou a importação falhou)"*. Medido, não suposto: o banco estava intacto (133 produtos, 169 preços, mais dado que antes), e `ai_calls.jsonl` prova que o modelo **não chamou ação nenhuma** (`raw_response: "text"`) — inventou o motivo. Duas causas, dois remédios: nenhuma guarda existia contra texto livre afirmar estado do sistema (a mesma assimetria que a guarda de dinheiro da persona já resolvia, nunca replicada pro agente), e `build_agent` nunca configurava `temperature` — o provedor caía no próprio default (tipicamente 1.0) pra uma decisão que é literalmente "multiple choice" entre 15 ações.

`bot/agent.py` ganha `ROUTING_TEMPERATURE = 0.0` (a própria documentação do `ModelSettings.temperature` do `pydantic_ai` recomenda 0.0 pra esse tipo de tarefa) e um `@agent.output_validator` (`no_unlicensed_data_claims`) que barra qualquer resposta em texto livre citando uma de nove frases tiradas literalmente do incidente real ("buscas voltaram vazias", "não foi importado", "banco de dados"...) — forçando `ModelRetry` com saída única (chamar a ação certa, sem a opção mais barata de só reformular sem as palavras banidas) até esgotar os 2 `retries` já configurados, caindo então em `UnexpectedModelBehavior`. **Achado de revisão que mudou o mecanismo**: a guarda por palavra/frase sozinha barraria uma resposta LEGÍTIMA — o próprio prompt manda relatar em texto uma recusa de `resolve_product`/`resolve_store` ("Nenhum produto chamado «X»"), e essa fala pode mencionar "banco de dados" à toa mesmo depois de uma ação real ter rodado. A guarda passou a checar `ctx.messages` primeiro: só dispara quando **nenhuma** `ToolCallPart` existe nesta rodada — uma ação já ter rodado (mesmo terminando em `ModelRetry`) torna a fala seguinte legítima por construção, guarda ou não.

`bot/turn.py::handle_text` ganha um `except UnexpectedModelBehavior` específico, antes do `except Exception` genérico — mensagem própria ("Não consegui confirmar isso com segurança...") em vez do `AI_UNREACHABLE` de sempre, que sugeriria falha de rede, causa errada pra esse caso. `_charge` também parou de gravar sempre a string fixa `"text"` pra saída em texto livre — grava o conteúdo real agora, fechando a lacuna que obrigou reconstruir o incidente a partir de uma captura de tela em vez do log (`ai_calls.jsonl` nunca guardava a fala fabricada). Achado colateral: a versão do `pydantic-ai` em produção (2.45.0) divergia da do `.venv` de dev (2.44.0) — `pyproject.toml` não fixava nenhuma; agora fixa `==2.45.0` nas duas listas de dependência opcional, e o `.venv` de dev foi alinhado antes de rodar a suíte.

**1061 testes verdes** (`.venv/bin/pytest -q`, suíte inteira rodando contra `pydantic-ai==2.45.0`, a mesma versão de produção), incluindo o experimento que reproduz o incidente (texto fabricado → retry → ação de verdade), o caso de esgotamento (`UnexpectedModelBehavior` capturado, nunca a frase chega ao usuário) e o caso que a revisão pegou (ação real rodou, guarda não interfere).

**Rodada real** (19/09/2026, `make test-ia`, `temperature=0.0` pela primeira vez contra o modelo de verdade): roteamento **6 de 6 (100%)**, `US$ 0,0173`, guarda nunca disparou — nenhuma das 16 chamadas produziu texto livre com qualquer frase de `_UNLICENSED_DATA_CLAIMS`. **Achado real que corrigiu o próprio teste, não o produto**: a primeira rodada (antes desta correção) mediu "4 de 6" e marcou como erradas *"Você quer comprar o quê?..."* e *"Bom dia! Tudo bem..."* — as duas respostas certas, com o roteamento certo; o teste comparava `raw_response == "text"` por igualdade, e essa comparação nunca mais podia ser verdadeira depois que `_charge` passou a logar o conteúdo real em vez da string fixa `"text"` (o próprio ganho desta rodada). `tests/test_real_ai.py::_is_free_text` substitui a comparação por "não é nenhum nome de saída de ação conhecido", e a segunda rodada, já corrigida, deu 100%. Lição registrada: um teste que lê o log de produção quebra quando o formato do log melhora — não é o único lugar onde isso pode voltar a acontecer.

**v2.13 (o veredito de preço ao vivo pesa quantidade, em reais — `docs/requirements/quantity-aware-verdict.md` → `docs/design/quantity-aware-verdict.md`, 2026-09-19).** Nasceu de um caso trazido pelo usuário, não de um screenshot: uma compra do mês de 14kg de carne com 14% de diferença é dinheiro de verdade (vale trocar de mercado); a mesma diferença numa compra de 1kg é R$5-10, que não paga o deslocamento. `check_price` (RF4/RF5 de v2.11) respondia sim/não só pelo corte fixo `LIVE_PRICE_TOLERANCE_PCT = 15%`, sem noção de quantidade nenhuma.

**Achado que decidiu o design inteiro, medido contra os 17 `kind` do catálogo real com preço em 2+ mercados**: o corte não pode ser percentual. `sacola reutilizável` (10% de diferença, R$0,02) e o exemplo do usuário, acém (~14%, R$5,00/kg), caem na mesma faixa percentual e pedem respostas opostas — a mesma faixa produz "óbvio que sim" e "depende da quantidade" ao mesmo tempo. `LIVE_PRICE_TOLERANCE_PCT` saiu de cena, substituído por três constantes em `services/comparison.py`: `WORTH_IT_THRESHOLD_REAIS = 15.0` (o valor em reais, não percentual, que decide se vale trocar de mercado) e `PLAUSIBLE_QTY_MIN/MAX = 0.2/20.0` (a faixa de quantidade plausível usada só para decidir, ANTES de perguntar, se a resposta já está definida nos dois extremos). `check_price(conn, kind, price, quantity=None)` decide em três ramos: gap trivial mesmo comprando muito → sim, sem perguntar; gap já grande mesmo comprando pouco → não, sem perguntar; meio-termo sem `quantity` → `reason="quantity_needed"`, veredito ainda indefinido mas com todos os outros fatos preenchidos; meio-termo com `quantity` → decide por `gap × quantity` contra o corte.

**Reversão intencional, registrada em vez de escondida**: o par de exemplos que calibrou o corte antigo (ovos, R$0,53 → R$0,75, ~42%, "bem mais caro") se inverte sob o novo modelo — R$0,22 de gap nunca vira dinheiro real, mesmo comprando bastante, e o gate agora diz "sim, pode levar". Não é regressão: RF5 dos requisitos desta rodada pede exatamente isso ("diferença pequena não muda a resposta, qualquer que seja o percentual"). `tests/test_services_comparison.py::test_check_price_small_absolute_gap_is_a_yes_even_at_high_percent` fixa a reversão com o motivo no docstring, para não reaparecer como bug num futuro code review.

**`reason="quantity_needed"` não podia apagar os fatos que a pergunta precisa.** Antes desta rodada, qualquer `reason` preenchido em `PriceCheck` fazia `render.py::price_check_facts`/`price_check_fallback_line` devolverem só uma frase genérica de "sem dado" — um `quantity_needed` cairia nesse buraco e perderia `reference_price`/`reference_store`/`reference_at`, impedindo a frase que o próprio usuário deu como exemplo ("você já conseguiu comprar por R$35, quantos kg vai comprar?"). As duas funções ganharam um ramo próprio para esse `reason`: fatos completos (preço informado, referência, diferença) mais uma linha "pergunte quantos [quilos/litros/unidades]..." em vez do veredito. `price_check_fallback_line` produz literalmente a frase do exemplo do usuário, sem IA nenhuma.

**Decisão mais cara da rodada, e a que foi rejeitada**: um `PendingQuestion` irmão de `PendingWrite` em `ChatState`, com contador de tentativas e TTL. Rejeitado pelo mesmo motivo que as duas rodadas anteriores que enfrentaram problema parecido (RF4/RF5 de v2.10, RF4 de v2.11) — medir o que o histórico de 3 turnos já resolve antes de construir estado novo. `check_price` (ação, `bot/actions.py`) ganhou só um parâmetro opcional `quantity: float | None`; o loop de pergunta-resposta é inteiramente disciplina de prompt (`bot/agent.py::SYSTEM_PROMPT`, `BOT_PROMPT_VERSION = "2"`): o modelo vê sua própria pergunta anterior no `HISTORY_TURNS = 3` e rechama `check_price` com a quantidade quando a pessoa responde; se a resposta não ajudar depois de perguntar de novo uma vez, o prompt manda assumir uma quantidade pequena (1) em vez de insistir. **Tensão registrada, não escondida**: isso é o modelo decidindo quando desistir de perguntar — um estreitamento deliberado do "a IA nunca decide sozinha se pergunta ou não" (RF5), do mesmo tipo já registrado para "categoria conhecida" na v2.3. Se o uso real no Telegram mostrar o modelo perguntando sem parar ou esquecendo a pergunta, esse é o gatilho pra finalmente construir o estado explícito que três rodadas diferentes já adiaram.

**A lista de compras (`compare_stores`) não ganhou pergunta de quantidade — ganhou economia estimada.** Perguntar quantidade item a item numa lista de 20 itens desfaria o formato de resposta que a v2.11 acabou de conquistar (abre com a decisão); uma única quantidade aplicada a todos os itens somaria kg de carne com unidade de refrigerante sob uma base sem sentido. Em vez disso, `bot/render.py::_estimated_savings` soma a diferença mais-barato-menos-mais-caro (`KindComparison.entries`, já ordenado, o mesmo dado que `comparison_facts` já usa) sobre os `kind` que o veredito venceu — um piso de economia, "comprando 1 de cada", sem perguntar nada e sem tocar `services/`. Reduz o que foi combinado no brainstorm ("os dois fluxos" ganhariam pergunta) — decisão de design, com o motivo medido, não descuido.

**1083 testes verdes** (1074 na suíte padrão + 9 da suíte `real_ai`), incluindo os que fixam a reversão do exemplo dos ovos, os três ramos do gate (trivial/extremo/meio-termo), o roteiro completo do exemplo do acém (1kg → sim, 14kg → não) e a preservação dos fatos em `quantity_needed`.

**Rodada real** (19/09/2026, `make test-ia`, mesma cópia do banco de produção): **roteamento 7 de 7 (100%)**, incluindo o primeiro caso real de `check_price` já exercitado contra o modelo de verdade (`tests/test_real_ai.py::ROUTING_CASES` — nunca tinha caso nenhum antes desta rodada, lacuna que o próprio design apontou como precondição). "Aqui o quilo do tomate tá 9,90, tá bom?" roteou certo. A economia estimada (Decisão 5) apareceu grounded na comparação real de tomate+cebola: *"Comprando 1 de cada, você guarda R$ 5,20 no bolso."* — número batendo exatamente com `_estimated_savings` (R$2,10 da cebola + R$3,10 do tomate). **US$ 0,02** na rodada inteira (17 chamadas).

**O que esta rodada não cobre**: o loop de pergunta-e-resposta de quantidade em duas mensagens (Decisão 4) — nenhum caso de `ROUTING_CASES` ainda simula "check_price pede quantidade, pessoa responde, check_price roda de novo com quantity" turno a turno; isso só se confirma testando de verdade pelo Telegram, ou com um caso novo de `real_ai` que force o meio-termo do gate. Se esse comportamento falhar lá, é o gatilho já escrito acima para reabrir o estado explícito de pergunta pendente.

**Regra de teste que a v2.7 tornou obrigatória:** `narrate()`/`_narrate` nunca são chamados via `asyncio.to_thread` a partir de código que compartilha a conexão SQLite do turno — só chamada direta, síncrona. Todo teste de narração usa `ScriptedLlmClient`/`RaisingLlmClient` (`tests/_fakes.py`), nunca a rede.

**Regra de teste que a v2.6 tornou obrigatória:** nenhum teste fala com um modelo de verdade — `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` é `autouse` no `conftest`, irmão do `_no_cnpj_lookup`, e o roteamento é sempre `FunctionModel`. Expiração é testada por `now` injetado, **nunca** por `time.sleep`. O turno inteiro (texto e toque) é exercitado sem `python-telegram-bot`: só `bot/app.py` sabe o que é um `Update`.

**A rodada real aconteceu em 18/09/2026 e as duas perguntas em aberto foram respondidas** (`tests/test_real_ai.py`, `make test-ia`; 13 chamadas, **US$ 0,011**). O `extra_body` **desliga o thinking**: `deepseek-flash` devolveu **42 tokens de saída** em 1393 ms, sem erro — a falha de 15/09 teria consumido os 600 de `max_tokens` e voltado truncada, então a folga é de mais de uma ordem de grandeza. O roteamento **acertou 5 de 5**, e o prompt v1 passou **sem ajuste**. O id inexistente virou pergunta (*"Não encontrei nenhum produto com o id 99999…"*), não escrita no produto errado. Custo por mensagem: **~US$ 0,00085**, dominado pela entrada (2451 tokens = prompt + schema das 14 ações) — mil mensagens custam menos de US$ 1. Detalhe em `docs/design/telegram-bot.md` §9.1.

**A suíte `real_ai`, e por que ela é assim.** `tests/test_real_ai.py` é o único arquivo que fala com o modelo de verdade; pula por padrão e roda com `--real-ai` (`make test-ia`). Três decisões que não são acidentais: (1) **opt-in por flag, não por `-m`** — medido: com `addopts = "-m 'not real_ai'"`, um `pytest -m real_ai` continua desselecionando o teste, e um harness que some em silêncio é pior que nenhum; o `pytest_collection_modifyitems` do `conftest` **pula com motivo visível**. (2) **Invariante × roteamento são coisas diferentes**: "escrita não grava sem o toque" é assert (não depende do modelo); "escolheu a ação certa" é **taxa agregada** com piso em `MIN_ROUTING_HITS = 0.7`, porque um teste que fica vermelho por flutuação ensina a ignorar a suíte. (3) **Sempre numa cópia do banco** — `JULIUS_DB` nunca é tocado, e as três fixtures `autouse` do `conftest` (`_clean_env`, `_no_model_requests`, `_no_cnpj_lookup`) saem do caminho **só** quando o marcador `real_ai` está presente.

**v2.1 (consultar em linguagem natural)** — tickets 115–116, sem IA nova nenhuma. `julius consultar` passou a reconhecer uma tag dentro do texto livre: `julius consultar hortifruti` e `julius consultar leite laticinio` funcionam sem `--tag` (interseção quando dá match, retry como termo puro quando a interseção fica vazia), com a mesma tolerância a erro de digitação (`rapidfuzz`) que o nome de produto já tinha — corte próprio (`TAG_MATCH_CUTOFF = 75`), medido contra as 13 tags semeadas, não reaproveitado dos cortes de nome de produto. `--tag` explícito continua funcionando exatamente como antes; `--sem-tag` desliga a detecção quando ela atrapalha. Toda chamada de `consultar` grava uma linha em `~/.local/share/julius/query_log.jsonl` (mesmo `infra/ai_log.py::append` que já gravava `ai_calls.jsonl`, reaproveitado sem mudança), pra recalibrar cortes com dado real de uso no futuro — sem comando de leitura ainda, é `jq`/`Counter` por conta do usuário, mesma lógica de não existir `julius ia status`. Contrato completo com a medição do corte em `docs/design/consultar-v2.1.md`.

Resolvido nesta fase (ver "Requisitos novos" para o texto original):
- `julius produtos pendentes` (item 2) → virou `julius produtos revisar`.
- Dica via padrão `C/<número>` (item 3) → coberta pela revisão assistida por IA (`enrich_products`), não só pela dica impressa.

Ainda em aberto (questões de gosto, não bugs):
- Empates de preço em `consultar`: todas as linhas com o menor/maior preço são mantidas mesmo fora de `--limite` (honesto, mas com 4 preços iguais a tabela cresce). Ajustar se incomodar.

**Próximo passo, e é um só: rodar o smoke do bot.** `docs/como-testar-o-bot.md` é o roteiro passo a passo (dono: o usuário). Ele é o que decide se a v2.6 está pronta ou não — os 908 testes passam com `FunctionModel`, e **nenhuma chamada real ao modelo jamais passou por este código**. As duas perguntas abertas são se o `deepseek-flash` escolhe ação de forma confiável com catorze opções e se o `extra_body` desliga o *thinking* pelo caminho do PydanticAI; o resultado vai para `docs/design/telegram-bot.md` §9.1. Enquanto isso não acontecer, nem o README nem este documento afirmam esse comportamento — e **nada de v3 (outros estados, foto/OCR) antes disso**.

**Pendente desde antes da v2.6, e continua valendo:** rodar `julius importar` (sem argumento, varre a pasta de entrada) para o backfill do endereço e `julius produtos revisar` para curar o catálogo acumulado. Estado medido em 18/09/2026: o banco real tem **105 produtos, 132 preços, 5 mercados**, `~/.local/share/julius/entrada/` tem `qrcode-2.html`, `qrcode-3.html` e `qrcode-4.html` esperando, e `entrada/importados/` está **vazia** — ou seja, o `importar` sem argumento nunca rodou. (`qrcode-5.html` saiu da pasta em algum momento; `qrcode-4.html` é o cupom com `Gf`/`PC`, reservado como fixture futuro de regressão do mapa de unidade.) **Atenção desde a v2.2:** o import continua idempotente *no banco*, mas não no sistema de arquivos — todo HTML importado com sucesso é **movido** para `entrada/importados/`. Reimportar um arquivo já arquivado é seguro (nada é apagado), mas se quiser manter o `qrcode-4.html` fora do fluxo, tire-o da pasta antes.

## Convenções de código (regra dura, veio de irritação real do usuário)

- **Identificadores em inglês, sempre**: módulos, classes, funções, variáveis, campos de dataclass, tabelas e colunas SQL, variáveis de ambiente. Sem exceção "porque o domínio é brasileiro".
- **Português só no que o usuário lê**: nomes dos comandos do CLI (`julius importar`, `julius mercados listar` — são UI), textos de `--help`, mensagens impressas, este documento. Um comando em português mapeia pra função em inglês via `@app.command("importar")` sobre `def import_receipts(...)`.
- As seções de design abaixo foram escritas antes dessa regra e ainda usam vocabulário em português em prosa e em alguns exemplos — **o código é a fonte da verdade dos nomes**; a tabela de mapeamento em "Estrutura de pacote" traduz cada termo antigo pro identificador real.
- Comentários: só quando o *porquê* não é óbvio (uma restrição escondida, um workaround). Nunca comentário narrando o que o código já diz.
- Todo módulo com lógica (um `if`, um loop, um parser, um `INSERT`) nasce com teste de caminho feliz **e** triste. Sem framework além de `pytest`; SQLite real em `tmp_path` em vez de mocks de banco; rede sempre mockada.

## Requisitos-chave (resumo)

- Entrada: arquivos HTML de consulta NFC-e já salvos localmente (ex.: `qrcode.html`). Sem busca ao vivo no site da Receita — a URL original passa por captcha (`/Nfce/Captcha?Chave=...`).
- Saída: base de dados única, uma linha por item comprado (não por nota). ~~CSV~~ **revisto no design (ver seção Design v1): virou SQLite como fonte da verdade, CSV como export.**
- Deduplicação: reimportar o mesmo arquivo não pode duplicar linhas.
- Consulta: buscar por nome de produto e listar histórico ordenado (data, valor, unidade, local), destacando menor/maior valor já pago. Sem "veredito" automático (barato/caro) no MVP — dado histórico curto por produto, qualquer cálculo estatístico seria ruído. O usuário decide olhando a lista.
- Local do mercado: guardar um apelido legível por CNPJ (mantido manualmente pelo usuário), não a razão social crua do HTML.
- Escopo de estados no MVP: **somente Receita/DF**. Cada estado tem layout de HTML de NFC-e diferente — a parte que interpreta o HTML de um estado deve ficar isolada atrás de um único ponto de entrada, para que suportar um segundo estado no futuro não exija tocar no resto do sistema. Sem generalizar/criar abstração para múltiplos estados agora — só isolar a parte que muda (é a única implementação até hoje).

## Fatos e pegadinhas do domínio (verificados nos exemplos reais)

- **Não existe XML acessível.** Nem salvo localmente, nem exposto nesta tela da Receita/DF (só tem visualização HTML e impressão de PDF). O HTML já é suficiente — carrega todos os campos necessários.
- **Duas unidades de venda no mesmo recibo: `UN1` e `KG1`.** Nunca comparar ou fazer média entre preços de bases diferentes (ex.: R$/un vs R$/kg). Guardar a unidade original junto de cada preço.
- **Separador decimal misturado na mesma linha do HTML.** Quantidade vem com ponto (`1.0000`), valores em reais vêm com vírgula (`6,99`). Normalizar ao extrair, não assumir um padrão só.
- **Duas datas no documento — não confundir.** `Emissão: 12/09/2026 13:09:16` é a data da compra. `Data/Hora da Consulta` é quando a página foi acessada (irrelevante para o histórico de preços).
- **Mesmo código de produto pode repetir como linhas separadas na mesma nota** (ex.: código 14578 aparece 3x). Chave de deduplicação correta é `(chave de acesso, índice da linha)`, nunca a chave de acesso sozinha.
- **O HTML salvo tem DOM injetado por extensão de navegador** (`plasmo-csui`, fora da estrutura da nota fiscal). O parser deve ancorar na estrutura real da nota (`li.list-group-item` dentro dos `div.card.accordion`), não em heurísticas de "documento inteiro".
- **HTML só tem razão social** (ex.: "FL 3 COSTA MULTICANAL S A"), não o nome fantasia que a pessoa reconhece (ex.: "FL 3 COSTA ATACADAO", visível só no PDF). Resolver com um mapa CNPJ → apelido mantido pelo usuário, não extraindo do PDF.
- **Descrições de produto são maiúsculas, sem acento e abreviadas** (`LING FGO RESF AURORA kg`, `REFRI ANT GUARANA PET 1.5L`). Busca deve ser por trecho, sem distinguir maiúsculas/acentos — mas abreviações são uma limitação conhecida (buscar "linguiça" por extenso não acha "LING").
- **Código de unidade é um vocabulário aberto por rede, não duas strings fixas.** Confirmado em 5 notas de 5 mercados: `UN1`/`KG1` (FL 3 Costa), `UN`/`KG` (Comercial HTP, Dona de Casa) e, na maior rede do lote (Sendas/Assaí), `Un`/`Kg`/`PC`/`Gf` — **case misto e dois tokens novos** (`PC` = pacote, `Gf` = garrafa). Prova concreta: `AC MASC F TER ES 1kg` — o **nome** do produto diz "1kg", mas ele é vendido por `PC` (pacote inteiro, R$14,85 o pacote, não R$14,85/kg). **Resolvido no design final (ver "Contrato do parser"): a `CHECK (unidade IN ('UN','KG'))` sempre esteve certa — o que precisava mudar era só a extração, que virou um mapa curado em vez de "tirar as letras iniciais".**
- **Quantidade tem precisão decimal variável** (`1.0000`, `0.8800`, mas também `1.532` com 3 casas). Nunca assumir 4 casas fixas, só parsear como decimal genérico.
- **A página renderiza a nota completa mesmo quando a própria Receita sinaliza problema no QR.** Uma das notas de exemplo foi salva a partir de uma URL com `Codigo=100&Mensagem=QR Code Inválido&Descricao=Hash QR Code inválido` — mesmo assim o HTML veio com todos os itens, valores e a chave de acesso, e essa chave bate com a da URL. Esse sinal só existe no comentário `<!-- saved from url=... -->` que o navegador insere ao salvar a página (não é garantido em todo save futuro) — **não construir validação em cima disso**, é só uma observação registrada.
- **"Consumidor" às vezes traz CPF, às vezes "não identificado".** Não usado pelo schema e não deve ser guardado — é PII sem papel na lembrança de preço, o objetivo do sistema.
- **Confirmação real do caso que `produtos fundir` existe para resolver**: `TOMATE ITALIANO kg` (Cód 7147, mercado "Dona de Casa") e `TOMATE ITALIANO UNIAO kg` (Cód 22039, mercado "FL 3 Costa") são potencialmente o mesmo tipo de produto em mercados diferentes — mas com marca (`UNIAO`) diferente, exatamente o tipo de caso onde uma sugestão automática por similaridade de texto erraria (ver seção "Identidade de produto e busca"). Fusão continua manual, a critério do usuário.
- **Código de produto confirmado como não-global** (prova real, não hipótese): código `4134` é `DESENGORD UAU 500ML GATILHO` (desengordurante) no mercado "Dona de Casa" e `BROCOLE NINJA` (brócolis) no mercado "Sendas/Assaí" — mesmo número, produtos sem nenhuma relação. Confirma que a chave `(cnpj, produto_codigo)` é obrigatória; `produto_codigo` sozinho não significa nada entre mercados.
- **Filiais da mesma rede são CNPJs diferentes, e isso é o comportamento certo.** "Dona de Casa" aparece com `11.832.478/0002-85` (Guará) numa nota e `11.832.478/0003-66` (Candangolândia) noutra — endereços diferentes, preços podem diferir. Tratar como dois `mercados` distintos (já é o que o schema faz por chavear em `cnpj` completo) está correto; ao definir apelido, vale incluir um hint de local (ex. "Dona de Casa — Candangolândia") pra diferenciar filiais da mesma marca. **Confirmado em v2** com o endereço de verdade extraído do cupom: `11832478000285` → `QUADRA QE 30, 02/39, LJS 02/39, GUARA II, BRASILIA, DF`; `11832478000366` → `QUADRA QR 5, 05 MU 05, , CANDANGOLANDIA, BRASILIA, DF`. A identidade de rede (pra agrupar filiais na dica `SAME_CHAIN_BRANCHES`) é `cnpj[:8]` — os 8 primeiros dígitos (raiz do CNPJ) são iguais entre as duas, só o sufixo de filial muda.
- **Descrições ficam mais crípticas ainda em redes maiores.** Na nota do Sendas/Assaí (47 itens, a maior do lote): `AC MASC F TER ES 1kg`, `SBT GUAPAS 1L MACA V`, `QJ T PARM PIRAC PD` — abreviação mais agressiva que nas notas menores. Reforça (não muda) a decisão já tomada de não tentar NLP/classificação automática em cima da descrição — mas em v2 isso deixou de ser um beco sem saída: `enrich_products` (IA) expande essas abreviações para nome legível, com `renomear` como desfazer caso erre.
- **`deepseek-flash` raciocina por padrão e não converge no prompt de enriquecimento** (achado do smoke test antes do primeiro ticket de v2, `claudedocs/handoff_smoke_test_deepseek_20260915.md`). Com `thinking` ligado (o padrão do modelo), ele gasta todo o `max_tokens` "pensando" — testado com 1200, 3000 e 8000 tokens, sempre `finish_reason: length` e `content` vazio, nunca converge. Com `"thinking": {"type": "disabled"}` no corpo do request, responde em ~2s com JSON correto. Por isso `JULIUS_AI_REQUEST_EXTRAS` existe (ver "Camada opcional de IA") e o cliente trata `finish_reason != "stop"` como erro cobrado (pagou tokens, não veio resposta usável).

## Requisitos novos para o sistema evoluir com segurança

Pergunta direta do usuário: "o que precisa ser feito para que o sistema consiga evoluir". A resposta mais forte não veio de nenhuma feature nova — veio de olhar pra trás nesta própria conversa.

**1. Migração de schema — IMPLEMENTADO.** O schema deste projeto já mudou **quatro vezes** só nas sessões de design anteriores (CSV → SQLite; +`products`/`product_skus`/`tags`; +`content_quantity`/`content_unit`; +mapa de unidade). O banco vai guardar anos de recibos reais — não podia ficar sem mecanismo formal pra "mudar o schema não pode apagar dado". Ver seção "Migração de schema" no Design (v1): `PRAGMA user_version` + `julius/infra/db.py` lendo `julius/infra/migrations/*.sql`, backup automático do arquivo antes de qualquer migração real, sem framework tipo Alembic (desproporcional pra banco de um usuário só). Coberto por `tests/test_db.py`.

**2. Revisão periódica de produtos pendentes — RESOLVIDO em v2, corrigido na v2.3.** Uma única nota do Sendas/Assaí trouxe 39 produtos novos de uma vez (nenhum com tag, nenhum com conteúdo definido). A pergunta original ("vale um comando tipo `julius produtos pendentes`?") virou `julius produtos revisar`. A v2 listava `products.untagged_product_ids` — e por isso um produto saía da fila para sempre assim que ganhava uma tag, mesmo sem tipo nem conteúdo (4 pendentes num catálogo com 49 buracos). Desde a v2.3 a fila é `products.incomplete_product_ids`, por campo faltando.

**3. Dica (não automática) de conteúdo a partir do padrão `C/<número>` — RESOLVIDO em v2, coberto pela revisão.** Achado original: `OVO BCO GRANDE C/30` e `CHA LEAO RELAXA CX 16G C/10UN` usam `C/<dígito>` pra dizer "contém N unidades" — e em nenhuma das 5 notas isso colide com os outros usos de `C/` (`C/GAS`, `C/G`, `C/SAL`, sempre `C/` + letra). A dica impressa `PACKAGE_SIZE_IN_DESCRIPTION` (v1.1) continua existindo para quem não usa IA; com IA configurada, `enrich_products` já propõe o `content` durante `produtos revisar`/`importar`, sempre com confirmação humana antes de gravar (nunca automático).

## Evolução futura (não construir agora, sem prazo)

O usuário pode um dia querer mandar uma foto do recibo, ou do QR Code, inclusive via um bot do Telegram, para acionar o processo inteiro automaticamente. Três coisas distintas escondidas nessa ideia — não tratar como uma feature só:

- **Canal de entrega** (Telegram, etc.): é só transporte. Não muda nada do parsing/armazenamento.
- **Foto do QR Code**: decodificar dá a chave de acesso + a URL — mas é a mesma URL com captcha que já descartamos para busca automática (ver seção de pegadinhas). Ou seja, decodificar o QR **não** resolve sozinho o problema de obter o dado; só automatiza "qual URL", não "como pegar o conteúdo".
- **Foto do recibo impresso (OCR)**: pipeline totalmente diferente do parsing de HTML estruturado — texto não estruturado, sujeito a erro de leitura. Não é a mesma coisa que ler o QR.

Constraint de design a preservar: manter "como o dado chegou" (hoje: caminho de um HTML salvo) separado de "interpretar e guardar" — mesma disciplina aplicada ao parser por estado. Não construir abstração para os outros canais agora; só não acoplar a única forma de entrada atual ao resto do sistema.

## Decisões (defaults assumidos, sem objeção do usuário)

1. **Import em lote**: ~~não no MVP~~ **resolvido de graça**: `julius importar` aceita múltiplos arquivos (argumento variádico do Typer), então "vários arquivos de uma vez" já funciona sem código extra — não é mais uma feature em aberto.
2. **Correção de erro**: duas situações diferentes, tratadas diferente:
   - **Apelido de mercado errado/feio**: tem comando dedicado, `julius mercados renomear` — é a correção que se repete toda vez que aparece um mercado novo, vale o código.
   - **Linha de preço errada** (valor digitado errado, item duplicado por engano, etc.): sem comando dedicado, usa `sqlite3 prices.db` direto no terminal (`UPDATE`/`DELETE`) — já vem com o Python/SO, não é ferramenta nova.

Requisitos considerados fechados.

## Design (v1)

### Stack

Python 3. Extração do HTML: **regex/string matching sobre marcadores fixos do template** (`re`, stdlib), não um parser de DOM — o template da Receita/DF é rígido e não-adversarial (recibo próprio salvo, não HTML de terceiro hostil). Troca: se a Receita mudar o layout da página, quebra silenciosamente; aceitável pra ferramenta pessoal. Se no futuro isso incomodar, trocar por BeautifulSoup (menos código, uma dependência nova) é a evolução natural.

CLI: **Typer** (não `argparse`) — decisão explícita do usuário: priorizar framework pronto sobre stdlib pra minimizar código escrito, mesmo custando uma dependência nova. Typer dá subcomandos, `--help` formatado, validação de tipo e mensagens de erro só com type hints em funções Python — zero parsing manual de argv. Junto vem `rich`, usado só pra formatar tabela de saída (`consultar`, `mercados listar`, `produtos listar`).

Busca/identidade de produto: **`rapidfuzz`** (biblioteca pronta e leve de similaridade de string) — ver seção "Identidade de produto e busca" abaixo.

### Contrato do parser (a costura entre "estado" e o resto do sistema)

Contrato: `julius/parsers/__init__.py` → `class ReceiptParser(Protocol): def parse(self, html: str, source: str = "") -> Receipt`. `source` é só o nome do arquivo pra aparecer em mensagens de erro (`UnknownUnitError`), não é dado extraído.
Saída: um `Receipt` (`julius/domain/models.py`) — cabeçalho da nota + tupla de `ReceiptItem`, um por linha, já **normalizados dentro do parser** (unidade via `UNIT_MAP`, decimais via `parse_decimal_br`, CNPJ/chave via `digits_only` — tudo em `julius/domain/normalization.py`; a camada de armazenamento nunca vê texto bruto):

| campo | tipo | observação |
|---|---|---|
| `Receipt.issued_at` | ISO 8601 (`YYYY-MM-DDTHH:MM:SS`) | de "Emissão", nunca de "Data/Hora da Consulta" |
| `Receipt.store_cnpj` | string, 14 dígitos | só números |
| `Receipt.store_legal_name` | string | como está no HTML |
| `Receipt.access_key` | string, 44 dígitos | |
| `ReceiptItem.index` | inteiro, 1-based | posição do item na nota, na ordem do HTML |
| `ReceiptItem.product_code` | string | |
| `ReceiptItem.description` | string | maiúsculo/sem acento, como está no HTML |
| `ReceiptItem.quantity` | float | vírgula/ponto já normalizados |
| `ReceiptItem.unit` | `"UN"` ou `"KG"` | traduzido do código bruto por **mapa curado** (`UNIT_MAP`), não por extração de prefixo |
| `ReceiptItem.unit_price` | float | |
| `ReceiptItem.total_price` | float | |

v1: uma única implementação desse contrato, pro HTML da Receita/DF. **O item é identificado pelo marcador de conteúdo `(Cód: N)` junto dos rótulos `Qtde.:`/`UN:`/`Vl. Unit.:`, não pela posição do `<ul>`** — confirmado em 3 notas reais que os blocos de totais/pagamento/tributos também são `li.list-group-item` dentro do mesmo `#collapse1`, mas nenhum deles tem `(Cód:`; usar isso como âncora é mais robusto do que assumir "primeiro `<ul>`". Ignora qualquer coisa sem esse marcador (inclusive DOM injetado por extensão de navegador, tipo `plasmo-csui`). Sem registro/detecção de estado, sem `--estado` — só existe DF.

**Mapa de unidade (implementado).** A `CHECK (unit IN ('UN', 'KG'))` do schema sempre esteve certa; o que estava errado era a prosa descrevendo *como* chegar lá ("extrair letras iniciais" quebra em `PC`/`Gf`, que já são só letras e não significam o óbvio). Solução: `UNIT_MAP` em `julius/domain/normalization.py` — é regra de domínio, o parser só a consome via `normalize_sale_unit(raw, description=..., source=...)` — com exatamente os códigos brutos já observados em nota real, nada especulativo: `UN1`, `UN`, `PC`, `GF` → `UN`; `KG1`, `KG` → `KG`.

Lookup: maiusculizar o código bruto, buscar no dicionário (`Un`→`UN`, `Kg`→`KG`, `Gf`→`GF`→`UN` cobertos sem entrada duplicada por case). Código fora do mapa → `UnknownUnitError` citando o código bruto, a descrição do produto e o arquivo — nada é gravado (mesma disciplina de "parseia tudo antes de escrever"), e o humano estende o dicionário em uma linha quando isso acontecer. Mesma filosofia já usada pra decidir não gastar chamada de IA nisso (seção "Camada opcional de IA"): é evento raro, curadoria manual resolve. `UND` (que aparece em `SACOLA REUTILIZAVEL UND`) não entra no mapa — é texto da descrição, o campo de unidade real dessa nota é `UN`.

### Armazenamento: SQLite (`prices.db`), CSV é só export

**Por que não CSV como fonte da verdade** (revisado nesta sessão de design, a pedido do usuário): `sqlite3` é stdlib do Python — nunca foi "stdlib vs. dependência nova", as duas opções são stdlib. E o que `consultar` precisa (join com apelido, agrupar por unidade, ordenar por data, achar min/max por grupo) é literalmente uma query SQL — em CSV isso é join/group-by/sort escritos à mão em Python. Menos código com SQLite, não mais. De brinde: `FOREIGN KEY` e `UNIQUE`/`PRIMARY KEY` transformam regras que eram "disciplina do app" (nunca gravar um preço de mercado desconhecido; nunca duplicar item) em **restrições do banco** — que é exatamente a robustez que motivou a pergunta.

Schema v1 real está em `julius/infra/migrations/0001_initial_schema.sql` (fonte da verdade; o bloco abaixo é cópia pra leitura):

```sql
CREATE TABLE stores (
    cnpj       TEXT PRIMARY KEY,
    legal_name TEXT NOT NULL,
    nickname   TEXT NOT NULL
);

CREATE TABLE products (
    id               INTEGER PRIMARY KEY,
    canonical_name   TEXT NOT NULL,
    content_quantity REAL,                -- NULL até o usuário definir manualmente
    content_unit     TEXT CHECK (content_unit IN ('L', 'KG', 'UN'))
);

CREATE TABLE product_skus (
    store_cnpj   TEXT NOT NULL REFERENCES stores(cnpj),
    product_code TEXT NOT NULL,
    product_id   INTEGER NOT NULL REFERENCES products(id),
    PRIMARY KEY (store_cnpj, product_code)
);

CREATE TABLE tags (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE product_tags (
    product_id INTEGER NOT NULL REFERENCES products(id),
    tag_id     INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (product_id, tag_id)
);

CREATE TABLE prices (
    access_key   TEXT NOT NULL,
    item_index   INTEGER NOT NULL,
    purchased_at TEXT NOT NULL,          -- ISO 8601, from the receipt's "Emissão"
    store_cnpj   TEXT NOT NULL REFERENCES stores(cnpj),
    product_id   INTEGER NOT NULL REFERENCES products(id),
    product_code TEXT NOT NULL,          -- raw value from that receipt; joins go through product_id
    description  TEXT NOT NULL,          -- raw value from that receipt
    quantity     REAL NOT NULL,
    unit         TEXT NOT NULL CHECK (unit IN ('UN', 'KG')),
    unit_price   REAL NOT NULL,
    total_price  REAL NOT NULL,
    PRIMARY KEY (access_key, item_index)
);

CREATE TABLE ai_usage (
    month     TEXT PRIMARY KEY,          -- 'YYYY-MM'
    spent_usd REAL NOT NULL DEFAULT 0
);
```

**Migração 0002 (v2)** — `julius/infra/migrations/0002_store_address_and_seed_tags.sql`, primeira migração real do projeto (rodou contra o banco com dados de verdade, com backup `.bak-v1` automático):

```sql
-- Address as printed on the receipt header; NULL until a receipt of that store is (re)imported.
ALTER TABLE stores ADD COLUMN address TEXT;

-- Aisle categories the AI is asked to prefer. Users add more with `julius produtos tag`.
INSERT OR IGNORE INTO tags (name) VALUES
    ('hortifruti'), ('carnes'), ('frios'), ('laticinios'), ('padaria'), ('mercearia'),
    ('bebidas'), ('limpeza'), ('higiene'), ('congelados'), ('temperos'), ('doces'), ('utilidades');
```

**Migração 0003 (v2.2)** — `julius/infra/migrations/0003_product_kind.sql`, o grupo de comparação:

```sql
-- Comparison group: "what kind of thing is this", so prices of the same kind can be compared
-- across stores. One column, not a table: a product belongs to at most one group, and a single
-- column makes that the database's rule instead of the application's.
ALTER TABLE products ADD COLUMN kind TEXT;
```

Sem índice (catálogo de centenas de linhas) e sem `CHECK` — não-vazio é garantido na escrita, como já é feito para `tags.name`. Rodou contra o banco real (105 produtos, 132 preços) com backup `.bak-v2` automático.

**Migração 0004 (v2.4)** — `julius/infra/migrations/0004_product_merge.sql`, a fusão reversível:

```sql
ALTER TABLE products ADD COLUMN merged_into INTEGER REFERENCES products(id);

CREATE VIEW product_group AS
WITH RECURSIVE walk(product_id, current_id) AS (
    SELECT id, id FROM products
    UNION ALL
    SELECT w.product_id, p.merged_into FROM walk w JOIN products p ON p.id = w.current_id
     WHERE p.merged_into IS NOT NULL
)
SELECT w.product_id, w.current_id AS root_id
  FROM walk w JOIN products p ON p.id = w.current_id
 WHERE p.merged_into IS NULL;
```

`merged_into` guarda o **alvo direto**, não a raiz: é isso que faz desfundir um nível do meio devolver a folha ao pai antigo em vez de deixá-la na raiz. A view dá uma linha por produto (produto não fundido é raiz de si mesmo), então toda leitura pode dar `JOIN` nela sem caso especial; resolver 105 produtos custa 21 ms e um produto 0,34 ms.

**Um ciclo (`A→B` e `B→A`) faz a recursão nunca retornar** — medido: a consulta não volta e todo comando que lê produto para de responder, sem mensagem de erro. Nenhum `CHECK` de coluna vê ciclo de dois passos, então a guarda é na escrita (`catalog.merge_products` recusa alvo que já pertence ao grupo da origem) e tem teste próprio. Um teste que crie ciclo trava a suíte inteira.

`stores.address` guarda o endereço impresso no cabeçalho da nota, exatamente como está (sem normalizar caixa/vírgulas — é texto de exibição). As 13 tags semeadas são o vocabulário que a IA prefere ao sugerir categoria em `enrich_products`; o usuário estende com `julius produtos tag` normalmente, sem comando especial.

A `PRIMARY KEY (access_key, item_index)` já É a regra de deduplicação — `INSERT OR IGNORE` faz o import idempotente sem precisar escanear nada antes. `nickname` nasce igual a `legal_name` quando um CNPJ novo aparece (`INSERT OR IGNORE INTO stores`, que nunca sobrescreve um apelido já editado à mão). `PRAGMA foreign_keys = ON` é ligado em toda conexão por `infra.db.connect()` — sem isso o SQLite ignora as FKs silenciosamente (testado em `tests/test_db.py`).

**Correção de erro** (decisão mudou aqui, ver seção Decisões): `sqlite3 ~/.local/share/julius/prices.db` no terminal e um `UPDATE`/`DELETE` — mesmo espírito de "editar direto", só que em SQL em vez de num editor de texto.

### Migração de schema (fecha o requisito "o sistema tem que poder evoluir sem perder dado")

**Por que isso é infraestrutura nova, não um replay do histórico desta conversa.** O schema "mudou 4 vezes" só neste documento de design — nunca existiu um banco real rodando com uma versão antiga dele. Não há dado legado pra migrar. Então a versão 1 de verdade (a que `/sc:implement` vai gerar) já nasce com o schema completo acima (`mercados`, `produtos`, `produto_skus`, `tags`, `produto_tags`, `precos`, `ia_uso`) — o mecanismo abaixo é andaime pronto pra a **próxima** mudança real, não uma reconstrução das anteriores.

**Mecanismo**: `PRAGMA user_version` do próprio SQLite (inteiro embutido no arquivo do banco, sem tabela extra) guarda a versão aplicada.

**Migrações são arquivos `.sql`, não um dict em Python** (a pedido do usuário — nenhuma DDL fica embutida em string dentro de código). Isso exige `[tool.setuptools.package-data] "julius.infra.migrations" = ["*.sql"]` no `pyproject.toml`; sem isso um `pip install` não-editável deixaria os `.sql` de fora e o app abriria um banco com zero tabelas (bug real pego na primeira validação).

```
julius/infra/migrations/0001_initial_schema.sql   # DDL completo, v1
julius/infra/db.py
  connect(db_path: Path) -> sqlite3.Connection       # mkdir do pai, row_factory=Row, foreign_keys=ON, apply_migrations
  available_migrations(directory=MIGRATIONS_DIR) -> list[tuple[int, Path]]   # ordenado pelo prefixo numérico
  schema_version(conn) -> int                          # PRAGMA user_version
  apply_migrations(conn, db_path, migrations=None) -> None
```

A versão "atual" não é uma constante mantida à mão — `available_migrations` lista os `.sql` da pasta, lê o número do prefixo (`0001_`, `0002_`...) e o maior é a versão-alvo. Adicionar uma migração é só soltar `000N_description.sql` na pasta.

`apply_migrations` roda **dentro de `connect()`**, que a CLI chama no primeiro comando que precisa de banco — **nunca em tempo de import** (`tests/test_cli.py` garante que `import julius.cli` não toca em disco). Sem comando `julius migrate` pra usuário lembrar:
1. Banco não existe ainda (primeiro uso) → `user_version` começa em 0, todos os `.sql` rodam em sequência, sem backup (não há nada de valor num arquivo que acabou de ser criado).
2. Banco existe e `user_version == maior versão disponível` → não faz nada (ler o `PRAGMA` é instantâneo).
3. Banco existe e `user_version` menor → **copia o arquivo pra `prices.db.bak-v<versão_antiga>` primeiro** (nome determinístico; nada apaga backups antigos sozinho), roda os `.sql` pendentes em ordem, atualiza `user_version` após cada um.

O backup só acontece no caso 3 — nunca em toda abertura normal do banco, que é o que mantém isso barato. Nota honesta: `executescript` faz `COMMIT` implícito, então "todas as pendentes numa transação só" não é garantido pelo SQLite — a rede de segurança real é o backup, não a atomicidade. Mudanças que o `ALTER TABLE` do SQLite não faz direto (remover coluna em versões antigas, mudar tipo/constraint) seguem a receita padrão do próprio SQLite (criar tabela nova, copiar dado, apagar a antiga, renomear) dentro da migração numerada — não é um caso novo a inventar, é documentado pelo próprio SQLite.

### Identidade de produto e busca

Problema real: a mesma coisa aparece com descrições diferentes em mercados diferentes (às vezes até no mesmo mercado, se o texto mudar), e a busca por texto precisa aceitar termo parcial e erro de digitação. Duas necessidades distintas, duas soluções distintas — não dá pra resolver as duas com a mesma ferramenta:

**1. "É o mesmo produto, mesmo com nome diferente" → resolvido sob demanda, nunca no import.**
Toda combinação nova de `(cnpj, produto_codigo)` cria automaticamente uma linha em `produtos` (nome inicial = a própria `produto_descricao`) — o import continua 100% não-interativo, sem perguntar nada. Recomprar o mesmo item no mesmo mercado sempre reaproveita o `produto_id` já existente (é o que faz o histórico de preço por produto funcionar sem esforço). Quando o usuário perceber, olhando os resultados de `consultar`, que dois produtos são a mesma coisa (comprada em mercados diferentes, ou com descrição que mudou), ele funde manualmente com `julius produtos fundir ORIGEM DESTINO` — reatribui `produto_skus` e `precos` do id de origem pro destino, numa transação só, e apaga a linha vazia.

**Comparar entre lojas sem fundir: `products.kind` (v2.2).** Fundir dois produtos junta o histórico para sempre; agrupar não. `products.kind` é o grupo de comparação — "que tipo de coisa isso é" (`tomate`, `leite uht`, `refrigerante`), um por produto, coluna anulável em vez de tabela ou tag (um produto pertence a no máximo um grupo, e coluna faz disso regra do banco; reaproveitar `tags` também invalidaria a medição de `TAG_MATCH_CUTOFF` da v2.1, calibrada só contra as 13 tags de corredor). A IA propõe o tipo em `produtos revisar`/`importar` e ele é gravado automaticamente; `julius produtos tipo ID [--remover]` corrige. Quem consome: `mercados comparar` e o sinal de extremos do `importar` — `search_prices` **não** mudou, a seleção continua por `rapidfuzz` sobre `canonical_name` e por `--tag`.

**O grupo de fusão (v2.4) — como ele conta com o grupo de comparação sem se confundir.** `products.kind` agrupa **alternativas de compra** (dois tomates de marcas diferentes competem entre si); `products.merged_into` diz que dois registros **são a mesma coisa**. São critérios opostos, e é por isso que tipo igual foi medido e **reprovado** como filtro de fusão. Depois de fundir:

- os atributos do grupo são **derivados na leitura**, não gravados: nome (prefere o que não é a descrição crua do cupom), conteúdo e tipo (o da raiz, caindo para o do absorvido quando a raiz não tem) e tags (união). Nada é copiado, e é isso que faz `desfundir` reverter a herança sem código de reversão;
- o absorvido desaparece de `produtos listar` mas continua no banco, com seus próprios valores intactos;
- escrever num produto absorvido é possível e inofensivo — o valor fica inerte e volta a valer se ele for desfundido;
- `has_raw_name` passa a olhar o grupo: um nome editado à mão em **qualquer** membro impede a IA de renomear, porque é esse o nome que o grupo mostra;
- o `exportar` leva as duas verdades: `product_id`/`canonical_name` do produto da compra e `group_product_id` da raiz.

Consequência aceita e medida: fundir pode fazer o grupo **ganhar** conteúdo (herança), e a notificação diz de onde veio — o caso `Alho` (sem conteúdo) ≈ `Pão de Alho 400g` herdaria "alho a granel, 400 g" em silêncio, e conteúdo errado é o único erro que não aparece na saída normal.

Fragmentação por grafia (`tomate`/`Tomate`/`TOMATE`) é resolvida em `products.set_kind`, que minúsculo o valor e reaproveita a grafia já existente quando `normalize_text` coincide (então `açaí` não vira `acai`). Singular/plural fica de fora de propósito: seria um terceiro corte fuzzy a medir sem evidência de que o problema existe. Detecção quando existir, sem código novo: `SELECT kind, count(*) FROM products WHERE kind IS NOT NULL GROUP BY kind ORDER BY kind` — dois tipos vizinhos na ordem alfabética com contagens pequenas é a assinatura; um `UPDATE` resolve.

**Fusão automática foi rejeitada em v2.2 por medição e reaberta em v2.4 pela mesma medição, refeita.** Não foi mudança de opinião — foi o catálogo que mudou.

| | v2.2 (catálogo cru) | v2.4 (catálogo curado pela v2.3) |
|---|---|---|
| Candidatos acima do corte | 19 | 19 (15 depois do guarda de conteúdo) |
| Confirmados pela IA | a maioria; **no máximo 2 defensáveis**, precisão ~5% | **2**, ambos corretos |
| `Alho` ↔ `Pão de Alho` | confirmado com **confiança 1,00** | **rejeitado** |

O que mudou entre as duas medições foram os nomes legíveis e os tipos que a v2.3 aplicou. A rodada real de primeira curadoria (17/09, banco reprocessado com 108 produtos) fez **4 fusões automáticas e as 4 estão corretas** — e **três delas são exatamente as fusões que o usuário já havia feito à mão** (Tomate italiano, Cebola, Sacola reutilizável): o sistema reproduziu sozinho o julgamento humano registrado. Nenhum falso positivo.

**Dois filtros foram medidos e reprovados no caminho; não repropor sem dado novo.**
- **Corte de confiança**: os dois acertos vieram com **0,70 e 0,80** e o falso positivo histórico com **1,00**. Um corte em 0,85 — que soa conservador — mataria os dois acertos e aprovaria o erro. Quarta falha de auto-relato de confiança neste projeto.
- **Mesmo `kind` como filtro**: 12 dos 19 candidatos têm tipo igual, e entre eles estão `Água com gás ≈ Água sem gás` (0,92), `Pepsi ≈ Guaraná` (0,78), `Aveia fino ≈ regular` (0,87) e três `Dry Rub` de sabores diferentes. A razão é estrutural: `kind` agrupa **alternativas de compra**, o oposto do critério de fusão. Isso fecha a pendência antiga sobre estreitar `duplicate_candidates` por tipo — incomodaria.

**O filtro que funcionou é o conteúdo declarado.** Par com conteúdo diferente nos dois lados deixa de ser candidato: dos 19, **4 divergem e os 4 são falsos positivos** (`Água 500ml ≈ Água 1,5L`, `Pepsi 2L ≈ Guaraná 1,5L`, `Água s/gás ≈ c/gás 1,5L`, `Pão Zinho 300g ≈ Pão de queijo 800g`). Unidade diferente conta como divergência — são dimensões que o sistema nunca compara. O conteúdo que a v2.3 coletou virou, sem código novo, o guarda da fusão que a v2.4 automatizou.

**E a segunda condição que faltava foi construída: fundir deixou de ser destrutivo.** `merge_products` não apaga nem move nada — grava `products.merged_into` e a leitura resolve o grupo pela view `product_group` (migração 0004). `julius produtos desfundir ID` remove a relação e o estado anterior volta **por construção**, porque nada foi copiado. Ver "Armazenamento" para o schema e "Identidade de produto e busca — o grupo de fusão" abaixo.

**Rejeitado explicitamente: sugestão automática de fusão via similaridade de string.** `rapidfuzz` compara strings, não produtos — ele vai dar nota alta tanto pra `PICANHA BOV FAT kg PROMO` ≈ `PICANHA BOV FAT kg` (provavelmente o mesmo item, ok) quanto pra `SUCO ... 1.5L UVA` ≈ `SUCO ... 1.5L LARANJA` ou `REFRI PEPSI PET 2L` ≈ `REFRI PEPSI PET 1L` (produtos diferentes, sabor/tamanho mudam e são exatamente o que importa pro preço). Uma sugestão que erra sabor e tamanho ensina o usuário a ignorá-la. **Isso continua valendo em v2.4**: o que funde é o veredito da IA sobre um par que o texto apenas *propôs*, nunca a similaridade de texto sozinha — `Alho` ↔ `Pão de Alho` pontua 1,00 em texto puro e é rejeitado pela IA.

**Isso não contradiz o `produtos comparar` assistido por IA da seção "Camada opcional de IA" abaixo** — a diferença é *quando* a sugestão aparece. O que foi rejeitado aqui é sugestão **automática e não pedida**, embutida em todo `consultar` (ensinaria o usuário a ignorá-la, e custaria uma chamada de IA por busca — inviável no orçamento de $1/mês). `produtos comparar ID_A ID_B` é **o usuário pedindo, uma vez, por um par específico** — baixa frequência, opt-in, cabe no orçamento, e nunca funde sozinho (só imprime uma opinião; `fundir` continua sendo um comando separado e manual).

**2. Busca por termo parcial e com erro de digitação → `rapidfuzz`, sem FTS5.**
Com um catálogo pessoal de no máximo algumas centenas de produtos distintos, comparar o termo digitado contra todos os `nome_canonico` com `rapidfuzz.process.extract` roda em sub-milissegundos — não precisa de índice. Isso cobre termo parcial e erro de digitação **na mesma chamada**, com uma biblioteca só. `SQLite FTS5` foi cogitado e descartado: exigiria tabela virtual + triggers de sincronização pra ganhar ranqueamento que não faz falta nesse volume, e mesmo assim não resolveria digitação errada sozinho (então `rapidfuzz` entraria de qualquer jeito) — duas ferramentas fazendo o trabalho de uma.

**O scorer mudou em v2.3.1 (`fuzz.WRatio` → palavra a palavra), por medição no banco real — não reverta pra `WRatio`.** `WRatio` penaliza termo curto contra nome longo, e depois que a IA passou a escrever nomes legíveis (longos) isso **inverteu o ranking**: `pao` pontuava 60 contra `Pão de forma Bauducco tradicional 390g` (ficava de fora) e 72 contra `Laranja pera União` (entrava, por casamento parcial em "UNIAO"). Resultado medido: `julius consultar pao` devolvia 12 frutas e 1 pão; `julius consultar pao padaria` devolvia 1 linha, porque a interseção com a tag herdava o mesmo termo quebrado. Nenhum valor de corte conserta isso — 70 deixa as frutas entrarem, 75+ mata os pães que sobraram. `_name_score` (em `services/search.py`) compara **palavra a palavra**: pra cada palavra do termo, a melhor palavra do nome por `fuzz.ratio` ou por prefixo; o mínimo entre as palavras do termo é o score. `MATCH_SCORE_CUTOFF` subiu de 70 pra 80 na mesma medição. Depois: 6 linhas em `pao` (5 pães + 1 falso positivo de 80), 4 em `pao padaria`. O prefixo só funciona numa direção (`refri` → `REFRIGERANTE` sim; `LING` → `linguiça` não — esse é resolvido pelo rename da IA, ver abaixo), e termo multi-palavra ficou estrito de propósito (`pao de alho` caiu de 15 acertos pra 1). Números no docstring de `MATCH_SCORE_CUTOFF`.

**Conectivos saem do termo antes do score (2026-09-20, sem ticket, sem migração).** Incidente real pelo bot: "Quanto tá o suco de uva?" → o modelo extraiu `suco de uva`, a busca voltou **0** e o caminho de zero-resultado ofereceu "Suco pronto Natural One uva e maçã" como alternativa de categoria — a resposta disse "sem preço registrado" e citou um suco de uva na frase seguinte. Causa: `_name_score` exige que **toda** palavra do termo ache par no nome, e `DE` pontuava 20–67 contra todas as palavras dos três sucos de uva do catálogo (`suco uva` casa os três com 100). `CONNECTIVE_WORDS = {DE, DA, DO, DAS, DOS, E}` (`services/search.py`) é removido só do **termo**, dentro do próprio scorer (vale para produto e para `match_kind`). Medido contra o catálogo real (130 produtos, 23 termos multi-palavra): só `suco de uva` muda (0 → 3); `pao de alho`, `agua com gas`/`agua sem gas`, `creme de leite` etc. idênticos. `COM`/`SEM` ficam de fora de propósito — distinguem água com e sem gás. "Termo multi-palavra estrito" continua valendo: as palavras que sobram ainda precisam casar todas.

**Rejeitado explicitamente: busca semântica (embeddings/`sentence-transformers`).** Resolveria "limpeza" → "DETERGENTE" (ver item 3), mas custa um modelo de ML baixado localmente pra um catálogo de possivelmente umas centenas de itens — desproporcional. Não usar a menos que o catálogo cresça ordens de grandeza e isso vire dor real.

**Medido de verdade em 2026-09-22** (`claudedocs/research_entity_resolution_lexical_matching_scaling_20260922.md`, `docs/design/entity-resolution-architecture.md`) — a rejeição acima era suposição desde a v1; deixou de ser. Testados `fastembed` com dois modelos multilíngues (`paraphrase-multilingual-MiniLM-L12-v2`, 220MB, e `paraphrase-multilingual-mpnet-base-v2`, 1GB) contra os casos reais desta sessão. No nível de palavra, nenhum corte de cosseno separa os falsos positivos dos matches necessários: `TOMATEE`/`TOMATE` (precisa bater) mede 0,766; `SUCO`/`SUINCO` (falso positivo) mede 0,818 — mais parecido que o match de verdade. No nível de nome de produto inteiro (o uso normal de um "sentence transformer"), foi pior: pedindo "picanha", "coca", "pepsi" ou "suco" contra os 133 nomes reais, o produto certo **nem aparece no top 5** dos dois modelos. A IA que já resolve `kind` (`kind_candidates`, ver "Identidade de produto e busca" abaixo) acerta esses mesmos casos porque tem conhecimento de mundo que um modelo de frase genérico, sem ajuste ao domínio de cupom fiscal brasileiro, não tem — e não existe dado rotulado do próprio catálogo pra ajustar um modelo a esse domínio. Fecha, por ora, a hipótese de trocar por embeddings; reabrir exige as duas condições ao mesmo tempo (catálogo em outra ordem de grandeza **e** dado rotulado real), não uma sozinha.

**Convenção nomeada em 2026-09-22: toda resolução de entidade em `bot/actions.py` que encontra 2+ candidatos plausíveis, sem vencedor claro, levanta `ModelRetry` listando as opções — nunca escolhe sozinha.** Já era assim em `resolve_product`, `resolve_store` e `_resolve_kind` desde que cada um foi escrito, sem nunca ter sido nomeado como o mesmo padrão deliberado; auditados nesta rodada os dois candidatos a gap (`detect_tag`: sem ambiguidade observável nas 13 tags reais; `resolve_store`: já perguntava). É a peça de "desambiguação por sub-diálogo" que sistemas de diálogo orientados a tarefa usam há 30+ anos (`claudedocs/research_entity_resolution_lexical_matching_scaling_20260922.md`) — uma resolução de entidade nova que não seguir este formato é a exceção que precisa de justificativa, não o padrão.

**Abreviações (`LING FGO` → "linguiça" não bate) — solução durável chegou em v2, não é mais só uma limitação anotada.** `julius produtos revisar`/`importar` pedem à IA um nome legível (`enrich_products`), aplicado automaticamente quando o produto ainda tem o nome cru do cupom (`products.has_raw_name`) — depois disso `consultar linguiça` acha o produto pelo nome de verdade, sem precisar de sinônimo nenhum embutido no buscador. `has_raw_name` é o que impede a IA de sobrescrever um nome que o usuário já editou à mão: compara `canonical_name` com as `prices.description` daquele produto; se não bater mais com nenhuma, o produto foi renomeado manualmente e a IA nunca mexe de novo ali.

**3. "A busca não achou nada, nem por tag" → fallback de IA em `consultar`, só quando o determinístico veio vazio (v2).** `rapidfuzz` continua sendo a primeira tentativa sempre; a IA (`suggestions.match_products`) só é chamada quando `search_prices` devolve lista vazia, o termo não é `None` e não há `--tag` — nunca quando já existe resultado (regra de frequência do orçamento, ver "Camada opcional de IA"). Achando algo, a dica `FOUND_VIA_AI` sugere consertar o dado (`renomear`/`tag`) pra próxima busca já achar sem IA — o fallback é conforto, a correção do nome é a solução permanente.

**3. "termos tipo limpeza" (categoria) → não é busca, é tag manual.**
`rapidfuzz` (nem nenhuma métrica de string) conecta "limpeza" a "DETERGENTE" ou "SABAO EM PO" — não há sobreposição de caracteres entre essas palavras, edit-distance não ajuda aqui. Isso é conhecimento de categoria, não similaridade textual. Resolvido com `tags` + `produto_tags`: o usuário marca manualmente (`julius produtos tag ID limpeza`), sem classificação automática — evita categorizar errado silenciosamente.

**Isso também não contradiz `sugerir_tags` da IA (seção "Camada opcional de IA")** — a IA só **sugere** tags candidatas pra `julius produtos tag` mostrar antes de o usuário confirmar; ela nunca grava em `produto_tags` sozinha. "Auto-classificação" continua rejeitado; "sugestão que o usuário aceita ou ignora" é outra coisa.

**Isso também não contradiz a detecção de tag em texto livre da v2.1** (`julius consultar hortifruti`, ver seção "CLI") — `detect_tag` compara a **palavra digitada** contra os **nomes das tags já cadastradas** (`hortifruti` → tag `hortifruti`, erro de digitação incluído), nunca a descrição do produto contra uma categoria. "limpeza" continua sem achar "DETERGENTE" sozinho; o que mudou é só não precisar mais de `--tag` quando a palavra digitada já é (ou quase é) o nome de uma tag que existe.

### Preço por conteúdo (comparar embalagens de tamanho diferente)

**Escopo novo desta sessão de design** (surgiu ao analisar os 3 arquivos reais + pergunta explícita do usuário: "20 ovos por X, 30 ovos por Y, qual tá melhor?") — chegou depois do resto da interface já estar fechada, então os comandos abaixo não existiam nas seções anteriores.

**O problema que o agrupamento por `unidade` (UN/KG) não resolve.** Pra item vendido por KG (picanha, tomate, cebola), `valor_unitario` já É o preço por kg — comparável direto. Pra item vendido por UN (`REFRI PEPSI PET 2L` a R$6,99 vs `REFRI ANT GUARANA PET 1.5L` a R$4,99), `valor_unitario` é o preço da embalagem inteira, não do conteúdo — comparar os dois direto ignora que uma garrafa é 33% maior que a outra. É exatamente o caso "20 ovos vs 30 ovos" do usuário.

**Rejeitado explicitamente: extrair o tamanho da embalagem automaticamente da descrição.** As descrições reais têm números que não são conteúdo, ou são ambíguos:
- `PRATO REDOND DESC STRAWPLAS 21CM CRISTAL` — "21CM" é diâmetro do prato, não conteúdo nenhum.
- `CHA LEAO RELAXA CX 16G C/10UN CAMOM/MARACUJA` — "16G" é por sachê ou da caixa toda (16g × 10 = 160g)? Ambíguo pelo texto puro.

Um regex que acerta às vezes e erra silenciosamente em casos como esses é pior do que não ter a funcionalidade — o objetivo do sistema é confiança na lembrança de preço. Por isso: **conteúdo é sempre declarado manualmente pelo usuário**, nunca inferido.

**Schema**: `produtos.conteudo_qtd` + `produtos.conteudo_unidade`, os dois `NULL` até o usuário definir. `conteudo_unidade` normalizado pra uma base única por dimensão no momento de gravar — `G`/`ML` digitados pelo usuário viram `KG`/`L` na gravação (ex.: "500 G" grava `0.5, 'KG'`) — pra nunca ter parte do catálogo em `G` e parte em `KG` (que geraria preço-por-grama vs preço-por-quilo, números que ninguém compara de cabeça). Mesma disciplina do `UN1`→`UN` no parser: normalizar na borda, manter o interior burro.

- `julius produtos definir-conteudo ID QTD UNIDADE` — aceita `L`/`ML`/`KG`/`G`/`UN` como `UNIDADE` de entrada, converte e grava só `L`/`KG`/`UN`. Chama `core.definir_conteudo(produto_id, quantidade, unidade) -> None`.
**Regra de base de comparação (v2.2, `julius/domain/comparison_basis.py`).** O princípio fundador "nunca comparar preços de bases diferentes" estava sendo violado pelo próprio `highlight`: ele comparava `unit_price` dentro do grupo de mesma `unit`, e para item vendido por UN `unit_price` é o preço da *embalagem*. Medido no banco real: a garrafa de água de 500ml a R$ 1,49 era marcada como a mais barata do grupo quando por litro (R$ 2,98/L) ela é a **mais cara** (contra R$ 2,46/L da de 1,5L). A regra que substituiu a escolha da base, um ramo por caso observado:

| Situação do grupo (já agrupado por `unit`) | Base | Por quê |
|---|---|---|
| `unit == "KG"` | `unit_price` | R$/kg **já é** preço por conteúdo |
| `unit == "UN"`, todas as linhas do mesmo `product_id` | `unit_price` | mesma embalagem em datas diferentes: série temporal legítima |
| `unit == "UN"`, vários produtos, todos com conteúdo e `content_unit` único | `price_per_content` | é o caso da água, que inverte quem é o mais barato |
| `unit == "UN"`, conteúdo parcial | `price_per_content` **só no subconjunto** com conteúdo (se tiver ≥ 2 linhas) | quem não tem conteúdo não participa e fica sem destaque |
| subconjunto com < 2 linhas comparáveis | nenhum destaque no grupo | não há duas linhas comparáveis; silêncio é a resposta honesta |

Consequência que **não** é bug: enquanto o conteúdo de um produto-UN não estiver definido, ele deixa de receber marcação de mínimo/máximo em grupos heterogêneos. É o que transforma "preencher conteúdo" na ação de maior valor do sistema — e a razão de a v2.2 ter passado a aplicar o conteúdo sugerido pela IA automaticamente (ver "Camada opcional de IA"). **Na v2.3 isso virou o próprio critério de pendência**: um produto vendido por UN e sem conteúdo continua aparecendo em `produtos revisar` até alguém resolver, e é a única coisa que a revisão pergunta. Produto vendido só por KG nunca é cobrado de conteúdo — R$/kg já é o preço por conteúdo, ramo 1 da tabela acima. A mesma função é usada por `services/comparison.py`; por isso ela mora em `domain/`, não em `services/` (a DAG proíbe `services → services`).

- `consultar`, quando `conteudo_qtd` não é `NULL`, mostra uma coluna extra "preço por `conteudo_unidade`" (`valor_unitario / conteudo_qtd`) ao lado do preço cru — nunca substitui o preço cru, só complementa. Quando `conteudo_qtd` é `NULL` (a maioria dos produtos, no começo), a coluna simplesmente não aparece — sem tentar adivinhar.

**Achado real vs. caso ilustrativo — não confundir os dois.** Nos 3 recibos reais, `REFRI PEPSI PET 2L` (R$6,99 → R$3,50/L) e `REFRI ANT GUARANA PET 1.5L` (R$4,99 → R$3,33/L) têm tamanhos diferentes, mas nesse caso específico o Guaraná já é mais barato tanto no preço cru quanto no preço por litro — **não existe, nos dados reais, um caso onde a ordem muda** entre "mais barato no total" e "mais barato por conteúdo". O caso que realmente demonstra por que a funcionalidade importa é o do usuário (hipotético, não vem dos 3 arquivos): 20 ovos por R$12,00 (R$0,60/ovo) vs. 30 ovos por R$16,50 (R$0,55/ovo) — o pacote maior parece mais caro no total e é mais barato por unidade. Isso vira um fixture sintético nos testes (seção abaixo), não um fixture real.

### Camada opcional de IA (assistência em ambiguidades, nunca decisão automática)

**Estado: implementada e em uso real desde v2** (as seções abaixo, escritas na sessão original de design v1, propunham só a costura; o que segue documenta o contrato de verdade — texto de v1 mantido e anotado onde ficou obsoleto, não apagado).

**Pedido original (v1)**: projetar já a costura pra um dia acoplar uma LLM barata, que ajude nas situações não-determinísticas que este design já rejeitou resolver sozinho (fusão de produto, tag, conteúdo ambíguo) — sem gastar mais que US$1/mês. **Orçamento revisado em v2: US$5/mês** (provedor e preços reais escolhidos, ver abaixo).

**Princípio novo em v2, o que resume tudo abaixo: a IA grava o reversível, nunca o irreversível.** Nome legível (`renomear` desfaz), categoria (`tag ID TAG --remover`), conteúdo (`definir-conteudo ID --remover`, v2.2) e tipo (`tipo ID --remover`, v2.2) podem ser aplicados automaticamente. Fusão de produto e qualquer preço nunca são tocados por IA — `produtos fundir` continua 100% manual, mesmo quando a IA "tem certeza" de uma duplicata.

**Reversão deliberada em v2.2 — não é regressão, não "restaure" a confirmação.** Até a v2.1 este documento afirmava que conteúdo de embalagem *nunca* era gravado sem confirmação explícita, nem com `--sim`. A v2.2 reverteu isso de propósito, por dois motivos medidos: (1) conteúdo passa o teste de duas condições de `docs/requirements/comparability-closure.md` §4 — existe comando de desfazer desde o ticket 118, e um valor errado aparece na coluna "Por L/KG/UN" de `consultar` e na tabela de `produtos listar`; (2) a confirmação virou fricção pura — **32 dos 79 produtos vendidos por UN estavam sem conteúdo**, e o import de 16/09 imprimiu 26 comandos `definir-conteudo` que ninguém rodou. Como conteúdo é justamente o que habilita comparar embalagens de tamanhos diferentes (ver "Preço por conteúdo"), a fricção estava derrubando a funcionalidade principal. A linha vermelha que **não** mudou: fusão continua manual.

**Atualização da v2.4 — fusão saiu da lista de irreversíveis, porque deixou de ser irreversível.** A frase acima continua exata; o que mudou é de que lado a fusão está. Ela passou a cumprir **as duas metades** da regra: o erro é visível (o grupo aparece com um nome só em `produtos listar` e o histórico se junta em `consultar`) e existe comando de desfazer (`produtos desfundir`, ticket 141, construído **antes** da automação). Fundir automaticamente exige as duas — foi por faltar a segunda que a v2.2 recusou.

O que **não** mudou: a IA nunca toca em preço, e o gatilho é o veredito dela, sem limiar (ver "Identidade de produto e busca" para as duas medições que reprovaram limiar e tipo como filtro).

**Refinamento da v2.3 — a distinção que organiza tudo: conteúdo de rótulo × conteúdo de intuição.** A reversão da v2.2 continua valendo, mas só para **uma** origem de conteúdo. A regra de decisão, em uma frase que generaliza: **a IA pode gravar sozinha o que o usuário consegue ver que está errado.**

| Origem do conteúdo | Quem grava | Por quê |
|---|---|---|
| **Rótulo inequívoco** (`C/30` → 30 UN, `500G` → 0,5 KG), prompt `enrich` | automático, como na v2.2 | o número está escrito na descrição; errar é raro e visível |
| **Costume do varejo** (brócolis vem em bandeja de 1 UN), prompt `packaging` | **nunca** — só alimenta uma pergunta | não passa na condição (2) do teste de duas condições: conteúdo inventado não aparece na saída normal, vira um R$/UN plausível |

O contraexemplo que sustenta a linha está medido: `Filme PVC Wyda 30m x 28cm` virou **`30 UN`** — o modelo leu "30 metros" como "30 unidades" e marcou o campo de certeza. Um preço por unidade calculado em cima disso é um número plausível numa tabela, exatamente o tipo de erro que este projeto inteiro existe para não cometer. A proteção é estrutural (o humano escolhe), não engenharia de prompt: mexer no texto do prompt `packaging` invalida a medição que autorizou essa chamada a existir.

**Auto-relato de confiança da IA falhou três vezes neste projeto; o único sinal confiável é a recusa.** `confidence` numérico (v2, pedido no prompt `merge`: `Alho` ↔ `Pão de Alho` veio com **1,00**), número de tags como proxy de dúvida (v2.3: 2 categorias para 24 de 25 produtos, inútil como sinal) e "diga se o número veio do rótulo" (v2.3, sonda de embalagem: 9 de 9 palpites, nenhum recuo). O que funciona é a **recusa** do prompt de produção: instruído a preencher `content` só quando a descrição é inequívoca, ele devolveu `null` certo em **6 de 6**. É por isso que a pergunta de conteúdo é disparada pela recusa e não por um limiar — e é por isso que `enrich` e `packaging` são **duas chamadas separadas**, com versões e validadores próprios: pedir "recuse quando não for inequívoco" e "dê candidatos plausíveis" no mesmo prompt arrisca o único ativo de incerteza que foi medido. Custo da separação: US$ 0,0007 por rodada. Uma sessão futura que queira um threshold de confiança precisa antes explicar por que as três medições acima não se aplicam.

**Categoria automática é a primeira candidata *que já existe* no vocabulário (v2.3) — estreitamento deliberado do requisito.** O requisito original dizia "a primeira sugestão"; o design (`docs/design/review-scope-v2.3.md` §3.2) estreitou para "a primeira conhecida" porque o vocabulário de `tags` é a entrada da medição de `TAG_MATCH_CUTOFF = 75` (v2.1), calibrada contra as 13 tags semeadas com a garantia de que nenhuma pontua acima de 55 contra outra. Deixar a IA **criar** vocabulário sozinha, num caminho onde ninguém está olhando, põe em risco uma constante já medida. Custo do estreitamento na amostra: **zero** (a primeira candidata já era conhecida em 25 de 25). Quando não for, o produto fica pendente, reaparece, e o usuário cria a categoria com `julius produtos tag ID nova` — com ele olhando. Reverter para a forma literal é uma linha em `curation.propose`; esta nota existe para que seja decisão, não descuido. Pelo mesmo motivo, `--sim` deixou de aplicar uma primeira candidata desconhecida.

**A regra que faz o orçamento ser real: IA só é chamada em pontos de baixa frequência, nunca no caminho de leitura corriqueiro.** `consultar` roda várias vezes por dia — só chama IA **quando a busca determinística vem vazia** (regra revisada em v2; antes era "nunca chama IA nenhuma", ficou "nunca quando já achou algo determinístico"). `importar`/`produtos revisar` chamam IA para produtos novos/pendentes (algumas vezes por mês, não por busca). `produtos comparar` continua opt-in por par. Essa regra é o que impede uma sessão futura de "melhorar a busca" plugando IA em todo resultado de `consultar` e estourando o orçamento sem querer.

**Por que `urllib.request` da stdlib, não um SDK de provedor.** É uma chamada HTTP simples (um POST, um JSON de resposta, sem streaming) e baixíssima frequência — o caso raro em que stdlib já é menos código do que configurar e importar um SDK (o oposto do que aconteceu com Typer, onde o framework poupava trabalho real). Padronizar no formato REST `/chat/completions` (compatível com vários provedores baratos) é toda a "abstração de provedor" necessária — trocar de provedor é trocar `base_url`/`api_key`/`model` na config, sem registry nem plugins.

**Provedor/modelo — decidido em v2: DeepSeek, `deepseek-flash`.** Preço no screenshot do usuário: US$0,15/0,30 por milhão de tokens de entrada (fora de pico/pico), US$0,60/1,20 saída. `JULIUS_AI_INPUT_PRICE_USD_PER_1M`/`_OUTPUT_PRICE_USD_PER_1M` recomendados nos valores de **pico** (`0.30`/`1.20`) pra o contador de gasto nunca subestimar. Conta de padaria confirmada: um catálogo pessoal gera no máximo algumas dezenas de chamadas curtas por mês — a maioria fica na casa de centavos de dólar. Ainda assim o orçamento é reforçado por código, não por confiança na estimativa (próximo parágrafo).

**Orçamento reforçado com um contador persistido, não com confiança na estimativa:** tabela `ai_usage(month TEXT PK 'YYYY-MM', spent_usd REAL)` — já faz parte do schema v1 (ver "Armazenamento"). Antes de qualquer chamada: lê `spent_usd` do mês corrente; se já bateu o orçamento configurado, **não liga pra API, retorna "sem sugestão"**. Depois de uma chamada real: soma o custo estimado (tokens de entrada/saída da resposta × preço por token configurado). Preço por token não é hardcoded (mudaria toda vez que o provedor reajustar) — vem de variável de ambiente.

**Configuração — tudo por variável de ambiente, tudo opt-in** (lida uma vez por `julius/config.py` → `Config`; testado em `tests/test_config.py`):
- `JULIUS_AI_API_KEY` — não configurada = IA inteira desligada, silenciosamente (`Config.ai_configured` exige key + base_url + model). Sem isso o sistema funciona 100% igual a hoje.
- `JULIUS_AI_BASE_URL`, `JULIUS_AI_MODEL` — endpoint e modelo (compatível `/chat/completions`).
- `JULIUS_AI_BUDGET_USD` — default `1.0` (o usuário roda com `5.0`).
- `JULIUS_AI_INPUT_PRICE_USD_PER_1M`, `JULIUS_AI_OUTPUT_PRICE_USD_PER_1M` — preço por milhão de tokens, pra calcular o gasto real depois de cada chamada.
- `JULIUS_AI_REQUEST_EXTRAS` **(v2)** — JSON mesclado no corpo do request, por cima de `model`/`messages`/`temperature`/`max_tokens`/`response_format` (extras podem sobrescrever qualquer chave). Existe especificamente porque `deepseek-flash` raciocina por padrão e não converge no prompt de enriquecimento (ver "Fatos e pegadinhas"): `'{"thinking":{"type":"disabled"}}'` resolve. Default `{}` — só existe pra quem precisar, não é obrigatório pra outros provedores.

**Duas peças, não uma — separação que o esqueleto anterior errou.** Rede é infra; orçamento é regra de negócio + persistência. Misturar os dois obrigaria o cliente HTTP a conhecer o banco.
- `julius/infra/llm_client.py` — `Protocol LlmClient` com `complete(system_prompt, user_prompt, *, max_tokens) -> LlmResponse` (**v2**: nunca devolve `None` — toda falha vira `LlmResponse("", 0, 0, error="...")`, com `error` curto e estável: `"HTTP 429"`, `"timeout"`, `"finish_reason length"`, `"empty content"`; tokens vêm preenchidos quando o provedor já cobrou por eles). `HttpLlmClient` pede `response_format: {"type": "json_object"}` e mescla `ai_request_extras`. É `Protocol` porque teste de serviço substitui a rede por um fake (`tests/_fakes.py::ScriptedLlmClient`).
- `julius/infra/ai_log.py` **(v2, novo)** — `append(path, record)`, uma linha JSONL por tentativa de chamada em `~/.local/share/julius/ai_calls.jsonl` (ao lado do banco, sem variável nova). Nunca lança. É o que torna visível o silêncio de "IA não sugeriu nada": orçamento estourado, erro de rede e resposta truncada geram linha própria, cada uma com `error` preenchido.
- `julius/services/suggestions.py` — recebe `conn`, `Config` e um `LlmClient`; `_ask` (privada) checa orçamento, tenta até 2 vezes, cobra e loga cada tentativa (inclusive as que falharam ou vieram truncadas — pagou, conta), faz `json.loads` direto na resposta (JSON mode elimina extração por regex).
- `julius/services/curation.py` **(v2, novo)** — traduz o que a IA disse em decisões determinísticas (aplicar sozinho × perguntar) e encontra candidatos a duplicata; nunca imprime, nunca funde.

**Invariante mais importante — nem `LlmClient` nem `services/suggestions.py`/`curation.py` lançam exceção.** Chave ausente, orçamento estourado, erro de rede, resposta malformada: tudo vira `error` preenchido (cliente) ou `None`/lista vazia (serviços), nunca uma exception subindo pro chamador. Todo serviço que consulta sugestões trata isso como "sem sugestão" e cai no comportamento determinístico. É essa propriedade que garante que esquecer de configurar (ou de recarregar) a chave nunca quebra o sistema — ele só fica sem a ajuda extra.

`services/suggestions.py` expõe hoje (assinaturas reais, `julius/services/suggestions.py`):

- `is_available(conn, config, month=None) -> bool` — `config.ai_configured`, preços configurados e orçamento do mês não estourado.
- `spent_this_month(conn, month=None) -> float` — pra CLI mostrar "US$ gasto de US$ teto" sem importar `repositories`.
- `suggest_merges(conn, config, client, pairs: Sequence[tuple[str, str]]) -> list[MergeSuggestion | None]` — em lote (uma chamada pra N pares); usado por `produtos comparar` (par único) e por `curation.judge_duplicates` (candidatos pré-filtrados por `rapidfuzz`).
- `enrich_products(conn, config, client, products, known_tags) -> dict[int, ProductEnrichment]` — nome legível, 1–3 categorias, conteúdo da embalagem; em lotes de 25 (`ENRICH_BATCH_SIZE`), um lote que falha só perde aqueles produtos. Chamado por `curation.propose`, usado em `produtos revisar`/`importar`.
- `match_products(conn, config, client, term, catalog) -> list[int]` — dado um termo que a busca determinística não achou, devolve ids do catálogo que respondem (sinônimo/abreviação/categoria). Chamado só quando `consultar` vem vazio.
- `suggest_packaging(conn, config, client, products) -> dict[int, PackagingHint]` **(v2.3)** — a intuição de varejo: `form` (`unit`/`pack`/`weight`/`volume`/`unknown`) e até 3 candidatos de conteúdo. Prompt e versão próprios (`packaging` v1), separados do `enrich` de propósito. Só é chamada quando a revisão é interativa e há algo a perguntar; o resultado **nunca** é gravado, só vira opção na pergunta de conteúdo.

As três funções antigas do design v1 (fusão par a par, conteúdo isolado, tags isoladas) foram removidas em v2 — substituídas por `suggest_merges` (lote) e `enrich_products` (nome+tags+conteúdo numa chamada só).

**Cortado de propósito: classificar automaticamente um código de unidade novo (`Gf`, `PC`, etc.) via IA.** O mapa de unidade é uma constante curada no código-fonte, editada por um humano quando aparece um código novo — evento raro (surgiu 1x em 5 notas). Gastar uma chamada de rede e checagem de orçamento só pra decorar uma mensagem de erro é máquina demais pra um evento que já falha alto e claro sozinho; se quiser uma opinião da IA nesse momento, o usuário pode perguntar por fora, sem o sistema precisar saber fazer isso.

**`julius produtos comparar ID_A ID_B`** — chama `suggestions.suggest_merges(conn, config, client, [(a, b)])[0]`; sem sugestão, distingue três motivos (não é mais uma mensagem genérica): não configurada (dica `AI_NOT_CONFIGURED`), orçamento do mês esgotado (com valores em US$), ou a chamada falhou (aponta pra `ai_calls.jsonl`). Nunca funde sozinho — `julius produtos fundir` continua sendo o único jeito de aplicar.

**`julius produtos revisar [--sim]` e `julius importar [--sim]` (v2, reescrito na v2.3)** — a curadoria de verdade. `curation.propose` chama `enrich_products` pros produtos pendentes — desde a v2.3, "pendente" é `products.incomplete_product_ids`: falta tipo, categoria **ou** conteúdo (este só para produto vendido por UN). Aplicados **sem perguntar**: nome legível (desfazer: `renomear`), a primeira categoria **já conhecida** (`tag --remover`), tipo (`tipo ID --remover`) e conteúdo lido de rótulo inequívoco (`definir-conteudo ID --remover`). **Não existe mais pergunta de categoria** (`_ask_tag` saiu na v2.3): candidata desconhecida simplesmente não é aplicada e o produto reaparece na próxima rodada. A **única** pergunta é o conteúdo que a IA recusou, para produto vendido por UN: `suggest_packaging` alimenta as opções (`[1] 10 UN · pacote  [2] 20 UN · pacote  [3] digitar  [Enter] pular`), candidatos de `form == "weight"`/`"unknown"` são suprimidos (é onde saiu `500 KG` de bacon), entrada inválida vira pular sem repetir a pergunta, e a resposta grava por `curation.apply`, entrando em `actions.jsonl` com desfazer. `--sim` significa "não perguntar nada" (mudou de sentido na v2.3; renomear a flag foi avaliado e recusado). No fim, candidatos a duplicata (`curation.duplicate_candidates`, `rapidfuzz` corte 75) julgados pela IA (`judge_duplicates`) só imprimem o comando `fundir` pronto — nunca fundem. `importar` roda essa revisão uma vez, no fim, só para os produtos criados naquele import (não puxa o catálogo incompleto inteiro: o comando de pôr em dia é `produtos revisar`).

### Estrutura de pacote — camadas como DAG de dependências

Pedido do usuário: implementar por camadas, dos nós independentes pros dependentes, com modelos/serviços/repositórios separados, tudo testado — e um agente de código por ticket, sem se perder. A estrutura abaixo **substitui** um esqueleto anterior (Protocol em todo módulo + DI por construtor + um `ServicoPrecos`/`RepositorioPrecos` únicos com 11 métodos) que foi descartado por três motivos concretos: identificadores em português, "god objects" que fariam todo ticket editar o mesmo arquivo, e efeito colateral em tempo de import (`import julius.cli` abria e migrava o banco).

```
julius/
├── config.py                 # L1 · env → Config (frozen). Só os.environ; sem I/O de arquivo.
├── domain/                   # L1 · zero I/O, zero imports internos
│   ├── models.py             #      frozen dataclasses: Store, Product, ReceiptItem, Receipt, PriceRecord,
│   │                         #      ImportResult, MergeSuggestion, ContentSuggestion, ProductComparison
│   └── normalization.py      #      UNIT_MAP, normalize_sale_unit, normalize_content, parse_decimal_br, digits_only
├── infra/                    # L1/L2 · fala com o mundo (arquivo, rede); importa domain e config
│   ├── db.py                 #      connect, apply_migrations, available_migrations, schema_version
│   ├── migrations/*.sql
│   └── llm_client.py         #      Protocol LlmClient + LlmResponse (implementação HTTP: ticket)
├── parsers/                  # L2 · importa só domain
│   ├── __init__.py           #      Protocol ReceiptParser.parse(html, source) -> Receipt
│   └── df.py                 #      (ticket) DFReceiptParser
├── repositories/             # L2 · SQL por agregado; funções puras (conn, ...) — sem classes, sem ABC
│   ├── stores.py · products.py (skus, tags, conteúdo) · prices.py · ai_usage.py     (tickets)
├── services/                 # L3 · casos de uso; devolvem dados, nunca imprimem
│   ├── importing.py · search.py · catalog.py · export.py · suggestions.py           (tickets)
├── cli/                      # L4 · Typer; só chama services e formata com rich
│   ├── __init__.py           #      app + callback raiz (nenhuma conexão aberta em import)
│   └── receipts.py · stores.py · products.py                                          (tickets)
└── bot/                      # L4 (v2.6) · irmão de cli/, não o importa nem é importado
    ├── app.py                #      o único módulo que conhece Update/Telegram
    ├── turn.py · agent.py · actions.py · render.py
```

**Adições de v1.1 e v2** (a árvore acima é a original do design v1; ficou como registro histórico em vez de reescrita):
- `julius/services/guidance.py` + `julius/cli/_hints.py` — módulo de dicas de uso (v1.1, ver seção própria).
- `julius/infra/ai_log.py` **(v2)** — log JSONL de chamadas de IA, um arquivo, uma função (`append`).
- `julius/services/curation.py` **(v2)** — decide o que a IA pode aplicar sozinho e o que precisa perguntar; encontra candidatos a duplicata.
- `julius/cli/_review.py` **(v2)** — a tela de revisão compartilhada por `produtos revisar` e `importar`. **(v2.3)** `_ask_content`/`_FORM_LABELS` (a pergunta de conteúdo e a tradução de `form` para uma palavra fixa — nenhum texto livre da IA chega à tela); `_ask_tag` foi removido.
- `domain.PackagingForm`/`PackagingHint` + `SYSTEM_PROMPTS["packaging"]` **(v2.3)** — a intuição de varejo, ver "Camada opcional de IA".
- `repositories/products.py::incomplete_product_ids`/`sold_by_unit_ids`/`receipt_descriptions` **(v2.3)** — pendência por campo faltando, e os dois dados de exibição que a proposta passou a carregar (`ProductProposal.receipt_description`, `.tag`, `.sold_by_unit`; `tag_is_known`/`auto_tag` saíram).
- `julius/infra/migrations/0002_store_address_and_seed_tags.sql` **(v2)** — `stores.address` + 13 tags semeadas.
- `julius/domain/comparison_basis.py` **(v2.2)** — a regra de base de comparação, função pura sobre `PriceRecord`; vive em `domain` porque `services/search.py` **e** `services/comparison.py` a consomem e a DAG proíbe `services → services`.
- `julius/services/comparison.py` **(v2.2)** — `compare_stores` (preço por grupo entre mercados) e `new_extremes` (o que bateu recorde numa nota recém-importada).
- `julius/infra/cnpj_client.py` **(v2.5)** — `fetch_trade_name(cnpj)`, uma API pública via `urllib` (sem dependência nova); nunca lança, toda falha lê como "sem nome fantasia".
- `julius/domain/normalization.py::store_place`/`compose_nickname`/`is_unnamed` **(v2.5)** — o bairro do endereço e a única definição de como o apelido é composto e de quem está pendente.
- `services/catalog.py::name_stores`/`unnamed_stores` + `services/suggestions.py::suggest_trade_names` (prompt `store`) **(v2.5)** — a ordem registro → IA, a composição e a gravação.
- `julius/infra/receipt_files.py` **(v2.2)** — `archive` (move a nota importada pra `entrada/importados/<data>_<chave>.html`) e `discard_sidecar` (apaga a pasta `_files/`; **existe mas não é chamada**, pendente de decisão do usuário — é a única operação destrutiva do sistema).
- `julius/infra/migrations/0003_product_kind.sql` **(v2.2)** — `products.kind`.
- `julius/infra/migrations/0004_product_merge.sql` **(v2.4)** — `products.merged_into` + a view `product_group`; ver "Armazenamento".
- `repositories/products.py::set_merged_into`/`group_root`/`group_members` e `_group_product` **(v2.4)** — a relação de fusão e o produto efetivo do grupo. As 26 leituras que agrupam por `product_id` vivem só aqui e em `repositories/prices.py`, o que é o que tornou a mudança contida: nenhum serviço precisou ser editado.
- `services/catalog.py::unmerge_product`/`merge_inheritance` **(v2.4)** — desfazer e o que o grupo herdou (para a notificação). `merge_products` virou validação + um `UPDATE`; `reassign_skus`, `reassign_product` e `delete_product` foram removidas com ela. **Não existe mais nenhum caminho de código que apague um produto.**
- `julius/cli/_common.py::br_date`/`relative_age`/`date_cell` **(v2.5.1)** — data brasileira, idade relativa em faixas (`today` injetável, senão o teste depende do dia em que roda) e a célula empilhada. Substituíram as duas cópias de `_day_month`; `cli/products.py::_when` é o único chamador de fuso, para `actions.jsonl`.
- `julius/domain/formatting.py` **(v2.6)** — `money`/`br_date`/`relative_age`/`content_text`/`store_labels`/`coverage_text`/`plural_groups`, movidos de `cli/_common.py` e `cli/stores.py` **com o corpo idêntico**; `cli/_common.py` reexporta os quatro primeiros (um teste fixa a identidade, porque o import parece morto lá e apagá-lo quebraria quatro módulos).
- `julius/bot/` **(v2.6)** — `render.py` (texto de celular: HTML mínimo, teto de 4096 com `fit`), `actions.py` (`Deps`, `resolve_product`/`resolve_store`, 4 leituras, 10 escritas, `PendingWrite`/`execute`), `agent.py` (`build_model`/`build_agent`, `SYSTEM_PROMPT` v1), `turn.py` (`handle_text`/`handle_tap`, sem nada de Telegram) e `app.py` (o único que conhece `Update`).
- `services/suggestions.py::record_usage` **(v2.6)** — cobrança + log públicos, com `prompt_version` explícito; `_ask` passou a usá-la e `add_spent` tem **uma** ocorrência no módulo.
- `services/search.py::matching_product_ids` **(v2.6)** — era `_matching_ids`; virou pública porque `resolve_product` a usa.
- `~/.local/share/julius/actions.jsonl` **(v2.2)** — uma linha por gravação automática (campo, antes, depois, comando de desfazer), pelo mesmo `infra/ai_log.py`; lida por `ai_log.tail` em `produtos revisar --ultimas-acoes`.

**Regras de dependência (o que faz a DAG valer)** — codificadas em `tests/test_architecture.py`, que inspeciona os imports de todo módulo e falha em qualquer atalho:

| camada | pode importar |
|---|---|
| `config`, `domain` | nada de `julius` |
| `infra` | `domain`, `config` |
| `parsers`, `repositories` | `domain` |
| `services` | `domain`, `config`, `infra`, `parsers`, `repositories` |
| `cli` | `domain`, `config`, `infra`, `parsers`, `services` (é o composition root: instancia o parser concreto e o cliente de LLM e os passa aos serviços) |
| `bot` | `domain`, `config`, `infra`, `services` (o outro composition root, irmão de `cli`: sem `parsers` — não lê recibo — e sem `repositories`; nada importa `bot`) |

**Onde há `Protocol` e onde não há — decisão consciente, não uniformidade.** `ReceiptParser` (segundo estado é evolução prevista) e `LlmClient` (teste de serviço substitui a rede por fake). Nada mais: repositórios são funções que recebem `conn` — o `conn` de um SQLite em `tmp_path` já é a "injeção"; serviços são funções; a CLI é consumidora, não provedora. Interface pra implementação única é manutenção sem retorno.

**Agregados (DDD sem cerimônia):** **Store** (cnpj) · **Product** (id; possui SKUs, tags, conteúdo) · **Price** (registro imutável, chave `access_key+item_index`) · **AiUsage** (mês). Deliberadamente não existem ABCs de repositório, value-object pra CNPJ (`digits_only` + checagem de tamanho basta) nem event bus.

**Assinaturas dos casos de uso** (`services/`, todas recebem `conn: sqlite3.Connection` como primeiro argumento):

- `importing.import_receipt(conn, path: Path, parser: ReceiptParser) -> ImportResult` — **um arquivo por chamada**: parseia o arquivo inteiro antes de gravar qualquer coisa, grava numa transação, resolve `product_id` via `(store_cnpj, product_code)` (reaproveita se já existe, cria se não). `ImportResult(new_items, existing_items)`. Quem itera sobre vários arquivos (e reporta por arquivo, seguindo em frente se um falhar) é a CLI.
- `search.search_prices(conn, term: str | None = None, tag: str | None = None, limit: int = 20) -> list[PriceRecord]` — `term` casa por similaridade (`rapidfuzz`) contra `products.canonical_name`, não `LIKE`; `tag` filtra por `product_tags`. `PriceRecord.highlight` (`"lowest"`/`"highest"`/`None`) é calculado **por unidade** aqui — a regra "nunca mistura UN com KG" vive neste serviço, não no repositório nem na CLI. `price_per_content` preenchido só quando o produto tem conteúdo definido.
- `export.export_csv(conn, destination: Path) -> int` — nº de linhas escritas.
- `catalog.list_stores(conn) -> list[Store]` · `catalog.rename_store(conn, cnpj, nickname) -> None`
- `catalog.list_products(conn) -> list[Product]` · `catalog.rename_product(conn, product_id, name) -> None`
- `catalog.merge_products(conn, source_id, target_id) -> None` — reatribui `product_skus`/`prices` e apaga `source_id`, numa transação
- `catalog.tag_product(conn, product_id, tag) -> None` — cria a tag se não existir
- `catalog.set_product_content(conn, product_id, quantity, raw_unit) -> None` — aceita `L/ML/KG/G/UN`, grava `L/KG/UN` via `normalize_content`
- `catalog.compare_products(conn, config, client, id_a, id_b) -> ProductComparison` — `text_similarity` via `rapidfuzz` sempre; `ai_suggestion` só se `suggestions.is_available`
- `suggestions.*` — ver "Camada opcional de IA".

**Mapa de nomes (design antigo, em português → identificador real, em inglês).** As seções escritas antes da convenção ainda usam o vocabulário da esquerda em prosa; o código usa o da direita.

| antigo | real |
|---|---|
| `mercados` (`razao_social`, `apelido`) | `stores` (`legal_name`, `nickname`) |
| `produtos` (`nome_canonico`, `conteudo_qtd`, `conteudo_unidade`) | `products` (`canonical_name`, `content_quantity`, `content_unit`) |
| `produto_skus` (`cnpj`, `produto_codigo`, `produto_id`) | `product_skus` (`store_cnpj`, `product_code`, `product_id`) |
| `tags.nome` · `produto_tags` | `tags.name` · `product_tags` |
| `precos` (`chave_acesso`, `item_indice`, `data_hora_compra`, `produto_descricao`, `quantidade`, `unidade`, `valor_unitario`, `valor_total`) | `prices` (`access_key`, `item_index`, `purchased_at`, `description`, `quantity`, `unit`, `unit_price`, `total_price`) |
| `ia_uso` (`mes`, `gasto_usd`) | `ai_usage` (`month`, `spent_usd`) |
| `Mercado` · `Produto` · `RegistroNota` · `PrecoEncontrado` · `ImportResultado(novos, existentes)` | `Store` · `Product` · `ReceiptItem` (+ `Receipt` agregando a nota) · `PriceRecord` · `ImportResult(new_items, existing_items)` |
| `SugestaoFusao` · `SugestaoConteudo` · `ComparacaoProduto` · `destaque "menor"/"maior"` | `MergeSuggestion` · `ContentSuggestion` · `ProductComparison` · `highlight "lowest"/"highest"` |
| `MAPA_UNIDADE` · `ErroUnidadeDesconhecida` · `parsear` | `UNIT_MAP` · `UnknownUnitError` · `parse` |
| `importar` · `consultar` · `exportar_csv` | `import_receipts` · `search_prices` · `export_csv` |
| `listar_mercados` · `renomear_mercado` · `listar_produtos` · `renomear_produto` | `list_stores` · `rename_store` · `list_products` · `rename_product` |
| `fundir_produtos` · `marcar_tag` · `definir_conteudo` · `comparar_produtos` | `merge_products` · `tag_product` · `set_product_content` · `compare_products` |
| `disponivel` · `sugerir_fusao` | `is_available` · `suggest_merge` (v1; virou `suggest_merges` em lote na v2, ver "Camada opcional de IA") |
| `JULIUS_IA_*` · `precos.db` | `JULIUS_AI_*` (ver "Camada opcional de IA") · `prices.db` |

Path do banco: `Config.db_path` — variável de ambiente `JULIUS_DB`, default `~/.local/share/julius/prices.db` (`Path.home()`, stdlib puro — sem `platformdirs`, já que o alvo é só Linux). Sem flag `--db` em cada comando: é ferramenta de um usuário só, com um banco só; variável de ambiente já cobre testar em outro caminho se precisar.

### CLI — comando `julius` (Typer)

(nome escolhido pelo usuário: referência ao pai do Chris, em *Todo Mundo Odeia o Chris* — o cara que nunca deixa passar um preço.)

```
julius importar [ARQUIVO...]
julius consultar [PALAVRA...] [--tag TAG] [--sem-tag] [--limite/-n INT = 20]
julius exportar [--saida/-o PATH = ./julius-export.csv]
julius mercados listar
julius mercados renomear CNPJ APELIDO
julius mercados comparar
julius mercados revisar
julius produtos listar
julius produtos renomear ID NOME
julius produtos fundir ORIGEM DESTINO
julius produtos desfundir ID
julius produtos tag ID TAG [--remover]
julius produtos tipo ID [TIPO] [--remover]
julius produtos definir-conteudo ID [QTD UNIDADE] [--remover]
julius produtos comparar ID_A ID_B
julius produtos revisar [--sim] [--ultimas-acoes]   # --sim: não perguntar nada
```

`julius-bot` **(v2.6)** é um executável separado, não um subcomando: não aceita argumento nenhum, lê tudo de variável de ambiente e fica em long polling até Ctrl+C. Ver o parágrafo da v2.6 e `docs/como-testar-o-bot.md`.

Nomes de comando em português (são UI); cada um mapeia pra uma função em inglês em `julius/cli/*.py` via `@app.command("importar")`. Os três grupos (`julius`, `julius mercados`, `julius produtos`) usam `no_args_is_help=True`: digitar o grupo sozinho lista os comandos em vez de imprimir a caixa vermelha "Missing command." — o código de saída continua 2, porque nenhum comando rodou. Todo comando abre a conexão com `infra.db.connect(config.load().db_path)` **dentro do handler** — nunca em import. Um comando só é registrado quando o serviço que ele chama existe (sem stub `NotImplementedError` exposto).

- **`julius importar ARQUIVO...`** — um ou mais arquivos HTML (variádico, de graça no Typer — resolve "import em lote" sem código extra). Chama `services.importing.import_receipts` por arquivo (uma transação cada; falha num não afeta os outros), imprime "N itens novos, M já existiam" por arquivo. Arquivo inexistente/HTML fora do formato/unidade desconhecida → erro claro, nada gravado.
- **`julius consultar [PALAVRA...] [--tag TAG] [--sem-tag]`** — `PALAVRA...` aceita várias palavras sem aspas (`list[str]` no Typer, mesmo mecanismo de `importar ARQUIVO...`) e casa por similaridade (`rapidfuzz`) contra nome de produto **e** contra tag (v2.1): uma palavra que bate uma tag conhecida (`TAG_MATCH_CUTOFF = 75`, `services/search.py::detect_tag`) vira filtro, intersectado com o resto como termo — `julius consultar hortifruti` e `julius consultar leite laticinio` já funcionam sem `--tag`. Interseção vazia refaz a busca como termo puro antes de desistir (`services.search.search_free_text`). `--tag` explícito continua existindo e pula a detecção, sem mudança de comportamento; `--sem-tag` força o mesmo caminho quando a detecção atrapalha (ex.: o nome do produto coincide com uma categoria). Pelo menos uma palavra ou `--tag` é obrigatório. `--limite/-n` limita linhas por grupo de unidade (default 20). Renderiza com `rich.table.Table`: uma tabela por `unit` (nunca mistura UN com KG), colunas data/valor/apelido (+ preço por conteúdo quando existir), `highlight` colorido. Sem match → mensagem explícita, não tabela vazia. Toda chamada grava uma linha em `~/.local/share/julius/query_log.jsonl` (`Config.query_log_path`, mesmo `infra/ai_log.py::append` do log de IA) — palavras digitadas, tag explícita/detectada, termo e tag usados de fato, nº de resultados, se caiu no fallback de IA.
- **`julius exportar`** — `--saida/-o` escolhe o caminho do CSV (default no diretório atual). Chama `services.export.export_csv`. Não é a fonte da verdade, só um dump legível/pra planilha.
- **`julius mercados listar`** — `catalog.list_stores`, tabela `cnpj / razão social / apelido`.
- **`julius mercados renomear CNPJ APELIDO`** — `catalog.rename_store`. É a correção que se repete (todo mercado novo nasce com apelido = razão social), por isso ganhou comando — diferente da correção de uma linha de preço errada, que continua sem comando dedicado (ver seção Decisões).
- **`julius produtos listar`** — `catalog.list_products`, tabela `id / nome / tags`. Ajuda a achar o `ID` pra usar em `renomear`/`fundir`/`tag`.
- **`julius produtos renomear ID NOME`** — `catalog.rename_product`. Pro nome automático (= descrição do primeiro import) não ficar feio pra sempre.
- **`julius produtos fundir ORIGEM DESTINO`** — `catalog.merge_products`. **Desde a v2.4 não é destrutivo e não pede confirmação**: grava a relação, imprime o comando de desfazer e nada é apagado. O aviso de "irreversível" saiu porque deixou de ser verdade.
- **`julius produtos desfundir ID`** (v2.4) — `catalog.unmerge_product`, recebendo o id do produto **absorvido** (simétrico com `fundir`). É o comando que autoriza a revisão a fundir sozinha; existe **antes** da automação, de propósito.
- **`julius produtos tag ID TAG`** — `catalog.tag_product`. Categorização manual (ex.: `limpeza`, `hortifruti`); não tem relação com a busca por texto, é outro mecanismo.
- **`julius produtos definir-conteudo ID QTD UNIDADE`** — `catalog.set_product_content`. Ver seção "Preço por conteúdo". Sem esse comando, `consultar` mostra só o preço cru — nunca adivinha o conteúdo pela descrição.
- **`julius produtos tipo ID [TIPO] [--remover]`** (v2.2) — `catalog.set_product_kind`/`clear_product_kind`. Define ou remove o grupo de comparação. É o comando de desfazer que autoriza a IA a gravar tipo sozinha; existe **antes** da automação de propósito.
- **`julius produtos definir-conteudo ID --remover`** (v2.2) — `catalog.clear_product_content`, pelo mesmo motivo.
- **`julius produtos revisar --ultimas-acoes`** (v2.2) — lê o fim de `actions.jsonl` (`ai_log.tail`) e imprime a tabela `Quando · ID · Campo · Antes · Depois · Desfazer`. Não chama IA, não aplica nada. É a metade "detalhe sob demanda" do resumo agregado que a revisão imprime.
- **`julius mercados comparar`** (v2.2) — `comparison.compare_stores`. Uma tabela por grupo (mercado · preço · data, mais barato em verde), depois a contagem derivada ("mais barato em 3 de 3 grupos", contando só os grupos em que aquela loja aparece) e sempre o rodapé com número de grupos e intervalo de datas. O aviso do rodapé sobre período largo é medido, não defensivo: as notas de lojas diferentes estão a até 12 dias de distância, então parte da diferença pode ser o mês, não a loja. Sem grupo comparável, mensagem explícita em vez de tabela vazia.
- **`julius importar` sem argumento** (v2.2) — varre `entrada/*.html` (não recursivo, então `entrada/importados/` fica invisível: é isso que faz o comando significar "importe o que é novo") e arquiva cada nota importada com sucesso. A ordem dentro do comando é obrigatória: importar → revisar (é onde o tipo é atribuído) → sinal de extremos → dicas. Invertida, o sinal roda com `kind IS NULL` em todo produto novo e perde a comparação entre lojas.
- **`julius produtos comparar ID_A ID_B`** — `catalog.compare_products`. Pede uma opinião (IA se configurada, senão `rapidfuzz`) sobre se dois produtos são a mesma coisa — só informa, quem funde é `julius produtos fundir`, comando separado. Único ponto do sistema com custo de IA opt-in por chamada explícita do usuário (ver seção "Camada opcional de IA").

### Empacotamento

`pyproject.toml` com `[project.scripts] julius = "julius.cli:app"` — depois de `.venv/bin/pip install -e '.[dev]'`, o comando `.venv/bin/julius` fica disponível sem `python -m` nem caminho de script. Dependências: `typer`, `rich`, `rapidfuzz`; dev: `pytest`. `infra/llm_client.py` não adiciona dependência — chamada HTTP via `urllib.request` da stdlib. `[tool.setuptools.package-data]` inclui os `.sql` (ver "Migração de schema").

### Dicas de uso (`guidance`) — v1.1, estendida em v2

**Motivação (caso real):** `julius consultar banana` num banco recém-criado respondia `Nenhum resultado.` — verdadeiro e inútil. O usuário não tinha como saber que o problema era "nada foi importado ainda". Pedido explícito: quando algo dá vazio ou errado, o CLI **diagnostica o que aconteceu e sugere o próximo comando**, pronto pra copiar. Isso é um módulo, não um punhado de `if`s espalhados pela CLI.

**Princípios (não negociáveis dentro do módulo):**
1. **Dica é dado, não texto.** `services/guidance.py` devolve `Hint(kind, details)`; `cli/_hints.py` traduz `kind` → frase em português com o comando sugerido. Mesma separação de sempre: serviço diagnostica olhando o banco, CLI escreve.
2. **Só três gatilhos:** resultado vazio, erro, ou situação de primeira vez. Nunca em saída normal cheia — dica em cima de resultado bom vira ruído e o usuário aprende a ignorar. Máximo **2 dicas por comando**.
3. **Sem memória de "já mostrei".** A limitação natural já evita repetição: dica de embalagem só pra produtos *novos* daquele import; dica de apelido só enquanto houver loja com `nickname == legal_name`. Nada de tabela `hints_shown` (YAGNI).
4. **Nunca muda exit code, nunca pergunta, nunca executa.** Só imprime, em estilo discreto (`dim`), prefixo `Dica:`. Em erro, vai pra `stderr` junto do erro; em resultado vazio, `stdout`.
5. **Sem IA.** Diagnóstico é determinístico: estado do banco + tipo da exceção + padrão de texto. IA continua só em `produtos comparar`.

**Catálogo v1.1 de `HintKind`** (todos ancorados em problema observado ou em decisão já tomada no design):

| kind | gatilho | `details` | frase (CLI) |
|---|---|---|---|
| `NO_RECEIPTS_IMPORTED` | `consultar` com banco sem nenhuma loja | — | Nenhum recibo importado ainda. Comece com: `julius importar ARQUIVO.html` |
| `NO_MATCH_DID_YOU_MEAN` | `consultar TERMO` vazio, mas `search.closest_names` acha nomes que a busca não casou e têm uma palavra com `fuzz.ratio >= NEAR_MISS_CUTOFF` (70) contra o termo | até 3 nomes | Nenhum produto bate com esse nome. Parecidos: A, B, C |
| `NO_MATCH_TRY_TAGS` | `consultar TERMO` vazio e sem parecidos | até 5 tags existentes (pode ser vazio) | Busca é por nome, não por categoria. Pra agrupar (ex.: "carne"): `julius produtos tag ID carne` e `julius consultar --tag carne`. Tags que já existem: … |
| `UNKNOWN_TAG` | `consultar --tag X` e a tag não existe | tags existentes | Não existe a tag "X". Tags atuais: …. Crie com `julius produtos tag ID X` |
| `FIRST_IMPORT_NAME_STORES` | `importar` com sucesso e alguma loja ainda com `nickname == legal_name` | quantidade | N mercado(s) ainda com a razão social como nome. Dê apelidos: `julius mercados listar` → `julius mercados renomear CNPJ "Apelido"` |
| `PACKAGE_SIZE_IN_DESCRIPTION` | `importar` criou produto novo cuja descrição casa `C/\d+` ou `\d+(,\d+)?\s?(ML\|L\|G\|KG)\b` | até 3 `"id · nome"` + total | Estes produtos parecem ter tamanho na descrição; pra comparar por litro/kg/unidade: `julius produtos definir-conteudo ID QTD UNIDADE` |
| `IMPORT_FILE_NOT_FOUND` | `FileNotFoundError` | caminho | Arquivo não encontrado. Se usou `*.html`, nenhum arquivo casou com o padrão nessa pasta |
| `IMPORT_NOT_A_RECEIPT` | `ReceiptParseError` ou `UnicodeDecodeError` (PDF/binário no meio dos HTMLs) | nome do arquivo | Não parece a página de NFC-e da Receita/DF salva como HTML (PDF e `.har` não servem). Abra o link do QR code no navegador e "Salvar página como…" |
| `IMPORT_UNKNOWN_UNIT` | `UnknownUnitError` | código bruto | Código de unidade novo. Adicione uma linha em `UNIT_MAP` (`julius/domain/normalization.py`) — o import inteiro desse arquivo foi ignorado, nada gravado |
| `AI_NOT_CONFIGURED` | `produtos comparar`/`revisar` sem `Config.ai_configured` | — | Pra ter a opinião da IA, defina `JULIUS_AI_API_KEY`, `JULIUS_AI_BASE_URL`, `JULIUS_AI_MODEL` e os dois preços por token (ver README) |
| `SAME_CHAIN_BRANCHES` **(v2)** | `importar` com ≥2 lojas do mesmo `cnpj[:8]` e alguma ainda sem apelido | até 3 `"cnpj — endereço"` | Filiais da mesma rede: …. Dê apelidos que digam onde fica: `julius mercados renomear CNPJ "Rede — Bairro"` |
| `PRODUCTS_PENDING_REVIEW` **(v2)** | `importar` com produto novo sem tag e `reviewed=False` | quantidade | N produto(s) novo(s) sem categoria. Nome legível, categoria e conteúdo com ajuda da IA: `julius produtos revisar` |
| `FOUND_VIA_AI` **(v2)** | `consultar` achou produto só pelo fallback de IA (`match_products`) | até 3 `"id · nome"` + total | Encontrado pela IA, não pelo nome: …. Pra achar direto na próxima, renomeie ou marque: `julius produtos renomear ID "Nome"` / `julius produtos tag ID TAG` |

Isso **fecha a questão em aberto nº 3** ("dica via `C/<n>`"): vira `PACKAGE_SIZE_IN_DESCRIPTION` pra quem não usa IA, e é coberta por `enrich_products` (via `produtos revisar`) pra quem usa — ver "Camada opcional de IA".

**Contratos:**
- `domain/models.py`: `HintKind = Literal[...]` (13 hoje, os 10 de v1.1 + os 3 de v2 acima) e `Hint(kind: HintKind, details: tuple[str, ...] = ())`. `ImportResult` ganha `new_product_ids: tuple[int, ...] = ()` (quem cria produto novo é `importing`; sem isso a dica de embalagem não sabe o que é novo).
- `services/search.py`: `closest_names(conn, term, limit=3) -> list[tuple[str, int]]` — nomes que `search_prices` **não** casaria (score < `MATCH_SCORE_CUTOFF`) mas cuja melhor palavra tem `fuzz.ratio >= NEAR_MISS_CUTOFF` (70) contra o termo, ordenados por score desc. **Mudou em relação ao design original (faixa WRatio 45–70) por medição nos 5 recibos reais**: WRatio de termo curto contra nome longo bate no piso 45–60 pra qualquer entrada (`xyzabc` → 45 contra "CHA LEAO RELAXA…", `leite` → 67,5 contra "PAO ZINHO … BAGUETE") enquanto o erro real `pikana` → PICANHA fica em 65,5 — a faixa era só ruído e `NO_MATCH_TRY_TAGS` nunca dispararia. Palavra a palavra separa: `pikana` → PICANHA 77 e `arros` → ARR 75 entram; `frango`, `carne`, `sabao`, `feijao` ficam abaixo de 70. Falso positivo conhecido (nesta constante, `NEAR_MISS_CUTOFF`): `queijo` → QUERO 73. Números no docstring da constante. **O falso positivo `carne` vs `PAO DE ALHO PRADELLA 400G PICANTE` (72, registrado em v2) era artefato do `WRatio` e morreu com ele em v2.3.1** — hoje `carne` e `carnes` pontuam 0 os dois, e os testes que usam `carnes` pro fallback de IA passaram a valer pela razão certa. Com o scorer palavra a palavra, **para termo de uma palavra** as duas constantes viraram a mesma comparação: "parecido" é simplesmente a faixa logo abaixo do match, 70–80 (sem o bônus de prefixo). Para termo multi-palavra elas divergem — `_matching_ids` quebra o termo em palavras, `closest_names` compara o termo inteiro contra cada palavra do nome — então `NO_MATCH_DID_YOU_MEAN` só dispara com termo de uma palavra. Limitação pré-existente, mantida: unificar exigiria medir a faixa de novo sem evidência de que o caso incomoda. Não confundir com o `queijo`/`QUERO` acima, que continua vivo em `NEAR_MISS_CUTOFF`. **(v2)** `records_for_products(conn, product_ids, limit)` foi extraído de `search_prices` (o highlight/trim por unidade), pra o fallback de IA reaproveitar depois de resolver ids; `catalog_for_matching(conn)` devolve `(id, nome, tags)` pro prompt de `match_products`.
- `services/guidance.py` (só funções puras sobre `conn`/valores; nunca lança — dica que falha é dica que não aparece):
  - `after_search(conn, term, tag, records) -> list[Hint]`
  - `after_import(conn, result: ImportResult, *, reviewed: bool = False) -> list[Hint]` — **(v2)** `reviewed=True` (produtos revisados por `produtos revisar`/`importar`) suprime `PRODUCTS_PENDING_REVIEW` e `PACKAGE_SIZE_IN_DESCRIPTION`, já cobertos pela tela de revisão. Ordem: `PRODUCTS_PENDING_REVIEW` → `SAME_CHAIN_BRANCHES` → `FIRST_IMPORT_NAME_STORES` → `PACKAGE_SIZE_IN_DESCRIPTION`, cortando em `MAX_HINTS`.
  - `for_import_error(error: Exception, path: Path) -> list[Hint]`
  - `for_compare(config: Config) -> list[Hint]`
  - `after_ai_fallback(records) -> list[Hint]` **(v2)** — `[Hint("FOUND_VIA_AI", ...)]` se `records` não é vazio, senão `[]`. Continua sem IA nenhuma aqui dentro (princípio 5): quem chamou a IA e achou os `records` foi a CLI, este módulo só descreve o resultado.
  - Todas cortam em `MAX_HINTS = 2`.
- `cli/_hints.py`: `TEXTS: dict[HintKind, str]` (templates com `{details}`) e `print_hints(hints, *, to_stderr=False)`. Um teste garante que **todo** `HintKind` tem texto — esquecer um vira falha de teste, não frase em branco. **Separador de `{details}` mudou de `", "` pra `" · "` em v2** (endereços têm vírgula, ficaria ambíguo com o separador antigo).
- A checagem ad hoc `has_imports` que vivia em `cli/receipts.py` sumiu: virou `NO_RECEIPTS_IMPORTED` pelo caminho normal. Em `importar` com vários arquivos, `after_import` roda **uma vez no fim** sobre os resultados somados (não por arquivo), pra respeitar o máximo de 2 dicas por comando; as dicas de erro saem por arquivo, em `stderr`.

**Fora do escopo v1.1 (ainda de fora em v2, exceto onde marcado):** dicas em saída cheia, "não mostrar de novo", dicas geradas por IA (o texto continua determinístico; só o *dado* que alimenta `FOUND_VIA_AI` vem de uma busca que usou IA), tutorial interativo, telemetria de uso.

### Fora do escopo v1/v2/v2.2/v2.3 (de propósito)
Detecção automática de estado, comando de correção para linhas de preço (usa `sqlite3` direto), veredito automático de preço, lock de concorrência, flag `--db` por comando, `platformdirs`, **fusão automática de produtos** (nem por texto nem pela IA — `judge_duplicates` só imprime o `fundir` pronto, quem roda é o usuário), **busca semântica/embeddings** (v1, suposição; medido e reconfirmado em 2026-09-22 — dois modelos multilíngues testados contra os casos reais da sessão, nenhum supera a IA já em produção; ver "Identidade de produto e busca"), **auto-classificação de tags sem confirmação** (a primeira categoria **conhecida** é aplicada automaticamente desde a v2.3, mas isso é *aplicar a sugestão da IA*, não *classificar sem a IA*; candidata fora do vocabulário nunca é aplicada e o produto volta para a fila), **classificar código de unidade novo via IA** (evento raro, curadoria manual do mapa já resolve, não vale o custo), **cache de respostas de IA** (o caminho durável é corrigir o dado — renomear/marcar tag — não lembrar a resposta antiga), **fallback entre provedores de IA**, **`julius ia status`** (`tail -n 5 ai_calls.jsonl` e `SELECT * FROM ai_usage` já cobrem), **comando de analytics sobre `query_log.jsonl`** (v2.1 — `jq`/`Counter` do usuário sobre o arquivo já respondem "quais buscas falham"/"o que mais consulto", mesma lógica de não criar `julius ia status`), **tag multi-palavra na detecção de texto livre** (v2.1 — nenhuma das 13 tags semeadas precisa disso hoje), **fusão automática de produto em qualquer confiança** (v2.2 — rejeitada por medição, não por cautela: 19 pares acima do corte, no máximo 2 defensáveis, pior falso positivo `Alho` ↔ `Pão de Alho` com confiança 1,00; ver "Identidade de produto e busca"), **índice único de carestia por mercado** (v2.2 — a resposta é contagem por grupo com `n` e período, nunca uma média de razões entre grupos de preços muito diferentes), **qualquer estatística de dia da semana** (v2.2 — as 6 notas reais caem em 6 dias diferentes, zero repetição; a coluna "Dia" mostra o dado e cala), **`consultar --tipo`** (v2.2 — `rapidfuzz` já acha o grupo quando o termo é o próprio tipo), **corte fuzzy pra snapping de tipo** (v2.2 — terceiro cutoff a medir sem evidência de que o problema existe), **comando de analytics sobre `actions.jsonl`** (v2.2 — `--ultimas-acoes` já é a leitura; o resto é `jq`), **gravar conteúdo vindo de intuição de varejo sem confirmação** (v2.3 — medido: `Filme PVC 30m x 28cm` → `30 UN`; erro de conteúdo é o único que não aparece na saída normal, vira um R$/UN plausível), **score de confiança da IA como gatilho de qualquer coisa** (v2.3 — falhou três vezes; o gatilho é a recusa), **mandar ao prompt só os campos faltantes** (v2.3 — a passada inteira custa US$ 0,01; a economia não paga a complexidade), **limite numérico de sanidade nos candidatos de conteúdo** (v2.3 — seria constante nova sem medição; a supressão por `form == "weight"` resolve o caso observado), **corte de confiança para fusão** (v2.4 — os acertos vieram com 0,70/0,80 e o falso positivo com 1,00; qualquer corte inverte o sinal), **filtro de fusão por tipo igual** (v2.4 — 12 dos 19 candidatos têm tipo igual, incluindo `Água c/gás ≈ s/gás` e `Pepsi ≈ Guaraná`; `kind` agrupa alternativas de compra, o oposto de fusão), **reatribuir `prices.product_id` numa fusão** (v2.4 — destruiria a reversibilidade; `reassign_product` foi removida para o atalho não existir), **densidade por produto** para comparar massa com volume (v2.4 — zero casos medidos), **idade relativa em horas** (v2.5.1 — seria uma quarta granularidade a medir; ação automática é sempre recente e a hora já basta), **vão em dias no rodapé do `mercados comparar`** (v2.5.1 — a idade por linha já responde "quanto tempo faz"; o rodapé descreve um intervalo, e intervalo em linguagem relativa lê mal), **`--formato-data`/locale** (v2.5.1 — `strftime("%x")` depende de `LC_TIME` e quebraria em silêncio noutra máquina; é ferramenta de um usuário só, com uma preferência só), **contagem "2×" nas linhas colapsadas do `consultar`** (v2.4 — quantidade comprada é controle de gasto, que este sistema declaradamente não é). Da v2.6: **webhook e qualquer servidor HTTP** (long polling num PC doméstico não precisa de porta aberta nem de IP fixo), **`concurrent_updates`** (com um usuário, o processamento sequencial é o que garante que texto e toque não corram entre si), **persistir a pendência entre reinícios** (reiniciar perde, e o toque encontra "não está mais ativa"), **responder a quem está fora da allowlist**, **foto/QR/áudio** (pipelines diferentes, ver "Evolução futura"), **duas ações numa mensagem** (o run termina na primeira; o bot avisa que a segunda vem na próxima), **dicas (`guidance`) no bot** (os textos vivem em `cli/_hints.py`; trazê-los exigiria movê-los para `domain` como os formatadores), **escrita do bot em `actions.jsonl`** (é pedido do usuário mais confirmação, como a CLI — o log é das gravações automáticas) e **`Deferred Tools` no lugar de *output functions*** (o §4.3 do design ficou marcado para veto e não foi vetado; as ações encerram o run, o resultado não volta ao modelo, e é isso que garante uma chamada de modelo por mensagem).

## Design de testes

Framework: **pytest** (mesma lógica do Typer — código pronto em vez de escrever mais, `unittest` da stdlib exige mais boilerplate pra fixture/parametrização). Fixtures: os **3 arquivos HTML reais** em `tests/fixtures/` (`qrcode.html`, `qrcode-2.html`, `qrcode-3.html`) + **1 fixture sintético** pro caso de embalagem (não existe nos dados reais, ver seção "Preço por conteúdo"; ainda por criar). Nenhum teste bate na internet — tudo roda em cima de arquivo local + SQLite em `tmp_path` (fixtures `db_path`/`conn` em `tests/conftest.py`).

**Regra que a v2.2 tornou obrigatória, e vale para teste e para a mão:** `julius importar` **move** o arquivo que leu (arquivamento), então nunca aponte o comando para `tests/fixtures/` — os fixtures somem da árvore de trabalho (só voltam com `git checkout -- tests/fixtures/`, e voltariam mesmo, porque são versionados). Vale para teste automatizado e para checagem manual: qualquer verificação manual de `importar` copia o fixture para uma pasta temporária antes. `tests/conftest.py` tem `copied_fixtures`/`restore_fixture`: cada teste de CLI importa uma cópia em `tmp_path`.

**Já existentes e verdes:** `test_normalization.py`, `test_config.py`, `test_db.py` (schema, FKs, CHECK, PK, backup+migração), `test_architecture.py` (regras da DAG), `test_cli.py` (`--help`, sem efeito colateral em import). **As tabelas abaixo** usam o vocabulário antigo em português (`core.importar`, `mercados`, `ImportResultado(novos=...)`); leia pelo mapa de nomes em "Estrutura de pacote" — ex.: `core.importar` → `services.importing.import_receipts`, `ImportResultado(novos=20, existentes=0)` → `ImportResult(new_items=20, existing_items=0)`, `precos` → `prices`.

### Inventário dos 3 fixtures reais (valores que os testes fixam)

| | `qrcode.html` | `qrcode-2.html` | `qrcode-3.html` |
|---|---|---|---|
| Mercado | FL 3 COSTA MULTICANAL S A | COMERCIAL DE ALIMENTOS HTP LTDA | DONA DE CASA S/A |
| CNPJ | 27289076001379 | 20209736000181 | 11832478000285 |
| Itens (linhas) | 20 | 1 | 6 |
| `(cnpj, produto_codigo)` distintos | 15 (14578 e 32124 e 26948 repetem) | 1 | 5 (30487 repete) |
| `data_hora_compra` (de Emissão) | 2026-09-12T13:09:16 | 2026-09-05T16:50:34 | 2026-09-07T18:18:30 |
| Formato de `unidade` no HTML | `UN1` / `KG1` | `KG` (sem sufixo) | `UN` / `KG` (sem sufixo) |
| Casas decimais de quantidade | 4 (`1.0000`, `0.5780`) | 3 (`1.532`) | 4 (`1.0000`, `0.8800`) |

Importando os 3 juntos: 3 `mercados`, 27 linhas em `precos` (20+1+6), 21 `produtos` (15+1+5, sem colisão porque `cnpj` difere entre arquivos mesmo quando o número do código coincidiria).

### 1. Testes do parser (`parsers/df.py`) — unitários, sem banco

| Caso | Entrada | Esperado |
|---|---|---|
| Contagem de itens | cada um dos 3 fixtures | lista com 20 / 1 / 6 registros — bate com "Qtd. total de itens" do próprio HTML |
| Âncora por `(Cód:` | os 3 fixtures | blocos de "Qtd. total de itens", "Valor a pagar", "Forma de pagamento", "Tributos" (também `li.list-group-item`) **não** viram itens |
| Item repetido vira linhas distintas | `qrcode.html` cód. 14578 (3x), `qrcode-3.html` cód. 30487 (2x) | `item_indice` diferente por ocorrência, nenhuma soma/merge |
| Normalização de unidade — com sufixo | `qrcode.html`: `UN1`, `KG1` | normaliza pra `"UN"`, `"KG"` |
| Normalização de unidade — sem sufixo | `qrcode-2.html`/`qrcode-3.html`: `UN`, `KG` | normaliza pra `"UN"`, `"KG"` (idempotente — mesmo resultado com ou sem sufixo) |
| Separador decimal não vaza entre campos | qualquer linha (ex.: `Qtde.: 1.532` + `Vl. Unit.: 53,99` na mesma `qrcode-2.html`) | `quantidade == 1.532` (não `1532` nem `1.532` virando `1.532,99`) — pega especificamente o bug de um `replace(",", ".")` ingênuo na linha inteira |
| Quantidade com precisão variável | `1.0000` (4 casas) e `1.532` (3 casas) | ambos parseiam como float correto, sem exigir largura fixa |
| `data_hora_compra` vem da Emissão, não da Consulta | os 3 fixtures | valor bate com a tabela acima, nunca com "Data/Hora da Consulta" do rodapé |
| CNPJ só dígitos | `27.289.076/0013-79` no cabeçalho | vira `"27289076001379"`, 14 caracteres |
| Chave de acesso só dígitos, consistente | chave com espaços no corpo vs. chave da URL do botão "Visualizar NFC-e Detalhada" | as duas batem depois de tirar espaço, 44 dígitos |
| Nota com item único | `qrcode-2.html` | lista com exatamente 1 registro, não quebra assumindo múltiplos |
| DOM de extensão ignorado | os 3 fixtures (todos têm `plasmo-csui` injetado) | nenhum item espúrio vem de dentro do bloco injetado |
| Campo não usado não quebra o parser | `qrcode-2.html` (Consumidor com CPF) vs. `qrcode.html`/`qrcode-3.html` ("não identificado") | parser não tenta extrair Consumidor — não faz parte do contrato de saída, sucesso nos dois formatos |

### 2. Testes de import/dedup (`core.importar`) — com SQLite em `tmp_path`

| Caso | Ação | Esperado |
|---|---|---|
| Import simples | importar `qrcode.html` | `ImportResultado(novos=20, existentes=0)`; `mercados` com 1 linha; `produtos` com 15 linhas |
| Reimport idempotente | importar `qrcode.html` de novo | `ImportResultado(novos=0, existentes=20)`; `precos` continua com 20 linhas (sem duplicar) |
| Import em lote (múltiplos arquivos) | `importar([qrcode.html, qrcode-2.html, qrcode-3.html])` | 3 `mercados`, 27 linhas em `precos`, 21 `produtos` |
| Apelido não é sobrescrito | importar `qrcode.html`, editar apelido manualmente, reimportar o mesmo arquivo | `apelido` continua o editado, não volta pra razão social |
| FK protege contra preço órfão | inserir direto em `precos` um `cnpj` que não existe em `mercados` | `sqlite3.IntegrityError` |
| Falha no parse não grava nada parcial | HTML sem nenhum marcador `(Cód:` (arquivo inválido/vazio) | erro claro; `precos`/`mercados` sem nenhuma linha nova |

### 3. Testes de busca e identidade (`core.consultar`, `core.fundir_produtos`, `core.marcar_tag`)

| Caso | Ação | Esperado |
|---|---|---|
| Termo exato | `consultar("picanha")` (após importar `qrcode.html`) | retorna as 3 linhas do código 26948, agrupadas em `unidade = "KG"` |
| Erro de digitação | `consultar("pcanha")` (faltando um "i") | ainda retorna as linhas de picanha via `rapidfuzz` |
| Nunca mistura unidade | `consultar` em qualquer termo com resultados em UN e KG | duas listas/grupos separados, nunca um `min`/`max` comparando os dois |
| **Nunca funde automaticamente** | `consultar("tomate")` após importar `qrcode.html` + `qrcode-3.html` | retorna **dois** `produto_id` diferentes (cód. 22039 "FL 3 Costa" e cód. 7147 "Dona de Casa") — não vira um grupo só sem ação manual |
| Fusão manual funciona | `fundir_produtos(id_22039, id_7147)`, depois `consultar("tomate")` | as duas linhas de preço aparecem sob o mesmo `produto_id`, `produtos` com uma linha a menos |
| Tag filtra, texto não | `marcar_tag(id_cebola, "hortifruti")`, `marcar_tag(id_tomate, "hortifruti")`, depois `consultar(tag="hortifruti")` | retorna cebola + tomate; `consultar("hortifruti")` (texto) não retorna nada, porque tag e busca textual são mecanismos diferentes |

### 4. Testes de preço por conteúdo (`core.definir_conteudo`) — fixture sintético, não os 3 reais

| Caso | Ação | Esperado |
|---|---|---|
| Sem conteúdo definido | `consultar` em qualquer produto recém-importado | sem coluna de preço-por-conteúdo — nunca adivinha |
| Normalização de unidade de entrada | `definir_conteudo(id, 500, "G")` | grava `conteudo_qtd=0.5, conteudo_unidade="KG"` |
| **Caso do usuário: pacote maior pode ser mais barato por unidade** — fixture sintético: "OVOS 20UN" R$12,00 (produto A) e "OVOS 30UN" R$16,50 (produto B) | `definir_conteudo(A, 20, "UN")`, `definir_conteudo(B, 30, "UN")`, depois `consultar("ovos")` | preço por conteúdo: A = R$0,60/un, B = R$0,55/un — B aparece como mais barato por unidade **mesmo custando mais no total**, provando que comparar só o preço cru dá a resposta errada aqui |
| Achado real (sem flip) — registrado pra não reaparecer como "bug" | `REFRI PEPSI PET 2L` R$6,99 (→R$3,50/L) vs. `REFRI ANT GUARANA PET 1.5L` R$4,99 (→R$3,33/L), com conteúdo definido | Guaraná vence nas duas métricas nos dados reais — não existe inversão de ranking nesse par específico, só no fixture sintético dos ovos |

## Estrutura do repositório — código separado de dado

**Pedido explícito do usuário**: ele vai continuar baixando HTMLs de recibos (e o que vem junto) numa pasta própria — isso não pode ficar misturado com o código.

```
precos-dos-mercados/                  # repo git — só código
├── .gitignore
├── .venv/                           # ignorado; criado por python3 -m venv .venv
├── pyproject.toml
├── CLAUDE.md
├── docs/tickets/julius-v1/          # tickets de implementação, um por nó da DAG
├── julius/                          # ver árvore completa em "Estrutura de pacote"
│   ├── config.py
│   ├── domain/  infra/  parsers/  repositories/  services/  cli/
└── tests/
    ├── conftest.py                  # fixtures db_path / conn (SQLite em tmp_path)
    ├── fixtures/                    # só o .html — nunca a pasta *_files/ que vem junto
    │   ├── qrcode.html · qrcode-2.html · qrcode-3.html
    │   └── synthetic_eggs.html      # (ticket) fixture sintético, ver "Design de testes" item 4
    ├── test_architecture.py  test_cli.py  test_config.py  test_db.py  test_normalization.py
    └── test_parser_df.py  test_repositories_*.py  test_services_*.py   (tickets)
```

**Fixture leva só o `.html`, nunca a pasta `*_files/` que o navegador salva junto.** O parser lê texto de HTML, não a página renderizada — `qrcode_files/` é CSS, jQuery, logo SVG e fonte, peso morto que não faz o teste passar nem falhar. Copiar "a página inteira salva" por reflexo arrastaria isso pra dentro do repo à toa.

**Dado do usuário mora fora do repo, nunca versionado** — mesma área XDG já decidida pro banco:
```
~/.local/share/julius/
├── prices.db        # Config.db_path (JULIUS_DB)
├── ai_calls.jsonl · query_log.jsonl · actions.jsonl
└── entrada/          # pasta de entrada; `entrada` na raiz do repo é um symlink pra cá (make inbox)
    └── importados/   # notas já importadas, renomeadas <data>_<chave>.html
```
Não existe (nem precisa existir) uma variável tipo `JULIUS_ENTRADA` ou flag `--pasta`: `Config.inbox_path`/`archive_path` derivam de `JULIUS_DB` de graça.

**O symlink é o que dissolveu a fricção (v2.2).** O pedido original era "uma pasta no repo, porque `~/.local/share/julius/entrada` é fundo demais pra achar". `make inbox` cria `entrada -> ~/.local/share/julius/entrada`: o Ctrl+S do navegador cai em `precos-dos-mercados/entrada/` e o arquivo **já está** fisicamente no lugar canônico — não existe passo de mover, nem a pergunta "mover antes ou depois de ler". `/entrada` está no `.gitignore`. Depois de importar, a nota vai pra `entrada/importados/` (renomear é obrigatório: o navegador salva toda nota como `qrcode.html`, um destino plano colidiria no segundo import). Arquivo que falhou fica onde está.

**A pasta `_files/` que vem junto do Ctrl+S ainda não é apagada.** `infra/receipt_files.py::discard_sidecar` existe e está testada (nome derivado exato, precisa ser diretório real, nunca symlink), mas **não é chamada** — apagar é a única operação destrutiva do sistema e está pendente de decisão do usuário. Ligar é uma linha em `cli/receipts.py::_archive`, onde há um comentário marcando o lugar.

**`.gitignore`** (raiz do repo):
```
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
build/
dist/
.venv/
*.db
/*.html
/*.pdf
/*.har
```
Os três últimos padrões são **ancorados na raiz** (`/` no início, sem `**`) de propósito — ignoram HTML/PDF/HAR perdido na raiz do repo (hábito de salvar ali por engano) sem afetar `tests/fixtures/*.html`, que são commitados. Um `*.html` sem âncora, adicionado por reflexo no futuro, pararia de rastrear os fixtures silenciosamente e quebraria a suíte de testes pra quem clonar o repo.

**Nota pra depois, não decisão agora**: `qrcode-4.html` e `qrcode-5.html` (as notas com `Gf`/`PC`/case misto de unidade) são o fixture natural pro teste de regressão do mapa de unidade quando essa pendência for fechada — não expandir a tabela de testes agora, só não jogar esses dois arquivos fora antes de decidir isso.

## Status da limpeza dos arquivos atuais (já executada)

Feito: `qrcode.html`, `qrcode-2.html`, `qrcode-3.html` movidos pra `tests/fixtures/`. `qrcode-4.html`, `qrcode-5.html`, as 5 pastas `qrcode*_files/`, o PDF e o `.har` movidos (não apagados) pra `~/.local/share/julius/entrada/`. Repo com `git init`, `.gitignore` e `pyproject.toml` criados na mesma sessão — ver "Estrutura de pacote" pro estado atual do código.
