# Design: da correção pontual pra arquitetura de resolução de entidade — três frentes

> A partir de `docs/requirements/entity-resolution-architecture.md` (`/sc:brainstorm`, 2026-09-22) e de `claudedocs/research_entity_resolution_lexical_matching_scaling_20260922.md`. A Frente A pedia medição antes de decisão (RNF1) — medi de verdade nesta sessão, e o resultado inverteu a hipótese mais óbvia da pesquisa.

## Achado que decide metade deste design: embeddings, medidos de verdade, perdem pra IA neste catálogo

A pesquisa (`research_...md`) apontava embeddings como alternativa forte, com precedente de indústria (SBERT, 98% de acurácia em correspondência de produto). Testei isso contra o catálogo real, não contra o dataset de outra empresa — instalei `fastembed` (leve, ONNX, sem `torch`) e dois modelos multilíngues (`paraphrase-multilingual-MiniLM-L12-v2`, 220MB, e `paraphrase-multilingual-mpnet-base-v2`, 1GB) e comparei contra os casos reais desta sessão.

**Nível de palavra** (o mesmo nível que `_name_score` já usa): o modelo pequeno não separou os falsos positivos dos matches necessários por nenhum corte de cosseno —

| par | tipo | cosseno |
|---|---|---|
| ARROS/ARROZ | precisa bater | 0.928 |
| REFRI/REFRIGERANTE | precisa bater | 0.948 |
| PIKANA/PICANHA | precisa bater | 0.870 |
| PCANHA/PICANHA | precisa bater | 0.855 |
| **TOMATEE/TOMATE** | **precisa bater** | **0.766** |
| **SUCO/SUINCO** | **falso positivo** | **0.818** |
| PAO/PO | falso positivo (aceito) | 0.749 |
| QUEIJO/PAO DE QUEIJO | falso positivo | 0.690 |
| PICANHA/PINHA | falso positivo | 0.556 |
| PEPSI/PRESIDENT | falso positivo | 0.342 |

Qualquer corte que mantenha TOMATEE/TOMATE (0.766) também mantém SUCO/SUINCO (0.818) como match — o mesmo formato de falha que motivou trocar `WRatio` por `_name_score` em v2.3.1, só que agora em embeddings.

**Nível de nome de produto inteiro** (o uso normal de um "sentence transformer", não palavra solta) foi pior, não melhor: pedindo "picanha" contra os 133 nomes de produto reais, **o produto Picanha nem aparece no top 5** dos dois modelos — o pequeno devolve Pimenta biquinho/Cebola/Queijo parmesão/Limão/Queijo brie; o grande devolve Leite condensado/Queijo parmesão/Creme de ricota/**Pinha**/Pão de Alho. "pepsi" e "suco" também falham por completo nos dois modelos — nenhum Refrigerante Pepsi nem nenhum dos 3 sucos reais aparece no top 5. "queijo" foi a exceção que funcionou bem (top 5 são todos queijos de verdade, incluindo por que "pão de queijo" fica de fora) — mas 1 acerto em 4 termos-chave não sustenta trocar a arquitetura.

**Por que isso não é surpresa, em retrospecto**: estes modelos são treinados em paráfrase/similaridade de frase em texto geral (Wikipédia, web), sem exposição real a nomenclatura de cupom fiscal brasileiro nem a marcas de mercearia (`Pinha`, `Mandaka`, `Piracanjuba`). O sucesso de SBERT na literatura (98% no PriceRunner) vem de **milhões de pares rotulados do próprio domínio de e-commerce** pra ajustar o modelo — não existe isso pra um catálogo pessoal de 133 produtos. A IA (DeepSeek), por outro lado, tem conhecimento de mundo amplo o suficiente pra saber que "pepsi é refrigerante" e "suco é suco de fruta" sem nenhum ajuste — e isso já foi comprovado ao vivo, duas vezes, nas sessões anteriores (`kind_candidates`, vocabulário no prompt).

**Decisão da Frente A: não adotar embeddings.** Não é "embeddings nunca funcionam" — é que, medido, não funcionam *aqui*, com os modelos e o esforço proporcionais a um projeto pessoal. Ajustar um modelo pro domínio exigiria dados rotulados que não existem e um esforço de ML desproporcional ao problema (exatamente o motivo que o próprio `CLAUDE.md` já usava pra recusar busca semântica desde 2026-09). A camada semântica que resolve isto continua sendo **a IA que já está no loop**, aprofundada onde ainda falta, não uma peça de infraestrutura nova.

---

## Frente A (revisada): aprofundar IA-como-resolvedor, sem tocar no caminho de alta frequência

### O que já existe e fica exatamente como está

- `match_kind`/`kind_candidates`/`_match_kind_via_product` (kind resolution para `check_price`/`compare_stores`) — já usa fallback por nome de produto e, quando isso falha, `ModelRetry` pra perguntar. **Baixa frequência** (só quando a pessoa confere um preço ao vivo ou compara mercados) — cabe IA.
- `known_kinds`/`kind_vocabulary` no prompt de roteamento — já dá à IA a grafia exata dos tipos conhecidos antes mesmo de tentar resolver por texto.
- `matching_product_ids`/`search_prices` (busca de histórico) — **alta frequência** (toda pergunta de preço passa por aqui). Isto é deliberadamente **sem** IA por padrão, e a Frente A não muda essa regra — `docs/design/kind-resolution-in-routing.md` já mediu que o vocabulário de `kind` cabe no prompt porque cresce devagar; o vocabulário de *produto* (o que `matching_product_ids` usa) cresce junto com o catálogo e nunca deveria ir pro prompt de toda mensagem.
- `suggestions.match_products` — fallback de IA já existe para `search_prices`, mas só quando a busca determinística **não acha nada**. "Picanha"/"Pinha" nunca teria disparado esse fallback, porque a busca achou coisa demais, não de menos.

### O gap real, e por que a resposta não é "IA em toda busca"

`matching_product_ids` não tem nenhum fallback de IA para o caso "achou algo, mas um dos itens é coincidência" — só o `WORD_LENGTH_GAP_LIMIT` (guarda determinística, já corrigiu picanha/pinha) e o guard geral de comprimento. Colocar IA em toda chamada de `search_prices` violaria a regra já estabelecida do projeto ("IA só em ponto de baixa frequência, nunca no caminho de leitura corriqueiro") — `consultar`/busca de preço é literalmente o caminho mais usado do sistema.

**RF1 (revisado) — o guard determinístico continua sendo a primeira e principal linha de defesa pra `matching_product_ids`, e isso é uma decisão consciente, não uma lacuna.** Uma nova colisão medida (como picanha/pinha) vira um guard novo do mesmo formato — comprimento de palavra, prefixo, etc. — nunca uma lista de exceção por par. A diferença entre isto e o que o usuário temia ("bugfix que só aumenta") é que cada guard, aqui, é uma *regra medida contra o catálogo inteiro* (a varredura de 383 palavras já é reaproveitável), não um remendo pontual — e a taxa de incidência medida é baixa: **1 falso positivo novo em ~150+ termos testados nas duas rodadas de monkey test**, não uma enxurrada.

**RF2 — a única extensão real que vale medir e construir: dar à busca de produto o mesmo escape que `kind` já tem, mas só quando o resultado parece plural/heterogêneo demais pra ser confiável.** Concretamente: quando `search_prices` devolve resultados que abrangem **produtos de `kind` diferentes e sem tag em comum**, isso já é sinal de que a correspondência lexical pode ter juntado coisas que não deveriam estar juntas (é exatamente a assinatura de picanha+pinha: carnes + hortifruti na mesma resposta). Ao detectar essa assinatura, oferecer via texto/persona "isso inclui X e Y, que são coisas diferentes — quer só uma delas?" em vez de silenciosamente misturar — reaproveitando `ModelRetry`/pergunta de esclarecimento (Frente C), não uma chamada de IA nova.

### Atualização (2026-09-22, sessão seguinte): RF2 corrigida contra o catálogo real — sinal melhor achado, mas a precondição continua não satisfeita

`claudedocs/research_typesafe_entity_resolution_fit_20260922.md` mediu o Jev contra os casos desta trilha e apontou um encaixe possível (verificação de um shortlist pequeno já produzido pelo `rapidfuzz`). Antes de aceitar esse encaixe, medi a própria condição de gatilho da RF2 ("kind diferente e sem tag em comum") contra o catálogo real, porque ela nunca tinha sido testada contra um caso que já funciona hoje — e depois, a pedido do `advisor`, varri o catálogo inteiro em vez de confiar em 3 termos escolhidos a dedo.

**Primeiro achado: a condição literal da RF2 regride uma busca legítima.** `"leite"` (4 produtos: `leite uht`/bebidas, `leite condensado`/mercearia, `creme de leite`×2/laticinios) é heterogêneo por kind e por tag — três tags diferentes, nenhuma maioria — e é exatamente o tipo de busca comum, hoje correta, que a sessão anterior já tratou via rótulo de contexto na narração (`_search_narration_context`), não via pergunta. Kind/tag heterogêneo, sozinho, não distingue "resultado plural legítimo" de "coincidência lexical" — falta o dado que outro guard deste mesmo módulo já usa: o `_name_score` que `matching_product_ids` já calcula e descarta (devolve só o `set[int]`, não o placar).

**Segundo achado, medido item a item:** os 4 produtos de `"leite"` batem **100.0** (palavra inteira) nos três. Já `"vinho"` (3 produtos) tem 2 em 100.0 e **"Pão Zinho" em exatamente 80.0** — o corte. `"queijo"` (9 produtos) tem 8 em 100.0 e **"Requeijão" em exatamente 80.0**. O próprio docstring de `MATCH_SCORE_CUTOFF` (`services/search.py:16-33`) já documentava os dois como "o preço da tolerância a erro de digitação" — só nunca tinha virado um gatilho de verificação. Isso separa exatamente o que kind/tag não separava: nenhum item de `"leite"` fica perto do corte.

**Terceiro passo (correção pedida pelo `advisor` antes de eu declarar isto pronto): varredura completa, não amostra de 3 termos.** Rodei `_name_score` de cada uma das 383 palavras que aparecem em algum nome de produto contra os 133 produtos, e separado de cada um dos 44 nomes de `kind`/tag reais (termos de mais de uma palavra) contra o mesmo catálogo — reaproveitando exatamente o método do sweep de `WORD_LENGTH_GAP_LIMIT` já citado nesta trilha. Script em `/tmp` desta sessão, reproduzível.

| universo testado | termos com 1+ item em exatamente 80.0 ao lado de 1+ item em 100.0 |
|---|---|
| 383 palavras de nome de produto (busca de 1 palavra) | **41 (10,7%)** |
| 44 nomes de `kind`/tag (busca de frase real, 2+ palavras) | **0** |

**A varredura de frase (a pergunta específica do `advisor` sobre o regime multi-palavra) veio limpa: nenhum nome de `kind` ou tag real produz o padrão.** `_name_score` é um `min` sobre as palavras do termo, e isso já filtra coincidência de uma palavra só quando o termo tem mais de uma — o problema fica restrito a busca de palavra única, pelo menos neste catálogo.

**Da varredura de 41 palavras, boa parte não é um termo de busca realista**: 8 são token de quantidade solto (`100ML`, `15G`, `30M`, `500ML`, `50G`, `5G`, `750ML`, `900ML` — o formato de `_QUANTITY_TOKEN`, que já existe pra outro fim neste módulo; ninguém digita "500ml" sozinho como busca) e mais 3 são conectivo isolado (`DO`, `EM`, `SEM` — o mesmo formato de `CONNECTIVE_WORDS`). Descontando essas 11 mecanicamente (via as próprias constantes citadas, não por olho), sobram 30 candidatas; inspecionei manualmente as que pareciam nome de produto genérico e não marca/sufixo — `queijo`, `vinho`, `suco`, `pepsi`, `pao`/`po`, `manga`, `parmesao`, `coral`, `creme`/`cream`, entre outras (essa filtragem final foi minha classificação, não uma regra reprodutível). Em nenhuma das que inspecionei o item em 80.0 era uma correspondência legítima (`suco`→"Presunto Suinco", `pepsi`→"Cream cheese President", `manga`→"Queijo mussarela **Manda**ka", `parmesao`→"Azeitona verde **Prames**a", `coral`→"Mamão **Formosa**" — nenhuma antes registrada como incidente, todas achadas agora pela varredura) — mas isso é "nenhum falso alarme nos casos que olhei", não "100% medido", porque a filtragem em si não é uma regra que outra pessoa possa rodar de novo sem repetir o julgamento. A varredura também mostrou que o corte binário "exatamente 80" é curto: `"forma"` tem "Mamão Formosa" em 83,3 (não 80,0), a mesma coincidência de substring, só que o `fuzz.ratio` real não caiu bem no corte. Um sinal de produção precisaria de uma margem (ex. "mais de N pontos abaixo do máximo do grupo"), não um `== 80` exato — isso não foi medido aqui, fica para quando isto virar ticket.

**Limite honesto da varredura**: ela só testa palavras que já existem em algum nome de produto — não cobre abreviação que o catálogo nunca escreve por extenso, como `"refri"` (o próprio docstring documenta `"refri"` → `"Resfriada"` como falso positivo aceito, e ele não aparece na minha lista de 383 porque "REFRI" não é uma palavra de nenhum nome real). A varredura mede o que existe no catálogo, não todo termo que uma pessoa poderia digitar.

**RF2 revisada — dois formatos de falso positivo, só um deles é candidato a construir:**

1. **Coincidência de tolerância a erro de digitação** (item bem abaixo do máximo do grupo, hoje medido como `== MATCH_SCORE_CUTOFF`, na prática uma faixa) — vinho/Pão Zinho, queijo/Requeijão, suco/Presunto Suinco, pepsi/Cream cheese, manga/Mandaka, parmesão/Pramesa, coral/Formosa, e (histórico, não remedido porque já foi corrigido por outro mecanismo) picanha/Pinha antes do `WORD_LENGTH_GAP_LIMIT`. Sinal barato, determinístico, já calculado por `matching_product_ids`; só precisa deixar de descartar o placar.
2. **Deriva semântica de nome composto** (a palavra do termo aparece inteira dentro de um nome que é um produto diferente — queijo/"Pão de queijo", 100.0, bate a palavra inteira, não é coincidência de digitação). Mesma classe de ambiguidade que `match_kind` já resolveu via empate→pergunta, mas nunca observada como incidente próprio no caminho de `search_prices`. Fora de escopo desta revisão.

**Precondição da RF2 original ("segundo caso medido do formato picanha/pinha"): continua não satisfeita, agora com um número em vez de uma suposição.** Nenhuma das coincidências achadas pela varredura foi reportada como dano real a um usuário — é exatamente o mesmo status que este documento já dava a vinho/Pão Zinho antes desta rodada ("aceito, sem evidência de caso real"), só que agora com a taxa medida contra o catálogo inteiro: **41 de 383 palavras (10,7%)** produzem o padrão bruto; descontando mecanicamente os 8 tokens de quantidade e os 3 conectivos isolados (formato de `_QUANTITY_TOKEN`/`CONNECTIVE_WORDS`, não meu julgamento), sobram **30 de 372 (8,1%)**; e **0 de 44 frases reais de `kind`/tag**. Isso é uma informação melhor pra decidir, não uma decisão tomada — a taxa é baixa o bastante pra ser defensável não construir, e a pessoa que decide é quem vai conviver com a pergunta extra em até 1 em cada 12 buscas de palavra única, não quem mediu.

**O Jev, medido contra este resultado, parece desnecessário — não só caro.** A pesquisa anterior (`research_typesafe_entity_resolution_fit_20260922.md`) cogitava o Jev como segunda opinião pra decidir se o item em 80 pertence ao grupo. Mas nas ~20 palavras que inspecionei manualmente dentro das 30 candidatas (as que reconheço como nome de produto genérico, não marca/sufixo) **nenhum item em 80 ao lado de itens em 100 era uma correspondência legítima** — isso é "nenhum falso alarme nos casos que olhei", uma amostra inspecionada por mim, não uma regra reproduzível nem uma medição de 100% de precisão. Ainda assim, não apareceu nenhum contraexemplo, e não há ambiguidade residual óbvia pro Jev resolver: o gap de score (100 vs ~80) já é o sinal. Chamar uma IA externa pra confirmar o que o próprio placar, que o sistema já calcula de graça, já sugere violaria a RNF2 desta trilha (`matching_product_ids` sem IA no caminho comum) sem ganho medido — e evita de saída o risco de overconfiança do Jev em pergunta aberta que a outra pesquisa mediu. Se um caso real algum dia mostrar o placar sozinho enganado (um item legítimo com gap de score parecido com o de uma coincidência), aí sim cabe reabrir o Jev como segunda opinião — não antes.

**Onde isto viveria no código, se construído**: `matching_product_ids` (`services/search.py:484`) devolve `set[int]` hoje — descarta o placar na linha 486. Um sinal de heterogeneidade precisaria de uma função irmã que devolva `dict[int, float]` (ou o `search_prices`/`consultar` calculando o placar de novo sobre o resultado, evitando duplicar `matching_product_ids`). A decisão de perguntar tem que morar em `services/search.py`/`consultar`, não na camada de persona (`bot/turn.py`) — o dano é na tabela bruta que a pessoa lê, existe com ou sem `deps.client`, igual ao resto desta trilha (RNF2). E o corte precisaria virar margem (`"forma"`/83,3 mostrou que `== 80` exato é curto), calibração ainda não feita.

**Recomendação, não implementada aqui**: a taxa está medida (30/372 candidatas mecânicas, ~8,1%; 0/44 frases), nenhum falso alarme apareceu na amostra que inspecionei, e nenhuma IA nova parece necessária — mas nenhum incidente real de dano ainda apareceu. Construir ou não é decisão da pessoa, com o número em mãos; se decidir construir, o formato é `ModelRetry` direto no gap de score (Frente C), sem Jev. RF2 formato 2 (deriva semântica, queijo/pão de queijo em `search_prices`) continua sem caso medido nesse caminho específico — não implementar sem incidente real.

### Implementado (2026-09-22, a pedido explícito do usuário — não é o incidente medido decidindo, é a pessoa decidindo com a taxa em mãos)

RF2 formato 1: `suspicious_match_ids` (`services/search.py`) reaproveita o placar que `matching_product_ids` já calculava e descartava — expõe os ids cujo `_name_score` fica abaixo de 100 (não é hit de palavra inteira/prefixo) desde que outro id do mesmo termo bata exatamente 100 (a âncora confiante). Corte por "< 100" em vez de "== `MATCH_SCORE_CUTOFF`" de propósito: a varredura já tinha achado `"forma"` → "Mamão Formosa" em 83,3, não 80,0 — um corte exato teria deixado esse formato de coincidência passar. `_reject_suspicious_match` (`bot/actions.py`) levanta `ModelRetry` só quando a busca é por termo livre (`outcome.tag is None`, RF1: busca por tag nunca é suspeita) e quando o resultado final de fato mistura um id confiante com um suspeito — nunca filtra sozinho, sempre pergunta, mesmo padrão de `_resolve_kind`/`resolve_product`.

Validado contra o banco de produção real (leitura, sem escrita): `vinho`, `queijo` e `suco` pedem esclarecimento (Pão Zinho, Requeijão, Presunto Suinco, exatamente os casos desta medição); `leite` passa direto, sem pergunta. 6 testes novos (3 em `test_services_search.py`, 3 em `test_bot_actions_read.py`), suíte completa em 1189 verdes (era 1183). RF2 formato 2 continua fora de escopo, sem caso medido.

### Requisitos não funcionais confirmados pela medição

**RNF1 (fechado)** — número medido, publicado acima: embeddings não vencem nem no nível de palavra nem no de frase, com um modelo pequeno (220MB) nem um médio (1GB). Não revisitar sem uma mudança de escala real (catálogo crescendo ordens de grandeza, o mesmo gatilho que o projeto já usa) **e** dados rotulados do próprio domínio pra ajustar um modelo — nenhuma das duas condições existe hoje.

**RNF2 (fechado)** — `matching_product_ids` continua sem IA no caminho comum; `match_kind` continua sendo o único ponto de IA-como-resolvedor, e cresce (RF2) só na direção "detectar heterogeneidade suspeita", não "chamar IA sempre".

---

## Frente B: memória de conversa — um fix quase de graça, não o estado persistido que 3 rodadas adiaram

### Achado que muda o design em relação ao requisito

O requisito (RF4-RF6) supunha que fechar o "grounding gap" precisaria de estado novo — a mesma peça de infraestrutura que v2.10/v2.11/v2.13 e `shopping-list-conversation-context.md` já adiaram por falta de caso medido. Olhando o mecanismo existente de perto, **não precisa**: o bug não é falta de memória, é a *política de rotação* de `bot/turn.py::handle_text` jogar fora exatamente o turno que a pessoa às vezes pergunta sobre.

```python
# hoje (bot/turn.py)
state.runs.append(result.new_messages())
del state.runs[:-HISTORY_TURNS]   # guarda só os ÚLTIMOS HISTORY_TURNS turnos
```

Com `HISTORY_TURNS = 3` e 5 perguntas seguidas (banana, cebola, tomate, uva, "qual foi a primeira?"), o turno da banana já saiu da janela quando a 5ª pergunta chega — o modelo não hallucina por acaso, ele literalmente não tem a informação, e por isso reforçar o prompt (tentado na sessão passada, `BOT_PROMPT_VERSION` 5) não mudou nada: não é falta de instrução, é falta de dado, exatamente o que a pesquisa de "grounding gap" documentou.

### Decisão: fixar o primeiro turno na janela, sem aumentar o tamanho da janela

```python
def _trim_history(runs: list[list[ModelMessage]]) -> list[list[ModelMessage]]:
    """Mantém o primeiro turno da conversa para sempre, e desliza os últimos HISTORY_TURNS-1 --
    em vez de só "os últimos N", sem custo de token adicional (mesmo N de sempre, escolha
    diferente de QUAIS turnos). Fecha o achado real de 2026-09-22: perguntado "o que eu perguntei
    primeiro" na 5ª mensagem, o modelo afirmou "cebola" (a borda da janela antiga) em vez de
    "banana" (o turno 1, real) -- reforçar o prompt não mudou isso (testado ao vivo, mesma
    resposta errada) porque o problema nunca foi o modelo não seguir a instrução, foi o turno 1
    não estar mais em lugar nenhum que ele pudesse consultar."""
    if len(runs) <= HISTORY_TURNS:
        return runs
    return runs[:1] + runs[-(HISTORY_TURNS - 1):]
```

Testado (simulação de índices, sem custo de IA): com `HISTORY_TURNS=3`, a sequência banana→cebola→tomate→uva→"primeira?" resulta em `[banana, uva, "primeira?"]` no momento da 5ª pergunta — cebola e tomate saem, banana fica. Isso é suficiente pra fechar o incidente exato medido, sem inventar nenhuma tabela nova, TTL novo ou coluna no banco — é uma mudança de 3 linhas na política de corte que já existe.

**Limite explícito, coerente com RF5 do requisito ("escopo mínimo, só o que já causou incidente"):** isto responde "o que eu perguntei primeiro", não "o que eu perguntei 7 mensagens atrás mas não a primeira" — esse caso mais geral continua sem resposta, e continua sendo exatamente a pendência mais ampla que `shopping-list-conversation-context.md` já registrou (RF6 daquele documento) e que segue precisando de estado explícito de verdade se algum dia virar incidente medido. Não fundir os dois agora: um se resolve de graça, o outro não, e forçar a mesma solução nos dois either atrasaria o fix barato ou construiria infraestrutura sem necessidade medida pra ele.

### Requisitos não funcionais

**RNF3 (RNF4 do requisito) — sem custo de token adicional.** O número de turnos enviados por chamada não muda (`HISTORY_TURNS` continua 3); só a seleção de quais 3 muda. Nenhuma medição de custo pendente.

**RNF4 (RNF5 do requisito) — não fecha a pendência mais ampla, só a reconhece.** `shopping-list-conversation-context.md` RF6 continua aberto; este design não o resolve nem o torna desnecessário, só evita que os dois sejam confundidos numa solução só.

---

## Frente C: formalizar a pergunta de esclarecimento — auditoria fechada, sem gap encontrado

### Auditoria dos dois candidatos do requisito (RF8)

**`detect_tag`** (`services/search.py`) — testado contra as 13 tags reais com singular/plural e erro de digitação (`temperos`, `limpeza`, `frios`, `doce`→`doces`, `bebida`→`bebidas`): todos resolvem para exatamente uma tag, sem empate. A função nem tem mecanismo de detectar empate (usa `process.extractOne`, que já devolve só o melhor) — não há ambiguidade observável no vocabulário atual de 13 tags pra expor. **Sem mudança — nada encontrado, RNF6 respeitado (não mexer sem evidência nova).**

**`resolve_store`** (`bot/actions.py`) — lido o código: **já pergunta**. `if len(matches) > 1: raise ModelRetry(...)` já existe, com a mesma forma que `resolve_product`/`_resolve_kind` usam. Este candidato já estava em conformidade com o padrão antes mesmo desta rodada. **Sem mudança.**

### RF7 — nomear o padrão (o único trabalho real desta frente)

Não há código pra escrever; há uma frase pra fixar em CLAUDE.md ou num comentário de topo de módulo, porque hoje o padrão existe em 3 lugares (`resolve_product`, `resolve_store`, `_resolve_kind`) sem nenhum lugar que diga que é *o mesmo padrão*, deliberado, não uma coincidência de 3 correções separadas:

> **Convenção**: toda resolução de entidade em `bot/actions.py` que encontra 2+ candidatos plausíveis, sem um vencedor claro (nem por match exato nem por unanimidade), levanta `ModelRetry` listando as opções — nunca escolhe sozinha. Isto é a peça de "desambiguação por sub-diálogo" que sistemas de diálogo orientados a tarefa usam há 30+ anos (ver `claudedocs/research_entity_resolution_lexical_matching_scaling_20260922.md`); uma resolução de entidade nova que não seguir isto é a exceção que precisa de justificativa, não o padrão.

**RF9 confirmado por construção**: como o padrão já é aplicado de forma consistente nos 3 pontos auditados, uma resolução de entidade *nova* que seguir o mesmo formato (chamar `ModelRetry` quando há candidatos, não decidir sozinha) já herda a garantia — não precisa de "lembrar" de aplicar o padrão, precisa só de copiar a forma que já existe.

---

## Contrato final (o que muda de código)

| frente | módulo | mudança |
|---|---|---|
| A | (nenhuma) | decisão registrada: não adotar embeddings; `matching_product_ids` continua sem IA no caminho comum |
| A | `services/search.py` + `bot/actions.py` | RF2 (revisada) formato 1: `suspicious_match_ids` + `_reject_suspicious_match`, `ModelRetry` direto, sem IA — **implementado** a pedido do usuário (ver "Implementado" abaixo); formato 2 (deriva semântica de nome composto) segue fora de escopo |
| B | `bot/turn.py` | `_trim_history` substitui `del state.runs[:-HISTORY_TURNS]` |
| C | `CLAUDE.md` ou topo de `bot/actions.py` | parágrafo nomeando a convenção (RF7); nenhuma auditoria pendente (RF8 fechado, nada encontrado) |

## Testes que a implementação precisa cobrir

- **Frente B**: reproduzir exatamente o caso medido (`FunctionModel`/`ScriptedLlmClient`, 5 turnos, "o que eu perguntei primeiro") e confirmar que `state.history` no 5º turno inclui as `ModelMessage`s do turno 1. Teste de unidade em `_trim_history` isolado (índices, sem IA) cobrindo: conversa curta (≤`HISTORY_TURNS`, sem corte), conversa longa (corte, turno 1 sempre presente), e que o turno imediatamente anterior nunca é perdido (garante que os loops de `quantity_needed`/`ambiguous_unit`/ambiguidade de `kind` não regridem).
- **Frente C**: nenhum teste novo — nada mudou em código; se quiser, um teste de documentação (`assert` que a frase da convenção existe em algum lugar) é opcional, não essencial.
- **Frente A**: nenhum teste novo — decisão de não implementar; a varredura de 383 palavras e a comparação de embeddings ficam registradas neste documento como a medição que sustenta a decisão, reproduzível se o catálogo mudar de escala.

## Rodada real pendente

Depois de implementar a Frente B: reproduzir ao vivo o roteiro banana→cebola→tomate→uva→"primeira?" contra o modelo de verdade (numa cópia do banco, nunca o real) e confirmar que a resposta cita banana. Sem isso, a mudança fica só testada em índice, não em comportamento real do modelo — mesma disciplina de toda mudança de prompt/histórico já feita neste projeto.

## Fora de escopo desta rodada (registrado, não decidido aqui)

- **Estado de conversa persistido de propósito geral** (a pendência de `shopping-list-conversation-context.md` RF4-RF6) — continua aberta, agora com um quarto motivo medido, mas ainda sem construção própria.
- **RF2 da Frente A, formato 1** (coincidência de digitação) — **implementado** (ver "Implementado" acima), a pedido do usuário, mesmo sem incidente de dano real medido.
- **RF2 da Frente A, formato 2** (deriva semântica de nome composto, ex. queijo/pão de queijo, no caminho de `search_prices`) — sem caso medido de dano real *nesse caminho específico*; não implementar sem incidente próprio, mesma disciplina de "nasce de um caso, cresce com o próximo".
- **Reavaliar embeddings** — só se o catálogo crescer ordens de grandeza *e* houver dados rotulados pra ajustar um modelo ao domínio; nenhuma das duas condições existe hoje.

## Próximo passo

`/sc:implement` da Frente B (o único código real desta rodada) e do parágrafo de convenção da Frente C. Frente A não gera código nesta rodada — a medição em si é o entregável.
