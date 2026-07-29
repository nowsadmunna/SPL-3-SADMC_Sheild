import Redis from "ioredis";
import "dotenv/config";

const REDIS_URL = process.env.REDIS_URL || "redis://localhost:6380";

export const redis = new Redis(REDIS_URL, { lazyConnect: false });
redis.on("error", (err) => console.error("[redis] error:", err.message));

// Separate connection for pub/sub subscriptions (ioredis requires a
// dedicated connection once .subscribe()/.psubscribe() is used).
export const redisSub = new Redis(REDIS_URL, { lazyConnect: false });
redisSub.on("error", (err) => console.error("[redis-sub] error:", err.message));
