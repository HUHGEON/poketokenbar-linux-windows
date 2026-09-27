"""Which form a companion grows into, when the line branches.

This port used to answer "the first one, always": the evolution chain was
flattened by taking `evolves_to[0]` at every step. Eevee has eight children, so
seven of its evolutions were unreachable and the Pokedex could not be
completed — and `collected_finals`, which upstream uses to steer the choice,
was written to the save and never read by anything.
"""

import random

import pytest

from poketokenbar.balance import Rarity
from poketokenbar.companion import (
    CompanionState, EvoLine, EvoNode, apply_usage, pick_planned_child, plan_path,
)
from poketokenbar import balance


def eevee() -> EvoLine:
    """A wide, shallow line: one base, many finals, no intermediate form."""
    tree = EvoNode(133, [EvoNode(i) for i in (134, 135, 136, 196, 197, 470, 471)])
    return EvoLine(base_id=133, path_ids=[133, 134], rarity=Rarity.COMMON, tree=tree)


def wurmple() -> EvoLine:
    """A line that branches in the middle, so the two routes share a first step."""
    tree = EvoNode(265, [
        EvoNode(266, [EvoNode(267)]),
        EvoNode(268, [EvoNode(269)]),
    ])
    return EvoLine(base_id=265, path_ids=[265, 266, 267], rarity=Rarity.COMMON, tree=tree)


# MARK: the tree


def test_a_leaf_is_its_own_final_form():
    assert EvoNode(20).finals == [20]


def test_finals_gathers_every_branch():
    assert set(wurmple().tree.finals) == {267, 269}


def test_depth_is_the_longest_route():
    assert eevee().tree.depth == 2
    assert wurmple().tree.depth == 3


def test_a_species_without_an_animated_sprite_takes_its_branch_with_it():
    """Sylveon is #700, past the Gen-V assets. Keeping it would let a plan
    route into a form that cannot be drawn."""
    tree = EvoNode(133, [EvoNode(134), EvoNode(700)])
    kept = tree.keeping_animated()
    assert kept.finals == [134]


def test_a_whole_tree_past_the_asset_range_is_dropped():
    assert EvoNode(700, [EvoNode(701)]).keeping_animated() is None


def test_a_straight_line_can_still_be_described_without_a_tree():
    """The common case, and what every existing caller passes."""
    line = EvoLine(base_id=1, path_ids=[1, 2, 3], rarity=Rarity.COMMON)
    assert line.tree.finals == [3]
    assert line.total_forms == 3


# MARK: choosing a branch


def test_every_branch_is_reachable():
    """The regression. One of these used to be the answer every time."""
    line = eevee()
    rng = random.Random(11)
    reached = {plan_path(line, set(), rng)[-1] for _ in range(200)}
    assert reached == set(line.tree.finals)


def test_a_branch_you_have_not_collected_is_preferred():
    line = eevee()
    # Everything collected except Umbreon.
    collected = {f"133:{final}" for final in line.tree.finals} - {"133:197"}
    rng = random.Random(5)
    for _ in range(20):
        assert plan_path(line, collected, rng)[-1] == 197


def test_a_fully_collected_line_still_picks_something():
    """Once there is nothing fresh left the whole set is the pool again, rather
    than the plan coming back empty."""
    line = eevee()
    collected = {f"133:{final}" for final in line.tree.finals}
    plan = plan_path(line, collected, random.Random(2))
    assert plan[-1] in line.tree.finals


def test_freshness_looks_past_the_immediate_child():
    """Wurmple's children are Silcoon and Cascoon, neither of which is a final
    form — the preference has to reach the ends of each branch to mean
    anything."""
    line = wurmple()
    collected = {"265:267"}  # Beautifly caught; Dustox not
    rng = random.Random(1)
    for _ in range(20):
        assert plan_path(line, collected, rng) == [265, 268, 269]


def test_the_preference_is_per_base_species():
    """Collecting #267 from one base says nothing about another base that also
    reaches it."""
    line = wurmple()
    collected = {"999:267", "999:269"}
    reached = {plan_path(line, collected, random.Random(seed))[-1] for seed in range(30)}
    assert reached == {267, 269}


def test_picking_from_a_single_child_is_that_child():
    node = EvoNode(1, [EvoNode(2)])
    assert pick_planned_child(node, 1, set(), random.Random(0)).species_id == 2


# MARK: what the hatch records


def test_a_hatch_records_the_route_it_planned():
    state = CompanionState()
    line = wurmple()
    apply_usage(state, balance.EGG_HATCH_THRESHOLD, line_for_egg=line,
                rng=random.Random(4))
    mon = state.active
    assert mon.path_ids == mon.planned_path_ids
    assert mon.path_ids[0] == 265
    assert mon.path_ids[-1] in (267, 269)
    assert mon.total_forms == len(mon.path_ids)


def test_total_forms_follows_the_route_not_the_tree():
    """A two-form branch of a three-deep tree has two stages to pay for. Using
    the tree's depth would charge for a form this companion never reaches."""
    tree = EvoNode(1, [EvoNode(2), EvoNode(3, [EvoNode(4)])])
    line = EvoLine(base_id=1, path_ids=[1, 2], rarity=Rarity.COMMON, tree=tree)
    assert line.total_forms == 3, "the tree is three deep"

    state = CompanionState()
    # Everything but the short branch collected, so the long one is chosen.
    state.collected_finals = {"1:2"}
    apply_usage(state, balance.EGG_HATCH_THRESHOLD, line_for_egg=line,
                rng=random.Random(0))
    assert state.active.path_ids == [1, 3, 4]
    assert state.active.total_forms == 3

    state2 = CompanionState()
    state2.collected_finals = {"1:4"}
    apply_usage(state2, balance.EGG_HATCH_THRESHOLD, line_for_egg=line,
                rng=random.Random(0))
    assert state2.active.path_ids == [1, 2]
    assert state2.active.total_forms == 2


def test_a_graduation_feeds_the_next_hatch_s_choice():
    """End to end: graduating one branch makes the next egg prefer the other.
    This is the loop `collected_finals` exists for, and nothing read it."""
    line = wurmple()
    state = CompanionState()
    rng = random.Random(9)
    apply_usage(state, balance.EGG_HATCH_THRESHOLD, line_for_egg=line, rng=rng)
    first = list(state.active.path_ids)
    apply_usage(state, balance.graduation_total(Rarity.COMMON))
    assert state.active is None
    assert f"265:{first[-1]}" in state.collected_finals

    apply_usage(state, balance.EGG_HATCH_THRESHOLD, line_for_egg=line, rng=rng)
    assert state.active.path_ids[-1] != first[-1], "it planned the same branch again"


# MARK: the chain PokeAPI actually returns


def test_a_pokeapi_chain_becomes_a_tree_with_its_branches():
    from poketokenbar.pokeapi import _tree_from_chain

    chain = {
        "species": {"url": "https://pokeapi.co/api/v2/pokemon-species/265/"},
        "evolves_to": [
            {"species": {"url": "https://pokeapi.co/api/v2/pokemon-species/266/"},
             "evolves_to": [
                 {"species": {"url": "https://pokeapi.co/api/v2/pokemon-species/267/"},
                  "evolves_to": []}]},
            {"species": {"url": "https://pokeapi.co/api/v2/pokemon-species/268/"},
             "evolves_to": [
                 {"species": {"url": "https://pokeapi.co/api/v2/pokemon-species/269/"},
                  "evolves_to": []}]},
        ],
    }
    tree = _tree_from_chain(chain)
    assert tree.species_id == 265
    assert [child.species_id for child in tree.children] == [266, 268]
    assert set(tree.finals) == {267, 269}


@pytest.mark.parametrize("chain", [None, {}, {"species": {"url": "nonsense"}}])
def test_an_unusable_chain_is_refused_rather_than_half_built(chain):
    from poketokenbar.pokeapi import _tree_from_chain

    assert _tree_from_chain(chain) is None
