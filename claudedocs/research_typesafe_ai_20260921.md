# Pesquisa: TypeSafe.ai (Jev) e aplicabilidade ao Julius

**Data**: 2026-09-21 · **Escopo**: pesquisa apenas — nenhuma mudança de código feita ou recomendada para implementação imediata.

## Resumo executivo

- **TypeSafe AI** é uma startup fundada por Diogo Almeida (co-inventor do ChatGPT na OpenAI), com equipe de OpenAI/Google Brain/Meta-FAIR/Stripe/Airbnb. Saiu do modo stealth em 15/09/2026 com **US$40M** de seed liderado pela DCVC, lançando o **Jev**, o primeiro "System One model" da empresa.
- Jev **não gera texto**: recebe um `state` (contexto) e `questions` tipadas — **Choice** (escolher 1 de N opções), **Score** (nota numa rubrica ordenada) e **Noul** (sim/não como probabilidade 0–1) — e devolve valores tipados + distribuição de probabilidade, numa única chamada, em paralelo. Choice e Score também trazem `confidence`.
- **Achado central**: essa `confidence` é uma **estatística derivada da distribuição de probabilidade** — não o modelo "dizendo um número" (autorrelato). Para 3 opções, por exemplo, é `(3×maior_prob − 1)/2`. Isso é estruturalmente diferente do que o Julius já tentou.
- Preço divulgado: **US$0,042 por milhão de tokens de entrada, saída de graça** — a própria TypeSafe reconhece que não pode provar que não é subsidiado. Produto em **early access, fila de espera**.
- **Por que isso importa aqui**: o CLAUDE.md do projeto registra, três vezes, que confiança autorrelatada por LLM (DeepSeek) **falhou como filtro** — o par `Alho ↔ Pão de Alho` (falso positivo) veio com confiança 1,00, e os dois acertos de fusão vieram com 0,70/0,80. Um corte em cima disso teria matado os acertos e aprovado o erro. O mecanismo de confiança do TypeSafe ataca exatamente esse tipo de falha por construção — é o único ponto de encaixe genuinamente novo encontrado nesta pesquisa, não uma feature genérica.
- **Recomendação**: não adotar agora. Ver seção final.

## O que é o TypeSafe / Jev

| Conceito | O que faz |
|---|---|
| **State** | O contexto que a pergunta é avaliada contra (texto livre, ex.: nome de dois produtos, uma mensagem de chat) |
| **Choice** | Escolhe 1 opção de um conjunto fechado com critérios descritos; devolve `choice`, `probabilities` (uma por opção) e `confidence` |
| **Score** | Avalia o state numa rubrica ordenada (ex.: 0=calmo, 1=frustrado, 2=furioso); devolve `score`, `legend`, `probabilities`, `confidence` |
| **Noul** | Pergunta sim/não; devolve só `noul` (0–1), sem `confidence` separado — a própria probabilidade já carrega a informação |
| Todas as perguntas | Avaliadas **em paralelo e isoladas** contra o mesmo `state`, numa chamada só — custo quase não sobe ao adicionar perguntas |

**Padrões documentados** (`/patterns`): *speculative fan-out* (mandar várias perguntas de uma vez para não pagar round-trip), *confidence-gated routing* (confiança como segundo eixo — a resposta diz o quê, a confiança diz se agir), *composite scoring* (decompor um julgamento complexo em várias perguntas atômicas e combinar em código, em vez de pedir "dê uma nota geral"), *intent routing* (classificar e rotear para handlers).

**Confiança, em detalhe** (`/confidence`): a documentação é explícita — *"confidence is a statistic computed from the probability distribution the answer already gives you"* — e avisa que não é universal: *"you are never locked into our definition"*, recomendando olhar as `probabilities` completas quando o caso pedir, e calibrar o corte por domínio começando conservador.

**Acesso**: HTTP puro (`POST /v1/systemone`, JSON in/out — sem streaming, sem SDK obrigatório) ou SDKs oficiais Python/JavaScript. Em **early access**, atrás de lista de espera.

## Onde poderia se encaixar no Julius (mapeamento concreto)

| Ponto do sistema hoje | Prompt/mecanismo atual | Encaixe possível do Jev | Avaliação |
|---|---|---|---|
| `services/curation.judge_duplicates` → `suggestions.suggest_merges` (prompt `merge`) | DeepSeek devolve `same_product` + `confidence` autorrelatada — **medido e reprovado 2x** como filtro | **Noul** "estes dois nomes descrevem o mesmo produto de supermercado?", com `state` = os dois nomes; a `confidence` viria da distribuição, não de o modelo inventar um número | **É o único encaixe com potencial real** — ataca exatamente a falha documentada. Mas exige medir contra os mesmos candidatos reais antes de confiar (ver recomendação) |
| `suggestions.suggest_packaging` (`form`: unit/pack/weight/volume/unknown) | DeepSeek, com recusa como único sinal confiável hoje | **Choice** com os 5 critérios | Ganho marginal — o projeto já resolveu isso via recusa e nunca aplica automaticamente (humano sempre confirma) |
| `bot/agent.py` — roteamento entre 14/15 ações | PydanticAI + DeepSeek, `temperature=0`, **medido em 100% de acerto** | **Choice** entre as ações | Choice não extrai argumentos (ids, itens, quantidades) — precisaria de uma segunda chamada para isso, adicionando uma dependência e uma chamada a um problema que já funciona perfeitamente e custa centavos |
| Guard `_claims_unchecked_data` (bot/agent.py) | Lista de frases proibidas em texto livre | **Noul** "este texto afirma que uma busca/importação falhou?" | Sem necessidade — a lista de frases já resolve, é grátis e determinística |
| `enrich_products` (nome legível), `narrate()` (persona), `suggest_trade_names` (nome fantasia) | Geração de texto livre | **Não coberto** | Jev nunca gera texto — não é o tipo de modelo para isso, por desenho |

## Por que não adotar agora

1. **Acesso**: está em lista de espera, não é uso imediato.
2. **Domínio não testado**: nomes de produto em português, abreviados, extraídos de cupom fiscal (`LING FGO RESF AURORA kg`) são um domínio bem específico. Nada na documentação ou na cobertura de imprensa fala de calibração nesse tipo de texto — seria preciso medir, não supor.
3. **Segundo provedor de IA**: o projeto tem uma decisão deliberada de manter tudo atrás de três variáveis `JULIUS_AI_*` e um cliente HTTP único (`urllib`, sem SDK) — "trocar de provedor é trocar `base_url`/`api_key`/`model`". Um provedor que só faz Choice/Score/Noul (sem geração) não cabe nessa mesma abstração; seria um segundo caminho de código, não uma troca de configuração.
4. **Custo já é irrisório**: rodadas reais custam US$0,01–0,02, orçamento é US$5/mês — o preço agressivo do Jev (US$0,042/milhão de tokens de entrada) não resolve nenhum problema de custo que este projeto tenha.
5. **Sustentabilidade do preço**: a própria TypeSafe admite que não pode provar que o preço atual não é subsidiado.
6. **Cultura do projeto**: toda automação aqui nasceu de medição contra o catálogo real, nunca de "a ferramenta promete resolver X" (ver a rejeição e reabertura da fusão automática em v2.2/v2.4, e as três medições que reprovaram confiança autorrelatada). Adotar o Jev sem medir contra os mesmos 19 pares já catalogados repetiria o erro que essas rodadas corrigiram.

## Medição real (2026-09-21, chave de acesso liberada — `JULIUS_TYPESAFE_API_KEY`)

O acesso deixou de ser o bloqueio (a lista de espera liberou uma chave). Rodei o experimento offline recomendado acima, **contra os 20 candidatos a duplicata reais do catálogo de produção** (`services.curation.duplicate_candidates`, banco copiado, nunca tocado em produção): uma pergunta **Noul** por par — *"os dois produtos são o mesmo, a ponto de fazer sentido juntar o histórico de preço?"* — via `POST /v1/systemone`, `urllib` puro, sem SDK (mesmo estilo do `HttpLlmClient` que o projeto já usa).

**Os 13 pares com veredito humano documentado no CLAUDE.md (todos "NÃO deve fundir") saíram TODOS com `noul` baixo (0,02–0,15)** — inclusive o caso que mais importa: **`Alho` ↔ `Pão de Alho Pradella 400g Picante`, o falso positivo que o DeepSeek confirmou com confiança autorrelatada de 1,00, saiu com `noul = 0,02`** no Jev. Os 3 pares de `Dry Rub` de sabor diferente, `Água com/sem gás`, `Coca-Cola Zero/original`, `Aveia fino/regular`, cortes de carne diferentes (`Picanha`/`Fraldinha`) — todos corretamente próximos de zero.

Para calibrar a outra ponta, testei 5 pares sintéticos obviamente **iguais** (mesmo nome em caixa diferente, vírgula vs. ponto decimal, nome cru vs. legível do caso real `Sacola reutilizável`): todos saíram em **0,64–0,92** — nenhum bateu 1,0 cravado (o modelo parece manter incerteza residual mesmo em texto idêntico), mas há uma folga limpa entre o pior "sim" (0,64) e o pior "talvez" do catálogo real (0,24, `Cebola` ↔ `Cebola branca nacional`, sem veredito humano ainda) — um corte em ~0,4–0,5 separaria os dois grupos sem ambiguidade nesta amostra.

| Aspecto medido | Resultado |
|---|---|
| Discrimina o falso positivo que enganou o DeepSeek? | **Sim** — 0,02 vs. 1,00 autorrelatado |
| Separa "sim" de "não" com folga? | Sim nesta amostra (gap 0,24→0,64) — mas com poucos "sim" reais testados (só sintéticos) |
| Uso da API | `POST` JSON simples, sem SDK — cabe no `HttpLlmClient` existente, só trocando endpoint/schema |
| Latência | ~600–900ms por pergunta (comparável ao DeepSeek) |
| Custo | Irrelevante nesta escala (input a US$0,042/milhão de tokens) |

**Limite da medição**: só tenho ground truth humano confirmado para o lado "não fundir" (13 pares) e para pares sintéticos triviais do lado "fundir". Nenhum caso real e sutil de "sim, é o mesmo produto" (o tipo `Tomate italiano` ≈ `Tomate Italiano União`, que só existe hoje já fundido) foi testado — a amostra não prova que o Jev acerta os verdadeiros positivos difíceis, só que ele não repete o erro documentado do DeepSeek nos negativos difíceis.

## Recomendação (para decisão humana)

O resultado é bom o suficiente para justificar um passo a mais, mas não para trocar `judge_duplicates` sem mais dado: (1) rodar essa mesma pergunta contra os **próximos** candidatos reais que aparecerem (todo `julius produtos revisar`/`importar` futuro), registrando o `noul` ao lado do veredito humano real que sair da revisão — sem aplicar fusão automática baseada nisso ainda; (2) só depois de acumular alguns casos reais de "sim" (não sintéticos) decidir se um corte tipo `noul >= 0.5` substitui ou complementa o prompt `merge` do DeepSeek. Continua valendo a ressalva de que isso introduz um segundo provedor de IA — mas, ao contrário da avaliação inicial, agora há evidência concreta (não só teoria de documentação) de que o mecanismo de confiança resolve exatamente a falha que os três autorrelatos do DeepSeek não resolveram.

## Fontes

- [Documentação oficial TypeSafe](https://docs.typesafe.ai) — Introduction, Quickstart, Confidence, Patterns/confidence-routing (conteúdo colado no prompt do usuário e lido diretamente via WebFetch nesta pesquisa)
- [What Is Jev? Inside TypeSafe AI's System One Model — getmaxim.ai](https://www.getmaxim.ai/articles/what-is-jev-system-one-model/)
- [TypeSafe Jev: the first System One model, explained — eesel.ai](https://www.eesel.ai/blog/typesafe-jev)
- [Jev Explained — MindStudio](https://www.mindstudio.ai/blog/jev-system-one-model-launch)
- [Jev: TypeSafe's System One Model That Never Hallucinates — DataCamp](https://www.datacamp.com/blog/system-one-models-jev)
- [A deep dive into Jev — flaviocopes.com](https://flaviocopes.com/jev/)
- [TypeSafe AI Releases Jev — MarkTechPost](https://www.marktechpost.com/2026/09/19/typesafe-ai-releases-jev/)
- [TypeSafe AI's Jev offers an alternative to LLMs — Tom's Hardware](https://www.tomshardware.com/tech-industry/artificial-intelligence/typesafe-ais-jev-offers-an-alternative-to-llms-that-claims-to-be-193x-faster-and-445x-cheaper-system-one-type-model-is-bespoke-for-probabilistic-decision-making)
- [TypeSafe AI debuts model for machines that plays Doom — The Register](https://www.theregister.com/ai-and-ml/2026/09/16/typesafe-ai-debuts-model-for-machines-that-plays-doom/5296711)
- [TypeSafe AI Raises $40M Seed — WOWTALE](https://en.wowtale.net/2026/09/21/235190/)
- [TypeSafe · GitHub](https://github.com/typesafe-ai)
