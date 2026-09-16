# precos-dos-mercados

## Objetivo

Ferramenta pessoal (CLI) para registrar os preços pagos em compras de mercado (a partir de recibos NFC-e) e depois **comparar** um preço com o histórico — "R$12/kg de banana tá caro?" — junto com o local onde cada preço foi pago.

Não é uma ferramenta de comparação entre mercados em geral nem de controle de gastos: é memória de preços + decisão de compra.

## Status

Fase: **v2.2 implementada.** Os 30 tickets de `docs/tickets/julius-v2/` estão feitos (101–114 da v2, 115–116 da v2.1, 117–130 da v2.2), um commit por ticket, 540 testes verdes (`.venv/bin/pytest -q`), nenhum `NotImplementedError`, nenhum identificador em português. Provedor de IA: DeepSeek, modelo `deepseek-flash`, `thinking` desligado via `JULIUS_AI_REQUEST_EXTRAS='{"thinking":{"type":"disabled"}}'` (sem isso o modelo raciocina em vez de responder — ver "Fatos e pegadinhas"). Orçamento US$5/mês.

Ambiente: `make install` instala `julius` global via `pipx install --editable .` (aponta pro código do diretório — editar ou trocar de branch já vale, sem reinstalar; rode de novo só se o `pyproject.toml` mudar). `make test` cria o `.venv/` na primeira vez e roda o pytest. `make uninstall` remove.

**v1.1 (módulo de dicas de uso)** — tickets 015 e 016 (v1). Nasceu do primeiro uso real (`consultar` num banco vazio dizia só "Nenhum resultado."). Ver "Dicas de uso (`guidance`)"; a única diferença em relação ao design original está registrada lá (`closest_names` compara palavra a palavra, não por faixa de WRatio).

**v2 (IA na prática)** — tickets 101–114. A IA passou de "só testada com fake" para uso real: `julius produtos revisar`/`importar` aplicam nome legível e categoria automaticamente (reversível), sugerem conteúdo de embalagem e candidatos a duplicata; `consultar` cai para a IA só quando a busca determinística vem vazia; endereço do mercado aparece em `mercados listar`/`consultar`/`exportar`. Ver "Camada opcional de IA" (contrato atual) e "Dicas de uso" (3 dicas novas).

**v2.2 (comparabilidade: comparar antes de opinar)** — tickets 117–130, migração 0003. Três trilhas que se juntam: (1) **grupo de comparação** — `products.kind` ("que tipo de coisa isso é": `tomate`, `leite uht`), proposto pela IA e aplicado automaticamente, com `julius produtos tipo ID [--remover]` pra corrigir e a coluna "Tipo" em `produtos listar` pra ver o erro; (2) **comparar de verdade** — `domain/comparison_basis.py` corrige a base do mínimo/máximo (ver "Preço por conteúdo"), `julius mercados comparar` responde "esse mercado é mais caro?" por grupo com `n` e período, e `importar` termina com o sinal "Nesta compra:" dos itens que bateram recorde; (3) **arquivamento** — `julius importar` sem argumento varre `entrada/` e move cada nota importada pra `entrada/importados/<data>_<chave>.html`. Toda gravação automática vira uma linha em `~/.local/share/julius/actions.jsonl`, com o comando de desfazer, lida por `julius produtos revisar --ultimas-acoes`. Contrato completo em `docs/design/comparability-v2.2.md`.

**v2.1 (consultar em linguagem natural)** — tickets 115–116, sem IA nova nenhuma. `julius consultar` passou a reconhecer uma tag dentro do texto livre: `julius consultar hortifruti` e `julius consultar leite laticinio` funcionam sem `--tag` (interseção quando dá match, retry como termo puro quando a interseção fica vazia), com a mesma tolerância a erro de digitação (`rapidfuzz`) que o nome de produto já tinha — corte próprio (`TAG_MATCH_CUTOFF = 75`), medido contra as 13 tags semeadas, não reaproveitado dos cortes de nome de produto. `--tag` explícito continua funcionando exatamente como antes; `--sem-tag` desliga a detecção quando ela atrapalha. Toda chamada de `consultar` grava uma linha em `~/.local/share/julius/query_log.jsonl` (mesmo `infra/ai_log.py::append` que já gravava `ai_calls.jsonl`, reaproveitado sem mudança), pra recalibrar cortes com dado real de uso no futuro — sem comando de leitura ainda, é `jq`/`Counter` por conta do usuário, mesma lógica de não existir `julius ia status`. Contrato completo com a medição do corte em `docs/design/consultar-v2.1.md`.

Resolvido nesta fase (ver "Requisitos novos" para o texto original):
- `julius produtos pendentes` (item 2) → virou `julius produtos revisar`.
- Dica via padrão `C/<número>` (item 3) → coberta pela revisão assistida por IA (`enrich_products`), não só pela dica impressa.

Ainda em aberto (questões de gosto, não bugs):
- Empates de preço em `consultar`: todas as linhas com o menor/maior preço são mantidas mesmo fora de `--limite` (honesto, mas com 4 preços iguais a tabela cresce). Ajustar se incomodar.

Próximo passo sugerido: rodar `julius importar ~/.local/share/julius/entrada/*.html` para o backfill do endereço (idempotente) e `julius produtos revisar` para curar o catálogo acumulado; depois, usar de verdade por mais algumas semanas antes de cogitar v3 (outros estados, Telegram).

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

**2. Revisão periódica de produtos pendentes — RESOLVIDO em v2.** Uma única nota do Sendas/Assaí trouxe 39 produtos novos de uma vez (nenhum com tag, nenhum com conteúdo definido). A pergunta original ("vale um comando tipo `julius produtos pendentes`?") virou `julius produtos revisar`: lista `products.untagged_product_ids`, pede à IA nome legível/categoria/conteúdo, aplica o automático e pergunta o resto (ver "Camada opcional de IA" e ticket 112).

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

Fragmentação por grafia (`tomate`/`Tomate`/`TOMATE`) é resolvida em `products.set_kind`, que minúsculo o valor e reaproveita a grafia já existente quando `normalize_text` coincide (então `açaí` não vira `acai`). Singular/plural fica de fora de propósito: seria um terceiro corte fuzzy a medir sem evidência de que o problema existe. Detecção quando existir, sem código novo: `SELECT kind, count(*) FROM products WHERE kind IS NOT NULL GROUP BY kind ORDER BY kind` — dois tipos vizinhos na ordem alfabética com contagens pequenas é a assinatura; um `UPDATE` resolve.

**Fusão automática foi rejeitada por medição, não por cautela — registre isto antes de propor de novo.** Rodando `duplicate_candidates` + julgamento da IA contra o catálogo real: **19 pares acima do corte, no máximo 2 defensáveis**, e o pior falso positivo foi `Alho` ↔ `Pão de Alho`, que a IA classificou como o mesmo produto com **confiança 1,00**. Precisão medida na casa de 5%. Reabrir exige dado novo — e exigiria antes construir a reversibilidade que `merge_products` não tem (ele apaga a linha de origem; não há desfazer). O grupo de comparação existe justamente porque responde à mesma necessidade sem o risco.

**Rejeitado explicitamente: sugestão automática de fusão via similaridade de string.** `rapidfuzz` compara strings, não produtos — ele vai dar nota alta tanto pra `PICANHA BOV FAT kg PROMO` ≈ `PICANHA BOV FAT kg` (provavelmente o mesmo item, ok) quanto pra `SUCO ... 1.5L UVA` ≈ `SUCO ... 1.5L LARANJA` ou `REFRI PEPSI PET 2L` ≈ `REFRI PEPSI PET 1L` (produtos diferentes, sabor/tamanho mudam e são exatamente o que importa pro preço). Uma sugestão que erra sabor e tamanho ensina o usuário a ignorá-la. Fusão fica manual, disparada pelo usuário quando ele reconhece o caso — nunca automática.

**Isso não contradiz o `produtos comparar` assistido por IA da seção "Camada opcional de IA" abaixo** — a diferença é *quando* a sugestão aparece. O que foi rejeitado aqui é sugestão **automática e não pedida**, embutida em todo `consultar` (ensinaria o usuário a ignorá-la, e custaria uma chamada de IA por busca — inviável no orçamento de $1/mês). `produtos comparar ID_A ID_B` é **o usuário pedindo, uma vez, por um par específico** — baixa frequência, opt-in, cabe no orçamento, e nunca funde sozinho (só imprime uma opinião; `fundir` continua sendo um comando separado e manual).

**2. Busca por termo parcial e com erro de digitação → `rapidfuzz`, sem FTS5.**
Com um catálogo pessoal de no máximo algumas centenas de produtos distintos, comparar o termo digitado contra todos os `nome_canonico` com `rapidfuzz.process.extract` roda em sub-milissegundos — não precisa de índice. Isso cobre termo parcial e erro de digitação **na mesma chamada**, com uma biblioteca só. `SQLite FTS5` foi cogitado e descartado: exigiria tabela virtual + triggers de sincronização pra ganhar ranqueamento que não faz falta nesse volume, e mesmo assim não resolveria digitação errada sozinho (então `rapidfuzz` entraria de qualquer jeito) — duas ferramentas fazendo o trabalho de uma.

**Rejeitado explicitamente: busca semântica (embeddings/`sentence-transformers`).** Resolveria "limpeza" → "DETERGENTE" (ver item 3), mas custa um modelo de ML baixado localmente pra um catálogo de possivelmente umas centenas de itens — desproporcional. Não usar a menos que o catálogo cresça ordens de grandeza e isso vire dor real.

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

Consequência que **não** é bug: enquanto o conteúdo de um produto-UN não estiver definido, ele deixa de receber marcação de mínimo/máximo em grupos heterogêneos. É o que transforma "preencher conteúdo" na ação de maior valor do sistema — e a razão de a v2.2 ter passado a aplicar o conteúdo sugerido pela IA automaticamente (ver "Camada opcional de IA"). A mesma função é usada por `services/comparison.py`; por isso ela mora em `domain/`, não em `services/` (a DAG proíbe `services → services`).

- `consultar`, quando `conteudo_qtd` não é `NULL`, mostra uma coluna extra "preço por `conteudo_unidade`" (`valor_unitario / conteudo_qtd`) ao lado do preço cru — nunca substitui o preço cru, só complementa. Quando `conteudo_qtd` é `NULL` (a maioria dos produtos, no começo), a coluna simplesmente não aparece — sem tentar adivinhar.

**Achado real vs. caso ilustrativo — não confundir os dois.** Nos 3 recibos reais, `REFRI PEPSI PET 2L` (R$6,99 → R$3,50/L) e `REFRI ANT GUARANA PET 1.5L` (R$4,99 → R$3,33/L) têm tamanhos diferentes, mas nesse caso específico o Guaraná já é mais barato tanto no preço cru quanto no preço por litro — **não existe, nos dados reais, um caso onde a ordem muda** entre "mais barato no total" e "mais barato por conteúdo". O caso que realmente demonstra por que a funcionalidade importa é o do usuário (hipotético, não vem dos 3 arquivos): 20 ovos por R$12,00 (R$0,60/ovo) vs. 30 ovos por R$16,50 (R$0,55/ovo) — o pacote maior parece mais caro no total e é mais barato por unidade. Isso vira um fixture sintético nos testes (seção abaixo), não um fixture real.

### Camada opcional de IA (assistência em ambiguidades, nunca decisão automática)

**Estado: implementada e em uso real desde v2** (as seções abaixo, escritas na sessão original de design v1, propunham só a costura; o que segue documenta o contrato de verdade — texto de v1 mantido e anotado onde ficou obsoleto, não apagado).

**Pedido original (v1)**: projetar já a costura pra um dia acoplar uma LLM barata, que ajude nas situações não-determinísticas que este design já rejeitou resolver sozinho (fusão de produto, tag, conteúdo ambíguo) — sem gastar mais que US$1/mês. **Orçamento revisado em v2: US$5/mês** (provedor e preços reais escolhidos, ver abaixo).

**Princípio novo em v2, o que resume tudo abaixo: a IA grava o reversível, nunca o irreversível.** Nome legível (`renomear` desfaz), categoria (`tag ID TAG --remover`), conteúdo (`definir-conteudo ID --remover`, v2.2) e tipo (`tipo ID --remover`, v2.2) podem ser aplicados automaticamente. Fusão de produto e qualquer preço nunca são tocados por IA — `produtos fundir` continua 100% manual, mesmo quando a IA "tem certeza" de uma duplicata.

**Reversão deliberada em v2.2 — não é regressão, não "restaure" a confirmação.** Até a v2.1 este documento afirmava que conteúdo de embalagem *nunca* era gravado sem confirmação explícita, nem com `--sim`. A v2.2 reverteu isso de propósito, por dois motivos medidos: (1) conteúdo passa o teste de duas condições de `docs/requirements/comparability-closure.md` §4 — existe comando de desfazer desde o ticket 118, e um valor errado aparece na coluna "Por L/KG/UN" de `consultar` e na tabela de `produtos listar`; (2) a confirmação virou fricção pura — **32 dos 79 produtos vendidos por UN estavam sem conteúdo**, e o import de 16/09 imprimiu 26 comandos `definir-conteudo` que ninguém rodou. Como conteúdo é justamente o que habilita comparar embalagens de tamanhos diferentes (ver "Preço por conteúdo"), a fricção estava derrubando a funcionalidade principal. A linha vermelha que **não** mudou: fusão continua manual.

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

As três funções antigas do design v1 (fusão par a par, conteúdo isolado, tags isoladas) foram removidas em v2 — substituídas por `suggest_merges` (lote) e `enrich_products` (nome+tags+conteúdo numa chamada só).

**Cortado de propósito: classificar automaticamente um código de unidade novo (`Gf`, `PC`, etc.) via IA.** O mapa de unidade é uma constante curada no código-fonte, editada por um humano quando aparece um código novo — evento raro (surgiu 1x em 5 notas). Gastar uma chamada de rede e checagem de orçamento só pra decorar uma mensagem de erro é máquina demais pra um evento que já falha alto e claro sozinho; se quiser uma opinião da IA nesse momento, o usuário pode perguntar por fora, sem o sistema precisar saber fazer isso.

**`julius produtos comparar ID_A ID_B`** — chama `suggestions.suggest_merges(conn, config, client, [(a, b)])[0]`; sem sugestão, distingue três motivos (não é mais uma mensagem genérica): não configurada (dica `AI_NOT_CONFIGURED`), orçamento do mês esgotado (com valores em US$), ou a chamada falhou (aponta pra `ai_calls.jsonl`). Nunca funde sozinho — `julius produtos fundir` continua sendo o único jeito de aplicar.

**`julius produtos revisar [--sim]` e `julius importar [--sim]` (v2, novo)** — a curadoria de verdade. `curation.propose` chama `enrich_products` pros produtos pendentes (sem tag); nome legível e categoria com um único candidato conhecido são aplicados **sem perguntar** (desfazer: `renomear`/`tag --remover`); categoria em dúvida pergunta (TTY) ou fica pendente; conteúdo de embalagem e tipo são aplicados **sem perguntar** desde a v2.2 (desfazer: `definir-conteudo ID --remover` / `tipo ID --remover`). No fim, candidatos a duplicata (`curation.duplicate_candidates`, `rapidfuzz` corte 75) julgados pela IA (`judge_duplicates`) só imprimem o comando `fundir` pronto — nunca fundem. `importar` roda essa revisão uma vez, no fim, só para os produtos criados naquele import.

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
└── cli/                      # L4 · Typer; só chama services e formata com rich
    ├── __init__.py           #      app + callback raiz (nenhuma conexão aberta em import)
    └── receipts.py · stores.py · products.py                                          (tickets)
```

**Adições de v1.1 e v2** (a árvore acima é a original do design v1; ficou como registro histórico em vez de reescrita):
- `julius/services/guidance.py` + `julius/cli/_hints.py` — módulo de dicas de uso (v1.1, ver seção própria).
- `julius/infra/ai_log.py` **(v2)** — log JSONL de chamadas de IA, um arquivo, uma função (`append`).
- `julius/services/curation.py` **(v2)** — decide o que a IA pode aplicar sozinho e o que precisa perguntar; encontra candidatos a duplicata.
- `julius/cli/_review.py` **(v2)** — a tela de revisão compartilhada por `produtos revisar` e `importar`.
- `julius/infra/migrations/0002_store_address_and_seed_tags.sql` **(v2)** — `stores.address` + 13 tags semeadas.
- `julius/domain/comparison_basis.py` **(v2.2)** — a regra de base de comparação, função pura sobre `PriceRecord`; vive em `domain` porque `services/search.py` **e** `services/comparison.py` a consomem e a DAG proíbe `services → services`.
- `julius/services/comparison.py` **(v2.2)** — `compare_stores` (preço por grupo entre mercados) e `new_extremes` (o que bateu recorde numa nota recém-importada).
- `julius/infra/receipt_files.py` **(v2.2)** — `archive` (move a nota importada pra `entrada/importados/<data>_<chave>.html`) e `discard_sidecar` (apaga a pasta `_files/`; **existe mas não é chamada**, pendente de decisão do usuário — é a única operação destrutiva do sistema).
- `julius/infra/migrations/0003_product_kind.sql` **(v2.2)** — `products.kind`.
- `~/.local/share/julius/actions.jsonl` **(v2.2)** — uma linha por gravação automática (campo, antes, depois, comando de desfazer), pelo mesmo `infra/ai_log.py`; lida por `ai_log.tail` em `produtos revisar --ultimas-acoes`.

**Regras de dependência (o que faz a DAG valer)** — codificadas em `tests/test_architecture.py`, que inspeciona os imports de todo módulo e falha em qualquer atalho:

| camada | pode importar |
|---|---|
| `config`, `domain` | nada de `julius` |
| `infra` | `domain`, `config` |
| `parsers`, `repositories` | `domain` |
| `services` | `domain`, `config`, `infra`, `parsers`, `repositories` |
| `cli` | `domain`, `config`, `infra`, `parsers`, `services` (é o composition root: instancia o parser concreto e o cliente de LLM e os passa aos serviços) |

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
julius produtos listar
julius produtos renomear ID NOME
julius produtos fundir ORIGEM DESTINO
julius produtos tag ID TAG [--remover]
julius produtos tipo ID [TIPO] [--remover]
julius produtos definir-conteudo ID [QTD UNIDADE] [--remover]
julius produtos comparar ID_A ID_B
julius produtos revisar [--sim] [--ultimas-acoes]
```

Nomes de comando em português (são UI); cada um mapeia pra uma função em inglês em `julius/cli/*.py` via `@app.command("importar")`. Todo comando abre a conexão com `infra.db.connect(config.load().db_path)` **dentro do handler** — nunca em import. Um comando só é registrado quando o serviço que ele chama existe (sem stub `NotImplementedError` exposto).

- **`julius importar ARQUIVO...`** — um ou mais arquivos HTML (variádico, de graça no Typer — resolve "import em lote" sem código extra). Chama `services.importing.import_receipts` por arquivo (uma transação cada; falha num não afeta os outros), imprime "N itens novos, M já existiam" por arquivo. Arquivo inexistente/HTML fora do formato/unidade desconhecida → erro claro, nada gravado.
- **`julius consultar [PALAVRA...] [--tag TAG] [--sem-tag]`** — `PALAVRA...` aceita várias palavras sem aspas (`list[str]` no Typer, mesmo mecanismo de `importar ARQUIVO...`) e casa por similaridade (`rapidfuzz`) contra nome de produto **e** contra tag (v2.1): uma palavra que bate uma tag conhecida (`TAG_MATCH_CUTOFF = 75`, `services/search.py::detect_tag`) vira filtro, intersectado com o resto como termo — `julius consultar hortifruti` e `julius consultar leite laticinio` já funcionam sem `--tag`. Interseção vazia refaz a busca como termo puro antes de desistir (`services.search.search_free_text`). `--tag` explícito continua existindo e pula a detecção, sem mudança de comportamento; `--sem-tag` força o mesmo caminho quando a detecção atrapalha (ex.: o nome do produto coincide com uma categoria). Pelo menos uma palavra ou `--tag` é obrigatório. `--limite/-n` limita linhas por grupo de unidade (default 20). Renderiza com `rich.table.Table`: uma tabela por `unit` (nunca mistura UN com KG), colunas data/valor/apelido (+ preço por conteúdo quando existir), `highlight` colorido. Sem match → mensagem explícita, não tabela vazia. Toda chamada grava uma linha em `~/.local/share/julius/query_log.jsonl` (`Config.query_log_path`, mesmo `infra/ai_log.py::append` do log de IA) — palavras digitadas, tag explícita/detectada, termo e tag usados de fato, nº de resultados, se caiu no fallback de IA.
- **`julius exportar`** — `--saida/-o` escolhe o caminho do CSV (default no diretório atual). Chama `services.export.export_csv`. Não é a fonte da verdade, só um dump legível/pra planilha.
- **`julius mercados listar`** — `catalog.list_stores`, tabela `cnpj / razão social / apelido`.
- **`julius mercados renomear CNPJ APELIDO`** — `catalog.rename_store`. É a correção que se repete (todo mercado novo nasce com apelido = razão social), por isso ganhou comando — diferente da correção de uma linha de preço errada, que continua sem comando dedicado (ver seção Decisões).
- **`julius produtos listar`** — `catalog.list_products`, tabela `id / nome / tags`. Ajuda a achar o `ID` pra usar em `renomear`/`fundir`/`tag`.
- **`julius produtos renomear ID NOME`** — `catalog.rename_product`. Pro nome automático (= descrição do primeiro import) não ficar feio pra sempre.
- **`julius produtos fundir ORIGEM DESTINO`** — `catalog.merge_products`. É a correção manual de "isso é o mesmo produto" (nunca sugerida automaticamente — ver seção "Identidade de produto e busca").
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
- `services/search.py`: `closest_names(conn, term, limit=3) -> list[tuple[str, int]]` — nomes que `search_prices` **não** casaria (WRatio < `MATCH_SCORE_CUTOFF`) mas cuja melhor palavra tem `fuzz.ratio >= NEAR_MISS_CUTOFF` (70) contra o termo, ordenados por score desc. **Mudou em relação ao design original (faixa WRatio 45–70) por medição nos 5 recibos reais**: WRatio de termo curto contra nome longo bate no piso 45–60 pra qualquer entrada (`xyzabc` → 45 contra "CHA LEAO RELAXA…", `leite` → 67,5 contra "PAO ZINHO … BAGUETE") enquanto o erro real `pikana` → PICANHA fica em 65,5 — a faixa era só ruído e `NO_MATCH_TRY_TAGS` nunca dispararia. Palavra a palavra separa: `pikana` → PICANHA 77 e `arros` → ARR 75 entram; `frango`, `carne`, `sabao`, `feijao` ficam abaixo de 70. Falso positivo conhecido (nesta constante, `NEAR_MISS_CUTOFF`): `queijo` → QUERO 73. Números no docstring da constante. **Falso positivo diferente, achado em v2, na outra constante (`MATCH_SCORE_CUTOFF`, a que decide o *match* de `search_prices`, não a de "parecidos"):** `carne` vs `PAO DE ALHO PRADELLA 400G PICANTE` pontua 72 — cruza o corte de 70, então `julius consultar carne` acha pão de alho e nunca chega a cair no fallback de IA; `carnes` (65) erra como devia. Os testes de v2 usam `carnes` por isso — documentado no docstring de `MATCH_SCORE_CUTOFF`, não confundir com o `queijo`/`QUERO` acima (constantes e funções diferentes). **(v2)** `records_for_products(conn, product_ids, limit)` foi extraído de `search_prices` (o highlight/trim por unidade), pra o fallback de IA reaproveitar depois de resolver ids; `catalog_for_matching(conn)` devolve `(id, nome, tags)` pro prompt de `match_products`.
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

### Fora do escopo v1/v2/v2.2 (de propósito)
Detecção automática de estado, comando de correção para linhas de preço (usa `sqlite3` direto), veredito automático de preço, lock de concorrência, flag `--db` por comando, `platformdirs`, **fusão automática de produtos** (nem por texto nem pela IA — `judge_duplicates` só imprime o `fundir` pronto, quem roda é o usuário), **busca semântica/embeddings** (desproporcional pro tamanho do catálogo), **auto-classificação de tags sem confirmação** (categoria com um único candidato conhecido é aplicada automaticamente em v2, mas isso é *aplicar a sugestão da IA*, não *classificar sem a IA*; categoria em dúvida ainda pergunta), **classificar código de unidade novo via IA** (evento raro, curadoria manual do mapa já resolve, não vale o custo), **cache de respostas de IA** (o caminho durável é corrigir o dado — renomear/marcar tag — não lembrar a resposta antiga), **fallback entre provedores de IA**, **`julius ia status`** (`tail -n 5 ai_calls.jsonl` e `SELECT * FROM ai_usage` já cobrem), **comando de analytics sobre `query_log.jsonl`** (v2.1 — `jq`/`Counter` do usuário sobre o arquivo já respondem "quais buscas falham"/"o que mais consulto", mesma lógica de não criar `julius ia status`), **tag multi-palavra na detecção de texto livre** (v2.1 — nenhuma das 13 tags semeadas precisa disso hoje), **fusão automática de produto em qualquer confiança** (v2.2 — rejeitada por medição, não por cautela: 19 pares acima do corte, no máximo 2 defensáveis, pior falso positivo `Alho` ↔ `Pão de Alho` com confiança 1,00; ver "Identidade de produto e busca"), **índice único de carestia por mercado** (v2.2 — a resposta é contagem por grupo com `n` e período, nunca uma média de razões entre grupos de preços muito diferentes), **qualquer estatística de dia da semana** (v2.2 — as 6 notas reais caem em 6 dias diferentes, zero repetição; a coluna "Dia" mostra o dado e cala), **`consultar --tipo`** (v2.2 — `rapidfuzz` já acha o grupo quando o termo é o próprio tipo), **corte fuzzy pra snapping de tipo** (v2.2 — terceiro cutoff a medir sem evidência de que o problema existe), **comando de analytics sobre `actions.jsonl`** (v2.2 — `--ultimas-acoes` já é a leitura; o resto é `jq`).

## Design de testes

Framework: **pytest** (mesma lógica do Typer — código pronto em vez de escrever mais, `unittest` da stdlib exige mais boilerplate pra fixture/parametrização). Fixtures: os **3 arquivos HTML reais** em `tests/fixtures/` (`qrcode.html`, `qrcode-2.html`, `qrcode-3.html`) + **1 fixture sintético** pro caso de embalagem (não existe nos dados reais, ver seção "Preço por conteúdo"; ainda por criar). Nenhum teste bate na internet — tudo roda em cima de arquivo local + SQLite em `tmp_path` (fixtures `db_path`/`conn` em `tests/conftest.py`).

**Nota de teste que a v2.2 tornou obrigatória:** `importar` **move** o arquivo que leu (arquivamento), então nenhum teste de CLI pode entregar os fixtures do repositório como entrada — eles sumiriam da árvore de trabalho. `tests/conftest.py` tem `copied_fixtures`/`restore_fixture`: cada teste de CLI importa uma cópia em `tmp_path`.

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
