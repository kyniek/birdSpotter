# This is a sample Python script.

# Press ⌃R to execute it or replace it with your code.
# Press Double ⇧ to search everywhere for classes, files, tool windows, actions, and settings.
def neo4J_test():
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(
        "bolt://localhost:7687",
        auth=("neo4j", "Qwerty1234")
    )
    with driver.session() as session:
        result = session.run(
            "CALL dbms.components() "
            "YIELD name, versions "
            "RETURN name, versions[0] AS version"
        )

        for row in result:
            print(f"{row['name']} {row['version']}")
    driver.close()


def redis_test():
    try:
        # Połączenie z Redis
        r = redis.Redis(
            host="localhost",
            port=6379,
            decode_responses=True
        )

        # Test połączenia
        response = r.ping()
        print(f"PING -> {response}")

        # Zapis danych
        r.set("test_key", "Redis działa!")

        # Odczyt danych
        value = r.get("test_key")
        print(f"test_key -> {value}")

        print("✅ Redis działa poprawnie.")

    except Exception as e:
        print(f"❌ Błąd połączenia: {e}")


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    print('Birt Spotter')

    neo4J_test()

    import redis

    redis_test()
