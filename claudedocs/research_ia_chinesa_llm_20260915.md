# Qual API de LLM chinesa usar no `julius` (camada `JULIUS_AI_*`)

Pesquisa feita em 2026-09-15. Escopo: só pesquisa/recomendação — nenhuma implementação, nenhum código alterado. Ver "Camada opcional de IA" em `CLAUDE.md` pro contrato que essa escolha precisa satisfazer (`/chat/completions`, orçamento US$1/mês, chamado só em `importar`/`produtos comparar`, nunca em `consultar`).

## Perfil real de uso (por que a maioria dos critérios de benchmark não importa aqui)

- Volume: dezenas de chamadas curtas por mês (import-time, não por busca).
- Tarefas: 3, todas simples — `suggest_merge` (mesmo produto ou não, dado 2 descrições curtas), `suggest_content` (extrair quantidade/unidade de um padrão tipo `C/10UN`), `suggest_tags` (sugerir categoria a partir de descrição + lista de tags existentes). Nenhuma exige raciocínio longo, contexto grande ou geração longa.
- Consequência: **custo por token é irrelevante em valor absoluto** — qualquer modelo abaixo custa centavos de dólar por mês nesse volume. O que decide é: robustez/documentação da API compatível com `/chat/completions`, facilidade de conseguir a chave (conta, verificação, pagamento) morando fora da China, e qualidade "boa o suficiente" em texto abreviado em português.

## Comparativo (preços por 1M tokens, setembro/2026)

| Provedor | Modelo recomendado p/ este uso | Input | Output | Compatível OpenAI? | Observação |
|---|---|---|---|---|---|
| **DeepSeek** | `deepseek-flash` (DeepSeek-V4.1-Flash) | $0,15 (cache miss) / $0,003 (cache hit) | $0,60 | Sim — `https://api.deepseek.com` | Mais maduro/documentado, sem split de região, cadastro tranquilo pra estrangeiro (cartão internacional aceito) |
| **Alibaba Qwen** | `qwen-flash` (Model Studio/DashScope) | $0,10 | $0,40 | Sim — endpoint `compatible-mode/v1` | Ainda mais barato; exige conta Alibaba Cloud, endpoint internacional separado do da China continental |
| **Zhipu (GLM)** | `glm-4.7-flash` | **Grátis** (rate-limited: 1 requisição concorrente) | Grátis | Sim — `open.bigmodel.cn/api/paas/v4` | Custo zero bate o orçamento sempre; risco prático: cadastro no bigmodel.cn historicamente pede verificação por SMS de número chinês |
| Moonshot (Kimi) | `kimi-k2.6` (flagship K3 é $3/$15) | $0,95+ | $4,00+ | Sim | Posicionado pra contexto longo/raciocínio — não é o ponto forte que este projeto precisa, mais caro sem necessidade |
| MiniMax | `minimax-m3` | $0,30 | $1,20 | Sim | Meio-termo, sem vantagem clara sobre DeepSeek/Qwen aqui |

Peço nota: preços de DeepSeek têm faixa "peak"/"off-peak" (peak = 01h–04h e 06h–10h UTC em dias úteis, ~2x mais caro); os valores acima são off-peak, que cobre a maior parte da semana incluindo todo fim de semana.

## Recomendação

**DeepSeek (`deepseek-flash`)** como default. Justificativa, nessa ordem:
1. API compatível OpenAI mais simples de configurar (uma única `base_url`, sem separação mainland/internacional como a Alibaba tem).
2. Ecossistema mais maduro e documentado — menos risco de mudança de contrato/retirada abrupta (já aconteceu com `deepseek-chat`/`deepseek-reasoner`, retirados em jul/2026, mas a migração foi documentada e o preço só melhorou).
3. Custo, embora não seja o critério decisivo aqui, ainda é desprezível no seu volume (frações de centavo por mês).

**Alternativa a considerar sem custo nenhum**: **Zhipu GLM-4.7-Flash** é gratuito e cobriria o orçamento de US$1/mês permanentemente — mas o cadastro em `bigmodel.cn` costuma exigir verificação por telefone chinês, o que pode ser fricção real pra quem mora fora da China. Vale tentar se o cadastro se mostrar viável; se travar na verificação, cair pro DeepSeek sem perder tempo.

**Não recomendo**: Kimi/Moonshot (caro pro que se precisa aqui) nem MiniMax (sem vantagem sobre as duas primeiras opções).

## Como isso encaixa no design já feito

Nada muda em `julius/infra/llm_client.py` — ele já é um cliente REST genérico (`urllib.request`, protocolo `/chat/completions`). Trocar de provedor é só preencher:
```
JULIUS_AI_API_KEY=...
JULIUS_AI_BASE_URL=https://api.deepseek.com
JULIUS_AI_MODEL=deepseek-flash
JULIUS_AI_INPUT_PRICE_USD_PER_1M=0.15
JULIUS_AI_OUTPUT_PRICE_USD_PER_1M=0.60
```
(valores de preço por token pra alimentar o contador de `ai_usage`, não hardcode no código — já é assim no design.)

**Nenhuma dessas variáveis foi setada nem nenhum código foi tocado nesta sessão** — isso é decisão do usuário, e o próprio design em CLAUDE.md já registra que preço muda com frequência e deve ser conferido na hora de configurar, não confiado de memória.

## Fontes

- [DeepSeek API Pricing (oficial)](https://api-docs.deepseek.com/quick_start/pricing)
- [DeepSeek API Pricing 2026 — BenchLM.ai](https://benchlm.ai/deepseek/api-pricing)
- [Qwen API Pricing (September 2026) — BenchLM.ai](https://benchlm.ai/alibaba/api-pricing)
- [Qwen pricing in 2026 — eesel AI](https://www.eesel.ai/blog/qwen-pricing)
- [Kimi API Pricing (September 2026) — BenchLM.ai](https://benchlm.ai/moonshot/api-pricing)
- [Official Zhipu GLM API Pricing 2026 — Clawrouters](https://www.clawrouters.com/blog/zhipu-glm-api-pricing-2026)
- [GLM-4.7-Flash — freellm.net](https://freellm.net/models/z-ai-zhipu-ai/glm-4-7-flash)
- [MiniMax API Pricing 2026 — costbench.com](https://costbench.com/software/llm-api-providers/minimax-api/)
- [The 2026 Chinese LLM Price War — DEV Community](https://dev.to/hassann/the-2026-chinese-llm-price-war-top-5-frontier-api-costs-compared-e1g)
- [Chinese LLM API Pricing Comparison 2026 — LLM Abacus](https://www.llmabacus.com/en/chinese-llm-api-pricing)

Nota de confiabilidade: a maioria dessas fontes são agregadores de terceiros (não documentação oficial dos provedores), com exceção do link da DeepSeek. Os números de DeepSeek foram conferidos direto na documentação oficial; os demais (Qwen, Kimi, Zhipu, MiniMax) vieram de agregadores e devem ser reconferidos na página oficial do provedor escolhido antes de configurar `JULIUS_AI_*`.
