# Comando para rodar o design do bot do Julius

Cole isto no terminal (dentro de `project-julius/`) quando quiser passar do planejamento pra arquitetura. O brief é autocontido — funciona mesmo numa sessão nova, sem o histórico desta conversa — porque aponta pros documentos que já têm todo o requisito e toda a pesquisa feita até aqui.

```
/sc:design Desenhe a arquitetura de alto nível para dar ao Julius uma interface de bot no Telegram, além da CLI que já existe. Antes de propor qualquer coisa, leia nesta ordem: docs/requirements/messaging-bot-integration.md (todos os requisitos e decisões já fechadas — canal, transporte, hospedagem, escopo de ações, confirmação de escrita), claudedocs/research_messaging_bot_integration_20260917.md (por que Telegram e não WhatsApp, por que long polling), e claudedocs/research_bot_stack_libraries_20260917.md (a pilha de bibliotecas já pesquisada: python-telegram-bot assíncrono + PydanticAI + Deferred Tools do PydanticAI para a confirmação de escrita). Essas decisões já estão fechadas — o design parte delas, não as reabre sem motivo novo.

Há um repositório de referência clonado em ../majordomo (fora deste repo git, não é dependência nem submódulo) — um assistente pessoal real, em produção, rodando dentro do Telegram com tool-calling e escrita protegida por aprovação. Estude-o COM DESCONFIANÇA: é um projeto correto para o problema QUE ELE resolve (múltiplos conectores, múltiplos usuários potenciais, múltiplos provedores de LLM com fallback, memória de longo prazo), que é ordens de grandeza maior que o problema do Julius (um catálogo de preços, um usuário, um provedor de IA já escolhido e orçado). Não copie a arquitetura dele por ela existir — avalie cada padrão à luz da escala real do Julius e dos princípios já registrados em CLAUDE.md (DAG de camadas L1-L4 já existente, sem abstração especulativa, sem dependência que uma função pequena substitui).

Especificamente do majordomo, considere adaptar (são baratos e resolvem um risco real, mesmo em escala pequena):
- a resposta final ao usuário deve vir do RETORNO REAL da função de services/* chamada, nunca da frase que a IA gerou sobre o que ela fez — evita reportar sucesso numa ação que não rodou;
- a mensagem de confirmação de escrita deve mostrar o que o PRÓPRIO CÓDIGO calculou (ex.: os nomes reais de produto/mercado buscados no banco a partir dos IDs), não o que a IA disse que ia fazer — evita confirmar em cima de um alvo que a IA alucinou;
- qualquer falha na confirmação (timeout, exceção, resposta ambígua) nega por padrão, nunca executa;
- o bot deve se recusar a subir se a allowlist de chat_id estiver vazia, em vez de logar um aviso e continuar aberto;
- o logger HTTP do python-telegram-bot expõe o token do bot na URL de polling em nível INFO — precisa ser capado em WARNING antes de ir pra produção.

Especificamente do majordomo, NÃO traga (resolvem problemas de escala/produto que o Julius não tem — se o design usar algum destes, justifique por que o Julius realmente precisa, não porque o majordomo tem):
- a arquitetura hexagonal de 5 camadas com import-linter (ports/adapters/domain/kernel/runtime) — o Julius já tem sua DAG de 4 camadas testada em tests/test_architecture.py, use essa;
- fallback entre múltiplos provedores de LLM — o Julius já decidiu DeepSeek único, orçamento medido;
- aprovação em lote com fingerprint de chamadas (propose_writes/manifests) — resolve um problema de volume que uma ferramenta pessoal de uso esporádico não tem;
- qualquer coisa relacionada a memória de longo prazo com embeddings/RAG, execução de código sandboxed, múltiplos bots numa "control room", ou skills auto-escritas pela IA — sem relação com o domínio do Julius;
- múltiplos arquivos de configuração por instância (config.yaml/persona.yaml/platform.yaml/.env) — o Julius resolve configuração com variáveis de ambiente (JULIUS_AI_*), proporcional ao tamanho do projeto.

O design deve ser alto nível: módulos novos e onde entram na árvore de julius/ (respeitando a DAG de camadas do CLAUDE.md), o contrato entre o bot e services/*, como as tools são declaradas e validadas, e como o fluxo de confirmação de escrita se encaixa no turno de mensagem. Decisões de baixo nível (nomes exatos de função, schema JSON de cada tool, layout de arquivo) ficam para a implementação, não para este design.
```
