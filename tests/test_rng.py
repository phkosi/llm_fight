import pytest
from llm_fight import rng  # Import the module itself to access its functions

# Note: llm_fight.rng is seeded from CONFIG when it's first imported.
# Tests need to be mindful of this initial state or explicitly re-seed.


def test_initial_determinism():
    """Test if initial state (from config or default seed) is deterministic."""
    # We don't know the exact seed from config without loading it here too,
    # but we can check if subsequent calls are consistent before any re-seeding.
    # This relies on the global CONFIG being loaded consistently if it affects the seed.
    # For a truly isolated test, one might mock CONFIG.get for rng module, but that's complex.

    # Reset to a known state for this specific test block, independent of config.ini
    # This makes the test independent of external config files.
    initial_test_seed = 12345
    rng.seed(initial_test_seed)

    seq1_rand = [rng.rand() for _ in range(5)]
    seq1_dice = [rng.dice(6) for _ in range(5)]
    seq1_choice = [rng.choice([1, 2, 3, 4, 5]) for _ in range(5)]

    rng.seed(initial_test_seed)  # Re-seed with the same value

    seq2_rand = [rng.rand() for _ in range(5)]
    seq2_dice = [rng.dice(6) for _ in range(5)]
    seq2_choice = [rng.choice([1, 2, 3, 4, 5]) for _ in range(5)]

    assert seq1_rand == seq2_rand, "rand() should be deterministic after seeding"
    assert seq1_dice == seq2_dice, "dice() should be deterministic after seeding"
    assert seq1_choice == seq2_choice, "choice() should be deterministic after seeding"


def test_explicit_seeding_determinism():
    test_seed = 42
    rng.seed(test_seed)
    r1_val1 = rng.rand()
    r1_val2 = rng.dice(100)
    r1_val3 = rng.choice(["a", "b", "c"])

    rng.seed(test_seed)  # Re-seed with the same value
    r2_val1 = rng.rand()
    r2_val2 = rng.dice(100)
    r2_val3 = rng.choice(["a", "b", "c"])

    assert r1_val1 == r2_val1
    assert r1_val2 == r2_val2
    assert r1_val3 == r2_val3


def test_different_seeds_produce_different_results():
    rng.seed(1)
    res1_rand = [rng.rand() for _ in range(10)]
    res1_dice = [rng.dice(20) for _ in range(10)]

    rng.seed(2)
    res2_rand = [rng.rand() for _ in range(10)]
    res2_dice = [rng.dice(20) for _ in range(10)]

    # It's statistically highly improbable they'd be identical for different seeds over 10 numbers
    assert res1_rand != res2_rand, "Different seeds should produce different rand() sequences"
    assert res1_dice != res2_dice, "Different seeds should produce different dice() sequences"


def test_rand_range():
    rng.seed(77)
    for _ in range(100):
        val = rng.rand()
        assert 0.0 <= val < 1.0, "rand() result out of range [0, 1)"


def test_dice_range_and_type():
    rng.seed(88)
    sides = 6
    for _ in range(100):
        roll = rng.dice(sides)
        assert isinstance(roll, int), "dice() should return an int"
        assert 1 <= roll <= sides, f"dice({sides}) roll out of range [1, {sides}]"

    sides = 1  # Edge case: 1-sided die
    for _ in range(10):
        roll = rng.dice(sides)
        assert roll == 1, "dice(1) should always return 1"

    with pytest.raises(ValueError):  # random.randint(1,0) raises ValueError
        rng.dice(0)
    with pytest.raises(ValueError):  # random.randint(1,-1) raises ValueError
        rng.dice(-1)


def test_choice():
    rng.seed(99)
    my_list = [10, 20, 30, 40, 50]
    my_tuple = ("x", "y", "z")
    my_string = "abc"

    for _ in range(20):
        assert rng.choice(my_list) in my_list
        assert rng.choice(my_tuple) in my_tuple
        assert rng.choice(my_string) in my_string

    with pytest.raises(IndexError):  # choice from empty sequence
        rng.choice([])
