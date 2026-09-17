# Julius — data legível e idade relativa: design

> `/sc:design` de 2026-09-17, a partir de `docs/requirements/readable-dates.md` (F1–F7, RF1–RF8, N1–N4, Q1–Q5). Especificação para o ticket 149. **Nenhum código foi alterado.**
> **Q1–Q5 fecham com os defaults propostos no brainstorm**, com uma exceção: **Q3 fecha mais estreito** — o rodapé do `mercados comparar` ganha só o ano (`04/09/2026 a 16/09/2026`), não o vão em dias. Motivo em §6.
> Achado no caminho, fora do pedido original mas dentro do mesmo código: o `--ultimas-acoes` exibe **hora UTC como se fosse local** (§3). Medido, não suposto.

## 0. O que os requisitos já decidiram e este design obedece

| Decisão | Consequência no design |
|---|---|
| Uma função só, camada `cli` (RF8) | `cli/_common.py`, ao lado de `money`; as duas `_day_month` duplicadas morrem (§2) |
| Célula empilhada, sem coluna nova (RF5) | `date_cell` devolve `rich.text.Text`; `_store_cell` é o precedente exato (§1.3) |
| Data de referência por argumento (RF6) | `relative_age(iso, *, today=None)`; nenhum `date.today()` dentro da lógica de faixa |
| Comparação em `date`, não `datetime` (RF7) | `date.fromisoformat(iso[:10])` — a hora é descartada antes de subtrair |
| Uma unidade só acima de semanas (RF3b) | `meses = dias // 30`, anos = `meses // 12`; nenhum `dias // 365` no código |
| Faixas acima de "dias" não têm caso real (N1) | Teste sintético com `today` fixo é obrigatório, não opcional (§5.1) |
| CSV e nome de arquivo continuam ISO (§4 dos requisitos) | `services/export.py` e `infra/receipt_files.py` **não aparecem** neste design |

## 1. As três funções

Todas em `julius/cli/_common.py`. Nenhuma lança — data ruim vira string vazia, mesma disciplina do `_weekday` que já existe.

### 1.1 `br_date(purchased_at: str) -> str`

`"2026-09-16T10:00:00"` → `"16/09/2026"`. Fatiamento de string, igual ao `_day_month` que ela substitui — sem `datetime`, então não há exceção a tratar. `len < 10` → `""` (o `--ultimas-acoes` lê um JSONL que pode ter registro parcial; `ai_log.tail` já tolera isso por contrato e há teste).

### 1.2 `relative_age(purchased_at: str, *, today: date | None = None) -> str`

```python
days = ((today or date.today()) - date.fromisoformat(purchased_at[:10])).days
if days <= 0:   return "hoje"                       # <= 0, não == 0: nota emitida "no futuro" (relógio) não vira "há -1 dias"
if days == 1:   return "ontem"
if days <= 15:  return f"há {days} dias"
if days <= 29:  return f"há {days // 7} semanas"    # só 2, 3 ou 4 são alcançáveis (RF2)
months = days // 30
if months < 12: return f"há {months} {'mês' if months == 1 else 'meses'}"
years, rest = months // 12, months % 12
label = f"há {years} {'ano' if years == 1 else 'anos'}"
return label if rest == 0 else f"{label} e {rest} {'mês' if rest == 1 else 'meses'}"
```

`date.fromisoformat` lança em entrada malformada → `try/except ValueError: return ""`, como `_weekday` já faz. O `# ponytail:` de N2 (mês=30, ano=360 dias, aproximados de propósito) vai acima de `months`.

### 1.3 `date_cell(purchased_at: str, *, today: date | None = None) -> Text`

```python
age = relative_age(purchased_at, today=today)
absolute = br_date(purchased_at)
return Text(absolute) if not age else Text.assemble(absolute, "\n", (age, "dim"))
```

**Composição de estilo não é risco, é precedente**: `_store_cell` já devolve um `Text` com um trecho `dim` para linhas que levam `style=HIGHLIGHT_STYLE.get(...)` no `add_row` do `consultar`. Rich compõe (`green` + `dim`). Ninguém precisa conferir isso à mão.

**A largura não muda, e isso foi renderizado, não suposto**: `16/09/2026` e `há 13 dias` têm 10 caracteres, exatamente o que `2026-09-16` já ocupava — a coluna Data do `mercados comparar` sai com a mesma borda de 12 caracteres de hoje. O custo é altura: cada linha vira duas (no `consultar`, onde `_store_cell` já faz isso, o custo é zero nas linhas cuja loja tem endereço — 125 das 132 hoje, F5).

## 2. Os 5 pontos de chamada

A regra que decide **onde a idade relativa entra**: ela acompanha data que descreve **uma observação cuja validade o usuário precisa julgar**. Não acompanha intervalo.

| # | Onde | Hoje | Depois |
|---|---|---|---|
| 1 | `cli/stores.py:128` — `mercados comparar`, coluna Data | `entry.purchased_at[:10]` | `date_cell(entry.purchased_at)` |
| 2 | `cli/receipts.py:287` — `consultar`, coluna Data | `record.purchased_at[:10]` | `date_cell(record.purchased_at)` |
| 3 | `cli/receipts.py:212` — `_extreme_line` | `…, {_day_month(previous_at)}` | `…, {br_date(...)} · {relative_age(...)}` — é observação: "bateu um preço de **há 3 meses**" é notícia diferente de "de **ontem**". **Separador `·`, não parênteses**: `previous` já entra entre parênteses em `_extreme_line`, e `(… (há 7 dias))` aninha — visto ao validar a saída. `·` é o separador que o projeto já usa (`base:`, `_labels`, dicas). |
| 4 | `cli/stores.py:88` — rodapé `base: N grupos · …` | `_day_month(first)} a {_day_month(last)` | `{br_date(first)} a {br_date(last)}` — é intervalo, **sem** idade (Q3, §6) |
| 5 | `cli/products.py:250` — `--ultimas-acoes`, coluna Quando | `str(at)[:16].replace("T", " ")` | `_when(at)` privado, §3 — data br + hora **local**, sem idade (Q5) |

`_day_month` deixa de existir nos dois arquivos (RF8/F4). A coluna **"Dia"** (dia da semana) do `consultar` **fica** (Q4): responde outra pergunta e não custa largura.

## 3. O bug de fuso, que este design precisa consertar para não piorar

`cli/_review.py:76` grava `"at": datetime.now(timezone.utc).isoformat(...)` e `cli/products.py:250` exibe `str(at)[:16]` cru. Medido nesta sessão: gravado `2026-09-17T22:31:47+00:00`, exibido `2026-09-17 22:31`, hora local **19:31**. Três horas de mentira. Formatar isso como `17/09/2026 22:31` deixaria o número errado com cara de mais autoridade — por isso entra no escopo.

- **O conserto** é no lado da escrita: `_review.py:76` passa a gravar `datetime.now().isoformat(timespec="seconds")` (local ingênuo), que é o que `prices.purchased_at` já é — o log fica coerente com o banco e a exibição volta a ser só formatação.
Misturar os dois formatos no mesmo arquivo é seguro, e isso foi verificado: `ai_log.tail` tem **um** chamador de produção (`cli/products.py:244`) e `at` tem **um** leitor (`cli/products.py:250`; o único teste que o toca, `tests/test_cli_review.py:197`, só checa se é truthy). Nada ordena nem filtra por `at` — `tail` devolve na ordem do arquivo, não do campo — então offsets misturados não quebram ordenação nenhuma.

- **A compatibilidade** com as linhas UTC já gravadas é `.astimezone()` na leitura, que converte o que é aware e devolve intacto o que é ingênuo — uma expressão cobre os dois casos:

```python
def _when(raw: str) -> str:          # privado em cli/products.py: um único chamador
    try:
        moment = datetime.fromisoformat(raw).astimezone()
    except ValueError:
        return ""
    return f"{br_date(moment.date().isoformat())} {moment:%H:%M}"
```

## 4. Contratos por módulo

| Módulo | Mudança |
|---|---|
| `julius/cli/_common.py` | **+** `br_date`, `relative_age`, `date_cell`. **+** imports `datetime.date`, `rich.text.Text`. |
| `julius/cli/stores.py` | **−** `_day_month`. Pontos 1 e 4. |
| `julius/cli/receipts.py` | **−** `_day_month`. Pontos 2 e 3. |
| `julius/cli/products.py` | **+** `_when` privado. Ponto 5. |
| `julius/cli/_review.py` | Linha 76: `timezone.utc` sai (§3). `timezone` pode ficar órfão no import — conferir. |
| `domain/`, `services/`, `repositories/`, `infra/` | **nada.** É formatação; a DAG já põe isso em `cli`. |

## 5. Testes

### 5.1 Novo: `tests/test_cli_common.py` — a tabela de faixas (N1)

`today` fixo, parametrizado. Os casos que **têm** de estar lá porque o banco real não os tem: `330d → há 11 meses`, `360d → há 1 ano`, `456d → há 1 ano e 3 meses` (o exemplo literal do usuário), `720d → há 2 anos`, `760d → há 2 anos e 1 mês`. Mais as fronteiras (`15d`/`16d`, `29d`/`30d`, `359d`/`360d`), o plural irregular (`1 mês` × `2 meses`), `hoje`/`ontem`, data futura → `hoje`, e entrada vazia/malformada → `""`.

### 5.2 `_when` exige fuso fixo, senão o teste é dependente da máquina

`.astimezone()` usa o fuso do SO — um teste que afirme "22:31 UTC → 19:31" só passa em UTC−3. Fixar com `monkeypatch.setenv("TZ", "America/Sao_Paulo")` + `time.tzset()` (stdlib, sem dependência nova). **Sem isso o teste passa aqui e quebra em CI.**

### 5.3 Regra de isolamento: teste de CLI afirma data absoluta, nunca idade relativa

Os pontos de chamada **não** passam `today` (produção quer o dia real), então todo teste de nível CLI renderiza contra o relógio. As datas de fixture são de setembro de 2026: um teste que afirme `há 10 dias` **passa hoje e quebra quando a fixture cruzar 15 dias**, virando `há 2 semanas`, e de novo em 30 dias. Portanto: teste de CLI afirma só a parte absoluta (`07/09/2026`), que é estável para sempre; **toda** afirmação de faixa vive em `tests/test_cli_common.py` com `today` injetado (§5.1). Isso vale para os testes novos do `--ultimas-acoes` também — `_when` não tem idade (Q5), só data e hora, e a hora é fixada pelo `TZ` da §5.2.

### 5.4 Testes existentes

| Teste | O que fazer |
|---|---|
| `tests/test_cli_catalog.py:376` — `"base: 1 grupo · 07/09 a 12/09"` | **Quebra.** Atualizar para `07/09/2026 a 12/09/2026`. É o único que quebra. |
| `tests/test_cli_receipts.py:543` — `"07/09" in` a linha do `↓` | **Não quebra, e é pior**: `"07/09"` casa como substring de `"07/09/2026"`, então o teste fica verde **sem mais discriminar nada**. Apertar para `"07/09/2026"`. **Não** afirmar a idade aqui — ver §5.3. |
| `tests/test_cli_review.py:501` — `--ultimas-acoes` | Não afirma o timestamp; segue verde. Ganha um caso novo para §3/§5.2. |
| `tests/test_cli_receipts.py` — tabelas do `consultar` | Nenhum afirma a coluna Data. Sem impacto. |

## 6. Por que Q3 fechou mais estreito que o default do brainstorm

O default proposto era `base: 6 grupos · últimos 13 dias`, e cheguei a considerar `04/09/2026 a 16/09/2026 (13 dias)`. Os dois estão errados pelo mesmo motivo: **RF1 pediu ano no rodapé, não um terceiro segmento**. A idade por linha — o objetivo da feature — já responde "quanto tempo faz"; o rodapé descreve um **intervalo**, e o brainstorm já havia registrado que intervalo em linguagem relativa lê mal ("de há 13 dias a ontem"). O aviso "Período largo" foi medido para existir na v2.2 e não muda aqui. Ficou `04/09/2026 a 16/09/2026`: uma função, zero ramo de borda (nenhum caso "vão de 0 dias"). Se o vão fizer falta, é uma linha depois.

## 7. Sequência de implementação

Um ticket basta — são ~40 linhas em 5 arquivos, com uma dependência interna só (as 3 funções antes dos 5 pontos de chamada). Ordem: (1) `_common.py` + `tests/test_cli_common.py`; (2) os 5 pontos de chamada; (3) `_review.py:76` + o caso de fuso; (4) os dois testes existentes da §5.4.

As três funções e o `_when` da §3 foram **executados** nesta sessão (script descartável, fora do projeto) contra as 15 faixas da §5.1, os dois casos de fuso da §5.2 e a tabela real do `mercados comparar`: todas as asserções passaram e a saída renderizada é a de §1.3. O ticket implementa código já verificado, não especulação.

## 8. O que este design decidiu, além dos requisitos

- **A regra de onde a idade entra** (§2): acompanha observação, não intervalo. É o que separa o ponto 3 (leva) do ponto 4 (não leva), em vez de decidir caso a caso.
- **O bug de fuso (§3)** não estava no pedido. Entra porque é a mesma expressão que este trabalho reescreve, e prettificar um número errado o piora.
- **`days <= 0` em vez de `== 0`**: data futura por relógio torto vira `hoje`, não `há -1 dias`.
- **Não entrou**: idade em horas no `--ultimas-acoes` (Q5 — seria uma quarta granularidade a medir), vão em dias no rodapé (§6), `--formato-data` (ferramenta de um usuário só).

## 9. O que a implementação corrigiu neste design

Três desvios, todos achados ao executar — registrados para o doc não mentir sobre o que foi feito.

| # | O design dizia | O que era |
|---|---|---|
| 1 | Tickets "147+" | 147 e 148 foram ocupados por outra frente de trabalho **durante** esta sessão (`Say which product each compared price belongs to`, `Say which product the new record beat`), que também reformatou os dois pontos de chamada e acrescentou a coluna "Produto" às tabelas do `mercados comparar`. Este é o **149**, e os dois pontos foram reaplicados contra o conteúdo novo. |
| 2 | "É o único que quebra" (§5.4) | **5 testes quebraram.** O levantamento olhou `tests/test_cli_*.py` e não `tests/test_e2e.py`, que afirma data ISO na saída em 4 lugares (`test_e2e.py:150, 323, 461, 588`). Corrigidos pela regra da §5.3: só a parte absoluta. As asserções de **nome de arquivo** (`2026-09-07_…`) ficaram ISO, como §0 manda. |
| 3 | Um write site de UTC (`_review.py:76`) | **Dois.** O ticket 148 acrescentou `cli/stores.py::log_namings`, que grava `at` no mesmo `actions.jsonl`. O conserto cobre os dois. `cli/receipts.py:147` grava `"ts"` em UTC no `query_log.jsonl` e **ficou como está**: campo diferente, arquivo diferente, nenhum caminho de exibição. |

Verificado à mão contra cópia do banco real: a coluna Data do `mercados comparar` manteve os mesmos 12 caracteres, o `consultar` não ganhou altura (as linhas já eram de duas por causa do endereço) e o `--ultimas-acoes` mostra a linha UTC antiga como `16/09/2026 19:31` e a nova local intacta.
