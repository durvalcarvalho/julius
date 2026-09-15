# precos-dos-mercados

## Objetivo

Ferramenta pessoal (CLI) para registrar os preços pagos em compras de mercado (a partir de recibos NFC-e) e depois **comparar** um preço com o histórico — "R$12/kg de banana tá caro?" — junto com o local onde cada preço foi pago.

Não é uma ferramenta de comparação entre mercados em geral nem de controle de gastos: é memória de preços + decisão de compra.

## Status

Fase: **v1 implementada.** Os 14 tickets de `docs/tickets/julius-v1/` estão feitos, um commit por ticket, 220 testes verdes (`.venv/bin/pytest`), nenhum `NotImplementedError`, nenhum identificador em português. Todos os comandos do CLI funcionam de ponta a ponta contra os 5 recibos reais e o fixture sintético dos ovos; `tests/test_e2e.py` exercita os fluxos como o usuário usa. Camada de IA existe e está testada com fake, mas **nunca foi chamada contra um provedor real** — falta escolher provedor/modelo e configurar `JULIUS_AI_*` (ver "Camada opcional de IA").

Ambiente: `.venv/` próprio do projeto (`python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`); rodar `.venv/bin/pytest`. Uso: `.venv/bin/julius --help`.

Ainda em aberto (questões de gosto, não bugs):
- `julius produtos pendentes` (revisão periódica) — ver "Requisitos novos", item 2.
- Dica via padrão `C/<número>` no `importar` — ver "Requisitos novos", item 3; `suggestions.suggest_content` já existe, ninguém a chama no import.
- Empates de preço em `consultar`: todas as linhas com o menor/maior preço são mantidas mesmo fora de `--limite` (honesto, mas com 4 preços iguais a tabela cresce). Ajustar se incomodar.

Próximo passo sugerido: usar de verdade por algumas semanas (importar os recibos de `~/.local/share/julius/entrada/`), e só então decidir os itens acima e a v2 (outros estados, Telegram).

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
- **Filiais da mesma rede são CNPJs diferentes, e isso é o comportamento certo.** "Dona de Casa" aparece com `11.832.478/0002-85` (Guará) numa nota e `11.832.478/0003-66` (Candangolândia) noutra — endereços diferentes, preços podem diferir. Tratar como dois `mercados` distintos (já é o que o schema faz por chavear em `cnpj` completo) está correto; ao definir apelido, vale incluir um hint de local (ex. "Dona de Casa — Candangolândia") pra diferenciar filiais da mesma marca.
- **Descrições ficam mais crípticas ainda em redes maiores.** Na nota do Sendas/Assaí (47 itens, a maior do lote): `AC MASC F TER ES 1kg`, `SBT GUAPAS 1L MACA V`, `QJ T PARM PIRAC PD` — abreviação mais agressiva que nas notas menores. Reforça (não muda) a decisão já tomada de não tentar NLP/classificação automática em cima da descrição.

## Requisitos novos para o sistema evoluir com segurança

Pergunta direta do usuário: "o que precisa ser feito para que o sistema consiga evoluir". A resposta mais forte não veio de nenhuma feature nova — veio de olhar pra trás nesta própria conversa.

**1. Migração de schema — IMPLEMENTADO.** O schema deste projeto já mudou **quatro vezes** só nas sessões de design anteriores (CSV → SQLite; +`products`/`product_skus`/`tags`; +`content_quantity`/`content_unit`; +mapa de unidade). O banco vai guardar anos de recibos reais — não podia ficar sem mecanismo formal pra "mudar o schema não pode apagar dado". Ver seção "Migração de schema" no Design (v1): `PRAGMA user_version` + `julius/infra/db.py` lendo `julius/infra/migrations/*.sql`, backup automático do arquivo antes de qualquer migração real, sem framework tipo Alembic (desproporcional pra banco de um usuário só). Coberto por `tests/test_db.py`.

**2. Revisão periódica de produtos pendentes — pergunta em aberto, não decisão.** Uma única nota do Sendas/Assaí trouxe 39 produtos novos de uma vez (nenhum com tag, nenhum com conteúdo definido). Conforme o catálogo cresce, vai acumular produtos que nunca foram revisados. Vale um comando tipo `julius produtos pendentes` (lista produtos sem tag e sem `conteudo_qtd`, pra revisar de vez em quando) — ou isso é manutenção demais pro valor que traz, e o usuário prefere só usar `produtos listar` quando lembrar? Pergunta pro usuário, não fechei isso.

**3. Dica (não automática) de conteúdo a partir do padrão `C/<número>` — proposta, não compromisso.** Achado novo: `OVO BCO GRANDE C/30` e `CHA LEAO RELAXA CX 16G C/10UN` usam `C/<dígito>` pra dizer "contém N unidades" — e em nenhuma das 5 notas isso colide com os outros usos de `C/` (`C/GAS`, `C/G`, `C/SAL`, que são sempre `C/` + letra, nunca `C/` + dígito). Isso não muda a decisão de não extrair conteúdo automaticamente (ver seção "Preço por conteúdo") — mas dá pra cogitar uma **sugestão impressa** no `importar` (algo como "💡 produto parece ter C/30 unidades — rode `julius produtos definir-conteudo <id> 30 UN` se quiser comparar por unidade"), nunca aplicada sozinha. É uma questão de gosto (ajuda ou vira ruído?) — decisão do usuário, não minha.

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

**Rejeitado explicitamente: sugestão automática de fusão via similaridade de string.** `rapidfuzz` compara strings, não produtos — ele vai dar nota alta tanto pra `PICANHA BOV FAT kg PROMO` ≈ `PICANHA BOV FAT kg` (provavelmente o mesmo item, ok) quanto pra `SUCO ... 1.5L UVA` ≈ `SUCO ... 1.5L LARANJA` ou `REFRI PEPSI PET 2L` ≈ `REFRI PEPSI PET 1L` (produtos diferentes, sabor/tamanho mudam e são exatamente o que importa pro preço). Uma sugestão que erra sabor e tamanho ensina o usuário a ignorá-la. Fusão fica manual, disparada pelo usuário quando ele reconhece o caso — nunca automática.

**Isso não contradiz o `produtos comparar` assistido por IA da seção "Camada opcional de IA" abaixo** — a diferença é *quando* a sugestão aparece. O que foi rejeitado aqui é sugestão **automática e não pedida**, embutida em todo `consultar` (ensinaria o usuário a ignorá-la, e custaria uma chamada de IA por busca — inviável no orçamento de $1/mês). `produtos comparar ID_A ID_B` é **o usuário pedindo, uma vez, por um par específico** — baixa frequência, opt-in, cabe no orçamento, e nunca funde sozinho (só imprime uma opinião; `fundir` continua sendo um comando separado e manual).

**2. Busca por termo parcial e com erro de digitação → `rapidfuzz`, sem FTS5.**
Com um catálogo pessoal de no máximo algumas centenas de produtos distintos, comparar o termo digitado contra todos os `nome_canonico` com `rapidfuzz.process.extract` roda em sub-milissegundos — não precisa de índice. Isso cobre termo parcial e erro de digitação **na mesma chamada**, com uma biblioteca só. `SQLite FTS5` foi cogitado e descartado: exigiria tabela virtual + triggers de sincronização pra ganhar ranqueamento que não faz falta nesse volume, e mesmo assim não resolveria digitação errada sozinho (então `rapidfuzz` entraria de qualquer jeito) — duas ferramentas fazendo o trabalho de uma.

**Rejeitado explicitamente: busca semântica (embeddings/`sentence-transformers`).** Resolveria "limpeza" → "DETERGENTE" (ver item 3), mas custa um modelo de ML baixado localmente pra um catálogo de possivelmente umas centenas de itens — desproporcional. Não usar a menos que o catálogo cresça ordens de grandeza e isso vire dor real.

**3. "termos tipo limpeza" (categoria) → não é busca, é tag manual.**
`rapidfuzz` (nem nenhuma métrica de string) conecta "limpeza" a "DETERGENTE" ou "SABAO EM PO" — não há sobreposição de caracteres entre essas palavras, edit-distance não ajuda aqui. Isso é conhecimento de categoria, não similaridade textual. Resolvido com `tags` + `produto_tags`: o usuário marca manualmente (`julius produtos tag ID limpeza`), sem classificação automática — evita categorizar errado silenciosamente.

**Isso também não contradiz `sugerir_tags` da IA (seção "Camada opcional de IA")** — a IA só **sugere** tags candidatas pra `julius produtos tag` mostrar antes de o usuário confirmar; ela nunca grava em `produto_tags` sozinha. "Auto-classificação" continua rejeitado; "sugestão que o usuário aceita ou ignora" é outra coisa.

### Preço por conteúdo (comparar embalagens de tamanho diferente)

**Escopo novo desta sessão de design** (surgiu ao analisar os 3 arquivos reais + pergunta explícita do usuário: "20 ovos por X, 30 ovos por Y, qual tá melhor?") — chegou depois do resto da interface já estar fechada, então os comandos abaixo não existiam nas seções anteriores.

**O problema que o agrupamento por `unidade` (UN/KG) não resolve.** Pra item vendido por KG (picanha, tomate, cebola), `valor_unitario` já É o preço por kg — comparável direto. Pra item vendido por UN (`REFRI PEPSI PET 2L` a R$6,99 vs `REFRI ANT GUARANA PET 1.5L` a R$4,99), `valor_unitario` é o preço da embalagem inteira, não do conteúdo — comparar os dois direto ignora que uma garrafa é 33% maior que a outra. É exatamente o caso "20 ovos vs 30 ovos" do usuário.

**Rejeitado explicitamente: extrair o tamanho da embalagem automaticamente da descrição.** As descrições reais têm números que não são conteúdo, ou são ambíguos:
- `PRATO REDOND DESC STRAWPLAS 21CM CRISTAL` — "21CM" é diâmetro do prato, não conteúdo nenhum.
- `CHA LEAO RELAXA CX 16G C/10UN CAMOM/MARACUJA` — "16G" é por sachê ou da caixa toda (16g × 10 = 160g)? Ambíguo pelo texto puro.

Um regex que acerta às vezes e erra silenciosamente em casos como esses é pior do que não ter a funcionalidade — o objetivo do sistema é confiança na lembrança de preço. Por isso: **conteúdo é sempre declarado manualmente pelo usuário**, nunca inferido.

**Schema**: `produtos.conteudo_qtd` + `produtos.conteudo_unidade`, os dois `NULL` até o usuário definir. `conteudo_unidade` normalizado pra uma base única por dimensão no momento de gravar — `G`/`ML` digitados pelo usuário viram `KG`/`L` na gravação (ex.: "500 G" grava `0.5, 'KG'`) — pra nunca ter parte do catálogo em `G` e parte em `KG` (que geraria preço-por-grama vs preço-por-quilo, números que ninguém compara de cabeça). Mesma disciplina do `UN1`→`UN` no parser: normalizar na borda, manter o interior burro.

- `julius produtos definir-conteudo ID QTD UNIDADE` — aceita `L`/`ML`/`KG`/`G`/`UN` como `UNIDADE` de entrada, converte e grava só `L`/`KG`/`UN`. Chama `core.definir_conteudo(produto_id, quantidade, unidade) -> None`.
- `consultar`, quando `conteudo_qtd` não é `NULL`, mostra uma coluna extra "preço por `conteudo_unidade`" (`valor_unitario / conteudo_qtd`) ao lado do preço cru — nunca substitui o preço cru, só complementa. Quando `conteudo_qtd` é `NULL` (a maioria dos produtos, no começo), a coluna simplesmente não aparece — sem tentar adivinhar.

**Achado real vs. caso ilustrativo — não confundir os dois.** Nos 3 recibos reais, `REFRI PEPSI PET 2L` (R$6,99 → R$3,50/L) e `REFRI ANT GUARANA PET 1.5L` (R$4,99 → R$3,33/L) têm tamanhos diferentes, mas nesse caso específico o Guaraná já é mais barato tanto no preço cru quanto no preço por litro — **não existe, nos dados reais, um caso onde a ordem muda** entre "mais barato no total" e "mais barato por conteúdo". O caso que realmente demonstra por que a funcionalidade importa é o do usuário (hipotético, não vem dos 3 arquivos): 20 ovos por R$12,00 (R$0,60/ovo) vs. 30 ovos por R$16,50 (R$0,55/ovo) — o pacote maior parece mais caro no total e é mais barato por unidade. Isso vira um fixture sintético nos testes (seção abaixo), não um fixture real.

### Camada opcional de IA (assistência em ambiguidades, nunca decisão automática)

**Pedido explícito do usuário nesta sessão**: projetar já a costura pra um dia acoplar uma LLM barata, que ajude nas situações não-determinísticas que este design já rejeitou resolver sozinho (fusão de produto, tag, conteúdo ambíguo) — sem gastar mais que **US$1/mês**. Escopo: só a interface/contrato, sem implementar chamada nenhuma agora.

**A regra que faz o orçamento de US$1/mês ser real: IA só é chamada em pontos de baixa frequência, nunca no caminho de leitura.** `consultar` roda várias vezes por dia — nunca chama IA. `importar` roda quando o usuário vai ao mercado (algumas vezes por mês) — pode chamar IA só pra itens novos/ambíguos daquela nota. Comandos que o próprio usuário aciona sob demanda (`produtos comparar`) também servem, porque a frequência é controlada por quem paga a conta. Essa regra é o que impede uma sessão futura de "melhorar a busca" plugando IA em todo `consultar` e estourando o orçamento sem querer.

**Por que `urllib.request` da stdlib, não um SDK de provedor.** É uma chamada HTTP simples (um POST, um JSON de resposta, sem streaming) e baixíssima frequência — o caso raro em que stdlib já é menos código do que configurar e importar um SDK (o oposto do que aconteceu com Typer, onde o framework poupava trabalho real). Padronizar no formato REST `/chat/completions` (compatível com vários provedores baratos) é toda a "abstração de provedor" necessária — trocar de provedor é trocar `base_url`/`api_key`/`model` na config, sem registry nem plugins.

**Não decidido aqui, de propósito: qual provedor/modelo.** Preço de API muda com frequência e não tenho como validar valor atual nesta sessão — isso é decisão de implementação, a revisitar checando preço real na hora. Candidatos conhecidos por serem historicamente baratos por token (não é recomendação fechada): camadas "mini"/"flash"/"nano" dos provedores grandes, ou provedores especializados em inferência barata. Conta de padaria: um catálogo pessoal gera no máximo algumas dezenas de chamadas curtas por mês (import-time, não toda busca) — a maioria dos modelos de camada barata deixa isso na casa de centavos de dólar, não dólares. Ainda assim o orçamento é reforçado por código, não por confiança na estimativa (próximo parágrafo).

**Orçamento reforçado com um contador persistido, não com confiança na estimativa:** tabela `ai_usage(month TEXT PK 'YYYY-MM', spent_usd REAL)` — já faz parte do schema v1 (ver "Armazenamento"). Antes de qualquer chamada: lê `spent_usd` do mês corrente; se já bateu o orçamento configurado, **não liga pra API, retorna "sem sugestão"**. Depois de uma chamada real: soma o custo estimado (tokens de entrada/saída da resposta × preço por token configurado). Preço por token não é hardcoded (mudaria toda vez que o provedor reajustar) — vem de variável de ambiente.

**Configuração — tudo por variável de ambiente, tudo opt-in** (lida uma vez por `julius/config.py` → `Config`; testado em `tests/test_config.py`):
- `JULIUS_AI_API_KEY` — não configurada = IA inteira desligada, silenciosamente (`Config.ai_configured` exige key + base_url + model). Sem isso o sistema funciona 100% igual a hoje.
- `JULIUS_AI_BASE_URL`, `JULIUS_AI_MODEL` — endpoint e modelo (compatível `/chat/completions`).
- `JULIUS_AI_BUDGET_USD` — default `1.0`.
- `JULIUS_AI_INPUT_PRICE_USD_PER_1M`, `JULIUS_AI_OUTPUT_PRICE_USD_PER_1M` — preço por milhão de tokens, pra calcular o gasto real depois de cada chamada.

**Duas peças, não uma — separação que o esqueleto anterior errou.** Rede é infra; orçamento é regra de negócio + persistência. Misturar os dois obrigaria o cliente HTTP a conhecer o banco.
- `julius/infra/llm_client.py` — `Protocol LlmClient` com `complete(system_prompt, user_prompt) -> LlmResponse | None` (`LlmResponse`: `text`, `input_tokens`, `output_tokens`). A implementação HTTP (`urllib.request`) vem num ticket próprio. É `Protocol` porque teste de serviço substitui a rede por um fake.
- `julius/services/suggestions.py` — recebe `conn`, `Config` e um `LlmClient`; checa `ai_usage`, monta prompts, interpreta a resposta, registra o gasto.

**Invariante mais importante — nem `LlmClient` nem `services/suggestions.py` lançam exceção.** Chave ausente, orçamento estourado, erro de rede, resposta malformada: tudo vira `None` (ou lista vazia), nunca uma exception subindo pro chamador. Todo serviço que consulta sugestões trata `None` como "sem sugestão" e cai no comportamento determinístico. É essa propriedade que garante que esquecer de configurar (ou de recarregar) a chave nunca quebra o sistema — ele só fica sem a ajuda extra.

`services/suggestions.py` expõe (assinaturas, não implementação):

- `is_available(conn, config) -> bool` — `config.ai_configured` e orçamento do mês não estourado.
- `suggest_merge(conn, config, client, description_a, description_b) -> MergeSuggestion | None` — `MergeSuggestion`: `same_product: bool`, `confidence: float`, `rationale: str`. Usado só por `julius produtos comparar`, sob pedido explícito do usuário (ver reconciliação na seção "Identidade de produto e busca" — isso não é a sugestão automática já rejeitada).
- `suggest_content(conn, config, client, description) -> ContentSuggestion | None` — `ContentSuggestion`: `quantity: float`, `unit: "L"|"KG"|"UN"`, `confidence: float`. Chamado no `importar`, só para descrições que já batem um padrão ambíguo conhecido (tipo `\d+G C/\d+UN`) — resultado é impresso como sugestão, quem grava de fato continua sendo `julius produtos definir-conteudo`, chamado pelo usuário.
- `suggest_tags(conn, config, client, description, existing_tags) -> list[str]` — lista vazia se indisponível. Sugestão mostrada junto do produto novo no fim do `importar`; gravar a tag continua exigindo `julius produtos tag`.

**Cortado de propósito: classificar automaticamente um código de unidade novo (`Gf`, `PC`, etc.) via IA.** O mapa de unidade é uma constante curada no código-fonte, editada por um humano quando aparece um código novo — evento raro (surgiu 1x em 5 notas). Gastar uma chamada de rede e checagem de orçamento só pra decorar uma mensagem de erro é máquina demais pra um evento que já falha alto e claro sozinho; se quiser uma opinião da IA nesse momento, o usuário pode perguntar por fora, sem o sistema precisar saber fazer isso.

**Módulo novo**: `julius produtos comparar ID_A ID_B` — chama `suggestions.suggest_merge`; se IA indisponível, cai pra mostrar só a similaridade `rapidfuzz` entre os dois nomes lado a lado (ainda útil, só menos esperto). Nunca funde sozinho — `julius produtos fundir` continua sendo o único jeito de aplicar.

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
| `disponivel` · `sugerir_fusao` · `sugerir_conteudo` · `sugerir_tags` | `is_available` · `suggest_merge` · `suggest_content` · `suggest_tags` |
| `JULIUS_IA_*` · `precos.db` | `JULIUS_AI_*` (ver "Camada opcional de IA") · `prices.db` |

Path do banco: `Config.db_path` — variável de ambiente `JULIUS_DB`, default `~/.local/share/julius/prices.db` (`Path.home()`, stdlib puro — sem `platformdirs`, já que o alvo é só Linux). Sem flag `--db` em cada comando: é ferramenta de um usuário só, com um banco só; variável de ambiente já cobre testar em outro caminho se precisar.

### CLI — comando `julius` (Typer)

(nome escolhido pelo usuário: referência ao pai do Chris, em *Todo Mundo Odeia o Chris* — o cara que nunca deixa passar um preço.)

```
julius importar ARQUIVO...
julius consultar [TERMO] [--tag TAG] [--limite/-n INT = 20]
julius exportar [--saida/-o PATH = ./julius-export.csv]
julius mercados listar
julius mercados renomear CNPJ APELIDO
julius produtos listar
julius produtos renomear ID NOME
julius produtos fundir ORIGEM DESTINO
julius produtos tag ID TAG
julius produtos definir-conteudo ID QTD UNIDADE
julius produtos comparar ID_A ID_B
```

Nomes de comando em português (são UI); cada um mapeia pra uma função em inglês em `julius/cli/*.py` via `@app.command("importar")`. Todo comando abre a conexão com `infra.db.connect(config.load().db_path)` **dentro do handler** — nunca em import. Um comando só é registrado quando o serviço que ele chama existe (sem stub `NotImplementedError` exposto).

- **`julius importar ARQUIVO...`** — um ou mais arquivos HTML (variádico, de graça no Typer — resolve "import em lote" sem código extra). Chama `services.importing.import_receipts` por arquivo (uma transação cada; falha num não afeta os outros), imprime "N itens novos, M já existiam" por arquivo. Arquivo inexistente/HTML fora do formato/unidade desconhecida → erro claro, nada gravado.
- **`julius consultar [TERMO] [--tag TAG]`** — `TERMO` casa por similaridade (`rapidfuzz`, tolera termo parcial e erro de digitação); `--tag` filtra por categoria marcada manualmente (mecanismo separado — texto parecido não vira categoria, ver seção "Identidade de produto e busca"). Pelo menos um dos dois é obrigatório. `--limite/-n` limita linhas por grupo de unidade (default 20). Chama `services.search.search_prices`, renderiza com `rich.table.Table`: uma tabela por `unit` (nunca mistura UN com KG), colunas data/valor/apelido (+ preço por conteúdo quando existir), `highlight` colorido. Sem match → mensagem explícita, não tabela vazia.
- **`julius exportar`** — `--saida/-o` escolhe o caminho do CSV (default no diretório atual). Chama `services.export.export_csv`. Não é a fonte da verdade, só um dump legível/pra planilha.
- **`julius mercados listar`** — `catalog.list_stores`, tabela `cnpj / razão social / apelido`.
- **`julius mercados renomear CNPJ APELIDO`** — `catalog.rename_store`. É a correção que se repete (todo mercado novo nasce com apelido = razão social), por isso ganhou comando — diferente da correção de uma linha de preço errada, que continua sem comando dedicado (ver seção Decisões).
- **`julius produtos listar`** — `catalog.list_products`, tabela `id / nome / tags`. Ajuda a achar o `ID` pra usar em `renomear`/`fundir`/`tag`.
- **`julius produtos renomear ID NOME`** — `catalog.rename_product`. Pro nome automático (= descrição do primeiro import) não ficar feio pra sempre.
- **`julius produtos fundir ORIGEM DESTINO`** — `catalog.merge_products`. É a correção manual de "isso é o mesmo produto" (nunca sugerida automaticamente — ver seção "Identidade de produto e busca").
- **`julius produtos tag ID TAG`** — `catalog.tag_product`. Categorização manual (ex.: `limpeza`, `hortifruti`); não tem relação com a busca por texto, é outro mecanismo.
- **`julius produtos definir-conteudo ID QTD UNIDADE`** — `catalog.set_product_content`. Ver seção "Preço por conteúdo". Sem esse comando, `consultar` mostra só o preço cru — nunca adivinha o conteúdo pela descrição.
- **`julius produtos comparar ID_A ID_B`** — `catalog.compare_products`. Pede uma opinião (IA se configurada, senão `rapidfuzz`) sobre se dois produtos são a mesma coisa — só informa, quem funde é `julius produtos fundir`, comando separado. Único ponto do sistema com custo de IA opt-in por chamada explícita do usuário (ver seção "Camada opcional de IA").

### Empacotamento

`pyproject.toml` com `[project.scripts] julius = "julius.cli:app"` — depois de `.venv/bin/pip install -e '.[dev]'`, o comando `.venv/bin/julius` fica disponível sem `python -m` nem caminho de script. Dependências: `typer`, `rich`, `rapidfuzz`; dev: `pytest`. `infra/llm_client.py` não adiciona dependência — chamada HTTP via `urllib.request` da stdlib. `[tool.setuptools.package-data]` inclui os `.sql` (ver "Migração de schema").

### Fora do escopo v1 (de propósito)
Detecção automática de estado, comando de correção para linhas de preço (usa `sqlite3` direto), veredito automático de preço, lock de concorrência, flag `--db` por comando, `platformdirs`, **sugestão automática (não pedida) de fusão de produtos** (similaridade de string erra sabor/tamanho — sugestão sob pedido explícito via `produtos comparar` é diferente, ver seção "Camada opcional de IA"), **busca semântica/embeddings** (desproporcional pro tamanho do catálogo), **auto-classificação de tags sem confirmação** (sugestão via IA é diferente — grava só quando o usuário confirma com `produtos tag`), **extração automática de conteúdo/tamanho de embalagem da descrição** (números ambíguos ou irrelevantes no texto real — sugestão via IA precisa igual de confirmação por `definir-conteudo`), **classificar código de unidade novo via IA** (evento raro, curadoria manual do mapa já resolve, não vale o custo).

## Design de testes

Framework: **pytest** (mesma lógica do Typer — código pronto em vez de escrever mais, `unittest` da stdlib exige mais boilerplate pra fixture/parametrização). Fixtures: os **3 arquivos HTML reais** em `tests/fixtures/` (`qrcode.html`, `qrcode-2.html`, `qrcode-3.html`) + **1 fixture sintético** pro caso de embalagem (não existe nos dados reais, ver seção "Preço por conteúdo"; ainda por criar). Nenhum teste bate na internet — tudo roda em cima de arquivo local + SQLite em `tmp_path` (fixtures `db_path`/`conn` em `tests/conftest.py`).

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
├── prices.db      # Config.db_path (JULIUS_DB)
└── entrada/        # convenção, não obrigatória — onde salvar HTMLs baixados antes de importar
```
Não existe (nem precisa existir) uma variável tipo `JULIUS_ENTRADA` ou flag `--pasta`: `julius importar ARQUIVO...` já é variádico, então `julius importar ~/.local/share/julius/entrada/*.html` já funciona hoje — quem expande o `*` é o shell, não o Python. Adicionar uma segunda forma de apontar "de onde importar" seria dizer a mesma coisa duas vezes.

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
