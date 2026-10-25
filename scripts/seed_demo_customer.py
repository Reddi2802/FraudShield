from passlib.hash import bcrypt

from db.models import Account, Customer
from db.session import SessionLocal, init_db


def main():
    init_db()

    with SessionLocal() as session:
        email = "seed.customer.00001@example.invalid"
        customer = session.query(Customer).filter_by(email=email).first()

        if customer is None:
            customer = Customer(
                synthetic_uid="demo-customer-00001",
                name="Demo Customer",
                email=email,
                hashed_password=bcrypt.hash("ChangeMe123!"),
            )
            session.add(customer)
            session.flush()

        if not session.query(Account).filter_by(
            customer_id=customer.customer_id
        ).first():
            session.add(
                Account(
                    customer_id=customer.customer_id,
                    account_number="DEMO00001",
                    account_type="checking",
                )
            )

        session.commit()
        print("Demo customer ready.")


if __name__ == "__main__":
    main()
