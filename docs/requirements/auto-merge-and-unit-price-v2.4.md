# Julius v2.4 — fusão automática (reaberta por medição) e a leitura do preço por unidade base: requisitos

> `/sc:brainstorm` de 2026-09-17. Dois pedidos do usuário, no mesmo dia em que ele rodou a v2.3 de verdade contra o banco real.
> **Este documento reabre `docs/requirements/auto-merge-clusters.md`**, que estava marcado "sem efeito" desde 16/09. O `CLAUDE.md` exigia "dado novo" para reabrir; o dado novo existe e está em F2–F4. Os `RF1`–`RF6` daquele documento **voltam a valer** com as emendas da §2.A aqui; não foram reescritos.
> Insumos: banco real do usuário (105 produtos, 132 preços, curado pela v2.3 hoje às 07:02), `curation.duplicate_candidates` + `judge_duplicates` rodados de verdade contra ele, `search_prices` e `mercados comparar` observados na saída real.
> **Emendado em 2026-09-17 (terceira rodada):** princípio novo do usuário — *"devemos sempre tentar preservar informações, e de forma que seja consistente, nem que use a IA para isso"*. Isso **substitui o RF1e** (que aceitava perder o conteúdo do absorvido) pela §2.A''. Medindo a regra, ela virou também um **filtro de qualidade da fusão** (F16). As questões em aberto foram fechadas por decisão do agente, a pedido do usuário (§5).
> **Emendado em 2026-09-17 (segunda rodada do brainstorm):** o usuário refinou o RF1 — fundir não pode ser destrutivo *no nível de dados*, em vez de destrutivo-com-restauração. A §2.A' abaixo substitui o RF1; F11–F15 são as medições que a decisão gerou.
> Próximo passo: `/sc:design` → tickets 137+. **Nenhum código foi alterado nesta sessão.**

## 0. Fatos verificados nesta sessão (medidos, não estimados)

| # | Fato | Evidência |
|---|---|---|
| F1 | **A v2.3 funcionou em campo, inclusive a proteção.** O usuário rodou `produtos revisar` no banco real hoje às 07:02: a fila caiu de 86 para 2, e no `Filme PVC Wyda 30m x 28cm` ele gravou **`1 UN`** em vez do `30 UN` que a intuição de varejo ofereceu. O caso que autorizou a pergunta a existir aconteceu e o humano corrigiu. | `actions.jsonl` (ids 31, 32, 66 às 10:02 UTC); `incomplete_product_ids` = `[13, 55]`. |
| F2 | **Dado novo que reabre a fusão automática: 19 candidatos, a IA confirma 2, e os 2 estão certos.** `Banana prata ≈ Banana Prata Extra União` (0,80) e `Uva branca bandeja 500g ≈ Uva Pta Seleta União Bandeja 500g` (0,70). Reproduzido duas vezes — na revisão real de 16/09 e numa chamada direta hoje. | `judge_duplicates` contra o banco real, custo US$ 0,0011. |
| F3 | **O pior falso positivo histórico agora é rejeitado.** `Alho ≈ Pão de Alho Pradella 400g Picante` tem similaridade de texto **1,00** e continua no topo dos candidatos, mas a IA **não** o confirma mais — na medição da v2.2 ela o confirmava com confiança 1,00. O que mudou entre as duas medições é o catálogo: os nomes legíveis e os tipos que a v2.3 aplicou. | mesma execução de F2; `CLAUDE.md`, "Identidade de produto e busca". |
| F4 | **Confiança continua imprestável como corte, e agora com o sinal invertido.** Os dois pares corretos vieram com **0,80 e 0,70**; o falso positivo histórico tinha **1,00**. Um corte em 0,85 — que soaria conservador — mataria os dois acertos e teria aprovado o erro. Quarta falha de auto-relato de confiança neste projeto. | F2/F3; `CLAUDE.md`, "auto-relato de confiança falhou três vezes". |
| F5 | **Estreitar por `kind` é pior que o problema, apesar de matar o `Alho`.** Dos 19 candidatos, **12 têm tipo igual** — e entre eles estão `Água Crystal com gás 500ml ≈ Água Crystal sem gás 500ml` (0,92), `Refrigerante Pepsi PET 2L ≈ Guaraná Antarctica PET 1,5L` (0,78), `Aveia Quaker fino ≈ regular` (0,87) e os três pares de `Tempero Coral Dry Rub` (Beef/Trad/Chicken, 0,90). A razão é estrutural, não amostral: `kind` foi desenhado para agrupar **alternativas de compra** ("marca, fornecedor, sabor e tamanho NÃO entram no tipo"), que é o oposto do critério de fusão. Tipo igual daria falsa confirmação exatamente nos piores pares. | `duplicate_candidates` + `products.kind` do banco real. Fecha a pendência registrada em `CLAUDE.md` ("estreitar `duplicate_candidates` por tipo... vira trivial depois do 117 se incomodar"): **incomodaria**. |
| F6 | **`merge_products` continua irreversível.** Reatribui SKUs e preços e apaga a linha de origem, sem guardar quais `(store_cnpj, product_code)` migraram nem o nome/tags/tipo/conteúdo que a origem tinha. O pedido do usuário ("se eu identificar que alguma besteira foi feita eu rodo o comando de desfazer") pressupõe um comando que **não existe**. | `julius/services/catalog.py::merge_products`; idêntico ao F1 de `auto-merge-clusters.md`, inalterado desde então. |
| F7 | **O preço por unidade base já existe, já está correto e já decide o destaque.** Em `consultar agua`: `Água mineral Indaiá 1,5L` a R$ 3,69 é marcada como **a mais barata** (`lowest`) porque sai a **R$ 2,46/L**, contra R$ 2,98/L da Crystal 500ml que custa R$ 1,49. `mercados comparar` já rotula os grupos com "(por conteúdo)". O pedido nº 2 **não é sobre o cálculo**. | saída real de `julius consultar agua` e `julius mercados comparar`; `domain/comparison_basis.py` (v2.2). |
| F8 | **O que atrapalha a leitura é repetição e ordem.** 20% das linhas de `consultar` são repetições exatas (mesmo produto, data, mercado e preço): 9 de 45 linhas em 7 buscas, sendo **5 de 9 em `agua`** e 4 de 13 em `tempero`. Vêm de item repetido na mesma nota somado aos empates que a v2.2 decidiu manter fora do `--limite`. A tabela ordena por data, então responder "qual embalagem compensa" exige ler a coluna e ordenar de cabeça. | contagem sobre `search_prices` no banco real; `CLAUDE.md`, "Ainda em aberto: empates de preço em `consultar`". |
| F9 | **Há exatamente 1 grupo onde o preço por conteúdo inverte o ranking**, e é o da água. Dos 7 grupos-UN com dois ou mais produtos com conteúdo, só `água mineral` inverte. Nenhum grupo mistura massa com volume. | varredura por `kind` no banco real. |
| F10 | **O exemplo do usuário mistura massa e volume.** "500g por R$ 10,00 custa R$ 20,00 por litro" só vale assumindo densidade 1 (água). O sistema normaliza `G→KG` e `ML→L` em dimensões separadas justamente para não fazer essa conta. Zero ocorrências no banco hoje (F9), então é questão em aberto, não defeito. | `domain/normalization.py::normalize_content`; F9. |
| F11 | **O dado que identifica a origem de cada preço nunca se perde, nem hoje.** Cada linha de `prices` carrega `store_cnpj` + `product_code`, e `product_skus` guarda o mesmo par. "De qual SKU veio este preço" é sempre recuperável. O que a fusão destrói é só a **linha de `products`** do absorvido (nome, tipo, conteúdo), suas tags, e o **agrupamento** (qual SKU pertencia a qual produto, quando o absorvido tinha mais de um). | schema de `prices`/`product_skus`; `catalog.py::merge_products`. |
| F12 | **Toda leitura que agrupa por `product_id` está contida em dois arquivos.** São 26 queries, 21 em `repositories/products.py` e 5 em `repositories/prices.py`; nenhum SQL cru em `services/` ou `cli/`. A DAG de camadas paga dividendo aqui: resolver "este produto foi absorvido por aquele" é mudança de repositório, não varredura pelo sistema. | `grep` por `product_id` em `julius/**.py`. |
| F13 | **Três fusões já aconteceram, e as três estão corretas.** `Tomate Italiano União` (2 SKUs, FL 3 Costa + Dona de Casa), `Cebola` (2 SKUs) e `Sacola reutilizável` (mesmo código em duas filiais da Dona de Casa). Não há erro a reverter — a demanda por reversibilidade é sobre o futuro automático, não sobre essas. | `product_skus` agrupado por `product_id` no banco real. |
| F14 | **O banco é reconstruível a partir dos HTMLs, ao centavo — e os seis existem.** Reimportando os 6 recibos (3 em `tests/fixtures/`, 3 em `~/.local/share/julius/entrada/`) num banco vazio: **132 preços, 6 notas com as mesmas chaves de acesso, 5 mercados e soma dos totais R$ 1.801,57 — diferença de R$ 0,00** contra o banco real. São 108 produtos em vez de 105, porque as três fusões de F13 deixam de existir. | reimport real contra cópias, em banco limpo no scratchpad. |
| F15 | **Mas reprocessar cobra a curadoria inteira: 391 valores.** O banco reconstruído vem com **0** nomes legíveis (contra 103), **0** tipos (contra 104), **0** conteúdos (contra 78) e **0** marcações de tag (contra 106) — inclusive as respostas de conteúdo que o usuário deu hoje às 07:02. Recuperar isso custa ~US$ 0,01 de IA e responder as perguntas de conteúdo de novo. | mesma execução de F14. |
| F16 | **Conteúdo divergente é prova de que o par não é o mesmo produto — e pega justo o que o texto erra.** Dos 19 candidatos, **4 têm conteúdo declarado diferente nos dois lados, e os 4 são falsos positivos**: `Água 500ml ≈ Água 1,5L` (0,86), `Pepsi 2L ≈ Guaraná 1,5L` (0,78), `Água s/gás 500ml ≈ Água c/gás 1,5L` (0,76) e `Pão Zinho 300g ≈ Pão de queijo 800g` (0,75). Os 12 pares de conteúdo igual incluem os dois acertos. O conteúdo que a v2.3 coletou virou, sem código novo, um guarda para a fusão que a v2.4 quer automatizar. | conteúdo dos dois lados de cada par, banco real. |
| F17 | **Herança cega de conteúdo tem risco próprio, medido no mesmo lote.** Em 1 dos 19 pares só um lado tem conteúdo, e é o pior falso positivo histórico: `Alho` (sem conteúdo) ≈ `Pão de Alho Pradella 400g` (0,4 KG). Herdar sem dizer nada gravaria "alho a granel, 400 g" — o erro exatamente do tipo que a v2.3 identificou como invisível na saída normal. Herança precisa aparecer na notificação. | mesma execução de F16. |
| F18 | **Os seis recibos agora estão os seis na pasta de entrada.** `qrcode.html` a `qrcode-6.html`. Os três primeiros foram **copiados** de `tests/fixtures/` (os versionados continuam lá); os três últimos já estavam. O próximo `julius importar` sem argumento importa os seis (idempotente no banco: 0 itens novos para os já conhecidos) e arquiva cada um em `entrada/importados/<data>_<chave>.html`, que é o lugar canônico e o nome que diz qual nota é qual. | `~/.local/share/julius/entrada/` após a cópia. |

## 1. Objetivo

**Frente A — inverter o padrão da fusão.** Parar de imprimir comandos `fundir` para o usuário executar: quando a IA afirmar que dois produtos são o mesmo, fundir, avisar o que foi feito e por quê, e oferecer o desfazer. Isto estende à fusão o padrão que a v2.2/v2.3 já aplicam a nome, categoria, tipo e conteúdo de rótulo — e obedece à mesma condição que autorizou cada um deles: **a IA pode gravar sozinha o que o usuário consegue ver que está errado, e desfazer com um comando.**

**Frente B — dar a resposta, não só o dado.** O preço por unidade base já é calculado e já decide o destaque (F7). Falta a tabela deixar essa informação legível: sem linhas repetidas, na ordem que responde a pergunta, e com a conclusão dita em uma frase.

## 2. Requisitos funcionais

### 2.A — Fusão automática (emendas aos `RF1`–`RF6` de `auto-merge-clusters.md`)

| # | Requisito |
|---|---|
| **RF1** (substituído pela §2.A') | *Ver §2.A' — a fusão deixa de ser uma transformação com restauração e passa a ser um estado reversível.* |
| **RF2** (substituído) | O gatilho é **o veredito da IA, sem limiar**: funde todo par que `judge_duplicates` marcar como `same_product`. Nenhum corte de confiança — F4 mostra que qualquer corte plausível inverteria o resultado. Nenhum filtro por `kind` — F5 mostra que daria falsa confirmação nos piores pares. O corte determinístico de candidatos (`DUPLICATE_CANDIDATE_CUTOFF = 75`) continua como está, decidindo só **quem é submetido** ao julgamento. |
| **RF3** (mantido) | Atingido o gatilho, fundir dentro do fluxo normal, sem perguntar. |
| **RF4** (mantido, detalhado) | Imediatamente após fundir: dizer quais produtos foram fundidos, qual sobreviveu, o `rationale` que a IA escreveu, **o comando exato de desfazer**, e um pedido explícito de verificação. O usuário descreveu essa notificação como parte do pedido, não como cortesia. |
| **RF5** (mantido) | Par abaixo do corte determinístico, ou que a IA não confirmou: nada acontece, nada é impresso. |
| **RF6** (mantido) | Toda fusão automática é uma ação registrada como as outras: uma linha em `actions.jsonl` com antes/depois e o comando de desfazer, visível em `produtos revisar --ultimas-acoes`. |
| **RF7** (novo) | **Ordem de construção é de princípio, não técnica**: o desfazer (RF1) existe e está testado **antes** de qualquer fusão automática ser ligada. Mesma restrição que pôs o ticket 118 antes do 122 na v2.2. Um agente que inverter isso entrega um sistema que apaga dado que o usuário não consegue recuperar. |
| **RF8** (novo) | A fusão automática nunca toca linhas de `prices` além de reatribuir `product_id` — nenhum preço é alterado, somado ou apagado, nem no desfazer. |

### 2.A' — Fusão não destrutiva: o estado pós-fusão (substitui o RF1)

Pedido literal do usuário: *"o fundir não deveria ser destrutivo a nível de dados, pois se eu fundir e logo em seguida quiser desfundir, deve ser possível voltar ao estado anterior, então devemos lidar com esse estado pós-fundir que pode ser desfeito"*. Isto **não** é o mesmo que "guardar o estado e restaurar depois", que era o RF1 antigo: a diferença é que nenhum dado sai do lugar, então o desfazer não reconstrói nada — ele só remove a relação.

| # | Requisito |
|---|---|
| RF1a | **Fundir não apaga nem move nenhuma linha.** A linha de `products` do produto absorvido continua existindo, com o nome, tipo, conteúdo e tags que tinha. Nenhum `DELETE`, e nenhuma reatribuição de `prices` ou `product_skus` é necessária para a fusão acontecer. |
| RF1b | **A fusão é uma relação registrada, e desfazer é removê-la.** Depois de fundir, o sistema sabe que o produto A pertence ao grupo do produto B; desfazer apaga esse registro e o estado anterior volta por construção, não por restauração. Por isso o desfazer é barato, simétrico e não pode falhar por dado faltando. |
| RF1c | **O grupo se apresenta com um nome só**: o do sobrevivente. Onde hoje aparece um produto (`consultar`, `produtos listar`, `mercados comparar`, o sinal do `importar`), passa a aparecer o grupo — os preços do absorvido entram no histórico do sobrevivente e sob o nome dele. |
| RF1d | **O absorvido desaparece das listagens** (`produtos listar`), como se tivesse sido apagado. A lista continua sendo "o que eu tenho"; quem foi fundido em quem se lê em `produtos revisar --ultimas-acoes`, que já é o log de ações. |
| RF1e | *Substituído pela §2.A'' — fundir não pode fazer o grupo perder informação que algum dos dois lados já tinha.* |
| RF1f | **Desfazer não é um caso especial do log.** Como o estado anterior está no banco e não no `actions.jsonl`, desfazer uma fusão funciona mesmo que o log tenha sido apagado, rotado ou nunca escrito. O log continua registrando a ação (RF6), mas não é a fonte da verdade do desfazer. |
| RF1g | **A relação registra o alvo direto; o grupo efetivo é plano.** Fundir A em B e depois B em C guarda "A→B" e "B→C", e as leituras resolvem até a raiz (C), de modo que existe um sobrevivente só. Reapontar A direto para C foi considerado e recusado: destruiria o estado anterior, e desfundir B deixaria A pendurado em C em vez de voltar para B — quebrando o RF1b. |
| RF1h | **`julius produtos fundir` manual usa exatamente o mesmo mecanismo.** Não existem duas fusões, uma destrutiva e uma reversível. Consequência: o aviso de "irreversível — por isso pede confirmação" que hoje acompanha o comando manual deixa de ser verdade e precisa sair do `--help` e do `README`. |

### 2.A'' — A fusão não perde informação (substitui o RF1e)

Princípio do usuário: *"devemos sempre tentar preservar informações e de forma que seja consistente, nem que use a IA para isso"*. A versão anterior deste documento aceitava que fundir podia fazer um grupo perder o conteúdo de embalagem. Isso está revogado: perder conteúdo derruba a comparação por litro/quilo, que é a funcionalidade central desde a v2.2.

A regra por campo, em ordem de preferência — determinística primeiro, IA só onde uma regra não decide:

| Campo | Só um lado tem | Os dois têm, iguais | Os dois têm, diferentes |
|---|---|---|---|
| **Tags** | união | união | **união** — tags são multivaloradas, então não existe conflito e nada se perde |
| **Nome** | vale o não-cru | — | vale o do sobrevivente; o outro fica na linha do absorvido e sai na notificação |
| **Conteúdo** | **herda, e a notificação diz de quem herdou** (F17) | nada a fazer | **a fusão automática não acontece** (F16) |
| **Tipo** | herda | nada a fazer | vale o do sobrevivente; a divergência sai na notificação |

| # | Requisito |
|---|---|
| RF1i | **Tags são unidas.** Nenhuma marcação se perde numa fusão, em nenhum caso. |
| RF1j | **O nome do grupo prefere o nome que não é cru.** Se o sobrevivente ainda tem a descrição do cupom como nome e o absorvido já tem nome legível, o grupo usa o legível — informação curada não é descartada por causa de qual id sobreviveu. Empate (os dois legíveis, ou os dois crus): vale o do sobrevivente. **Sem IA aqui**: um nome errado é visível em qualquer listagem e `produtos renomear` corrige, então pagar uma chamada para escolher entre dois nomes é máquina demais. |
| RF1k | **Conteúdo e tipo são herdados quando só um lado tem.** É o oposto do RF1e revogado: fundir nunca pode tirar um grupo da comparação por conteúdo. Toda herança é uma ação registrada (`actions.jsonl`) e **aparece na notificação da fusão**, dizendo de qual produto veio — F17 mostra por que o silêncio seria perigoso (o `Alho` herdaria 400 g do `Pão de Alho`). |
| RF1l | **Conteúdo divergente impede a fusão automática.** Dois conteúdos declarados e diferentes são evidência de que não é o mesmo produto: F16 mediu 4 pares assim e os 4 são falsos positivos, incluindo `Pepsi 2L ≈ Guaraná 1,5L`. O par não é fundido e nada é impresso (ele volta a ser candidato se algum dos conteúdos mudar). A fusão **manual** continua possível — é o usuário mandando, e ele vê o aviso —, mas não mescla conteúdo. |
| RF1m | **Tipo divergente não impede.** `kind` é genérico de propósito (`suco` vs `suco integral` divergem sem se contradizer), e usá-lo como veto seria o filtro de F5 pelo avesso. Prevalece o do sobrevivente, e a divergência sai na notificação para o usuário conferir com `produtos tipo`. |
| RF1n | **Desfazer reverte também as heranças.** Se o sobrevivente herdou conteúdo ou tipo do absorvido, desfundir devolve os dois ao estado anterior — o herdeiro volta a não ter o valor. Um desfazer que deixasse uma cópia órfã do conteúdo no sobrevivente não teria voltado ao estado anterior, que é o que o RF1b promete. |
| RF1o | **A IA fica de reserva, não de regra.** Nenhuma das quatro linhas da tabela acima precisa de uma chamada. Se um campo novo aparecer no futuro sem regra determinística possível, a IA é o caminho aceitável — desde que o valor escolhido seja visível numa listagem e reversível por comando, que é a condição que o projeto aplica desde a v2.3. |

**Fusões anteriores à mudança (F13) não recebem tratamento.** As três existentes estão corretas e não há o que reverter; a garantia de reversibilidade vale da mudança em diante. **Nada de migração de dado**: a mudança de schema é aditiva, sem tentar reconstituir os produtos já absorvidos — reconstituição parcial apresentada como completa foi explicitamente recusada.

**A política de último recurso, agora medida.** Decisão do usuário: *"ainda estamos no MVP local, podemos simplesmente reprocessar tudo novamente usando os HTMLs que temos"*. F14 prova que isso funciona para os **fatos** — 132 preços, as 6 mesmas notas, R$ 0,00 de diferença — e F15 mostra o preço: **391 valores de curadoria** (103 nomes, 104 tipos, 78 conteúdos, 106 tags) mais as respostas de conteúdo dadas hoje. Então reprocessar é plano B legítimo e barato em dinheiro (~US$ 0,01), e é o que dispensa qualquer código de migração — mas exercê-lo hoje custaria trabalho já feito. Não é ação desta fase.

### 2.B — Leitura do preço por unidade base

| # | Requisito |
|---|---|
| RF9 | `consultar` colapsa linhas idênticas — mesmo produto, mesma data, mesmo mercado, mesmo preço — em uma só. São 20% das linhas hoje e metade da tabela no caso da água (F8), justamente onde a comparação por conteúdo importa. |
| RF10 | Quando o grupo tem preço por conteúdo, a ordenação passa a servir à pergunta "qual embalagem compensa", em vez de só ao histórico. A ordenação por data continua disponível — é ela que responde "o preço subiu?". |
| RF11 | Uma linha de resposta por grupo, dizendo qual embalagem sai mais barata na unidade base e por quanto, em vez de deixar o usuário ler a coluna e ordenar de cabeça. Exemplo com o dado real: *"mais barato por litro: Água mineral Indaiá 1,5L a R$ 2,46/L — a Crystal 500ml sai a R$ 2,98/L"*. |
| RF12 | Isto **não** é o veredito automático de barato/caro que o MVP rejeitou, e a distinção precisa ser preservada: RF11 declara uma ordenação de fatos já calculados dentro do que foi comprado, sem afirmar nada sobre preço justo, tendência ou momento de comprar. |

## 3. Requisitos não funcionais

- **N1** Fusão e desfazer são tudo-ou-nada, numa transação só (garantia que `merge_products` já tem).
- **N2** Custo de IA dentro do orçamento existente. Medido: julgar os 19 candidatos custa **US$ 0,0011** por rodada.
- **N3** A frente B não muda o que `search_prices` **calcula** — `price_per_content` e `highlight` estão corretos (F7) e nenhum requisito aqui pede recálculo. É apresentação.
- **N4** Nenhum identificador em português; comandos, mensagens e prompts em português.
- **N5** A mudança de schema é aditiva e passa pelo mecanismo de migração existente (`PRAGMA user_version` + backup automático do arquivo antes de aplicar).
- **N6** **A política "o banco é reconstruível" depende da pasta de entrada sobreviver.** Resolvido em parte nesta rodada (F18): os seis recibos estão os seis em `~/.local/share/julius/entrada/`, e o próximo `importar` os arquiva em `importados/` com o nome canônico. Três deles também estão versionados em `tests/fixtures/`; os outros três (`qrcode-4/5/6.html`) existem só ali, fora do git. Não é requisito de código — é a consequência da decisão de F14/F15 que vale dizer em voz alta.

## 4. Decisões do usuário (Q&A deste brainstorm)

| Pergunta | Decisão | Consequência |
|---|---|---|
| O que autoriza fundir sozinho? | **A IA confirmar, sem limiar** | RF2. Nenhuma constante nova a calibrar. O risco residual está declarado em §5/Q1. |
| O que o desfazer devolve? | **Tudo, fielmente** | RF1. Exige guardar o estado do produto absorvido antes de fundir. |
| O que falta no preço por conteúdo? | **Colapsar linhas repetidas + ordenar por preço por conteúdo + uma linha de resposta por grupo** | RF9, RF10, RF11. O cálculo não entra: já está certo. |
| Fundir pode ser destrutivo, com restauração? | **Não — não destrutivo no nível de dados** | §2.A' inteira. Substitui o RF1: o desfazer para de reconstruir e passa a só remover a relação. |
| O absorvido aparece em `produtos listar`? | **Não aparece** | RF1d. |
| Conflito de atributos entre absorvido e sobrevivente? | **Valem os do sobrevivente; os do absorvido ficam inertes** | RF1e, com a perda de conteúdo declarada como aceita. |
| E as três fusões antigas? | **Nada a fazer; se um dia incomodar, reprocessa tudo dos HTMLs** | Sem migração de dado, sem comando de separar SKU. F14/F15 medem o custo. |

## 5. Questões fechadas por decisão do agente (a pedido do usuário)

O usuário pediu explicitamente para não ser inundado de perguntas e para as decisões serem tomadas. Cada uma abaixo está fechada com a razão; todas são reversíveis em pouco código, e nenhuma depende de gosto que só ele poderia ter.

| # | Questão | Decisão | Razão |
|---|---|---|---|
| Q1 | Qual produto sobrevive à fusão automática? | **O de menor id.** | Determinístico e estável. As alternativas ("o com mais preços", "o com nome editado à mão") mudam de resposta conforme o banco cresce, então a mesma fusão daria resultados diferentes em dias diferentes. E com a §2.A'' o sobrevivente quase não importa: nome, conteúdo, tipo e tags do grupo já vêm do lado que tem a melhor informação, não do lado que sobreviveu. |
| Q2 | A fusão automática roda no `importar` também? | **Sim, nos dois** — no mesmo ponto onde hoje imprime as sugestões. | O par entre lojas aparece justamente ao importar a nota da segunda loja. Restringir a `produtos revisar` obrigaria dois comandos para o efeito que a fase existe para dar de graça. |
| Q3 | Fundir par do mesmo mercado? | **Sim, sem filtro por mercado.** | O filtro pareceria seguro mas é dispensável: os pares intra-mercado perigosos (Água c/gás ≈ s/gás, os três Temperos) já são rejeitados pela IA, e o que sobraria deles é pego pelo guarda de conteúdo (RF1l). Um filtro a menos para explicar. |
| Q4 | Colapsar linha repetida mostra a contagem ("4×")? | **Não mostra.** | Duas linhas com mesmo produto, data, mercado e preço não carregam informação de **preço** nenhuma — só de quantidade comprada, que é controle de gasto, algo que este sistema declaradamente não é. Nada é apagado do banco; é só a tabela. |
| Q5 | Ordenar por preço por conteúdo é padrão ou flag? | **Nem um nem outro: segue a mesma condição que já escolhe a base de comparação.** Quando o grupo compara por `price_per_content` (vários produtos), ordena por preço por conteúdo; quando é série temporal do mesmo produto, ordena por data. | Zero flag nova e zero constante nova: `domain/comparison_basis.py` já decidiu essa distinção na v2.2, e a ordem passa a concordar com o destaque em vez de contradizê-lo. |
| Q6 | A linha de resposta sai em `consultar`, `mercados comparar` ou nos dois? | **Só em `consultar`.** | `mercados comparar` já responde por construção: uma tabela por grupo, o mais barato em verde e a contagem derivada. Repetir a frase lá seria dizer duas vezes a mesma coisa. |
| Q7 | Grupo com massa e volume juntos? | **Nunca comparar.** | Converter exigiria densidade por produto — campo novo, sem um único caso de uso no banco (F9/F10). As duas dimensões continuam sem se falar, como `normalize_content` já garante. |
| Q9 | Fundir em cadeia: proibir ou reapontar? | **Nem um nem outro: guardar o alvo direto e resolver até a raiz** (RF1g reescrito). | Reapontar A direto para C destrói o estado anterior e quebra o desfazer fiel; proibir obrigaria o usuário a entender o estado interno para fazer uma coisa legítima. |
| Q10 | Qual id o `exportar` (CSV) leva? | **Os dois**: `product_id`/`canonical_name` continuam sendo os do produto da linha (a verdade histórica da compra) e entra uma coluna `group_product_id`, vazia quando não houve fusão. | O princípio desta rodada é preservar informação; o CSV é um dump, e uma coluna a mais é o jeito mais barato de não escolher entre a verdade histórica e a análise. |
| Q11 | `desfundir` recebe o id de quem? | **Do absorvido** — simétrico com `fundir ABSORVIDO SOBREVIVENTE`, e é o comando que a notificação e o `--ultimas-acoes` imprimem pronto. | `desfundir SOBREVIVENTE` seria ambíguo assim que ele tivesse absorvido dois produtos. |
| Q8 | ~~O desfazer preserva o id do absorvido?~~ | **Sim, por construção** | A linha nunca é apagada (§2.A'). |

**A única coisa que permanece aberta, e é de produto:** nada nesta fase. Se algo aparecer no `/sc:design` que dependa de preferência sua, ele pergunta lá.

## 6. Fora de escopo, de propósito

- **Corte de confiança para fusão** — F4: os acertos vieram com 0,70/0,80 e o erro com 1,00. Quarta falha do auto-relato.
- **Filtro de fusão por `kind`** — F5: 12 dos 19 candidatos têm tipo igual, incluindo os piores. Questão encerrada, não adiada.
- **Fusão sem julgamento da IA** (só por similaridade de texto) — `Alho ≈ Pão de Alho` pontua 1,00 em texto puro.
- **Recalcular ou mudar `price_per_content`/`comparison_basis`** — F7: está correto e é o que faz a Indaiá 1,5L ser marcada como a mais barata.
- **Densidade por produto** para comparar massa com volume — F10, nenhum caso medido.
- **Veredito de barato/caro** — RF12 mantém a linha de sempre.
- **Fundir mercados** (filiais da mesma rede) — continua fora, como desde a v2.
- **Migração de dado para as fusões antigas** e **comando de separar SKU** — F13: as três estão corretas; F14/F15: se um dia incomodarem, o caminho é reprocessar os HTMLs.
- **Escolher nome/tipo do grupo com IA** — RF1j/RF1o: as regras determinísticas decidem todos os casos observados, e o erro é visível e reversível.
- **Veto de fusão por tipo divergente** — RF1m: seria o filtro reprovado em F5 pelo avesso.
- **Desfazer baseado em `actions.jsonl`** — RF1f: o log audita, não é a fonte da verdade do estado.
