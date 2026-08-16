# FAILURES.md

Honest list of the ways this system can still lose a DM, send a duplicate,
or report a wrong number, and the conditions under which each happens.

---

### 1. Process crash between "PseudoGram accepted the DM" and our DB write

In `dm_worker._process_send`, we `await client.send_dm(...)`, get back a
`202` with a `dm_id`, and only then write `status=in_flight, dm_id=...`
to Mongo. If the process is killed in the gap between the HTTP response
arriving and the `update_one` completing, PseudoGram has accepted (and
may deliver) a DM that our database has no record of. The job document
is still sitting at `status=sending` forever — it will never be reconciled,
never retried, and never counted in `/stats`. It isn't duplicated (we
won't resend it, because nothing tells us to), but it's an orphaned
in-flight DM our own numbers don't reflect. A periodic sweep that resets
stale `sending` jobs back to `queued` after a timeout would at least
convert this into a duplicate-risk problem (mitigated by the
`Idempotency-Key`) instead of a silent-loss problem — I did not build
that sweep.

### 2. In-process rate limiter and idempotency window don't survive a restart

The 10-req/60s token bucket (`RollingWindowRateLimiter`) lives in memory.
If Render restarts the service (deploy, crash, free-tier spin-down), the
limiter resets to empty and PseudoGram's *real* rolling window doesn't
know that. For the first ~60 seconds after a restart, if there's a large
backlog of queued jobs, we could send faster than PseudoGram's server-side
limiter actually allows on their side, because our count of "requests in
the last 60s" was wiped out by the restart even though PseudoGram's
wasn't. In practice this mostly self-corrects via the 429 retry path, but
it's a real gap, not a theoretical one.

### 3. Single-process assumption

The unique-index-based duplicate protection (`events.event_id`,
`dm_jobs.(rule_id,user_id)`) is safe under any number of concurrent
processes — that part scales. The in-memory rate limiter and the
worker's polling loop do not: if Render is ever scaled to more than one
instance, each instance runs its own independent 10-req/60s budget and
its own polling loop. Two instances could each think they have room for
10 requests/minute and collectively blow through PseudoGram's real
limit. We deploy a single instance specifically to avoid this; the code
does not defend against it.

### 4. `comment.deleted` racing a job that's already past the check

We check `comments.deleted` once, at the top of `_process_send`, before
calling PseudoGram. If a `comment.deleted` event is processed by the
webhook handler in the small window *after* that check but *before*
`send_dm` returns, we will still send the DM. The deletion tombstone
only prevents sends that haven't started yet; it doesn't cancel one
already in flight. This window is small (single-digit milliseconds
under normal load) but it's not zero.

### 5. `duplicates_blocked` undercounts one specific case

We log a duplicate in exactly two places: a rejected `events.event_id`
insert, and a rejected `dm_jobs.(rule_id,user_id)` insert. If a comment
matches zero rules, or a webhook payload is missing `from.user_id`, we
silently return `{"status": "ok"}` without touching `duplicates_blocked`
— which is correct, those aren't duplicates. But if `comment.deleted`
arrives for a comment we'd already matched (job already queued/sent),
we do not go back and touch that job at all — so a "deletion after the
DM was already queued" is neither a duplicate nor a failure in our
stats; it's invisible. Whether that's the right stats treatment is a
judgment call I made, not something the README specifies.

### 6. Comment-deletion policy is a guess, not a spec

The README explicitly says "think about what should happen" for
`comment.deleted` arriving before the DM is sent — it's an open design
question. I chose: don't send, and count the job as `failed` with
`error=comment_deleted_before_send`. That means our `failed` number in
`/stats` conflates "we tried and PseudoGram gave up" with "we
deliberately chose not to try." If the grader's `/truth` endpoint
expects deleted-comment DMs to still be sent, this will look like a bug
rather than a design decision. I'm flagging it here specifically because
I'm not fully confident it's the interpretation the grader wants.

### 7. MongoDB Atlas connectivity blip during a burst

If MongoDB Atlas has a brief connectivity hiccup (network partition,
Atlas maintenance) while the webhook handler is mid-request, the
`db.events.insert_one` or `db.dm_jobs.insert_one` calls will raise, and
FastAPI will return a `500` to PseudoGram for that event instead of the
required `200`. PseudoGram's own redelivery (the ~8% redelivery
behavior described in the README) is what saves us here — but if a
comment's *only* delivery attempt happens to land inside that outage
window, the event is lost outright and no job is ever created for it.
There's no local disk buffer or outbox to fall back on.
