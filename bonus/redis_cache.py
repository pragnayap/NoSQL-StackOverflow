import os
import json
import time
import redis
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI  = os.getenv("MONGO_URI")
MONGO_DB   = os.getenv("MONGO_DB",   "stackoverflow")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
CACHE_TTL  = 3600   # seconds
SEP        = "─" * 52


# MongoDB helpers

def fetch_top_tags(col, n=20):
    """Aggregation: top N tags by question count."""
    pipeline = [
        {"$unwind": "$tags"},
        {"$group":  {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort":   {"count": -1}},
        {"$limit":  n},
    ]
    return [{"tag": r["_id"], "count": r["count"]}
            for r in col.aggregate(pipeline, allowDiskUse=True)]


def fetch_top_users(col, n=20):
    """Aggregation: top N users by questions asked."""
    pipeline = [
        {"$match":  {"owner_user_id": {"$ne": None}}},
        {"$group":  {
            "_id":       "$owner_user_id",
            "questions": {"$sum": 1},
            "score":     {"$sum": "$score"},
        }},
        {"$sort":   {"questions": -1}},
        {"$limit":  n},
    ]
    return [{"user_id": r["_id"], "questions": r["questions"], "score": r["score"]}
            for r in col.aggregate(pipeline, allowDiskUse=True)]


# Redis operations

def cache_top_tags(r, tags):
    """Store as JSON string with TTL + as a Hash for field-level access."""
    r.setex("top_tags", CACHE_TTL, json.dumps(tags))
    # also as Hash: tag_name → count
    r.hset("tag_counts", mapping={item["tag"]: item["count"] for item in tags})
    print(f"  [SET]  top_tags      → {len(tags)} tags   (TTL={CACHE_TTL}s)")
    print(f"  [HSET] tag_counts    → {r.hlen('tag_counts')} fields")


def cache_top_users(r, users):
    """Store as JSON string + as a Sorted Set leaderboard."""
    r.setex("top_users", CACHE_TTL, json.dumps(users))
    for u in users:
        r.zadd("user_leaderboard", {str(u["user_id"]): u["questions"]})
    print(f"  [SET]  top_users     → {len(users)} users  (TTL={CACHE_TTL}s)")
    print(f"  [ZADD] user_leaderboard → {r.zcard('user_leaderboard')} members")


def show_leaderboard(r, top_n=5):
    """Print top N from the sorted-set leaderboard."""
    print(f"\n{SEP}")
    print(f"  User Leaderboard  (top {top_n})")
    print(SEP)
    for uid, score in r.zrevrange("user_leaderboard", 0, top_n - 1, withscores=True):
        print(f"  User {uid:<12}  {int(score):>5} questions asked")


def show_cache_hit_speed(r):
    """Demonstrate the latency difference."""
    print(f"\n{SEP}")
    print("  Cache hit speed demo")
    print(SEP)

    # simulate slow MongoDB aggregation
    t0 = time.perf_counter()
    time.sleep(0.08)                       
    slow_ms = (time.perf_counter() - t0) * 1000

    # real Redis GET
    t0 = time.perf_counter()
    raw = r.get("top_tags")
    fast_ms = (time.perf_counter() - t0) * 1000

    print(f"  Simulated MongoDB latency : {slow_ms:6.1f} ms")
    print(f"  Redis GET latency         : {fast_ms:6.2f} ms")
    speedup = slow_ms / max(fast_ms, 0.01)
    print(f"  Speed-up factor           : {speedup:6.0f}×")

    if raw:
        tags = json.loads(raw)
        print(f"\n  Cached top 5 tags:")
        for t in tags[:5]:
            print(f"    #{t['tag']:<25}  {t['count']:>6,} questions")


def show_all_keys(r):
    print(f"\n{SEP}")
    print("  All Redis keys")
    print(SEP)
    for key in sorted(r.keys("*")):
        ktype = r.type(key)
        ttl   = r.ttl(key)
        print(f"  {key:<25}  type={ktype:<8}  TTL={ttl}s")


# main

def main():
    # Connect MongoDB
    mongo_client = MongoClient(MONGO_URI)
    col          = mongo_client[MONGO_DB]["questions"]

    # Connect Redis
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    try:
        r.ping()
    except redis.ConnectionError:

        try:
            r = redis.Redis(host="redis", port=REDIS_PORT, decode_responses=True)
            r.ping()
        except redis.ConnectionError:
            print(f"[Redis] Cannot connect to {REDIS_HOST}:{REDIS_PORT} or redis:{REDIS_PORT}")
            print("  Make sure Redis is running:  docker compose up -d redis")
            return

    print(f"[Redis] Connected to {REDIS_HOST}:{REDIS_PORT}\n")

    # Fetch from MongoDB and cache in Redis
    print("[Redis] Fetching top tags from MongoDB …")
    tags  = fetch_top_tags(col)
    print("[Redis] Fetching top users from MongoDB …")
    users = fetch_top_users(col)

    print(f"\n{SEP}")
    print("  Caching results into Redis")
    print(SEP)
    cache_top_tags(r, tags)
    cache_top_users(r, users)

    show_leaderboard(r)
    show_cache_hit_speed(r)
    show_all_keys(r)

    mongo_client.close()
    print(f"\n{'='*52}")
    print("Redis demo complete.")
    print(f"{'='*52}")


if __name__ == "__main__":
    main()
