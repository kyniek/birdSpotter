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


def mail_test():
    import imaplib
    import email
    from email.header import decode_header
    # Konfiguracja
    IMAP_HOST = "imap.gmail.com"
    EMAIL = "k.p.nielepkowicz@gmail.com"
    PASSWORD = "hnob bhxo jtop diqp"  # App Password z Google
    # Połączenie
    mail = imaplib.IMAP4_SSL(IMAP_HOST)
    mail.login(EMAIL, PASSWORD)
    # Otwórz skrzynkę odbiorczą
    mail.select("INBOX")
    # Pobierz identyfikatory wszystkich wiadomości
    status, messages = mail.search(None, "ALL")
    if status != "OK":
        raise Exception("Nie udało się pobrać wiadomości")
    message_ids = messages[0].split()
    # Ostatnie 10 wiadomości
    last_10 = message_ids[-10:]
    print("\nOstatnie 10 wiadomości:\n")
    for msg_id in reversed(last_10):
        status, msg_data = mail.fetch(msg_id, "(RFC822)")

        if status != "OK":
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = msg.get("Subject", "(brak tematu)")

        # Dekodowanie polskich znaków i innych kodowań
        decoded_parts = decode_header(subject)
        decoded_subject = ""

        for text, encoding in decoded_parts:
            if isinstance(text, bytes):
                decoded_subject += text.decode(encoding or "utf-8", errors="replace")
            else:
                decoded_subject += text

        print(decoded_subject)
    mail.logout()


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    print('Birt Spotter')

    neo4J_test()

    import redis

    redis_test()

    mail_test()
