"""The sprite files behind the companion on Home."""


def test_a_failed_animation_falls_back_to_the_still_and_is_asked_for_again(tmp_path):
    """A GIF that cannot be fetched left Home drawing an empty box until some
    later poll happened to succeed (upstream 2f2fb32)."""
    from poketokenbar.companion import CompanionState, MonState
    from poketokenbar.companion_store import CompanionStore

    asked = []

    class Sprites:
        def path(self, species_id, animated=True, shiny=False, form=None):
            asked.append(animated)
            # The animation is unavailable; the still picture is there.
            return None if animated else tmp_path / f"{species_id}.png"

    store = CompanionStore(save_path=tmp_path / "companion.json", api=None,
                           sprite_store=Sprites())
    store.state = CompanionState(active=MonState(
        base_id=1, path_ids=[1], planned_path_ids=[1], total_forms=1))

    assert store.sprite_path().endswith("1.png")
    assert asked == [True, False], "the animation is tried first"

    # Nothing is remembered about the failure: the next poll tries again.
    asked.clear()
    store.sprite_path()
    assert asked == [True, False]
