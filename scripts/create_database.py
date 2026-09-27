from backend.database.connection import engine
from backend.database.models import Base


def create_database():
    Base.metadata.create_all(bind=engine)

    print("======================================")
    print("DATABASE CREATED")
    print("======================================")
    print("Database: data/healthcare.db")
    print("")


if __name__ == "__main__":
    create_database()