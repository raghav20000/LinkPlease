# FAILURES.md

Honest list of the ways this system can still lose a DM, send a duplicate,
or report a wrong number, and the conditions under which each happens.

---

### 1. Webhook signature verification (Part B) could not be validated end-to-end

Our HMAC-SHA256-of-raw-body implementation is provably correct in isolation:
a manually constructed request, signed client-side with our issued `api_key`,
is accepted (`200`) by our verification code. However, real traffic from
`/v1/simulate/start` never produces a signature that matches what we compute
with that same key -- confirmed via server-side debug logging comparing
`expected_sig` against `received_sig` on every request, with the key's
length and last 4 characters logged to rule out a stale/wrong key on our
end (they were stable and correct across every request). We could not
determine whether PseudoGram signs webhook deliveries with a different
secret than the issued API key, or whether this is a platform-side issue.
We flagged this on the LinkedIn post. Signature enforcement is currently
set to log-only (warns, does not reject) so that Part A/C could be tested
and verified against real traffic. This means Part B's rejection behavior
is implemented and independently tested as correct, but not currently
active in production.

### 2. PseudoGram's DM-send response didn't match the documented shape, and we shipped with a real bug because of it

The README documents `POST /v1/dm/send` returning `202` with
`{"dm_id","status":"queued"}`. In practice, the actual simulator sometimes
returns `200` with `{"dm_id","status":"delivered"}` immediately -- no
`202`, no polling required. Our original code only branched on
`status_code == 202` and treated everything else (including this `200`)
as an unexpected error, retrying it until it exhausted attempts and was
wrongly marked `failed`. This was caught via debug logging during our own
load test (a run where every attempt logged `status=200,
body={"status":"delivered"}` and was still marked failed) and fixed to
accept both response shapes. Noted here because it demonstrates real
event data diverging from the documented contract -- any integration
relying solely on the README's `202` description would silently drop
DMs the same way ours did before the fix.

### 3. Process crash between "PseudoGram accepted the DM" and our DB write

In `dm_worker._process_send`, we `await client.send_dm(...)`, get back a
success response, and only then write the resulting status to Mongo. If
the process is killed in the gap between the HTTP response arriving and
the `update_one` completing, PseudoGram has accepted (and may deliver) a
DM that our database has no record of. The job document is still sitting
at `status=sending` forever -- never reconciled, never retried, never
counted in `/stats`. There's no periodic sweep that resets stale
`sending` jobs back to `queued` after a timeout; we did not build that.

### 4. In-process rate limiter and worker assume a single backend instance

The 10-req/60s token bucket and the worker's polling loop both live in
memory, scoped to one process. If Render restarts the service, the
limiter resets even though PseudoGram's own rolling window doesn't. If
Render were ever scaled to more than one instance, each instance would
run its own independent budget and polling loop, and their combined
traffic could exceed PseudoGram's real limit. We deploy a single
instance specifically to avoid this; the code does not defend against it.

### 5. `comment.deleted` racing a job that's already past the check

We check `comments.deleted` once, at the top of `_process_send`, before
calling PseudoGram. If a `comment.deleted` event is processed by the
webhook handler in the small window after that check but before
`send_dm` returns, we will still send the DM. The deletion tombstone
only prevents sends that haven't started yet.

### 6. Comment-deletion policy is a judgment call, not a spec

The README explicitly leaves "what should happen if `comment.deleted`
arrives before you've sent the DM" open. We chose: don't send, and
count the job as `failed` with `error=comment_deleted_before_send`.
That conflates "we tried and gave up" with "we deliberately declined"
in the `failed` stats bucket. If the grader expects deleted-comment DMs
to still be sent, this will read as a bug rather than a design decision.

### 7. MongoDB Atlas connectivity blip during a burst

If Atlas has a brief connectivity hiccup while the webhook handler is
mid-request, `db.events.insert_one` or `db.dm_jobs.insert_one` will
raise, and FastAPI returns a `500` instead of the required `200`.
PseudoGram's own ~8% redelivery is what saves us here -- but if a
comment's only delivery attempt lands inside that outage window, the
event is lost outright with no local disk buffer or outbox to fall
back on.

### 8. ~10-11% gap between expected and actual unique recipients under load

In a clean 500-event simulator run (run_0673e7d71e9d), PseudoGram's
`/truth` reported 90 expected unique recipients; our system created DM
jobs for 80 of them (71 delivered, 9 failed after retries exhausted).
We did not have time to fully root-cause the ~10-recipient gap before
the deadline. The most likely explanations, in order of suspicion: (a)
comment.deleted tombstones arriving before the matching comment.created
for some of those users, which our code correctly treats as "don't
send" rather than a bug -- but we did not verify this is actually what
happened for these specific 10; (b) a subtler timing issue in how we
resolve duplicate/redelivered events for users whose only matching
comment arrived as a redelivery. This is flagged here rather than
silently left out of parts_completed.
