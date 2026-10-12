from models.customers import Customers


class CustomersDTO:
    @staticmethod
    def only_customer_key(customer: Customers) -> dict:
        dto = dict()
        dto["customer_key"] = customer.customer_key
        
        return dto