import threading
from functools import wraps
from typing import Callable, List, Any

from .interpreter import Interpreter
from sismic import model


def log_trace(interpreter: Interpreter) -> List[model.MacroStep]:
    """
    Return a list that will be populated by each value returned by the *execute_once* method
    of given interpreter.

    :param interpreter: an *Interpreter* instance
    :return: a list of *MacroStep*
    """
    func = interpreter.execute_once  # type: Callable[[], model.MacroStep]
    trace = []

    @wraps(func)
    def new_func():
        step = func()
        if step:
            trace.append(step)
        return step

    interpreter.execute_once = new_func  # type: ignore
    return trace


def run_in_background(interpreter: Interpreter,
                      delay: float=0.05,
                      callback: Callable[[List[model.MacroStep]], Any]=None) -> threading.Thread:
    """
    Run given interpreter in background. The time is updated according to
    *time.time() - starttime*. The interpreter is ran until it reaches a final configuration.
    You can manually stop the thread using the added *stop* of the returned Thread object.
    This is for convenience only and should be avoided, because a call to *stop* puts the interpreter in
    an empty (and thus final) configuration, without properly leaving the active states.

    :param interpreter: an interpreter
    :param delay: delay between each call to *execute()*
    :param callback: a function that accepts the result of *execute*.
    :return: started thread (instance of *threading.Thread*)
    """
    import time

    def _task():
        starttime = time.time()
        while not interpreter.final:
            interpreter.time = time.time() - starttime
            steps = interpreter.execute()
            if callback:
                callback(steps)
            time.sleep(delay)
    thread = threading.Thread(target=_task)

    def stop_thread():
        interpreter._configuration = set()

    thread.stop = stop_thread  # type: ignore

    thread.start()
    return thread