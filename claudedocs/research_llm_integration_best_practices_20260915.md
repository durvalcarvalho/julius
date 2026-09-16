# Integrar LLM num sistema com schema/contratos — práticas, prompt e logging

Pesquisa feita em 2026-09-15. Escopo: só pesquisa/recomendação, nenhum código alterado. Aplica-se à camada já desenhada em `CLAUDE.md` ("Camada opcional de IA"): `julius/infra/llm_client.py` (`Protocol LlmClient.complete(system_prompt, user_prompt) -> LlmResponse | None`) e `julius/services/suggestions.py` (`suggest_merge`, `suggest_content`, `suggest_tags`), com o invariante já fixado no design: **nem client nem serviço lançam exceção — falha vira `None`**.

Boa notícia adiantada: a maior parte do que a literatura recomenda pra lidar com não-determinismo **o design deste projeto já faz** (nunca confiar cegamente, nunca deixar IA decidir sozinha, silenciar erro em vez de propagar). O que falta é: como pedir o JSON certo, e como logar as chamadas pra você conseguir olhar depois.

## 1. O problema central

LLM não é determinística; seu sistema (dataclasses `MergeSuggestion`/`ContentSuggestion`, `CHECK` no schema SQLite, `Literal["L","KG","UN"]`) é. A ponte entre os dois nunca é "confiar que o modelo obedeceu" — é **pedir formato estruturado + validar no seu código antes de aceitar**. As duas partes são obrigatórias; uma sem a outra falha:
- só pedir JSON no prompt, sem validar → aceita lixo ocasional (todo modelo, mesmo os melhores, erra formato uma fração das vezes).
- só validar, sem pedir formato claro no prompt → taxa de erro alta demais, gasta tokens/chamadas à toa.

## 2. Como conseguir saída que respeita o schema

Duas técnicas nativas de API, nenhuma exige framework novo:

**JSON mode** (`response_format: {"type": "json_object"}`) — a DeepSeek suporta isso nativamente. Regras da própria documentação oficial:
- precisa da palavra "json" em algum lugar do system/user prompt;
- precisa de **um exemplo concreto** do formato desejado no prompt (o modelo copia a forma do exemplo, não só a instrução em prosa);
- definir `max_tokens` com folga — resposta cortada no meio quebra o parse;
- a própria doc avisa que a API "pode ocasionalmente retornar conteúdo vazio" — trate isso como mais um caso de falha → `None`, não como bug do seu client.

**Function/tool calling com "strict mode"** — mais rígido (o provedor valida contra um JSON Schema antes de devolver), mas é mais máquina do que este projeto precisa: 3 tarefas pequenas, chamadas de baixa frequência. JSON mode + validação manual no seu código (dataclass + `if`s, sem Pydantic — este projeto já decidiu não empilhar dependência nova pra isso) é proporcional. Guarde tool calling como opção se um dia a suposição mudar (múltiplos campos aninhados, múltiplas ferramentas).

**Nunca é 100% garantido, nenhuma das duas técnicas.** Mesmo GPT-4/DeepSeek/etc. têm taxa de erro de validação não-zero reportada na literatura. Isso não é um bug a caçar — é o motivo de o invariante "nunca lança, vira `None`" já estar certo no design.

## 3. Como lidar com não-determinismo (prático, não teoria)

1. **Temperatura baixa** (`0` a `0.2`) pras 3 tarefas — são classificação/extração, não geração criativa. Não existe motivo pra usar o default (geralmente ~0.7-1.0) aqui.
2. **Validar sempre no seu lado**, nunca confiar no `response_format` sozinho: `json.loads()` dentro de `try/except`, depois checar que os campos esperados existem e têm o tipo certo (`same_product` é bool, `confidence` é float entre 0 e 1, `unit` é um dos 3 valores aceitos). Qualquer coisa fora disso → `None`, igual a erro de rede.
3. **Um retry, não um loop.** Se a resposta vier vazia ou malformada, uma segunda tentativa cobre a maioria dos casos (é o comportamento documentado da própria DeepSeek); daí em diante, desistir e devolver `None` — orçamento e paciência do usuário não pedem mais que isso.
4. **Poucos exemplos (few-shot), incluindo um exemplo negativo.** Sem um caso "não é o mesmo produto" no prompt, o modelo tende a viés de sempre confirmar (problema conhecido em tarefas de "A e B são iguais?"). Os dois casos reais já documentados em `CLAUDE.md` — `TOMATE ITALIANO` vs `TOMATE ITALIANO UNIAO` (mesmo tipo, marca diferente) e o par Pepsi/Guaraná (tamanhos diferentes) — são exemplos prontos, um positivo e um negativo, pra colar direto no prompt.
5. **Aceitar que "sugestão" nunca é 100% reproduzível — e por isso ela é sugestão, não gravação automática.** Isso já é uma decisão fechada no design (`fundir`/`tag`/`definir-conteudo` continuam manuais); a literatura confirma que é a escolha certa: mesmo com schema estrito, a **correção semântica** ("é realmente o mesmo produto?") não é garantida pelo formato, só a forma da resposta é.

## 4. Como desenhar o prompt

Estrutura recomendada (achado consistente em toda a literatura de 2026 pesquisada): papel → tarefa → formato de saída exato, com exemplo → poucos exemplos few-shot, incluindo casos de borda → entrada real. E um detalhe pouco intuitivo mas com respaldo direto: **peça o campo de justificativa (`rationale`) antes do campo de decisão no JSON.** Como o modelo gera token a token da esquerda pra direita, pedir "pense antes de responder" só funciona se o campo de raciocínio vier primeiro na saída — se `same_product` vem antes de `rationale`, o modelo já "commitou" a decisão antes de justificar, e a justificativa vira pós-racionalização, não parte do raciocínio. Isso não obriga a mudar a ordem dos campos na dataclass Python (`MergeSuggestion(same_product, confidence, rationale)` continua igual) — é só a ordem pedida *dentro do JSON*, remapeada ao desserializar.

Exemplo concreto pra `suggest_merge` (ilustrativo, não é o prompt final — isso é implementação, fora do escopo desta pesquisa):

```
SYSTEM:
Você compara duas descrições de produtos de supermercado brasileiro (maiúsculas,
sem acento, abreviadas) e decide se são o mesmo produto. Marca, sabor e tamanho
diferentes tornam produtos diferentes mesmo com nome-base parecido.
Responda só com um json no formato exato, nada antes ou depois:
{"rationale": "<até 20 palavras>", "same_product": <true|false>, "confidence": <0.0-1.0>}

Exemplo 1:
A="TOMATE ITALIANO kg" B="TOMATE ITALIANO UNIAO kg"
{"rationale": "mesma variedade, UNIAO é só a marca/fornecedor", "same_product": true, "confidence": 0.7}

Exemplo 2:
A="REFRI PEPSI PET 2L" B="REFRI ANT GUARANA PET 1.5L"
{"rationale": "sabor e tamanho diferentes", "same_product": false, "confidence": 0.95}

USER:
A="{description_a}" B="{description_b}"
```
`temperature=0.1`, `response_format={"type": "json_object"}`, `max_tokens` com folga (~150).

`suggest_content` e `suggest_tags` seguem o mesmo esqueleto (papel + formato exato + 1-2 exemplos reais do próprio `CLAUDE.md`, como `CHA LEAO RELAXA CX 16G C/10UN` → conteúdo ambíguo, ou `OVO BCO GRANDE C/30` → sem ambiguidade).

## 5. Como logar localmente pra analisar depois

Padrão simples e sem dependência nova: **um arquivo JSONL** (uma linha = um objeto JSON = uma chamada), aberto em modo append. É o formato que toda ferramenta de observability de LLM (Langfuse, LangSmith, etc.) usa por baixo — mas aqui não precisa de nenhuma delas, é `open(path, "a")` + `json.dumps()` por chamada, direto no client ou no serviço.

**Onde**: mesma área XDG já usada pro banco — `~/.local/share/julius/ai_calls.jsonl` (não versionado, não vai pro CSV de export, é debug/auditoria, não dado de domínio).

**Campos mínimos por linha** (sem PII — este projeto não lida com dado pessoal de qualquer forma, então logar a descrição de produto crua é seguro; nunca logar nada como CPF de consumidor, que o próprio schema já rejeita guardar):
- `timestamp` (ISO 8601)
- `call_kind` (`"merge"` / `"content"` / `"tags"`) — qual função de `suggestions.py` chamou
- `prompt_version` — uma string curta que você muda manualmente toda vez que edita o texto do prompt no código (não precisa de sistema de versionamento, só disciplina de trocar o valor quando o prompt muda — sem isso, comparar resultados de "antes" e "depois" de um ajuste de prompt não tem como saber qual prompt gerou qual log)
- `system_prompt` / `user_prompt` (ou só o `user_prompt`, já que o `system_prompt` é fixo por `call_kind` e reconstruível a partir do `prompt_version`)
- `raw_response` — o texto cru devolvido pela API, antes de qualquer parse
- `parsed_ok` (bool) e `parsed_response` (se `parsed_ok`) — permite depois comparar "quantas vezes o JSON veio malformado" por modelo/prompt
- `input_tokens` / `output_tokens` / `estimated_cost_usd`
- `latency_ms`
- `error` (string ou `null`) — inclui "vazio", "JSON inválido", erro de rede, etc.

**Pra que serve depois, concretamente:**
- Quando você mudar o prompt (ou trocar de provedor/modelo), rodar os `user_prompt` salvos de nota antiga contra o prompt novo e comparar `parsed_response` velho vs novo — isso é o "regression test" da literatura, só que manual e sem framework, proporcional ao volume (dezenas de chamadas/mês).
- Se um dia a IA "parar de sugerir" (fica tudo `None` silenciosamente, por design), o log é o único lugar que mostra se foi orçamento estourado, erro de rede, ou o provedor mudou de comportamento — sem log, esse silêncio é indistinguível de "não havia nada a sugerir".
- Casos que o modelo errou (você percebeu ao usar `produtos fundir`/`tag`/`definir-conteudo` manualmente e discordar da sugestão) viram, colados à mão, os primeiros exemplos few-shot do próximo ajuste de prompt — fecha o ciclo sem precisar de nenhuma ferramenta de eval.

Não vale, neste volume: rotação de log, banco de dados de trace, dashboard. Um arquivo que cresce devagar (dezenas de linhas/mês) é grep-ável a olho por anos antes de incomodar.

## 6. Pitfalls (o que evitar)

- **Deixar o parse do JSON fora do `try/except`.** A chamada de rede pode não lançar (client já trata isso), mas `json.loads()` de uma resposta malformada lança — se isso escapar, quebra o invariante "nunca lança" do design.
- **Pedir JSON sem exemplo no prompt.** A própria doc da DeepSeek é explícita: só instrução em prosa ("responda em json") sem um exemplo do formato gera inconsistência bem maior do que com exemplo.
- **Não fixar `max_tokens`** — resposta truncada no meio do JSON é indistinguível de "modelo divagou", mas a causa é outra e a correção é diferente (aumentar o limite, não mudar o prompt).
- **Temperatura alta em tarefa de classificação/extração.** Fica não-determinístico à toa — nessas 3 tarefas não há motivo pra criatividade.
- **Não versionar o prompt no log.** Sem `prompt_version`, comparar "melhorou ou piorou depois que editei o prompt" vira anedota, não dado.
- **Confundir "veio JSON válido" com "a resposta está semanticamente certa".** Schema estrito garante forma, nunca conteúdo — o modelo pode devolver `{"same_product": true, "confidence": 0.9}` com formato perfeito e estar errado. É exatamente por isso que a decisão final continua manual (`fundir`/`tag`/`definir-conteudo`) — reforça, não contradiz, o que já está fechado no design.
- **Confiar em modelo "grátis" pra sempre disponível com o mesmo nome.** Ver seção 7 — isso é específico do OpenRouter free tier.
- **Logar dado sensível "só porque é fácil".** Não é um risco real *neste* projeto (descrição de produto não é PII), mas é o motivo de nunca ter pensado em logar o campo "Consumidor" do recibo (CPF) — o mesmo cuidado vale se algum dia a IA receber outro tipo de payload.

## 7. DeepSeek vs. modelos gratuitos do OpenRouter, aplicado a este uso

(Retoma o comparativo do relatório anterior — `research_ia_chinesa_llm_20260915.md` — sob a lente de robustez operacional, não só preço.)

| | DeepSeek direto | OpenRouter (modelos `:free`) |
|---|---|---|
| JSON mode | Suportado nativamente, documentado (`response_format`) | Depende do modelo por trás — OpenRouter roteia pra dezenas de modelos diferentes, cada um com suporte variável a `response_format`; precisa checar por modelo escolhido |
| Estabilidade do identificador do modelo | `deepseek-flash` é um produto com contrato de API estável | Lista de modelos `:free` "muda constantemente" (provedores entram/saem/reprecificam) — o modelo que você fixar em `JULIUS_AI_MODEL` pode simplesmente sumir |
| Rate limit | Não é tema neste volume | ~20 req/min e algo entre 50/dia (conta free) e 1000/dia (com US$10 de crédito comprado) — folgado o bastante pro volume deste projeto, mas existe |
| SLA/disponibilidade | Provedor único, responsabilidade clara | Sem SLA nos free models; picos de demanda despriorizam requisições grátis frente às pagas |
| Dado/privacidade | Política própria da DeepSeek (conferir se aceitável pro seu caso) | Por padrão a OpenRouter não loga prompt: mas se você (ou o provedor por trás do modelo escolhido) habilitar logging, a política da OpenRouter concede a eles direito irrevogável de uso comercial dos dados — vale ler a política do provedor específico atrás do modelo `:free` escolhido antes de decidir, não só a da OpenRouter |
| Custo | Desprezível no seu volume (~centavos/mês) | Zero |

**Como isso interage com o invariante já fechado no design** ("nem client nem serviço lançam exceção, falha vira `None`"): esse invariante já absorve o pior caso da OpenRouter (modelo sumir, rate limit estourar, resposta inconsistente) sem quebrar o resto do sistema — é exatamente a rede de segurança que a literatura de "production reliability" recomenda, e você já tem. O risco real de usar `:free` não é "vai quebrar o `julius`", é "vai silenciosamente parar de sugerir e você não vai saber por quê" — o que a seção 5 (log local) resolve.

**Sugestão prática, não implementação**: como as duas opções custam ~zero no seu volume, a diferença que importa é operacional — DeepSeek dá previsibilidade de contrato (modelo não muda de nome/desaparece sem aviso); OpenRouter `:free` dá zero custo mas com um identificador de modelo que pode precisar ser trocado sem aviso prévio do provedor. Dado que a troca é só uma variável de ambiente (`JULIUS_AI_BASE_URL`/`JULIUS_AI_MODEL`), não há necessidade de decidir isso de forma definitiva agora nem de construir fallback automático entre os dois (YAGNI dado o volume) — o log da seção 5 é o que permite perceber, quando quer que aconteça, que a troca é necessária.

## Fontes

- [JSON Output — DeepSeek API Docs (oficial)](https://api-docs.deepseek.com/guides/json_mode/)
- [Function Calling — DeepSeek API Docs (oficial)](https://api-docs.deepseek.com/guides/function_calling)
- [The guide to structured outputs and function calling with LLMs — Agenta](https://agenta.ai/blog/the-guide-to-structured-outputs-and-function-calling-with-llms)
- [LLM Structured Outputs with JSON Schema — TrueFoundry](https://www.truefoundry.com/blog/llm-structured-outputs-json-schema)
- [Reliable JSON from Any LLM: Pydantic + Zod (2026) — TECHSY](https://techsy.io/en/blog/llm-structured-outputs-guide)
- [A Practitioner's Guide to Prompt Engineering in 2026 — getmaxim.ai](https://www.getmaxim.ai/articles/a-practitioners-guide-to-prompt-engineering-in-2025/)
- [Prompt Engineering in 2026: 10 Patterns That Actually Work — FutureAGI](https://futureagi.com/blog/effective-prompt-engineering-maximize-llm-performance/)
- [A Practical Guide to Observability for LLM Applications — Medium](https://medium.com/@zakariabenhadi/a-practical-guide-to-observability-for-llm-applications-logs-traces-and-quality-metrics-c29568ef52eb)
- [Golden dataset evaluation: build and maintain LLM test sets — Langfuse](https://langfuse.com/resources/engineering/golden-dataset-evaluation)
- [What is LLM evaluation? — Braintrust](https://www.braintrust.dev/articles/llm-evaluation-guide)
- [OpenRouter Free Tier 2026 — Price Per Token](https://pricepertoken.com/endpoints/openrouter/free)
- [OpenRouter free models list 2026 — Ruben Torney](https://rubentorney.com/blog/en/openrouter-modeles-gratuits-2026.html)
- [Is OpenRouter Reliable? Uptime & Rate Limits Tested (2026) — TokenMix](https://tokenmix.ai/blog/is-openrouter-reliable-uptime-rate-limits-2026)
- [Provider Logging - Provider Data Retention Policies — OpenRouter (oficial)](https://openrouter.ai/docs/guides/privacy/provider-logging)
- [Zero Data Retention (ZDR) — OpenRouter Blog (oficial)](https://openrouter.ai/blog/insights/zero-data-retention/)

**Nota de confiabilidade:** os dois links da DeepSeek e os dois da OpenRouter marcados "(oficial)" são documentação/blog do próprio provedor — conferidos direto. Os demais são de blogs/agregadores de terceiros; os princípios gerais (schema validation, few-shot, JSONL, golden dataset) aparecem repetidos e consistentes entre várias fontes independentes, o que dá confiança razoável neles mesmo sem uma única fonte "canônica" — mas números específicos de rate limit/roster de modelos grátis da OpenRouter mudam mês a mês e valem reconferência na hora de configurar.
