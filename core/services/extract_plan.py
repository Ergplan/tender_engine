"""Which field groups of a run share a page window.

Every group has its own window (core.services.extract.select_pages). Pages sent once per
group are paid for once per group; pages of a window that several groups share are paid
for in full once, written to the prompt cache, and read from it by the other groups at a
small fraction of the price. Sharing therefore pays when windows overlap enough, and costs
when it makes a group read many pages it did not ask for or need more calls.

share_windows merges windows step by step, always the two that make their groups read
the fewest extra pages, and keeps the cheapest of the partitions it passes on the way. A
merged window stays within the page cap of a group. Plain arithmetic on page counts: the
unit is the price of one page sent uncached.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SharedWindow:
    """Groups that are read from the same pages, in schema order."""

    groups: tuple[str, ...]
    pages: tuple[int, ...]

    @property
    def shared(self) -> bool:
        return len(self.groups) > 1


def window_cost(
    pages: int,
    groups: int,
    *,
    pages_per_call: int,
    cache_write_factor: float,
    cache_read_factor: float,
    call_overhead_pages: float,
) -> float:
    """Cost of reading `pages` for `groups` groups, in uncached pages. One group: every
    page at full price. Several: one write to the cache, the others read from it. Each
    call also costs its output, weighed as `call_overhead_pages`."""
    if pages == 0 or groups == 0:
        return 0.0
    calls = groups * -(-pages // pages_per_call)
    if groups == 1:
        reading = float(pages)
    else:
        reading = pages * (cache_write_factor + cache_read_factor * (groups - 1))
    return reading + calls * call_overhead_pages


def share_windows(
    windows: dict[str, list[int]],
    *,
    max_pages: int,
    pages_per_call: int,
    cache_write_factor: float,
    cache_read_factor: float,
    call_overhead_pages: float,
) -> list[SharedWindow]:
    """Merge the groups' windows where that is cheaper. `windows` maps a group to its
    pages, in schema order; the result keeps that order (a merged window stands where its
    first group stood). A merged window is the union of its groups' pages and never
    exceeds `max_pages`."""

    def cost(pages: frozenset[int], groups: int) -> float:
        return window_cost(
            len(pages),
            groups,
            pages_per_call=pages_per_call,
            cache_write_factor=cache_write_factor,
            cache_read_factor=cache_read_factor,
            call_overhead_pages=call_overhead_pages,
        )

    order = {name: position for position, name in enumerate(windows)}
    clusters: list[tuple[tuple[str, ...], frozenset[int]]] = [
        ((name,), frozenset(pages)) for name, pages in windows.items() if pages
    ]

    def total(partition: list[tuple[tuple[str, ...], frozenset[int]]]) -> float:
        return sum(cost(pages, len(names)) for names, pages in partition)

    best, best_cost = list(clusters), total(clusters)
    while len(clusters) > 1:
        # The pair whose union adds the fewest pages to what its groups read; a tie goes
        # to the groups that come first in the schema.
        choice: tuple[int, int, int, int, int] | None = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                (names_i, pages_i), (names_j, pages_j) = clusters[i], clusters[j]
                union = len(pages_i | pages_j)
                if union > max_pages:
                    continue
                extra = (union - len(pages_i)) * len(names_i) + (union - len(pages_j)) * len(
                    names_j
                )
                key = (extra, order[names_i[0]], order[names_j[0]], i, j)
                if choice is None or key < choice:
                    choice = key
        if choice is None:
            break
        i, j = choice[3], choice[4]
        names = tuple(sorted(clusters[i][0] + clusters[j][0], key=order.__getitem__))
        merged = (names, clusters[i][1] | clusters[j][1])
        clusters = sorted(
            [c for k, c in enumerate(clusters) if k not in (i, j)] + [merged],
            key=lambda cluster: order[cluster[0][0]],
        )
        if total(clusters) < best_cost - 1e-9:
            best, best_cost = list(clusters), total(clusters)
    return [SharedWindow(groups=names, pages=tuple(sorted(pages))) for names, pages in best]
