// ============================================================
// analytics/cypher_queries.cypher
// Copy-paste into Neo4j Browser or Aura query editor
// so_analytics — Stack Overflow Knowledge Intelligence
// ============================================================


// ── SETUP ─────────────────────────────────────────────────────────────────────

CREATE CONSTRAINT user_id_unique     IF NOT EXISTS FOR (u:User)     REQUIRE u.id IS UNIQUE;
CREATE CONSTRAINT question_id_unique IF NOT EXISTS FOR (q:Question) REQUIRE q.id IS UNIQUE;
CREATE CONSTRAINT answer_id_unique   IF NOT EXISTS FOR (a:Answer)   REQUIRE a.id IS UNIQUE;
CREATE CONSTRAINT tag_name_unique    IF NOT EXISTS FOR (t:Tag)       REQUIRE t.name IS UNIQUE;

CREATE INDEX question_score IF NOT EXISTS FOR (q:Question) ON (q.score);
CREATE INDEX question_date  IF NOT EXISTS FOR (q:Question) ON (q.creation_date);


// ── Q1: Most Connected Users ──────────────────────────────────────────────────

MATCH (u:User)
OPTIONAL MATCH (u)-[:ASKED]->(q:Question)
WITH u, count(DISTINCT q) AS asked
OPTIONAL MATCH (u)-[:ANSWERED]->(q2:Question)
WITH u, asked, count(DISTINCT q2) AS answered
WITH u, asked, answered, (asked + answered) AS total
WHERE total > 0
RETURN u.id     AS user_id,
       asked    AS questions_asked,
       answered AS questions_answered,
       total    AS total_activity
ORDER BY total DESC
LIMIT 20;


// ── Q2: Tag Co-Occurrence Network ─────────────────────────────────────────────

MATCH (t1:Tag)-[r:CO_OCCURS_WITH]-(t2:Tag)
WHERE id(t1) < id(t2)
RETURN t1.name  AS tag_a,
       t2.name  AS tag_b,
       r.weight AS shared_questions
ORDER BY shared_questions DESC
LIMIT 25;

// Rebuild co-occurrence edges (run once if missing):
MATCH (t1:Tag)<-[:TAGGED]-(q:Question)-[:TAGGED]->(t2:Tag)
WHERE id(t1) < id(t2)
WITH t1, t2, count(q) AS w
WHERE w >= 5
MERGE (t1)-[r:CO_OCCURS_WITH]-(t2)
SET   r.weight = w;


// ── Q3: Top Experts per Tag ───────────────────────────────────────────────────

MATCH (u:User)-[:PROVIDED]->(a:Answer)-[:ANSWERS]->(q:Question)-[:TAGGED]->(t:Tag)
WITH t.name      AS tag,
     u.id        AS user_id,
     sum(a.score)AS total_score,
     count(a)    AS answers_given
WHERE answers_given >= 3
RETURN tag, user_id, total_score, answers_given
ORDER BY total_score DESC
LIMIT 30;


// ── Q4: Shortest Path Between Two Users ──────────────────────────────────────
// Replace IDs with real user IDs from your dataset.

MATCH (u1:User {id: 22656}), (u2:User {id: 29407})
MATCH path = shortestPath(
    (u1)-[:ASKED|ANSWERED*..8]-(u2)
)
RETURN u1.id        AS from_user,
       u2.id        AS to_user,
       length(path) AS hops,
       [n IN nodes(path) |
           CASE
               WHEN n:User     THEN 'User:'  + toString(n.id)
               WHEN n:Question THEN 'Q:'     + toString(n.id)
               ELSE 'other'
           END
       ] AS path_nodes;


// ── BONUS: Versatile Developers ───────────────────────────────────────────────

MATCH (u:User)-[:ANSWERED]->(q:Question)-[:TAGGED]->(t:Tag)
WITH u.id                          AS user_id,
     count(DISTINCT t.name)         AS unique_tags,
     count(DISTINCT q)              AS questions_answered,
     collect(DISTINCT t.name)[0..5] AS sample_tags
WHERE questions_answered >= 5
RETURN user_id, unique_tags, questions_answered, sample_tags
ORDER BY unique_tags DESC
LIMIT 20;


// ── BONUS: Degree Centrality on Tags ─────────────────────────────────────────

CALL gds.graph.project('tagDeg', 'Tag', {CO_OCCURS_WITH:{orientation:'UNDIRECTED'}});
CALL gds.degree.stream('tagDeg')
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).name AS tag, toInteger(score) AS degree
ORDER BY degree DESC LIMIT 20;
CALL gds.graph.drop('tagDeg');
