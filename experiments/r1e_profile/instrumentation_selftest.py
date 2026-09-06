"""Test only stdlib profiling hooks on neutral arithmetic, not a strategy run."""
import cProfile
import pstats
import sys


class Stop(BaseException):
    pass


def arithmetic(value):
    return value + 1


def subject():
    for value in range(3):
        arithmetic(value)


def main():
    seen = []
    profiler = cProfile.Profile()
    monitor = sys.monitoring
    if monitor.get_tool(5) is not None:
        raise RuntimeError("Tool 5 occupied")

    def on_line(code, line):
        assert sys._getframe(1).f_code is subject.__code__
        profiler.disable()
        profiler.enable()

    def on_start(code, offset):
        frame = sys._getframe(1)
        assert frame.f_code is arithmetic.__code__
        seen.append(frame.f_locals["value"])
        if len(seen) == 2:
            raise Stop()

    monitor.use_tool_id(5, "neutral_selftest")
    monitor.register_callback(5, monitor.events.LINE, on_line)
    monitor.register_callback(5, monitor.events.PY_START, on_start)
    monitor.set_local_events(5, subject.__code__, monitor.events.LINE)
    monitor.set_local_events(5, arithmetic.__code__, monitor.events.PY_START)
    profiler.enable()
    caught = False
    try:
        subject()
    except Stop:
        caught = True
    finally:
        profiler.disable()
        monitor.set_local_events(5, subject.__code__, 0)
        monitor.set_local_events(5, arithmetic.__code__, 0)
        monitor.register_callback(5, monitor.events.LINE, None)
        monitor.register_callback(5, monitor.events.PY_START, None)
        monitor.free_tool_id(5)
    assert caught and seen == [0, 1]
    assert pstats.Stats(profiler).total_calls > 0
    assert monitor.get_tool(5) is None
    print("PASS: frame identity, arguments, cProfile switching, BaseException stop, hook cleanup; no strategy executed")


if __name__ == "__main__":
    main()
