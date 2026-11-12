# QuickPizza performance results

Short version: on my laptop QuickPizza meets the SLA up to 75 concurrent users and falls over at 100. The weak spot is `POST /api/pizza` (get a recommendation), which calls back into its own server 9 times per request.

## Setup

- QuickPizza built from source, monolithic mode, in-memory SQLite, on `localhost:3333`
- JMeter 5.6.3 in non-GUI mode, JDK 25
- Windows 11 laptop with 4 logical CPUs. JMeter and QuickPizza run on the same machine.
- Think time: Gaussian, 500 ms ± 200 ms
- The `00` setUp registration requests are excluded from the numbers

### A note on the first runs

My first stress runs failed the SLA at only 10 users, and the numbers jumped around: recommendation p95 was 556 ms on one run and 1450 ms on the next, both on a fresh server. The CPU turned out to be at 100% before the test even started, because a browser with lots of tabs and VS Code were open.

With nothing else running, I timed a single client making sequential requests:

| Endpoint (1 client) | min | p50 | p90 | max |
|---|---:|---:|---:|---:|
| `POST /api/pizza` | 17 ms | 270 ms | 1011 ms | 4401 ms |
| `GET /api/doughs` | 1 ms | 3 ms | 46 ms | 64 ms |

The doughs endpoint barely noticed the busy CPU. The recommendation endpoint got hit much harder, because it waits for the CPU again on every one of its internal calls. That was the first hint about the bottleneck. It also meant results from a busy laptop weren't worth keeping, so I closed everything and ran the tests again.

The final runs below used a freshly started server with about 2.7 GB of RAM free. Windows services still kept the CPU around 50% at idle, so read the absolute numbers as approximate. The shape of the curve is the useful part.

## Stress test

The load goes up in 60-second steps. The cells are p95 latency, with the error rate in brackets when it wasn't zero.

| Users | 02 Recommendation | 03 Rate | 04 Ratings | 05 Doughs | req/s | SLA |
|---:|---:|---:|---:|---:|---:|:---:|
| 10 | 157 ms | 15 ms | 13 ms | 7 ms | 17 | pass |
| 20 | 159 ms | 16 ms | 14 ms | 6 ms | 33 | pass |
| 30 | 172 ms | 32 ms | 24 ms | 11 ms | 49 | pass |
| 40 | 183 ms (0.09%) | 42 ms | 29 ms | 19 ms | 64 | pass |
| 50 | 169 ms | 41 ms | 23 ms | 14 ms | 81 | pass |
| 75 | 159 ms | 31 ms | 18 ms | 11 ms | 124 | pass |
| 100 | 1983 ms (26%) | 2257 ms (1.7%) | 2273 ms (4.0%) | 662 ms (2.1%) | 56 | fail |

Up to 75 users, latency stays flat and throughput grows by about 1.65 req/s per user. At 100 users it doesn't slow down gradually. It collapses:

- Throughput drops from 124 to 56 req/s, even though there are a third more users.
- Recommendations fail the most, with 26% errors. The other endpoints only start failing because they're stuck in the same queue.
- Every endpoint has a max of around 17 to 18 seconds. Those requests sat waiting on internal calls until the HTTP client timed out.

So the limit is somewhere between 75 and 100 users. I didn't test between those two steps.

## Load test

20 users for 3 minutes, well under the limit:

| Request | Samples | Errors | p50 | p95 (budget) | p99 | req/s | SLA |
|---|---:|---:|---:|---:|---:|---:|:---:|
| 01 Login | 20 | 0% | 205 ms | 222 ms (800) | 241 ms | 0.7 | pass |
| 02 Get recommendation | 1780 | 0% | 131 ms | 264 ms (500) | 376 ms | 10.0 | pass |
| 03 Rate pizza | 1773 | 0% | 42 ms | 97 ms (300) | 138 ms | 9.9 | pass |
| 04 View my ratings | 531 | 0% | 12 ms | 50 ms (300) | 84 ms | 3.0 | pass |
| 05 Browse doughs | 1765 | 0% | 5 ms | 36 ms (300) | 60 ms | 9.9 | pass |

About 5,800 requests ran with no errors. Even at this level, a recommendation takes 26 times longer than a doughs request at the median (131 ms vs 5 ms).

## Why recommendations are slow

`AddRecommendations` in [`pkg/http/http.go`](https://github.com/grafana/quickpizza/blob/main/pkg/http/http.go) handles `POST /api/pizza`. For every request it makes these HTTP calls to its own server, one after another:

| # | Call | What for |
|---|---|---|
| 1-4 | `GET /api/ingredients/{olive_oil,tomato,mozzarella,topping}` | ingredients |
| 5 | `GET /api/tools` | tools |
| 6 | `GET /api/doughs` | doughs |
| 7 | `GET /api/adjectives` | pizza name |
| 8 | `GET /api/names` | pizza name |
| 9 | `POST /api/internal/recommendations` | save the result |

Calls 1 to 8 return the same static data every time, and none of it is cached. Each call also goes through the token check and a DB query, and waits in the same queues as real users. With 9 calls in a row, latency adds up. Once the server gets busy, it multiplies.

An earlier 50-user run on the busy laptop shows what happens when those calls time out. The server log had:

```
"msg":"Requesting ingredients", "err":"... net/http: request canceled (Client.Timeout exceeded while awaiting headers)"
"msg":"Storing recommendation in catalog", "err":"... context deadline exceeded (Client.Timeout exceeded while awaiting headers)"
"msg":"Failed to check token", "err":"context canceled"
```

In that run, `02 Get recommendation` returned 177 responses with status 500 and 98 with 401. The 401s are misleading, because the token was valid and only the token check timed out. Another 244 requests with status 400 on `03 Rate pizza` happened only because there was no pizza id to rate. I then added an If Controller to skip the rating in that case, so the error rate counts each failure once.

## Suggestions

1. Cache the static data (ingredients, tools, doughs, adjectives, names) in memory with a TTL. That removes 8 of the 9 calls.
2. Run whatever calls are left in parallel (for example with `errgroup`), so the wait is the slowest call rather than the sum of all of them.
3. In monolithic mode, call the services as functions instead of going over HTTP to localhost.
4. Save the recommendation in the background, or at least don't fail the request if saving fails.
5. When an internal call times out, return 503 with `Retry-After`. Returning 401 makes clients log in again, which adds even more load.

Until then, one instance shouldn't be planned for more than about 75 concurrent users. Fixes 1 to 3 should push that limit up a lot, since each recommendation currently costs the server as much as 9 requests.
