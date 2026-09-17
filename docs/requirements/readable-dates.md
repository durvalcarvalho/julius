# Julius — data legível e idade relativa: requisitos

> Brainstorm de 2026-09-17 (`/sc:brainstorm`), disparado por uso real: o usuário rodou `julius mercados comparar` e reclamou da coluna "Data" em duas frentes — **"não tá no formato do Brasil"** e **"é difícil saber quantos dias atrás foi, se foi até 15 dias ou se faz 3, 4 semanas ou 1 2 3 meses ou 1 ano e 3 meses"**.
> Insumos: saída real colada pelo usuário; medição direta no `prices.db` de produção feita nesta sessão; leitura de `cli/stores.py`, `cli/receipts.py`, `cli/products.py`, `cli/_common.py`, `services/export.py`, `infra/receipt_files.py`.
> Próximo passo: `/sc:design` → ticket(s) em `docs/tickets/julius-v2/` (147+).

## 0. Ponto de partida — fatos verificados

| # | Fato | Evidência |
|---|---|---|
| F1 | **Medição real (banco de produção, hoje 17/09/2026): só 6 datas distintas, todas dentro de 13 dias** (04/09 n=47, 05/09 n=1, 07/09 n=6, 10/09 n=12, 12/09 n=20, 16/09 n=46; 132 preços). **Toda data do banco cai hoje na primeira faixa ("até 15 dias")** — as faixas de semanas/meses/anos não têm nenhum caso observável. | Query em `prices` feita nesta sessão. |
| F2 | O vão entre a nota mais velha e a mais nova é **12 dias** — exatamente o número que já motivou o aviso "Período largo: parte da diferença pode ser variação de preço no mês, não o mercado" do `mercados comparar`. A idade relativa por linha mostra, **linha a linha**, o que hoje só existe como rodapé genérico. | F1 + `cli/stores.py:89`; `CLAUDE.md`, seção `mercados comparar`. |
| F3 | A data ISO crua aparece em **5 lugares** que o usuário lê: coluna "Data" do `mercados comparar` (`purchased_at[:10]`), coluna "Data" do `consultar` (`purchased_at[:10]`), coluna "Quando" do `revisar --ultimas-acoes` (`[:16]` com o `T` trocado por espaço), o rodapé `base: N grupos · 04/09 a 16/09` (`_day_month`, sem ano) e a linha de extremos do `importar` (`era R$ X em LOJA, 16/09`, `_day_month`). Só os dois últimos já estão em ordem brasileira — e **sem ano**. | `cli/stores.py:128`, `cli/receipts.py:287`, `cli/products.py::_print_last_actions`, `cli/stores.py:88`, `cli/receipts.py:212`. |
| F4 | `_day_month` está **duplicado literalmente** em `cli/stores.py:96` e `cli/receipts.py:216` (mesmo corpo, duas casas). `cli/_common.py` já é a casa da formatação compartilhada (`money`, `content_text`, `HIGHLIGHT_STYLE`) e já é importado pelos dois arquivos. | Os dois arquivos; `cli/_common.py`; imports em `stores.py:9` e `receipts.py:13`. |
| F5 | **As linhas do `consultar` já têm duas linhas de altura**: `_store_cell` monta `Text.assemble(nickname, "\n", (address, "dim"))` e os endereços foram preenchidos na v2. Uma segunda linha na célula de data, em `dim`, custa **zero largura** em todas as tabelas — que é a restrição que importa nas tabelas largas do `mercados comparar`. Altura extra também é zero **onde a loja tem endereço**; medido hoje, 2 das 5 lojas ainda não têm (7 das 132 linhas de `prices`), e essas linhas passam de 1 para 2. | `cli/receipts.py::_store_cell`; `stores.address` (migração 0002). |
| F6 | O CSV do `exportar` grava `purchased_at` ISO cru, e o arquivamento nomeia a nota como `<purchased_at[:10]>_<chave>.html`. Nos dois casos o ISO é o que **faz o formato funcionar**: planilha parseia e `ls` ordena lexicograficamente. | `repositories/prices.py::EXPORT_COLUMNS`; `infra/receipt_files.py:19`. |
| F7 | Não existe dependência de data no projeto (`typer`, `rich`, `rapidfuzz`; dev `pytest`). Mês e ano exatos de calendário exigiriam dependência nova ou aritmética de calendário à mão. | `pyproject.toml`. |

## 1. Objetivo

Trocar a data ISO crua por **duas informações em uma célula**: a data no formato brasileiro (`16/09/2026`) e, abaixo dela em cinza, quanto tempo faz (`há 1 dia`, `há 3 semanas`, `há 1 ano e 3 meses`) — nas 5 telas de F3, por **uma** função em `cli/_common.py` que substitui as duas copias de `_day_month` (F4). A idade relativa não é enfeite: é o que responde "esse preço ainda vale?" sem o usuário fazer conta de cabeça, e é a versão por linha do aviso de período largo que o `mercados comparar` já dá no rodapé (F2).

## 2. Requisitos funcionais

| # | Requisito |
|---|---|
| RF1 | Data absoluta renderizada como `DD/MM/AAAA` (com ano sempre, nas 5 telas de F3) — hoje 3 delas mostram ISO e 2 mostram `DD/MM` sem ano. |
| RF2 | Idade relativa em faixas, **transcritas do pedido do usuário**: `hoje` (0 dias) · `ontem` (1) · `há N dias` (2–15) · `há N semanas` (16–29 — só 2, 3 ou 4 são alcançáveis, porque dias cobrem até 15; é o que você pediu, não um bug) · `há N meses` (30–359) · `há N anos` / `há N anos e M meses` (≥360, com o "e M meses" omitido quando M é 0). As fronteiras de mês e ano saem de RF3b, não de `dias // 365`. |
| RF3 | Arredondamento **para baixo** em toda faixa (`dias // 7`, `dias // 30`, `meses // 12`): "há 2 semanas" significa "pelo menos 2 semanas", que é como se fala e é o lado honesto do erro. Nenhuma faixa subestima. |
| RF3b | **Uma unidade só acima de semanas, para o floor não se contradizer**: `meses = dias // 30`; abaixo de 12 imprime meses, de 12 em diante imprime `anos = meses // 12` mais o resto em meses. Isso nunca produz "há 12 meses" (com "há 1 ano" a um dia de distância) **sem** precisar de um limite artificial que faria 364 dias subestimar. A fronteira do ano cai em 360 dias, coerente com a aproximação de mês=30 dias que N2 já declara. Aresta achada ao validar as faixas nesta sessão, não hipótese. |
| RF4 | Plural correto em português, incluindo o irregular: `1 dia`/`2 dias`, `1 semana`/`2 semanas`, **`1 mês`/`2 meses`**, `1 ano`/`2 anos`. `cli/stores.py::_plural` é o precedente de como isso já é feito. |
| RF5 | A célula mostra as duas coisas empilhadas — absoluta em cima, relativa em `dim` embaixo — reaproveitando o `Text.assemble` de `_store_cell` (F5), **sem coluna nova** em nenhuma tabela. |
| RF6 | A idade é calculada contra uma **data de referência recebida como argumento**, com default "hoje". Sem `datetime.now()` dentro da função de formatação: senão o teste das faixas depende do dia em que roda. |
| RF7 | Comparação em `date`, não `datetime`: `purchased_at` vem da "Emissão" (hora local, ingênua) e comparar datetimes coloca um off-by-one na virada da meia-noite. |
| RF8 | Uma função só, em `cli/_common.py`, consumida pelas 5 telas; as duas `_day_month` duplicadas (F4) deixam de existir. Nenhum `services/` muda — é formatação, camada `cli` (a DAG já diz isso). |

**Faixas validadas nesta sessão** (script descartável, não código de projeto), incluindo o exemplo literal do pedido:

```
  0d → hoje          16d → há 2 semanas     30d → há 1 mês       360d → há 1 ano
  1d → ontem         21d → há 3 semanas     60d → há 2 meses     395d → há 1 ano e 1 mês
  2d → há 2 dias     28d → há 4 semanas    330d → há 11 meses    456d → há 1 ano e 3 meses
 15d → há 15 dias    29d → há 4 semanas    359d → há 11 meses    720d → há 2 anos
```

Contra as 6 datas reais do banco (F1): `ontem` (n=46), `há 5 dias` (n=20), `há 7 dias` (n=12), `há 10 dias` (n=6), `há 12 dias` (n=1), `há 13 dias` (n=47).

## 3. Requisitos não funcionais

- **N1** Faixas acima de "dias" **não têm caso real no banco** (F1) e por isso exigem **teste sintético** — mesmo precedente do `synthetic_eggs.html`, criado porque o dado real não tinha o caso. Sem isso, meses e anos entram em produção sem nunca ter sido executados, e ninguém descobre por um ano.
- **N2** Mês e ano são **aproximados** (30 e 365 dias), não calendário exato. Para lembrança de preço a faixa é a informação — "há 3 meses" errar por 2 dias não muda decisão de compra nenhuma, e o exato custaria dependência nova ou aritmética de calendário à mão (F7). Decisão registrada, não bug a reportar depois; marcar com comentário `ponytail:` no código.
- **N3** Zero custo de IA, zero query nova: `purchased_at` já vem em toda leitura.
- **N4** Nada de locale/`babel`/`strftime("%x")` — depende de `LC_TIME` do ambiente e quebraria silenciosamente em outra máquina. Formato fixo, que é o que o usuário pediu.

## 4. Fora de escopo (dito de propósito, pra ninguém "consertar" depois)

- **CSV do `exportar` continua ISO** (F6): planilha parseia e a coluna ordena. Formato brasileiro ali seria regressão.
- **Nome do arquivo arquivado continua `AAAA-MM-DD_<chave>.html`** (F6): é o que faz `ls entrada/importados/` sair em ordem cronológica.
- **`ai_calls.jsonl` / `query_log.jsonl` / `actions.jsonl` continuam ISO no arquivo** — são para `jq`, não para ler. Só a *exibição* do `--ultimas-acoes` muda.
- **Nenhum veredito novo sobre o preço**: "há 3 meses" é um fato, não "esse preço está velho, desconsidere". A decisão continua do usuário (requisito-chave do projeto).
- **Sem faixa configurável / sem `--formato-data`**: é ferramenta de um usuário só, com uma preferência só.

## 5. Questões abertas (defaults propostos; corrija o que discordar)

| # | Questão | Default proposto |
|---|---|---|
| Q1 | `1 dia` ou `ontem`? E `0 dias` — `hoje`? | `hoje` e `ontem` como palavras, `há N dias` de 2 em diante. Mais natural, e é como se fala. |
| Q2 | A faixa de dias termina em 15 (pedido literal) — então **15 dias → `há 15 dias`** e **16 dias → `há 2 semanas`**. Incomoda esse salto? | Manter o 15, é o número que você deu. |
| Q3 | O rodapé do `mercados comparar` (`base: 6 grupos · 04/09 a 16/09`) ganha ano nos dois extremos, ou vira **`base: 6 grupos · últimos 13 dias`**? | `últimos 13 dias`: responde direto o que o aviso de período largo insinua, e encurta a linha. |
| Q4 | A coluna **"Dia"** (dia da semana) do `consultar` foi decisão consciente da v2.2 ("mostra o dado e cala"). Com data + idade relativa na mesma célula, ficam 3 informações de tempo em 6 colunas. Ela fica? | Fica. Dia da semana responde outra pergunta (feira de terça, promoção de quinta) e não custa largura relevante. |
| Q5 | O `--ultimas-acoes` mostra hora (`16/09/2026 14:32`). Mantém a hora, ou só data + `há 2 horas`? | Manter data + hora e **não** dar idade relativa em horas — ação automática é sempre recente, a hora já basta e faixas de horas seriam uma quarta granularidade a medir. |
