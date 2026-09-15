# Julius

> *"Banana a R$ 12 o quilo… tá caro?"*
> Julius lembra por você. Ele guarda cada preço que você já pagou no mercado — a partir do cupom fiscal — e responde essa pergunta na hora, mostrando onde e quando você pagou menos.

Nome em homenagem ao pai do Chris em *Todo Mundo Odeia o Chris*: o cara que sabe o preço de tudo e nunca deixa passar um centavo.

---

## Índice

1. [O que ele faz](#o-que-ele-faz)
2. [Em 60 segundos](#em-60-segundos)
3. [Como funciona](#como-funciona)
4. [Guia de uso](#guia-de-uso)
5. [Conceitos que valem a pena entender](#conceitos-que-valem-a-pena-entender)
6. [Configuração](#configuração)
7. [IA opcional (e o teto de US$ 1/mês)](#ia-opcional-e-o-teto-de-us-1mês)
8. [Arquitetura](#arquitetura)
9. [Banco de dados](#banco-de-dados)
10. [Desenvolvimento](#desenvolvimento)
11. [Limitações conhecidas e próximos passos](#limitações-conhecidas-e-próximos-passos)

---

## O que ele faz

Toda compra de mercado gera um cupom fiscal eletrônico (NFC-e) com um QR code. Esse QR code leva a uma página da Receita com **cada item, quantidade, unidade e preço**. Julius lê essa página, guarda tudo num banco local e deixa você consultar depois:

- **"Quanto eu já paguei por picanha?"** — histórico por data e por mercado, com o menor e o maior preço destacados.
- **"Esse pacote de 30 ovos vale mais que o de 20?"** — preço por unidade, litro ou quilo, quando você informa o tamanho da embalagem.
- **"Onde a banana estava mais barata?"** — cada mercado (e cada filial) tem um apelido que você escolhe.

O que ele **não** é: não compara mercados em geral, não controla orçamento, não dá veredito automático de "caro" ou "barato". Ele mostra o histórico; quem decide é você.

Funciona 100% offline, num arquivo SQLite no seu computador. Nada sai da sua máquina, a menos que você ligue a camada opcional de IA.

---

## Em 60 segundos

```bash
# 1. instalar (Python 3.10+ e pipx) — deixa o comando `julius` disponível em qualquer pasta
git clone <este-repo> && cd precos-dos-mercados
make install

# 2. importar um cupom (veja "Como pegar o HTML" abaixo)
julius importar ~/Downloads/cupom.html
#   cupom.html: 20 itens novos, 0 já existiam

# 3. perguntar
julius consultar tomate
```

Sem `pipx`? `python3 -m venv .venv && .venv/bin/pip install -e .` e use `.venv/bin/julius`.

```
                                Preços por KG
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Data       ┃ Produto                  ┃ Mercado                ┃ Preço    ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━┩
│ 2026-09-12 │ TOMATE ITALIANO UNIAO kg │ FL3 Costa Águas Claras │ R$ 11,89 │  ← verde
│ 2026-09-07 │ TOMATE ITALIANO kg       │ Dona de Casa Guará     │ R$ 14,99 │  ← vermelho
└────────────┴──────────────────────────┴────────────────────────┴──────────┘
                              Preços por UN
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Data       ┃ Produto                   ┃ Mercado            ┃ Preço   ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ 2026-09-07 │ TOMATE TREBESCHI 250G DUO │ Dona de Casa Guará │ R$ 9,90 │
└────────────┴───────────────────────────┴────────────────────┴─────────┘
```

Tomate por quilo e tomate em bandeja nunca vão para a mesma tabela — e o menor e o maior preço de cada uma ficam destacados. Digitou errado? `julius consultar pcanha` acha picanha do mesmo jeito.

### Como pegar o HTML do cupom

1. Aponte a câmera para o QR code do cupom. Ele abre uma página da Receita (no DF: `ww1.receita.fazenda.df.gov.br/...`).
2. Passe pelo captcha, se aparecer.
3. No navegador, **Salvar página como…** → qualquer opção serve (só HTML ou página completa). Julius lê apenas o `.html`; a pasta `_files` que vem junto pode ser apagada.
4. Guarde os arquivos onde quiser. Sugestão: `~/.local/share/julius/entrada/`. Depois: `julius importar ~/.local/share/julius/entrada/*.html`.

Por que não baixar direto pela URL? Porque a página passa por captcha — automatizar isso seria frágil e provavelmente contra os termos do site. Salvar o HTML leva cinco segundos e funciona sempre.

---

## Como funciona

```mermaid
flowchart LR
    QR([QR code do cupom]) --> HTML[Página da Receita<br/>salva como .html]
    HTML -->|julius importar| DB[(prices.db<br/>SQLite local)]
    DB -->|julius consultar| T[Tabela por unidade<br/>menor e maior destacados]
    DB -->|julius exportar| CSV[CSV para planilha]
    DB -->|julius mercados / produtos| C[Você ajusta apelidos,<br/>tags, embalagens, fusões]
```

Três ideias sustentam tudo:

1. **Importar é idempotente.** Cada linha do cupom tem uma chave única (`chave de acesso + posição do item`). Importar o mesmo arquivo duas vezes não duplica nada — só avisa "já existiam".
2. **Nada é adivinhado.** O parser lê o que está no HTML. Tamanho de embalagem, categoria e "esses dois produtos são a mesma coisa" são decisões suas, feitas por comandos explícitos. Onde a heurística erraria em silêncio, Julius prefere não fazer.
3. **Unidades nunca se misturam.** Preço por quilo e preço por unidade vivem em tabelas separadas na consulta. R$ 12/kg não é comparável com R$ 12 a unidade, e o sistema não finge que é.

---

## Guia de uso

Todos os comandos têm `--help`. Nomes em português porque são a interface; o código por baixo é em inglês.

### `importar` — trazer cupons para dentro

```bash
julius importar cupom1.html cupom2.html          # vários de uma vez
julius importar ~/.local/share/julius/entrada/*.html
```

- Reporta por arquivo: `cupom1.html: 20 itens novos, 0 já existiam`.
- Se um arquivo falhar (não existe, HTML fora do formato, unidade desconhecida), imprime o erro em `stderr`, **continua os outros** e termina com código 1.
- Um arquivo com problema nunca grava nada, nem parcialmente — o parse acontece inteiro antes de qualquer escrita.

### `consultar` — a pergunta principal

```bash
julius consultar banana                # por nome (parcial, tolera erro de digitação)
julius consultar --tag hortifruti      # por categoria que você marcou
julius consultar leite --tag laticinio # os dois: interseção
julius consultar arroz -n 5            # só as 5 compras mais recentes por unidade
```

- Uma tabela por unidade de venda (`KG`, `UN`).
- Linhas mais recentes primeiro. A linha de **menor preço fica verde**, a de **maior fica vermelha** — e essas duas sempre aparecem, mesmo que sejam mais antigas que o `-n` pede.
- Se o produto tem embalagem definida (veja `produtos definir-conteudo`), surge a coluna **Por L / Por KG / Por UN**.
- Sem resultado: `Nenhum resultado.` — não uma tabela vazia.

### `mercados` — dar nome aos lugares

O cupom traz só a razão social ("FL 3 COSTA MULTICANAL S A"). Você quer ver "Atacadão Águas Claras".

```bash
julius mercados listar
julius mercados renomear 27.289.076/0013-79 "Atacadão Águas Claras"   # CNPJ formatado ou só dígitos
```

Filiais são CNPJs diferentes, e Julius as trata como mercados diferentes de propósito — os preços variam entre lojas da mesma rede. Vale pôr o bairro no apelido.

### `produtos` — cuidar do catálogo

```bash
julius produtos listar                          # id, nome, conteúdo, tags
julius produtos renomear 14 "Suco de uva integral 1,5 L"
julius produtos tag 14 bebidas                  # categoria livre, minúscula
julius produtos definir-conteudo 14 1.5 L       # L, ML, KG, G ou UN
julius produtos definir-conteudo 27 500 G       # gravado como 0,5 KG
julius produtos comparar 14 31                  # "são a mesma coisa?" — só opina
julius produtos fundir 31 14                    # 31 desaparece, 14 fica com todo o histórico
julius produtos fundir 31 14 --sim              # sem pedir confirmação
```

- **Nome**: nasce igual à descrição do primeiro cupom (`SUCO INT PARREIRAS DO SUL GF 1.5L UVA`). Renomeie quando cansar de ler abreviação.
- **Tag**: é o único jeito de agrupar por categoria. Busca por texto não sabe que "detergente" é "limpeza"; a tag sabe.
- **Conteúdo**: habilita a coluna de preço por litro/quilo/unidade. `G` e `ML` são convertidos para `KG` e `L` na hora de gravar, para todo o catálogo falar a mesma língua.
- **Fundir**: irreversível — por isso pede confirmação. Use quando o mesmo produto aparece com códigos diferentes em mercados diferentes.
- **Comparar**: dá similaridade de texto e, se a IA estiver configurada, uma opinião. Nunca funde sozinho.

### `exportar` — levar para a planilha

```bash
julius exportar                        # ./julius-export.csv
julius exportar -o ~/precos.csv
```

CSV com `;` como separador (o Excel em português abre direto), uma linha por item comprado, com apelido do mercado e nome do produto já resolvidos. É uma cópia para leitura — o banco continua sendo a fonte da verdade.

### Corrigir um preço errado

Não há comando para isso, de propósito: é raro, e o `sqlite3` já vem instalado.

```bash
sqlite3 ~/.local/share/julius/prices.db
sqlite> UPDATE prices SET unit_price = 4.99 WHERE access_key = '5326…' AND item_index = 3;
```

---

## Conceitos que valem a pena entender

**Produto = código do produto *dentro de um mercado*.** O código `4134` é desengordurante numa loja e brócolis em outra — aconteceu de verdade nos cupons de teste. Por isso um produto novo é criado por par `(CNPJ, código)`, e o mesmo item recomprado no mesmo mercado sempre cai no mesmo produto. Juntar produtos de mercados diferentes é decisão sua (`fundir`).

**Por que a fusão não é automática.** Similaridade de texto acha que `SUCO … 1.5L UVA` e `SUCO … 1.5L LARANJA` são quase iguais. Sabor e tamanho são justamente o que muda o preço. Uma sugestão que erra isso ensinaria você a ignorá-la — então ela só aparece quando você pede (`comparar`).

**Por que o tamanho da embalagem não é lido da descrição.** `PRATO REDOND DESC 21CM` tem um número que é diâmetro. `CHA CX 16G C/10UN` pode ser 16 g o sachê ou a caixa. Um regex que acerta às vezes e erra em silêncio destruiria a confiança no número — e confiança é o produto inteiro.

**Códigos de unidade variam por rede.** `UN1`/`KG1` num mercado, `Un`/`Kg`/`PC`/`Gf` em outro. Julius traduz por um mapa curado (`PC` e `Gf` são "vendido inteiro", logo `UN`). Um código nunca visto **interrompe o import com erro claro** em vez de chutar — e a correção é uma linha em `julius/domain/normalization.py`.

**Duas datas no cupom.** "Emissão" é quando você comprou; "Data/Hora da Consulta" é quando você abriu a página. Só a primeira importa.

**O destaque é relativo à unidade, não ao produto.** Buscar "água" pode trazer água com gás e água mineral na mesma tabela `UN`; o verde e o vermelho marcam os extremos daquela tabela. Se quiser ver um produto só, seja mais específico no termo ou use tags.

---

## Configuração

Tudo por variável de ambiente. Sem nenhuma, Julius funciona com os padrões.

| Variável | Padrão | Para quê |
|---|---|---|
| `JULIUS_DB` | `~/.local/share/julius/prices.db` | Caminho do banco. Útil para experimentar com outro arquivo sem tocar no seu histórico. |
| `JULIUS_AI_API_KEY` | — | Liga a IA. Ausente = IA desligada, silenciosamente. |
| `JULIUS_AI_BASE_URL` | — | Endpoint compatível com `/chat/completions`. |
| `JULIUS_AI_MODEL` | — | Nome do modelo. |
| `JULIUS_AI_BUDGET_USD` | `1.0` | Teto de gasto por mês. |
| `JULIUS_AI_INPUT_PRICE_USD_PER_1M` | — | Preço por milhão de tokens de entrada (obrigatório para a IA rodar). |
| `JULIUS_AI_OUTPUT_PRICE_USD_PER_1M` | — | Idem, saída. |

O banco e a pasta são criados no primeiro comando que precisa deles. Importar a CLI (ou rodar `--help`) não toca em disco — há teste garantindo isso.

---

## IA opcional (e o teto de US$ 1/mês)

Julius foi desenhado para custar zero. A IA existe para as três coisas que ele se recusa a decidir sozinho — e só **sugere**; gravar continua sendo um comando seu:

| Situação | O que a IA faz | Quem grava |
|---|---|---|
| "Esses dois produtos são iguais?" | `produtos comparar` mostra a opinião dela | você, com `produtos fundir` |
| Tamanho de embalagem ambíguo | `suggest_content` está pronta no código | você, com `definir-conteudo` |
| Categoria de um produto novo | `suggest_tags` está pronta no código | você, com `produtos tag` |

Hoje só `comparar` chama a IA de fato; as outras duas ficaram prontas mas desligadas até se provarem úteis.

**Como o teto vira realidade, não promessa:**

- A IA nunca roda em `consultar` (que você usa várias vezes ao dia). Só em ações raras e explícitas.
- Cada chamada registra seu custo (tokens × preço configurado) na tabela `ai_usage`, por mês. Antes de qualquer chamada, se o mês já bateu o orçamento, ela simplesmente não acontece.
- Sem os preços por token configurados, a IA não roda — não dá para debitar o que não se sabe medir.
- **Nenhuma falha de IA quebra nada.** Sem chave, sem rede, resposta malformada, orçamento estourado: tudo vira "sem sugestão" e o comando segue com o caminho determinístico.

Qualquer provedor que fale o formato `/chat/completions` serve. A escolha de modelo é sua; modelos das camadas "mini"/"flash" costumam custar centavos por mês nesse volume.

---

## Arquitetura

Camadas com dependências em um só sentido — um grafo acíclico, checado por teste (`tests/test_architecture.py` falha se alguma camada importar o que não deve).

```mermaid
flowchart TB
    subgraph cli["cli/ — interface (Typer + rich)"]
        direction LR
        c_receipts["receipts.py<br/>importar · consultar · exportar"]
        c_stores["stores.py<br/>mercados …"]
        c_products["products.py<br/>produtos …"]
    end

    subgraph services["services/ — casos de uso (devolvem dados, nunca imprimem)"]
        direction LR
        s_importing["importing.py"]
        s_search["search.py<br/>rapidfuzz · highlight por unidade"]
        s_catalog["catalog.py<br/>renomear · fundir · tag · conteúdo · comparar"]
        s_export["export.py"]
        s_suggestions["suggestions.py<br/>orçamento + prompts"]
    end

    subgraph repositories["repositories/ — SQL por agregado (funções que recebem conn)"]
        direction LR
        r_stores["stores.py"]
        r_products["products.py<br/>SKUs · tags · conteúdo"]
        r_prices["prices.py"]
        r_ai["ai_usage.py"]
    end

    subgraph parsers["parsers/"]
        p_proto["ReceiptParser (Protocol)"]
        p_df["df.py — DFReceiptParser"]
    end

    subgraph infra["infra/"]
        i_db["db.py<br/>SQLite · migrações · backup"]
        i_llm["llm_client.py<br/>LlmClient (Protocol) · HttpLlmClient"]
    end

    subgraph domain["domain/ — puro, sem I/O"]
        d_models["models.py<br/>Store · Product · Receipt · PriceRecord …"]
        d_norm["normalization.py<br/>UNIT_MAP · decimais pt-BR · texto"]
    end

    config["config.py<br/>env → Config"]

    cli --> services
    cli --> parsers
    cli --> infra
    cli --> config
    services --> repositories
    services --> parsers
    services --> infra
    services --> domain
    repositories --> domain
    parsers --> domain
    infra --> domain
    infra --> config
```

### O que cada camada pode e não pode

| Camada | Responsabilidade | Pode importar |
|---|---|---|
| `domain/` | Tipos imutáveis e regras puras (normalizar unidade, decimal, texto). Zero I/O. | só stdlib |
| `config.py` | Ler variáveis de ambiente para um `Config` imutável. | só stdlib |
| `infra/` | Falar com o mundo: arquivo SQLite, HTTP. | `domain`, `config` |
| `parsers/` | Transformar o HTML de um estado num `Receipt` já normalizado. | `domain` |
| `repositories/` | SQL de um agregado. Sem regra de negócio. | `domain` |
| `services/` | Casos de uso: orquestram parser + repositórios, aplicam as regras. | tudo acima |
| `cli/` | Traduzir argumentos em chamadas de serviço e dados em tabelas. É o *composition root*: o único lugar que instancia o parser e o cliente de IA concretos. | `services`, `parsers`, `infra`, `config`, `domain` |

### Decisões que explicam a forma do código

- **`Protocol` só onde há segunda implementação plausível**: `ReceiptParser` (outros estados virão) e `LlmClient` (testes trocam a rede por um fake). Repositórios e serviços são funções — a conexão SQLite *é* a injeção de dependência.
- **Um módulo por agregado / por caso de uso**, em vez de uma classe `Service` com quinze métodos. Cada funcionalidade nova toca um arquivo, não o mesmo arquivo de sempre.
- **Regras de negócio moram em `services/`.** "Nunca misturar UN com KG", "destacar menor e maior", "normalizar tag para minúsculas" — nada disso está no SQL nem na CLI.
- **Zero efeito colateral em import.** Nenhum módulo abre banco ou lê env ao ser importado; tudo acontece dentro do handler do comando.

### O caminho de um cupom

```mermaid
sequenceDiagram
    actor U as Você
    participant C as cli/receipts.py
    participant P as parsers/df.py
    participant S as services/importing.py
    participant R as repositories/*
    participant DB as SQLite

    U->>C: julius importar cupom.html
    C->>S: import_receipt(conn, path, DFReceiptParser())
    S->>P: parse(html, source="cupom.html")
    P-->>S: Receipt (loja + itens já normalizados)
    Note over S,DB: só agora abre a transação — parse inválido nunca grava nada
    S->>R: ensure_store · resolve_product_id · insert_price (por item)
    R->>DB: INSERT OR IGNORE …
    S-->>C: ImportResult(new_items=20, existing_items=0)
    C-->>U: cupom.html: 20 itens novos, 0 já existiam
```

---

## Banco de dados

Um arquivo SQLite. Chaves estrangeiras ligadas em toda conexão (`PRAGMA foreign_keys = ON`) — o banco recusa um preço apontando para um mercado inexistente, em vez de o código ter que lembrar de checar.

| Tabela | O que guarda | Chave |
|---|---|---|
| `stores` | mercados: CNPJ, razão social, apelido | `cnpj` |
| `products` | catálogo: nome canônico, conteúdo da embalagem | `id` |
| `product_skus` | qual código de qual mercado é qual produto | `(store_cnpj, product_code)` |
| `tags` / `product_tags` | categorias manuais | — |
| `prices` | **uma linha por item comprado**: data, mercado, produto, quantidade, unidade, preço | `(access_key, item_index)` |
| `ai_usage` | gasto de IA por mês | `month` |

A chave de `prices` é o que torna o import idempotente: `INSERT OR IGNORE` e pronto, sem consulta prévia.

### Migrações

O schema evolui por arquivos `julius/infra/migrations/000N_*.sql`, aplicados em ordem; a versão vigente fica no `PRAGMA user_version` do próprio arquivo. Isso roda em toda conexão:

- banco novo → cria tudo na versão atual;
- banco em dia → não faz nada;
- banco atrasado → **copia o arquivo para `prices.db.bak-vN` antes** de aplicar o que falta.

Adicionar uma migração é soltar um `.sql` novo na pasta. O backup é a rede de segurança real; nada apaga backups antigos por você.

---

## Desenvolvimento

```bash
make test        # cria o .venv/ na primeira vez e roda os ~220 testes (< 3 s)
make install     # `julius` global via pipx, em modo editável: editar o código já vale
make uninstall
```

Sem `make`: `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/pytest -q`.

Dependências: `typer`, `rich`, `rapidfuzz`. Dev: `pytest`. Nada mais — HTTP é `urllib`, CSV é `csv`, banco é `sqlite3`.

### Convenções

- **Código em inglês** (módulos, funções, variáveis, colunas SQL, env vars). **Português só no que o usuário lê** (nomes de comando, `--help`, mensagens, docs). Um comando `importar` chama uma função `import_receipts`.
- **Todo módulo com lógica nasce com teste de caminho feliz e triste.** Banco real em `tmp_path`, nunca mock de SQLite; rede sempre substituída por fake.
- **Comentário só para o porquê não óbvio.** Nada de narrar o que o código já diz.
- **Sem `NotImplementedError`.** O que não existe, não existe.

### Testes que valem conhecer

| Arquivo | Garante |
|---|---|
| `test_architecture.py` | as setas do diagrama de camadas — inspeciona imports de todo módulo |
| `test_cli.py` | `import julius.cli` não cria arquivo nenhum (roda em subprocesso) |
| `test_parser_df.py` | os 5 cupons reais em `tests/fixtures/` parseiam com contagens, datas e unidades exatas |
| `test_db.py` | FKs, `CHECK`s, PK de deduplicação e o backup antes de migrar |
| `test_e2e.py` | os fluxos inteiros pela CLI, incluindo o caso "30 ovos por R$ 16,50 é mais barato por unidade que 20 por R$ 12,00" |

Fixtures são só o `.html` — nunca a pasta `_files/` que o navegador salva junto.

### Como estender

**Um novo código de unidade** (`LT`, `CX`…): uma linha em `UNIT_MAP`, `julius/domain/normalization.py`. O import vai ter falhado alto com o código exato na mensagem.

**Um novo estado**: implemente o `Protocol ReceiptParser` em `julius/parsers/<uf>.py` devolvendo um `Receipt` normalizado. Hoje a CLI instancia `DFReceiptParser` direto; escolher o parser pelo conteúdo do HTML é o próximo passo natural quando houver dois.

**Uma mudança de schema**: `julius/infra/migrations/0002_descricao.sql`. Nada mais a registrar.

**Um novo caso de uso**: função em `services/`, recebendo `conn` primeiro, devolvendo dataclasses de `domain/`. Depois um comando fino em `cli/` que só formata.

### Histórico do desenho

`CLAUDE.md` guarda o raciocínio completo — requisitos, cada decisão e cada alternativa rejeitada (por que SQLite e não CSV, por que `rapidfuzz` e não FTS5, por que não extrair conteúdo da descrição), além das pegadinhas encontradas nos cupons reais. `docs/tickets/julius-v1/` tem os 14 tickets que geraram o código, na ordem da DAG.

---

## Limitações conhecidas e próximos passos

**Hoje**

- Só o layout de NFC-e do **Distrito Federal**. Outros estados têm HTML diferente.
- Descrições vêm abreviadas do cupom (`LING FGO RESF AURORA kg`). A busca tolera erro de digitação, mas "linguiça" por extenso não acha `LING` — renomeie os produtos que você consulta muito.
- Se a Receita mudar o layout da página, o parser quebra — com erro claro, não em silêncio, e os cupons reais em `tests/fixtures/` mostram exatamente o que mudou.
- Em `consultar`, empates no menor/maior preço mantêm todas as linhas empatadas mesmo fora do `-n`.
- A camada de IA está testada contra fakes, mas ainda não foi usada com um provedor real.

**Evoluções plausíveis** (nenhuma prometida)

- Parsers para outros estados, com seleção automática pelo HTML.
- `julius produtos pendentes` para revisar produtos sem tag nem conteúdo.
- Dica automática de conteúdo quando a descrição traz `C/30` (contém 30) — a função já existe, falta decidir se ajuda ou atrapalha.
- Um bot (Telegram) recebendo o HTML e chamando os mesmos serviços — a CLI foi feita para ser *uma* interface, não a única.
