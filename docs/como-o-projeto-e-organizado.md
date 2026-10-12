# Organização do projeto

A API separa transporte HTTP, regras de negócio e persistência. Uma requisição passa pelas camadas abaixo:

```text
Cliente HTTP
  -> middleware
  -> resource
  -> controller
  -> repository
  -> model / PostgreSQL
```

## Inicialização e requisições

[src/app.py](../src/app.py) configura o FastAPI, registra os middlewares e associa cada rota ao seu resource. O middleware de token protege as rotas internas; o middleware de sessão disponibiliza uma sessão SQLAlchemy durante a requisição e garante seu encerramento.

Os resources em `src/resources/` validam os dados de entrada com os contratos de `src/schemas/`, chamam um controller e definem o status HTTP. Eles não devem conter regras de negócio nem consultas ao banco.

Os controllers em `src/controllers/` coordenam as regras do domínio. Por exemplo, o cadastro de cliente valida CPF, idade, e-mail e duplicidade antes de solicitar a persistência. O controller confirma a transação depois de uma operação bem-sucedida.

Os repositories em `src/repositories/` concentram as consultas SQLAlchemy. Os models em `src/models/` mapeiam as tabelas PostgreSQL e os DTOs em `src/dtos/` escolhem quais dados são devolvidos ao cliente.

## Domínios

- `customers`: cadastro, consulta e exclusão de clientes.
- `accounts`: abertura e consulta de contas, depósitos, saques e extratos.
- `transactions`: transferências, idempotência e lançamentos associados.

Valores monetários são armazenados em centavos. A transferência e seus lançamentos são persistidos como uma unidade; o extrato consulta os lançamentos da conta. A tarifa é configurada por `TRANSFER_FEE_CENTS`.

## Contratos e persistência

Cada arquivo JSON em `src/schemas/` descreve o formato aceito por uma rota. `src/utils/schema_handler.py` aplica esses contratos antes da execução do método do resource. Regras que dependem de estado ou de vários campos continuam sob responsabilidade do controller.

`src/database.py` configura a conexão e o contexto da sessão. `database/database.sql` define as tabelas, chaves estrangeiras, restrições e índices usados pelos models. O serviço `db` do Docker Compose aplica esse arquivo quando o banco é criado.

## Testes

Os testes de integração ficam em `tests/integration/`, organizados por domínio. `tests/conftest.py` configura o cliente de teste e as fixtures compartilhadas; `tests/utils/` contém os geradores e adaptadores HTTP usados pelos cenários.

Execute a suíte com a API e o banco iniciados:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```
