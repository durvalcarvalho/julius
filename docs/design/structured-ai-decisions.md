# Design: camada de decisão de IA estruturada (TypeSafe/Jev)

**Baseado em**: `docs/requirements/structured-ai-decisions.md`. Decisão de mecanismo tomada via diálogo (2026-09-21): **gate único** — o `noul` do Jev substitui o julgamento do DeepSeek na decisão de auto-fusão, mas só depois de uma fase de validação medida contra o catálogo real ("antes faça medições, prova de conceito. Queremos melhorar o sistema, e não piorá-lo" — palavras do usuário). Isso vira o eixo do design inteiro: **todo ponto novo entra em modo `shadow` por padrão e só é promovido a `active` por decisão explícita, depois de critério de graduação medido.**

Nenhum código é escrito nesta etapa — este documento define interfaces, esquema e fluxo para `/sc:implement`.

## 1. Onde a camada vive na DAG existente

```
julius/
├── infra/
│   ├── llm_client.py        # já existe — geração de texto livre (DeepSeek)
│   └── decision_client.py   # NOVO — decisão tipada (Choice/Noul), hoje só TypeSafe/Jev
├── repositories/
│   └── decision_usage.py    # NOVO — orçamento por provedor (paralelo a ai_usage.py)
├── infra/migrations/
│   └── 0005_decision_usage.sql   # NOVO
├── services/
│   ├── curation.py          # passa a receber decision_client opcional
│   └── suggestions.py       # idem
```

Mesma regra de DAG já documentada: só `infra/` conhece o transporte HTTP do TypeSafe; `services/` só conhece a interface `DecisionClient`. Trocar de provedor (ou desligar) nunca toca `services/`.

## 2. Interface `DecisionClient` (infra/decision_client.py)

Paralela a `LlmClient`, mesmo idioma: **nunca lança exceção**, toda falha vira campo `error` preenchido — mesma disciplina que já existe para o cliente DeepSeek.

```python
@dataclass(frozen=True)
class NoulResult:
    value: float | None       # 0.0–1.0; None quando error preenchido
    error: str | None = None  # "HTTP 429" / "timeout" / "budget exceeded" / etc.

@dataclass(frozen=True)
class ChoiceResult:
    choice: str | None
    confidence: float | None
    probabilities: dict[str, float] | None
    error: str | None = None

class DecisionClient(Protocol):
    def ask_noul(self, state: str, instructions: str) -> NoulResult: ...
    def ask_choice(self, state: str, instructions: str, criteria: dict[str, str]) -> ChoiceResult: ...
```

Nota de escopo: **Score não é implementado agora** — nenhum dos três casos de uso precisa. O `Protocol` fica pronto pra ganhar `ask_score` no dia em que aparecer um caso real (mesma disciplina de não construir para hipótese).

`TypeSafeDecisionClient` (implementação): `urllib.request`, sem SDK — um `POST` para `config.typesafe_base_url`, corpo `{"state", "model", "questions": {"q": {...}}}`, timeout curto (a medição real ficou em 600–900ms). Cada pergunta é **uma chamada HTTP** (o `state` do TypeSafe é por request; não dá pra propor N pares como N perguntas isoladas de um state só, porque cada par tem seu próprio "state") — diferente do `suggest_merges` do DeepSeek, que hoje já manda vários pares numa chamada só. Consequência aceita: uma rodada de `produtos revisar` com ~20 candidatos faz ~20 chamadas sequenciais de <1s — 10–15s de review, aceitável para um comando interativo esporádico, não um caminho quente.

## 3. Config (extensão de `julius/config.py`)

| Variável | Default | Uso |
|---|---|---|
| `JULIUS_TYPESAFE_API_KEY` | — | ausente = camada inteira desligada, silenciosamente (`Config.typesafe_configured`) |
| `JULIUS_TYPESAFE_BASE_URL` | `https://api.typesafe.ai/v1/systemone` | mesma disciplina do `JULIUS_AI_BASE_URL` — trocar de provedor futuro é trocar isso |
| `JULIUS_TYPESAFE_MODEL` | `jev-latest` | |
| `JULIUS_TYPESAFE_BUDGET_USD` | `1.0` | **teto separado** do `JULIUS_AI_BUDGET_USD` (resolve a pendência dos requisitos) — é um provedor e um risco diferentes, orçamento não deve se misturar |
| `JULIUS_TYPESAFE_INPUT_PRICE_USD_PER_1M` | `0.042` | preço público hoje; saída é de graça, não há variável de output price |
| `JULIUS_TYPESAFE_MERGE_MODE` | `shadow` | `shadow` (só loga, não decide) ou `active` (decide sozinho) — por decisão de ponto, não uma flag global |
| `JULIUS_TYPESAFE_MERGE_AUTO_CUTOFF` | `0.6` | só usado em modo `active`; valor inicial vem do gap medido (pior "talvez" real = 0,24; pior "sim" sintético = 0,64) — **revisar antes de graduar**, não é definitivo |

`packaging`/`tag` ganham o mesmo par `_MODE`/`_CUTOFF` quando chegar a vez deles (seção 6) — nascem em `shadow` também, sem cutoff de `active` definido ainda (não há medição pra isso hoje).

## 4. Persistência: orçamento genérico por provedor

Migração `0005_decision_usage.sql`:

```sql
-- Orçamento por provedor de decisão estruturada — genérico desde o início,
-- pra um segundo provedor (concorrente do Jev, se/quando existir) não pedir migração nova.
CREATE TABLE decision_usage (
    provider  TEXT NOT NULL,   -- 'typesafe' hoje
    month     TEXT NOT NULL,   -- 'YYYY-MM'
    spent_usd REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (provider, month)
);
```

`repositories/decision_usage.py` espelha `repositories/ai_usage.py` (mesmas duas funções: ler gasto do mês, somar gasto), só parametrizado por `provider`. Isso já responde ao requisito de interface plugável no nível de dado: um provedor novo não pede `ALTER TABLE`.

## 5. Logging

Reaproveita `infra/ai_log.py::append` e `~/.local/share/julius/ai_calls.jsonl` — é JSONL solto, sem schema fixo, então basta acrescentar um campo por registro: `{"provider": "typesafe", "question": "merge_noul", "pair": [id_a, id_b], "value": 0.02, "latency_ms": 780, "error": null, "mode": "shadow"}`. Nenhum arquivo novo, nenhuma migração — mesmo lugar que o usuário já olha hoje.

## 6. O gate por ponto de decisão — mecanismo comum

Cada um dos três pontos (fusão, embalagem, tag) segue a mesma máquina de estados, o que cumpre o requisito de "interface bem definida pra plugar fácil":

```mermaid
flowchart TD
    A[Candidato a decisão\n(par de produtos / produto pendente)] --> B{DecisionClient\ndisponível?\n(chave + orçamento + rede ok)}
    B -- não --> F[Fallback: comportamento de hoje\n(prompt DeepSeek decide sozinho, como sempre)]
    B -- sim --> C{Modo do ponto\n(shadow / active)}
    C -- shadow --> D[Pergunta ao Jev, LOGA o resultado,\nmas quem decide de verdade\ncontinua sendo o DeepSeek de hoje]
    C -- active --> E{noul/confidence\nacima do corte?}
    E -- sim --> G[Aplica automaticamente\n(sempre por um caminho já reversível:\nmerged_into / tag --remover / etc.)]
    E -- não --> F
```

Ponto-chave do desenho: **em `active`, o Jev substitui o DeepSeek nessa decisão específica — não some, nem soma**. Se o Jev estiver indisponível no meio de uma rodada `active` (rede caiu, orçamento estourou), a linha `B -- não --> F` garante queda pro comportamento de hoje na hora, nunca um erro nem uma pendência travada.

## 7. Fluxo específico: fusão de produtos

- **Hoje** (sem mudança, é o fallback `F`): `curation.duplicate_candidates` (rapidfuzz, corte 75) → `judge_duplicates` → `suggestions.suggest_merges` (DeepSeek, `same_product: bool`) → `True` funde automaticamente com aviso, `False` não faz nada.
- **`shadow` (default ao ligar a chave)**: o fluxo acima roda **idêntico**; adicionalmente, para cada candidato, `ask_noul(state=f'Produto A: "{nome_a}"\nProduto B: "{nome_b}"', instructions=...)` é chamado e o resultado só é logado. Zero efeito em produção — é a fase de "prova de conceito" que o usuário pediu.
- **`active`**: `judge_duplicates` para de chamar o prompt `merge` do DeepSeek para a decisão de auto-fusão (fica sem uso nesse caminho — pode ser removido depois, não precisa ser removido agora). Cada candidato de `duplicate_candidates` recebe só `ask_noul`; `noul >= JULIUS_TYPESAFE_MERGE_AUTO_CUTOFF` funde automaticamente pelo mecanismo já existente (`merged_into`, reversível via `produtos desfundir`); abaixo disso, nada acontece (mesmo silêncio de hoje quando `same_product=False`).

### Critério de graduação (`shadow` → `active`), proposto

Não é um teste automatizado — é uma checklist humana, no mesmo espírito de "medir antes de automatizar" que já rege este projeto:

1. Rodar `shadow` por tempo suficiente para acumular candidatos **reais** (não sintéticos) nos dois lados — hoje a amostra medida (`research_typesafe_ai_20260921.md`) só tem negativos reais e positivos sintéticos.
2. Cruzar `ai_calls.jsonl` (noul por par) com `actions.jsonl` (fusões manuais que o usuário de fato confirmou via `produtos fundir`/revisão) — sem comando novo, é o mesmo `jq`/leitura manual que o projeto já faz para outras análises.
3. Confirmar que existe uma folga limpa entre o pior "sim" real e o pior "não" real (a medição preliminar deu 0,24 vs. 0,64, mas com zero positivos reais — isso **tem** que ser revisto com dado real antes de confiar).
4. Só então mudar `JULIUS_TYPESAFE_MERGE_MODE=active` (e ajustar `JULIUS_TYPESAFE_MERGE_AUTO_CUTOFF` se a folga real for diferente da preliminar).

## 8. Fluxo específico: forma de embalagem e categoria/tag

Mesma máquina de estados da seção 6, mas **nascem em `shadow` sem previsão de graduação nesta rodada** — nenhuma medição existe ainda para esses dois pontos (diferente da fusão, que já tem prova de conceito real). `services/suggestions.py::suggest_packaging`/`enrich_products` ganham a mesma chamada opcional a `ask_choice` (critérios = vocabulário fechado já existente: `form` de packaging, `known_tags` de enrich), só logando em `shadow`. Medir e decidir cutoff de `active` fica para uma rodada própria, depois que a fusão já tiver validado o padrão de rollout.

## 9. Degradação (FR5) — tabela de casos

| Situação | Comportamento |
|---|---|
| `JULIUS_TYPESAFE_API_KEY` ausente | `Config.typesafe_configured=False`; nenhuma chamada é tentada; todos os 3 pontos ficam no fallback `F` (comportamento de hoje) |
| Orçamento do mês (`decision_usage`) estourado | mesmo fallback — não liga pra API, sem erro |
| Erro de rede / timeout / HTTP≠200 | `NoulResult`/`ChoiceResult` com `error` preenchido, nunca exceção; ponto cai no fallback `F` **nessa chamada específica** (não desliga a camada inteira — a próxima chamada tenta de novo) |
| `active` mas Jev indisponível no meio da rodada | cada candidato cai no fallback individualmente — nenhuma rodada trava, nenhuma exceção sobe até `produtos revisar`/`importar` |

## 10. O que fica para `/sc:implement`

Sugestão de ordem (não vinculante, cada um cabe num ticket):
1. `infra/decision_client.py` (Protocol + `TypeSafeDecisionClient` + testes com fake, mesmo padrão de `ScriptedLlmClient`).
2. Migração `0005_decision_usage.sql` + `repositories/decision_usage.py`.
3. `Config` novas variáveis + `typesafe_configured`.
4. Fiação do modo `shadow` em `curation.judge_duplicates` (só logar, zero mudança de comportamento — é o ticket de menor risco e o que já tem prova de conceito).
5. Fiação do modo `shadow` em `suggest_packaging`/`enrich_products` (idem, só logar).
6. (Futuro, só depois da checklist da seção 7): trocar `JULIUS_TYPESAFE_MERGE_MODE` para `active` em produção — não é ticket de código, é uma mudança de variável de ambiente depois de revisar o log acumulado.

## 11. O que este design deliberadamente não resolve agora

- Cutoff de `active` para embalagem/tag — sem medição, sem número.
- UI nova mostrando o `noul` na tela de `produtos revisar` — cosmético, pode entrar depois que `active` for real; não é requisito de graduação.
- Remoção do prompt `merge` do DeepSeek — fica no código, sem uso no caminho de fusão quando `active`, até alguém decidir limpar (não é ponytail deixar código morto por uma versão até confirmar que `active` é definitivo).
