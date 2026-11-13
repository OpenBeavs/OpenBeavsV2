"""The cap on simultaneous model calls: bounded concurrency, bounded wait."""

import asyncio
import json
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.registry.llm import (
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_WAIT_SECONDS,
    ModelBusyError,
    ModelLimiter,
)

from .a2a_helpers import Harness, add_agent, run

REPLY = json.dumps({"agent_id": "none", "confidence": 0.9, "reason": "ok"})


def tracked_call(hold: float = 0.05):
    """A fake model that records how many calls overlap."""
    state = {"now": 0, "peak": 0, "total": 0}

    async def call(system: str, user: str, schema: dict) -> str:
        state["now"] += 1
        state["total"] += 1
        state["peak"] = max(state["peak"], state["now"])
        try:
            await asyncio.sleep(hold)
        finally:
            state["now"] -= 1
        return REPLY

    return call, state


class TestLimiter:
    def test_calls_never_exceed_the_limit(self) -> None:
        call, state = tracked_call()
        limited = ModelLimiter(max_concurrent=2, wait_seconds=5).wrap(call)

        async def scenario() -> None:
            await asyncio.gather(*(limited("s", "u", {}) for _ in range(6)))

        run(scenario())
        assert state["total"] == 6 and state["peak"] == 2

    def test_a_request_that_waits_too_long_is_refused(self) -> None:
        call, state = tracked_call(hold=0.5)
        limited = ModelLimiter(max_concurrent=1, wait_seconds=0.05).wrap(call)

        async def scenario() -> list:
            return await asyncio.gather(
                limited("s", "u", {}), limited("s", "u", {}), return_exceptions=True
            )

        first, second = run(scenario())
        assert first == REPLY
        assert isinstance(second, ModelBusyError)
        assert state["total"] == 1  # the refused request never reached the model

    def test_the_refusal_is_quick_not_after_the_whole_call(self) -> None:
        call, _ = tracked_call(hold=1.0)
        limited = ModelLimiter(max_concurrent=1, wait_seconds=0.05).wrap(call)

        async def scenario() -> float:
            holder = asyncio.create_task(limited("s", "u", {}))
            await asyncio.sleep(0.01)
            started = time.monotonic()
            with pytest.raises(ModelBusyError):
                await limited("s", "u", {})
            elapsed = time.monotonic() - started
            holder.cancel()
            await asyncio.gather(holder, return_exceptions=True)
            return elapsed

        assert run(scenario()) < 0.5

    def test_a_zero_wait_refuses_at_once_but_uses_a_free_slot(self) -> None:
        call, _ = tracked_call(hold=0.2)
        limited = ModelLimiter(max_concurrent=1, wait_seconds=0).wrap(call)

        async def scenario() -> list:
            return await asyncio.gather(
                limited("s", "u", {}), limited("s", "u", {}), return_exceptions=True
            )

        first, second = run(scenario())
        assert first == REPLY and isinstance(second, ModelBusyError)

    def test_a_failing_call_gives_its_slot_back(self) -> None:
        async def boom(system: str, user: str, schema: dict) -> str:
            raise RuntimeError("model down")

        limited = ModelLimiter(max_concurrent=1, wait_seconds=0).wrap(boom)

        async def scenario() -> None:
            for _ in range(3):  # a leaked slot would make the 2nd try "busy"
                with pytest.raises(RuntimeError):
                    await limited("s", "u", {})

        run(scenario())

    def test_a_cancelled_call_gives_its_slot_back(self) -> None:
        slow, _ = tracked_call(hold=5)
        limited = ModelLimiter(max_concurrent=1, wait_seconds=0)
        slow_call = limited.wrap(slow)
        fast, _ = tracked_call(hold=0)
        fast_call = limited.wrap(fast)

        async def scenario() -> str:
            task = asyncio.create_task(slow_call("s", "u", {}))
            await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return await fast_call("s", "u", {})

        assert run(scenario()) == REPLY

    def test_it_can_be_reused_across_event_loops(self) -> None:
        call, _ = tracked_call(hold=0)
        limited = ModelLimiter(max_concurrent=1, wait_seconds=0.05).wrap(call)
        assert run(limited("s", "u", {})) == REPLY
        assert run(limited("s", "u", {})) == REPLY

    @pytest.mark.parametrize("args", [(0, 1), (-1, 1), (1, -0.5)])
    def test_invalid_settings_are_refused(self, args: tuple) -> None:
        with pytest.raises(ValueError):
            ModelLimiter(*args)


class TestSettings:
    def test_documented_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("REGISTRY_MODEL_MAX_CONCURRENCY", raising=False)
        monkeypatch.delenv("REGISTRY_MODEL_QUEUE_SECONDS", raising=False)
        limiter = ModelLimiter.from_env()
        assert limiter.max_concurrent == DEFAULT_MAX_CONCURRENT == 8
        assert limiter.wait_seconds == DEFAULT_WAIT_SECONDS == 2.0

    def test_settings_are_read_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_MODEL_MAX_CONCURRENCY", "3")
        monkeypatch.setenv("REGISTRY_MODEL_QUEUE_SECONDS", "1.5")
        limiter = ModelLimiter.from_env()
        assert (limiter.max_concurrent, limiter.wait_seconds) == (3, 1.5)

    @pytest.mark.parametrize("bad", ["0", "-2", "abc", "nan", "inf", "1000", ""])
    def test_bad_concurrency_falls_back_to_the_default(
        self, bad: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_MODEL_MAX_CONCURRENCY", bad)
        assert ModelLimiter.from_env().max_concurrent == DEFAULT_MAX_CONCURRENT

    @pytest.mark.parametrize("bad", ["-1", "abc", "nan", "inf", "3600"])
    def test_bad_wait_falls_back_to_the_default(
        self, bad: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_MODEL_QUEUE_SECONDS", bad)
        assert ModelLimiter.from_env().wait_seconds == DEFAULT_WAIT_SECONDS

    def test_zero_wait_is_a_valid_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REGISTRY_MODEL_QUEUE_SECONDS", "0")
        assert ModelLimiter.from_env().wait_seconds == 0


@pytest.fixture
def db(tmp_path: Path) -> Session:
    """A file database: these tests read it from several threads at once, which the
    shared in-memory connection used by the other registry tests cannot do safely."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'limits.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def gated_call():
    """A fake model that holds its slot until the test opens the gate."""
    entered, gate = asyncio.Event(), asyncio.Event()
    state = {"total": 0}

    async def call(system: str, user: str, schema: dict) -> str:
        state["total"] += 1
        entered.set()
        await gate.wait()
        return REPLY

    return call, entered, gate, state


class TestThroughTheA2AEndpoint:
    def test_a_burst_gets_a_clear_retryable_overload_reply(self, db: Session) -> None:
        add_agent(db, "math")
        call, entered, gate, state = gated_call()
        harness = Harness(db, call, limiter=ModelLimiter(1, 0.05))

        async def scenario() -> tuple[dict, list]:
            holder = asyncio.create_task(harness.ask("first"))
            await asyncio.wait_for(entered.wait(), 10)  # it now holds the only slot
            refused = await asyncio.gather(harness.ask("second"), harness.ask("third"))
            gate.set()
            _, answered = await holder
            return answered, [data for _, data in refused]

        answered, refused = run(scenario())
        assert answered["status"] == "no_match"
        for data in refused:
            assert data["status"] == "error"
            assert data["error"] == {"code": "selection_busy", "retryable": True}
            assert data["agent"] is None
        assert state["total"] == 1  # the refused requests never reached the model

    def test_a_request_gets_the_slot_once_it_is_free(self, db: Session) -> None:
        add_agent(db, "math")
        call, entered, gate, state = gated_call()
        harness = Harness(db, call, limiter=ModelLimiter(1, 10))

        async def scenario() -> list:
            first = asyncio.create_task(harness.ask("first"))
            await asyncio.wait_for(entered.wait(), 10)
            second = asyncio.create_task(harness.ask("second"))  # waits for the slot
            await asyncio.sleep(0.1)
            gate.set()
            return [data for _, data in await asyncio.gather(first, second)]

        replies = run(scenario())
        assert [d["status"] for d in replies] == ["no_match", "no_match"]
        assert state["total"] == 2

    def test_requests_within_the_limit_all_succeed(self, db: Session) -> None:
        add_agent(db, "math")
        call, state = tracked_call(hold=0.05)
        harness = Harness(db, call, limiter=ModelLimiter(2, 10))

        async def scenario() -> list:
            return await asyncio.gather(*(harness.ask(f"q{i}") for i in range(4)))

        replies = [data for _, data in run(scenario())]
        assert [d["status"] for d in replies] == ["no_match"] * 4
        assert state["peak"] <= 2

    def test_the_environment_limits_apply_when_no_limiter_is_given(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_agent(db, "math")
        monkeypatch.setenv("REGISTRY_MODEL_MAX_CONCURRENCY", "1")
        monkeypatch.setenv("REGISTRY_MODEL_QUEUE_SECONDS", "0")
        call, entered, gate, _ = gated_call()
        harness = Harness(db, call)

        async def scenario() -> tuple[dict, dict]:
            holder = asyncio.create_task(harness.ask("first"))
            await asyncio.wait_for(entered.wait(), 10)
            _, refused = await harness.ask("second")
            gate.set()
            _, answered = await holder
            return answered, refused

        answered, refused = run(scenario())
        assert answered["status"] == "no_match"
        assert refused["error"] == {"code": "selection_busy", "retryable": True}
