"""MessageRepo: which message the bot edits for a given purpose.

Moved out of test_classes_repo.py when the table stopped belonging to the classes alone.
"""

from db import MessageRepo


async def test_a_managed_message_is_remembered(messages: MessageRepo) -> None:
    await messages.remember("board", 10, 20)

    managed = await messages.get("board")

    assert managed is not None
    assert (managed.channel_id, managed.message_id) == (10, 20)


async def test_two_boards_are_remembered_separately(messages: MessageRepo) -> None:
    """The two messages are edited independently, so neither may overwrite the other."""
    await messages.remember("board_main", 10, 20)
    await messages.remember("board_alt", 10, 21)

    main = await messages.get("board_main")
    alternates = await messages.get("board_alt")

    assert main is not None and alternates is not None
    assert main.message_id != alternates.message_id


async def test_reposting_replaces_the_remembered_message(messages: MessageRepo) -> None:
    await messages.remember("board", 10, 20)

    await messages.remember("board", 11, 21)

    managed = await messages.get("board")
    assert managed is not None
    assert (managed.channel_id, managed.message_id) == (11, 21)


async def test_an_unknown_managed_message_is_none(messages: MessageRepo) -> None:
    assert await messages.get("inconnu") is None


async def test_forget_reports_whether_it_existed(messages: MessageRepo) -> None:
    await messages.remember("board", 10, 20)

    assert await messages.forget("board") is True
    assert await messages.forget("board") is False


async def test_keys_are_swept_by_prefix(messages: MessageRepo) -> None:
    """The directory posts one message per profession, and reposting must find them all."""
    await messages.remember("prof:alchemy", 1, 1)
    await messages.remember("prof:tailoring", 1, 2)
    await messages.remember("class_board_main", 1, 3)

    assert await messages.keys_starting_with("prof:") == ["prof:alchemy", "prof:tailoring"]
