# QI tecnologia

**Integrantes:** Arthur Lima Marques Rocha, Beatriz Kimberlin do Carmo Barssoti, Robert Souza Gom

Motor antifraude de Pix. Uma API recebe o pedido de Pix e responde `approved`, `two_factor_required` ou `rejected`, sempre com o motivo da decisão registrado.

---

## Como o motor de decisão funciona

### Em uma frase

Cada Pix que chega passa por 14 regras independentes. Cada regra olha um sinal de risco (valor, horário, velocidade, histórico, conta de destino, dispositivo) e devolve **pontos**, um **bloqueio** ou uma **exigência de 2FA**. A soma dos pontos e esses sinais decidem: aprova, pede 2FA ou reprova. O que é "normal" vem, sempre que possível, do passado do próprio pagador.

### O caminho de um Pix

```
POST /pix/transaction
   │
   ├─ 1. o schema confere o formato do JSON ............ torto → 400
   ├─ 2. as datas precisam ter fuso e existir ........... inválida → 422
   ├─ 3. esse `id` já foi analisado? .................... sim → devolve a análise gravada (200)
   ├─ 4. grava a transação (documentos só com dígitos)
   ├─ 5. busca o histórico necessário (poucas consultas, com índice)
   ├─ 6. roda as 14 regras → lista de (regra, pontos, motivo)
   ├─ 7. calcula a decisão (ver "Como as regras viram decisão")
   ├─ 8. grava a análise: key, status e metadata
   └─ 9. responde { key, status, metadata } ............. 201

GET /pix/transaction/{id}   →   devolve a análise que foi gravada
```

### Princípios de desenho

1. **Sinal fraco sozinho não incomoda ninguém.** Pagar um novo destinatário ou usar um celular novo é normal. Por isso cada regra vale pontos e o 2FA só aparece quando os pontos se somam.
2. **O normal é de cada pagador.** R$ 8.000 é rotina para uma empresa que paga fornecedores e é um sinal forte para quem costuma mandar R$ 400. Nas regras de valor, rajada e total diário, o limite é calculado a partir do histórico do próprio pagador. O valor fixo só entra quando ainda não há histórico suficiente.
3. **Pessoa física e empresa não são tratadas igual.** R$ 10.000 para um CNPJ pode ser uma despesa empresarial rotineira, enquanto R$ 10.000 para um CPF pode ser atípico. Os limites consideram se o destinatário (ou o pagador, nas regras de velocidade e de total diário) é CPF ou CNPJ.
4. **Reprovar é raro.** Exige evidência forte de fraude ou pontuação muito alta. Um Pix de valor elevado não é, por si só, prova de fraude: ele exige 2FA para o cliente confirmar que é ele mesmo.
5. **Valores altos pedem 2FA, não um bloqueio cego.** Um valor extremo para o pagador sempre passa por 2FA, mesmo que a pontuação seja baixa, e fica registrado no `metadata`.
6. **Todas as regras rodam, sem atalho.** Assim o `metadata` mostra tudo o que pesou na decisão, e a decisão é sempre explicável.

### Vocabulário (vale para todas as regras)

| Termo | Significado |
|---|---|
| **agora** | o `transaction_date` do Pix analisado. Nunca o relógio do servidor, para que a análise seja a mesma se o Pix for reenviado depois. |
| **pagador** / **destinatário** | `source_account.owner.document_number` / `destination_account.owner.document_number`, guardados só com dígitos (`123.456.789-09` vira `12345678909`). |
| **CPF / CNPJ** | documento com 11 dígitos é CPF (pessoa física); com 14 é CNPJ (empresa). |
| **histórico** | Pix já gravados com `transaction_date` **anterior** ao de agora, excluindo o próprio `id`. |
| **tentativa** | qualquer Pix do histórico, qualquer que tenha sido a decisão (inclusive `rejected`). |
| **movimentação efetiva** | Pix do histórico cuja decisão **não** foi `rejected`. |
| **dia ativo** | dia (no horário local) em que o pagador teve ao menos uma movimentação efetiva. |
| **base** | o conjunto de números do passado do pagador que uma regra usa para aprender o seu limite (ver "Limites que aprendem com o pagador"). |
| **piso** | o menor valor a partir do qual uma regra faz sentido, mesmo que o histórico sugira um limite menor. |
| **horário local** | `America/Sao_Paulo`. A hora de `transaction_date` é convertida para esse fuso antes de qualquer regra de horário. |
| **valores** | sempre em centavos no código e no banco. Neste documento aparecem em reais. |

### Banco de dados

Duas tabelas, em `database/database.sql`:

- `pix_transaction`: o que chegou (um registro por `id` de Pix, com o `id` único). Tem índices para as consultas de histórico: por pagador e data, por destinatário e data, por par pagador-destinatário e por dispositivo e data.
- `pix_analysis`: o que decidimos (`key` UUID, `status` e `metadata` em JSON), uma por transação.

Separar entrada e decisão permite reanalisar um Pix no futuro sem mexer no que foi recebido.

### Onde está o código

```
src/resources/pix_transaction.py            recebe o HTTP, valida o schema, devolve o status HTTP
src/schemas/post_pix_transaction.json       contrato de entrada
src/controllers/pix_transaction_controller.py   orquestra: idempotência, grava, busca histórico, chama o motor, grava a análise
src/controllers/antifraud/                  o motor e as regras (sem acesso a banco)
src/controllers/antifraud/limits.py         escala robusta, limite aprendido e escolha entre limite aprendido e fixo
src/controllers/antifraud/constants.py      todos os parâmetros
src/repositories/pix_transaction_repository.py  consultas, inclusive as de histórico
src/dtos/pix_analysis_dto.py                devolve só key, status e metadata
```

O motor recebe a transação e o histórico já carregado e devolve uma decisão. Ele não fala com o banco nem com HTTP.

---

## Regras

Os parâmetros abaixo são **padrões de política**, escolhidos por raciocínio e pela regulação, e não ajustados em dados reais de fraude (não temos dados rotulados). Estão todos em um módulo só (`src/controllers/antifraud/constants.py`) justamente para poderem ser calibrados depois. Ver "Sobre a calibração" mais abaixo.

As regras marcadas com *(aprende)* calculam o limite a partir do histórico do pagador e usam um valor fixo quando não há histórico suficiente. A seção "Limites que aprendem com o pagador" explica como isso funciona.

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `night_over_limit` *(limite)* | Pagador pessoa física (CPF) paga acima do limite noturno entre 20h e 6h. | Janela 20h–6h; limite R$ 1.000; **+2**. | Espelha o limite noturno padrão do Banco Central para pessoas físicas, que o cliente pode alterar. Vale só 2 pontos porque ele pode ter aumentado o limite de propósito. Sozinha não pede 2FA. |
| `amount_vs_median` *(perfil, aprende)* | O valor está muito acima do que o pagador costuma enviar. | Base: valores dos Pix efetivos do pagador (90 dias, até 50). Mínimo 5. Limite = mediana + 3 × escala robusta; piso R$ 500; **+2**. Sem histórico: regra pulada. | Não compara um valor bruto com um múltiplo arbitrário da mediana. A mediana representa o centro; a escala robusta (baseada no MAD, desvio absoluto mediano) estima a dispersão sem ser distorcida por Pix extremos. Para um valor individual, o erro-padrão da média não é a escala correta: ele mede a incerteza da estimativa do centro e diminui com mais amostras, podendo sinalizar operações normais como anômalas. |
| `high_value_review` *(valor crítico, aprende)* | **Caso crítico de `amount_vs_median`**: o valor é extremo para este pagador e alto em termos absolutos. | Mesma base. Limite = mediana + 6 × escala robusta; piso por tipo de destinatário: **CPF** R$ 5.000, **CNPJ** R$ 20.000. Sem histórico: teto fixo, **CPF** R$ 30.000, **CNPJ** R$ 100.000. Efeito: **exige 2FA**, mesmo com pontuação baixa. | Um valor muito acima do habitual pode ser legítimo e importante; bloquear automaticamente pode causar dano ao cliente. Em vez de rejeitar, o cliente confirma que é ele mesmo com 2FA. O piso evita pedir 2FA por um valor pequeno só porque o pagador é muito regular. O teto fixo só vale quando não há passado. |
| `destination_type_amount` *(contraparte, aprende)* | O valor é elevado para o tipo de destinatário (CPF ou CNPJ). | Base: Pix efetivos do pagador para destinatários **do mesmo tipo** (90 dias, até 50). Mínimo 5. Limite = mediana + 3 × escala robusta; piso **CPF** R$ 1.000, **CNPJ** R$ 5.000; pontos **CPF +3**, **CNPJ +2**. Sem histórico daquele tipo: **CPF** ≥ R$ 10.000, **CNPJ** ≥ R$ 50.000. | Uma transferência para uma pessoa física merece mais escrutínio do que o mesmo valor para uma empresa, que pode estar pagando fornecedores ou despesas operacionais. Quem sempre paga empresas e agora manda para um CPF não tem histórico com CPFs: vale o valor fixo. É um sinal de risco, não uma rejeição automática. |
| `burst` *(velocity, aprende)* | Muitas tentativas do mesmo pagador em poucos minutos. | Janela 10 min. Base: pico de Pix efetivos em qualquer janela de 10 min nos últimos 90 dias (mínimo 10 Pix). Alerta ≥ 2 × pico (piso **CPF** 4, **CNPJ** 10): **+3**. Bloqueio ≥ 4 × pico (piso **CPF** 10, **CNPJ** 40). Sem histórico: **CPF** 5 (+3) e 10 (bloqueio); **CNPJ** 20 (+3) e 40 (bloqueio). | Quem toma uma conta esvazia o saldo rápido, mas uma empresa que paga fornecedores ou faz repasses em lote também. Comparar com o maior pico que o próprio pagador já teve separa os dois casos. Conta tentativas rejeitadas porque insistir é sinal de risco. O histórico pode relaxar o bloqueio, mas nunca baixá-lo abaixo do valor fixo: rejeitar automaticamente é uma decisão séria. |
| `rolling_24h_total` *(montante, aprende)* | O total que o pagador movimentou em 24h, mais este Pix, passa do que ele costuma movimentar por dia. | Base: total por dia ativo nos últimos 90 dias (mínimo 5 dias ativos). Alerta ≥ mediana + 3 × escala (piso **CPF** R$ 2.000, **CNPJ** R$ 10.000): **+2**. Nível crítico ≥ mediana + 6 × escala (piso **CPF** R$ 10.000, **CNPJ** R$ 50.000): **exige 2FA**. Sem histórico: alerta **CPF** R$ 10.000 e **CNPJ** R$ 50.000; nível crítico **CPF** R$ 30.000 e **CNPJ** R$ 150.000. | Pega o golpe fatiado em vários Pix pequenos, que passaria por qualquer regra que olhe um Pix de cada vez. O tipo do **pagador** define o piso e o valor fixo: uma empresa movimenta muito mais por dia que uma pessoa. O nível crítico leva a 2FA (e não à rejeição) pelo mesmo motivo de `high_value_review`: dinheiro grande pede confirmação do cliente, não um bloqueio cego. |
| `new_device` *(perfil)* | Primeira vez que o pagador usa este dispositivo. | Pagador com ≥ 3 Pix em 90 dias; `device_id` inédito; valor ≥ R$ 200; **+2**. | Sinal clássico de conta tomada. Só vale se já existe um dispositivo habitual. No primeiro Pix de alguém tudo é "novo". |
| `young_payer_account` *(perfil)* | Conta de origem aberta há pouco tempo movimenta valor alto. | Idade < 30 dias; valor > R$ 1.000; **+1**. | Contas recém-abertas que enviam muito dinheiro são padrão de identidade falsa ou conta de passagem. Sinal fraco. |
| `impossible_travel` *(perfil)* | Dois Pix do mesmo pagador em lugares tão distantes que o deslocamento seria impossível. | Pix anterior com geolocalização nas últimas 24h; distância ≥ 100 km; velocidade > 900 km/h; **+3**. | Indica que a sessão ou o dispositivo não são da mesma pessoa. O piso de 100 km evita falso alarme por imprecisão de GPS. |
| `young_destination` *(contraparte)* | A conta que recebe foi aberta há pouco tempo. | Valor ≥ R$ 500; idade < 7 dias **+3**; idade < 30 dias **+2**. | Contas de laranja são abertas pouco antes de serem usadas. Quanto mais nova, maior o risco. |
| `new_payee` *(contraparte)* | Primeira vez que este pagador paga este destinatário. | Valor ≥ R$ 1.000; **+1**. | Sinal fraco: serve de desempate junto com outros. Sozinho não incomoda ninguém. |
| `payee_burst` *(contraparte)* | Muitos pagamentos do pagador ao mesmo destinatário, em pouco tempo, **sem relacionamento anterior** entre os dois. | Janela 30 min; soma na janela ≥ R$ 1.000; destinatário **CPF**: ≥ 3 Pix **+2**, ≥ 5 Pix **+3**; destinatário **CNPJ**: ≥ 5 Pix **+2**, ≥ 10 Pix **+3**. Não dispara se o pagador já tinha Pix efetivos para esse destinatário **antes** da janela. | É o padrão de quem está sendo induzido a pagar várias vezes a um desconhecido (golpe do falso pagamento, falsa central). A conta de destino não precisa ser nova: o que importa é que o pagador não tem história com ela. Quem paga uma empresa várias vezes seguidas (compras no mesmo dia) é mais comum, por isso o limiar é maior para CNPJ. O piso de R$ 1.000 evita alerta por rachar uma conta de restaurante. |
| `mule_fan_in` *(contraparte)* | Um CPF recebe de muitos pagadores diferentes em pouco tempo. | Destinatário CPF; janela 24h; ≥ 5 pagadores distintos **+3**; ≥ 10 **bloqueio**. | É o desenho de uma conta de laranja: junta dinheiro de várias vítimas. Só vale para CPF, porque uma empresa (CNPJ) recebe de muita gente legitimamente. |
| `shared_device` *(contexto)* | O mesmo dispositivo é usado por vários pagadores diferentes. | Janela 24h; ≥ 3 pagadores distintos (contando o atual); **+3**. | Indica uma "fazenda de dispositivos" ou uma quadrilha operando várias contas do mesmo aparelho. |

### Quem importa em cada regra: pagador ou destinatário

| Tipo que decide os limites | Regras |
|---|---|
| **Destinatário** (para quem vai o dinheiro) | `high_value_review`, `destination_type_amount`, `payee_burst`, `mule_fan_in` (só CPF) |
| **Pagador** (quem envia) | `burst`, `rolling_24h_total`, `night_over_limit` (só CPF) |

### Limites que aprendem com o pagador

**A ideia.** O que é normal depende de quem paga. As regras de valor, rajada e total diário comparam o Pix com o passado **do próprio pagador**. Só quando o pagador ainda não tem passado suficiente, a regra usa um valor fixo, por tipo (CPF ou CNPJ). Isso é mais justo com clientes regulares e mais duro com quem foge do próprio padrão.

**Passo a passo (igual para todas as regras que aprendem):**

1. O repositório carrega, em **uma consulta** (índice por pagador e data), os Pix efetivos do pagador nos últimos 90 dias, no máximo 500 linhas, com data, valor, documento do destinatário e dispositivo.
2. Cada regra monta a sua **base** a partir dessas linhas (tabela abaixo).
3. Se a base tem amostras suficientes, o **limite aprendido** vale: `limite = max(piso, limite aprendido)`. No `metadata`, `basis = "history"`.
4. Se não tem, vale o **limite fixo** do tipo correspondente. No `metadata`, `basis = "fixed"`.
5. A regra compara o Pix com o limite e escreve no `reason` o valor do limite e de onde ele veio.

| Regra | O que aprende (a base) | Mínimo para aprender | Limite aprendido | Sem histórico (fixo) |
|---|---|---|---|---|
| `amount_vs_median` | valores dos Pix do pagador | 5 Pix | mediana + 3 × escala | pulada |
| `high_value_review` | valores dos Pix do pagador | 5 Pix | mediana + 6 × escala | teto fixo por destinatário |
| `destination_type_amount` | valores dos Pix do pagador **para o mesmo tipo de destinatário** | 5 Pix daquele tipo | mediana + 3 × escala | valor fixo por destinatário |
| `burst` | pico de Pix em 10 minutos | 10 Pix | alerta 2 × pico; bloqueio 4 × pico | valores fixos por pagador |
| `rolling_24h_total` | total por dia ativo | 5 dias ativos | mediana + 3 × escala (alerta); mediana + 6 × escala (crítico) | valores fixos por pagador |

**A escala robusta.** Em vez de média e desvio padrão (que um único Pix grande distorce), usamos a mediana e o MAD:

```
mediana = mediana(amostras)
MAD     = mediana(|amostra − mediana|)
escala  = max(1,4826 × MAD, 25% da mediana)
limite aprendido = mediana + k × escala        (k = 3 alerta, k = 6 crítico)
```

O fator 1,4826 faz a escala equivaler a um desvio padrão quando os dados são "bem comportados". O piso de 25% da mediana garante que mesmo um pagador perfeitamente regular só levante alerta bem acima do habitual: com k = 3, a partir de 1,75 × a mediana. Sem esse piso, quem sempre paga o mesmo valor teria escala zero e qualquer variação pequena viraria alerta.

**O piso.** Cada regra tem um valor mínimo abaixo do qual ela nunca dispara, mesmo que o histórico sugira um limite menor. Nos casos de alerta, o piso evita ruído (a estatística de quem manda R$ 20 por Pix não deve gerar alerta com R$ 90). Nos casos graves (2FA forçado e bloqueio de rajada), o piso protege o cliente de uma confirmação ou rejeição desnecessária.

**Como o limite é escolhido (pseudocódigo, em `limits.py`):**

```python
def robust_scale(samples):
    m = median(samples)
    mad = median(abs(x - m) for x in samples)
    return m, max(1.4826 * mad, 0.25 * m)

def learned_limit(samples, k):
    m, scale = robust_scale(samples)
    return m + k * scale

def burst_peak(timestamps, window_minutes):
    # maior número de Pix em qualquer janela de 10 min (duas pontas, O(n))
    ...

def resolve(rule, kind, history):
    learned = rule.learn(history)            # None se faltar amostra
    if learned is None:
        return Limit(value=rule.fixed[kind], basis="fixed")
    return Limit(value=max(rule.floor[kind], learned), basis="history")
```

`kind` é `"cpf"` ou `"cnpj"`: do destinatário nas regras de valor e de `payee_burst`, do pagador em `burst` e `rolling_24h_total`.

### Detalhes e casos de borda

Esta parte existe para que não reste dúvida de como cada regra é calculada. Quando não se disser o contrário, atingir o limite (≥) já dispara.

**Pagando para si mesmo.** Se o documento do pagador for igual ao do destinatário, as regras `young_destination`, `new_payee`, `payee_burst` e `mule_fan_in` são puladas: é a pessoa movendo o próprio dinheiro, e isso é rotina.

**Falta de histórico.** Toda regra que depende de histórico tem um mínimo de amostras. Se não chega a ele:

- as regras que aprendem (`high_value_review`, `destination_type_amount`, `burst`, `rolling_24h_total`) **voltam ao limite fixo** e registram `basis = "fixed"`;
- as regras sem versão fixa (`amount_vs_median`, `new_device`, `impossible_travel`) **não rodam** e registram o motivo em `rules_skipped`. Elas não aprovam nem reprovam em silêncio.

Isso evita punir quem acabou de chegar: o primeiro Pix de qualquer pagador é julgado pelos valores fixos e pelas regras que não precisam de passado.

**Quais Pix do histórico contam em cada regra:**

| Regra | Conta | Por quê |
|---|---|---|
| `burst` (contagem atual), `payee_burst` (contagem na janela), `mule_fan_in`, `shared_device` | todas as tentativas | o comportamento de insistir ou de juntar dinheiro aparece mesmo quando já fomos reprovando. |
| `burst` (pico aprendido), `rolling_24h_total`, `amount_vs_median`, `high_value_review`, `destination_type_amount`, `new_payee`, `payee_burst` (relacionamento prévio) | só movimentações efetivas | um Pix reprovado não saiu da conta, então não soma ao total, não define o "habitual", não eleva o pico aprendido e não torna alguém um "destinatário conhecido". |
| `new_device` | todas as tentativas do pagador | o dispositivo já foi usado, mesmo numa tentativa reprovada. |

**Cálculo de cada regra:**

- `night_over_limit`: converte `transaction_date` para `America/Sao_Paulo`. É noite se a hora for ≥ 20 ou < 6. Só vale quando o pagador é CPF.
- `amount_vs_median`: base = valores das movimentações efetivas dos últimos 90 dias (as 50 mais recentes). Precisa de pelo menos 5. Dispara se `amount ≥ max(R$ 500, mediana + 3 × escala)`.
- `high_value_review`: mesma base. Com 5 ou mais amostras, dispara se `amount ≥ max(piso do destinatário, mediana + 6 × escala)`. Com menos de 5, dispara se `amount ≥ teto fixo do destinatário`. Os valores de piso e teto dependem do tipo do **destinatário** (CPF: R$ 5.000 e R$ 30.000; CNPJ: R$ 20.000 e R$ 100.000). É um subcaso de `amount_vs_median`: um Pix pode disparar as duas regras, e os pontos de uma não anulam o fluxo da outra.
- `destination_type_amount`: separa as amostras pelo tipo do documento do destinatário (11 dígitos = CPF; 14 = CNPJ) e usa só as do mesmo tipo do Pix atual (as 50 mais recentes). Com 5 ou mais, dispara se `amount ≥ max(piso, mediana + 3 × escala)` (piso R$ 1.000 para CPF, R$ 5.000 para CNPJ). Com menos, dispara se `amount ≥ valor fixo` (R$ 10.000 para CPF, R$ 50.000 para CNPJ). Pontos: CPF +3, CNPJ +2. Os limites são parâmetros de política, não afirmações de que todo Pix empresarial é seguro.
- `burst`: conta as tentativas do pagador com `transaction_date` em (agora − 10 min, agora) e **soma 1** pelo Pix atual (todas as decisões). Com 10 ou mais Pix efetivos em 90 dias, calcula o pico `P`: o maior número de Pix efetivos em qualquer janela de 10 minutos (percorrendo as datas em ordem, com duas pontas). Limite de alerta = `max(piso de alerta, ceil(2 × P))`; limite de bloqueio = `max(piso de bloqueio, ceil(4 × P))`. Pisos: alerta CPF 4 / CNPJ 10; bloqueio CPF 10 / CNPJ 40. Sem histórico: CPF 5 e 10; CNPJ 20 e 40. O tipo que vale é o do **pagador**.
- `rolling_24h_total`: o valor atual é `V` = soma de `amount` das movimentações efetivas do pagador em [agora − 24h, agora) **mais o valor do Pix atual**. A base é o total por dia ativo (no horário local, só dias anteriores ao de agora, últimos 90 dias). Com 5 ou mais dias ativos: alerta se `V ≥ max(piso, mediana + 3 × escala)` e crítico se `V ≥ max(piso crítico, mediana + 6 × escala)`. Pisos de alerta: CPF R$ 2.000 / CNPJ R$ 10.000. Pisos críticos: CPF R$ 10.000 / CNPJ R$ 50.000. Sem histórico: alerta CPF R$ 10.000 / CNPJ R$ 50.000; crítico CPF R$ 30.000 / CNPJ R$ 150.000. O tipo que vale é o do **pagador**. O dia de agora é comparado com a base de dias anteriores, e a janela de 24h é móvel: a pequena diferença entre as duas medidas é aceitável para uma regra de alerta.
- `new_device`: precisa de pelo menos 3 Pix do pagador nos últimos 90 dias. Dispara se nenhum deles veio do `device_id` atual e `amount ≥ R$ 200`.
- `young_payer_account`: idade = agora − `source_account.opening_date`.
- `impossible_travel`: precisa de `geolocation` no Pix atual e em algum Pix anterior do pagador nas últimas 24h (usa o mais recente com geolocalização). Distância pela fórmula de haversine. Velocidade = distância ÷ horas entre os dois, com um mínimo de 1 minuto para nunca dividir por zero.
- `young_destination`: idade = agora − `destination_account.opening_date`. Se a data de abertura for **posterior** a agora (dado inconsistente), a idade é tratada como zero, ou seja, a faixa mais arriscada. Aplica **uma** faixa só: a de < 7 dias ou a de < 30 dias, nunca as duas.
- `new_payee`: dispara se o pagador não tem **nenhum** Pix efetivo anterior para esse documento de destino (inclusive os feitos há poucos minutos) e `amount ≥ R$ 1.000`. Só o primeiro pagamento da sequência dispara.
- `payee_burst`: conta as tentativas (qualquer decisão) do pagador para o mesmo documento de destino em (agora − 30 min, agora), **incluindo o atual** (`N`), e soma os valores delas (`S`). Primeiro verifica o relacionamento: se o pagador tem algum Pix efetivo para esse destinatário com data **anterior a agora − 30 min** (nos últimos 90 dias), a regra não dispara. Se não tem, e `S ≥ R$ 1.000`: destinatário CPF dispara +2 com `N ≥ 3` e +3 com `N ≥ 5`; destinatário CNPJ dispara +2 com `N ≥ 5` e +3 com `N ≥ 10`. Não depende da idade da conta de destino.
- `mule_fan_in`: conta documentos de pagador **distintos** que enviaram para o mesmo documento de destino nas últimas 24h, **incluindo o pagador atual**.
- `shared_device`: conta documentos de pagador distintos que usaram o mesmo `device_id` nas últimas 24h, **incluindo o pagador atual**.

**Faixas de uma mesma regra são exclusivas.** Quando uma regra tem faixas (ex.: `burst` com +3 e bloqueio, ou `rolling_24h_total` com alerta e nível crítico), vale só a mais alta que foi atingida.

**Regras relacionadas podem disparar juntas.** `amount_vs_median` compara o Pix com o passado geral do pagador; `destination_type_amount`, com o passado do pagador para aquele tipo de destinatário. O mesmo Pix pode ser incomum nas duas visões, e nesse caso os pontos se somam. `new_payee` e `payee_burst` também se complementam: a primeira marca o primeiro pagamento, a segunda a repetição seguida.

### Parâmetros em um lugar só

É a lista que o código lê. Valores em centavos. Onde há `cpf` e `cnpj`, o tipo vem do destinatário ou do pagador, conforme a tabela "Quem importa em cada regra".

```python
# src/controllers/antifraud/constants.py

# --- comum aos limites que aprendem ---
HISTORY_WINDOW_DAYS          = 90
HISTORY_MAX_ROWS             = 500            # linhas carregadas por consulta
SAMPLE_MAX_ROWS              = 50             # amostras mais recentes nas regras de valor
ROBUST_MAD_FACTOR            = 1.4826
ROBUST_SCALE_FLOOR_RATIO     = 0.25           # escala mínima = 25% da mediana
WARN_Z                       = 3.0            # k do alerta
CRITICAL_Z                   = 6.0            # k do nível crítico
AMOUNT_MIN_SAMPLES           = 5              # amount_vs_median, high_value_review, destination_type_amount

NIGHT_START_HOUR             = 20             # horário local, inclusive
NIGHT_END_HOUR               = 6              # horário local, exclusive
NIGHT_LIMIT                  = 100_000        # R$ 1.000
NIGHT_POINTS                 = 2

# --- amount_vs_median ---
MEDIAN_MIN_AMOUNT            = 50_000         # R$ 500 (piso)
MEDIAN_POINTS                = 2

# --- high_value_review (caso crítico de amount_vs_median) ---
HIGH_VALUE_FLOOR             = {"cpf": 500_000,    "cnpj": 2_000_000}    # R$ 5.000 / R$ 20.000
HIGH_VALUE_FIXED_CEILING     = {"cpf": 3_000_000,  "cnpj": 10_000_000}   # R$ 30.000 / R$ 100.000 (sem histórico)

# --- destination_type_amount ---
DEST_TYPE_FLOOR              = {"cpf": 100_000,    "cnpj": 500_000}      # R$ 1.000 / R$ 5.000
DEST_TYPE_FIXED              = {"cpf": 1_000_000,  "cnpj": 5_000_000}    # R$ 10.000 / R$ 50.000 (sem histórico)
DEST_TYPE_POINTS             = {"cpf": 3,          "cnpj": 2}

# --- burst (tipo do pagador) ---
BURST_WINDOW_MINUTES         = 10
BURST_MIN_HISTORY            = 10             # Pix efetivos em 90 dias
BURST_WARN_FACTOR            = 2              # alerta = 2 x pico
BURST_BLOCK_FACTOR           = 4              # bloqueio = 4 x pico
BURST_WARN_FLOOR             = {"cpf": 4,  "cnpj": 10}
BURST_BLOCK_FLOOR            = {"cpf": 10, "cnpj": 40}
BURST_FIXED                  = {"cpf": (5, 10), "cnpj": (20, 40)}        # (alerta, bloqueio) sem histórico
BURST_POINTS                 = 3

# --- rolling_24h_total (tipo do pagador) ---
DAILY_WINDOW_HOURS           = 24
DAILY_MIN_ACTIVE_DAYS        = 5
DAILY_WARN_FLOOR             = {"cpf": 200_000,    "cnpj": 1_000_000}    # R$ 2.000 / R$ 10.000
DAILY_CRITICAL_FLOOR         = {"cpf": 1_000_000,  "cnpj": 5_000_000}    # R$ 10.000 / R$ 50.000
DAILY_FIXED                  = {"cpf": (1_000_000, 3_000_000),
                                "cnpj": (5_000_000, 15_000_000)}         # (alerta, crítico) sem histórico
DAILY_POINTS                 = 2

NEW_DEVICE_MIN_HISTORY       = 3
NEW_DEVICE_MIN_AMOUNT        = 20_000         # R$ 200
NEW_DEVICE_POINTS            = 2

YOUNG_PAYER_DAYS             = 30
YOUNG_PAYER_MIN_AMOUNT       = 100_000        # R$ 1.000
YOUNG_PAYER_POINTS           = 1

TRAVEL_WINDOW_HOURS          = 24
TRAVEL_MIN_DISTANCE_KM       = 100
TRAVEL_MAX_SPEED_KMH         = 900
TRAVEL_MIN_ELAPSED_MINUTES   = 1
TRAVEL_POINTS                = 3

YOUNG_DEST_MIN_AMOUNT        = 50_000         # R$ 500
YOUNG_DEST_VERY_NEW_DAYS     = 7              # +3
YOUNG_DEST_NEW_DAYS          = 30             # +2
YOUNG_DEST_VERY_NEW_POINTS   = 3
YOUNG_DEST_NEW_POINTS        = 2

NEW_PAYEE_MIN_AMOUNT         = 100_000        # R$ 1.000
NEW_PAYEE_POINTS             = 1

# --- payee_burst (tipo do destinatário) ---
PAYEE_BURST_WINDOW_MINUTES   = 30
PAYEE_BURST_MIN_TOTAL        = 100_000        # R$ 1.000 somados na janela
PAYEE_BURST_WARN_COUNT       = {"cpf": 3, "cnpj": 5}                     # +2
PAYEE_BURST_STRONG_COUNT     = {"cpf": 5, "cnpj": 10}                    # +3
PAYEE_BURST_WARN_POINTS      = 2
PAYEE_BURST_STRONG_POINTS    = 3

FAN_IN_WINDOW_HOURS          = 24
FAN_IN_WARN_PAYERS           = 5              # +3
FAN_IN_BLOCK_PAYERS          = 10             # bloqueio
FAN_IN_POINTS                = 3

SHARED_DEVICE_WINDOW_HOURS   = 24
SHARED_DEVICE_PAYERS         = 3
SHARED_DEVICE_POINTS         = 3

TWO_FACTOR_THRESHOLD         = 3
REJECT_THRESHOLD             = 8
```

### Sobre a calibração

Estes números não saíram de um modelo treinado, e dizer o contrário seria enganar quem lê. Eles saíram de três fontes: a regulação (o limite noturno), padrões conhecidos de fraude em Pix (conta de laranja, tomada de conta, fracionamento, golpe do falso pagamento) e o princípio de proteger o cliente bom (pisos de valor, exceções e limites que aprendem com o próprio cliente).

Os limites aprendidos têm uma fragilidade conhecida: dependem do histórico do pagador, e um fraudador que opera uma conta por semanas pode "ensinar" um padrão mais alto. Para reduzir esse risco, só movimentações **efetivas** entram na base (Pix reprovados não normalizam nada), os pisos impedem que o limite caia abaixo do que faz sentido, e o bloqueio de rajada nunca desce abaixo do valor fixo. Em produção, valeria acrescentar tetos absolutos por cliente.

O caminho de calibração seria: guardar cada decisão, cruzar com as fraudes confirmadas e as contestações, medir quantos clientes bons foram incomodados (falso positivo) e quantas fraudes passaram (falso negativo), e ajustar `constants.py` para uma meta de falso positivo. Os limites de CPF/CNPJ são hipóteses iniciais: devem ser calibrados por segmento empresarial, perfil de cliente e dados reais. É por isso que todos os parâmetros estão em um arquivo só e que o `metadata` guarda a pontuação de cada decisão e de onde veio cada limite.

---

## Como as regras viram decisão

### A ordem

1. Todas as regras rodam (a ordem delas não muda o resultado). Cada uma devolve pontos, um bloqueio, uma exigência de 2FA ou "pulada".
2. Soma-se a pontuação de todas as regras que dispararam.
3. A decisão sai por prioridade, de cima para baixo. A exigência de 2FA vale mesmo com pontuação baixa; uma regra de bloqueio ou pontuação ≥ 8 continua prevalecendo como rejeição:

| Condição | Decisão | Quando acontece |
|---|---|---|
| alguma regra **bloqueou** (`burst` ou `mule_fan_in`) | `rejected` | o risco é claro por si só: rajada muito acima do normal do pagador ou uma conta que junta dinheiro de muitas vítimas. |
| pontuação **≥ 8** | `rejected` | vários sinais fortes juntos: não há dúvida razoável. |
| alguma regra **exigiu 2FA** (`high_value_review` ou nível crítico de `rolling_24h_total`) **ou** pontuação **≥ 3** | `two_factor_required` | valor extremo sempre pede 2FA, mesmo com pontuação baixa; nos demais casos, há dúvida e o cliente precisa confirmar a identidade. |
| pontuação **< 3** | `approved` | segue normal, sem fricção. |

### Quando pede 2FA

A régua dos pesos é simples e vale para todas as regras:

- **+3 (sinal forte):** sozinho já pede 2FA. É o caso de rajada, destinatário que junta dinheiro de muitos, dispositivo compartilhado, viagem impossível, conta de destino com menos de 7 dias, valor atípico para um destinatário pessoa física e muitos pagamentos seguidos a um desconhecido.
- **+2 (sinal médio):** precisa de companhia. Dois sinais médios, ou um médio e um fraco, pedem 2FA.
- **+1 (sinal fraco):** só ajuda a desempatar.

O limiar de reprovar (8) equivale a cerca de três sinais fortes ao mesmo tempo. É de propósito alto: reprovar um cliente bom custa caro. Valor alto, por si só, não soma pontos nem causa rejeição: força o 2FA.

### Exemplos

**Aprovado.** Pix de R$ 150,00 às 14h, para alguém que o cliente já pagou antes, com conta antiga e comportamento normal. Nenhuma regra dispara: pontuação 0.

**2FA (o Pix do exemplo do desafio).** R$ 1.500,00 às 22h15, de uma conta aberta em 2025, para uma conta aberta 7 dias antes, sem histórico do pagador:

| Regra | Resultado |
|---|---|
| `night_over_limit` | R$ 1.500 > R$ 1.000 em horário noturno: +2 |
| `young_destination` | conta de destino com 7 dias (menos de 30) e valor ≥ R$ 500: +2 |
| `new_payee` | primeiro Pix para esse destinatário, valor ≥ R$ 1.000: +1 |
| `high_value_review`, `destination_type_amount`, `burst`, `rolling_24h_total` | rodam com o limite fixo (sem histórico) e não disparam |
| `amount_vs_median`, `new_device`, `impossible_travel` | puladas por falta de histórico |

Pontuação 5, entre 3 e 7: **`two_factor_required`**.

**Reprovado por pontuação.** R$ 12.000,00 às 2h30, de um CPF com 20 Pix anteriores para outras pessoas físicas (mediana R$ 300, escala ≈ R$ 255), dispositivo inédito, para um CPF com conta de 3 dias que recebeu de 6 pagadores diferentes nas últimas 24h, primeiro Pix para ele:

| Regra | Pontos |
|---|---|
| `night_over_limit` | +2 |
| `destination_type_amount` (limite aprendido para CPFs ≈ R$ 1.070, piso R$ 1.000) | +3 |
| `amount_vs_median` (limite aprendido ≈ R$ 1.070) | +2 |
| `new_device` | +2 |
| `young_destination` (< 7 dias) | +3 |
| `new_payee` | +1 |
| `mule_fan_in` | +3 |
| `high_value_review` e `rolling_24h_total` (nível crítico) | exigem 2FA, 0 pontos |

Pontuação 16, acima de 8: **`rejected`**. As exigências de 2FA também dispararam, mas a rejeição por pontuação tem prioridade, porque há evidência forte de fraude além do valor.

**2FA forçado, com histórico.** R$ 8.000,00 às 15h de um CPF com 30 Pix nos últimos 90 dias (mediana R$ 400, escala ≈ R$ 222), para um destinatário CPF que ele já pagou antes, dispositivo habitual:

| Regra | Resultado |
|---|---|
| `destination_type_amount` | R$ 8.000 acima do limite aprendido (≈ R$ 1.070): +3 |
| `amount_vs_median` | R$ 8.000 acima do limite aprendido (≈ R$ 1.070): +2 |
| `rolling_24h_total` | total de R$ 8.000 acima do alerta (piso R$ 2.000), abaixo do crítico (piso R$ 10.000): +2 |
| `high_value_review` | R$ 8.000 acima do limite aprendido de ≈ R$ 1.730 e do piso de R$ 5.000 (destinatário CPF): **exige 2FA** |

Pontuação 7, abaixo de 8, sem bloqueio: **`two_factor_required`**. Mesmo que os outros sinais não existissem, `high_value_review` sozinho já exigiria o 2FA.

**O mesmo valor, outro pagador.** R$ 8.000,00 de um CNPJ com Pix típicos de R$ 6.000 (escala ≈ R$ 2.970) para um fornecedor CNPJ que ele já paga: os limites aprendidos ficam em torno de R$ 14.900 (alerta de valor) e R$ 23.800 (crítico), então nada dispara. Pontuação 0: **`approved`**. O Pix que travaria o pagador do exemplo anterior é rotina para este.

**Sem histórico, teto fixo.** R$ 35.000,00 de um CPF sem histórico para outro CPF: `high_value_review` usa o teto fixo de R$ 30.000 para destinatário CPF e exige **2FA**. O mesmo valor, de um CNPJ sem histórico para um CNPJ, fica abaixo do teto fixo de R$ 100.000 e só soma o `new_payee` (+1): **`approved`**.

### O que vai no `metadata`

Todo Pix analisado devolve, junto do `status`, o porquê. Cada regra que disparou diz de onde veio o limite: `basis` vale `"history"` (aprendido) ou `"fixed"` (valor fixo). Exemplo, para o Pix do exemplo do desafio:

```json
{
  "key": "b3f1c2e0-7d4a-4c1e-9a52-1f0e6c9d2a77",
  "status": "two_factor_required",
  "metadata": {
    "engine_version": "1",
    "score": 5,
    "thresholds": { "two_factor": 3, "reject": 8, "warn_z": 3.0, "critical_z": 6.0 },
    "rules_triggered": [
      { "rule": "night_over_limit",  "points": 2, "block": false,
        "reason": "Pix de R$ 1.500,00 às 22:15, acima do limite noturno de R$ 1.000,00 (20h às 6h)." },
      { "rule": "young_destination", "points": 2, "block": false,
        "reason": "Conta de destino aberta há 7 dias (menos de 30) e valor de R$ 1.500,00." },
      { "rule": "new_payee",         "points": 1, "block": false,
        "reason": "Primeiro Pix deste pagador para este destinatário, valor de R$ 1.500,00." }
    ],
    "rules_skipped": [
      { "rule": "amount_vs_median",  "reason": "histórico insuficiente (0 de 5 Pix necessários)" },
      { "rule": "new_device",        "reason": "histórico insuficiente (0 de 3 Pix necessários)" },
      { "rule": "impossible_travel", "reason": "nenhum Pix anterior com geolocalização" }
    ]
  }
}
```

Regras que rodaram e não dispararam não aparecem. Cada `reason` traz os valores reais do Pix, para que quem lê a decisão não precise abrir o código.

Quando uma regra exige 2FA (`high_value_review` ou nível crítico de `rolling_24h_total`), a entrada dela em `rules_triggered` traz `requires_2fa: true`. Exemplo (o caso "2FA forçado, com histórico"):

```json
{
  "key": "5c0e9a14-3b7d-4f26-8d1e-72a4b6c8e9f0",
  "status": "two_factor_required",
  "metadata": {
    "engine_version": "1",
    "score": 7,
    "thresholds": { "two_factor": 3, "reject": 8, "warn_z": 3.0, "critical_z": 6.0 },
    "rules_triggered": [
      { "rule": "high_value_review", "points": 0, "block": false, "requires_2fa": true, "basis": "history",
        "reason": "Pix de R$ 8.000,00 acima do limite aprendido de R$ 5.000,00 (mediana R$ 400,00 + 6 × escala; piso de R$ 5.000,00 para destinatário CPF)." },
      { "rule": "destination_type_amount", "points": 3, "block": false, "basis": "history",
        "reason": "Pix de R$ 8.000,00 acima do limite aprendido de R$ 1.070,00 para Pix a pessoas físicas." },
      { "rule": "amount_vs_median", "points": 2, "block": false, "basis": "history",
        "reason": "Pix de R$ 8.000,00 acima do limite aprendido de R$ 1.070,00 (mediana R$ 400,00 + 3 × escala)." },
      { "rule": "rolling_24h_total", "points": 2, "block": false, "basis": "history",
        "reason": "Total de R$ 8.000,00 em 24h acima do alerta de R$ 2.000,00 para pagador CPF." }
    ],
    "rules_skipped": []
  }
}
```

- `requires_2fa: true` significa que a regra pediu 2FA por conta própria, independentemente da pontuação. Se nenhuma regra traz esse campo e o status é `two_factor_required`, o 2FA veio da pontuação (≥ 3).

---

## Como rodar e testar

### O que precisa estar instalado

Docker (com `docker compose version` funcionando), Git e Python 3.11 ou mais novo. O Python só é usado para rodar os testes: a API e o banco rodam no Docker.

### Subir a API

```bash
git clone https://github.com/tucarthur/bootcamp_qitech.git
cd bootcamp_qitech
docker compose up
```

Quando aparecer `Application startup complete`, a API está em <http://localhost:3000>. Não precisa criar nenhum arquivo antes: os valores padrão estão no `docker-compose.yml`.

Mudou o `database/database.sql`? Esse arquivo só roda quando o banco nasce, então recrie o banco:

```bash
docker compose down -v
docker compose up
```

### Mandar um Pix

Todas as rotas (menos `/` e `/health_check`) exigem o cabeçalho `INTERNAL-TOKEN`. O valor padrão é `default_token`.

```bash
curl -i -X POST http://localhost:3000/pix/transaction \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "pix-000123",
    "amount": 150000,
    "transaction_date": "2026-10-17T22:15:00-03:00",
    "source_account": {
      "branch": "0001",
      "account_number": "88213",
      "opening_date": "2025-03-02T10:00:00-03:00",
      "owner": { "document_number": "123.456.789-09" }
    },
    "destination_account": {
      "participant": "60701190",
      "branch": "3675",
      "account_number": "10442",
      "opening_date": "2026-10-10T09:00:00-03:00",
      "owner": { "document_number": "987.654.321-00" }
    },
    "source": {
      "device_id": "dvc-9f2c71a8",
      "channel": "app",
      "ip": "198.51.100.23",
      "geolocation": { "latitude": -23.56, "longitude": -46.65 }
    }
  }'
```

Com o banco vazio, a resposta é `201` com `status: "two_factor_required"` e o `metadata` do exemplo acima (a `key` muda a cada análise).

### Consultar a análise

```bash
curl http://localhost:3000/pix/transaction/pix-000123 \
  -H "INTERNAL-TOKEN: default_token"
```

A rota aceita o `id` do Pix. Se o valor tiver o formato de UUID e nenhum Pix tiver esse `id`, ela procura pela `key` da análise.

### O que a API responde

| Situação | Resposta |
|---|---|
| Pix novo analisado | `201` com `key`, `status` e `metadata` |
| Mesmo `id` enviado de novo | `200` com a análise já gravada (mesma `key`). Nada é reanalisado nem duplicado. |
| JSON fora do formato (campo faltando, tipo errado, valor ≤ 0, campo desconhecido) | `400`, código `QIT000001` |
| Data sem fuso ou que não existe no calendário | `422`, código `QIT001009` |
| Pix não encontrado no `GET` | `404`, código `QIT001008` |
| Sem o `INTERNAL-TOKEN` | `403`, código `QIT000002` |

O reenvio do mesmo `id` devolve a análise original de propósito: é seguro repetir um pedido que deu timeout, e o cliente nunca é analisado duas vezes pelo mesmo Pix.

### Rodar os testes

Uma vez só, para instalar as dependências de teste:

```bash
python3 -m venv .venv
source .venv/bin/activate        # no Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

Com a API de pé em outro terminal:

```bash
pytest
```

Os testes falam com a API por HTTP, como um cliente de verdade, e ficam em `tests/integration/pix_transaction/`. Cada regra tem testes de dois tipos: um cenário em que dispara e um em que não dispara. Os cenários de histórico são montados mandando Pix de verdade pela API, usando `transaction_date` controlado para que o resultado nunca dependa do relógio. Cada regra que aprende tem, além disso, um cenário **sem histórico** (limite fixo) e um **com histórico** (limite aprendido).

| Cenário | Resultado esperado |
|---|---|
| Pix do exemplo do desafio, banco vazio | `two_factor_required` (pontuação 5) |
| R$ 150,00 de dia, destinatário conhecido | `approved` |
| R$ 35.000 de um CPF sem histórico para um CPF | `two_factor_required` (`high_value_review`, teto fixo de R$ 30.000) |
| R$ 35.000 de um CNPJ sem histórico para um CNPJ, de dia | `approved` (pontuação 1: só `new_payee`; abaixo do teto fixo de R$ 100.000) |
| CPF com 6 Pix de cerca de R$ 100 envia R$ 6.000 | `two_factor_required` (`high_value_review`, limite aprendido, acima do piso de R$ 5.000) |
| CNPJ com Pix típicos de R$ 6.000 (variação de cerca de R$ 2.000) envia R$ 8.000 a um fornecedor conhecido | `approved` (limites aprendidos acima de R$ 8.000) |
| CPF com histórico envia R$ 3.000, sendo que costuma enviar cerca de R$ 100, com piso de `high_value_review` em R$ 5.000 | `high_value_review` não dispara (abaixo do piso); `amount_vs_median` e `destination_type_amount` somam pontos |
| 10 Pix do mesmo CPF em 10 minutos, sem histórico | o décimo é `rejected` (`burst`, limite fixo de bloqueio 10) |
| 5 Pix do mesmo CPF em 10 minutos, sem histórico | o quinto sobe para `two_factor_required` (`burst`, +3, limite fixo 5) |
| 20 Pix de um CNPJ em 10 minutos, sem histórico | o vigésimo dispara `burst` (+3); o quadragésimo é `rejected` |
| CNPJ com pico histórico de 30 Pix em 10 minutos envia 45 | `burst` não dispara (limite aprendido de alerta 60); o mesmo CNPJ sem histórico dispararia |
| R$ 1.200 às 21h para destinatário conhecido | `approved` (só `night_over_limit`, +2) |
| R$ 1.200 às 21h para destinatário novo | `two_factor_required` (+2 e +1) |
| 4 Pix de R$ 500 em 20 minutos ao mesmo CPF, sem Pix anteriores a ele | `payee_burst` dispara (+2) |
| Mesmo cenário, mas o pagador já tinha pago esse CPF semanas antes | `payee_burst` não dispara |
| 4 Pix de R$ 50 em 20 minutos ao mesmo CPF (soma R$ 200) | `payee_burst` não dispara (abaixo de R$ 1.000 somados) |
| 6 pagadores diferentes para o mesmo CPF em 24h | `two_factor_required` por `mule_fan_in` |
| 6 pagadores diferentes para o mesmo CNPJ em 24h | `mule_fan_in` não dispara (empresa) |
| Pagador e destinatário com o mesmo documento, conta de destino nova | `young_destination` e `payee_burst` puladas |
| Dois Pix geolocalizados a 400 km de distância com 30 min de diferença | `impossible_travel` dispara (+3) |
| Mesmo `id` enviado duas vezes | `201` e depois `200`, mesma `key`, uma linha no banco |
| `GET` com um `id` que não existe | `404` com `QIT001008` |
| Sem `INTERNAL-TOKEN` | `403` |
| Campo obrigatório faltando | `400` |
| Data sem fuso | `422` |

### Se algo der errado

- `port is already allocated`: outra coisa está usando a porta 3000 ou 5432. Copie `.env.example` para `.env` e troque `API_PORT` e `DB_PORT` (mudou `DB_PORT`? Troque também a porta na `DATABASE_URL`).
- `failed to connect to the docker API`: o Docker não está ligado. Abra o Docker Desktop e espere ficar verde.
- `relation "..." does not exist`: você mexeu no `database.sql`. Rode `docker compose down -v` e suba de novo.
- Ver o que a API está fazendo: `docker compose logs -f api`.
