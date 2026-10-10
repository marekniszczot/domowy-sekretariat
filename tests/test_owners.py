import pytest

from sekretariat.household import Member, Role
from sekretariat.owners import Cause, OwnerEvent, act, coordinator, initial_owner

# Household order defines OSOBA_n: OSOBA_1 = rodzic, OSOBA_2 = koord (coordinator), ...
RODZIC = Member("rodzic", Role.DOMOWNIK)
KOORD = Member("koord", Role.KOORDYNATOR)
SENIOR = Member("senior", Role.BEZ_KONTA)
DZIECKO = Member("dziecko", Role.DOMOWNIK)
HOUSE = [RODZIC, KOORD, SENIOR, DZIECKO]


@pytest.mark.parametrize("verdict", ["NONE", "SELF", "FORWARD"])
@pytest.mark.parametrize(
    "addressee, owner",
    [
        ("OSOBA_1", "rodzic"),  # addressee with an account
        ("OSOBA_4", "dziecko"),
        ("OSOBA_2", "koord"),  # the coordinator is an addressee too
        ("OSOBA_3", "koord"),  # addressee without an account
        ("OSOBA_9", "koord"),  # outside the household
        ("INNA_1", "koord"),
        ("INNA", "koord"),
        ("NIEZNANY", "koord"),
        ("OSOBA_DOMU", "koord"),  # family name only: not known who
        (None, "koord"),  # analysis failed
    ],
)
def test_owner_before_any_action(verdict, addressee, owner):
    # The rule does not depend on the verdict: NONE with a deadline needs an owner too.
    assert initial_owner(HOUSE, addressee) == OwnerEvent(Cause.INITIAL, owner)


def test_two_member_household():
    house = [Member("a", Role.DOMOWNIK), Member("b", Role.KOORDYNATOR)]
    assert initial_owner(house, "OSOBA_1").owner == "a"
    assert initial_owner(house, "INNA_2").owner == "b"


def test_single_member_household():
    house = [Member("solo", Role.KOORDYNATOR)]
    assert initial_owner(house, "OSOBA_1").owner == "solo"
    assert initial_owner(house, "NIEZNANY").owner == "solo"


@pytest.mark.parametrize("previous", ["rodzic", "koord"])
@pytest.mark.parametrize("actor", ["rodzic", "koord", "dziecko"])
def test_handle_makes_the_actor_owner(previous, actor):
    assert act(HOUSE, previous, Cause.HANDLE, actor) == OwnerEvent(
        Cause.HANDLE, actor, previous, actor
    )


def test_handle_by_current_owner_is_still_an_event():
    event = act(HOUSE, "rodzic", Cause.HANDLE, "rodzic")
    assert event.owner == event.previous == "rodzic"
    assert event.cause == Cause.HANDLE


@pytest.mark.parametrize("target", ["koord", "dziecko", "rodzic"])
def test_forward_makes_the_target_owner(target):
    assert act(HOUSE, "rodzic", Cause.FORWARD, "rodzic", target) == OwnerEvent(
        Cause.FORWARD, target, "rodzic", "rodzic"
    )


@pytest.mark.parametrize("target", ["senior", "nobody", None])
def test_forward_needs_a_target_with_an_account(target):
    with pytest.raises(ValueError, match="cannot forward"):
        act(HOUSE, "rodzic", Cause.FORWARD, "rodzic", target)


@pytest.mark.parametrize("actor", ["senior", "nobody"])
def test_only_members_with_an_account_act(actor):
    with pytest.raises(ValueError, match="cannot act"):
        act(HOUSE, "koord", Cause.HANDLE, actor)


def test_initial_is_not_an_action():
    with pytest.raises(ValueError, match="not an action"):
        act(HOUSE, "koord", Cause.INITIAL, "koord")


def test_household_without_coordinator_is_an_error():
    with pytest.raises(ValueError, match="no coordinator"):
        initial_owner([RODZIC], "NIEZNANY")


def test_first_coordinator_is_used():
    house = [RODZIC, Member("x", Role.KOORDYNATOR), KOORD]
    assert coordinator(house).id == "x"
