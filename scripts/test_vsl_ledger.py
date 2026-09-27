from governance.ledger import LEDGER_PATH, get_ledger


def main():
    print("\n======================================")
    print("VSL LEDGER TEST")
    print("======================================")

    ledger = get_ledger()

    print(f"Ledger type: {type(ledger).__name__}")
    print(f"Ledger path: {LEDGER_PATH}")
    print(f"Ledger exists: {LEDGER_PATH.exists()}")

    print("\nLedger initialization: SUCCESS")


if __name__ == "__main__":
    main()