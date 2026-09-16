# Pesquisa — bibliotecas/algoritmos pra v2.1 (`consultar` com tag em texto livre + log de consultas)

Data: 2026-09-16. Escopo: os requisitos fechados no `/sc:brainstorm` anterior (RF1–RF5, ver `CLAUDE.md`/histórico da conversa). Pergunta: qual solução de terceiros minimiza o código próprio necessário para implementar a v2.1.

## Resumo executivo

Os três blocos de trabalho da v2.1 — tag dentro do texto livre com tolerância a erro de digitação, múltiplas palavras sem aspas no `consultar`, e log de consultas — são resolvíveis quase inteiramente com o que **já está instalado e já está em uso neste repositório**: `rapidfuzz` e `typer` (dependências existentes) e o padrão já implementado em `julius/infra/ai_log.py`. **Nenhuma dependência nova é necessária.** O código genuinamente novo se reduz a: (1) uma função pequena que testa tokens do texto livre contra as tags conhecidas via `rapidfuzz`, (2) trocar a assinatura Typer de `term: Optional[str]` para `words: list[str]`, e (3) um novo call site reaproveitando `ai_log.append` com um payload diferente.

## RF1/RF2 — Detectar tag dentro do texto livre, tolerando erro de digitação

**Evidência primária (lida no código):**
- `julius/services/search.py::_matching_ids` já usa `rapidfuzz.process.extract(term, names_dict, scorer=fuzz.WRatio, score_cutoff=...)` pra casar termo contra nomes de produto.
- `julius/repositories/products.py::product_ids_with_tag` faz `WHERE t.name = ?` — comparação exata, sem `rapidfuzz`.
- Não existe, em nenhum lugar do projeto, um caminho que teste palavras individuais de um texto contra uma lista pequena de tags.

**Alternativas avaliadas:**

| Opção | O que é | Avaliação |
|---|---|---|
| **`rapidfuzz.process.extractOne`/`extract`** (já é dependência) | Aceita `choices` como lista/dict, `scorer` e `score_cutoff`; devolve o melhor match ou `None` | Resolve RF1+RF2 direto: `process.extractOne(token, tags, scorer=fuzz.ratio, score_cutoff=X)`. Zero dependência nova, mesma API já usada duas linhas acima no mesmo arquivo. |
| `fuzzywuzzy` | Predecessor do rapidfuzz, mesma API, mais lento, GPL | O rapidfuzz nasceu como substituto direto; não há motivo pra ter as duas libs. |
| `symspellpy` (SymSpell) | Correção ortográfica via edit-distance pré-computado, pensado pra dicionários de milhões de palavras | Desproporcional pra 13 tags — o ganho de performance existe numa escala que este projeto não tem. Mesmo raciocínio que já rejeitou FTS5/embeddings no `CLAUDE.md`. |
| `spaczz` / `DeezyMatch` | Fuzzy matching sobre NLP pipeline (spaCy) ou deep learning | Exigem modelo de linguagem/ML pra decidir se "laticinio" bate com "laticinios". Viola diretamente o "busca semântica: desproporcional" já registrado no design do projeto. |
| Motor de busca com facetas (Whoosh, Elasticsearch, Algolia) | Índice de busca com suporte nativo a facetas | Já indiretamente rejeitado (`FTS5` descartado por infraestrutura desproporcional ao volume). Resolveria "de fábrica", por um custo de infraestrutura ilegítimo pra ferramenta de um usuário só. |

**Recomendação:** nenhuma lib nova. Função pequena (~10–15 linhas) em `services/search.py`, no mesmo módulo que já tem `_matching_ids`, chamando `process.extractOne` por token contra os nomes de tag. O cutoff dedicado ainda precisa ser **medido** contra as 13 tags reais — isso é medição, não escolha de biblioteca, e já está registrado como questão aberta.

## RF3 — múltiplas palavras sem aspas (`julius consultar leite laticinio`)

**Achado de pesquisa:** hoje `search()` em `cli/receipts.py` declara `term: Optional[str]` — um único argumento posicional. Digitar `julius consultar leite laticinio` sem aspas **já falha hoje** (Typer/Click recebe dois argv pra um parâmetro só). Isso não tinha aparecido no brainstorm anterior.

A correção não precisa de biblioteca nova: o próprio Typer resolve com anotação `list[str]`, igual a `julius importar ARQUIVO...` (`files: list[Path]`, já em `cli/receipts.py:22`). A documentação oficial confirma que um argumento posicional `list[...]` convive normalmente com opções nomeadas (`--tag`, `--limite`), já que opções não competem por posição — só conflitaria com outro argumento posicional obrigatório *depois* dele, o que não é o caso aqui.

**Recomendação:** `words: Annotated[list[str], typer.Argument()] = []`, depois `term = " ".join(words) or None`. Nenhuma lib de parsing adicional (nem `shlex`, nem `argparse` manual) — reaproveita o padrão que `import_receipts` já usa duas linhas abaixo, no mesmo arquivo.

## RF5 — log de consultas

**Achado de pesquisa mais forte do relatório:** `julius/infra/ai_log.py::append(path, record)` **já é genérico** — não menciona IA em nenhum lugar da assinatura ou do corpo, só grava qualquer `Mapping` como uma linha JSON em `path`, nunca lança exceção.

| Opção | Avaliação |
|---|---|
| **Reusar `ai_log.append` como está** | Zero código novo de infraestrutura — só um call site novo em `cli/receipts.py::search()` com payload diferente, apontando pra `~/.local/share/julius/query_log.jsonl`. |
| `structlog`/`loguru` | Bibliotecas maduras de logging estruturado, mas resolvem problemas (níveis, formatação, contexto aninhado) que este caso não tem — o projeto já tem o "formatter" necessário em 6 linhas. Dependência nova pra reimplementar 6 linhas já escritas é o oposto de "menos código". |
| `logging` (stdlib) + formatter JSON custom | Mais código de configuração (handlers/formatters) que a função já pronta. |
| Tabela SQL nova em `prices.db` | Viável e pesquisável por SQL, mas exige migração nova + repositório — mais trabalho que reaproveitar o JSONL. Só compensaria se "analytics de uso" precisasse de joins complexos, o que não é o caso. |

**Recomendação:** reaproveitar `ai_log.append` literalmente (renomear o módulo pra algo mais genérico é opcional, é troca de nome, não de código) gravando em `query_log.jsonl`, irmão do `ai_calls.jsonl`. Pra "quais produtos/tags mais consultados", `collections.Counter` (stdlib) sobre as linhas do JSONL responde sem precisar de pandas nem SQL.

## RF4 — flag de opt-out

Nada a pesquisar: `typer.Option(bool)`, mesma API que `julius importar --sim` já usa (`cli/receipts.py:24`). Só a flag + um `if`.

## Tabela-resumo — esforço por requisito

| Requisito | Lib nova? | Código genuinamente novo |
|---|---|---|
| RF1/RF2 (tag no texto livre, fuzzy) | Não — `rapidfuzz` já é dependência | 1 função pequena + 1 constante de cutoff (a medir) |
| RF3 (múltiplas palavras sem aspas) | Não — `typer` já é dependência | Trocar 1 assinatura de parâmetro + `" ".join()` |
| RF4 (flag opt-out) | Não | 1 `typer.Option(bool)` + 1 `if` |
| RF5 (log de consultas) | Não | 1 call site reaproveitando `ai_log.append` |

Nenhum item da v2.1 justifica dependência nova. "Menor esforço possível" já é o caminho natural: falta composição do que está instalado, não pesquisa de pacote externo.

## Riscos que a pesquisa não resolve (ficam pro `/sc:design`)

- O cutoff de tag (RF2) precisa ser **medido**, não escolhido de catálogo — nenhuma biblioteca faz isso por você; é o mesmo trabalho manual que já gerou `MATCH_SCORE_CUTOFF=70` e `NEAR_MISS_CUTOFF=70` nos 5 recibos reais.
- Tag multi-palavra (ex.: uma futura tag "frutas secas") exigiria testar janelas de N palavras, não só tokens únicos — ainda resolvido por `rapidfuzz`, só cresce a função de ~15 pra ~25 linhas.

## Fontes

- [rapidfuzz.process — RapidFuzz documentation](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html)
- [RapidFuzz GitHub — process_py.py](https://github.com/rapidfuzz/RapidFuzz/blob/main/src/rapidfuzz/process_py.py)
- [RapidFuzz vs FuzzyWuzzy — Medium](https://medium.com/@amarshaw83/rapidfuzz-339295aece71)
- [How lnx does fuzzy searching 5x faster with SymSpell](https://blog.cf8.gg/fuzzy-searching-5x-faster-with-symspell/)
- [DeezyMatch — PyPI](https://pypi.org/project/DeezyMatch/)
- [Typer docs — Arguments with multiple values](https://typer.tiangolo.com/tutorial/multiple-values/arguments-with-multiple-values/)
- Código do próprio projeto: `julius/services/search.py`, `julius/repositories/products.py`, `julius/cli/receipts.py`, `julius/infra/ai_log.py` (evidência primária, lida diretamente).
