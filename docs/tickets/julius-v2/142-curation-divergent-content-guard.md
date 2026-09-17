# 142: `curation` — conteúdo divergente descarta o candidato

> O conteúdo que a v2.3 coletou passa a proteger a fusão que a v2.4 vai automatizar. Quatro falsos positivos saem de graça.

## Contexto

`docs/design/merge-and-unit-price-v2.4.md` §5. Requisito RF1l, medição F16 de `docs/requirements/auto-merge-and-unit-price-v2.4.md`.

Medido no catálogo real: dos 19 pares acima do corte, **4 declaram conteúdo diferente nos dois lados e os 4 são falsos positivos** — `Água 500ml ≈ Água 1,5L`, `Pepsi 2L ≈ Guaraná 1,5L`, `Água s/gás ≈ c/gás 1,5L`, `Pão Zinho 300g ≈ Pão de queijo 800g`. Os 12 pares de conteúdo igual incluem os dois acertos.

Depende de **138** (o produto efetivo do grupo; com ele, `duplicate_candidates` já deixou de ver absorvidos, porque deriva de `list_products`).

## Escopo

### Dentro
- `julius/services/curation.py`: `duplicate_candidates` descarta par com conteúdo divergente.
- `tests/test_services_curation.py`.

### Fora
- Fundir automaticamente (→ 143).
- Filtrar por `kind`: **medido e reprovado** (F5 — 12 dos 19 pares têm tipo igual, incluindo Água c/gás ≈ s/gás, Pepsi ≈ Guaraná e os três Dry Rub). Não reintroduzir.
- Qualquer corte de confiança (F4: os acertos vieram com 0,70/0,80 e o falso positivo histórico com 1,00).
- Excluir produtos absorvidos: já vem do 138. Confirme com um teste, não com código novo.

## Requisitos

### Funcionais

- Em `duplicate_candidates`, um par é descartado **antes de virar candidato** quando os dois produtos têm `content_quantity` não-nulo e o conteúdo difere. "Difere" inclui unidade diferente (`0,5 L` vs `0,5 KG`): são dimensões que o sistema nunca compara.
- Par em que só um lado tem conteúdo **continua candidato** (é o caso `Alho ≈ Pão de Alho`, que a IA hoje rejeita; a proteção dele é a notificação de herança do 143).
- Par em que nenhum lado tem conteúdo continua candidato (é o caso do acerto `Banana prata ≈ Banana Prata Extra União`).
- O descarte é silencioso: nada é impresso, e o par volta a ser candidato sozinho se algum dos conteúdos mudar.

### Validação e erros
- `duplicate_candidates` continua não lançando e continua determinística (sem IA).

## Especificação técnica

```
modificar julius/services/curation.py
modificar tests/test_services_curation.py
```

### Padrão a seguir
- O filtro entra no mesmo laço que já aplica `DUPLICATE_CANDIDATE_CUTOFF`; nenhuma constante nova.
- `Product` já traz `content_quantity`/`content_unit`, então a comparação é em memória — sem query nova.

## Testes obrigatórios

1. `test_divergent_content_is_not_a_candidate` — dois produtos de nomes quase iguais, um `2 L` e outro `1.5 L` → o par não aparece, mesmo com score acima do corte.
2. `test_divergent_content_unit_is_not_a_candidate` — `0.5 L` vs `0.5 KG` → descartado.
3. `test_same_content_is_still_a_candidate` — os dois `0.5 KG` → aparece.
4. `test_one_sided_content_is_still_a_candidate` — um com conteúdo, outro sem → aparece.
5. `test_absorbed_products_are_not_candidates` — funde dois produtos e confere que o par não é sugerido de novo (prova que o efeito do 138 chegou aqui).
6. Os testes existentes de `duplicate_candidates` sobre os 5 recibos continuam passando **sem edição** — se algum quebrar, o filtro está pegando par que não devia.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `grep -n "kind" julius/services/curation.py` não mostra nenhum uso em `duplicate_candidates`.
- [ ] Rodar contra uma cópia do banco real: `duplicate_candidates` devolve **15** pares (contra 19 hoje), e os 4 que saíram são os de F16.

## Notas para o agente
- O filtro é sobre **candidato**, não sobre veredito: descartar antes economiza a chamada de IA e mantém a regra numa função determinística e testável.
- Não confunda com o guarda de unidade de venda (`UN`/`KG`) de `comparison_basis`: aqui é o conteúdo declarado da embalagem.
