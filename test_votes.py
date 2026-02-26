import mysql.connector

conn = mysql.connector.connect(
    host='localhost',
    user='root',
    password='',
    database='voting_db',
    port=3306
)

cursor = conn.cursor(dictionary=True)

# Check candidates
print('=== CANDIDATES ===')
cursor.execute('SELECT id, c_name, c_party FROM candidates')
candidates = cursor.fetchall()
for c in candidates:
    print(f"ID: {c['id']}, Name: {c['c_name']}, Party: {c['c_party']}")

# Check votes
print('\n=== VOTES ===')
cursor.execute('SELECT voter_id, candidate_id FROM votes')
votes = cursor.fetchall()
print(f'Total votes: {len(votes)}')
for v in votes:
    print(f"Voter: {v['voter_id']}, Candidate: {v['candidate_id']}")

# Check vote count per candidate
print('\n=== VOTE COUNT PER CANDIDATE ===')
cursor.execute('''
    SELECT c.id, c.c_name, COUNT(v.voter_id) as votes
    FROM candidates c
    LEFT JOIN votes v ON c.id = v.candidate_id
    GROUP BY c.id, c.c_name
''')
results = cursor.fetchall()
for r in results:
    print(f"Candidate ID {r['id']}: {r['c_name']} = {r['votes']} votes")

cursor.close()
conn.close()
