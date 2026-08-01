"""
Week 1 drill solutions — arrays, two pointers, hash maps.

DO NOT OPEN THIS UNTIL YOU HAVE ATTEMPTED THE PROBLEM AND STATED YOUR COMPLEXITY
OUT LOUD. Reading a solution feels like progress and isn't.

Run the tests: python drills/week1/solutions.py
"""

from collections import Counter, defaultdict


# 1 -------------------------------------------------------------------------
def two_sum(amounts: list[int], target: int) -> tuple[int, int] | None:
    """O(n) time, O(n) space.

    The move: as you scan, ask "have I already seen the number that completes
    this pair?" That inverts a nested loop into a single pass. Every problem in
    this set is a variation on trading space for a second loop.
    """
    seen: dict[int, int] = {}
    for i, amount in enumerate(amounts):
        complement = target - amount
        if complement in seen:
            return (seen[complement], i)
        seen[amount] = i
    return None


# 2 -------------------------------------------------------------------------
def longest_distinct_run(actions: list[str]) -> int:
    """O(n) time, O(k) space where k = distinct actions.

    Sliding window. The window shrinks when the invariant ("no duplicates")
    breaks. Jumping `left` straight past the previous occurrence — rather than
    stepping it one at a time — is what keeps this O(n) instead of O(n^2).
    """
    last_seen: dict[str, int] = {}
    left = 0
    best = 0
    for right, action in enumerate(actions):
        if action in last_seen and last_seen[action] >= left:
            left = last_seen[action] + 1
        last_seen[action] = right
        best = max(best, right - left + 1)
    return best


# 3 -------------------------------------------------------------------------
def merge_periods(periods: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """O(n log n) time (sort dominates), O(n) space.

    Sorting by start is what makes the single scan correct: once sorted, a period
    can only ever overlap the one you're currently building. `start <= cur_end + 1`
    merges adjacent days too — read the spec carefully, because "adjacent" vs
    "strictly overlapping" is exactly the kind of detail an interviewer plants.
    """
    if not periods:
        return []

    merged: list[tuple[int, int]] = []
    for start, end in sorted(periods):
        if merged and start <= merged[-1][1] + 1:
            cur_start, cur_end = merged[-1]
            merged[-1] = (cur_start, max(cur_end, end))
        else:
            merged.append((start, end))
    return merged


# 4 -------------------------------------------------------------------------
def first_unique(ids: list[str]) -> str | None:
    """O(n) time, O(n) space.

    Two passes, and two passes is correct here — you cannot know something is
    unique until you've seen everything. Candidates who try to force one pass
    usually produce a subtly wrong answer. Say "two passes, both O(n), so still
    O(n)" and move on.
    """
    counts = Counter(ids)
    for doc_id in ids:
        if counts[doc_id] == 1:
            return doc_id
    return None


# 5 -------------------------------------------------------------------------
def move_unbilled_to_end(entries: list[int]) -> list[int]:
    """O(n) time, O(1) extra space. Mutates in place and returns the list.

    Write-pointer pattern: `write` marks where the next kept element goes.
    Swapping (rather than assigning then zero-filling) keeps it to one pass.
    """
    write = 0
    for read in range(len(entries)):
        if entries[read] != 0:
            entries[write], entries[read] = entries[read], entries[write]
            write += 1
    return entries


# 6 -------------------------------------------------------------------------
def max_profit(prices: list[int]) -> int:
    """O(n) time, O(1) space.

    Track the running minimum. This is the smallest possible dynamic program:
    the state you carry forward is "cheapest price so far", and that's the whole
    trick. Recognise it now — week 6's DP problems are this idea with more state.
    """
    best = 0
    cheapest = float("inf")
    for price in prices:
        cheapest = min(cheapest, price)
        best = max(best, price - cheapest)
    return best


# 7 -------------------------------------------------------------------------
def group_anagrams(words: list[str]) -> list[list[str]]:
    """O(n * k log k) time where k = word length, O(n * k) space.

    Canonical form as a hash key. Sorted letters is the simplest canonical form;
    a 26-length count tuple gets you O(n * k) if the interviewer pushes. The
    general idea — reduce variants to one canonical key, then group — is the same
    one behind citation dedup and near-duplicate document detection.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for word in words:
        groups["".join(sorted(word))].append(word)
    return list(groups.values())


# 8 -------------------------------------------------------------------------
def longest_consecutive(years: list[int]) -> int:
    """O(n) time, O(n) space.

    The insight: only start counting from a year whose predecessor is ABSENT.
    That guarantees each run is walked exactly once, so the inner while loop
    doesn't make this quadratic. Without that guard it's O(n^2); with it, O(n).
    Sorting would be O(n log n) and is the trap the problem is testing for.
    """
    present = set(years)
    best = 0
    for year in present:
        if year - 1 in present:
            continue  # not the start of a run
        length = 1
        while year + length in present:
            length += 1
        best = max(best, length)
    return best


# 9 -------------------------------------------------------------------------
def count_subarrays_with_sum(amounts: list[int], target: int) -> int:
    """O(n) time, O(n) space.

    Prefix sums in a hash map. If prefix[j] - prefix[i] == target, then the
    subarray (i, j] sums to target — so at each j, ask how many earlier prefixes
    equalled prefix[j] - target.

    Why not a sliding window? A window relies on the sum growing monotonically as
    you extend it. Negative numbers break that, so shrinking on "too big" is no
    longer valid. Prefix sums don't care about sign. Know this distinction — it's
    a favourite follow-up.

    The seed {0: 1} accounts for subarrays that start at index 0.
    """
    counts: dict[int, int] = {0: 1}
    running = 0
    found = 0
    for amount in amounts:
        running += amount
        found += counts.get(running - target, 0)
        counts[running] = counts.get(running, 0) + 1
    return found


# 10 ------------------------------------------------------------------------
def product_except_self(nums: list[int]) -> list[int]:
    """O(n) time, O(1) extra space (excluding the output).

    Two passes: build prefix products left-to-right into the output, then fold
    suffix products in right-to-left. Division is banned because a single zero
    breaks it — and if the interviewer allows division, they'll immediately ask
    what happens with a zero. Know both answers.
    """
    n = len(nums)
    out = [1] * n

    prefix = 1
    for i in range(n):
        out[i] = prefix
        prefix *= nums[i]

    suffix = 1
    for i in range(n - 1, -1, -1):
        out[i] *= suffix
        suffix *= nums[i]

    return out


# --------------------------------------------------------------------- tests
def _run_tests() -> None:
    assert two_sum([120, 340, 55, 260], 315) == (2, 3)
    assert two_sum([1, 2], 100) is None

    assert longest_distinct_run(["view", "edit", "view", "save", "edit"]) == 3
    assert longest_distinct_run([]) == 0
    assert longest_distinct_run(["a", "a", "a"]) == 1

    assert merge_periods([(1, 5), (6, 9), (12, 15)]) == [(1, 9), (12, 15)]
    assert merge_periods([(5, 10), (1, 3)]) == [(1, 3), (5, 10)]
    assert merge_periods([]) == []

    assert first_unique(["d1", "d2", "d1", "d3"]) == "d2"
    assert first_unique(["d1", "d1"]) is None

    assert move_unbilled_to_end([1, 0, 3, 0, 0, 7]) == [1, 3, 7, 0, 0, 0]
    assert move_unbilled_to_end([0, 0]) == [0, 0]

    assert max_profit([7, 1, 5, 3, 6, 4]) == 5
    assert max_profit([9, 8, 7]) == 0
    assert max_profit([]) == 0

    groups = group_anagrams(["listen", "silent", "enlist", "google"])
    assert sorted(len(g) for g in groups) == [1, 3]

    assert longest_consecutive([1994, 1996, 1995, 2010, 1993]) == 4
    assert longest_consecutive([]) == 0

    assert count_subarrays_with_sum([1, 2, 3], 3) == 2
    assert count_subarrays_with_sum([1, -1, 0], 0) == 3

    assert product_except_self([1, 2, 3, 4]) == [24, 12, 8, 6]
    assert product_except_self([2, 0, 3]) == [0, 6, 0]

    print("all week 1 drill tests passed")


if __name__ == "__main__":
    _run_tests()
