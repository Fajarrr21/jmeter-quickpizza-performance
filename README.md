# jmeter-quickpizza-performance

![Performance Smoke](https://github.com/Fajarrr21/jmeter-quickpizza-performance/actions/workflows/performance.yml/badge.svg)

JMeter performance tests for [QuickPizza](https://github.com/grafana/quickpizza), a small demo app from Grafana built for practicing load testing. The project has one test plan that runs in five load profiles, plus a Python script that checks the results against an SLA and fails CI on a breach.

The results and my analysis are in [RESULTS.md](RESULTS.md). In short, the SLA holds up to 75 concurrent users and breaks at 100. The cause is the recommendation endpoint, which makes 9 sequential HTTP calls back into its own server for every request.

QuickPizza runs locally for these tests. Don't point a load test at a server you don't own.

## The scenario

Each virtual user:

1. Logs in once and keeps the token
2. Asks for a pizza recommendation and saves the `pizza_id` from the response
3. Rates that pizza, but only if step 2 actually returned one
4. Views their ratings, in about 30% of iterations
5. Browses the dough list

Before every request there's a random think time of 500 ms ± 200 ms. A setUp thread group first registers all 200 users from `data/users.csv`. If a user already exists from an earlier run, the 400 response is accepted.

Everything that changes between runs (host, port, users, ramp-up, duration, think time) is a JMeter property, so the same `.jmx` file covers every profile.

## SLA

| Request | p95 limit |
|---|---|
| 01 Login | 800 ms (password hashing makes it slower on purpose) |
| 02 Get recommendation | 500 ms |
| everything else | 300 ms |

On top of that, each request must have an error rate under 1%. `scripts/sla_check.py` reads the `.jtl` file, prints a table, and exits with code 1 if anything is over budget. `scripts/test_sla_check.py` is a small test for that script.

## Running it

Start QuickPizza. You need Go 1.26+ and Node.js:

```bash
git clone https://github.com/grafana/quickpizza && cd quickpizza
cd pkg/web && npm install && npm run build && cd ../..
go build -o bin/quickpizza ./cmd && ./bin/quickpizza      # http://localhost:3333
```

Then run a profile. You need JMeter 5.6+ and Python 3:

```bash
export JMETER_HOME=/path/to/apache-jmeter-5.6.3
bash scripts/run.sh smoke     # 5 users, 30 s
bash scripts/run.sh load      # 20 users, 3 min (LOAD_USERS=50 to change)
bash scripts/run.sh stress    # 10, 20, 30, 40, 50, 75, 100 users, stops at the first SLA failure
bash scripts/run.sh spike     # 300 users ramped up in 5 s
bash scripts/run.sh soak      # 30 users, 15 min
```

Each run writes to `results/<profile>/`: the raw `results.jtl`, a `summary.md` with the SLA table, and the JMeter HTML dashboard. You can override any property, for example `bash scripts/run.sh load -Jhost=10.0.0.5 -Jthink_ms=1000`.

CI runs the smoke profile on every push, with QuickPizza as a service container. The SLA table goes into the job summary and the dashboard is uploaded as an artifact.

## Problems I ran into

- At first I used `__chooseRandom` to pick random values. It isn't a core JMeter function, because it comes from the Plugins pack. Without the plugin, JMeter sent the literal text `${__chooseRandom(...)}` and every request got a 400. I replaced it with `__jexl3` and `__Random`, which are built in.
- JMeter 5.6.3 ships a Groovy version that doesn't work on JDK 25 (`Unsupported class file major version 69`). Every thread that hit a `__groovy` call died. The plan doesn't use Groovy anymore, and CI runs on JDK 17.
- When a recommendation failed, the rating after it failed too, so one problem counted as two errors. The If Controller in step 3 fixes that.
- On a 4-core laptop with a browser and an IDE open, results were all over the place even with only 10 users. More on this in [RESULTS.md](RESULTS.md#a-note-on-the-first-runs).

## Files

```
test-plans/quickpizza.jmx   the test plan
data/users.csv              200 test users
scripts/run.sh              runs a profile, builds the dashboard, checks the SLA
scripts/sla_check.py        SLA check (p50/p90/p95/p99, error %, req/s)
scripts/test_sla_check.py   test for sla_check.py
.github/workflows/          CI smoke run
RESULTS.md                  results and analysis
```
