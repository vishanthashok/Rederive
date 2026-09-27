"""Redis sorted-set job queue. Lower depth pops first, then lower job id.

Postgres holds the job state. Redis only orders the work, so a lost Redis
entry is recovered by the worker's periodic sweep.
"""

import redis

KEY = "rederive:jobs"
DEPTH_SCALE = 1_000_000_000


class RedisQueue:
    def __init__(self, url: str):
        self.redis = redis.Redis.from_url(url)

    def push(self, jobs: list[tuple[int, int]]) -> None:
        if jobs:
            self.redis.zadd(KEY, {str(job_id): depth * DEPTH_SCALE + job_id for job_id, depth in jobs})

    def pop(self, timeout: float = 1.0) -> tuple[int, int] | None:
        item = self.redis.bzpopmin(KEY, timeout=timeout)
        if item is None:
            return None
        _, member, score = item
        job_id = int(member)
        return job_id, int(score) // DEPTH_SCALE

    def size(self) -> int:
        return self.redis.zcard(KEY)

    def clear(self) -> None:
        self.redis.delete(KEY)
