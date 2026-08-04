# Field Notes

Observations from running this pattern in practice, generalized — nothing
below references a specific company, dataset, or metric. If a note here
sounds oddly specific, that's the point: these are the kinds of failures
that only show up once real analysts and real Claude sessions are working
against a shared repo at the same time, not the failures you'd predict
from a design doc.

## The registry only works if it's cheaper to use than to bypass

The first version of a rule like "always resolve metrics through the
registry" is a paragraph in a README. That paragraph gets ignored under
deadline pressure, every time — not out of carelessness, but because
writing `SELECT SUM(...)` inline is faster than opening a second file. The
fix isn't a stricter instruction, it's removing the option: a resolver
function that's the *only* accessible path to warehouse data from
dashboard/bot code. If the shortcut doesn't exist, nobody has to resist
taking it.

## "Filterable by everything" is a trap

The instinct is to make every metric sliceable by every dimension, because
it *feels* like more flexibility. In practice, some metrics have a fixed
cohort window baked into their definition (a 90-day LTV, a channel-grained
CAC) and don't compose with an arbitrary filter without silently changing
what the number means. Marking those explicitly — "this one doesn't
filter, here's why" — prevented more confusion than any amount of
flexibility would have added.

## Golden-query tests catch the change nobody meant to make

Most regressions in a shared metrics layer aren't someone deliberately
redefining a number — it's a refactor of a shared base query (like a fact
table join) that quietly shifts a downstream aggregate. Pinning actual
values in tests, not just "does it run," is what catches that class of
bug before it reaches a dashboard.

## Verification earns trust faster than accuracy claims do

Analysts didn't start trusting Claude-generated dashboard code because it
was described as accurate — they started trusting it once they could see
the same PR that changed a formula also had to touch the test that pins
its value, and CI enforced that pairing. The trust came from the process
being visible and hard to route around, not from a claim about output
quality.

## Parallel sessions need branches more than they need permission

Once analysts had a repeatable way to spin up isolated worktrees, the
question stopped being "can I touch this while someone else is working"
and became "which branch is this on" — a normal git question instead of a
coordination problem. The infrastructure did more work here than any
process document would have.
