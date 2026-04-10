import os
import json
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

NEO4J_URI  = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "password")


def run_query(session, title, cypher, params=None):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    result = session.run(cypher, **(params or {}))
    rows   = [dict(r) for r in result]
    for r in rows[:15]:
        print(r)
    return {"title": title, "rows": rows[:15]}


def main():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    output = []

    with driver.session() as s:

        #  Query 1  Most connected users 
        output.append(run_query(s, "Q1 · Most Connected Users (asked + answered)", """
            MATCH (u:User)
            OPTIONAL MATCH (u)-[:ASKED]->(q:Question)
            WITH u, count(DISTINCT q) AS asked
            OPTIONAL MATCH (u)-[:ANSWERED]->(q2:Question)
            WITH u, asked, count(DISTINCT q2) AS answered
            WITH u, asked, answered, (asked + answered) AS total_activity
            WHERE total_activity > 0
            RETURN u.id            AS user_id,
                   asked           AS questions_asked,
                   answered        AS questions_answered,
                   total_activity
            ORDER BY total_activity DESC
            LIMIT 20
        """))

        #  Query 2  Tag co-occurrence (most related tech pairs) 
        output.append(run_query(s, "Q2 · Top Tag Co-Occurrences (technology pairs)", """
            MATCH (t1:Tag)-[r:CO_OCCURS_WITH]-(t2:Tag)
            WHERE id(t1) < id(t2)
            RETURN t1.name  AS tag_a,
                   t2.name  AS tag_b,
                   r.weight AS shared_questions
            ORDER BY shared_questions DESC
            LIMIT 25
        """))

        #  Query 3  Top experts per tag (Aura‑compatible version) 
        output.append(run_query(s, "Q3 · Top Experts per Tag (by total answer score)", """
            MATCH (u:User)-[:ANSWERED]->(q:Question)-[:TAGGED]->(t:Tag)
            MATCH (u)-[:PROVIDED]->(a:Answer)-[:ANSWERS]->(q)
            WITH t.name AS tag, u.id AS user_id,
                 sum(a.score) AS total_score,
                 count(a) AS answer_count
            WHERE answer_count >= 3
            ORDER BY tag, total_score DESC

            WITH tag, collect({
                user_id: user_id,
                total_score: total_score,
                answer_count: answer_count
            }) AS ranked

            UNWIND range(0, size(ranked)-1) AS idx
            WITH tag, idx+1 AS rk, ranked[idx] AS entry
            WHERE rk <= 3

            RETURN tag,
                   entry.user_id AS user_id,
                   entry.total_score AS total_score,
                   entry.answer_count AS answer_count,
                   rk AS rank
            ORDER BY tag, rank
            LIMIT 40
        """))

        #  Query 4  Shortest path between two users 
        output.append(run_query(s, "Q4 · Shortest Knowledge Path Between Two Users", """
            MATCH (u1:User), (u2:User)
            WHERE u1.id <> u2.id
            WITH u1, u2
            LIMIT 1
            MATCH path = shortestPath(
                (u1)-[:ASKED|ANSWERED*..6]-(u2)
            )
            RETURN u1.id          AS from_user,
                   u2.id          AS to_user,
                   length(path)   AS hops,
                   [n IN nodes(path) WHERE n:Question | n.id] AS shared_questions
            LIMIT 5
        """))

        #  Bonus  -Tag diversity per top user 
        output.append(run_query(s, "BONUS · Technology Breadth per Expert User", """
            MATCH (u:User)-[:ANSWERED]->(q:Question)-[:TAGGED]->(t:Tag)
            WITH u.id AS user_id,
                 count(DISTINCT t.name) AS unique_tags,
                 count(DISTINCT q)      AS questions_answered,
                 collect(DISTINCT t.name)[0..5] AS sample_tags
            WHERE questions_answered >= 5
            RETURN user_id, unique_tags, questions_answered, sample_tags
            ORDER BY unique_tags DESC
            LIMIT 20
        """))

    #  Save results 
    with open("neo4j_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)

    print("\nResults saved to neo4j_results.json")
    driver.close()


if __name__ == "__main__":
    main()
