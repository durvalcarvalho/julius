# Pesquisa: correspondência de texto livre contra um catálogo em evolução — isso escala?

> `/sc:research`, 2026-09-22. Pergunta original do usuário, depois de uma sessão de monkey test que achou e corrigiu 5+ bugs em duas rodadas seguidas: *"Esses problemas me fazem pensar que a fundação do sistema não está sólida... será tecnicamente impossível, visto que a quantidade de bugfixes só aumenta à medida que o catálogo aumenta. Já foi resolvido em outros contextos?"*

## Resumo executivo

**A pergunta tem duas partes, e elas têm respostas diferentes.**

1. **"O jeito atual escala?"** — Não, e isso não é opinião: é um resultado matemático de 40+ anos de linguística computacional (Zipf, a explosão combinatória de sistemas baseados em regra). Continuar tratando cada colisão nova como "mais uma palavra pra lista de exceção" (`KIND_NOISE_WORDS`, cutoffs, casos aceitos documentados) tem um teto estrutural: a cauda longa de variação de linguagem natural nunca converge, e cada produto novo no catálogo aumenta o número de colisões *possíveis* de forma pelo menos quadrática (par a par). O medo do usuário está certo.
2. **"O problema em si é resolvido em algum lugar?"** — Também não, no sentido absoluto (nenhum campo afirma 100%). Mas a pergunta certa não é "está resolvido", é "existe uma arquitetura madura que não sofre desse teto" — e a resposta aí é **sim, há 50+ anos**, em pelo menos quatro campos que atacaram exatamente este problema: *record linkage/entity resolution* (bancos de dados, desde 1969), *correspondência de produto em e-commerce* (a versão comercial mais próxima deste caso), *slot-filling e desambiguação em sistemas de diálogo orientados a tarefa* (a peça que resolve "queijo ambíguo, pergunte qual"), e mais recentemente *grounding/faithfulness em RAG* (a peça que resolve "a IA inventou um fato").

**O achado mais importante desta pesquisa**: a arquitetura que o projeto já convergiu organicamente para esta sessão — casamento determinístico primeiro, um fallback mais inteligente (hoje: buscar pelo nome do produto; potencialmente: embeddings ou o próprio LLM) quando o determinístico falha, e uma pergunta de esclarecimento quando a ambiguidade é genuína — **é literalmente o padrão dominante da literatura de entity resolution**, chamado de pipeline *blocking → matching*, com a adição, cada vez mais comum desde 2023, de "LLM como matcher" para bases pequenas. Isso não é coincidência nem sorte: é o formato para onde qualquer sistema que enfrenta este problema converge, porque as alternativas (só regra, ou só ML) já foram tentadas e descartadas décadas atrás.

## O problema, restado com precisão

Toda vez que este projeto corrigiu um "bug de busca" nesta sessão, a forma era a mesma: **uma string digitada por uma pessoa precisa apontar pra uma entidade num vocabulário fechado que muda com o tempo**, e o mecanismo usado pra isso — `rapidfuzz.fuzz.ratio` sobre palavras — mede *coincidência de caracteres*, não *significado*. Os casos reais medidos nesta sessão:

| caso real | por que a string bate | o que precisaria ter batido |
|---|---|---|
| "picanha" → "Pinha" (fruta) | 83% de sobreposição de caracteres | nada — são conceitos diferentes |
| "queijo" → "pão de queijo" | empate lexical, desempate alfabético | um dos 4 tipos de queijo de verdade |
| "coca"/"pepsi" → sem `kind` próprio | a marca não é uma categoria | resolver marca → categoria via outro sinal |
| "leite" → um dos 3 tipos empatados | mesma coisa | qual dos 3, perguntando |

Isso tem nome: é **entity resolution** (ligar uma menção em texto livre a uma entidade canônica) e, quando as duas coisas sendo comparadas são registros de um catálogo, é o caso específico chamado **record linkage** desde Fellegi & Sunter (1969)[^1]. O projeto não inventou um problema novo — reproduziu, com `rapidfuzz`, exatamente a primeira geração de solução que o campo já tentou e superou.

## 1. Por que "mais uma regra" tem teto — a resposta é matemática, não de opinião

A distribuição de frequência de palavras em linguagem natural segue a Lei de Zipf: poucas palavras (a "cabeça") cobrem a maioria dos casos reais, e uma cauda enorme de variações raras nunca acaba — a lei descreve uma tendência geral, mas "há sempre exceções e variações nos dados do mundo real" que a própria distribuição não cobre por completo[^2]. Isso é o motivo estrutural pelo qual `KIND_NOISE_WORDS`, `CONNECTIVE_WORDS`, `NEAR_MISS_CUTOFF` etc. nunca fecham: cada um resolve os casos que **já apareceram**, nunca os da cauda que ainda não apareceram.

O outro lado do mesmo problema é combinatório, não linguístico: sistemas simbólicos/baseados em regra sofreram historicamente de **explosão combinatória** — adicionar uma regra não estende a cobertura linearmente, cria novas combinações e interações com *todas* as regras existentes, um aumento multiplicativo de complexidade[^3]. Isso é exatamente o padrão que a varredura desta sessão expôs: 50 pares de palavras colidindo no catálogo atual (98 kinds, ~300 produtos) — e cada produto novo aumenta esse número de pares **quadraticamente**, não linearmente, porque toda palavra nova pode colidir com toda palavra já existente.

Isso foi, historicamente, o motivo exato pelo qual o campo de NLP migrou de sistemas simbólicos (anos 1950–1980) para estatísticos (anos 1980–1990) e depois neurais (2010s): não por moda, mas porque regra escrita à mão não escala com a variação real da língua, enquanto um modelo aprendido de exemplos escala com dados, não com esforço de engenharia por caso[^4].

## 2. Como cada campo que já bateu nisso resolveu — nenhum "só regra", nenhum "só ML"

### Record linkage / entity resolution (bancos de dados, desde 1969)

O modelo Fellegi-Sunter formaliza o "match" como decisão estatística (ligar / possivelmente ligar / não ligar) minimizando dois tipos de erro, em vez de uma regra de corte única[^1]. A arquitetura que se tornou padrão da indústria desde então é o pipeline de duas fases **blocking → matching**: uma fase barata e determinística filtra pares obviamente diferentes (o que `MATCH_SCORE_CUTOFF`/`_name_score` já fazem), e só o que sobra passa por um matcher mais caro e mais inteligente (hoje: modelos de ML ou LLM)[^5]. Um artigo recente descreve exatamente o padrão que este projeto reinventou sozinho: *"resolve todo registro que pode ser casado deterministicamente por identificadores confiáveis, depois roda matching probabilístico só no que sobrou, e funde as duas saídas"* — precisamente `match_kind` (determinístico) → `_match_kind_via_product`/`kind_candidates` (fallback) → pergunta ao usuário (o "não decido sozinho").

### Correspondência de produto em e-commerce (o paralelo comercial mais direto)

Esta é a versão comercial exata do problema de Julius: nomes de produto variam por vendedor, abreviação, marca. A solução que dominou a partir de ~2019 foi trocar comparação de string por **embeddings semânticos** — um sistema com Sentence-BERT chega a 98% de acurácia e 100% de precisão comparando títulos de produtos no dataset PriceRunner[^6]; sistemas maiores (200M+ itens) combinam embedding de texto e imagem com um banco vetorial (Milvus) pra busca de similaridade em escala[^7]. O ponto que interessa aqui: **o motivo de trocar não foi "regra não funciona nunca"**, foi exatamente o achado desta sessão — regra por edição de caractere não distingue "produtos diferentes que se parecem" de "o mesmo produto escrito diferente", porque as duas coisas têm a mesma assinatura de superfície.

### Slot-filling e desambiguação em diálogo orientado a tarefa (a peça que já foi construída aqui)

Sistemas de diálogo (reservar voo, restaurante) sempre separaram **intent classification** (o que a pessoa quer) de **slot filling** (qual valor preenche cada campo), com um **dialogue state tracker** acumulando isso turno a turno e um sub-diálogo de desambiguação quando o valor não é único[^8]. "Pergunte qual queijo" — o fix que fizemos nesta sessão — não é um remendo improvisado: é a peça padrão desta arquitetura desde os anos 1990 (sistemas como o DARPA Communicator já faziam confirmação por sub-diálogo). O achado de pesquisa relevante aqui é que **isso nunca teve alternativa melhor**: nenhum sistema de diálogo do mundo real elimina a pergunta de desambiguação — ela É a resposta madura pra ambiguidade genuína, não uma muleta.

### Grounding / faithfulness em RAG (a peça que virou a guarda de veredito)

A pesquisa mais recente (2024–2025) trata exatamente do problema do achado #3 desta sessão (a persona narrando o oposto do veredito real): RAG "melhora significativamente a fidelidade ancorando a saída em evidência recuperada", mas **"não elimina completamente as alucinações — o modelo ainda introduz detalhes não suportados, ou contradiz o contexto"**[^9]. A prática recomendada não é "impedir 100%" (ninguém alcançou isso), é **checagem de consistência pós-hoc**: alinhar a saída gerada com a evidência recuperada e derrubar o que não bate[^10] — literalmente o desenho de `_contradicts_price_check` e da guarda de dinheiro que já existiam. **Achar um caso raro de contradição depois de ter essa guarda não é sinal de que a guarda falhou — é o comportamento esperado e documentado do estado da arte.**

### O caso que a pesquisa mostra como genuinamente não resolvido: memória de conversa

O achado #2 desta sessão (o bot afirmou "você começou com cebola" quando a pergunta real tinha saído da janela de `HISTORY_TURNS`) toca um problema que a pesquisa de 2023–2025 chama de **"grounding gap"**: mesmo quando um LLM estabelece corretamente o terreno comum (common ground, no sentido de Clark & Brennan[^11]) num turno, ele **"frequentemente falha em usar esse terreno comum de forma confiável depois"**[^12]. Isso não é uma falha de engenharia deste projeto — é uma limitação aberta e documentada dos LLMs em geral, e explica por que o reforço de prompt que tentamos não mudou o comportamento na prática: **reforço de prompt não resolve um grounding gap, porque o problema não é "o modelo não sabe a regra", é que o modelo não tem acesso à informação que precisaria pra aplicá-la** (a mensagem da banana já não está em nenhum lugar que ele possa consultar). A mitigação real que a área usa é **estado de diálogo explícito e estruturado** (guardar fatos específicos, não confiar em reler o histórico bruto) — o mesmo "estado de pergunta pendente" que este projeto já adiou 3 vezes por falta de caso medido, e que agora tem um quarto caso medido, de um tipo ligeiramente diferente (memória de fato, não pergunta pendente).

## 3. Respondendo direto: "será tecnicamente impossível"?

**Não — mas a estratégia específica de "adicionar mais uma palavra à lista" é, sim, estruturalmente limitada, e o medo está correto sobre ESSA estratégia.** A distinção importa:

- **O que não escala** (matematicamente, não por falta de esforço): tratar cada colisão nova como uma regra lexical nova. Zipf garante que a cauda nunca acaba; a explosão combinatória garante que cada item novo no catálogo aumenta as colisões possíveis mais rápido que linearmente. Isso bate exatamente com a observação do usuário ("a quantidade de bugfixes só aumenta com o catálogo") — e essa observação está certa sobre esse eixo específico.
- **O que escala**, com 50+ anos de precedente em pelo menos quatro campos: uma cascata **determinístico (barato, rápido) → semântico (embeddings ou LLM, mais caro mas entende significado) → esclarecimento (pergunta, quando a ambiguidade é real) → verificação pós-hoc (guarda contra alucinação, aceitando que não chega a 100%)**. Nenhuma das quatro camadas sozinha resolve o problema; a combinação é o que todo sistema maduro do campo usa.

O projeto já tem as quatro camadas, só que construídas uma de cada vez, reagindo a incidente — o que faltou até agora não foi arquitetura errada, foi **reconhecer que já são uma arquitetura**, com um nome e um corpo de pesquisa por trás, em vez de "mais um patch".

## 4. O que a pesquisa sugere como direção — não uma decisão, questões pra pesar

Sem entrar em desenho de implementação (fora do escopo deste research), a literatura aponta três alavancas concretas que o projeto ainda não usou por completo:

1. **Camada semântica sob o casamento lexical**, pra parar de depender só de sobreposição de caracteres. Duas variantes com precedente forte: (a) continuar e aprofundar o padrão já iniciado (LLM como resolvedor — `kind_candidates`, vocabulário no prompt), reconhecido na literatura de 2023+ como alternativa leve a embeddings especificamente pra bases de conhecimento pequenas/especializadas[^13]; ou (b) embeddings de texto locais/baratos especificamente pro nome de produto (sem precisar de banco vetorial — um catálogo de centenas de itens cabe inteiro em memória, comparação por cosseno é O(n) trivial nesse volume). A escolha entre as duas é uma questão de custo/complexidade que vale medir, não assumir.
2. **Tratar a pergunta de esclarecimento como arquitetura permanente, não gambiarra** — já é isso na prática (o mecanismo de `ModelRetry`/`kind_candidates` construído nesta sessão), mas vale nomear explicitamente: ambiguidade genuína SEMPRE vai existir (dois queijos são, de fato, ambíguos sem mais contexto) — o objetivo nunca foi zero perguntas, é perguntar só quando a ambiguidade é real.
3. **Memória de conversa como estado estruturado, não histórico bruto relido** — a única alavanca que a pesquisa aponta como resposta real ao "grounding gap"; é uma peça mais cara (a mesma que este projeto já adiou 3 vezes) e agora tem um quarto motivo medido pra reabrir a decisão.

## Fontes

- [^1]: Fellegi, I.P. & Sunter, A.B. — modelo fundacional de record linkage probabilístico; ver também "(Almost) All of Entity Resolution" — [arXiv:2008.04443](https://arxiv.org/pdf/2008.04443) / [Science Advances](https://www.science.org/doi/10.1126/sciadv.abi8021)
- [^2]: Zipf's word frequency law — [PMC4176592](https://pmc.ncbi.nlm.nih.gov/articles/PMC4176592/), [GeeksforGeeks](https://www.geeksforgeeks.org/nlp/zipfs-law/)
- [^3]: Explosão combinatória em sistemas simbólicos — [From Symbolic Rules to Statistical Learning](https://mbrenndoerfer.com/writing/history-symbolic-to-statistical-nlp-paradigm-shift), [NLP Evolution — From Rules to AI Models](https://medium.com/it-chronicles/the-nlp-landscape-from-the-1960s-to-the-2020s-efea1e63932b)
- [^4]: História rule-based → statistical → neural NLP — [Strengths and Weaknesses of LLM-Based and Rule-Based NLP](https://www.mdpi.com/2079-9292/14/15/3064), [Rule-Based vs. Statistical Approaches in NLP](https://tenthousandhourproject.wordpress.com/2025/11/10/rule-based-vs-statistical-approaches-in-nlp/)
- [^5]: Pipeline blocking→matching e matching determinístico+probabilístico — [Deterministic vs Probabilistic Matching](https://www.zingg.ai/post/deterministic-vs-probabilistic-matching-why-enterprise-entity-resolution-needs-both), [Entity Resolution in Practice](https://arxiv.org/html/2607.26298), [SC-Block](https://arxiv.org/pdf/2303.03132)
- [^6]: Product Matching using Sentence-BERT — [academia.edu](https://www.academia.edu/145184230/Product_Matching_using_Sentence_BERT_A_Deep_Learning_Approach_to_E_Commerce_Product_Deduplication)
- [^7]: Optimizing Product Deduplication with Multimodal Embeddings — [arXiv:2509.15858](https://arxiv.org/abs/2509.15858)
- [^8]: Slot filling / intent classification / dialogue state tracking — [Recent Neural Methods on Slot Filling and Intent Classification, arXiv:2011.00564](https://arxiv.org/html/2011.00564), [Recent Advances in Deep Learning Based Dialogue Systems](https://arxiv.org/pdf/2105.04387)
- [^9]: RAG não elimina alucinação — [Mitigating Hallucination in LLMs: an Application-Oriented Survey, arXiv:2510.24476](https://arxiv.org/html/2510.24476v1), [Hallucination Mitigation for RAG LLMs: A Review](https://www.mdpi.com/2227-7390/13/5/856)
- [^10]: Checagem de consistência pós-hoc / faithfulness — [Benchmarking LLM Faithfulness in RAG, arXiv:2505.04847](https://arxiv.org/pdf/2505.04847), [Disentangling Faithfulness Hallucinations in RAG](https://link.springer.com/article/10.1007/s10994-026-07121-y)
- [^11]: Common ground, Clark & Brennan — [A Psychological Model of Grounding and Repair in Dialog](http://www.psychology.sunysb.edu/sbrennan-/papers/cahnbren.pdf), [Conversational Grounding: Annotation and Analysis](https://arxiv.org/pdf/2403.16609)
- [^12]: "Grounding gap" em LLMs — [Grounding Gaps in Language Model Generations, arXiv:2311.09144](https://arxiv.org/pdf/2311.09144); limitação de janela de contexto — [TRACE: Real-Time Multimodal Common Ground Tracking, arXiv:2503.09511](https://arxiv.org/pdf/2503.09511)
- [^13]: LLM como resolvedor de entidade em bases pequenas — [Leveraging LLMs in Entity Linking via Adaptive Routing, arXiv:2510.20098](https://arxiv.org/html/2510.20098v2), [Contextual Augmentation for Entity Linking using LLMs](https://aclanthology.org/2025.coling-main.570.pdf)
- Achados adicionais de apoio: colisão fuzzy-vs-semântica ([Fuzzy Matching and Semantic Search](https://ipullrank.com/fuzzy-matching-semantic-search), [Aerospike](https://aerospike.com/blog/fuzzy-matching/)); ambiguidade de item em assistentes de voz de mercado, incluindo o achado direto de "'leite' tem mais de 50 SKUs" no domínio de compras por voz — [patente US11430445B2](https://patents.google.com/patent/US11430445); pipeline híbrido BM25+denso como referência de arquitetura de busca em corpora pequenos — [Hybrid Retrieval: BM25 vs. Dense Embeddings](https://medium.com/@dineshkarthik_kandregula/hybrid-retrieval-bm25-vs-dense-embeddings-smarter-search-using-elasticsearch-huggingface-3dd6a6351b05); benchmark clássico de entity matching em datasets pequenos — [projeto Magellan/py_entitymatching](https://sites.google.com/site/anhaidgroup/current-projects/magellan/py_entitymatching).
