# Julius — fechamento do brainstorm: comparabilidade é o problema real

> Rodada final de `/sc:brainstorm` de 2026-09-16. Fecha as 18 perguntas em aberto dos três documentos anteriores desta mesma sessão (`receipt-inbox.md`, `import-price-signal.md`, `cross-store-price-comparison.md`, `auto-merge-clusters.md`) com medições no banco de produção real, e registra as 4 decisões que eram do usuário.
> **Este documento tem precedência sobre os quatro anteriores onde houver conflito** — em particular, `auto-merge-clusters.md` foi resolvido *contra* a proposta original (ver §3).
> Próximo passo: `/sc:design` → tickets em `docs/tickets/julius-v2/` (117+).

## 1. O problema real, redefinido

Todas as perguntas que o usuário fez ao longo da sessão — "paguei caro?", "esse mercado é mais caro?", "quarta é mais barato que sexta?", "me ajude a achar os melhores preços" — estavam sendo tratadas como perguntas diferentes, cada uma com sua feature. Não são. Todas travam na **mesma** coisa, e nenhuma trava em estatística ou em falta de feature:

> **Para opinar sobre um preço é preciso ter outro preço comparável. O sistema hoje quase nunca tem.**

Comparabilidade tem exatamente três ingredientes, e a medição diz qual falta:

| Ingrediente | Estado medido hoje | Falta? |
|---|---|---|
| **Mesma coisa agrupada** — duas linhas falam do mesmo tipo de produto | 2 produtos fundidos manualmente abrangem 2 lojas. Agrupando por tipo+unidade: **12 grupos** abrangem >1 loja | **Sim** — é o gargalo principal |
| **Mesma unidade** — nunca comparar R$/UN com R$/KG | Já garantido em `records_for_products` (agrupa por `unit`) | Não |
| **Mesmo tamanho de embalagem** — para item vendido por UN, o preço é da embalagem, não do conteúdo | **32 dos 79 produtos-UN sem `content`**; o import de hoje imprimiu 26 comandos `definir-conteudo` que não foram rodados | **Sim** |

Consequência direta: **a ordem de trabalho é comparabilidade primeiro, opinião depois.** Opinião sobre dado incomparável é o "ruído" que a decisão original de "sem veredito automático" previu — e continua certa até os dois ingredientes que faltam serem resolvidos.

## 2. O achado que decide o desenho: KG já compara, UN não

Agrupando os 105 produtos do banco real por tipo (proxy: primeira palavra do nome legível) + unidade, os 12 grupos que abrangem mais de uma loja se dividem de forma limpa:

**Grupos utilizáveis hoje — todos vendidos por KG:**

| Grupo | Observações | Resposta que já dá |
|---|---|---|
| `Cebola` [KG] | R$ 7,89 (FL 3 Costa, 12 e 16/09) · R$ 9,99 (Dona de Casa, 10/09) | FL 3 Costa mais barato |
| `Tomate` [KG] | R$ 11,89 (FL 3 Costa, 12 e 16/09) · R$ 14,99 (Dona de Casa, 07/09) | FL 3 Costa mais barato |
| `Banana` [KG] | R$ 3,79 (FL 3 Costa, 16/09) · R$ 5,99 (Assaí, 04/09) | FL 3 Costa mais barato |

**Grupos inutilizáveis hoje — todos vendidos por UN**, e por dois motivos diferentes que não devem ser confundidos:

| Grupo | Problema | O que resolve |
|---|---|---|
| `Agua` [UN] | junta 500ml (R$ 1,49) com 1,5L (R$ 3,69) | `content` — vira R$ 2,98/L vs R$ 2,46/L, comparável |
| `Tempero` [UN] | junta pacote de 5g (R$ 1,79) com frasco de 70g (R$ 6,99) | `content` — revela que o sachê é ~3,6× mais caro por grama |
| `Leite` [UN] | junta leite UHT 1L com leite **condensado** 395g | **`content` não resolve** — são produtos de tipos diferentes |
| `Pao` [UN] | junta pão de forma, pão de alho e pão de queijo | **`content` não resolve** — mesmo caso |

**Regra que sai disso, e é o eixo do desenho:**

1. Grupo vendido por **KG** é comparável na hora, sem mais nada.
2. Grupo vendido por **UN** só é comparável com `content` definido — por isso preencher conteúdo é a ação automática de maior valor disponível (32 pendentes, 26 já sugeridas e não aplicadas), não fundir produto.
3. `Leite`/`Pao` mostram o limite do agrupamento por texto: quando o grupo é heterogêneo **por tipo** (não por tamanho), nenhum cálculo salva — só um nome de grupo na granularidade certa. **É o argumento para a IA nomear o grupo**, em vez de derivá-lo da primeira palavra.

## 3. Por que fusão automática foi rejeitada (medição, não opinião)

`curation.duplicate_candidates(conn, product_ids=None)` nunca havia sido executado sobre o catálogo inteiro. Rodado nesta sessão sobre os 105 produtos reais: **19 pares acima do corte `DUPLICATE_CANDIDATE_CUTOFF = 75`**, dos quais no máximo 2 são defensáveis.

| Par real | Score | Veredito |
|---|---|---|
| `Alho` ↔ `Pão de Alho Pradella 400g Picante` | **1,00** | Falso positivo **na nota máxima** — alho e pão de alho |
| `Suco OQ integral 1,5L uva` ↔ `Suco Integral Parreiras do Sul GF 1,5L` | 0,93 | Marcas diferentes |
| `Água Crystal com gás` ↔ `Água Crystal sem gás` | 0,92 | Com/sem gás |
| `Tempero Coral Dry Rub` Beef ↔ Trad ↔ Chicken | 0,90 | Três sabores |
| `Picanha Bovina Fatiada` ↔ `Fraldinha Bovina` | 0,82 | Cortes diferentes |
| `Refrigerante Pepsi PET 2L` ↔ `Antarctica Guaraná PET 1,5L` | 0,78 | **O par exato que o design previu** |
| `Banana prata` ↔ `Banana Prata Extra União` | 1,00 | Verdadeiro positivo |

Dois fatos fecham a questão:

- **Nenhum corte de similaridade de texto é seguro**, porque o pior falso positivo do catálogo tira a nota máxima (1,00). Não é um problema de calibrar o número; é o sinal que não discrimina.
- **A confiança da IA não é rede de segurança auditável.** `MergeSuggestion.confidence` é um float que o modelo escreve sobre a própria resposta, sem nenhuma medição contra pares conhecidos no repositório — diferente de `MATCH_SCORE_CUTOFF`, `NEAR_MISS_CUTOFF`, `TAG_MATCH_CUTOFF` e `DUPLICATE_CANDIDATE_CUTOFF`, todos com docstring citando medição real. Dos 2 pares que a IA aprovou hoje, um (`fundir 71 49`, duas uvas em bandeja de 500g) tem os **dois preços idênticos em R$ 6,99** — se estivesse errado, a fusão teria *escondido* o erro em vez de mostrá-lo, e só apareceria quando os preços divergissem, já com os históricos misturados e sem desfazer.

E o bloqueio prático, já registrado em `auto-merge-clusters.md` F1: `merge_products` apaga a linha de origem (`catalog.py:45`), sem guardar quais SKUs migraram. O "desfazer" prometido no pedido original não existe.

**Decisão do usuário: agrupar sem fundir.** A IA atribui um tipo a cada produto; o grupo é quem compartilha tipo + unidade. Nada é apagado, desfazer é trocar o tipo. Isso entrega os 12 grupos (6× os 2 de hoje) sem construir infraestrutura de undo e sem reabrir a linha "a IA grava o reversível, nunca o irreversível". `julius produtos fundir` continua existindo, manual e raro, para identidade literal.

**Observação que reforça a escolha:** no nível de grupo, o "erro" da IA nas uvas deixa de ser erro. Um grupo `uva` **deve** conter uva branca e uva Green Dreams — e aí o usuário vê R$ 6,99 ao lado de R$ 14,99 pela mesma bandeja de 500g e decide, que é exatamente a filosofia original do projeto ("o usuário decide olhando a lista"). Fundir destruiria justamente a distinção que ele precisa ver.

## 4. Princípio geral: quando uma "ação inteligente" pode se aplicar sozinha

Fecha a pergunta ampla do usuário ("os hints agora começam a ser ações inteligentes") sem enumerar os 13 `HintKind`. Uma ação pode ser aplicada automaticamente **se e somente se** as duas condições valem:

1. **É reversível por um comando que já existe** — não por um que precisaria ser construído.
2. **Um erro é visível na saída normal** — aparece numa tabela que o usuário já olha, sem precisar auditar nada.

| Ação | (1) reversível | (2) erro visível | Automática? |
|---|---|---|---|
| Nome legível | `renomear` | sim, na coluna Produto | **Sim** (já é hoje) |
| Categoria (tag de corredor) | `tag --remover` | sim, ao filtrar | **Sim** (já é hoje) |
| Tipo/grupo de comparação | trocar o tipo | sim, o grupo errado aparece junto | **Sim** (novo) |
| Conteúdo de embalagem | `definir-conteudo` de novo | sim, na coluna "Por KG/L" | **Sim** (novo — hoje exige confirmação) |
| **Fundir produtos** | **não existe** | **não** — histórico misturado é invisível | **Não** |
| Apelido de mercado | `mercados renomear` | sim | **Não** — não há valor correto a calcular, é escolha humana |

A linha que separa é a (2): fusão falha porque o dano é agregado e silencioso. Apelido de mercado falha por outro motivo — não existe resposta certa que a máquina possa derivar.

## 5. As 18 perguntas, fechadas

### `receipt-inbox.md`

| Q | Resolução | Base |
|---|---|---|
| Q1 — nome/caminho da pasta de queda | **Symlink `entrada/` na raiz do repo apontando para `~/.local/share/julius/entrada/`**, criado por um alvo no `Makefile` (`ln -s`), gitignorado. Ctrl+S cai em `precos-dos-mercados/entrada/` e o arquivo já está fisicamente no lugar canônico. | Resolve a fricção relatada ("dir super nested") com uma linha e zero código |
| Q2 — mover antes de ler ou depois | **Dissolvida.** Com o symlink existe um só local físico; não há passo de mover. Só resta arquivar após sucesso. | Consequência de Q1 |
| Q3 — `julius importar` sem argumento | **Sim**, passa a varrer `entrada/*.html`. Combinado com o arquivamento, `julius importar` sem argumento significa "importe o que é novo" — o arquivado sai do caminho da varredura sozinho. | É o ganho de UX real; elimina o glob decorado |
| Q4 — onde arquivar | `entrada/importados/`, plano. **Nome do arquivo precisa ser reescrito** — o navegador salva sempre como `qrcode.html`, então um destino plano colide no segundo import. Usar data + chave de acesso (única, é a PK da nota): `2026-09-16_53260927…9308.html` | Colisão verificada: os dois arquivos desta sessão se chamam `qrcode.html` |
| Q5 — `_files/` | **Recomendação: apagar depois que o `.html` estiver arquivado com sucesso.** O princípio "arquivar, nunca apagar" protege a fonte *reparseável* — foi o que permitiu o backfill de endereço em v2. `_files/` é jQuery, CSS e um SVG de logo: não pode gerar campo novo nunca. É a única exceção proposta ao princípio; vetável. | `CLAUDE.md`, "Fixture leva só o `.html`" |

### `import-price-signal.md`

| Q | Resolução | Base |
|---|---|---|
| Q1 — linha por item ou agregado | **Linha por item que bateu extremo**, limitada a 5 com "+N mais". É naturalmente curto: hoje 2 de 46 itens tinham histórico. | Medição da nota de hoje |
| Q2 — `HintKind` novo ou saída própria | **Saída própria, fora de `guidance.py`.** Um novo mínimo é resultado, não dica — o princípio "nunca dica em saída normal cheia" fica intacto, sem exceção. | `CLAUDE.md`, "Dicas de uso", princípio 2 |
| Q3 — fixture sintético | **Necessário só para "novo máximo"**: nos dados reais cebola e tomate só caíram de preço, nunca subiram. Mínimo e "sem histórico" já têm caso real. | Séries reais dos produtos 5 e 63 |
| **Novo** — escopo da comparação | O sinal compara contra o **grupo**, não só contra o `product_id` — é o que a decisão de §3 força, e é o que torna o sinal capaz de dizer "mais barato que na outra loja". | Decisão do usuário |

### `cross-store-price-comparison.md`

| Q | Resolução | Base |
|---|---|---|
| Q1 — "praticamente igual" restrito a categorias? | **Não há lista de categorias permitidas.** A regra que substitui é a de §2: KG compara direto; UN exige `content`; heterogeneidade *por tipo* se resolve com o nome do grupo na granularidade certa, não com whitelist. | §2 |
| Q2 — comando novo, flag, ou parte de outro | `consultar` já agrupa e já marca mínimo/máximo através do grupo. O que é novo: a varredura que atribui tipo, e o comando de comparação entre mercados (Q3). Superfície exata é `/sc:design`. | `search.py:152-165` |
| Q3 — índice de mercado agora ou esperar | **Agora, com `n` e período explícitos.** Formato: por grupo, quem é mais barato; depois a contagem por loja ("mais barato em 3/3") — **nunca um número único de índice**, nunca média de razões. Sempre acompanhado do intervalo de datas. | Decisão do usuário |
| Q4 — gatilho do dia da semana | **Não é mais necessário.** Ver decisão abaixo. | Decisão do usuário |
| Q5 — custo de IA da varredura | **Medido: 19 pares** acima do corte (teto `MAX_DUPLICATE_PAIRS = 20`). Mas com agrupamento em vez de fusão, o custo relevante passa a ser o caminho de `enrich` (lotes de 25) para atribuir tipo aos 105 produtos: ~5 chamadas, uma vez. Irrelevante frente aos US$ 5/mês. | Execução real nesta sessão |

### `auto-merge-clusters.md`

| Q | Resolução | Base |
|---|---|---|
| Q1 — como tornar o merge reversível | **Dissolvida.** Fusão sai do caminho automático, então a infraestrutura de undo não precisa existir. RF1–RF6 daquele documento ficam **sem efeito**. | Decisão do usuário, §3 |
| Q2 — corte de confiança | **Dissolvida para fusão.** Para atribuição de tipo, reaproveita a regra que já existe em `curation.propose`: candidato único e confiante aplica; ambíguo pergunta ou fica pendente. Nenhum corte novo a calibrar. | `services/curation.py::propose` |
| Q3 — fusão ou agrupamento | **Agrupamento.** | Decisão do usuário |
| Q4 — "hints como ações" é amplo? | **Sim, com o teste de duas condições de §4** — reversível por comando existente **e** erro visível na saída normal. Fecha a pergunta sem enumerar os 13 `HintKind`. | §4 |
| Q5 — flag para desligar | **Não precisa de flag nova.** Desligar é não configurar `JULIUS_AI_*`, que já é como toda a camada de IA é opt-in; `--sim`/TTY já cobre o modo não interativo. | `config.py::ai_configured` |

## 6. Requisitos que saem deste fechamento

| # | Requisito |
|---|---|
| RF1 | Cada produto pertence a **no máximo um** grupo de comparação — é "que tipo de coisa isso é", não uma etiqueta livre. Um produto em dois grupos apareceria em duas comparações e é estado inválido. Mecanismo (reaproveitar `tags` × campo próprio em `products`) é decisão de `/sc:design`; o invariante é requisito. |
| RF2 | A IA propõe o nome do grupo junto do que já propõe hoje (nome legível, categoria, conteúdo), preferindo grupos já existentes — mesma mecânica de `known_tags` que já evita proliferação de categorias. |
| RF3 | Grupo e conteúdo são **aplicados automaticamente** quando a sugestão é confiante, e reversíveis pelos comandos que já existem (§4). |
| RF4 | A notificação é **resumo agregado** ("Apliquei N conteúdos e M tipos"), com o detalhe e o desfazer disponíveis sob demanda — não uma linha por ação. Na primeira rodada seriam ~107 linhas; o resumo é o que mantém a saída legível. |
| RF5 | Comparação entre mercados: por grupo, quem está mais barato; depois a contagem por loja. Sempre com número de grupos que sustentam a conta e intervalo de datas. Nunca um índice único. |
| RF6 | `consultar` passa a exibir o dia da semana ao lado da data. Nenhuma afirmação sobre padrão semanal, nenhum cálculo — só o dado, para o olho do usuário. |
| RF7 | Item vendido por UN sem `content` definido **não entra** em comparação de grupo como se fosse comparável — ou o conteúdo é preenchido, ou a linha aparece sem participar do mínimo/máximo do grupo. |

## 7. Interação com trabalho já em andamento (não commitado)

`docs/design/consultar-v2.1.md` §1 mediu `TAG_MATCH_CUTOFF = 75` contra **as 13 tags de corredor**, registrando "nenhuma das 13 tags pontua acima de 55 contra outra". Se `/sc:design` resolver RF1 reaproveitando a tabela `tags` para os grupos, entram ~75 nomes novos no mesmo espaço (`tomate`, `uva`, `banana`, `leite uht`…) e **essa medição deixa de valer** — nomes de grupo colidem entre si e com palavras de produto muito mais do que categorias de corredor colidem. Um campo próprio em `products` mantém o espaço de tags intacto e a medição válida. É a principal entrada deste fechamento para o design.

> **Correção factual (pós-escrita):** este parágrafo dizia que os tickets 115/116 estavam "no diretório de trabalho sem commit". Estavam quando a medição foi feita, mas foram commitados durante esta mesma sessão (`350e810`, `9843e68`), com a suíte em 394 testes verdes. O que importa para o design continua valendo: a medição de `TAG_MATCH_CUTOFF` foi calibrada contra as 13 tags de corredor e não sobrevive a ~75 nomes finos no mesmo espaço.

## 8. Ação operacional (não é código)

Duas das cinco lojas ainda têm `address` nulo: `11832478000285` (Dona de Casa) e `20209736000181` (Comercial HTP). Reimportar os recibos correspondentes de `entrada/` preenche o endereço e é idempotente para os preços (a PK `(access_key, item_index)` garante). Não adiciona nenhuma observação de preço nova — o que confirma que **não existe backlog histórico a importar**: a cobertura cresce só no ritmo em que o usuário faz compras, o que é mais um motivo para maximizar o valor de cada observação (§1) em vez de esperar volume.

## 9. Fora de escopo, agora explicitamente

Fusão automática de produtos, em qualquer nível de confiança (§3) · infraestrutura de undo para `fundir` (não é mais necessária) · índice único de "carestia" por mercado (RF5 usa contagem por grupo) · qualquer afirmação sobre padrão de dia da semana (RF6 só mostra o dado) · veredito estatístico com média/desvio/percentual · classificação automática de código de unidade novo · aplicar ação automática a apelido de mercado (§4, falha o teste por não ter valor correto derivável).
