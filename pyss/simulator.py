from pyss import statemachine
from pyss.evaluator import Evaluator, DummyEvaluator


class Step:
    def __init__(self, event: statemachine.Event, transition: statemachine.Transition,
                 entered_states: list, exited_states: list):
        """
        Create a step. A step consider `event`, takes `transition` and results in a list
        of `entered_states` and a list of `exited_states`.
        Order in the two lists is REALLY important!
        :param event: Event or None in case of eventless transition
        :param transition: Transition or None if no matching transition
        :param entered_states: possibly empty list of entered states
        :param exited_states: possibly empty list of exited states
        """
        self.event = event
        self.transition = transition
        self.entered_states = entered_states
        self.exited_states = exited_states

    def __repr__(self):
        return 'Step({}, {}, {}, {})'.format(self.event, self.transition, self.entered_states, self.exited_states)


class Simulator:
    """
    Use case:
    >>> simulator = Simulator(sm)
    >>> assert(simulator.running == False)
    >>> simulator.start()
    >>> assert(simulator.running == True)
    >>> simulator.fire_event(Event('click'))
    >>> for step in simulator:
            print(step)
    >>> assert(simulator.running == False)
    """

    def __init__(self, sm: statemachine.StateMachine, evaluator: Evaluator=None):
        """
        A simulator that interprets a state machine according to a specific semantic.
        :param sm: state machine to interpret
        :param evaluator: Code evaluator (optional)
        """
        self._evaluator = evaluator if evaluator else DummyEvaluator()
        self._sm = sm
        self._configuration = set()  # Set of active states
        self._events = []  # Event queue

    @property
    def configuration(self) -> list:
        return list(self._configuration)

    @property
    def events(self) -> list:
        return self._events

    def start(self) -> list:
        """
        Make this machine runnable:
         - Execute state machine initial code
         - Execute until a stable situation is reached.
        :return A (possibly empty) list of executed Step.
        """
        # Initialize state machine
        if self._sm.on_entry:
            self._evaluator.execute_action(self._sm.on_entry)

        # Initial step and stabilization
        step = Step(None, None, [self._sm.initial], [])
        self._execute_step(step)
        return [step] + self._stabilize()

    @property
    def running(self) -> bool:
        """
        Return True iff state machine is running.
        """
        for state in self._sm.leaf_for(list(self._configuration)):
            if not isinstance(self._sm.states[state], statemachine.FinalState):
                return True
        return False

    def fire_event(self, event: statemachine.Event):
        self._events.append(event)

    def __iter__(self):
        """
        Return an iterator for current execution.
        It corresponds to successive call to execute().
        There is no need to manually start() this executor.
        Event can be added using iterator.send().
        """
        if not self.running:
            self.start()

        consecutive_null_steps = 0
        while self.running:
            step = self.execute()
            consecutive_null_steps = 0 if step else consecutive_null_steps + 1
            if consecutive_null_steps >= 42:
                raise RuntimeError('Possible infinite run detected')
            event = yield step
            if event:
                self.fire_event(event)
        raise StopIteration()

    def execute(self) -> list:
        """
        Execute an eventless transition or an evented transition and put the
        state machine in a stable state.
        Return a list of executed Step instances.
        """
        steps = []

        # Try eventless transitions
        step = self._transition_step(event=None)  # Explicit is better than implicit

        if not step and len(self._events) > 0:
            event = self._events.pop(0)
            step = self._transition_step(event=event)
            if not step:
                steps.append(Step(event, None, [], []))

        if step:
            steps.append(step)
            self._execute_step(step)

        # Stabilization
        return steps + self._stabilize()

    def _actionable_transitions(self, event: statemachine.Event=None) -> list:
        """
        Return a list of transitions that can be actioned wrt.
        the current configuration. The list is ordered: deepest states first.
        :param event: Event to considered or None for eventless transitions
        :return: A (possibly empty) ordered list of Transition instances
        """
        transitions = []
        for transition in self._sm.transitions:
            if transition.event != event:
                continue
            if transition.from_state not in self._configuration:
                continue
            if transition.condition is None or self._evaluator.evaluate_condition(transition.condition, event):
                transitions.append(transition)

        # Order by deepest first
        return sorted(transitions, key=lambda t: self._sm.depth_of(t.from_state), reverse=True)

    def _stabilize_step(self) -> Step:
        """
        Return a stabilization step, ie. a step that lead to a more stable situation
        for the current state machine (expand to initial state, expand to history state, etc.).
        :return: A Step instance or None if this state machine can not be stabilized
        """
        # Check if we are in a set of "stable" states
        leaves = self._sm.leaf_for(list(self._configuration))
        for leaf in leaves:
            leaf = self._sm.states[leaf]
            if isinstance(leaf, statemachine.HistoryState):
                states_to_enter = leaf.memory
                states_to_enter.sort(key=lambda x: self._sm.depth_of(x))
                return Step(None, None, states_to_enter, [leaf.name])
            elif isinstance(leaf, statemachine.OrthogonalState):
                return Step(None, None, leaf.children, [])
            elif isinstance(leaf, statemachine.CompoundState):
                return Step(None, None, [leaf.initial], [])

    def _stabilize(self) -> list:
        """
        Compute, apply and return stabilization steps.
        :return: A list of Step instances
        """
        # Stabilization
        steps = []
        step = self._stabilize_step()
        while step:
            steps.append(step)
            self._execute_step(step)
            step = self._stabilize_step()
        return steps

    def _transition_step(self, event: statemachine.Event=None) -> Step:
        """
        Return the Step (if any) associated with the appropriate transition matching
        given event (or eventless transition if event is None).
        :param event: Event to consider (or None)
        :return: A Step instance or None
        """
        transitions = self._actionable_transitions(event)

        if len(transitions) == 0:
            return None

        # TODO: Check there is at most one transition for selected depth
        transition = transitions[0]

        # Internal transition
        if transition.to_state is None:
            return Step(event, transition, [], [])

        lca = self._sm.least_common_ancestor(transition.from_state, transition.to_state)
        from_ancestors = self._sm.ancestors_for(transition.from_state)
        to_ancestors = self._sm.ancestors_for(transition.to_state)

        exited_states = [transition.from_state]
        for state in from_ancestors:
            if state == lca:
                break
            exited_states.append(state)

        entered_states = [transition.to_state]
        for state in to_ancestors:
            if state == lca:
                break
            entered_states.insert(0, state)

        return Step(event, transition, entered_states, exited_states)

    def _execute_step(self, step: Step):
        """
        Apply given Step on this state machine
        :param step: Step instance
        """
        entered_states = map(lambda s: self._sm.states[s], step.entered_states)
        exited_states = map(lambda s: self._sm.states[s], step.exited_states)

        for state in exited_states:
            # Execute exit action
            if isinstance(state, statemachine.ActionStateMixin) and state.on_exit:
                self._evaluator.execute_action(state.on_exit)

        # Deal with history: this only concerns compound states
        for state in filter(lambda s: isinstance(s, statemachine.CompoundState), exited_states):
            # Look for an HistoryState among its children
            for child_name in state.children:
                child = self._sm.states[child_name]
                if isinstance(child, statemachine.HistoryState):
                    if child.deep:
                        # This MUST contain at least one element!
                        active = self._configuration.intersection(self._sm.descendants_for(state.name))
                        assert len(active) >= 1
                        child.memory = list(active)
                    else:
                        # This MUST contain exactly one element!
                        active = self._configuration.intersection(state.children)
                        assert len(active) == 1
                        child.memory = list(active)

        # Remove states from configuration
        self._configuration = self._configuration.difference(step.exited_states)

        # Execute transition
        if step.transition and step.transition.action:
            self._evaluator.execute_action(step.transition.action, step.transition.event)

        for state in entered_states:
            # Execute entry action
            if isinstance(state, statemachine.ActionStateMixin) and state.on_entry:
                self._evaluator.execute_action(state.on_entry)

        # Add state to configuration
        self._configuration = self._configuration.union(step.entered_states)

    def __repr__(self):
        return '{}[{}]'.format(self.__class__.__name__, ' '.join(self._configuration))

