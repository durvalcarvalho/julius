# Julius v2.4 — fusão automática (reaberta por medição) e a leitura do preço por unidade base: requisitos

> `/sc:brainstorm` de 2026-09-17. Dois pedidos do usuário, no mesmo dia em que ele rodou a v2.3 de verdade contra o banco real.
> **Este documento reabre `docs/requirements/auto-merge-clusters.md`**, que estava marcado "sem efeito" desde 16/09. O `CLAUDE.md` exigia "dado novo" para reabrir; o dado novo existe e está em F2–F4. Os `RF1`–`RF6` daquele documento **voltam a valer** com as emendas da §2.A aqui; não foram reescritos.
> Insumos: banco real do usuário (105 produtos, 132 preços, curado pela v2.3 hoje às 07:02), `curation.duplicate_candidates` + `judge_duplicates` rodados de verdade contra ele, `search_prices` e `mercados comparar` observados na saída real.
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

## 1. Objetivo

**Frente A — inverter o padrão da fusão.** Parar de imprimir comandos `fundir` para o usuário executar: quando a IA afirmar que dois produtos são o mesmo, fundir, avisar o que foi feito e por quê, e oferecer o desfazer. Isto estende à fusão o padrão que a v2.2/v2.3 já aplicam a nome, categoria, tipo e conteúdo de rótulo — e obedece à mesma condição que autorizou cada um deles: **a IA pode gravar sozinha o que o usuário consegue ver que está errado, e desfazer com um comando.**

**Frente B — dar a resposta, não só o dado.** O preço por unidade base já é calculado e já decide o destaque (F7). Falta a tabela deixar essa informação legível: sem linhas repetidas, na ordem que responde a pergunta, e com a conclusão dita em uma frase.

## 2. Requisitos funcionais

### 2.A — Fusão automática (emendas aos `RF1`–`RF6` de `auto-merge-clusters.md`)

| # | Requisito |
|---|---|
| **RF1** (reafirmado, agora com escopo) | Desfazer uma fusão precisa devolver o estado **fielmente**: o produto absorvido volta com o `canonical_name`, as tags, o tipo e o conteúdo que tinha, e recebe de volta exatamente os SKUs e preços que eram dele. Um desfazer que devolve o produto com o nome cru do cupom foi avaliado e recusado — o desfazer tem que ser neutro, não custar trabalho de recuration. |
| **RF2** (substituído) | O gatilho é **o veredito da IA, sem limiar**: funde todo par que `judge_duplicates` marcar como `same_product`. Nenhum corte de confiança — F4 mostra que qualquer corte plausível inverteria o resultado. Nenhum filtro por `kind` — F5 mostra que daria falsa confirmação nos piores pares. O corte determinístico de candidatos (`DUPLICATE_CANDIDATE_CUTOFF = 75`) continua como está, decidindo só **quem é submetido** ao julgamento. |
| **RF3** (mantido) | Atingido o gatilho, fundir dentro do fluxo normal, sem perguntar. |
| **RF4** (mantido, detalhado) | Imediatamente após fundir: dizer quais produtos foram fundidos, qual sobreviveu, o `rationale` que a IA escreveu, **o comando exato de desfazer**, e um pedido explícito de verificação. O usuário descreveu essa notificação como parte do pedido, não como cortesia. |
| **RF5** (mantido) | Par abaixo do corte determinístico, ou que a IA não confirmou: nada acontece, nada é impresso. |
| **RF6** (mantido) | Toda fusão automática é uma ação registrada como as outras: uma linha em `actions.jsonl` com antes/depois e o comando de desfazer, visível em `produtos revisar --ultimas-acoes`. |
| **RF7** (novo) | **Ordem de construção é de princípio, não técnica**: o desfazer (RF1) existe e está testado **antes** de qualquer fusão automática ser ligada. Mesma restrição que pôs o ticket 118 antes do 122 na v2.2. Um agente que inverter isso entrega um sistema que apaga dado que o usuário não consegue recuperar. |
| **RF8** (novo) | A fusão automática nunca toca linhas de `prices` além de reatribuir `product_id` — nenhum preço é alterado, somado ou apagado, nem no desfazer. |

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

## 4. Decisões do usuário (Q&A deste brainstorm)

| Pergunta | Decisão | Consequência |
|---|---|---|
| O que autoriza fundir sozinho? | **A IA confirmar, sem limiar** | RF2. Nenhuma constante nova a calibrar. O risco residual está declarado em §5/Q1. |
| O que o desfazer devolve? | **Tudo, fielmente** | RF1. Exige guardar o estado do produto absorvido antes de fundir. |
| O que falta no preço por conteúdo? | **Colapsar linhas repetidas + ordenar por preço por conteúdo + uma linha de resposta por grupo** | RF9, RF10, RF11. O cálculo não entra: já está certo. |

## 5. Questões em aberto (para o `/sc:design` fechar)

| # | Questão | Por que importa |
|---|---|---|
| Q1 | **Qual produto sobrevive à fusão automática?** Hoje o usuário escolhe (`fundir ORIGEM DESTINO`). Automático precisa de regra: o de menor id, o com mais preços, o com nome já editado à mão, o do mercado onde se compra mais? | Escolher errado joga o nome bom no lixo e faz o desfazer ser usado por motivo bobo. |
| Q2 | **A fusão automática roda em `importar` também, ou só em `produtos revisar`?** Hoje as duas portas chamam a mesma revisão, mas `importar` revisa só os produtos novos da nota. | Fundir no import é onde o par entre lojas aparece; e é também onde o usuário está menos disposto a auditar. |
| Q3 | **A IA confirmando um par do mesmo mercado deve fundir?** Os dois acertos de hoje são entre lojas diferentes; os piores candidatos (Água c/gás ≈ s/gás, os Temperos) são do mesmo mercado. Ela não os confirmou — se confirmar, funde? | Filtro estrutural barato, sem número a calibrar. Foi oferecido e não escolhido; fica registrado para não voltar por acidente. |
| Q4 | **Colapsar linha repetida mostra a contagem ("4×") ou silencia?** Silenciar perde "comprei quatro"; mostrar polui a tabela que o requisito quer limpar. | `consultar` é sobre preço, não sobre quantidade — mas o dado existe. |
| Q5 | **A ordenação por preço por conteúdo é o padrão quando o grupo tem conteúdo, ou uma flag?** | Trocar o padrão muda o significado da tabela para quem a usa como histórico. |
| Q6 | **A linha de resposta (RF11) sai em `consultar`, em `mercados comparar` ou nos dois?** | Os dois têm grupos e base de comparação; só um foi medido nesta sessão. |
| Q7 | **Grupo com massa e volume juntos (F10): nunca comparar, ou pedir a densidade?** Zero casos hoje. | A recomendação registrada é **nunca comparar** — comparar exigiria densidade por produto, um campo novo sem nenhum caso de uso medido. |
| Q8 | **O desfazer preserva o id do produto absorvido?** Ele é citado no `actions.jsonl`, nas dicas e na memória do usuário. | Reciclar id é confuso; criar id novo faz o log antigo apontar para o nada. |

## 6. Fora de escopo, de propósito

- **Corte de confiança para fusão** — F4: os acertos vieram com 0,70/0,80 e o erro com 1,00. Quarta falha do auto-relato.
- **Filtro de fusão por `kind`** — F5: 12 dos 19 candidatos têm tipo igual, incluindo os piores. Questão encerrada, não adiada.
- **Fusão sem julgamento da IA** (só por similaridade de texto) — `Alho ≈ Pão de Alho` pontua 1,00 em texto puro.
- **Recalcular ou mudar `price_per_content`/`comparison_basis`** — F7: está correto e é o que faz a Indaiá 1,5L ser marcada como a mais barata.
- **Densidade por produto** para comparar massa com volume — F10, nenhum caso medido.
- **Veredito de barato/caro** — RF12 mantém a linha de sempre.
- **Fundir mercados** (filiais da mesma rede) — continua fora, como desde a v2.
