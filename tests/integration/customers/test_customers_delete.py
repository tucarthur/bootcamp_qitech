from uuid import uuid4

from tests.utils import RandomGenerator, RequestGenerator


class TestCustomersGet:
	def test_get_created_customer_by_key(self):
		payload = {
			"name": "Maria da Silva",
			"email": f"maria.silva.{uuid4()}@exemplo.com.br",
			"document_number": RandomGenerator.generate_cpf(),
			"birthdate": "1990-05-17",
		}

		status, response = RequestGenerator.POST_customer(payload)
		assert status == 201
		customer_key = response["customer_key"]

		status, response = RequestGenerator.GET_customer(customer_key)
		assert status == 200
		assert response["customer_key"] == customer_key
