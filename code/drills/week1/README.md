# Week 1 Drills — Arrays, Two Pointers, Hash Maps

**20 minutes at the START of every session. Two problems. Timer on.**

The HackerRank gate is a speed test, and speed is built by spaced repetition, not
by volume in a burst. Ten problems this week, ten next week, forty sessions total.

## How to run these

1. Set a timer for 10 minutes per problem.
2. Write your solution in `attempts/<day>_<n>.py` — not in your head.
3. State the time and space complexity **out loud** before you look at the solution.
4. Only then open `solutions.py`.
5. If you didn't finish in 10 minutes, write down *where* you stalled. That's the signal.

Do not read the solutions first. Reading a solution feels like learning and isn't.

## The problems

### Day 1

**1. Two-sum on a running ledger.** Given `amounts: list[int]` and a `target`,
return the indices of the two amounts summing to `target`, or `None`. One pass.
*(hash map — the base case for everything else this week)*

**2. Longest run of distinct actions.** Given a list of action strings, return the
length of the longest contiguous window in which no action repeats.
*(sliding window + hash map)*

### Day 2

**3. Merge overlapping billing periods.** Given `periods: list[tuple[int, int]]`
of `(start_day, end_day)` inclusive, merge overlapping and adjacent periods and
return them sorted.
*(sort + linear scan — appears constantly in FDE data-cleanup work)*

**4. First non-repeating document ID.** Given a list of IDs, return the first one
that appears exactly once, or `None`.
*(counting pass then order pass — watch for the two-pass instinct)*

### Day 3

**5. Move all unbilled entries to the end.** Given a list where `0` means
unbilled, move every `0` to the end in place, preserving the relative order of
the non-zero entries. O(1) extra space.
*(two pointers, write index)*

**6. Max profit from one buy and one sell.** Given `prices: list[int]` in
chronological order, return the maximum profit from a single buy followed by a
later sell, or `0`.
*(running minimum — the DP base case you'll build on in week 6)*

### Day 4

**7. Group anagram citations.** Given a list of strings, group them so that
strings which are anagrams of each other end up in the same group. Return the
groups.
*(hash map with a canonical key — the "canonical form" idea recurs in dedup work)*

**8. Longest consecutive sequence of case years.** Given an unsorted list of
years, return the length of the longest run of consecutive years present.
O(n) — sorting is the trap here.
*(set membership + only start counting from run beginnings)*

### Day 5

**9. Subarray summing to a target.** Given `amounts: list[int]` (may contain
negatives) and `target`, return the number of contiguous subarrays summing to
`target`.
*(prefix sums in a hash map — the single highest-leverage pattern in this set)*

**10. Product of all other entries.** Given `nums: list[int]`, return a list
where `out[i]` is the product of every element except `nums[i]`. No division,
O(n) time.
*(prefix and suffix passes)*

## After you finish all ten

Answer these out loud, no notes:

- When does a sliding window apply, and what tells you the window should shrink?
- Why does prefix-sum-in-a-hash-map handle negative numbers when a sliding window doesn't?
- Problem 8 forbids sorting. What is the actual insight that makes it O(n)?
- Which two of these ten share the same underlying pattern?

If you can't answer all four, redo the ones you're shaky on tomorrow instead of
moving to Week 2's set. Coverage matters less than the patterns sticking.
