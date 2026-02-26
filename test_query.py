import mysql.connector

conn = mysql.connector.connect(
    host='localhost',
    user='root',
    password='',
    database='voting_db',
    port=3306
)

cursor = conn.cursor(dictionary=True)

# Test the exact query from app.py
print('=== RUNNING VOTE RESULTS QUERY ===')
cursor.execute("""
    SELECT c.id, c.c_name, c.c_party, c.c_symbol, COUNT(v.voter_id) AS votes
    FROM candidates c
    LEFT JOIN votes v ON c.id = v.candidate_id
    GROUP BY c.id
    ORDER BY votes DESC, c.id ASC
""")
results = cursor.fetchall()

for r in results:
    print(f"ID: {r['id']}, Name: {r['c_name']}, Party: {r['c_party']}, Votes: {r['votes']}")

cursor.close()
conn.close()
